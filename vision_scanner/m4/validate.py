"""8 automated checks on an M4 audit_results document."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .schema import ALLOWED_CONFIDENCES, ALLOWED_VERDICTS, M4AuditResults


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def _check_schema(document: Dict[str, Any]) -> CheckResult:
    try:
        M4AuditResults.model_validate(document)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "1. schema_valid", False, f"Pydantic validation failed: {str(exc)[:200]}"
        )
    n = len(document.get("content", []))
    return CheckResult("1. schema_valid", True, f"{n} content findings OK")


def _check_m2_clause_ids_resolve(
    document: Dict[str, Any], known_m2_clauses: set
) -> CheckResult:
    bad: List[Tuple[str, str]] = []
    for f in document.get("content", []):
        for cid in f.get("m4_m2_clause_ids", []) or []:
            if cid not in known_m2_clauses:
                bad.append((f.get("rule_code"), cid))
    if bad:
        return CheckResult(
            "2. m2_clause_ids_resolve",
            False,
            f"{len(bad)} m4_m2_clause_ids refs not in vision_findings: {bad[:5]}",
        )
    n = sum(len(f.get("m4_m2_clause_ids", []) or []) for f in document.get("content", []))
    return CheckResult(
        "2. m2_clause_ids_resolve", True, f"all {n} clause refs resolve"
    )


def _check_m3_disagreements_applied(
    document: Dict[str, Any],
    critic_doc: Optional[Dict[str, Any]],
    enabled_m2_clauses: set,
) -> CheckResult:
    """For every M3 critic disagreement whose clause is in the M4 enabled set
    AND maps to an engine rule, there should be a corresponding M4 finding
    with m4_override_source='m3_critic_disagreement'."""
    if critic_doc is None:
        return CheckResult(
            "3. m3_disagreements_applied", True, "skipped — no critic_doc provided"
        )
    disagree_clauses = {
        cf.get("clause_id")
        for cf in (critic_doc.get("critic_findings") or [])
        if cf.get("critic_verdict") == "disagree"
        and cf.get("clause_id") in enabled_m2_clauses
    }
    # Subtract sidecar-only clauses (they don't override an engine row)
    from .clause_mapping import MAPPINGS
    sidecar_clauses = {e["m2_clause_id"] for e in MAPPINGS if e["plot_scope"] == "sidecar"}
    expected_routed = disagree_clauses - sidecar_clauses

    applied = set()
    for f in document.get("content", []):
        if f.get("m4_override_source") == "m3_critic_disagreement":
            applied.update(f.get("m4_m2_clause_ids", []) or [])

    missing = expected_routed - applied
    if missing:
        return CheckResult(
            "3. m3_disagreements_applied",
            False,
            f"{len(missing)} critic disagreements not escalated to M4 verdicts: {sorted(missing)[:5]}",
        )
    return CheckResult(
        "3. m3_disagreements_applied",
        True,
        f"{len(expected_routed)} routed critic disagreements all escalated",
    )


def _check_verdict_enum(document: Dict[str, Any]) -> CheckResult:
    bad: List[Tuple[str, str]] = []
    for f in document.get("content", []):
        v = f.get("verdict")
        if v not in ALLOWED_VERDICTS:
            bad.append((f.get("rule_code"), v))
    if bad:
        return CheckResult(
            "4. verdict_enum_valid",
            False,
            f"{len(bad)} content findings with bad verdict: {bad[:5]}",
        )
    return CheckResult("4. verdict_enum_valid", True, "all content verdicts in extended enum")


def _check_engine_passthrough(
    document: Dict[str, Any], engine_doc: Optional[Dict[str, Any]]
) -> CheckResult:
    """For non-overridden findings, every original engine field is preserved."""
    if engine_doc is None:
        return CheckResult(
            "5. engine_passthrough_preserved", True, "skipped — no engine_doc provided"
        )
    engine_by_key: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
    for f in engine_doc.get("content", []) or []:
        engine_by_key[(f.get("rule_code"), f.get("ta_shetach_id"))] = f

    bad: List[Tuple[str, Optional[str], str]] = []
    for f in document.get("content", []):
        if f.get("m4_override_applied"):
            continue
        key = (f.get("rule_code"), f.get("ta_shetach_id"))
        orig = engine_by_key.get(key)
        if orig is None:
            bad.append((f.get("rule_code"), f.get("ta_shetach_id"), "no engine counterpart"))
            continue
        for field in ("rule_code", "rule_name_he", "ta_shetach_id", "verdict",
                      "confidence", "failure_mode"):
            if f.get(field) != orig.get(field):
                bad.append((f.get("rule_code"), f.get("ta_shetach_id"),
                            f"field {field} differs"))
    if bad:
        return CheckResult(
            "5. engine_passthrough_preserved",
            False,
            f"{len(bad)} non-overridden findings mutated: {bad[:3]}",
        )
    return CheckResult(
        "5. engine_passthrough_preserved",
        True,
        "all non-overridden findings preserve engine fields",
    )


def _check_input_refs_sha256(
    document: Dict[str, Any],
    engine_path: Optional[Path],
    vision_path: Optional[Path],
    critic_path: Optional[Path],
) -> CheckResult:
    issues: List[str] = []
    refs = document.get("m4_input_refs") or {}
    pairs = [
        ("engine_audit_results_sha256", engine_path),
        ("vision_findings_sha256", vision_path),
        ("critic_findings_sha256", critic_path),
    ]
    for key, path in pairs:
        if path is None or not path.exists():
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        claimed = refs.get(key)
        if actual != claimed:
            issues.append(f"{key}: doc={claimed!r} disk={actual!r}")
    if issues:
        return CheckResult(
            "6. input_refs_sha256_match",
            False,
            "; ".join(issues),
        )
    return CheckResult(
        "6. input_refs_sha256_match",
        True,
        "all provided input_refs sha256 match disk",
    )


def _check_summary_consistent(document: Dict[str, Any]) -> CheckResult:
    summary = document.get("m4_summary") or {}
    findings = document.get("content", [])
    actual_after = Counter(f.get("verdict") for f in findings)
    claimed_after = summary.get("verdict_distribution_after") or {}
    if {k: v for k, v in claimed_after.items() if v} != {k: v for k, v in actual_after.items() if v}:
        return CheckResult(
            "7. verdict_distribution_consistent",
            False,
            f"after: actual={dict(actual_after)} vs claimed={claimed_after}",
        )
    overridden_actual = sum(1 for f in findings if f.get("m4_override_applied"))
    if summary.get("overridden_count") != overridden_actual:
        return CheckResult(
            "7. verdict_distribution_consistent",
            False,
            f"overridden_count claimed={summary.get('overridden_count')} actual={overridden_actual}",
        )
    return CheckResult(
        "7. verdict_distribution_consistent",
        True,
        f"after={dict(actual_after)}, overridden={overridden_actual}",
    )


def _check_no_orphan_overrides(document: Dict[str, Any]) -> CheckResult:
    """No finding has m4_override_applied=True with empty m4_m2_clause_ids.

    Exception: m4_override_source='hedged_reasoning_escalation' (Task #32 fix)
    is derived from engine text alone, no M2 clause needed.
    """
    bad: List[str] = []
    for f in document.get("content", []):
        if not f.get("m4_override_applied"):
            continue
        if f.get("m4_override_source") == "hedged_reasoning_escalation":
            continue
        if not (f.get("m4_m2_clause_ids") or []):
            bad.append(f"{f.get('rule_code')}:{f.get('ta_shetach_id')}")
    if bad:
        return CheckResult(
            "8. no_orphan_overrides",
            False,
            f"{len(bad)} overrides with empty m4_m2_clause_ids: {bad[:5]}",
        )
    return CheckResult(
        "8. no_orphan_overrides", True, "every override has clause_id traceability"
    )


def _check_hedged_escalations_not_pass(document: Dict[str, Any]) -> CheckResult:
    """Every finding with m4_override_source='hedged_reasoning_escalation' must
    NOT have verdict='pass' (the whole point of escalation). It can have other
    verdicts (e.g. requires_review, or pass-flipped-back-by-M2-override) — but
    if the source is still 'hedged_reasoning_escalation', the verdict must NOT
    be the original 'pass'."""
    bad: List[str] = []
    for f in document.get("content", []):
        if f.get("m4_override_source") == "hedged_reasoning_escalation":
            if f.get("verdict") == "pass":
                bad.append(f"{f.get('rule_code')}:{f.get('ta_shetach_id')}")
    if bad:
        return CheckResult(
            "9. hedged_escalations_not_pass",
            False,
            f"{len(bad)} escalations still show pass: {bad[:5]}",
        )
    return CheckResult(
        "9. hedged_escalations_not_pass",
        True,
        "all hedged_reasoning_escalation findings escaped 'pass'",
    )


def run_all(
    document: Dict[str, Any],
    known_m2_clauses: set,
    *,
    engine_doc: Optional[Dict[str, Any]] = None,
    critic_doc: Optional[Dict[str, Any]] = None,
    engine_path: Optional[Path] = None,
    vision_path: Optional[Path] = None,
    critic_path: Optional[Path] = None,
    enabled_m2_clauses: Optional[set] = None,
) -> List[CheckResult]:
    enabled_m2_clauses = enabled_m2_clauses or set()
    return [
        _check_schema(document),
        _check_m2_clause_ids_resolve(document, known_m2_clauses),
        _check_m3_disagreements_applied(document, critic_doc, enabled_m2_clauses),
        _check_verdict_enum(document),
        _check_engine_passthrough(document, engine_doc),
        _check_input_refs_sha256(document, engine_path, vision_path, critic_path),
        _check_summary_consistent(document),
        _check_no_orphan_overrides(document),
        _check_hedged_escalations_not_pass(document),
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
