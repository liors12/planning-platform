"""Project CRUD endpoints — Phase 2a Module A.

  POST   /projects                — create
  GET    /projects                — list (active + archived under toggle)
  GET    /projects/{id}           — full detail
  PATCH  /projects/{id}           — partial update
  POST   /projects/{id}/archive   — soft-archive
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .engine_bridge import has_schema
from .models import Project


_router = APIRouter(prefix="/projects", tags=["projects"])


# ── Pydantic schemas ──────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name_he: str = Field(..., min_length=1, max_length=255)
    tava_number: str = Field(..., min_length=1, max_length=64)
    name_en: str | None = Field(None, max_length=255)
    address: str | None = Field(None, max_length=512)

    @field_validator("name_he", "tava_number", "name_en", "address")
    @classmethod
    def _strip(cls, v):
        if v is None:
            return v
        v = v.strip()
        return v or None


class ProjectPatch(BaseModel):
    name_he: str | None = Field(None, min_length=1, max_length=255)
    name_en: str | None = Field(None, max_length=255)
    tava_number: str | None = Field(None, min_length=1, max_length=64)
    address: str | None = Field(None, max_length=512)


class ProjectOut(BaseModel):
    id: int
    name_he: str
    name_en: str | None
    tava_number: str
    address: str | None
    status: str
    created_at: str
    archived_at: str | None
    has_schema: bool                  # whether engine can run on this project
    # Only present in /projects list with include_summary=true and in GET-by-id:
    latest_submission: dict | None = None
    submission_count: int | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────

def make_router(get_engine):
    def _session() -> Session:
        return Session(get_engine())

    def _serialize(p: Project, *, include_summary: bool = False) -> ProjectOut:
        d = p.to_dict(include_submissions_summary=include_summary)
        d["has_schema"] = has_schema(p.tava_number)
        return ProjectOut(**d)

    @_router.post("", response_model=ProjectOut, status_code=201)
    def create_project(payload: ProjectCreate) -> ProjectOut:
        if not payload.name_he or not payload.tava_number:
            raise HTTPException(422, "name_he and tava_number are required")

        # Pre-check: surface an existing active project with the same tava
        # BEFORE the INSERT so the response can carry the existing project's
        # id + name_he without a second round-trip. The partial UNIQUE index
        # is still the authoritative guard (race-safe).
        with _session() as sess:
            existing = (
                sess.query(Project)
                .filter(Project.tava_number == payload.tava_number,
                        Project.status != "archived")
                .order_by(Project.created_at.asc())
                .first()
            )
            if existing is not None:
                raise HTTPException(status_code=409, detail={
                    "error": "duplicate_tava_active",
                    "message_he": (
                        f'פרויקט עם תב"ע {payload.tava_number} כבר קיים '
                        f'("{existing.name_he}"). הוסף הגשה חדשה אליו במקום ליצור כפילות, '
                        f'או העבר אותו לארכיון תחילה.'
                    ),
                    "existing_project": {
                        "id": existing.id,
                        "name_he": existing.name_he,
                        "tava_number": existing.tava_number,
                        "status": existing.status,
                    },
                })

            project = Project(
                name_he=payload.name_he,
                tava_number=payload.tava_number,
                name_en=payload.name_en,
                address=payload.address,
                status="active",
            )
            sess.add(project)
            try:
                sess.commit()
            except IntegrityError as exc:
                # Race-safe path: another request snuck in between the
                # pre-check and the commit. Re-query the existing row and
                # surface the same structured 409.
                sess.rollback()
                race_existing = (
                    sess.query(Project)
                    .filter(Project.tava_number == payload.tava_number,
                            Project.status != "archived")
                    .order_by(Project.created_at.asc())
                    .first()
                )
                if race_existing is not None:
                    raise HTTPException(status_code=409, detail={
                        "error": "duplicate_tava_active",
                        "message_he": (
                            f'פרויקט עם תב"ע {payload.tava_number} כבר קיים '
                            f'("{race_existing.name_he}"). הוסף הגשה חדשה אליו במקום '
                            f'ליצור כפילות.'
                        ),
                        "existing_project": {
                            "id": race_existing.id,
                            "name_he": race_existing.name_he,
                            "tava_number": race_existing.tava_number,
                            "status": race_existing.status,
                        },
                    }) from exc
                raise HTTPException(500, f"db integrity error: {exc}") from exc
            sess.refresh(project)
            return _serialize(project, include_summary=True)

    @_router.get("", response_model=list[ProjectOut])
    def list_projects(include_archived: bool = Query(False)) -> list[ProjectOut]:
        with _session() as sess:
            q = sess.query(Project)
            if not include_archived:
                q = q.filter(Project.status != "archived")
            rows = q.order_by(Project.created_at.desc(), Project.id.desc()).all()
            return [_serialize(r, include_summary=True) for r in rows]

    @_router.get("/{project_id}", response_model=ProjectOut)
    def get_project(project_id: int) -> ProjectOut:
        with _session() as sess:
            p = sess.get(Project, project_id)
            if p is None:
                raise HTTPException(404, f"project {project_id} not found")
            return _serialize(p, include_summary=True)

    @_router.patch("/{project_id}", response_model=ProjectOut)
    def patch_project(project_id: int, payload: ProjectPatch) -> ProjectOut:
        with _session() as sess:
            p = sess.get(Project, project_id)
            if p is None:
                raise HTTPException(404, f"project {project_id} not found")
            updates = payload.model_dump(exclude_unset=True)
            for k, v in updates.items():
                if isinstance(v, str):
                    v = v.strip() or None
                setattr(p, k, v)
            sess.commit()
            sess.refresh(p)
            return _serialize(p, include_summary=True)

    @_router.post("/{project_id}/archive", response_model=ProjectOut)
    def archive_project(project_id: int) -> ProjectOut:
        with _session() as sess:
            p = sess.get(Project, project_id)
            if p is None:
                raise HTTPException(404, f"project {project_id} not found")
            if p.status == "archived":
                # Idempotent — already archived.
                return _serialize(p, include_summary=True)
            p.status = "archived"
            p.archived_at = datetime.now(timezone.utc)
            sess.commit()
            sess.refresh(p)
            return _serialize(p, include_summary=True)

    return _router
