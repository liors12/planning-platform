"""Compliance evaluator — main entry point.

Given a parcel, extracted data, and a DB connection, runs every applicable
rule through its type-specific evaluator and returns a list of `Violation`
objects (one per rule, including passes). The caller is responsible for
persisting results to the `violations` table.

Pipeline per parcel:
  1. Resolve rules via `rule_resolver.resolve_rules_for_parcel()`.
  2. For each rule:
     a. Check the not_applicable list — if rule_id is in
        `extracted_data['parcels'][parcel_id]['not_applicable_rules']`,
        emit a Violation with verdict=NOT_APPLICABLE and skip the
        type-specific evaluator.
     b. Otherwise dispatch to the evaluator for `rule.rule_type` via
        EVALUATORS dict.
     c. Wrap the dispatch in try/except — if the evaluator raises, emit
        a Violation with verdict=UNEVALUABLE and the exception message
        in `notes`. The run continues.
  3. Return the collected list.

Expected `extracted_data` shape (used by all evaluators)::

    {
        "parcels": {
            "<parcel_id>": {
                "numeric_values":      {<field_name>: <number>, ...},
                "documents_present":   {<doc_name>: <bool>, ...},
                "procedural_flags":    {<flag_name>: <bool|str>, ...},
                "geometry":            {...},                # placeholder
                "not_applicable_rules": [<rule_id>, ...],    # optional
            },
            ...
        }
    }

Real extraction comes from the PDF / DWG pipelines and will populate
this dict. For tests and early development, fixtures hand-build it.
"""
from __future__ import annotations

import logging
import sqlite3
import traceback
from typing import Callable

from .rule_resolver import resolve_rules_for_parcel
from .types import (
    FailureMode,
    Rule,
    RuleType,
    Verdict,
    Violation,
    compute_error_fingerprint,
)
from .evaluators import (
    numeric as _numeric,
    geometric as _geometric,
    document_presence as _document_presence,
    procedural as _procedural,
    qualitative as _qualitative,
)


logger = logging.getLogger(__name__)


# Type alias for evaluator functions. Each one takes (rule, extracted_data,
# parcel_id, engine_run_id) and returns a single Violation.
EvaluatorFn = Callable[[Rule, dict, str, str], Violation]


# Dispatch table: RuleType → evaluator function. The dispatcher in
# `evaluate_parcel` looks up the entry by rule.rule_type.value (string).
EVALUATORS: dict[RuleType, EvaluatorFn] = {
    RuleType.NUMERIC:           _numeric.evaluate,
    RuleType.GEOMETRIC:         _geometric.evaluate,
    RuleType.DOCUMENT_PRESENCE: _document_presence.evaluate,
    RuleType.PROCEDURAL:        _procedural.evaluate,
    RuleType.QUALITATIVE:       _qualitative.evaluate,
}

# Sanity guard: every RuleType must have a registered evaluator. This
# fires at import time so a future RuleType addition can't silently leave
# rules unevaluable.
_missing = set(RuleType) - set(EVALUATORS)
if _missing:
    raise RuntimeError(
        f"EVALUATORS dispatch table missing entries for: "
        f"{sorted(t.value for t in _missing)}"
    )


def evaluate_parcel(
    parcel_id: str,
    project_data: dict,
    extracted_data: dict,
    db_conn: sqlite3.Connection,
    engine_run_id: str,
) -> list[Violation]:
    """Evaluate every rule that applies to `parcel_id` and return Violations."""
    rules = resolve_rules_for_parcel(parcel_id, project_data, db_conn)

    parcel_block = extracted_data.get("parcels", {}).get(parcel_id, {}) or {}
    not_applicable_set = set(parcel_block.get("not_applicable_rules") or [])

    out: list[Violation] = []
    for rule in rules:
        if rule.rule_id in not_applicable_set:
            out.append(_make_not_applicable(rule, parcel_id, engine_run_id))
            continue

        evaluator = EVALUATORS.get(rule.rule_type)
        if evaluator is None:
            # Defensive — the import-time guard above should make this
            # impossible, but if it ever happens, surface UNEVALUABLE
            # rather than crashing the run.
            out.append(_make_unevaluable(
                rule, parcel_id, engine_run_id,
                note=f"no evaluator registered for rule_type "
                     f"{rule.rule_type.value!r}",
                failure_mode=FailureMode.AMBIGUOUS_RULE,
                fingerprint=compute_error_fingerprint(
                    f"dispatch:no_evaluator:{rule.rule_type.value}"),
            ))
            continue

        try:
            violation = evaluator(rule, extracted_data, parcel_id, engine_run_id)
        except Exception as e:
            logger.warning(
                "evaluator for rule %s raised %s: %s",
                rule.rule_id, type(e).__name__, e,
            )
            # Fingerprint = sha256(exception_type + first 200 chars of
            # message). Two violations that hit the same KeyError("x")
            # share a fingerprint so the PDF generator can fold them.
            fp_seed = f"engine_error:{type(e).__name__}:{str(e)[:200]}"
            out.append(_make_unevaluable(
                rule, parcel_id, engine_run_id,
                note=(f"evaluator raised {type(e).__name__}: {e}\n"
                      f"{traceback.format_exc(limit=3)}").strip(),
                failure_mode=FailureMode.ENGINE_ERROR,
                fingerprint=compute_error_fingerprint(fp_seed),
            ))
            continue

        out.append(violation)

    return out


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _make_not_applicable(
    rule: Rule, parcel_id: str, engine_run_id: str,
) -> Violation:
    return Violation(
        engine_run_id=engine_run_id,
        parcel_id=parcel_id,
        rule_id=rule.rule_id,
        rule_type=rule.rule_type,
        verdict=Verdict.NOT_APPLICABLE,
        expected_value=rule.parameters.get("description"),
        actual_value=None,
        evidence={
            "applies_when": rule.parameters.get("applies_when"),
        },
        notes=(f"rule does not apply to parcel {parcel_id!r} per "
                f"applies_when condition (or extractor's "
                f"not_applicable_rules list)"),
        is_override_applied=rule.is_overridden,
    )


def _make_unevaluable(
    rule: Rule, parcel_id: str, engine_run_id: str, note: str,
    failure_mode: FailureMode = FailureMode.NONE,
    fingerprint: str | None = None,
) -> Violation:
    return Violation(
        engine_run_id=engine_run_id,
        parcel_id=parcel_id,
        rule_id=rule.rule_id,
        rule_type=rule.rule_type,
        verdict=Verdict.UNEVALUABLE,
        expected_value=rule.parameters.get("description"),
        actual_value=None,
        evidence={},
        notes=note,
        is_override_applied=rule.is_overridden,
        failure_mode=failure_mode,
        error_fingerprint=fingerprint,
    )
