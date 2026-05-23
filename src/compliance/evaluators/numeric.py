"""Numeric rule evaluator.

Compares an extracted numeric value against the rule's threshold using the
rule's operator. Produces FAIL_BORDERLINE when the value fails the rule
but lands within a tolerance band of the threshold; produces PASS_WITH_NOTE
when the value passes but is within the same band on the satisfying side.

Rule parameters consumed:
  - parameter (str): the key under extracted_data['parcels'][parcel_id]
                     ['numeric_values'] to read the actual value from.
                     If absent, falls back to the rule_id itself.
  - operator  (str): one of '<=', '<', '>=', '>', '=', '==', '!='. For
                     range checks, use 'range' with min_value / max_value.
  - threshold (float|int): the value to compare against. For range
                            checks, ignored — use min_value / max_value.
  - threshold_text (str|None): set when the rule's threshold is non-
                                numeric (e.g. "1:250"). Numeric evaluator
                                returns UNEVALUABLE for these — they
                                belong to the procedural evaluator.
  - tolerance_pct (float, default 2.0): borderline band as a percentage
                                          of threshold. fail_borderline
                                          fires when |actual - threshold|
                                          / threshold ≤ tolerance_pct/100
                                          AND the rule failed.
"""
from __future__ import annotations

from typing import Any

from ..types import FailureMode, Rule, Verdict, Violation, compute_error_fingerprint


DEFAULT_TOLERANCE_PCT = 2.0


def evaluate(
    rule: Rule,
    extracted_data: dict,
    parcel_id: str,
    engine_run_id: str,
) -> Violation:
    params = rule.parameters
    field_name = params.get("parameter") or rule.rule_id
    parcel_block = extracted_data.get("parcels", {}).get(parcel_id, {}) or {}
    numeric_values = parcel_block.get("numeric_values", {}) or {}
    actual = numeric_values.get(field_name)

    operator = params.get("operator")
    threshold = params.get("threshold")
    threshold_text = params.get("threshold_text")
    tolerance_pct = float(params.get("tolerance_pct") or DEFAULT_TOLERANCE_PCT)

    base = _build_base_violation(rule, parcel_id, engine_run_id, actual,
                                 expected=_format_expected(operator, threshold,
                                                           threshold_text, params))

    # If the rule has no numeric threshold (text only), this evaluator
    # can't help — the procedural evaluator should handle it.
    if threshold is None and threshold_text is not None:
        base.verdict = Verdict.UNEVALUABLE
        base.failure_mode = FailureMode.AMBIGUOUS_RULE
        base.error_fingerprint = compute_error_fingerprint(
            f"numeric:ambiguous:threshold_text:{rule.rule_id}")
        base.notes = (f"numeric evaluator cannot handle threshold_text "
                       f"{threshold_text!r}; route this rule to the "
                       f"procedural evaluator")
        return base

    if actual is None:
        base.verdict = Verdict.UNEVALUABLE
        base.failure_mode = FailureMode.MISSING_DATA
        base.error_fingerprint = compute_error_fingerprint(
            f"numeric:missing:{field_name}")
        base.notes = (f"no extracted numeric value for "
                       f"parcels[{parcel_id!r}].numeric_values[{field_name!r}]")
        return base

    # Range check: rule.parameters has min_value AND max_value.
    if operator == "range" or ("min_value" in params and "max_value" in params
                                and operator in (None, "range")):
        min_v = params.get("min_value")
        max_v = params.get("max_value")
        if min_v is None or max_v is None:
            base.verdict = Verdict.UNEVALUABLE
            base.failure_mode = FailureMode.AMBIGUOUS_RULE
            base.error_fingerprint = compute_error_fingerprint(
                f"numeric:ambiguous:range_bounds:{rule.rule_id}")
            base.notes = "range rule missing min_value or max_value"
            return base
        passed = (min_v <= actual <= max_v)
        base.expected_value = f"{min_v} ≤ x ≤ {max_v}"
        return _decorate_with_borderline(base, passed, actual,
                                          edge=_nearest_edge(actual, min_v, max_v),
                                          tolerance_pct=tolerance_pct)

    if operator is None or threshold is None:
        base.verdict = Verdict.UNEVALUABLE
        base.failure_mode = FailureMode.AMBIGUOUS_RULE
        base.error_fingerprint = compute_error_fingerprint(
            f"numeric:ambiguous:operator_or_threshold:{rule.rule_id}")
        base.notes = "rule missing operator or threshold"
        return base

    try:
        passed = _compare(actual, operator, threshold)
    except ValueError as e:
        base.verdict = Verdict.UNEVALUABLE
        base.failure_mode = FailureMode.AMBIGUOUS_RULE
        base.error_fingerprint = compute_error_fingerprint(
            f"numeric:ambiguous:operator:{operator!r}")
        base.notes = f"comparison failed: {e}"
        return base

    return _decorate_with_borderline(base, passed, actual,
                                      edge=threshold,
                                      tolerance_pct=tolerance_pct)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _compare(actual: float, operator: str, threshold: float) -> bool:
    if operator in ("<=", "≤"): return actual <= threshold
    if operator == "<":          return actual < threshold
    if operator in (">=", "≥"): return actual >= threshold
    if operator == ">":          return actual > threshold
    if operator in ("=", "=="):  return actual == threshold
    if operator in ("!=", "≠"):  return actual != threshold
    raise ValueError(f"unknown operator {operator!r}")


def _decorate_with_borderline(
    base: Violation,
    passed: bool,
    actual: float,
    edge: float,
    tolerance_pct: float,
) -> Violation:
    """Set verdict to PASS / PASS_WITH_NOTE / FAIL / FAIL_BORDERLINE
    based on closeness to the rule's edge (threshold or range boundary)."""
    if edge == 0:
        # Avoid divide-by-zero — treat any numeric drift as "exact" territory.
        within_band = (actual == edge)
    else:
        within_band = abs(actual - edge) / abs(edge) * 100.0 <= tolerance_pct

    if passed and within_band:
        base.verdict = Verdict.PASS_WITH_NOTE
        base.notes = (f"value {actual} passes but is within {tolerance_pct}% "
                       f"of edge {edge}")
    elif passed:
        base.verdict = Verdict.PASS
    elif within_band:
        base.verdict = Verdict.FAIL_BORDERLINE
        base.notes = (f"value {actual} fails but is within {tolerance_pct}% "
                       f"of edge {edge}")
    else:
        base.verdict = Verdict.FAIL
    return base


def _nearest_edge(actual: float, min_v: float, max_v: float) -> float:
    return min_v if abs(actual - min_v) <= abs(actual - max_v) else max_v


def _format_expected(operator, threshold, threshold_text, params) -> Any:
    if operator == "range" or ("min_value" in params and "max_value" in params):
        return f"{params.get('min_value')} ≤ x ≤ {params.get('max_value')}"
    if threshold_text is not None and threshold is None:
        return threshold_text
    if operator and threshold is not None:
        return f"{operator} {threshold}"
    return None


def _build_base_violation(
    rule: Rule,
    parcel_id: str,
    engine_run_id: str,
    actual: Any,
    expected: Any,
) -> Violation:
    return Violation(
        engine_run_id=engine_run_id,
        parcel_id=parcel_id,
        rule_id=rule.rule_id,
        rule_type=rule.rule_type,
        verdict=Verdict.UNEVALUABLE,  # default; caller mutates
        expected_value=expected,
        actual_value=actual,
        evidence=dict(rule.parameters.get("_evidence") or {}),
        is_override_applied=rule.is_overridden,
    )
