"""Job status endpoint — Phase 2a.

  GET /jobs/{job_id}  — current status of a queued/running/completed/failed job.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .queue_worker import EngineQueue


_router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobOut(BaseModel):
    id: str
    job_type: str
    submission_id: int | None
    status: str
    queued_at: str
    started_at: str | None
    completed_at: str | None
    error: str | None


def make_router(queue: EngineQueue):
    @_router.get("/{job_id}", response_model=JobOut)
    def get_job(job_id: str) -> JobOut:
        job = queue.get_job(job_id)
        if job is None:
            raise HTTPException(404, f"job {job_id} not found")
        return JobOut(**job.to_dict())

    return _router
