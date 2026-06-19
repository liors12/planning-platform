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
import time
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
_STARTED_AT_MONOTONIC = time.monotonic()


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
# /diagnostics — single-call health report
# Returns a structured snapshot of every check the UI's "system status" panel
# needs: sidecar up, DB connected, seed files on disk, weasyprint present,
# render+excel readiness. Aggregates per-project file checks so a missing seed
# file surfaces as a specific error string instead of a silent "render failed
# at run time" later. No auth — local 127.0.0.1 binding (spec § 8).
# ─────────────────────────────────────────────────────────────────────────────


def _check_file(path: Path) -> dict:
    return {"path": str(path), "exists": path.exists()}


def _resolve_weasyprint_path() -> dict:
    """Reproduces compliance_engine.report_generator._resolve_weasyprint_exe
    without importing it (avoids loading the engine for a healthcheck).
    Same lookup order: env var → exe_dir/weasyprint → exe_dir.parent/weasyprint.
    """
    env_path = os.environ.get("WEASYPRINT_EXE_PATH")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return {"path": str(p), "exists": True}
    exe_dir = Path(sys.executable).resolve().parent
    candidates = [
        exe_dir / "weasyprint" / "weasyprint.exe",
        exe_dir.parent / "weasyprint" / "weasyprint.exe",
    ]
    for c in candidates:
        if c.is_file():
            return {"path": str(c), "exists": True}
    # Report the most-likely Tauri-layout path so the error is actionable.
    return {"path": str(candidates[1]), "exists": False}


def _audit_results_for(tava: str, version: str) -> Path | None:
    out_dir = CFG.data_dir / "audit_outputs" / tava / f"v{version}"
    for leaf in ("audit_results.m4.sanitized.json", "audit_results.m4.json"):
        p = out_dir / leaf
        if p.exists():
            return p
    return None


@app.get("/diagnostics")
def diagnostics() -> dict:
    errors: list[str] = []

    # ── sidecar ──────────────────────────────────────────────────────────
    sidecar_block = {
        "running": True,
        "uptime_seconds": int(time.monotonic() - _STARTED_AT_MONOTONIC),
        "port": CFG.bind_port,
    }

    # ── db ───────────────────────────────────────────────────────────────
    db_connected = False
    # `backend` is derived from db.py's _BACKEND_NAME at import time
    # ("sqlcipher" or "sqlite3"); DB_STATUS only captures runtime PRAGMA
    # output, so check the SQLAlchemy URL dialect for a stable read.
    backend_name = ENGINE.dialect.name  # "sqlite" for both backends
    db_block = {
        "connected": False,
        "backend": backend_name,
        "encrypted": bool(DB_STATUS.get("cipher_version")),
        "path": str(CFG.db_path),
    }
    try:
        with ENGINE.begin() as conn:
            conn.execute(text("SELECT 1"))
        db_connected = True
        db_block["connected"] = True
    except Exception as exc:
        errors.append(f"DB connection failed: {exc}")

    # ── projects ─────────────────────────────────────────────────────────
    project_count = 0
    project_names: list[str] = []
    project_rows: list = []
    if db_connected:
        try:
            with Session(ENGINE) as sess:
                project_rows = (
                    sess.query(Project)
                        .filter(Project.status != "archived")
                        .all()
                )
                project_count = len(project_rows)
                project_names = [p.name_he for p in project_rows]
        except Exception as exc:
            errors.append(f"failed to read projects: {exc}")

    # ── seed files (for the first project, if any) ───────────────────────
    # Aggregated readiness over ALL projects is computed below; this block
    # gives the UI concrete paths to display.
    seed_block: dict = {
        "schema_file":        {"path": None, "exists": False},
        "metadata_file":      {"path": None, "exists": False},
        "audit_results_file": {"path": None, "exists": False},
    }
    if project_rows:
        first = project_rows[0]
        tava = first.tava_number
        proj_dir = CFG.data_dir / "projects" / tava
        schema_p = proj_dir / f"project-schema-{tava}-v2.json"
        seed_block["schema_file"] = _check_file(schema_p)
        if not schema_p.exists():
            errors.append(f"schema missing for {tava} at {schema_p}")
        # Pick whichever submission version has metadata.json on disk; the
        # seed ships v24.3, but new uploads create their own dirs.
        subs_root = proj_dir / "submissions"
        if subs_root.exists():
            for sub_dir in sorted(subs_root.iterdir()):
                meta = sub_dir / "metadata.json"
                if meta.exists():
                    seed_block["metadata_file"] = _check_file(meta)
                    audit = _audit_results_for(tava, sub_dir.name.lstrip("v"))
                    if audit:
                        seed_block["audit_results_file"] = _check_file(audit)
                    break
        if not seed_block["metadata_file"]["exists"]:
            errors.append(f"no submission metadata.json found under {subs_root}")
        if not seed_block["audit_results_file"]["exists"]:
            errors.append(f"no audit_results found for {tava}")

    # ── weasyprint ───────────────────────────────────────────────────────
    weasy_block = _resolve_weasyprint_path()
    if not weasy_block["exists"]:
        errors.append(f"weasyprint.exe not found at {weasy_block['path']}")

    # ── readiness ────────────────────────────────────────────────────────
    any_audit_results = False
    if project_rows:
        for p in project_rows:
            for sub_dir in (CFG.data_dir / "projects" / p.tava_number
                            / "submissions").glob("v*"):
                if _audit_results_for(p.tava_number, sub_dir.name.lstrip("v")):
                    any_audit_results = True
                    break
            if any_audit_results:
                break
    excel_ready = any_audit_results
    render_ready = any_audit_results and weasy_block["exists"]

    # ── overall status ───────────────────────────────────────────────────
    if not db_connected:
        status = "error"
    elif errors:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "sidecar": sidecar_block,
        "db": db_block,
        "seed": seed_block,
        "projects": {"count": project_count, "names": project_names},
        "weasyprint": weasy_block,
        "render_ready": render_ready,
        "excel_ready": excel_ready,
        "errors": errors,
    }


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
