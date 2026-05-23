"""Compliance persistence layer.

Wraps the in-memory evaluator (`evaluate_parcel`) with engine-run lifecycle
management and database I/O. This is the layer that turns "here's a list
of Violation objects" into "here's a complete, queryable audit trail of
the run."

Lifecycle (per `run_compliance_evaluation`):

  1. Insert an `engine_runs` row with `status='running'` (committed
     immediately so a crash leaves the row visible for diagnostics).
  2. For each parcel in `project_data.project.parcels[]`:
       a. Call `evaluate_parcel()` — returns `list[Violation]`.
       b. Insert each Violation into `violations`.
       c. Commit (so partial progress survives a later parcel's crash).
  3. Compute summary stats; UPDATE the run row with status='complete',
     summary_stats_json, completed_at; commit.

  Failure path: any uncaught exception during step 2 marks the run
  'failed', stores the traceback in error_message, commits, and re-raises.
  Partial violations from earlier parcels stay for diagnostic value.

This module also provides `load_violations_for_run` — the read path used
by downstream consumers (PDF generator, reviewer UI). It rehydrates
`Violation` objects from the violations table, deserializing the JSON
columns and converting the integer override flag back to bool.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import traceback
import uuid
from collections import Counter, defaultdict
from typing import Any

from .evaluator import evaluate_parcel
from .types import Confidence, FailureMode, RuleType, Verdict, Violation


logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Public API — write path
# ──────────────────────────────────────────────────────────────────────

def run_compliance_evaluation(
    project_id: str,
    project_data: dict,
    extracted_data: dict,
    db_conn: sqlite3.Connection,
    engine_version: str,
    submission_version: str,
    triggered_by: str = "manual",
) -> str:
    """Run full compliance evaluation for a project and persist the results.

    Returns the engine_run_id (UUID string) for downstream reference.

    Args:
        project_id: The `projects.id` UUID. The caller is responsible for
            having loaded the project via `load_project.py` first.
        project_data: Parsed project schema JSON. Must include
            `project.parcels[]` and `linked_statutory_plans[]` (consumed
            by the resolver).
        extracted_data: Per-parcel extracted values. See `evaluator` module
            docstring for the expected shape.
        db_conn: Open SQLite connection. Must have the persistence layer
            DDL applied (see `src/load_project.py`).
        engine_version: Semver string identifying this engine build
            (stored on the run row for two-axis versioning).
        submission_version: String identifying which submission these
            results apply to. Caller's choice of identifier — could be a
            submission_id, a version label, or a content hash.
        triggered_by: Human or system identifier for who/what initiated
            the run. Free-form string.

    Raises:
        Re-raises any uncaught exception from evaluation. The run row is
        committed as 'failed' before re-raise, so the caller can read the
        error_message column for diagnostics.
    """
    parcels = project_data.get("project", {}).get("parcels", []) or []
    parcel_ids = [p.get("parcel_id") for p in parcels if p.get("parcel_id")]

    engine_run_id = str(uuid.uuid4())
    _insert_run_row(
        db_conn,
        engine_run_id=engine_run_id,
        project_id=project_id,
        engine_version=engine_version,
        submission_version=submission_version,
        triggered_by=triggered_by,
    )

    try:
        for parcel_id in parcel_ids:
            violations = evaluate_parcel(
                parcel_id=parcel_id,
                project_data=project_data,
                extracted_data=extracted_data,
                db_conn=db_conn,
                engine_run_id=engine_run_id,
            )
            for v in violations:
                _insert_violation_row(db_conn, v)
            db_conn.commit()  # per-parcel commit preserves partial progress
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("engine_run %s failed during evaluation: %s",
                     engine_run_id, e)
        _mark_run_failed(db_conn, engine_run_id, error_message=tb)
        raise

    summary = _compute_summary_stats(db_conn, engine_run_id)
    _mark_run_complete(db_conn, engine_run_id, summary_stats=summary)
    return engine_run_id


# ──────────────────────────────────────────────────────────────────────
# Public API — read path
# ──────────────────────────────────────────────────────────────────────

def load_violations_for_run(
    engine_run_id: str,
    db_conn: sqlite3.Connection,
) -> list[Violation]:
    """Reconstruct Violation objects from the violations table.

    JSON columns are deserialized; the integer override flag is converted
    back to bool. Rows are returned in `(parcel_id, rule_id)` order for
    stable presentation by downstream consumers (PDF generator, UI).
    """
    cur = db_conn.execute(
        """SELECT id, engine_run_id, parcel_id, rule_id, rule_type, verdict,
                  expected_value_json, actual_value_json, evidence_json,
                  notes, is_override_applied, failure_mode, error_fingerprint,
                  confidence
           FROM violations
           WHERE engine_run_id = ?
           ORDER BY parcel_id, rule_id""",
        (engine_run_id,),
    )
    out: list[Violation] = []
    for row in cur:
        (vid, run_id, parcel_id, rule_id, rule_type_str, verdict_str,
         expected_json, actual_json, evidence_json,
         notes, is_override_applied,
         failure_mode_str, error_fingerprint, confidence_str) = row
        out.append(Violation(
            violation_id=vid,
            engine_run_id=run_id,
            parcel_id=parcel_id,
            rule_id=rule_id,
            rule_type=RuleType.from_str(rule_type_str),
            verdict=Verdict.from_str(verdict_str),
            expected_value=_loads_or_none(expected_json),
            actual_value=_loads_or_none(actual_json),
            evidence=_loads_or_empty(evidence_json),
            notes=notes,
            is_override_applied=bool(is_override_applied),
            failure_mode=FailureMode.from_str(failure_mode_str or "none"),
            error_fingerprint=error_fingerprint,
            confidence=Confidence.from_str(confidence_str or "high"),
        ))
    return out


# ──────────────────────────────────────────────────────────────────────
# Internal — DB row helpers
# ──────────────────────────────────────────────────────────────────────

def _insert_run_row(
    db_conn: sqlite3.Connection, *,
    engine_run_id: str,
    project_id: str,
    engine_version: str,
    submission_version: str,
    triggered_by: str,
) -> None:
    db_conn.execute(
        """INSERT INTO engine_runs
             (id, project_id, engine_version, submission_version, status,
              triggered_by)
           VALUES (?, ?, ?, ?, 'running', ?)""",
        (engine_run_id, project_id, engine_version, submission_version,
         triggered_by),
    )
    db_conn.commit()


def _insert_violation_row(db_conn: sqlite3.Connection, v: Violation) -> None:
    db_conn.execute(
        """INSERT INTO violations
             (id, engine_run_id, parcel_id, rule_id, rule_type, verdict,
              expected_value_json, actual_value_json, evidence_json,
              notes, is_override_applied, failure_mode, error_fingerprint,
              confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            v.violation_id,
            v.engine_run_id,
            v.parcel_id,
            v.rule_id,
            v.rule_type.value,
            v.verdict.value,
            _dumps_or_none(v.expected_value),
            _dumps_or_none(v.actual_value),
            _dumps_or_none(v.evidence) if v.evidence else None,
            v.notes,
            1 if v.is_override_applied else 0,
            v.failure_mode.value,
            v.error_fingerprint,
            v.confidence.value,
        ),
    )


