"""Eight automated checks on a critic_findings document.

Each check returns a CheckResult; the runner aggregates and exits non-zero
on any failure. Mirrors the M2 validation pattern.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .schema import (
    ALLOWED_CRITIC_INDICATORS,
    ALLOWED_CRITIC_VERDICTS,
    ALLOWED_M2_INDICATORS,
    ALLOWED_SEVERITIES,
    CriticFindings,
)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def _check_schema(document: Dict[str, Any]) -> CheckResult:
    try:
        CriticFindings.model_validate(document)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "1. schema_valid", False, f"Pydantic validation failed: {str(exc)[:200]}"
        )
    n = len(document.get("critic_findings", []))
    return CheckResult("1. schema_valid", True, f"{n} critic_findings OK")


def _check_clause_ids_in_vision(
    document: Dict[str, Any], known_clause_ids: set
) -> CheckResult:
    bad: List[str] = []
    for f in document.get("critic_findings", []):
        cid = f.get("clause_id")
        if cid not in known_clause_ids:
            bad.append(str(cid))
    if bad:
        return CheckResult(
            "2. clause_ids_in_vision",
            False,
            f"{len(bad)} critic_findings reference clause_id not in vision_findings: {bad[:5]}",
        )
    return CheckResult(
        "2. clause_ids_in_vision",
        True,
        f"all {len(document.get('critic_findings', []))} clause_ids resolve to M2 findings",
    )


def _check_source_pages_in_range(document: Dict[str, Any], page_count: int = 63) -> CheckResult:
    bad: List[Tuple[str, int]] = []
    for f in document.get("critic_findings", []):
        for p in f.get("m2_source_pages", []) or []:
            if not isinstance(p, int) or p < 1 or p > page_count:
                bad.append((f.get("clause_id"), p))
    if bad:
        return CheckResult(
            "3. source_pages_in_range",
            False,
            f"{len(bad)} out-of-range m2_source_pages (e.g. {bad[:3]})",
        )
    return CheckResult(
        "3. source_pages_in_range", True, f"all m2_source_pages in [1, {page_count}]"
    )


def _check_verdict_enum(document: Dict[str, Any]) -> CheckResult:
    bad: List[Tuple[str, Any]] = []
    for f in document.get("critic_findings", []):
        v = f.get("critic_verdict")
        if v not in ALLOWED_CRITIC_VERDICTS:
            bad.append((f.get("clause_id"), v))
    if bad:
        return CheckResult(
            "4. verdict_enum_valid",
            False,
            f"{len(bad)} critic_findings with bad verdict: {bad[:5]}",
        )
    return CheckResult("4. verdict_enum_valid", True, "all in {agree, disagree, cannot_determine}")


def _check_disagree_has_severity(document: Dict[str, Any]) -> CheckResult:
    """Severity must be set whenever verdict == disagree, null otherwise."""
    bad: List[Tuple[str, str, Any]] = []
    for f in document.get("critic_findings", []):
        v = f.get("critic_verdict")
        sev = f.get("disagreement_severity")
        if v == "disagree":
            if sev not in ALLOWED_SEVERITIES:
                bad.append((f.get("clause_id"), "disagree+missing_severity", sev))
        else:
            if sev is not None:
                bad.append((f.get("clause_id"), f"{v}+stray_severity", sev))
    if bad:
        return CheckResult(
            "5. disagree_has_severity",
            False,
            f"{len(bad)} findings violate severity rule (e.g. {bad[:3]})",
        )
    return CheckResult(
        "5. disagree_has_severity",
        True,
        "severity set iff verdict=disagree",
    )


def _check_disagree_has_extraction_value(document: Dict[str, Any]) -> CheckResult:
    """Critic must provide its own extraction_value when disagreeing."""
    bad: List[str] = []
    for f in document.get("critic_findings", []):
        if f.get("critic_verdict") == "disagree":
            cev = f.get("critic_extraction_value")
            if cev is None or cev == "":
                bad.append(f.get("clause_id"))
    if bad:
        return CheckResult(
            "6. disagree_has_extraction_value",
            False,
            f"{len(bad)} disagree findings missing critic_extraction_value: {bad[:5]}",
        )
    return CheckResult(
        "6. disagree_has_extraction_value",
        True,
        "every disagree has a critic_extraction_value",
    )


def _check_input_ref_sha256(
    document: Dict[str, Any], vision_findings_path: Optional[Path]
) -> CheckResult:
    """input_refs.vision_findings_sha256 must match the on-disk file (or be skipped)."""
    if vision_findings_path is None:
        return CheckResult(
            "7. input_refs_sha256_match",
            True,
            "skipped — no vision_findings_path provided",
        )
    if not vision_findings_path.exists():
        return CheckResult(
            "7. input_refs_sha256_match",
            False,
            f"vision_findings file not found at {vision_findings_path}",
        )
    actual = hashlib.sha256(vision_findings_path.read_bytes()).hexdigest()
    claimed = (document.get("input_refs") or {}).get("vision_findings_sha256")
    if actual != claimed:
        return CheckResult(
            "7. input_refs_sha256_match",
            False,
            f"vision_findings sha256 mismatch: doc={claimed!r}, disk={actual!r}",
        )
    return CheckResult(
        "7. input_refs_sha256_match",
        True,
        "vision_findings sha256 matches disk",
    )


def _check_summary_counts(document: Dict[str, Any]) -> CheckResult:
    findings = document.get("critic_findings", [])
    summary = document.get("summary") or {}
    n = len(findings)
    expected_agree = sum(1 for f in findings if f.get("critic_verdict") == "agree")
    expected_disagree = sum(1 for f in findings if f.get("critic_verdict") == "disagree")
    expected_cannot = sum(
        1 for f in findings if f.get("critic_verdict") == "cannot_determine"
    )
    issues: List[str] = []
    if summary.get("critiqued_count") != n:
        issues.append(f"critiqued_count={summary.get('critiqued_count')} vs actual={n}")
    if summary.get("agree_count") != expected_agree:
        issues.append(f"agree_count={summary.get('agree_count')} vs actual={expected_agree}")
    if summary.get("disagree_count") != expected_disagree:
        issues.append(f"disagree_count={summary.get('disagree_count')} vs actual={expected_disagree}")
    if summary.get("cannot_determine_count") != expected_cannot:
        issues.append(
            f"cannot_determine_count={summary.get('cannot_determine_count')} "
            f"vs actual={expected_cannot}"
        )
    if (expected_agree + expected_disagree + expected_cannot) != n:
        issues.append("verdict counts don't sum to critiqued_count")
    if issues:
        return CheckResult(
            "8. summary_counts_consistent",
            False,
            "; ".join(issues),
        )
    return CheckResult(
        "8. summary_counts_consistent",
        True,
        f"critiqued={n}, agree={expected_agree}, disagree={expected_disagree}, "
        f"cannot_determine={expected_cannot}",
    )


def run_all(
    document: Dict[str, Any],
    known_clause_ids: set,
    page_count: int = 63,
    vision_findings_path: Optional[Path] = None,
) -> List[CheckResult]:
    return [
        _check_schema(document),
        _check_clause_ids_in_vision(document, known_clause_ids),
        _check_source_pages_in_range(document, page_count),
        _check_verdict_enum(document),
        _check_disagree_has_severity(document),
        _check_disagree_has_extraction_value(document),
        _check_input_ref_sha256(document, vision_findings_path),
        _check_summary_counts(document),
    ]


def summarize(results: List[CheckResult]) -> Tuple[bool, str]:
    lines: List[str] = []
    all_ok = True
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        if not r.passed:
            all_ok = False
        lines.append(f"  [{status}] {r.name} — {r.detail}")
    return all_ok, "\n".join(lines)
