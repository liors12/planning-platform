"""Document-presence rule evaluator.

Checks whether a named document/section/field exists in the submission.
The rule's `parameter` is the lookup key into
`extracted_data['parcels'][parcel_id]['documents_present']`, which maps
document names to booleans (True = present, False = absent).

Verdicts:
  - PASS              the document is present
  - FAIL              the document is absent (key present, value False)
  - UNEVALUABLE       the key is missing from documents_present (extractor
                       didn't check) — caller can't tell pass from fail
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
    docs = parcel_block.get("documents_present", {}) or {}

    base = Violation(
        engine_run_id=engine_run_id,
        parcel_id=parcel_id,
        rule_id=rule.rule_id,
        rule_type=rule.rule_type,
        verdict=Verdict.UNEVALUABLE,
        expected_value=f"document/field {field_name!r} present",
        actual_value=docs.get(field_name),
        evidence={"document_key": field_name},
        is_override_applied=rule.is_overridden,
    )

    if field_name not in docs:
        base.failure_mode = FailureMode.MISSING_DATA
        base.error_fingerprint = compute_error_fingerprint(
            f"document_presence:missing:{field_name}")
        base.notes = (f"extractor did not record presence/absence for "
                       f"{field_name!r} on parcel {parcel_id!r}")
        return base

    if docs[field_name]:
        base.verdict = Verdict.PASS
    else:
        base.verdict = Verdict.FAIL
        base.notes = f"required document/field {field_name!r} is absent"
    return base
