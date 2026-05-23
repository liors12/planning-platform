"""Subprocess-isolation dispatch helper.

Implements the contract in ADR-001 § Implication 1: JSON-on-disk handoff. Each
job gets a per-invocation temp dir under the platform data dir. Sidecar writes
`job_input.json`, spawns the worker script with `--job-dir`, the worker writes
`job_output.json` (or `error.json`) and exits.

This is the ONLY way the sidecar may execute work that doesn't fit ADR-001's
"sidecar's own hot path" exception (config loading, SQLite queries). Adding a
new job means adding a row to docs/architecture/job_types.md AND a script
that obeys this contract — never an in-process import.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config

log = logging.getLogger(__name__)


class JobError(Exception):
    """Raised when a worker subprocess exits non-zero or breaches the budget."""


@dataclass
class JobResult:
    job_id: str
    job_type: str
    exit_code: int
    duration_s: float
    output: dict  # contents of job_output.json (empty if error)
    job_dir: Path  # preserved for forensics on failure
    stderr_tail: str = ""


def run_job(
    *,
    cfg: Config,
    job_type: str,
    worker_module: str,
    input_payload: dict,
    timeout_s: float,
) -> JobResult:
    """Spawn `python -m worker_module --job-dir DIR`, wait, parse output.

    Args:
        cfg: loaded Config (for python binary + data dirs).
        job_type: identifier for logs and audit (e.g. "echo", "run_audit").
        worker_module: importable module path, e.g. "sidecar.jobs.echo_worker".
            MUST expose a `__main__` block that reads job_input.json from
            --job-dir and writes job_output.json or error.json.
        input_payload: JSON-serializable dict written as job_input.json.
        timeout_s: SIGKILL deadline. See docs/architecture/job_types.md.

    Returns: JobResult on success.
    Raises:  JobError on non-zero exit, timeout, or malformed output.
    """
    job_id = str(uuid.uuid4())
    job_dir = cfg.jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)

    (job_dir / "job_input.json").write_text(
        json.dumps(input_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (job_dir / "_meta.json").write_text(
        json.dumps({
            "job_id": job_id,
            "job_type": job_type,
            "worker_module": worker_module,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "timeout_s": timeout_s,
        }, indent=2),
        encoding="utf-8",
    )

    cmd = [
        cfg.sidecar_python,
        "-m", worker_module,
        "--job-dir", str(job_dir),
    ]
    log.info("dispatching job_id=%s type=%s cmd=%s", job_id, job_type, cmd)

    started = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration = (datetime.now(timezone.utc) - started).total_seconds()
        log.error("job_id=%s timed out after %.1fs (budget %.1fs)", job_id, duration, timeout_s)
        raise JobError(
            f"job {job_type!r} exceeded wall-clock budget {timeout_s}s; killed."
        ) from exc

    duration = (datetime.now(timezone.utc) - started).total_seconds()
    stderr_tail = (proc.stderr or "")[-2000:]

    if proc.returncode != 0:
        err_path = job_dir / "error.json"
        err_payload = {}
        if err_path.exists():
            try:
                err_payload = json.loads(err_path.read_text(encoding="utf-8"))
            except Exception:
                err_payload = {"_parse_error": "error.json exists but is not valid JSON"}
        log.error(
            "job_id=%s exited %d in %.2fs; stderr_tail=%r err=%r",
            job_id, proc.returncode, duration, stderr_tail, err_payload,
        )
        raise JobError(
            f"job {job_type!r} (job_id={job_id}) exited {proc.returncode}: "
            f"{err_payload or stderr_tail or '<no error detail>'}"
        )

    out_path = job_dir / "job_output.json"
    if not out_path.exists():
        raise JobError(
            f"job {job_type!r} succeeded with exit 0 but wrote no job_output.json "
            f"(stderr_tail={stderr_tail!r})"
        )

    output = json.loads(out_path.read_text(encoding="utf-8"))
    log.info("job_id=%s OK in %.2fs", job_id, duration)
    return JobResult(
        job_id=job_id,
        job_type=job_type,
        exit_code=0,
        duration_s=duration,
        output=output,
        job_dir=job_dir,
        stderr_tail=stderr_tail,
    )


def cleanup_old_jobs(cfg: Config, *, keep_last_n: int = 50) -> int:
    """Garbage-collect the per-job temp dirs, keeping the N most recent.

    Failed jobs are preserved for forensics; this only trims succeeded ones.
    """
    dirs = sorted(
        (d for d in cfg.jobs_dir.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for d in dirs[keep_last_n:]:
        if (d / "error.json").exists():
            continue  # keep failures
        shutil.rmtree(d, ignore_errors=True)
        removed += 1
    return removed
