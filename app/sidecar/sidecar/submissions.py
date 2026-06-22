"""Submission endpoints — Phase 2a Module A + engine integration + Phase 2b PDF serving.

  POST   /projects/{project_id}/submissions     — multipart upload (PDF + opt DWG)
  GET    /projects/{project_id}/submissions     — list submissions for a project
  GET    /submissions/{submission_id}           — full detail
  POST   /submissions/{submission_id}/run-engine — enqueue engine job
  GET    /submissions/{submission_id}/findings  — raw findings JSON
  GET    /submissions/{submission_id}/pdf       — stream PDF with Range support (Phase 2b)
"""
from __future__ import annotations

import json
import logging
import re
import os
import shutil
import subprocess
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Config
from .engine_bridge import has_schema
from .models import Project, Submission
from .queue_worker import EngineQueue, engine_run_available
from .storage import StorageError, sanitize_upload_filename, submission_dir


def _audit_outputs_dir(cfg: Config, tava_number: str, version_string: str) -> Path:
    """The canonical per-submission output directory:
    <data_dir>/audit_outputs/<tava>/v<version>/
    Matches _run_render_only(base_dir=cfg.data_dir, output_subdir="audit_outputs").
    Versions in the DB sometimes carry a "v" prefix and sometimes don't —
    we always store on disk with the prefix."""
    ver = version_string if version_string.startswith("v") else f"v{version_string}"
    return cfg.data_dir / "audit_outputs" / tava_number / ver


def _audit_results_path(cfg: Config, tava_number: str, version_string: str) -> Path | None:
    """Return the on-disk audit_results JSON for this submission, preferring
    the sanitized variant (what the approved PDF was rendered from) and
    falling back to the raw M4. None if neither exists."""
    out_dir = _audit_outputs_dir(cfg, tava_number, version_string)
    for leaf in ("audit_results.m4.sanitized.json", "audit_results.m4.json"):
        p = out_dir / leaf
        if p.exists():
            return p
    return None


def _report_pdf_path(cfg: Config, tava_number: str, version_string: str) -> Path:
    """Where the render writes the report PDF. May or may not exist."""
    ver_bare = version_string[1:] if version_string.startswith("v") else version_string
    return _audit_outputs_dir(cfg, tava_number, version_string) / f"audit_report_{ver_bare}.pdf"


def _report_xlsx_path(cfg: Config, tava_number: str, version_string: str) -> Path:
    """Where _run_export_excel writes the architect-response workbook."""
    ver_bare = version_string[1:] if version_string.startswith("v") else version_string
    return _audit_outputs_dir(cfg, tava_number, version_string) / f"הערות_סקירה_v{ver_bare}.xlsx"


# Two routers because the URL grouping crosses prefixes:
_projects_subs_router = APIRouter(prefix="/projects", tags=["submissions"])
_subs_router = APIRouter(prefix="/submissions", tags=["submissions"])


class SubmissionOut(BaseModel):
    id: int
    project_id: int
    version_string: str
    status: str
    pdf_path: str
    dwg_path: str | None
    findings_json_path: str | None
    uploaded_at: str
    # True iff audit_results.m4.sanitized.json (or .m4.json fallback)
    # exists on disk under cfg.data_dir/audit_outputs/<tava>/v<ver>/.
    # Frontend uses this to show "הפיקי דו״ח" / "הפיקי אקסל" — independent
    # of DB status, so seeded pilots without findings_json_path still
    # surface the buttons.
    has_audit_results: bool = False
    has_report_pdf: bool = False
    has_report_xlsx: bool = False
    # False on win32+frozen, where the full-audit subprocess can't
    # spawn an external Python interpreter (the render-only path is
    # already in-process). Frontend hides/disables "הפעילי את התוכנה"
    # when False to avoid the misleading [WinError 2] SchemaNotFound
    # path. See queue_worker.engine_run_available.
    engine_run_available: bool = True


class JobOut(BaseModel):
    id: str
    job_type: str
    submission_id: int | None
    status: str
    queued_at: str
    started_at: str | None
    completed_at: str | None
    error: str | None


_VERSION_HINT = (
    "version_string must start with an alphanumeric and contain only [A-Za-z0-9._-]. "
    'Examples that work: "v24.3", "24.3", "draft_2026-05-18".'
)


