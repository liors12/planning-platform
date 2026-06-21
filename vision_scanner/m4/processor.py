"""Core M4 override loop.

Reads engine audit_results + M2 vision_findings + M3 critic_findings, and
produces an M4AuditResults document (audit_results.m4.json).

Override precedence per finding (rule_code × ta_shetach_id):
  1. If ANY matching M2 finding has a critic verdict of "disagree" →
     escalate to requires_review (M3 critic policy, per Fix C).
  2. Else if ANY matching M2 finding has confidence=="high" →
     override verdict using the highest-confidence finding's compliance_indicator.
  3. Else if matching M2 findings exist (but only medium/low confidence) →
     annotate (notes_he) but DO NOT override verdict.
  4. Else → passthrough (engine output unchanged for this row).
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .clause_mapping import all_enabled_clauses, select_matches, sidecar_only_entries
from .translator import m2_confidence_to_engine, m2_indicator_to_engine_verdict  # noqa: F401


M4_VERSION = "m4-v1"


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _index_critic_findings(critic_doc: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Index critic findings by M2 clause_id (one clause may have multiple critic findings)."""
    idx: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for cf in critic_doc.get("critic_findings", []) or []:
        cid = cf.get("clause_id")
        if cid:
            idx[cid].append(cf)
    return idx


