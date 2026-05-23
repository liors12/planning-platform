"""Geometric rule evaluator — STUB.

Geometric rules (setbacks, building footprint within boundary, balcony
protrusion limits, etc.) require parsing DWG/DXF or shapefile geometry
and computing distances/intersections via Shapely. The DWG → DXF
conversion and integration is not yet wired end-to-end (see CONTEXT.md
Open Tasks: "Identify the building-line layer (קו בניין)").

For now this evaluator returns UNEVALUABLE with a fixed note so the
overall pipeline still produces a complete per-parcel verdict set —
geometric rules just defer to the human reviewer pending the DWG work.
"""
from __future__ import annotations

from ..types import FailureMode, Rule, Verdict, Violation, compute_error_fingerprint


GEOMETRIC_NOT_IMPLEMENTED_NOTE = (
    "geometric evaluation not yet implemented (DWG parsing pending)"
)

# Stable fingerprint for the stub-evaluator path: every geometric rule in
# the run hits this same fingerprint so the PDF generator can collapse the
# block into a single incident row instead of N copies of the same notice.
GEOMETRIC_STUB_FINGERPRINT = compute_error_fingerprint(
    "geometric:stub:dwg_parsing_pending")


def evaluate(
    rule: Rule,
    extracted_data: dict,
    parcel_id: str,
    engine_run_id: str,
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
        notes=GEOMETRIC_NOT_IMPLEMENTED_NOTE,
        is_override_applied=rule.is_overridden,
        failure_mode=FailureMode.MISSING_DATA,
        error_fingerprint=GEOMETRIC_STUB_FINGERPRINT,
    )