def _mark_run_complete(
    db_conn: sqlite3.Connection,
    engine_run_id: str,
    summary_stats: dict,
) -> None:
    db_conn.execute(
        """UPDATE engine_runs
             SET status = 'complete',
                 summary_stats_json = ?,
                 completed_at = CURRENT_TIMESTAMP
             WHERE id = ?""",
        (json.dumps(summary_stats, ensure_ascii=False), engine_run_id),
    )
    db_conn.commit()


def _mark_run_failed(
    db_conn: sqlite3.Connection,
    engine_run_id: str,
    error_message: str,
) -> None:
    db_conn.execute(
        """UPDATE engine_runs
             SET status = 'failed',
                 error_message = ?,
                 completed_at = CURRENT_TIMESTAMP
             WHERE id = ?""",
        (error_message, engine_run_id),
    )
    db_conn.commit()


# ──────────────────────────────────────────────────────────────────────
# Internal — summary stats
# ──────────────────────────────────────────────────────────────────────

# Verdicts that count as "failures" for the parcels_with_failures rollup.
_FAILURE_VERDICTS = {Verdict.FAIL.value, Verdict.FAIL_BORDERLINE.value}


def _compute_summary_stats(
    db_conn: sqlite3.Connection,
    engine_run_id: str,
) -> dict[str, Any]:
    """Compute summary stats by querying the violations table after all
    parcel evaluations have committed.

    Output shape:
      {
        "total_violations": int,
        "by_verdict": {"pass": int, "fail": int, ...},
          # all 7 keys, zero-filled
        "by_parcel": {"plot_1": {"pass": int, ...}, ...},
        "by_failure_mode": {"engine_error": int, "missing_data": int,
                            "ambiguous_rule": int,
                            "extraction_failure": int, "none": int},
          # all 5 keys, zero-filled. Counts ALL violations by their
          # failure_mode column, but only UNEVALUABLE rows can have a
          # non-'none' value.
        "by_confidence": {"high": int, "medium": int, "low": int},
          # all 3 keys, zero-filled. Reliability axis, orthogonal to
          # verdict and failure_mode.
        "error_fingerprint_clusters": {fingerprint: count, ...},
          # only fingerprints with count >= 1; sorted by descending count
          # in insertion order so consumers can iterate top-down.
        "parcels_evaluated": int,
        "parcels_with_failures": int,
      }
    """
    by_verdict: Counter[str] = Counter({v.value: 0 for v in Verdict})
    by_parcel: dict[str, Counter[str]] = defaultdict(
        lambda: Counter({v.value: 0 for v in Verdict})
    )
    by_failure_mode: Counter[str] = Counter({m.value: 0 for m in FailureMode})
    by_confidence: Counter[str] = Counter({c.value: 0 for c in Confidence})
    fingerprint_counts: Counter[str] = Counter()
    total = 0

    cur = db_conn.execute(
        """SELECT parcel_id, verdict, failure_mode, error_fingerprint,
                  confidence
           FROM violations WHERE engine_run_id = ?""",
        (engine_run_id,),
    )
    for parcel_id, verdict, failure_mode, fingerprint, confidence in cur:
        total += 1
        by_verdict[verdict] += 1
        by_parcel[parcel_id][verdict] += 1
        by_failure_mode[failure_mode or "none"] += 1
        by_confidence[confidence or "high"] += 1
        if fingerprint:
            fingerprint_counts[fingerprint] += 1

    parcels_with_failures = sum(
        1 for counts in by_parcel.values()
        if any(counts.get(v, 0) > 0 for v in _FAILURE_VERDICTS)
    )

    # Sort clusters by descending count so the largest incidents surface
    # first when consumers iterate. dict() preserves insertion order in
    # Python 3.7+, which is what we want.
    clusters_sorted = dict(sorted(
        fingerprint_counts.items(), key=lambda kv: (-kv[1], kv[0])))

    return {
        "total_violations": total,
        "by_verdict": dict(by_verdict),
        "by_parcel": {pid: dict(c) for pid, c in by_parcel.items()},
        "by_failure_mode": dict(by_failure_mode),
        "by_confidence": dict(by_confidence),
        "error_fingerprint_clusters": clusters_sorted,
        "parcels_evaluated": len(by_parcel),
        "parcels_with_failures": parcels_with_failures,
    }


# ──────────────────────────────────────────────────────────────────────
# Internal — JSON helpers
# ──────────────────────────────────────────────────────────────────────

def _dumps_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=_json_fallback)


def _loads_or_none(blob: str | None) -> Any:
    if blob is None or blob == "":
        return None
    return json.loads(blob)


def _loads_or_empty(blob: str | None) -> dict:
    if blob is None or blob == "":
        return {}
    out = json.loads(blob)
    return out if isinstance(out, dict) else {"_raw": out}


def _json_fallback(o: Any) -> Any:
    """Coerce non-JSON-native types to strings so dumps() never crashes."""
    if hasattr(o, "value"):
        return o.value  # Enum
    return str(o)