def _critic_verdict_for_m2(
    m2_finding: Dict[str, Any],
    critic_index: Dict[str, List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Pick the critic finding that matches this M2 finding most closely.

    A critic finding matches when it shares the same clause_id AND the same
    m2_source_pages tuple. Falls back to first critic for the clause if no
    page match.
    """
    cid = m2_finding.get("clause_id")
    if not cid or cid not in critic_index:
        return None
    candidates = critic_index[cid]
    m2_pages = tuple(m2_finding.get("source_pages") or [])
    for c in candidates:
        c_pages = tuple(c.get("m2_source_pages") or [])
        if c_pages == m2_pages:
            return c
    return candidates[0]


def _pick_best_m2(matches: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pick the M2 finding with the highest confidence; tie-break by clause_id order."""
    rank = {"high": 3, "medium": 2, "low": 1}
    return sorted(
        matches,
        key=lambda m: (
            -rank.get((m.get("confidence") or "").lower(), 0),
            m.get("clause_id") or "",
        ),
    )[0]


def _empty_m4_extras() -> Dict[str, Any]:
    return {
        "m4_override_applied": False,
        "m4_override_source": None,
        "m4_m2_clause_ids": [],
        "m4_m3_critic_verdict": None,
        "m4_evidence_pages": [],
        "m4_evidence_bboxes": [],
    }


def _normalize_engine_finding(f: Dict[str, Any]) -> Dict[str, Any]:
    """Add M4 extra fields with defaults to an engine finding."""
    out = dict(f)
    out.setdefault("confidence", "HIGH")
    out.setdefault("failure_mode", "NONE")
    out.setdefault("evidence", {})
    out.setdefault("notes_he", "")
    out.setdefault("remediation_he", "")
    out.update(_empty_m4_extras())
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Task #32 fix — hedged-pass escalation
# ─────────────────────────────────────────────────────────────────────────────
# When the engine emits `pass` but its own reasoning admits incomplete
# verification (e.g. "אימות התאמה מדויקת לתקן … לא קיימת בהגשה זו"), escalate
# to `requires_review`. M4 override logic runs AFTER this step and can still
# flip back to `pass` when a high-confidence M2 finding supports it.

HEDGED_REASONING_MARKERS = [
    "ראשונית",
    "לא ניתן לאמת",
    "דורש טבלת",
    "אינו כולל",
    "נדרשת השלמה",
    "לא קיימת בהגשה",
    "preliminary",
    "cannot be verified",
]


def escalate_hedged_pass_verdicts(
    finding: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    """Return (possibly-escalated finding, was_escalated)."""
    if finding.get("verdict") != "pass":
        return finding, False
    reasoning = (finding.get("notes_he") or "")
    if not any(marker in reasoning for marker in HEDGED_REASONING_MARKERS):
        return finding, False
    escalated = _normalize_engine_finding(finding)
    escalated["verdict"] = "requires_review"
    escalated["m4_override_applied"] = True
    escalated["m4_override_source"] = "hedged_reasoning_escalation"
    escalated["notes_he"] = _append_note(
        finding.get("notes_he"),
        "הציון 'תקין' שונה ל'דורש בירור' מאחר שאימות מדויק "
        "לתקן דורש מידע נוסף שאינו קיים בהגשה.",
    )
    return escalated, True


def _is_unambiguous_numeric_pass(raw_f: Dict[str, Any]) -> bool:
    """Bug A guard predicate. True iff the engine ran a deterministic
    submission ≤ schema comparison and the comparison holds mathematically.

    When this returns True for a finding the critic disagreed with, the
    critic's concern (about table format / evidence provenance) is a real
    issue but should NOT override the verdict — it belongs in a sidecar
    entry for the מהנדס/ת to review.
    """
    if raw_f.get("verdict") != "pass":
        return False
    ev = raw_f.get("evidence") or {}
    if ev.get("comparison") != "submission_le_schema":
        return False
    sv = ev.get("submission_value")
    schv = ev.get("schema_value")
    if sv is None or schv is None:
        return False
    try:
        return float(sv) <= float(schv)
    except (TypeError, ValueError):
        return False


def _is_dwg_deferred(raw_f: Dict[str, Any]) -> bool:
    """Bug B guard predicate. True iff the engine explicitly deferred this
    check because DWG parsing isn't implemented. M2's partial sub-rule
    evidence (e.g. visually confirming ONE setback) MUST NOT flip the engine
    verdict to pass — many other setbacks remain unverified.
    """
    ev = raw_f.get("evidence") or {}
    reason = ev.get("reason") or ""
    return "DWG parsing not implemented" in reason


def _parse_plot_int(plot_id: Optional[str]) -> Optional[int]:
    """'plot_1' → 1, 'plot_20' → 20, None/other → None."""
    if not plot_id or not isinstance(plot_id, str):
        return None
    if plot_id.startswith("plot_"):
        try:
            return int(plot_id[5:])
        except ValueError:
            return None
    return None


def process_engine_findings(
    engine_findings: List[Dict[str, Any]],
    m2_findings: List[Dict[str, Any]],
    critic_index: Dict[str, List[Dict[str, Any]]],
    *,
    enabled_clause_ids: Optional[set] = None,
) -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
    """Override engine findings using M2 + critic data.

    Order of operations per finding:
      1. Task #32 hedged-pass escalation (runs first; may flip pass→requires_review)
      2. M3 critic disagreement (escalate to requires_review if any),
         UNLESS Bug A guard fires — then keep pass, spawn sidecar
      3. M2 high-confidence override (may flip back to pass / non_compliant / etc),
         UNLESS Bug B guard fires — then annotate only, keep engine verdict
      4. M2 medium/low annotation (no verdict change)

    Returns (m4_findings, list_of_critic_clause_ids_actually_applied,
             extra_sidecars_from_bug_a_guard).
    """
    if enabled_clause_ids is None:
        enabled_clause_ids = all_enabled_clauses()

    out: List[Dict[str, Any]] = []
    critic_applied: List[str] = []
    extra_sidecars: List[Dict[str, Any]] = []

    for raw_f in engine_findings:
        # Step 1 — Task #32 hedged-pass escalation, applied to the raw engine finding
        f, was_escalated = escalate_hedged_pass_verdicts(raw_f)

        rule_code = f.get("rule_code")
        plot = f.get("ta_shetach_id")
        matches = select_matches(
            rule_code, plot, m2_findings, enabled_clause_ids=enabled_clause_ids
        )

        if not matches:
            out.append(_normalize_engine_finding(f) if not was_escalated else f)
            continue

        # If this finding was hedged-escalated, the engine's own reasoning admits
        # incomplete verification. M2's tangential evidence (e.g. "all parking
        # underground" doesn't address the engine's ratio-formula hedge) MUST NOT
        # flip the verdict back to pass. Annotate-only.
        if was_escalated:
            override = _apply_m2_annotation(f, matches, [])
            # Keep the escalation marker
            override["m4_override_source"] = "hedged_reasoning_escalation"
            override["m4_override_applied"] = True
            out.append(override)
            continue

        # Look up critic verdicts for the matched M2 findings
        critic_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        for m in matches:
            c = _critic_verdict_for_m2(m, critic_index)
            if c is not None:
                critic_pairs.append((m, c))

        disagreeing = [
            (m, c) for (m, c) in critic_pairs if c.get("critic_verdict") == "disagree"
        ]

        # Bug A guard — for deterministic numeric ≤ comparisons that
        # mathematically pass, a critic disagreement about evidence
        # provenance / table format is real but should not flip the
        # verdict. Move the critic's concern to a sidecar entry instead.
        if disagreeing and _is_unambiguous_numeric_pass(raw_f):
            for (m, c) in disagreeing:
                extra_sidecars.append({
                    "clause_id": m.get("clause_id") or "—",
                    "ta_shetach_takanon": _parse_plot_int(plot),
                    "compliance_indicator": "table_format_concern",
                    "reasoning": (c.get("critic_reasoning") or "").strip(),
                    "source_pages": sorted({
                        p for m2 in matches for p in (m2.get("source_pages") or [])
                    }),
                    "engine_rule_code": rule_code,
                    "engine_submission_value": (raw_f.get("evidence") or {}).get("submission_value"),
                    "engine_schema_value": (raw_f.get("evidence") or {}).get("schema_value"),
                })
            critic_applied.extend(
                sorted({m["clause_id"] for (m, _) in disagreeing if m.get("clause_id")})
            )
            # Suppress critic-escalation; fall through to normal M2 override/annotation path
            disagreeing = []

        if disagreeing:
            # Critic disagreement takes precedence — escalate to requires_review
            override = _apply_critic_escalation(f, matches, disagreeing)
            critic_applied.extend(
                sorted({m["clause_id"] for (m, _) in disagreeing if m.get("clause_id")})
            )
            out.append(override)
            continue

        # Bug B guard — engine deferred because DWG isn't parsed. M2's
        # partial sub-rule evidence (one setback visually confirmed) MUST NOT
        # flip the engine verdict to pass; many other sub-rules remain
        # unverified. Annotate only.
        if _is_dwg_deferred(raw_f):
            override = _apply_m2_annotation(f, matches, critic_pairs)
            override["m4_override_source"] = "dwg_deferred_annotation"
            override["m4_override_applied"] = False  # verdict not flipped
            out.append(override)
            continue

        # No critic disagreement — apply M2 high-confidence override if any
        high_conf = [m for m in matches if (m.get("confidence") or "").lower() == "high"]

        # Bug A guard, A2 extension — engine ran an unambiguous numeric ≤
        # comparison that mathematically passes. M2 high-confidence findings
        # flagging "wrong table type / evidence provenance" MUST NOT flip the
        # verdict away from pass. Surface those concerns as sidecar entries
        # and keep the engine's pass verdict.
        if high_conf and _is_unambiguous_numeric_pass(raw_f):
            flipping = [
                m for m in high_conf
                if m2_indicator_to_engine_verdict(m.get("compliance_indicator")) != "pass"
            ]
            if flipping:
                ev = raw_f.get("evidence") or {}
                for m in flipping:
                    extra_sidecars.append({
                        "clause_id": m.get("clause_id") or "—",
                        "ta_shetach_takanon": _parse_plot_int(plot),
                        "compliance_indicator": "m2_provenance_concern",
                        "reasoning": (m.get("compliance_reasoning") or "").strip(),
                        "source_pages": sorted(set(m.get("source_pages") or [])),
                        "engine_rule_code": rule_code,
                        "engine_submission_value": ev.get("submission_value"),
                        "engine_schema_value": ev.get("schema_value"),
                        "m2_indicator_original": m.get("compliance_indicator"),
                        "m2_confidence_original": m.get("confidence"),
                    })
                override = _apply_m2_annotation(f, matches, critic_pairs)
                override["m4_override_source"] = "m2_provenance_suppressed"
                override["m4_override_applied"] = False  # engine verdict stands
                out.append(override)
                continue

        if high_conf:
            override = _apply_m2_override(f, matches, high_conf, critic_pairs)
            out.append(override)
        else:
            # M2 only has medium/low — annotate without verdict flip
            override = _apply_m2_annotation(f, matches, critic_pairs)
            out.append(override)

    return out, sorted(set(critic_applied)), extra_sidecars


def _apply_m2_override(
    engine_finding: Dict[str, Any],
    all_matches: List[Dict[str, Any]],
    high_conf: List[Dict[str, Any]],
    critic_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]],
) -> Dict[str, Any]:
    best = _pick_best_m2(high_conf)
    new_verdict = m2_indicator_to_engine_verdict(best.get("compliance_indicator"))
    new_confidence = m2_confidence_to_engine(best.get("confidence"))

    reasoning = best.get("compliance_reasoning") or ""
    new_notes = _append_note(
        engine_finding.get("notes_he"),
        f"[Vision evidence — M2 clause {best.get('clause_id')}]: {reasoning}",
    )

    evidence_pages = sorted(
        {p for m in all_matches for p in (m.get("source_pages") or [])}
    )
    evidence_bboxes = [b for m in all_matches for b in (m.get("evidence_bboxes") or [])]

    critic_verdict = None
    if critic_pairs:
        critic_verdict = critic_pairs[0][1].get("critic_verdict")

    out = _normalize_engine_finding(engine_finding)
    out.update({
        "verdict": new_verdict,
        "confidence": new_confidence,
        "notes_he": new_notes,
        "m4_override_applied": True,
        "m4_override_source": "m2_finding",
        "m4_m2_clause_ids": sorted({m["clause_id"] for m in all_matches if m.get("clause_id")}),
        "m4_m3_critic_verdict": critic_verdict,
        "m4_evidence_pages": evidence_pages,
        "m4_evidence_bboxes": evidence_bboxes,
    })
    return out


def _apply_critic_escalation(
    engine_finding: Dict[str, Any],
    all_matches: List[Dict[str, Any]],
    disagreeing: List[Tuple[Dict[str, Any], Dict[str, Any]]],
) -> Dict[str, Any]:
    """Force verdict to requires_review and annotate with critic reasoning."""
    pieces: List[str] = []
    for (m, c) in disagreeing:
        sev = c.get("disagreement_severity") or "unspecified"
        reasoning = c.get("critic_reasoning") or ""
        pieces.append(
            f"[M3 critic disagreement / {sev} on clause {m.get('clause_id')}]: {reasoning}"
        )

    new_notes = _append_note(engine_finding.get("notes_he"), "\n".join(pieces))

    evidence_pages = sorted(
        {p for m in all_matches for p in (m.get("source_pages") or [])}
    )
    evidence_bboxes = [b for m in all_matches for b in (m.get("evidence_bboxes") or [])]

    out = _normalize_engine_finding(engine_finding)
    out.update({
        "verdict": "requires_review",
        # Keep engine confidence as-is when escalating via critic
        "notes_he": new_notes,
        "m4_override_applied": True,
        "m4_override_source": "m3_critic_disagreement",
        "m4_m2_clause_ids": sorted({m["clause_id"] for m in all_matches if m.get("clause_id")}),
        "m4_m3_critic_verdict": "disagree",
        "m4_evidence_pages": evidence_pages,
        "m4_evidence_bboxes": evidence_bboxes,
    })
    return out


def _apply_m2_annotation(
    engine_finding: Dict[str, Any],
    all_matches: List[Dict[str, Any]],
    critic_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]],
) -> Dict[str, Any]:
    """M2 only has medium/low confidence — annotate without overriding verdict."""
    pieces = []
    for m in all_matches:
        conf = m.get("confidence") or "?"
        cid = m.get("clause_id")
        reasoning = m.get("compliance_reasoning") or ""
        pieces.append(f"[Vision evidence (confidence={conf}) clause {cid}]: {reasoning}")
    new_notes = _append_note(engine_finding.get("notes_he"), "\n".join(pieces))

    evidence_pages = sorted(
        {p for m in all_matches for p in (m.get("source_pages") or [])}
    )
    evidence_bboxes = [b for m in all_matches for b in (m.get("evidence_bboxes") or [])]

    out = _normalize_engine_finding(engine_finding)
    out.update({
        "notes_he": new_notes,
        # m4_override_applied stays False for annotation-only
        "m4_m2_clause_ids": sorted({m["clause_id"] for m in all_matches if m.get("clause_id")}),
        "m4_evidence_pages": evidence_pages,
        "m4_evidence_bboxes": evidence_bboxes,
    })
    return out


