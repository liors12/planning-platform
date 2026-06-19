"""Engine job queue + worker — Phase 2a.

Implements MAX_CONCURRENT_JOBS=1 by running a single asyncio background task
that pulls Job UUIDs off a FIFO queue and processes them sequentially. Jobs
are persisted to the DB so the UI can show "queued / running / completed /
failed" status that survives sidecar restarts (orphaned jobs from a previous
process are marked failed at startup).

ADR-001 § Implication 2 (concurrency cap of 1) lands here. The synchronous
`dispatch.run_job()` helper from Phase 1 (used by /jobs/echo) still exists
for one-shot demos that don't need queueing; the queue is for real
long-running engine work that the UI polls.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .config import Config
from .engine_bridge import resolve_schema
from .models import DisciplineComment, Job, Submission
from .storage import findings_path
from sqlalchemy import select

log = logging.getLogger(__name__)


# Wall-clock budget per docs/architecture/job_types.md `run_audit` row.
RUN_AUDIT_BUDGET_S = 300.0

# Phase 2b — render-only path skips M1-M4 (~2 sec WeasyPrint pass) but keep a
# generous budget for cold cache / large reports.
RENDER_BUDGET_S = 60.0

# Path to the run_audit script. Resolved at module-load so we don't recompute
# per job. Lives at <REPO_ROOT>/scripts/run_audit.py.
_RUN_AUDIT_PATH = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "run_audit.py"


def _normalize_submission_version(version_string: str) -> str:
    """The engine's submission_version is the bare version without 'v' prefix.
    The platform's storage uses whatever the user typed (commonly 'v24.3'),
    so we strip a leading 'v' here when handing off to the engine.
    Mirror of the deleted engine_bridge._normalize_submission_version."""
    return version_string[1:] if version_string.startswith("v") else version_string


def engine_run_available() -> bool:
    """Whether the full-audit subprocess path (_process_one → run_audit.py)
    can actually execute on this machine.

    The subprocess path spawns `cfg.sidecar_python` — which defaults to
    `/opt/homebrew/bin/python3.13` (macOS Homebrew) when PLATFORM_PYTHON
    isn't set. On a PyInstaller-frozen Windows install there's no
    external Python interpreter, that path doesn't exist, and
    `subprocess.run` raises FileNotFoundError [WinError 2]. The render-
    only path already has a win32+frozen in-process branch
    (_process_render_pdf); _process_one does not. Until it does, the
    "הפעילי את התוכנה" button cannot succeed in the Windows package.

    Returns False precisely when the subprocess path would 100% fail
    pre-flight. macOS dev and non-frozen runs are unaffected."""
    return not (sys.platform == "win32" and getattr(sys, "frozen", False))


class EngineQueue:
    """A single-worker FIFO queue. One instance per sidecar process.

    Cross-thread enqueue is supported (FastAPI sync endpoints run in a
    threadpool while the worker awaits in the event loop): we capture the
    event-loop reference at start() and route `put` calls via
    `asyncio.run_coroutine_threadsafe`. Without this, `put_nowait` from a
    different thread silently corrupts pending getter futures.
    """

    def __init__(self, *, cfg: Config, engine: Engine) -> None:
        self._cfg = cfg
        self._engine = engine
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self) -> None:
        """Launch the background worker. Idempotent; safe to call once at
        sidecar startup."""
        if self._worker_task is None or self._worker_task.done():
            self._loop = asyncio.get_running_loop()
            self._mark_orphans_failed()
            self._worker_task = asyncio.create_task(self._run_worker(),
                                                    name="engine-queue-worker")
            log.info("engine queue worker started")

    async def stop(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except (asyncio.CancelledError, Exception):
                pass
        log.info("engine queue worker stopped")

    def enqueue_run_audit(self, submission_id: int) -> Job:
        """Insert a Job row and put its id on the queue. Returns the row."""
        with Session(self._engine) as sess:
            sub = sess.get(Submission, submission_id)
            if sub is None:
                raise ValueError(f"submission {submission_id} not found")
            job_id = str(uuid.uuid4())
            job_dir = self._cfg.jobs_dir / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            job = Job(
                id=job_id,
                job_type="run_audit",
                submission_id=submission_id,
                status="queued",
                job_dir=str(job_dir),
            )
            # Mark submission as analyzing so the UI can show that state even
            # before the worker picks the job up (could be moments later).
            sub.status = "analyzing"
            sess.add(job)
            sess.commit()
            sess.refresh(job)
            # Cross-thread-safe: schedule the put on the worker's event loop.
            if self._loop is None:
                raise RuntimeError("EngineQueue.start() was not called")
            asyncio.run_coroutine_threadsafe(self._queue.put(job_id), self._loop)
            log.info("enqueued job %s for submission %s", job_id, submission_id)
            return job

    def enqueue_excel(self, submission_id: int) -> Job:
        """Queue an architect-response Excel export. Fast (~1-2s), no
        subprocess. Submission status is NOT changed."""
        with Session(self._engine) as sess:
            sub = sess.get(Submission, submission_id)
            if sub is None:
                raise ValueError(f"submission {submission_id} not found")
            job_id = str(uuid.uuid4())
            job_dir = self._cfg.jobs_dir / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            job = Job(
                id=job_id,
                job_type="export_excel",
                submission_id=submission_id,
                status="queued",
                job_dir=str(job_dir),
            )
            sess.add(job)
            sess.commit()
            sess.refresh(job)
            if self._loop is None:
                raise RuntimeError("EngineQueue.start() was not called")
            asyncio.run_coroutine_threadsafe(self._queue.put(job_id), self._loop)
            log.info("enqueued excel job %s for submission %s",
                     job_id, submission_id)
            return job

    def enqueue_render(self, submission_id: int) -> Job:
        """Phase 2b Module D: queue a --render-only re-render that merges
        the submission's current discipline_comments into the PDF.

        Unlike enqueue_run_audit, the submission status is NOT flipped to
        'analyzing' — re-rendering does not change the underlying analysis.
        """
        with Session(self._engine) as sess:
            sub = sess.get(Submission, submission_id)
            if sub is None:
                raise ValueError(f"submission {submission_id} not found")
            job_id = str(uuid.uuid4())
            job_dir = self._cfg.jobs_dir / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            job = Job(
                id=job_id,
                job_type="render_pdf",
                submission_id=submission_id,
                status="queued",
                job_dir=str(job_dir),
            )
            sess.add(job)
            sess.commit()
            sess.refresh(job)
            if self._loop is None:
                raise RuntimeError("EngineQueue.start() was not called")
            asyncio.run_coroutine_threadsafe(self._queue.put(job_id), self._loop)
            log.info("enqueued render job %s for submission %s",
                     job_id, submission_id)
            return job

    def get_job(self, job_id: str) -> Optional[Job]:
        with Session(self._engine) as sess:
            return sess.get(Job, job_id)

    # ── internal worker loop ───────────────────────────────────────────────

    async def _run_worker(self) -> None:
        while True:
            try:
                job_id = await self._queue.get()
                await asyncio.to_thread(self._process_one, job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("worker loop crashed; continuing")

    def _process_one(self, job_id: str) -> None:
        """Synchronous job execution (runs in a thread). Catches every
        exception and persists the result."""
        # Capture plain values inside the session — ORM instances become
        # detached when the `with` block exits, and the heavy subprocess.run
        # work below has to happen outside the session.
        with Session(self._engine) as sess:
            job = sess.get(Job, job_id)
            if job is None:
                log.error("job %s pulled from queue but missing from DB", job_id)
                return
            sub = sess.get(Submission, job.submission_id) if job.submission_id else None
            if sub is None:
                self._fail(sess, job, error_type="MissingSubmission",
                           error_message=f"submission {job.submission_id} not found at job-pickup time")
                return
            # Capture EVERY field we'll need after session close. SQLAlchemy's
            # default expire_on_commit=True blanks all instance attributes at
            # commit; once the `with` block exits, any access on the detached
            # `sub` raises DetachedInstanceError. Caught a real-world hang here:
            # `sub.id` accessed below the commit kept render jobs stuck at
            # "running" forever because the worker raised before persist.
            submission_id_local = sub.id
            project_id = sub.project_id
            project_tava_number = sub.project.tava_number
            submission_version_string = sub.version_string
            submission_pdf_path = sub.pdf_path
            job_type = job.job_type
            job_dir_str = job.job_dir
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            sess.commit()

        if job_type == "render_pdf":
            self._process_render_pdf(
                job_id=job_id,
                submission_id=submission_id_local,
                project_tava_number=project_tava_number,
                submission_version_string=submission_version_string,
                job_dir_str=job_dir_str,
            )
            return

        if job_type == "export_excel":
            self._process_export_excel(
                job_id=job_id,
                project_tava_number=project_tava_number,
                submission_version_string=submission_version_string,
            )
            return

        # Heavy work happens outside the session (subprocess.run blocks).
        # Phase 2b: write job_input.json with platform paths and spawn
        # `run_audit.py --job-dir DIR`. Engine reads inputs from disk, writes
        # job_output.json, exits. No legacy-layout copying.
        error_payload = None
        try:
            schema_path = resolve_schema(project_tava_number)
            job_dir = Path(job_dir_str)
            job_input = {
                "pdf_path": submission_pdf_path,
                "schema_path": str(schema_path),
                "project_key": project_tava_number,
                "submission_version": _normalize_submission_version(submission_version_string),
            }
            # Phase 2b: the Cowork-extracted overlays (extracts.json +
            # discipline_findings.json) live at the canonical repo location for
            # the pilot project. The platform's submission dir under
            # ~/.platform/ doesn't have them, so we pass explicit paths and let
            # run_audit stage them next to the PDF via _maybe_stage_overlay.
            # Phase 4 / v8a-2 will move these into platform storage as part of
            # per-submission Cowork integration.
            normalized_version = _normalize_submission_version(submission_version_string)
            canonical_submission_dir = (
                _RUN_AUDIT_PATH.parent.parent
                / "projects" / project_tava_number / "submissions" / f"v{normalized_version}"
            )
            for overlay_leaf, job_input_key in (
                ("extracts.json", "extracts_path"),
                ("discipline_findings.json", "discipline_findings_path"),
            ):
                candidate = canonical_submission_dir / overlay_leaf
                if candidate.exists():
                    job_input[job_input_key] = str(candidate)
            (job_dir / "job_input.json").write_text(
                json.dumps(job_input, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            cmd = [
                self._cfg.sidecar_python,
                str(_RUN_AUDIT_PATH),
                "--job-dir", str(job_dir),
            ]
            log.info("spawning run_audit: %s", cmd)
            # cwd=PROJECT_ROOT so the engine's legacy relative-path defaults
            # (notably compliance_engine/format_rules_checker.py's default
            # `Path("submission_format_rules.json")`) resolve correctly.
            # Future cleanup: make those defaults absolute or accept explicit
            # paths via job_input.json. Tracked informally; not a Phase 2b
            # blocker since cwd= is a one-line, low-risk shim.
            result = subprocess.run(
                cmd,
                cwd=str(_RUN_AUDIT_PATH.parent.parent),  # = PROJECT_ROOT
                capture_output=True, text=True,
                timeout=RUN_AUDIT_BUDGET_S,
                check=False,
            )

            if result.returncode != 0:
                # Prefer structured error.json (worker contract) over stderr tail.
                error_json_path = job_dir / "error.json"
                if error_json_path.exists():
                    try:
                        worker_err = json.loads(error_json_path.read_text(encoding="utf-8"))
                    except Exception:
                        worker_err = {"error_type": "MalformedErrorJson"}
                    error_payload = {
                        "error_type": worker_err.get("error_type", "EngineFailure"),
                        "error_message": worker_err.get("error_message", "run_audit failed"),
                        "stderr_tail": (result.stderr or "")[-2000:],
                    }
                else:
                    error_payload = {
                        "error_type": "EngineNonZeroExit",
                        "error_message": f"run_audit exit code {result.returncode}",
                        "stderr_tail": (result.stderr or "")[-4000:],
                        "stdout_tail": (result.stdout or "")[-2000:],
                    }
            else:
                job_output_path = job_dir / "job_output.json"
                if not job_output_path.exists():
                    error_payload = {
                        "error_type": "MissingJobOutput",
                        "error_message": (
                            f"run_audit exited 0 but no job_output.json at {job_output_path}"
                        ),
                    }
                else:
                    # Collect: copy job_output.json → platform findings_path.
                    dest = findings_path(self._cfg, project_id, submission_version_string)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(job_output_path.read_bytes())
        except subprocess.TimeoutExpired:
            error_payload = {
                "error_type": "TimeoutExpired",
                "error_message": f"run_audit exceeded {RUN_AUDIT_BUDGET_S}s wall-clock budget; killed",
            }
        except FileNotFoundError as exc:
            # Two distinct sources for FileNotFoundError land here:
            #   1. resolve_schema() — genuine missing project schema
            #   2. subprocess.run() — the spawned interpreter doesn't
            #      exist (the win32+frozen case: cfg.sidecar_python =
            #      /opt/homebrew/bin/python3.13 which isn't on Windows).
            # Mislabeling case 2 as "SchemaNotFound" sent Ellen on a
            # wild goose chase. Disambiguate by checking whether the
            # missing path matches the sidecar_python config.
            missing = getattr(exc, "filename", "") or str(exc)
            if missing and missing == self._cfg.sidecar_python:
                error_payload = {
                    "error_type": "EngineNotAvailable",
                    "error_message": (
                        "Engine subprocess interpreter not found: "
                        f"{self._cfg.sidecar_python!r} does not exist on this machine. "
                        "Full-audit runs require a Python interpreter on PATH or "
                        "PLATFORM_PYTHON; the win32+frozen build needs an in-process "
                        "branch (see _process_render_pdf for the pattern)."
                    ),
                }
            else:
                error_payload = {
                    "error_type": "SchemaNotFound",
                    "error_message": str(exc),
                }
        except Exception as exc:
            log.exception("run_audit job %s crashed", job_id)
            error_payload = {
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }

        # Persist outcome.
        with Session(self._engine) as sess:
            job = sess.get(Job, job_id)
            sub = sess.get(Submission, job.submission_id)
            now = datetime.now(timezone.utc)
            if error_payload is not None:
                job.status = "failed"
                job.error_json = json.dumps(error_payload, ensure_ascii=False)
                # Mirror every job failure into errors.log so the file holds
                # a complete trail even when the engine signalled failure via
                # return-code instead of raising (the case that hid Ellen's
                # "metadata not found" error from the rotating handler).
                log.error("job %s failed: %s", job_id, error_payload.get("error_message", error_payload))
                if sub is not None:
                    sub.status = "failed"
            else:
                job.status = "completed"
                dest = findings_path(self._cfg, sub.project_id, sub.version_string)
                job.output_path = str(dest)
                if sub is not None:
                    sub.status = "complete"
                    sub.findings_json_path = str(dest)
            job.completed_at = now
            sess.commit()
            log.info("job %s finished: status=%s", job_id, job.status)

    def _process_render_pdf(
        self,
        *,
        job_id: str,
        submission_id: int,
        project_tava_number: str,
        submission_version_string: str,
        job_dir_str: str,
    ) -> None:
        """Phase 2b Module D: spawn `run_audit.py --render-only --comments-file ...`.

        Writes the submission's current discipline_comments to job_dir/comments.json,
        invokes the render path, and persists job status. No job_output.json is
        produced — success = PDF exists at the canonical path.
        """
        error_payload = None
        try:
            job_dir = Path(job_dir_str)
            normalized_version = _normalize_submission_version(submission_version_string)

            # Snapshot comments to disk for the engine to read.
            with Session(self._engine) as sess:
                rows = sess.execute(
                    select(DisciplineComment)
                    .where(DisciplineComment.submission_id == submission_id)
                    .order_by(DisciplineComment.discipline_key,
                              DisciplineComment.created_at)
                ).scalars().all()
                comments_payload = [r.to_dict() for r in rows]
            comments_path = job_dir / "comments.json"
            comments_path.write_text(
                json.dumps(comments_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # Branch by platform-frozen state. The frozen Windows build has no
            # external Python interpreter to spawn (sidecar.exe IS the runtime
            # and cfg.sidecar_python defaults to /opt/homebrew/bin/python3.13
            # which doesn't exist on Windows). Falling through the subprocess
            # path on macOS/dev keeps that flow byte-identical.
            use_inproc = sys.platform == "win32" and getattr(sys, "frozen", False)

            if use_inproc:
                log.info(
                    "render job %s: in-process path (win32+frozen) tava=%s ver=%s",
                    job_id, project_tava_number, normalized_version,
                )
                # Local import: defers the engine import until a render job
                # actually arrives, keeps sidecar cold-start light. The
                # base_dir kwarg routes every user-data lookup through
                # cfg.data_dir (= %LOCALAPPDATA%\\Planning Platform\\) so we
                # never read or write into _MEIPASS.
                from compliance_engine.render import run_render_only
                # Capture the engine's stderr while it runs so the
                # frontend's friendlyError() mapper has the actual cause
                # ("metadata not found at …", "schema not found …") to
                # match on. Without this the only thing the UI sees is
                # "returned 1" — generic-fallback territory.
                import contextlib
                import io
                _stderr_buf = io.StringIO()
                try:
                    with contextlib.redirect_stderr(_stderr_buf):
                        rc = run_render_only(
                            project_key=project_tava_number,
                            submission_version=normalized_version,
                            output_subdir="audit_outputs",
                            comments_file=comments_path,
                            base_dir=self._cfg.data_dir,
                        )
                except Exception as exc:
                    log.exception("render job %s in-process call raised", job_id)
                    error_payload = {
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "stderr_tail": _stderr_buf.getvalue()[-4000:],
                    }
                    rc = -1
                if error_payload is None and rc != 0:
                    error_payload = {
                        "error_type": "RenderNonZeroExit",
                        "error_message": f"in-process run_render_only returned {rc}",
                        "stderr_tail": _stderr_buf.getvalue()[-4000:],
                    }
            else:
                cmd = [
                    self._cfg.sidecar_python,
                    str(_RUN_AUDIT_PATH),
                    "--render-only",
                    "--comments-file", str(comments_path),
                    project_tava_number,
                    normalized_version,
                ]
                log.info("spawning render: %s", cmd)
                result = subprocess.run(
                    cmd,
                    cwd=str(_RUN_AUDIT_PATH.parent.parent),
                    capture_output=True, text=True,
                    timeout=RENDER_BUDGET_S,
                    check=False,
                )
                if result.returncode != 0:
                    error_payload = {
                        "error_type": "RenderNonZeroExit",
                        "error_message": f"render exit code {result.returncode}",
                        "stderr_tail": (result.stderr or "")[-4000:],
                        "stdout_tail": (result.stdout or "")[-2000:],
                    }

            # Shared post-check — locate the PDF the render wrote (or should
            # have written). In-process used cfg.data_dir as base; subprocess
            # used _RUN_AUDIT_PATH.parent.parent (= repo root in dev).
            if error_payload is None:
                base_for_pdf = (
                    self._cfg.data_dir if use_inproc
                    else _RUN_AUDIT_PATH.parent.parent
                )
                pdf_path = (
                    base_for_pdf / "audit_outputs"
                    / project_tava_number / f"v{normalized_version}"
                    / f"audit_report_{normalized_version}.pdf"
                )
                if not pdf_path.exists():
                    error_payload = {
                        "error_type": "MissingRenderOutput",
                        "error_message": f"render exited 0 but no PDF at {pdf_path}",
                    }
                else:
                    output_path_str = str(pdf_path)
        except subprocess.TimeoutExpired:
            error_payload = {
                "error_type": "TimeoutExpired",
                "error_message": f"render exceeded {RENDER_BUDGET_S}s wall-clock budget; killed",
            }
        except Exception as exc:
            log.exception("render job %s crashed", job_id)
            error_payload = {
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }

        with Session(self._engine) as sess:
            job = sess.get(Job, job_id)
            now = datetime.now(timezone.utc)
            if error_payload is not None:
                job.status = "failed"
                job.error_json = json.dumps(error_payload, ensure_ascii=False)
                # Mirror every job failure into errors.log so the file holds
                # a complete trail even when the engine signalled failure via
                # return-code instead of raising (the case that hid Ellen's
                # "metadata not found" error from the rotating handler).
                log.error("job %s failed: %s", job_id, error_payload.get("error_message", error_payload))
            else:
                job.status = "completed"
                job.output_path = output_path_str
            job.completed_at = now
            sess.commit()
            log.info("render job %s finished: status=%s", job_id, job.status)

    def _process_export_excel(
        self,
        *,
        job_id: str,
        project_tava_number: str,
        submission_version_string: str,
    ) -> None:
        """Generate the architect-response XLSX via the in-process engine
        helper. Fast — no subprocess, no timeout budget needed at this size."""
        error_payload = None
        output_path_str: Optional[str] = None
        try:
            normalized_version = _normalize_submission_version(submission_version_string)
            # Local import to keep cold-start light (same pattern as render).
            from compliance_engine.render import run_export_excel
            rc = run_export_excel(
                project_key=project_tava_number,
                submission_version=normalized_version,
                output_subdir="audit_outputs",
                base_dir=self._cfg.data_dir,
            )
            if rc != 0:
                error_payload = {
                    "error_type": "ExcelNonZeroExit",
                    "error_message": f"run_export_excel returned {rc}",
                }
            else:
                xlsx_path = (
                    self._cfg.data_dir / "audit_outputs"
                    / project_tava_number / f"v{normalized_version}"
                    / f"הערות_סקירה_v{normalized_version}.xlsx"
                )
                if not xlsx_path.exists():
                    error_payload = {
                        "error_type": "MissingExcelOutput",
                        "error_message": f"export exited 0 but no XLSX at {xlsx_path}",
                    }
                else:
                    output_path_str = str(xlsx_path)
        except Exception as exc:
            log.exception("excel job %s crashed", job_id)
            error_payload = {
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }

        with Session(self._engine) as sess:
            job = sess.get(Job, job_id)
            now = datetime.now(timezone.utc)
            if error_payload is not None:
                job.status = "failed"
                job.error_json = json.dumps(error_payload, ensure_ascii=False)
                # Mirror every job failure into errors.log so the file holds
                # a complete trail even when the engine signalled failure via
                # return-code instead of raising (the case that hid Ellen's
                # "metadata not found" error from the rotating handler).
                log.error("job %s failed: %s", job_id, error_payload.get("error_message", error_payload))
            else:
                job.status = "completed"
                job.output_path = output_path_str
            job.completed_at = now
            sess.commit()
            log.info("excel job %s finished: status=%s", job_id, job.status)

    def _fail(self, sess: Session, job: Job, *, error_type: str, error_message: str) -> None:
        job.status = "failed"
        job.error_json = json.dumps({"error_type": error_type, "error_message": error_message})
        job.completed_at = datetime.now(timezone.utc)
        sess.commit()

    def _mark_orphans_failed(self) -> None:
        """At sidecar startup, any Job in queued/running state is from a
        previous process that didn't complete. We can't resume the
        subprocess; mark them failed with a clear error so the UI surfaces
        the situation rather than silently lying about state."""
        now = datetime.now(timezone.utc)
        payload = json.dumps({
            "error_type": "OrphanedAfterSidecarRestart",
            "error_message": "Sidecar restarted while this job was in flight. "
                             "Resume is not supported in Phase 2a; re-run the engine if needed.",
        })
        with Session(self._engine) as sess:
            stmt = (
                update(Job)
                .where(Job.status.in_(["queued", "running"]))
                .values(status="failed", error_json=payload, completed_at=now)
            )
            res = sess.execute(stmt)
            if res.rowcount:
                # Also revert any Submission that's stuck in "analyzing".
                sess.execute(
                    update(Submission)
                    .where(Submission.status == "analyzing")
                    .values(status="failed")
                )
                sess.commit()
                log.warning("marked %d orphaned jobs as failed at startup", res.rowcount)
