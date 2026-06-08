"""FastAPI router for discipline_comments + render trigger — Phase 2b Module D.

Endpoints:
  POST   /submissions/{id}/comments              create
  GET    /submissions/{id}/comments              list
  PATCH  /submissions/{id}/comments/{cid}        edit
  DELETE /submissions/{id}/comments/{cid}        delete
  POST   /submissions/{id}/render                trigger --render-only re-render

Render contract: comments are merged into the HTML at render time only.
They are NOT written into audit_results.m4.json, so re-analysis never
clobbers them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .disciplines import DISCIPLINE_KEYS, DISCIPLINES, STATUS_SET, TOPIC_MAX_LEN
from .models import DisciplineComment, Submission
from .queue_worker import EngineQueue


# ─── Pydantic schemas ────────────────────────────────────────────────────────

class CommentIn(BaseModel):
    discipline_key: str = Field(..., description="One of DISCIPLINE_KEYS")
    status: str = Field(..., description="One of STATUSES (Hebrew)")
    topic_he: str = Field(..., min_length=1, max_length=TOPIC_MAX_LEN)
    action_he: str = Field(..., min_length=1)


class CommentPatch(BaseModel):
    discipline_key: Optional[str] = None
    status: Optional[str] = None
    topic_he: Optional[str] = Field(None, min_length=1, max_length=TOPIC_MAX_LEN)
    action_he: Optional[str] = Field(None, min_length=1)


class CommentOut(BaseModel):
    id: str
    submission_id: int
    discipline_key: str
    status: str
    topic_he: str
    action_he: str
    author: str
    created_at: Optional[str]
    updated_at: Optional[str]


class JobOut(BaseModel):
    id: str
    job_type: str
    submission_id: Optional[int]
    status: str
    queued_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    error: Optional[str]


# ─── Validation helpers ──────────────────────────────────────────────────────

def _validate_discipline_key(key: str) -> None:
    if key not in DISCIPLINE_KEYS:
        raise HTTPException(
            422,
            f"invalid discipline_key {key!r}; expected one of "
            f"{sorted(DISCIPLINE_KEYS)}",
        )


def _validate_status(status: str) -> None:
    if status not in STATUS_SET:
        raise HTTPException(
            422,
            f"invalid status {status!r}; expected one of {sorted(STATUS_SET)}",
        )


# ─── Router factory ──────────────────────────────────────────────────────────

def make_routers(engine: Engine, queue: EngineQueue) -> tuple[APIRouter, APIRouter]:
    """Returns (comments_router, disciplines_router).

    comments_router mounts at /submissions and owns POST/GET/PATCH/DELETE
    on /{submission_id}/comments[/{cid}] + POST /{submission_id}/render.

    disciplines_router exposes GET /disciplines as a single source of truth
    for the frontend dropdown.
    """
    comments = APIRouter(prefix="/submissions", tags=["comments"])
    disciplines = APIRouter(tags=["disciplines"])

    def _session() -> Session:
        return Session(engine)

    def _require_submission(sess: Session, submission_id: int) -> Submission:
        sub = sess.get(Submission, submission_id)
        if sub is None:
            raise HTTPException(404, f"submission {submission_id} not found")
        return sub

    # ── GET /disciplines ──────────────────────────────────────────────────

    @disciplines.get("/disciplines")
    def list_disciplines():
        """Return the canonical 9 disciplines + valid statuses.

        Mounted at root (not under /submissions) because the dropdown is
        global. Used by both validation (the server checks the same list)
        and the frontend.
        """
        return {"disciplines": DISCIPLINES, "statuses": sorted(STATUS_SET)}

    # ── POST /submissions/{id}/comments ────────────────────────────────────

    @comments.post(
        "/{submission_id}/comments",
        response_model=CommentOut,
        status_code=201,
    )
    def create_comment(submission_id: int, body: CommentIn) -> CommentOut:
        _validate_discipline_key(body.discipline_key)
        _validate_status(body.status)
        with _session() as sess:
            _require_submission(sess, submission_id)
            now = datetime.now(timezone.utc)
            comment = DisciplineComment(
                id=str(uuid.uuid4()),
                submission_id=submission_id,
                discipline_key=body.discipline_key,
                status=body.status,
                topic_he=body.topic_he,
                action_he=body.action_he,
                author="user",
                created_at=now,
                updated_at=now,
            )
            sess.add(comment)
            sess.commit()
            sess.refresh(comment)
            return CommentOut(**comment.to_dict())

    # ── GET /submissions/{id}/comments ─────────────────────────────────────

    @comments.get(
        "/{submission_id}/comments",
        response_model=list[CommentOut],
    )
    def list_comments(submission_id: int) -> list[CommentOut]:
        with _session() as sess:
            _require_submission(sess, submission_id)
            rows = sess.execute(
                select(DisciplineComment)
                .where(DisciplineComment.submission_id == submission_id)
                .order_by(DisciplineComment.discipline_key,
                          DisciplineComment.created_at)
            ).scalars().all()
            return [CommentOut(**r.to_dict()) for r in rows]

    # ── PATCH /submissions/{id}/comments/{cid} ─────────────────────────────

    @comments.patch(
        "/{submission_id}/comments/{comment_id}",
        response_model=CommentOut,
    )
    def patch_comment(
        submission_id: int, comment_id: str, body: CommentPatch,
    ) -> CommentOut:
        with _session() as sess:
            _require_submission(sess, submission_id)
            comment = sess.get(DisciplineComment, comment_id)
            if comment is None or comment.submission_id != submission_id:
                raise HTTPException(404, f"comment {comment_id} not found")
            if body.discipline_key is not None:
                _validate_discipline_key(body.discipline_key)
                comment.discipline_key = body.discipline_key
            if body.status is not None:
                _validate_status(body.status)
                comment.status = body.status
            if body.topic_he is not None:
                comment.topic_he = body.topic_he
            if body.action_he is not None:
                comment.action_he = body.action_he
            comment.updated_at = datetime.now(timezone.utc)
            sess.commit()
            sess.refresh(comment)
            return CommentOut(**comment.to_dict())

    # ── DELETE /submissions/{id}/comments/{cid} ────────────────────────────

    @comments.delete(
        "/{submission_id}/comments/{comment_id}",
        status_code=204,
    )
    def delete_comment(submission_id: int, comment_id: str):
        with _session() as sess:
            _require_submission(sess, submission_id)
            comment = sess.get(DisciplineComment, comment_id)
            if comment is None or comment.submission_id != submission_id:
                raise HTTPException(404, f"comment {comment_id} not found")
            sess.delete(comment)
            sess.commit()
            return None

    # ── POST /submissions/{id}/render ──────────────────────────────────────

    @comments.post(
        "/{submission_id}/render",
        response_model=JobOut,
        status_code=202,
    )
    def render_submission(submission_id: int) -> JobOut:
        """Trigger a --render-only re-render of the PDF, with the current
        comments merged in. Returns 202 + job_id; poll /jobs/{id} for status.
        """
        with _session() as sess:
            sub = _require_submission(sess, submission_id)
            if sub.findings_json_path is None:
                raise HTTPException(
                    409,
                    f"submission {submission_id} has no engine output yet "
                    f"(status={sub.status!r}). Run /run-engine first.",
                )
        job = queue.enqueue_render(submission_id)
        return JobOut(**job.to_dict())

    return comments, disciplines