def _append_note(original: Optional[str], addition: str) -> str:
    base = (original or "").strip()
    addition = addition.strip()
    if not addition:
        return base
    if not base:
        return addition
    return f"{base}\n\n{addition}"


def _build_summary(
    engine_findings_before: List[Dict[str, Any]],
    m4_findings_after: List[Dict[str, Any]],
    critic_applied: List[str],
) -> Dict[str, Any]:
    before = Counter(f.get("verdict") for f in engine_findings_before)
    after = Counter(f.get("verdict") for f in m4_findings_after)
    sources = Counter(
        f.get("m4_override_source") for f in m4_findings_after if f.get("m4_override_applied")
    )
    overridden_count = sum(1 for f in m4_findings_after if f.get("m4_override_applied"))
    new_fail = [
        f"{f.get('rule_code')}:{f.get('ta_shetach_id') or 'plan-wide'}"
        for f in m4_findings_after
        if f.get("verdict") == "fail"
    ]
    return {
        "total_engine_findings": len(engine_findings_before),
        "overridden_count": overridden_count,
        "by_override_source": dict(sources),
        "verdict_distribution_before": dict(before),
        "verdict_distribution_after": dict(after),
        "new_fail_verdicts": new_fail,
        "critic_disagreements_applied": critic_applied,
    }


