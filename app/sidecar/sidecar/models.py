"""SQLAlchemy ORM models — Phase 2a (Module A + engine integration).

Phase 1 had just `Project`. Phase 2a adds:
  * `Submission` — uploaded PDF (+ optional DWG) attached to a project, with
    a free-text version_string (e.g., "v24.3") that the user controls.
  * `Job` — queued/running/completed/failed engine invocations, with backing
    job-dir path for ADR-001's JSON-on-disk handoff contract. Persisted so
    a sidecar restart can resume status reporting without losing history.

`Project` is extended with `name_en`, `address`, `status`, `archived_at`.

Schema upgrade in Phase 2a is via `Base.metadata.create_all(engine)` — Alembic
gets introduced when columns start being dropped/renamed (Phase 3+).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Project
# ─────────────────────────────────────────────────────────────────────────────
#
# Status values (kept as plain strings, not a DB enum — simpler to extend, and
# SQLite's enum support is half-baked):
#   active            — default; project being actively reviewed
#   awaiting_review   — submission uploaded, waiting on Ellen / discipline mgrs
#   signed            — final חוות דעת signed and dispatched
#   archived          — soft-deleted; hidden from default views

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name_he: Mapped[str] = mapped_column(String(255), nullable=False)
    tava_number: Mapped[str] = mapped_column(String(64), nullable=False)

    # Phase 2a additions:
    name_en: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active",
                                        server_default="active")
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True),
                                                            nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.datetime("now"),
        nullable=False,
    )

    submissions: Mapped[list["Submission"]] = relationship(
        "Submission", back_populates="project", cascade="all, delete-orphan",
        order_by="Submission.uploaded_at.desc()",
    )

    def to_dict(self, include_submissions_summary: bool = False) -> dict:
        d = {
            "id": self.id,
            "name_he": self.name_he,
            "name_en": self.name_en,
            "tava_number": self.tava_number,
            "address": self.address,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
        }
        if include_submissions_summary:
            d["latest_submission"] = (
                self.submissions[0].to_summary() if self.submissions else None
            )
            d["submission_count"] = len(self.submissions)
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Submission
# ─────────────────────────────────────────────────────────────────────────────
#
# Status flow:
#   uploaded   — files saved to disk; no engine run yet
#   extracting — vision extractor running (future v8a-2; not used in Phase 2a)
#   analyzing  — engine job in flight
#   complete   — engine job finished, findings JSON written
#   failed     — engine job failed; see findings_json_path for error.json
#
# `version_string` is user-controlled free text (e.g. "v24.3"). Uniqueness is
# enforced per-project at the DB layer to prevent accidental dupes.

class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_string", name="uq_submission_project_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True,
    )

    version_string: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded",
                                        server_default="uploaded")

    pdf_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    dwg_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    findings_json_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.datetime("now"),
        nullable=False,
    )

    project: Mapped["Project"] = relationship("Project", back_populates="submissions")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "version_string": self.version_string,
            "status": self.status,
            "pdf_path": self.pdf_path,
            "dwg_path": self.dwg_path,
            "findings_json_path": self.findings_json_path,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
        }

    def to_summary(self) -> dict:
        """Compact form for embedding in Project responses."""
        return {
            "id": self.id,
            "version_string": self.version_string,
            "status": self.status,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Job — queued/running/completed/failed engine invocations
# ─────────────────────────────────────────────────────────────────────────────
#
# Persistence purpose: if the sidecar restarts mid-job, the user's UI can
# still see "this submission was running an engine job that never finished".
# (The actual subprocess is lost on restart; Phase 2a marks orphaned jobs
# `failed` on startup with a clear error. Phase 4 can add real resumption.)

class Job(Base):
    __tablename__ = "jobs"

    # UUID string as PK — same id used for the on-disk job_dir name.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    submission_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("submissions.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued",
                                        server_default="queued")
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.datetime("now"),
        nullable=False,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True),
                                                           nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True),
                                                             nullable=True)

    # On-disk job dir holding job_input.json + job_output.json (or error.json).
    # Conforms to the ADR-001 § Implication 1 contract.
    job_dir: Mapped[str] = mapped_column(String(1024), nullable=False)
    # Convenience: where the worker wrote its output (computed from job_dir).
    output_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    # Serialized error_type + error_message + stderr tail when status == failed.
    error_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "job_type": self.job_type,
            "submission_id": self.submission_id,
            "status": self.status,
            "queued_at": self.queued_at.isoformat() if self.queued_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error_json,  # raw JSON-encoded blob; UI parses
        }


# ─────────────────────────────────────────────────────────────────────────────
# DisciplineComment — Phase 2b Module D (partial)
# ─────────────────────────────────────────────────────────────────────────────
#
# Referent notes that Ellen enters in the UI after her meetings. Stored
# separately from `audit_results.m4.json` (the engine's pure output): the
# render path merges them in as additional discipline rows at PDF generation
# time, tagged "(הערת רפרנט)". Re-running the engine never clobbers them.

class DisciplineComment(Base):
    __tablename__ = "discipline_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    discipline_key: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    topic_he: Mapped[str] = mapped_column(String(255), nullable=False)
    action_he: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(64), nullable=False,
                                        default="user", server_default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.datetime("now"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.datetime("now"),
        nullable=False,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "submission_id": self.submission_id,
            "discipline_key": self.discipline_key,
            "status": self.status,
            "topic_he": self.topic_he,
            "action_he": self.action_he,
            "author": self.author,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
