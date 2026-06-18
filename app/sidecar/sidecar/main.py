"""FastAPI sidecar — entry point for the desktop app's backend.

Responsibilities (Phase 2a):
  * Bind 127.0.0.1 only — explicitly rejects 0.0.0.0 (spec § 8 + ADR-001).
  * Open the SQLCipher-encrypted SQLite DB with WAL mode.
  * Expose /health for the Tauri shell + React UI to verify liveness.
  * Expose /jobs/echo as the day-1 proof of subprocess isolation (ADR-001).
  * Expose /projects (CRUD-ish: POST, GET, GET-by-id, PATCH, /archive).
  * Expose /projects/{id}/submissions (POST multipart upload, GET list).
  * Expose /submissions/{id} (GET, /run-engine, /findings).
  * Expose /jobs/{id} (GET status of queued engine jobs).
  * Run a single-worker engine queue (MAX_CONCURRENT_JOBS=1) that pulls
    Job UUIDs from an asyncio.Queue and shells out via the engine bridge.

NOT in scope here (Phase 2b+):
  * pdf.js viewer, guidelines editor, discipline feedback grid, final document
    generation. All Phase 3+ work.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .comments import make_routers as make_comment_routers
from .config import VERSION, Config, load
from .db import build_engine, initialize
from .jobs.dispatch import JobError, run_job
from .jobs_routes import make_router as make_jobs_router
from .models import Project
from .projects import make_router as make_projects_router
from .queue_worker import EngineQueue
from .submissions import make_routers as make_submission_routers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("sidecar")


CFG = load()
ENGINE = build_engine(CFG.db_path, CFG.db_key)
DB_STATUS: dict = {}
QUEUE = EngineQueue(cfg=CFG, engine=ENGINE)


# ─────────────────────────────────────────────────────────────────────────────
# First-run seed
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_seed_dir() -> Path | None:
    """Locate the bundled seed/ directory, PyInstaller-aware.

    Frozen: seed/ ships inside _MEIPASS (see backend.spec `datas=("seed",
    "seed")`). Dev: seed/ lives at app/sidecar/seed/ next to backend.spec.
    Returns None if the seed tree isn't present (dev with seed absent →
    no-op; production builds always include it).
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            cand = Path(meipass) / "seed"
            return cand if cand.exists() else None
    # Dev: app/sidecar/seed/, relative to this file (sidecar/main.py)
    cand = Path(__file__).resolve().parent.parent / "seed"
    return cand if cand.exists() else None


def _seed_data_dir(cfg: Config) -> dict:
    """Copy the bundled pilot seed into cfg.data_dir if it's not already there.

    Idempotent: only copies files whose destinations don't exist. Never
    overwrites user data. Returns a small report dict for the startup log.
    """
    seed_dir = _resolve_seed_dir()
    if seed_dir is None:
        return {"seed_dir": None, "copied": 0, "skipped_existing": 0}

    copied = 0
    skipped = 0
    for src in seed_dir.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(seed_dir)
        dst = cfg.data_dir / rel
        if dst.exists():
            skipped += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    return {"seed_dir": str(seed_dir), "copied": copied,
            "skipped_existing": skipped}


def _discover_projects(cfg: Config, engine: Engine) -> dict:
    """Reconcile DB project rows with `<data_dir>/projects/*/_project.json`.

    For each `_project.json` found on disk:
      - If no row exists with that tava_number → INSERT a fresh row.
      - If a row exists → UPDATE name_he / name_en / status in-place
        whenever the JSON provides a non-empty value that differs from
        the DB. This "heals" a manually-created project to match the
        canonical descriptor once the seed lands next to it, without
        ever clobbering UI edits with empty JSON fields.

    Returns {"discovered": N, "inserted": M, "updated": U, "skipped_unchanged": S}.
    """
    projects_root = cfg.data_dir / "projects"
    if not projects_root.exists():
        return {"discovered": 0, "inserted": 0, "updated": 0,
                "skipped_unchanged": 0}

    discovered = inserted = updated = skipped = 0
    with Session(engine) as sess:
        for proj_dir in sorted(projects_root.iterdir()):
            if not proj_dir.is_dir():
                continue
            descriptor = proj_dir / "_project.json"
            if not descriptor.exists():
                continue
            discovered += 1
            try:
                payload = json.loads(descriptor.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("skip %s: unreadable _project.json (%s)",
                            descriptor, exc)
                continue
            tava = payload.get("tava_number")
            name_he = payload.get("name_he")
            if not tava or not name_he:
                log.warning("skip %s: _project.json missing tava_number or name_he",
                            descriptor)
                continue
            existing = (sess.query(Project)
                            .filter(Project.tava_number == tava,
                                    Project.status != "archived")
                            .first())
            if existing is None:
                sess.add(Project(
                    tava_number=tava,
                    name_he=name_he,
                    name_en=payload.get("name_en"),
                    address=payload.get("address"),
                    status=payload.get("status") or "active",
                ))
                inserted += 1
                continue
            # Heal: overwrite only when JSON provides a non-empty value
            # that differs from the DB. Empty/missing JSON fields never
            # clobber values the user typed in the UI.
            changed = False
            for field, json_val in (
                ("name_he", name_he),
                ("name_en", payload.get("name_en")),
                ("status", payload.get("status")),
            ):
                if json_val and getattr(existing, field) != json_val:
                    setattr(existing, field, json_val)
                    changed = True
            if changed:
                updated += 1
            else:
                skipped += 1
        if inserted or updated:
            sess.commit()
    return {"discovered": discovered, "inserted": inserted,
            "updated": updated, "skipped_unchanged": skipped}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global DB_STATUS
    DB_STATUS = initialize(ENGINE)
    seed_report = _seed_data_dir(CFG)
    discovery_report = _discover_projects(CFG, ENGINE)
    log.info("sidecar starting on http://%s:%d "
             "(data_dir=%s, db=%s, seed=%s, projects=%s)",
             CFG.bind_host, CFG.bind_port, CFG.data_dir,
             DB_STATUS, seed_report, discovery_report)
    await QUEUE.start()
    yield
    await QUEUE.stop()
    ENGINE.dispose()
    log.info("sidecar shutting down")


app = FastAPI(
    title="Municipal Compliance Platform — sidecar",
    version=VERSION,
    lifespan=lifespan,
)

# CORS: the Tauri WebView origin + the Vite dev server. Localhost only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "tauri://localhost",          # Tauri v2 packaged WebView
        "http://tauri.localhost",     # alt form on some macOS versions
        "http://127.0.0.1:1420",      # Vite dev server (set in tauri.conf.json)
        "http://localhost:1420",
    ],
    # PATCH for project edits; multipart upload is POST so that's covered.
    # HEAD for pdf.js Range preflight on /submissions/{id}/pdf.
    # DELETE for Phase 2b Module D — discipline comment removal.
    allow_methods=["GET", "HEAD", "POST", "PATCH", "DELETE"],
    # Range is not a CORS-safelisted request header, so it triggers preflight
    # — allow it. Without this, react-pdf cannot send Range:bytes=... and
    # falls back to downloading the entire PDF before showing page 1.
    allow_headers=["Content-Type", "Range"],
    # Expose response headers that pdf.js reads to decide whether to use
    # byte-range fetching.
    expose_headers=["Accept-Ranges", "Content-Range", "Content-Length"],
)