def build_m4_document(
    engine_doc: Dict[str, Any],
    vision_doc: Dict[str, Any],
    critic_doc: Dict[str, Any],
    engine_path: Path,
    vision_path: Path,
    critic_path: Path,
    *,
    enabled_clause_ids: Optional[set] = None,
    translate_hebrew: bool = True,
    cad_findings: Optional[List[Dict[str, Any]]] = None,
    amenity_inventory: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Top-level: produce the M4AuditResults dict.

    Args:
      translate_hebrew: if True, run Flash-driven English→Hebrew translation
        on M2/M3/sidecar reasoning text before writing. Default True.
        Disable when running offline / for tests.
      cad_findings: optional list of CAD-derived findings (Phase 7.1+) that get
        appended to m4_summary.sidecar_only_findings. Each must already carry
        the sidecar shape (clause_id, ta_shetach_takanon, compliance_indicator,
        reasoning, source_pages) plus a source_type='cad_evidence' marker so
        the report generator can render them with the dedicated CAD style.
    """
    critic_index = _index_critic_findings(critic_doc)
    m2_findings = vision_doc.get("findings", []) or []

    # Only content scope is processed in v1; disciplines + format passthrough.
    content_engine = engine_doc.get("content", []) or []
    content_m4, critic_applied, extra_sidecars = process_engine_findings(
        content_engine, m2_findings, critic_index, enabled_clause_ids=enabled_clause_ids
    )

    disciplines_passthrough = [_normalize_engine_finding(f) for f in (engine_doc.get("disciplines") or [])]
    format_passthrough = [_normalize_engine_finding(f) for f in (engine_doc.get("format") or [])]

    summary = _build_summary(content_engine, content_m4, critic_applied)

    # Also surface sidecar-only M2 findings (no engine row to override)
    sidecar = sidecar_only_entries(m2_findings, enabled_clause_ids=enabled_clause_ids)
    if sidecar:
        summary.setdefault("sidecar_only_findings", [])
        for s in sidecar:
            summary["sidecar_only_findings"].append({
                "clause_id": s.get("clause_id"),
                "ta_shetach_takanon": s.get("ta_shetach_takanon"),
                "compliance_indicator": s.get("compliance_indicator"),
                "reasoning": s.get("compliance_reasoning"),
                "source_pages": s.get("source_pages") or [],
            })

    # Bug A guard spawns: critic table-format concerns on unambiguous numeric
    # passes don't override the verdict — they surface here as sidecar entries.
    if extra_sidecars:
        summary.setdefault("sidecar_only_findings", [])
        summary["sidecar_only_findings"].extend(extra_sidecars)

    # Phase 7.1 — CAD-derived findings (e.g. plot completeness from the תב"ע
    # tashrit DWG). These are the most authoritative source we have — they
    # come from the planning authority's own geometric source-of-truth.
    if cad_findings:
        summary.setdefault("sidecar_only_findings", [])
        summary["sidecar_only_findings"].extend(cad_findings)

    # Phase 7.4 — Amenity inventory (Architecture C, no verdicts).
    # Stashed verbatim in summary; report_generator picks it up to render §3.11
    # and the soft-clarification item in §4.
    if amenity_inventory:
        summary["amenity_inventory"] = amenity_inventory

    document = {
        "audit_run_id": engine_doc.get("audit_run_id"),
        "m4_version": M4_VERSION,
        "m4_input_refs": {
            "engine_audit_results_sha256": _sha256_path(engine_path),
            "vision_findings_sha256": _sha256_path(vision_path),
            "critic_findings_sha256": _sha256_path(critic_path),
        },
        "content": content_m4,
        "disciplines": disciplines_passthrough,
        "format": format_passthrough,
        "extraction_cache": engine_doc.get("extraction_cache", {}),
        "extracts_overlay": engine_doc.get("extracts_overlay", {}),
        "feedback_entries": engine_doc.get("feedback_entries", []),
        "m4_summary": summary,
    }

    if translate_hebrew:
        _apply_hebrew_translation(document)

    # Hebrew voice-normalization pass (catches leftover M2 voice violations the
    # English→Hebrew translator can't reach because the source is already Hebrew).
    _normalize_hebrew_voice(document)

    return document


# ─────────────────────────────────────────────────────────────────────────────
# Hebrew voice normalization (Phase 6.A)
# ─────────────────────────────────────────────────────────────────────────────
# The report is signed by the מהנדס and sent TO the architect. M2's prompt
# emitted some Hebrew strings in third-person ("יש לבקש מהאדריכל...") that
# should address the architect directly ("יש לצרף..."). The English→Hebrew
# translator can't touch these (they're already Hebrew), so we apply
# deterministic substitutions here.

_VOICE_NORMALIZATIONS = [
    # Third-person → architect-facing imperatives
    ("יש לבקש מהאדריכל לצרף", "יש לצרף"),
    ("יש לבקש מהאדריכל להוסיף", "יש להוסיף"),
    ("יש לבקש מהאדריכל לציין", "יש לציין"),
    ("יש לבקש מהאדריכל", "יש לצרף בהגשה הבאה"),
    ("נדרשת בקשה לתוכנית", "יש לצרף תוכנית"),
    ("יש להגיש בקשה מהאדריכל", "יש לצרף"),
    # Internal slug → human Hebrew (catches anything M2 emitted as 5.table)
    ("סעיף 5.table בתקנון", "טבלת הזכויות וההוראות בתקנון התב\"ע"),
    ("5.table בתקנון", "טבלת הזכויות וההוראות בתקנון התב\"ע"),
    ("בסעיף 5.table", "בטבלת הזכויות וההוראות"),
    (" 5.table ", " טבלת הזכויות וההוראות "),
    # Internal milestone labels
    ("בתקנון M2", "בתקנון התב\"ע"),
    ("(M2)", ""),
    ("(M3)", ""),
    ("(M4)", ""),
    ("מודל הראייה", "הבדיקה הוויזואלית"),
    ("מבקר עצמאי", "בדיקה משלימה"),
    # Drop confidence parentheticals
    ("(רמת ודאות=גבוהה) ", ""),
    ("(רמת ודאות=בינונית) ", ""),
    ("(רמת ודאות=נמוכה) ", ""),
    # Generic boilerplate cleanup
    (" הציות מחייב השוואה לטבלת הזכויות בתקנון.", ""),
]


def _normalize_voice_str(s: Optional[str]) -> Optional[str]:
    if not s:
        return s
    out = s
    for old, new in _VOICE_NORMALIZATIONS:
        if old in out:
            out = out.replace(old, new)
    # Collapse repeated whitespace/empty parens left after substitutions
    out = re.sub(r" {2,}", " ", out)
    out = re.sub(r" \. ", ". ", out)
    return out


def _normalize_hebrew_voice(document: Dict[str, Any]) -> None:
    for scope in ("content", "disciplines", "format"):
        for f in document.get(scope, []) or []:
            f["notes_he"] = _normalize_voice_str(f.get("notes_he"))
            f["remediation_he"] = _normalize_voice_str(f.get("remediation_he"))
    for s in (document.get("m4_summary") or {}).get("sidecar_only_findings") or []:
        s["reasoning"] = _normalize_voice_str(s.get("reasoning"))


def _apply_hebrew_translation(document: Dict[str, Any]) -> None:
    """Run Flash-driven Hebrew translation on M4 reasoning text in-place.

    Targets:
      - content[*].notes_he when M4 injected English (look for English bracket markers)
      - m4_summary.sidecar_only_findings[*].reasoning when English

    Preserves original English at content[*]._original_notes_en /
    sidecar[*]._original_reasoning_en for traceability.
    """
    from .translator_hebrew import (
        build_translation_map,
        is_predominantly_english,
    )

    # Collect candidate snippets to translate.
    snippets: List[str] = []

    # Content notes_he often have a mix of Hebrew engine text + English M2 evidence.
    # We split on the M4 markers and only translate the M4-injected English parts.
    M2_MARKER = "[Vision evidence"
    M3_MARKER = "[M3 critic disagreement"
    ANNOTATION_MARKER = "[Vision evidence (confidence="

    def _english_parts(notes: str) -> List[str]:
        """Find English-predominant sub-sections of the notes_he field."""
        if not notes:
            return []
        out: List[str] = []
        # Naive split on paragraph breaks (M4 uses \n\n)
        for chunk in re.split(r"\n\n+", notes):
            if is_predominantly_english(chunk):
                out.append(chunk)
        return out

    for f in document.get("content", []) or []:
        for part in _english_parts(f.get("notes_he") or ""):
            snippets.append(part)

    for s in (document.get("m4_summary") or {}).get("sidecar_only_findings") or []:
        r = s.get("reasoning") or ""
        if is_predominantly_english(r):
            snippets.append(r)

    if not snippets:
        return

    # Dedupe + translate
    print(f"[m5-translator] translating {len(snippets)} English snippets "
          f"({len(set(snippets))} unique) via Flash...", flush=True)
    tmap = build_translation_map(snippets)
    print(f"[m5-translator] translated {len(tmap)} unique snippets", flush=True)

    # Apply back
    for f in document.get("content", []) or []:
        original = f.get("notes_he") or ""
        if not original:
            continue
        chunks = re.split(r"\n\n+", original)
        changed = False
        new_chunks: List[str] = []
        for ch in chunks:
            if ch in tmap:
                new_chunks.append(tmap[ch])
                changed = True
            else:
                new_chunks.append(ch)
        if changed:
            f["_original_notes_en"] = original
            f["notes_he"] = "\n\n".join(new_chunks)

    for s in (document.get("m4_summary") or {}).get("sidecar_only_findings") or []:
        r = s.get("reasoning") or ""
        if r in tmap:
            s["_original_reasoning_en"] = r
            s["reasoning"] = tmap[r]


# Late import for the helper above
import re  # noqa: E402
