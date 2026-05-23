"""Procedural rule evaluator.

Checks that a workflow step / procedural attribute matches the rule's
expectation. Supports two flavors:

  1. Boolean flag check — rule asks "did step X happen?", extractor
     reports True/False under
     `extracted_data['parcels'][parcel_id]['procedural_flags'][key]`.

  2. Equality check — rule asks "is the value equal to a specific
     string?" (e.g., plan_scale should be "1:250"). Rule's
     `threshold_text` carries the expected value; extractor's
     `procedural_flags[key]` carries the actual value.

The rule's `parameter` is the lookup key. If absent, falls back to the
rule_id itself.

Verdicts:
  - PASS          flag is True (boolean check) OR actual == expected
  - FAIL          flag is False OR actual != expected
  - UNEVALUABLE   the key is missing from procedural_flags
"""
from __future__ import annotations

from ..types import FailureMode, Rule, Verdict, Violation, compute_error_fingerprint


def evaluate(
    rule: Rule,
    extracted_data: dict,
    parcel_id: str,
    engine_run_id: str,
) -> Violation:
    field_name = rule.parameters.get("parameter") or rule.rule_id
    parcel_block = extracted_data.get("parcels", {}).get(parcel_id, {}) or {}
    flags = parcel_block.get("procedural_flags", {}) or {}

    expected_text = rule.parameters.get("threshold_text")
    operator = rule.parameters.get("operator")

    base = Violation(
        engine_run_id=engine_run_id,
        parcel_id=parcel_id,
        rule_id=rule.rule_id,
        rule_type=rule.rule_type,
        verdict=Verdict.UNEVALUABLE,
        expected_value=(expected_text if expected_text is not None
                         else f"procedural flag {field_name!r} satisfied"),
        actual_value=flags.get(field_name),
        evidence={"flag_key": field_name},
        is_override_applied=rule.is_overridden,
    )

    if field_name not in flags:
        base.failure_mode = FailureMode.MISSING_DATA
        base.error_fingerprint = compute_error_fingerprint(
            f"procedural:missing:{field_name}")
        base.notes = (f"extractor did not record procedural flag "
                       f"{field_name!r} on parcel {parcel_id!r}")
        return base

    actual = flags[field_name]

    # Equality check: rule has threshold_text → compare strings.
    if expected_text is not None:
        if operator in ("!=", "≠"):
            passed = (str(actual) != expected_text)
        else:
            passed = (str(actual) == expected_text)
        base.verdict = Verdict.PASS if passed else Verdict.FAIL
        if not passed:
            base.notes = (f"procedural flag {field_name!r} = {actual!r}; "
                           f"expected {('!=' if operator in ('!=', '≠') else '==')} "
                           f"{expected_text!r}")
        return base

    # Boolean flag check.
    if isinstance(actual, bool):
        base.verdict = Verdict.PASS if actual else Verdict.FAIL
        if not actual:
            base.notes = f"procedural flag {field_name!r} is False"
        return base

    # Truthy fallback when extractor stored a non-bool.
    base.verdict = Verdict.PASS if actual else Verdict.FAIL
    return base
