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
import re
import shutil
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Config
from .engine_bridge import has_schema
from .models import Project, Submission
from .queue_worker import EngineQueue
from .storage import StorageError, sanitize_upload_filename, submission_dir


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
            # fast before streaming a multi-MB upload.
            try:
                target_dir = submission_dir(cfg, project_id, version_string)
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
                # Roll back the disk write so a re-POST works without leftover files.
                try:
                    shutil.rmtree(target_dir)
                except OSError:
                    pass
                raise HTTPException(
                    409,
                    f"submission {version_string!r} already exists for project {project_id}",
                )
            sess.refresh(submission)
            return SubmissionOut(**submission.to_dict())

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
            return [SubmissionOut(**r.to_dict()) for r in rows]

    # ── GET /submissions/{id} ──────────────────────────────────────────

    @_subs_router.get("/{submission_id}", response_model=SubmissionOut)
    def get_submission(submission_id: int) -> SubmissionOut:
        with _session() as sess:
            sub = sess.get(Submission, submission_id)
            if sub is None:
                raise HTTPException(404, f"submission {submission_id} not found")
            return SubmissionOut(**sub.to_dict())

    # ── POST /submissions/{id}/run-engine ──────────────────────────────

    @_subs_router.post("/{submission_id}/run-engine", response_model=JobOut, status_code=202)
    def run_engine(submission_id: int) -> JobOut:
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
            raise HTTPException(500, f"PDF gone from disk: {pdf_path}")
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
            raise HTTPException(500, f"PDF gone from disk: {pdf_path}")

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
