"""Discipline-policy compliance checker.

Reads `discipline_rules.json` and evaluates each rule against the submission
PDF using pure-Python checks:

  * `text_pattern`     — any-of substring match across the full extracted text
  * `annex_required`   — TOC/text keyword search for an annex's existence
  * `manual_review`    — deterministic `requires_review` (engineer must verify)

In v8j we overlay Cowork's hand-extracted `discipline_findings.json` from the
submission directory: when a finding matches the engine's rule (by Hebrew
name, via the tiered matcher in `discipline_findings.py`), the JSON's verdict
+ evidence + compliance note take precedence over the keyword-search default.
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz  # PyMuPDF
from compliance_engine.text_utils import patch_rtl_artifacts

from .discipline_findings import find_finding, load_discipline_findings


VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_REQUIRES_REVIEW = "requires_review"
VERDICT_NOT_SUBMITTED = "not_submitted"
VERDICT_UNEVALUABLE = "unevaluable"

FAILURE_NONE = "NONE"
FAILURE_NOT_PROVIDED = "DOCUMENT_NOT_PROVIDED"
FAILURE_POLICY = "POLICY_VIOLATION"
FAILURE_ENGINE = "ENGINE_ERROR"

# Map Cowork JSON verdicts → engine taxonomy.
_VERDICT_MAP = {
    "pass": VERDICT_PASS,
    "fail": VERDICT_FAIL,
    "requires_review": VERDICT_REQUIRES_REVIEW,
    "not_submitted": VERDICT_NOT_SUBMITTED,
}


def run_discipline_checks(
    pdf_path: Path,
    rules_path: Path | None = None,
    *,
    submission_dir: Path | None = None,
) -> list[dict]:
    rules_path = Path(rules_path) if rules_path else (Path(__file__).resolve().parent.parent / "discipline_rules.json")
    rules_data = json.loads(rules_path.read_text(encoding="utf-8"))
    rules = rules_data["rules"]

    text_by_page, page_count = _extract_text(pdf_path)
    full_text = "\n".join(text_by_page.values())

    findings_doc = load_discipline_findings(submission_dir or pdf_path.parent)

    results: list[dict] = []
    for rule in rules:
        try:
            finding = find_finding(findings_doc, rule.get("rule_name_he", ""))
            if finding is not None:
                results.append(_from_finding(rule, finding))
            else:
                results.append(_evaluate(rule, full_text, text_by_page, page_count))
        except Exception as exc:  # noqa: BLE001
            results.append(_engine_error(rule, f"{type(exc).__name__}: {exc}"))

    results.sort(key=lambda r: (r["discipline"], r["rule_code"]))
    return results


def _extract_text(pdf_path: Path) -> tuple[dict[int, str], int]:
    doc = fitz.open(str(pdf_path))
    try:
        return (
            {i + 1: patch_rtl_artifacts(p.get_text("text") or "") for i, p in enumerate(doc)},
            doc.page_count,
        )
    finally:
        doc.close()


def _from_finding(rule: dict, finding: dict) -> dict:
    """Build an engine result from a Cowork JSON finding (the source of truth)."""
    raw_verdict = (finding.get("verdict") or "").strip().lower()
    verdict = _VERDICT_MAP.get(raw_verdict, VERDICT_REQUIRES_REVIEW)
    evidence_pages = finding.get("evidence_pages") or []
    evidence_visual = (finding.get("evidence_visual") or "").strip()
    compliance_note = (finding.get("compliance_note") or "").strip()

    failure_mode = FAILURE_NONE
    if verdict == VERDICT_NOT_SUBMITTED:
        failure_mode = FAILURE_NOT_PROVIDED
    elif verdict == VERDICT_FAIL:
        failure_mode = FAILURE_POLICY

    # Renderer-facing note: prepend page list to compliance_note.
    if evidence_pages and compliance_note:
        notes_he = f"(עמ' {', '.join(str(p) for p in evidence_pages)}) {compliance_note}"
    elif evidence_pages:
        notes_he = f"(עמ' {', '.join(str(p) for p in evidence_pages)})"
    else:
        notes_he = compliance_note or rule.get("policy_he", "")

    return {
        "rule_code": rule["rule_code"],
        "discipline": rule["discipline"],
        "rule_name_he": rule.get("rule_name_he", rule["rule_code"]),
        "verdict": verdict,
        "failure_mode": failure_mode,
        "confidence": "HIGH",
        "evidence": {
            "source": "cowork_discipline_findings_v24.3",
            "evidence_pages": evidence_pages,
            "evidence_visual": evidence_visual,
            "compliance_note": compliance_note,
            "matched_rule_hebrew": finding.get("rule_hebrew", ""),
        },
        "evidence_visual": evidence_visual,
        "evidence_pages": evidence_pages,
        "compliance_note": compliance_note,
        "notes_he": notes_he,
        "remediation_he": rule.get("remediation_he", ""),
        "required_artifact_he": rule.get("required_artifact_he", ""),
        "booklet_section": rule.get("booklet_section", ""),
        "booklet_pages": rule.get("booklet_pages", []),
        "severity": rule.get("severity", "minor"),
    }


def _evaluate(rule: dict, full_text: str, text_by_page: dict[int, str], page_count: int) -> dict:
    check_type = rule["check_type"]
    spec = rule.get("check_spec", {}) or {}
    discipline = rule["discipline"]

    if check_type == "text_pattern":
        terms = spec.get("any_of") or []
        hits = {t: [] for t in terms}
        for t in terms:
            for pg, txt in text_by_page.items():
                if t in txt:
                    hits[t].append(pg)
        found = any(hits[t] for t in terms)
        if found:
            verdict = rule.get("verdict_on_pass", VERDICT_PASS)
            failure = FAILURE_NONE
            r = _result(rule, verdict, failure_mode=failure, evidence={
                "check_type": "text_pattern",
                "terms": terms,
                "matched_pages": {t: hits[t] for t in terms if hits[t]},
                "found_any": True,
            })
            return r
        # Not found by keyword search. v8i: emit `requires_review` not `not_submitted` —
        # the artifact may exist visually (colored areas, symbols, layout) that text
        # extraction can't detect. The honest verdict is "needs visual verification".
        verdict = VERDICT_REQUIRES_REVIEW
        r = _result(rule, verdict, evidence={
            "check_type": "text_pattern",
            "terms": terms,
            "matched_pages": {},
            "found_any": False,
        })
        # M7.6 Part A — architect-facing fallback. No staff-direction, no
        # automation framing. Tells the architect what's expected in the
        # submission, not what the engineer needs to verify.
        r["notes_he"] = (
            'יש להציג את הפריט באופן ברור בתכניות הפיתוח / החזיתות בהגשה הבאה.'
        )
        return r

    if check_type == "annex_required":
        keywords = spec.get("annex_keywords") or []
        hits = {k: [] for k in keywords}
        for k in keywords:
            for pg, txt in text_by_page.items():
                if k in txt:
                    hits[k].append(pg)
        found = any(hits[k] for k in keywords)
        if found:
            verdict = rule.get("verdict_on_pass", VERDICT_PASS)
            failure = FAILURE_NONE
        else:
            verdict = rule.get("verdict_on_fail", VERDICT_NOT_SUBMITTED)
            failure = FAILURE_NOT_PROVIDED
        return _result(rule, verdict, failure_mode=failure, evidence={
            "check_type": "annex_required",
            "annex_keywords": keywords,
            "matched_pages": {k: hits[k] for k in keywords if hits[k]},
            "annex_found": found,
        })

    if check_type == "manual_review":
        verdict = rule.get("verdict_on_fail", VERDICT_REQUIRES_REVIEW)
        return _result(rule, verdict, evidence={
            "check_type": "manual_review",
            "review_instructions_he": spec.get("review_instructions_he", ""),
        })

    return _engine_error(rule, f"unknown check_type: {check_type}")


def _result(rule: dict, verdict: str, *, failure_mode: str = FAILURE_NONE, evidence: dict | None = None) -> dict:
    return {
        "rule_code": rule["rule_code"],
        "discipline": rule["discipline"],
        "rule_name_he": rule.get("rule_name_he", rule["rule_code"]),
        "verdict": verdict,
        "failure_mode": failure_mode,
        "confidence": "HIGH",
        "evidence": evidence or {},
        "notes_he": rule.get("policy_he", ""),
        "remediation_he": rule.get("remediation_he", ""),
        "required_artifact_he": rule.get("required_artifact_he", ""),
        "booklet_section": rule.get("booklet_section", ""),
        "booklet_pages": rule.get("booklet_pages", []),
        "severity": rule.get("severity", "minor"),
    }


def _engine_error(rule: dict, message: str) -> dict:
    return {
        "rule_code": rule["rule_code"],
        "discipline": rule.get("discipline", "unknown"),
        "rule_name_he": rule.get("rule_name_he", rule["rule_code"]),
        "verdict": VERDICT_UNEVALUABLE,
        "failure_mode": FAILURE_ENGINE,
        "confidence": "HIGH",
        "evidence": {"error": message},
        "notes_he": rule.get("policy_he", ""),
        "remediation_he": "",
        "required_artifact_he": rule.get("required_artifact_he", ""),
        "booklet_section": rule.get("booklet_section", ""),
        "booklet_pages": rule.get("booklet_pages", []),
        "severity": rule.get("severity", "minor"),
    }
