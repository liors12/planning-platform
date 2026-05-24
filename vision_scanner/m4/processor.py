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
from .translator import m2_confidence_to_engine, m2_indicator_to_engine_verdict


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
        "[הסלמה אוטומטית]: ציון 'תקין' הוסלם ל'דורש בירור' "
        "מאחר שטקסט הנימוק מודה באימות חלקי בלבד.",
    )
    return escalated, True


def process_engine_findings(
    engine_findings: List[Dict[str, Any]],
    m2_findings: List[Dict[str, Any]],
    critic_index: Dict[str, List[Dict[str, Any]]],
    *,
    enabled_clause_ids: Optional[set] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Override engine findings using M2 + critic data.

    Order of operations per finding:
      1. Task #32 hedged-pass escalation (runs first; may flip pass→requires_review)
      2. M3 critic disagreement (escalate to requires_review if any)
      3. M2 high-confidence override (may flip back to pass / non_compliant / etc)
      4. M2 medium/low annotation (no verdict change)

    Returns (m4_findings, list_of_critic_clause_ids_actually_applied).
    """
    if enabled_clause_ids is None:
        enabled_clause_ids = all_enabled_clauses()

    out: List[Dict[str, Any]] = []
    critic_applied: List[str] = []

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

        if disagreeing:
            # Critic disagreement takes precedence — escalate to requires_review
            override = _apply_critic_escalation(f, matches, disagreeing)
            critic_applied.extend(
                sorted({m["clause_id"] for (m, _) in disagreeing if m.get("clause_id")})
            )
            out.append(override)
            continue

        # No critic disagreement — apply M2 high-confidence override if any
        high_conf = [m for m in matches if (m.get("confidence") or "").lower() == "high"]
        if high_conf:
            override = _apply_m2_override(f, matches, high_conf, critic_pairs)
            out.append(override)
        else:
            # M2 only has medium/low — annotate without verdict flip
            override = _apply_m2_annotation(f, matches, critic_pairs)
            out.append(override)

    return out, sorted(set(critic_applied))


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
) -> Dict[str, Any]:
    """Top-level: produce the M4AuditResults dict.

    Args:
      translate_hebrew: if True, run Flash-driven English→Hebrew translation
        on M2/M3/sidecar reasoning text before writing. Default True.
        Disable when running offline / for tests.
    """
    critic_index = _index_critic_findings(critic_doc)
    m2_findings = vision_doc.get("findings", []) or []

    # Only content scope is processed in v1; disciplines + format passthrough.
    content_engine = engine_doc.get("content", []) or []
    content_m4, critic_applied = process_engine_findings(
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

    return document


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
