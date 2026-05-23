"""Schema-path lookup for the compliance engine.

**History — Phase 2a "Approach B" (now obsolete):** This module used to copy
the user's uploaded PDF into a legacy `<REPO>/projects/{tava}/submissions/v{v}/`
directory layout and synthesize a `metadata.json` so the v8j-era `run_audit.py`
positional CLI could find the inputs. Approach B unblocked Phase 2a delivery
but violated ADR-001's uniform `--job-dir` worker contract.

**Phase 2b migration (this module's current state):** `run_audit.py` was
migrated to the `--job-dir` contract (see `scripts/run_audit.py` +
`docs/phase_2b_commitments.md` ticket #1). The queue worker now writes
`job_input.json` with platform paths directly — no copying, no metadata
synthesis. The `prepare()` / `invoke()` / `collect()` helpers + the
`EngineInvocation` / `EngineBridgeError` types from Approach B are gone.

What remains: two small helpers used to discover whether a project_schema
file exists for a given tava_number, and where it lives. Used by:
  - `projects.py` (to set the `has_schema` flag on /projects responses)
  - `submissions.py` (to gate the `Run Engine` endpoint)
  - `queue_worker.py` (to write `schema_path` into job_input.json)
"""
from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # planning-platform/


def has_schema(tava_number: str) -> bool:
    """Return True iff a `project-schema-{tava}-v2.json` file exists for
    this tava on disk. Used by the UI to gate engine runs."""
    return _candidate_paths(tava_number) != []


def resolve_schema(tava_number: str) -> Path:
    """Return the absolute path to the project's schema file. Raises
    FileNotFoundError if absent. Callers should `has_schema()` first."""
    paths = _candidate_paths(tava_number)
    if not paths:
        raise FileNotFoundError(
            f"no project-schema-{tava_number}-v2.json found for tava {tava_number!r}. "
            f"Phase 3 will add a schema-upload UI; until then, only "
            f"pre-existing schemas can be audited."
        )
    return paths[0]


def _candidate_paths(tava_number: str) -> list[Path]:
    return [
        p for p in (
            PROJECT_ROOT / "projects" / tava_number / f"project-schema-{tava_number}-v2.json",
            PROJECT_ROOT / f"project-schema-{tava_number}-v2.json",
        )
        if p.exists()
    ]
