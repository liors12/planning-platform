"""Translation tables: M2 indicator/confidence → engine enum values."""

from __future__ import annotations

from typing import Optional


# M2 compliance_indicator → engine verdict
_INDICATOR_TO_VERDICT = {
    "compliant": "pass",
    "non_compliant": "fail",            # NEW for content-scope after M4 override
    "requires_review": "requires_review",
    "missing": "not_submitted",
    "deferred_to_dwg": "requires_review",
}

# M2 confidence → engine confidence (uppercase)
_CONFIDENCE_MAP = {
    "high": "HIGH",
    "medium": "MEDIUM",                 # NEW value after M4 override
    "low": "LOW",                       # NEW value after M4 override
}


def m2_indicator_to_engine_verdict(indicator: Optional[str]) -> str:
    """Map M2 compliance_indicator to engine verdict. Unknown → requires_review."""
    return _INDICATOR_TO_VERDICT.get((indicator or "").lower(), "requires_review")


def m2_confidence_to_engine(confidence: Optional[str]) -> str:
    """Map M2 confidence (lowercase) to engine confidence (uppercase). Unknown → MEDIUM."""
    return _CONFIDENCE_MAP.get((confidence or "").lower(), "MEDIUM")