# ─────────────────────────────────────────────────────────────────────────────
# /health
# ─────────────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    sidecar_version: str
    bind: str
    db: dict
    data_dir: str
    max_concurrent_jobs: int


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness + DB sanity."""
    with ENGINE.begin() as conn:
        meta = conn.execute(text(
            "SELECT schema_version, sidecar_version, last_started_at FROM app_metadata WHERE id=1"
        )).mappings().first()
    db_report = {
        **DB_STATUS,
        "schema_version": meta["schema_version"] if meta else None,
        "last_started_at": meta["last_started_at"] if meta else None,
    }
    return HealthResponse(
        status="ok",
        sidecar_version=VERSION,
        bind=f"{CFG.bind_host}:{CFG.bind_port}",
        db=db_report,
        data_dir=str(CFG.data_dir),
        max_concurrent_jobs=CFG.max_concurrent_jobs,
    )


# ─────────────────────────────────────────────────────────────────────────────
# /jobs/echo — Phase 1 proof of subprocess isolation (ADR-001)
# Declared BEFORE the /jobs router so the literal "echo" path wins over the
# parameterized "/{job_id}" route.
# ─────────────────────────────────────────────────────────────────────────────

class EchoRequest(BaseModel):
    message: str
    extra: dict | None = None


class EchoResponse(BaseModel):
    job_id: str
    duration_s: float
    output: dict


@app.post("/jobs/echo", response_model=EchoResponse)
def echo(req: EchoRequest) -> EchoResponse:
    try:
        result = run_job(
            cfg=CFG,
            job_type="echo",
            worker_module="sidecar.jobs.echo_worker",
            input_payload=req.model_dump(),
            timeout_s=10.0,
        )
    except JobError as exc:
        log.exception("echo job failed")
        raise HTTPException(status_code=500, detail=str(exc))
    return EchoResponse(
        job_id=result.job_id,
        duration_s=round(result.duration_s, 3),
        output=result.output,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Mount module routers
# ─────────────────────────────────────────────────────────────────────────────

app.include_router(make_projects_router(lambda: ENGINE))

_projects_subs_router, _subs_router = make_submission_routers(
    lambda: ENGINE, cfg=CFG, queue=QUEUE,
)
app.include_router(_projects_subs_router)
app.include_router(_subs_router)
app.include_router(make_jobs_router(QUEUE))

# Phase 2b Module D — discipline comments + render trigger.
_comments_router, _disciplines_router = make_comment_routers(ENGINE, QUEUE, CFG)
app.include_router(_comments_router)
app.include_router(_disciplines_router)


# ─────────────────────────────────────────────────────────────────────────────
# uvicorn entry point — used by Tauri to spawn the sidecar
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    import uvicorn
    # Pass the app OBJECT, not "sidecar.main:app" as a string. The string form
    # makes uvicorn re-import the module — which, when launched via
    # `python -m sidecar.main`, creates a second module instance ALONGSIDE
    # `__main__`. Each instance has its own QUEUE singleton; the lifespan
    # starts one and the route handlers reference the other. Passing `app`
    # directly preserves the single-instance invariant.
    uvicorn.run(
        app,
        host=CFG.bind_host,
        port=CFG.bind_port,
        log_level="info",
        reload=False,
        workers=1,
    )


if __name__ == "__main__":
    main()