def _stream_upload_to_disk(upload: UploadFile, target: Path) -> None:
    """Stream the upload to disk so we don't load 100+ MB PDFs into memory."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as out:
        # 1 MB chunks — UploadFile already spools past ~1MB by default.
        while True:
            chunk = upload.file.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)


def make_routers(get_engine, cfg: Config, queue: EngineQueue):
    def _session() -> Session:
        return Session(get_engine())

    def _hydrate(sub: Submission) -> SubmissionOut:
        """Build a SubmissionOut with the on-disk flags resolved. Project
        tava_number is read off the loaded relationship; safe because each
        route opens its own session and we serialize before exit."""
        tava = sub.project.tava_number
        return SubmissionOut(
            **sub.to_dict(),
            has_audit_results=_audit_results_path(cfg, tava, sub.version_string) is not None,
            has_report_pdf=_report_pdf_path(cfg, tava, sub.version_string).exists(),
            has_report_xlsx=_report_xlsx_path(cfg, tava, sub.version_string).exists(),
            engine_run_available=engine_run_available(),
        )

    # ── POST /projects/{project_id}/submissions ────────────────────────

    @_projects_subs_router.post(
        "/{project_id}/submissions",
        response_model=SubmissionOut,
        status_code=201,
    )
    async def create_submission(
        project_id: int,
        version_string: str = Form(..., min_length=1, max_length=64),
        pdf: UploadFile = File(...),
        dwg: UploadFile | None = File(None),
    ) -> SubmissionOut:
        with _session() as sess:
            project = sess.get(Project, project_id)
            if project is None:
                raise HTTPException(404, f"project {project_id} not found")

            # Validate version + prepare target directory upfront so we fail
            # fast before streaming a multi-MB upload. The storage tree is
            # keyed by tava_number (matches the engine's audit_outputs tree).
            try:
                target_dir = submission_dir(cfg, project.tava_number, version_string)
            except StorageError as exc:
                raise HTTPException(422, f"{exc} {_VERSION_HINT}")

            try:
                pdf_leaf = sanitize_upload_filename(pdf.filename or "submission.pdf")
            except StorageError as exc:
                raise HTTPException(422, str(exc))
            pdf_path = target_dir / pdf_leaf

            dwg_path: Path | None = None
            if dwg is not None and dwg.filename:
                try:
                    dwg_leaf = sanitize_upload_filename(dwg.filename)
                except StorageError as exc:
                    raise HTTPException(422, str(exc))
                dwg_path = target_dir / dwg_leaf

            # Stream the uploads to disk.
            _stream_upload_to_disk(pdf, pdf_path)
            if dwg is not None and dwg_path is not None:
                _stream_upload_to_disk(dwg, dwg_path)

            # P2-A: write metadata.json so the render path always has it.
            # Originally this file was synthesized by the Phase 2a "Approach
            # B" code (deleted in Phase 2b — see engine_bridge.py history)
            # and never replaced. The render reads two fields from it
            # (submission_version, submission_date); both have empty-string
            # fallbacks, but the file's EXISTENCE used to be a fail-fast
            # gate. Skip writing if a seed/prior version already put one
            # there — never clobber existing metadata.
            metadata_path = target_dir / "metadata.json"
            if not metadata_path.exists():
                bare_version = (version_string[1:] if version_string.startswith("v")
                                else version_string)
                metadata_path.write_text(
                    json.dumps({
                        "plan_number": project.tava_number,
                        "submission_version": bare_version,
                        "submission_date": datetime.now(timezone.utc).date().isoformat(),
                        "file_name": pdf_leaf,
                        "_source": "platform-sidecar",
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            submission = Submission(
                project_id=project_id,
                version_string=version_string,
                status="uploaded",
                pdf_path=str(pdf_path),
                dwg_path=str(dwg_path) if dwg_path else None,
            )
            sess.add(submission)
            try:
                sess.commit()
            except IntegrityError:
                sess.rollback()
                # P2-B: NO file cleanup. We used to shutil.rmtree(target_dir)
                # here, which wiped seeded metadata.json + any prior successful
                # upload's PDF whenever a user accidentally re-uploaded the
                # same version (Ellen's exact failure on Friday). The bytes
                # we just streamed either overwrite the prior PDF with
                # identical content (same file) or coexist alongside a
                # different one — both cases are recoverable. The DB row
                # already exists; the user can re-upload after deleting the
                # version via the delete-version action (Priority 3).
                raise HTTPException(
                    409,
                    f"submission {version_string!r} already exists for project {project_id}",
                )
            sess.refresh(submission)
            return _hydrate(submission)

    # ── GET /projects/{project_id}/submissions ─────────────────────────

    @_projects_subs_router.get(
        "/{project_id}/submissions",
        response_model=list[SubmissionOut],
    )
    def list_submissions(project_id: int) -> list[SubmissionOut]:
        with _session() as sess:
            project = sess.get(Project, project_id)
            if project is None:
                raise HTTPException(404, f"project {project_id} not found")
            rows = (
                sess.query(Submission)
                .filter(Submission.project_id == project_id)
                .order_by(Submission.uploaded_at.desc(), Submission.id.desc())
                .all()
            )
            return [_hydrate(r) for r in rows]

    # ── GET /submissions/{id} ──────────────────────────────────────────

    @_subs_router.get("/{submission_id}", response_model=SubmissionOut)
    def get_submission(submission_id: int) -> SubmissionOut:
        with _session() as sess:
            sub = sess.get(Submission, submission_id)
            if sub is None:
                raise HTTPException(404, f"submission {submission_id} not found")
            return _hydrate(sub)

    # ── DELETE /submissions/{id} ───────────────────────────────────────
    # Removes the submission row + every file it produced. After delete,
    # the same version_string can be uploaded fresh — Priority 3's whole
    # point: today's manual sqlite3-CLI surgery becomes a button click.
    #
    # FK cascades (db.py:64 sets PRAGMA foreign_keys = ON):
    #   discipline_comments.submission_id  ON DELETE CASCADE
    #   jobs.submission_id                  ON DELETE SET NULL
    # so deleting the parent row cleans dependent comments automatically
    # and leaves job history intact (with NULL submission_id).
    #
    # On-disk: best-effort. File-delete failures (locked files, race
    # with a running render) log a warning but DON'T abort — the DB
    # delete is the source of truth. Re-upload of the same version
    # works because the unique constraint is keyed on (project_id,
    # version_string), not on disk paths.

    @_subs_router.delete("/{submission_id}", status_code=204)
    def delete_submission(submission_id: int):
        with _session() as sess:
            sub = sess.get(Submission, submission_id)
            if sub is None:
                raise HTTPException(404, f"submission {submission_id} not found")
            tava = sub.project.tava_number
            version = sub.version_string
            try:
                sess.delete(sub)
                sess.commit()
            except Exception as exc:
                sess.rollback()
                log.exception("delete-submission DB step failed for %s", submission_id)
                raise HTTPException(
                    500,
                    detail={
                        "error_type": "DeleteFailed",
                        "error_message": (
                            "Database delete failed. Please close any open "
                            "report/Excel files for this version and try again."
                        ),
                    },
                ) from exc

        # Best-effort file cleanup, logged but never fatal.
        deleted: list[str] = []
        warnings: list[str] = []
        for target in (
            submission_dir(cfg, tava, version),                      # upload folder
            _audit_outputs_dir(cfg, tava, version),                  # derived outputs
        ):
            try:
                if target.exists():
                    shutil.rmtree(target)
                    deleted.append(str(target))
            except OSError as exc:
                warnings.append(f"{target}: {exc}")
                log.warning("delete-submission could not remove %s: %s", target, exc)
        log.info("deleted submission %s (tava=%s ver=%s); folders removed: %s; warnings: %s",
                 submission_id, tava, version, deleted, warnings or "none")
        return Response(status_code=204)

    # NOTE: PDF re-render goes through comments.py's POST /submissions/{id}/render
    # — single source of truth, comments-aware by default. That endpoint
    # also probes audit_results on disk (not the DB findings flag), so it
    # works for seeded pilots without a per-install engine run.

    # ── POST /submissions/{id}/export-excel ────────────────────────────

    @_subs_router.post(
        "/{submission_id}/export-excel",
        response_model=JobOut,
        status_code=202,
    )
    def export_excel(submission_id: int) -> JobOut:
        with _session() as sess:
            sub = sess.get(Submission, submission_id)
            if sub is None:
                raise HTTPException(404, f"submission {submission_id} not found")
            tava = sub.project.tava_number
            if _audit_results_path(cfg, tava, sub.version_string) is None:
                raise HTTPException(
                    409,
                    f"submission {submission_id} has no audit_results.m4.json on disk; "
                    "run the engine first.",
                )
        job = queue.enqueue_excel(submission_id)
        return JobOut(**job.to_dict())

    # ── GET /submissions/{id}/report.pdf ───────────────────────────────
    # Streams the engine's generated report PDF (distinct from the
    # /pdf endpoint above, which serves the original submission upload).

    @_subs_router.get("/{submission_id}/report.pdf")
    def get_report_pdf(submission_id: int):
        with _session() as sess:
            sub = sess.get(Submission, submission_id)
            if sub is None:
                raise HTTPException(404, f"submission {submission_id} not found")
            tava = sub.project.tava_number
            version = sub.version_string
        path = _report_pdf_path(cfg, tava, version)
        if not path.exists():
            raise HTTPException(404, f"report PDF not generated yet for submission {submission_id}")
        return Response(
            content=path.read_bytes(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{path.name}"',
                "Cache-Control": "private, max-age=0, must-revalidate",
            },
        )

    # ── GET /submissions/{id}/report.xlsx ──────────────────────────────

    @_subs_router.get("/{submission_id}/report.xlsx")
    def get_report_xlsx(submission_id: int):
        with _session() as sess:
            sub = sess.get(Submission, submission_id)
            if sub is None:
                raise HTTPException(404, f"submission {submission_id} not found")
            tava = sub.project.tava_number
            version = sub.version_string
        path = _report_xlsx_path(cfg, tava, version)
        if not path.exists():
            raise HTTPException(404, f"Excel report not generated yet for submission {submission_id}")
        # Hebrew filename: RFC 5987 encoded for cross-browser correctness.
        from urllib.parse import quote
        ascii_name = f"audit_report_v{version.lstrip('v')}.xlsx"
        utf8_name = quote(path.name)
        return Response(
            content=path.read_bytes(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{ascii_name}"; '
                    f"filename*=UTF-8''{utf8_name}"
                ),
                "Cache-Control": "private, max-age=0, must-revalidate",
            },
        )

    # ── POST /submissions/{id}/open-output + /reveal-output ────────────
    # Today Ellen sees "nothing" when she clicks "פתחי דו״ח" because the
    # PDF link is target=_blank — and the Tauri webview swallows _blank
    # navigations. These endpoints solve that without adding a Tauri
    # plugin: the sidecar already has OS access via Python, so it just
    # spawns Explorer / the default app pointed at the generated file.
    #
    # Security: caller picks `kind ∈ {pdf,xlsx}` only. The path is built
    # server-side from cfg.data_dir + tava + version + the canonical
    # leaf name. Never accepts a user-supplied path.

    def _resolve_output(submission_id: int, kind: str) -> Path:
        if kind not in ("pdf", "xlsx"):
            raise HTTPException(422, f"unknown output kind: {kind!r}")
        with _session() as sess:
            sub = sess.get(Submission, submission_id)
            if sub is None:
                raise HTTPException(404, f"submission {submission_id} not found")
            tava = sub.project.tava_number
            version = sub.version_string
        path = (_report_pdf_path(cfg, tava, version) if kind == "pdf"
                else _report_xlsx_path(cfg, tava, version))
        if not path.exists():
            raise HTTPException(
                404,
                f"{kind} report not generated yet for submission {submission_id}",
            )
        return path

    def _spawn(args: list[str]) -> None:
        """Fire-and-forget. Errors swallowed because the OS file-open
        call shouldn't block or fail the HTTP response — the worst case
        is "user clicks button, nothing happens", which the front-end
        can re-prompt for. Errors do flow to errors.log via the warning."""
        try:
            subprocess.Popen(args, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception as exc:
            log.warning("OS open failed for %s: %s", args, exc)

    @_subs_router.post("/{submission_id}/open-output", status_code=204)
    def open_output(submission_id: int, kind: str):
        """Open the generated PDF or XLSX in the OS default app."""
        path = _resolve_output(submission_id, kind)
        if sys.platform == "win32":
            os.startfile(str(path))      # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            _spawn(["open", str(path)])
        else:
            _spawn(["xdg-open", str(path)])
        return Response(status_code=204)

    @_subs_router.post("/{submission_id}/reveal-output", status_code=204)
    def reveal_output(submission_id: int, kind: str):
        """Open the file's containing folder in the OS file manager,
        with the file selected/highlighted where the OS supports it."""
        path = _resolve_output(submission_id, kind)
        if sys.platform == "win32":
            # explorer /select highlights the file inside its folder.
            _spawn(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            _spawn(["open", "-R", str(path)])
        else:
            _spawn(["xdg-open", str(path.parent)])
        return Response(status_code=204)

    @_subs_router.post("/open-url", status_code=204)
    def open_url(url: str = Query(...)):
        """Open an external URL in the OS default browser.
        Needed because the Tauri webview ignores target="_blank"."""
        webbrowser.open(url)
        return Response(status_code=204)

    # ── POST /submissions/{id}/run-engine ──────────────────────────────

    @_subs_router.post("/{submission_id}/run-engine", response_model=JobOut, status_code=202)
    def run_engine(submission_id: int) -> JobOut:
        # Pre-flight: never enqueue a job that is 100% guaranteed to
        # fail. On win32+frozen the worker can't spawn cfg.sidecar_python
        # (it's an external interpreter path that doesn't exist in the
        # PyInstaller bundle). Fail fast with a structured 503 so the
        # frontend can surface a friendly "feature not available" line.
        if not engine_run_available():
            raise HTTPException(
                503,
                detail={
                    "error_type": "EngineNotAvailable",
                    "error_message": (
                        "Full-audit runs require a Python interpreter, which the "
                        "current packaged build does not bundle. Use 'הפיקי דו״ח' "
                        "to regenerate the report from existing audit results."
                    ),
                },
            )
        with _session() as sess:
            sub = sess.get(Submission, submission_id)
            if sub is None:
                raise HTTPException(404, f"submission {submission_id} not found")
            project = sub.project
            if not has_schema(project.tava_number):
                raise HTTPException(
                    409,
                    f"project {project.id} (tava {project.tava_number}) has no schema file; "
                    "engine cannot run. Phase 3 will add a schema-upload UI.",
                )
            if not Path(sub.pdf_path).exists():
                raise HTTPException(
                    409,
                    f"submission {submission_id} PDF missing from disk at {sub.pdf_path}",
                )

        # Enqueue from outside the session so the new Session inside enqueue_run_audit
        # doesn't conflict.
        job = queue.enqueue_run_audit(submission_id)
        return JobOut(**job.to_dict())

    # ── GET /submissions/{id}/findings ─────────────────────────────────

    @_subs_router.get("/{submission_id}/findings")
    def get_findings(submission_id: int):
        with _session() as sess:
            sub = sess.get(Submission, submission_id)
            if sub is None:
                raise HTTPException(404, f"submission {submission_id} not found")
            if sub.findings_json_path is None:
                raise HTTPException(
                    409,
                    f"submission {submission_id} has no findings yet (status={sub.status!r}). "
                    "POST /submissions/{id}/run-engine first.",
                )
            findings_file = Path(sub.findings_json_path)
            if not findings_file.exists():
                raise HTTPException(
                    500,
                    f"findings_json_path is recorded but file missing on disk: {findings_file}",
                )
            return json.loads(findings_file.read_text(encoding="utf-8"))

    # ── GET /submissions/{id}/pdf  (Phase 2b — Range-aware streaming) ──
    #
    # react-pdf reads the file with byte-range requests, fetching pdf.js
    # metadata + xref tables before pulling page bodies. Without 206 Partial
    # Content support, the browser falls back to downloading the whole file
    # (100 MB for v24.3) before showing page 1.
    #
    # Implementation notes:
    #   - Starlette's FileResponse offers Range support in recent versions,
    #     but behavior across starlette/uvicorn version combos has been
    #     uneven. We do it explicitly to be deterministic.
    #   - Spec § 8: 127.0.0.1-only, no auth. Same constraint as the rest of
    #     the API.
    #   - Memory: yield in 256 KB chunks. A 100 MB file at 200 chunks max is
    #     trivial; never holds the whole PDF in RAM.

    _PDF_CHUNK_SIZE = 256 * 1024  # 256 KB

    @_subs_router.head("/{submission_id}/pdf")
    def head_pdf(submission_id: int):
        """HEAD: probe for Accept-Ranges + Content-Length without body.
        pdf.js (via react-pdf) sometimes preflights with HEAD before issuing
        the first ranged GET, so we expose it explicitly."""
        with _session() as sess:
            sub = sess.get(Submission, submission_id)
            if sub is None:
                raise HTTPException(404, f"submission {submission_id} not found")
            pdf_path = Path(sub.pdf_path)
        if not pdf_path.exists():
            # Soft 404: the row exists but the bytes don't (e.g. user
            # cleared cfg.data_dir, or storage was migrated and this row
            # still points at the old layout). UI can react with a
            # "re-upload required" prompt instead of erroring loudly.
            raise HTTPException(
                404,
                f"submission {submission_id} PDF missing from disk "
                f"(stale file_path: {sub.pdf_path}). Re-upload required.",
            )
        file_size = pdf_path.stat().st_size
        return Response(
            status_code=200,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Type": "application/pdf",
                "Content-Length": str(file_size),
                "Cache-Control": "private, max-age=0, must-revalidate",
            },
        )

    @_subs_router.get("/{submission_id}/pdf")
    def get_pdf(
        submission_id: int,
        request: Request,
        range_header: str | None = Header(None, alias="range"),
    ):
        with _session() as sess:
            sub = sess.get(Submission, submission_id)
            if sub is None:
                raise HTTPException(404, f"submission {submission_id} not found")
            pdf_path = Path(sub.pdf_path)
        if not pdf_path.exists():
            # Soft 404: the row exists but the bytes don't (e.g. user
            # cleared cfg.data_dir, or storage was migrated and this row
            # still points at the old layout). UI can react with a
            # "re-upload required" prompt instead of erroring loudly.
            raise HTTPException(
                404,
                f"submission {submission_id} PDF missing from disk "
                f"(stale file_path: {sub.pdf_path}). Re-upload required.",
            )

        file_size = pdf_path.stat().st_size
        filename = pdf_path.name
        common_headers = {
            "Accept-Ranges": "bytes",
            "Content-Type": "application/pdf",
            "Cache-Control": "private, max-age=0, must-revalidate",
            "Content-Disposition": f'inline; filename="{filename}"',
        }

        if range_header is None:
            return StreamingResponse(
                _stream_file_range(pdf_path, 0, file_size - 1, _PDF_CHUNK_SIZE),
                status_code=200,
                headers={**common_headers, "Content-Length": str(file_size)},
            )

        # Parse "Range: bytes=START-END" (single range only — pdf.js never
        # requests multipart ranges).
        rng = _parse_range(range_header, file_size)
        if rng is None:
            return Response(
                status_code=416,  # Requested Range Not Satisfiable
                headers={**common_headers, "Content-Range": f"bytes */{file_size}"},
            )
        start, end = rng
        length = end - start + 1
        return StreamingResponse(
            _stream_file_range(pdf_path, start, end, _PDF_CHUNK_SIZE),
            status_code=206,  # Partial Content
            headers={
                **common_headers,
                "Content-Length": str(length),
                "Content-Range": f"bytes {start}-{end}/{file_size}",
            },
        )

    return _projects_subs_router, _subs_router


# ─────────────────────────────────────────────────────────────────────────────
# Range parsing + chunked file streaming (module-level helpers — testable)
# ─────────────────────────────────────────────────────────────────────────────

# RFC 7233-style Range header. We accept ONLY single byte ranges:
#   bytes=START-END   → both ends present
#   bytes=START-      → from START to EOF
#   bytes=-SUFFIX     → last SUFFIX bytes
_RANGE_RE = re.compile(r"^\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*$")


def _parse_range(header_value: str, file_size: int) -> tuple[int, int] | None:
    """Return (start, end) inclusive byte offsets, or None if unsatisfiable."""
    m = _RANGE_RE.match(header_value)
    if not m:
        return None
    raw_start, raw_end = m.group(1), m.group(2)

    if raw_start == "" and raw_end == "":
        return None  # "bytes=-" malformed
    if raw_start == "":
        # Suffix range: last N bytes.
        suffix = int(raw_end)
        if suffix == 0:
            return None
        start = max(0, file_size - suffix)
        end = file_size - 1
    else:
        start = int(raw_start)
        if start >= file_size:
            return None  # 416 path
        end = int(raw_end) if raw_end != "" else file_size - 1
        end = min(end, file_size - 1)
    if start > end:
        return None
    return start, end


def _stream_file_range(path: Path, start: int, end: int, chunk_size: int) -> Iterator[bytes]:
    """Yield bytes [start..end] inclusive from `path` in chunks. Never loads
    more than `chunk_size` bytes at a time into memory."""
    remaining = end - start + 1
    with path.open("rb") as f:
        f.seek(start)
        while remaining > 0:
            chunk = f.read(min(chunk_size, remaining))
            if not chunk:
                return
            remaining -= len(chunk)
            yield chunk
