"""Phase 7.2 — Cross-section (חתכים) height parser.

Reuses M1 page_manifests.visible_dimensions instead of running a fresh M2 Pro
extraction. M1 already parsed per-building absolute elevations on the late-group
cross-section pages (p48-51) and on the elevation pages (p52-62) with structured
`context` strings like "absolute top level elevation for building A5".

Produces two M4-compatible finding categories per building, all surfaced in
section 2ג of the audit PDF:

  1. **Ceiling check** — if max(top_elevations) > 91.0 m absolute (plan-wide
     flight-path ceiling, §6.7 — no relief permitted) → non_compliant
  2. **Consistency check** — if spread between min and max top-elevations
     across all source pages > 0.5 m → requires_review

Sources covered:
  - p48-51: late-group cross-sections (chatakhim)
  - p52-62: elevations (חזיתות) — same building can appear in both
  - Plot-level entries (e.g. "top of building 5" with no letter suffix) are
    used for the ceiling check but excluded from per-building consistency
    (apples-to-oranges with letter-labeled buildings).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Plan-wide absolute ceiling (§6.7 — flight path, no relief)
ABSOLUTE_CEILING_M = 91.0
CEILING_TOLERANCE_M = 0.0   # hard limit per takanon; even 0.01 m is a violation
CONSISTENCY_THRESHOLD_M = 0.5  # spread above which "drawings disagree" finding fires
GROUND_REF_THRESHOLD_M = 0.5   # spread above which "ground reference drift" finding fires

# Sanity range for absolute ground references on this 91 m site.
# Site grade lives ~40-55 m above sea level (per M1 data: 40, 42, 43, 44.5, 45.5,
# 47.75, 49.1, 49.5, 49.7). Anything outside this range is probably mislabeled.
GROUND_VALUE_MIN_M = 35.0
GROUND_VALUE_MAX_M = 55.0

# Pages we read from. Cross-sections + elevations.
CHATAKHIM_PAGES = {48, 49, 50, 51}
ELEVATION_PAGES = set(range(52, 63))  # p52-62
ALL_SOURCE_PAGES = CHATAKHIM_PAGES | ELEVATION_PAGES


# ─────────────────────────────────────────────────────────────────────────────
# Regex parsers over M1 context strings
# ─────────────────────────────────────────────────────────────────────────────

# Building IDs like A1, B4, C5, D5 — and the special combined "D1/A1" form.
# Accept "building B5", "בניין B5", "level B5" (per p59 elevation phrasing).
_BUILDING_ID_RE = re.compile(
    r"\b(?:building|בניין|level)\s+([A-D]\d{1,2}(?:/[A-D]\d{1,2})?)\b",
    re.IGNORECASE,
)

# Top-elevation context: any explicit "top" / "roof" / "highest" cue
# (broadened to match the variety of M1 phrasings observed in 407-1048248).
_TOP_CTX_RE = re.compile(
    r"(?:top\s+(?:floor|level)|top\s+of\s+building|roof|highest|\btop\b)",
    re.IGNORECASE,
)
# Generic "elevation level X" or "level X elevation" — fallback for tower pages
_ELEV_LEVEL_RE = re.compile(r"\b(?:elevation\s+level|level\s+\d{1,2}\s+(?:elevation|absolute))\b", re.IGNORECASE)

_GROUND_CTX_RE = re.compile(r"\bground\b|\bמפלס\s+כניסה\b|\bלמ\.כניסה\b", re.IGNORECASE)
_BASEMENT_CTX_RE = re.compile(r"\bbasement\b|\b[BM]S-\d{2}\b|\bמרתף\b", re.IGNORECASE)

# Plot-level (no building letter): "top of building 5", "absolute elevation building 3 top"
_PLOT_LEVEL_RE = re.compile(r"(?:top\s+of\s+building|building)\s+(\d{1,2})(?!\d)", re.IGNORECASE)

# Sanity range — at this 91 m site, absolute building-top values live in 60-100 m.
# Values below this for a "top" entry are almost certainly a relative-vs-absolute
# labeling slip in the M1 manifest (the context says "absolute" but the value
# is the relative one). Skip with no record.
TOP_VALUE_MIN_M = 60.0
TOP_VALUE_MAX_M = 100.0


# ─────────────────────────────────────────────────────────────────────────────
# Value-type taxonomy (Phase 7.3b)
# ─────────────────────────────────────────────────────────────────────────────
# Every parsed dimension is classified into one of five buckets. The bucket
# travels with the record and becomes a first-class field that downstream
# filters and renderers can query — replacing the context-regex special cases
# that the Option-3 surgical filter (M7.2) used.

VT_TRUE_BUILDING_TOP = "TRUE_BUILDING_TOP"
VT_INTERMEDIATE_LEVEL = "INTERMEDIATE_LEVEL"
VT_STATUTORY_LIMIT_ANNOTATION = "STATUTORY_LIMIT_ANNOTATION"
VT_GROUND_REFERENCE = "GROUND_REFERENCE"
VT_UNCERTAIN = "UNCERTAIN"

# Hebrew + English markers used by the classifier
_GROUND_TOKENS_RE = re.compile(r"\bground\b|קרקע", re.IGNORECASE)
_FLOOR_LADDER_RE = re.compile(r"\bfloor\s+\d{1,2}\b.*?\bplot\s+\d{1,2}\b", re.IGNORECASE)
_ENVELOPE_TOKENS_RE = re.compile(
    r"\benvelope\b|\blimit\b|מעטפת|מקסימום|תקרת|maximum",
    re.IGNORECASE,
)
_TOP_TOKENS_RE = re.compile(r"\btop\b|\broof\b|\bhighest\b|גג", re.IGNORECASE)
_INTERMEDIATE_TOKENS_RE = re.compile(
    r"\bpodium\b|\bmechanical\b|\bintermediate\b|פודיום|טכני|מפלס\s+ביניים",
    re.IGNORECASE,
)


def _classify_value_type(
    context: str,
    source_view: str,
    value_m: float,
) -> Tuple[str, str, str]:
    """Phase 7.3b — classify a parsed dimension into the value-type taxonomy.

    Returns (value_type, confidence ∈ {high, medium, low}, reasoning_he).

    Rule order — first match wins:
      1. GROUND_REFERENCE        — explicit ground annotation
      2. STATUTORY_LIMIT_ANNOTATION — floor-ladder reference ("floor N, plot M")
      3. STATUTORY_LIMIT_ANNOTATION — envelope/limit token
      4. INTERMEDIATE_LEVEL      — cross-section "top" (cut intersection, not roof)
      5. INTERMEDIATE_LEVEL      — explicit podium/mechanical marker
      6. TRUE_BUILDING_TOP       — elevation "top"/"roof"/"highest"
      7. TRUE_BUILDING_TOP       — value in absolute-top range on an elevation page
      8. UNCERTAIN               — fallback
    """
    ctx = context or ""
    sv = source_view or ""

    # Rule 1 — explicit ground
    if _GROUND_TOKENS_RE.search(ctx):
        return (VT_GROUND_REFERENCE, "high",
                "explicit ground annotation in M1 context")
    # Rule 2 — floor-ladder reference (floor N, plot M)
    if _FLOOR_LADDER_RE.search(ctx):
        return (VT_STATUTORY_LIMIT_ANNOTATION, "high",
                "floor-ladder reference (structural floor index, not roof claim)")
    # Rule 3 — envelope/limit tokens
    if _ENVELOPE_TOKENS_RE.search(ctx):
        return (VT_STATUTORY_LIMIT_ANNOTATION, "high",
                "envelope/limit marker in M1 context")
    # Rule 4 — cross-section + top → intermediate cut
    if sv == "cross_section" and _TOP_TOKENS_RE.search(ctx):
        return (VT_INTERMEDIATE_LEVEL, "medium",
                "cross-section cut-top is not the building's full top "
                "(intersects at cut location only)")
    # Rule 5 — explicit intermediate-level marker
    if _INTERMEDIATE_TOKENS_RE.search(ctx):
        return (VT_INTERMEDIATE_LEVEL, "high",
                "podium / mechanical / intermediate-floor marker in M1 context")
    # Rule 6 — elevation + top → true building top
    if sv == "elevation" and _TOP_TOKENS_RE.search(ctx):
        return (VT_TRUE_BUILDING_TOP, "high",
                "elevation-page top/roof annotation (full-facade view)")
    # Rule 7 — elevation page + value in absolute-top range (paired-label
    # contexts often drop the "top" word but the value clearly is a roof,
    # e.g. p53 "absolute elevation building A2" → 77.35 m)
    if sv == "elevation" and TOP_VALUE_MIN_M <= value_m <= TOP_VALUE_MAX_M:
        return (VT_TRUE_BUILDING_TOP, "medium",
                "elevation-page value in absolute-top range "
                "(paired-label inferred)")
    # Rule 8 — fallback
    return (VT_UNCERTAIN, "low",
            "no taxonomy rule matched the context — needs reviewer eyes")

# "absolute" hint — we only want absolute (above sea level) values, never relative-only
_ABSOLUTE_HINT_RE = re.compile(r"\babsolute\b", re.IGNORECASE)

# Floor-13 envelope marker — only meaningful on plot 5 elevation pages
# (this catches "absolute elevation, floor 13, plot 5" → 91.8 m)
_FLOOR_LEVEL_RE = re.compile(r"\bfloor\s+(\d{1,2})\b|\blevel\s+(\d{1,2})\b", re.IGNORECASE)
_PLOT_LABEL_RE = re.compile(r"\bplot\s+(\d{1,2})\b", re.IGNORECASE)


def _classify_dimension(
    d: Dict[str, Any],
    page_number: int,
    page_refs: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Inspect one M1 visible_dimensions entry; emit zero or more height records.

    Each emitted record carries:
      - building_id (str or None — None means plot-level)
      - plot_id (int or None — inferred from context or page_refs)
      - value_type ('top' / 'ground' / 'basement')
      - elevation_m (float)
      - source_page (int)
      - source_context (str — raw M1 string, for traceability)
    """
    ctx = (d.get("context") or "").strip()
    try:
        val = float(d.get("value"))
    except (TypeError, ValueError):
        return []
    unit = (d.get("unit") or "").lower()
    if unit not in ("m", "m.", ""):  # ignore m² etc.
        return []

    has_absolute_hint = bool(_ABSOLUTE_HINT_RE.search(ctx))

    # Determine value type (precedence: basement > ground > top-explicit > top-fallback)
    if _BASEMENT_CTX_RE.search(ctx):
        value_type = "basement"
    elif _GROUND_CTX_RE.search(ctx):
        value_type = "ground"
    elif _TOP_CTX_RE.search(ctx):
        value_type = "top"
    elif _ELEV_LEVEL_RE.search(ctx):
        value_type = "top" if val >= TOP_VALUE_MIN_M else None
    else:
        # Fallback: value is in absolute-top range AND context has some attribution
        # anchor (a building ID, a plot label, OR a high-floor marker like
        # "floor 13" / "level 13"). This catches:
        #   p58 "absolute elevation, floor 13, plot 5" → 91.80 (plot-level top)
        #   p53 "absolute elevation building A2" → 77.35 (building-level top)
        has_anchor = bool(
            _BUILDING_ID_RE.search(ctx)
            or _PLOT_LEVEL_RE.search(ctx)
            or _PLOT_LABEL_RE.search(ctx)
        )
        m_floor = _FLOOR_LEVEL_RE.search(ctx)
        floor_n = None
        if m_floor:
            try:
                floor_n = int(m_floor.group(1) or m_floor.group(2))
            except (TypeError, ValueError):
                floor_n = None
        is_top_floor_marker = floor_n is not None and floor_n >= 10
        if val >= TOP_VALUE_MIN_M and (has_anchor or is_top_floor_marker):
            value_type = "top"
        else:
            value_type = None

    if value_type is None:
        return []

    # Scope: Phase 7.2 only produces findings on `top` values. Skip ground/basement
    # entirely (they require their own audit dimensions — basement depth, garden-apt
    # elevations — both deferred to Phase 7.3+).
    if value_type != "top":
        return []

    # For top: gate via value-range sanity (absolute building tops on this 91 m
    # site live in 60-100 m). This handles two cases:
    #   1. Context labeled "absolute" but value is a relative number that
    #      slipped through M1 → range filter rejects it.
    #   2. Context has no "absolute" word (e.g. p59 "elevation level A5" = 89.8
    #      m, where M1 didn't tag absoluteness) — accept since the value is
    #      unmistakably in the absolute range.
    if not (TOP_VALUE_MIN_M <= val <= TOP_VALUE_MAX_M):
        return []
    # Additional safety: if no absolute hint, the context must carry a building
    # ID or a "plot N top" phrase — otherwise we don't know what to attribute it to.
    if not has_absolute_hint:
        if not (_BUILDING_ID_RE.search(ctx) or _PLOT_LEVEL_RE.search(ctx) or _PLOT_LABEL_RE.search(ctx)):
            return []

    # Building ID (e.g., A5, B4, D1/A1)
    bid_match = _BUILDING_ID_RE.search(ctx)
    plot_match = _PLOT_LEVEL_RE.search(ctx)
    plot_label_match = _PLOT_LABEL_RE.search(ctx)

    plot_id: Optional[int] = None
    if plot_label_match:
        plot_id = int(plot_label_match.group(1))
    elif plot_match:
        plot_id = int(plot_match.group(1))

    # Phase 7.3b — typed taxonomy classification (additive metadata)
    # source_view: M1's page_type, surfaced as a first-class field so downstream
    # queries don't have to peek at it indirectly.
    source_view = (page_refs and "") or ""  # placeholder; real value injected below
    # (source_view is injected by collect_height_records when wrapping records;
    #  here we leave it for the augmentation pass to add)

    vtype, vt_conf, vt_reason = _classify_value_type(ctx, "", val)

    records: List[Dict[str, Any]] = []
    if bid_match:
        raw = bid_match.group(1).upper()
        for bid in raw.split("/"):
            records.append({
                "building_id": bid,
                "plot_id": _infer_plot_from_building(bid),
                "value_type": value_type,
                "elevation_m": val,
                "source_page": page_number,
                "source_context": ctx,
                # Phase 7.3b additive fields
                "taxonomy_type": vtype,
                "taxonomy_confidence": vt_conf,
                "taxonomy_reasoning": vt_reason,
            })
    elif plot_id is not None and value_type == "top":
        records.append({
            "building_id": None,
            "plot_id": plot_id,
            "value_type": "top_unlabeled",
            "elevation_m": val,
            "source_page": page_number,
            "source_context": ctx,
            "taxonomy_type": vtype,
            "taxonomy_confidence": vt_conf,
            "taxonomy_reasoning": vt_reason,
        })
    elif value_type == "top" and page_refs and len(page_refs) == 1:
        # Page with a single plot ref and a top value with no in-context plot/building
        # label — attribute to that plot as un-labeled.
        records.append({
            "building_id": None,
            "plot_id": int(page_refs[0]),
            "value_type": "top_unlabeled",
            "elevation_m": val,
            "source_page": page_number,
            "source_context": ctx,
            "taxonomy_type": vtype,
            "taxonomy_confidence": vt_conf,
            "taxonomy_reasoning": vt_reason,
        })
    # else: ambiguous — page has multiple plot refs and context lacks attribution. Skip.

    return records


def _infer_plot_from_building(building_id: str) -> Optional[int]:
    """Building IDs in 407-1048248 follow [Letter][PlotNumber] convention:
      A1, B1, C1, D1 → plot 1
      A2 → plot 2 (only A series shown for plot 2)
      A3, B3, C3, D3 → plot 3
      A4, B4 → plot 4
      A5, B5, C5, D5 → plot 5
    """
    m = re.match(r"^[A-D](\d{1,2})$", building_id)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Aggregation
# ─────────────────────────────────────────────────────────────────────────────


def collect_height_records(manifests_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Walk M1 manifests, emit all parseable height records on source pages.

    Each record additionally carries `page_type` (cross_section / elevation)
    so downstream consistency-check logic can apply source-view rules
    (Phase 7.2 Option-3 surgical filter).
    """
    records: List[Dict[str, Any]] = []
    for p in manifests_doc.get("manifests", []) or []:
        n = p.get("page_number")
        if n not in ALL_SOURCE_PAGES:
            continue
        page_refs = p.get("ta_shetach_refs") or []
        page_type = p.get("page_type") or "unknown"
        for d in p.get("visible_dimensions") or []:
            for rec in _classify_dimension(d, n, page_refs=page_refs):
                rec["page_type"] = page_type
                # Phase 7.3b — source_view mirrors page_type as a first-class field
                # so downstream filters query a name that reflects intent ("source_view")
                # rather than a M1 implementation detail ("page_type").
                rec["source_view"] = page_type
                # Re-classify with the actual source_view now that we know it
                # (the inner _classify_dimension didn't have access to it).
                vt, vt_conf, vt_reason = _classify_value_type(
                    rec.get("source_context") or "",
                    page_type,
                    rec.get("elevation_m") or 0.0,
                )
                rec["taxonomy_type"] = vt
                rec["taxonomy_confidence"] = vt_conf
                rec["taxonomy_reasoning"] = vt_reason
                records.append(rec)
    return records


def _scan_ground_references(
    manifests_doc: Dict[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    """Phase 7.3a — extract per-building absolute ground references.

    Two extraction paths:

    1. **Explicit ground entries**: M1 context contains "ground" + a building ID
       + "absolute" (e.g. "absolute ground level elevation for building B4"
       → 47.75 m on p49). Value is taken directly when in the absolute-ground
       range (35-55 m above sea level for this site).

    2. **Inferred from paired labels**: M1 context contains a building ID +
       "ground" and has TWO values on the same context — one relative (0.0 m)
       and one absolute (e.g. "absolute elevation, building B4 ground"
       → 0.0 + 49.1 on p57). The larger is the absolute ground.

    Returns { building_id_uppercase → [
        { "page": int, "page_type": str, "ground_m": float, "context": str }, ...
    ] }
    """
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    seen: set[Tuple[str, int, float]] = set()

    for p in manifests_doc.get("manifests", []) or []:
        n = p.get("page_number")
        if n not in ALL_SOURCE_PAGES:
            continue
        page_type = p.get("page_type") or "unknown"
        # Group dimensions by full context (for paired-label detection)
        ctx_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for d in p.get("visible_dimensions") or []:
            try:
                val = float(d.get("value"))
            except (TypeError, ValueError):
                continue
            ctx = (d.get("context") or "").strip()
            ctx_groups[ctx.lower()].append({"val": val, "raw_ctx": ctx})

        for ctx_low, entries in ctx_groups.items():
            # Require absolute + building ID + ground hint
            if not _ABSOLUTE_HINT_RE.search(ctx_low):
                continue
            if not _GROUND_CTX_RE.search(ctx_low):
                continue
            m = _BUILDING_ID_RE.search(ctx_low)
            if not m:
                continue
            # Determine the absolute ground value:
            # If paired (0.0 + larger), take the larger; otherwise take the value
            # that's in the absolute-ground range.
            ground_candidates = [
                e["val"] for e in entries
                if GROUND_VALUE_MIN_M <= e["val"] <= GROUND_VALUE_MAX_M
            ]
            if not ground_candidates:
                continue
            # If multiple candidates on same context, take the maximum
            # (the absolute one, vs any paired smaller one that slipped through)
            ground_m = max(ground_candidates)
            raw_ctx = entries[0]["raw_ctx"]
            for bid in m.group(1).upper().split("/"):
                key = (bid, n, round(ground_m, 2))
                if key in seen:
                    continue
                seen.add(key)
                out[bid].append({
                    "page": n,
                    "page_type": page_type,
                    "ground_m": round(ground_m, 2),
                    "context": raw_ctx,
                    # Phase 7.3b additive metadata — ground entries are
                    # explicit GROUND_REFERENCE by definition (the scanner
                    # only emits when _GROUND_CTX_RE matches).
                    "source_view": page_type,
                    "taxonomy_type": VT_GROUND_REFERENCE,
                    "taxonomy_confidence": "high",
                    "taxonomy_reasoning": "explicit ground annotation in M1 context",
                })

    # Sort each building's entries by page
    for bid in out:
        out[bid].sort(key=lambda e: e["page"])
    return dict(out)


def _scan_paired_above_ground(
    manifests_doc: Dict[str, Any],
) -> Dict[Tuple[int, str], float]:
    """Phase 7.2 Option-3 helper: detect paired relative-absolute labels.

    The architect's elevation drawings annotate building tops in pairs:
        "absolute elevation, building A2 top" → 32.85 m  (= relative above ground)
        "absolute elevation, building A2 top" → 74.85 m  (= absolute above sea)
    Same page, identical context, two values. The smaller is the relative
    above-ground height; the larger is the absolute.

    Some pages drop the "top" word and just say "absolute elevation building A2"
    with the same two-value pattern (e.g. p53). Detect both phrasings.

    Returns a dict { (page_number, building_id_uppercase) → above_ground_m }.
    """
    out: Dict[Tuple[int, str], float] = {}
    for p in manifests_doc.get("manifests", []) or []:
        n = p.get("page_number")
        if n not in ALL_SOURCE_PAGES:
            continue
        # Group dimensions on this page by full context string.
        ctx_groups: Dict[str, List[float]] = defaultdict(list)
        for d in p.get("visible_dimensions") or []:
            try:
                val = float(d.get("value"))
            except (TypeError, ValueError):
                continue
            ctx = (d.get("context") or "").strip().lower()
            ctx_groups[ctx].append(val)
        for ctx, vals in ctx_groups.items():
            m = _BUILDING_ID_RE.search(ctx)
            if not m:
                continue
            # Skip explicit ground/basement contexts — those pair differently
            if _GROUND_CTX_RE.search(ctx) or _BASEMENT_CTX_RE.search(ctx):
                continue
            small = [v for v in vals if 0 < v < TOP_VALUE_MIN_M]
            large = [v for v in vals if TOP_VALUE_MIN_M <= v <= TOP_VALUE_MAX_M]
            if not small or not large:
                continue
            # Paired (small, large) for same context → smaller is above-ground
            above_ground = min(small)
            for bid in m.group(1).upper().split("/"):
                out[(n, bid)] = above_ground
    return out


def aggregate_by_building(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Group records by building_id (letter-labeled buildings only).

    Returns {building_id: {plot_id, top_values: [{elevation_m, source_page,
    source_context, page_type}, ...]}}
    """
    by_bld: Dict[str, Dict[str, Any]] = {}
    for r in records:
        bid = r.get("building_id")
        if not bid or r.get("value_type") != "top":
            continue
        slot = by_bld.setdefault(bid, {
            "building_id": bid,
            "plot_id": r.get("plot_id"),
            "top_values": [],
        })
        slot["top_values"].append({
            "elevation_m": r["elevation_m"],
            "source_page": r["source_page"],
            "source_context": r["source_context"],
            "page_type": r.get("page_type", "unknown"),
            # Phase 7.3b additive metadata
            "source_view": r.get("source_view") or r.get("page_type", "unknown"),
            "taxonomy_type": r.get("taxonomy_type", VT_UNCERTAIN),
            "taxonomy_confidence": r.get("taxonomy_confidence", "low"),
            "taxonomy_reasoning": r.get("taxonomy_reasoning", ""),
        })
    # Sort + dedupe each building's value list by (page, elevation)
    for bld in by_bld.values():
        bld["top_values"].sort(key=lambda v: (v["source_page"], v["elevation_m"]))
    return by_bld


def aggregate_plot_level_tops(records: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    """Plot-level top entries (no building letter, e.g. 'top of building 5')."""
    by_plot: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        if r.get("value_type") == "top_unlabeled" and r.get("plot_id") is not None:
            by_plot[r["plot_id"]].append({
                "elevation_m": r["elevation_m"],
                "source_page": r["source_page"],
                "source_context": r["source_context"],
                # Phase 7.3b additive metadata
                "source_view": r.get("source_view") or r.get("page_type", "unknown"),
                "taxonomy_type": r.get("taxonomy_type", VT_UNCERTAIN),
                "taxonomy_confidence": r.get("taxonomy_confidence", "low"),
                "taxonomy_reasoning": r.get("taxonomy_reasoning", ""),
            })
    return dict(by_plot)


# ─────────────────────────────────────────────────────────────────────────────
# Finding production
# ─────────────────────────────────────────────────────────────────────────────


def _format_value_list_he(values: List[Dict[str, Any]]) -> str:
    """'90.15 מ\' (עמ\' 49, 55) · 89.80 מ\' (עמ\' 59)'"""
    by_val: Dict[float, List[int]] = defaultdict(list)
    for v in values:
        by_val[round(v["elevation_m"], 2)].append(v["source_page"])
    pieces = []
    for val in sorted(by_val.keys()):
        pages = sorted(set(by_val[val]))
        page_str = ", ".join(str(p) for p in pages)
        pieces.append(f'{val:.2f} מ\' (עמ\' {page_str})')
    return " · ".join(pieces)


def _build_ceiling_finding(building_id: str, plot_id: Optional[int],
                            values: List[Dict[str, Any]]) -> Dict[str, Any]:
    max_val = max(v["elevation_m"] for v in values)
    page_list = sorted({v["source_page"] for v in values})
    pages_str = ", ".join(str(p) for p in page_list)
    n_sources = len(page_list)
    delta = max_val - ABSOLUTE_CEILING_M
    reasoning = (
        f'מבנה {building_id} מציג ב-{n_sources} תשריטים גובה מוחלט מקסימלי '
        f'של {max_val:.2f} מ\' מעל פני הים, החורג מהתקרה של {ABSOLUTE_CEILING_M:.2f} מ\' '
        f'שנקבעה בסעיף 6.7 לתקנון התב"ע (מגבלת מסלול הטיסה — לא תינתן הקלה). '
        f'חריגה של {delta:+.2f} מ\'. מקור הנתון: עמודי חתכים וחזיתות {pages_str}. '
        f'יש להנמיך את גובה הבניין כך שלא יחרוג מהמפלס המוחלט הקובע.'
    )
    return _build_finding(
        clause_id=f"chatakhim.height_ceiling.{building_id}",
        plot_id=plot_id,
        indicator="non_compliant",
        reasoning=reasoning,
        source_pages=page_list,
        building_id=building_id,
        check_type="ceiling",
        max_top_m=round(max_val, 2),
        ceiling_m=ABSOLUTE_CEILING_M,
        delta_m=round(delta, 2),
        value_list=values,
    )


def _build_consistency_finding(building_id: str, plot_id: Optional[int],
                                values: List[Dict[str, Any]]) -> Dict[str, Any]:
    max_val = max(v["elevation_m"] for v in values)
    min_val = min(v["elevation_m"] for v in values)
    spread = max_val - min_val
    n_distinct = len({round(v["elevation_m"], 2) for v in values})
    n_sources = len({v["source_page"] for v in values})
    value_list_str = _format_value_list_he(values)
    reasoning = (
        f'מבנה {building_id} מופיע ב-{n_sources} תשריטים שונים עם {n_distinct} ערכי גובה '
        f'שונים: {value_list_str}. הפער בין הערכים ({spread:.2f} מ\') חורג מסבילות סבירה '
        f'(0.5 מ\'). נדרש להבהיר את הגובה הקנוני של המבנה ולעדכן את התשריטים הסותרים.'
    )
    return _build_finding(
        clause_id=f"chatakhim.height_consistency.{building_id}",
        plot_id=plot_id,
        indicator="requires_review",
        reasoning=reasoning,
        source_pages=sorted({v["source_page"] for v in values}),
        building_id=building_id,
        check_type="consistency",
        max_top_m=round(max_val, 2),
        min_top_m=round(min_val, 2),
        spread_m=round(spread, 2),
        value_list=values,
    )


def _build_ground_reference_finding(
    building_id: str,
    plot_id: Optional[int],
    ground_entries: List[Dict[str, Any]],
    above_ground_heights: List[float],
) -> Dict[str, Any]:
    """Phase 7.3a: emit a ground-reference inconsistency finding."""
    grounds = [e["ground_m"] for e in ground_entries]
    spread = max(grounds) - min(grounds)
    n_sources = len(ground_entries)

    # Hebrew labels for page types
    pt_he = {"elevation": "חזית", "cross_section": "חתך"}
    bullets = "\n".join(
        f"- {e['ground_m']:.2f} מ\' ({pt_he.get(e['page_type'], e['page_type'])} עמ\' {e['page']})"
        for e in sorted(ground_entries, key=lambda x: x["page"])
    )

    # Sanity: is above-ground height consistent?
    # Require ≥2 samples to claim consistency. With a single sample we don't
    # know if the building's height matches across drawings — be honest.
    if len(above_ground_heights) >= 2:
        ag_spread = max(above_ground_heights) - min(above_ground_heights)
        ag_consistent = ag_spread <= CONSISTENCY_THRESHOLD_M
        ag_value = round(min(above_ground_heights), 2) if ag_consistent else None
    elif len(above_ground_heights) == 1:
        ag_spread = None
        ag_consistent = None  # unknown — only one sample
        ag_value = round(above_ground_heights[0], 2)
    else:
        ag_spread = None
        ag_consistent = None
        ag_value = None

    if ag_consistent is True and ag_value is not None:
        ag_clause = (
            f'הגובה המוצע מעל הקרקע ({ag_value:.2f} מ\') זהה ב-{n_sources} '
            f'התשריטים — חוסר העקביות הוא בקו האפס המוחלט ולא בגובה המבנה.'
        )
    elif ag_consistent is False:
        ag_clause = (
            f'בנוסף, הגובה מעל הקרקע אינו עקבי בין התשריטים '
            f'(פער של {ag_spread:.2f} מ\'). למבנה יש לפיכך שתי בעיות נפרדות: '
            f'הן בקו האפס המוחלט והן בגובה המוצע. שתיהן דורשות הבהרה.'
        )
    else:
        ag_clause = (
            'לא היה ניתן לוודא עקביות הגובה מעל הקרקע מנתוני התשריטים '
            f'הזמינים (קיים רק מדגם {len(above_ground_heights)}). יש לוודא '
            'ידנית שגם גובה המבנה עקבי בין התשריטים.'
        )

    reasoning = (
        f'מבנה {building_id} מופיע ב-{n_sources} תשריטים עם ערכי קרקע '
        f'מוחלטים שונים:\n{bullets}\n\n'
        f'הפער בין הערכים ({spread:.2f} מ\') חורג מסבילות סבירה לעיצוב. '
        f'{ag_clause}\n\n'
        f'חשיבות: בדיקת התקרה המוחלטת (סעיף 6.7, 91 מ\' מעל פני הים) '
        f'תלויה בקו האפס שנבחר. אם המבנה משורטט עם קרקע ב-'
        f'{max(grounds):.2f} מ\' בגרסה אחת וב-{min(grounds):.2f} מ\' באחרת, '
        f'הגובה המוחלט עשוי להשתנות ב-{spread:.2f} מ\' בהתאם להבחירה.\n\n'
        f'יש להבהיר באיזה קו אפס מתבסס כל תשריט (רחוב, חצר, מפלס כניסה), '
        f'ולציין באופן עקבי את הקרקע הקנונית בכל התשריטים. במידת הצורך, '
        f'להוסיף הערה הסברתית: "מפלס +0.00 = X מ\' מעל פני הים — '
        f'נקודת ייחוס כניסה ראשית" (או דומה).'
    )

    return _build_finding(
        clause_id=f"chatakhim.ground_reference.{building_id}",
        plot_id=plot_id,
        indicator="requires_review",
        reasoning=reasoning,
        source_pages=sorted({e["page"] for e in ground_entries}),
        building_id=building_id,
        check_type="ground_reference",
        max_ground_m=round(max(grounds), 2),
        min_ground_m=round(min(grounds), 2),
        spread_m=round(spread, 2),
        # ag_consistent can be True / False / None (unknown). JSON-encode as
        # str when None for human readability of the persistent log.
        above_ground_consistent=("unknown" if ag_consistent is None else ag_consistent),
        above_ground_height_m=ag_value,
        ground_entries=ground_entries,
        # value_list — used by the standard render path as a generic evidence table.
        # Phase 7.3b: include source_view + taxonomy metadata as additive fields.
        value_list=[
            {
                "elevation_m": e["ground_m"],
                "source_page": e["page"],
                "source_context": e["context"],
                "source_view": e.get("source_view") or e.get("page_type", "unknown"),
                "taxonomy_type": e.get("taxonomy_type", VT_GROUND_REFERENCE),
                "taxonomy_confidence": e.get("taxonomy_confidence", "high"),
                "taxonomy_reasoning": e.get("taxonomy_reasoning", ""),
            }
            for e in ground_entries
        ],
    )


def _build_plot_ceiling_finding(plot_id: int, values: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Ceiling check on plot-level top entries (un-labeled buildings).

    Phase 7.2 Option-3 framing: indicator is `requires_review` (amber) rather
    than `non_compliant` (red). The values that exceed the §6.7 ceiling may
    be one of:
      (a) actual roof appurtenances (parapet, mechanical, elevator overrun)
      (b) regulatory envelope annotations drawn for reference
      (c) unidentified buildings whose tops aren't reached by other source pages
    The chatakhim parser can't distinguish (a) from (b) — the architect must
    clarify. Flagging non_compliant on (b) would be a false-positive; flagging
    requires_review correctly surfaces the question.
    """
    violations = [v for v in values if v["elevation_m"] > ABSOLUTE_CEILING_M]
    if not violations:
        violations = values  # shouldn't happen — caller checks max>ceiling
    max_val = max(v["elevation_m"] for v in violations)
    page_list = sorted({v["source_page"] for v in violations})
    pages_str = ", ".join(str(p) for p in page_list)
    delta = max_val - ABSOLUTE_CEILING_M
    n_violations = len(violations)
    if n_violations == 1:
        values_phrase = (
            f'בתשריט מופיע ערך גובה מוחלט של {max_val:.2f} מ\' (עמ\' {pages_str})'
        )
    else:
        values_phrase = (
            f'בתשריטים מופיעים {n_violations} ערכי גובה מוחלט מעל לתקרה: '
            f'{_format_value_list_he(violations)}'
        )
    reasoning = (
        f'בתא שטח {plot_id}, {values_phrase} — מעל התקרה של '
        f'{ABSOLUTE_CEILING_M:.2f} מ\' מעל פני הים שנקבעה בסעיף 6.7 לתקנון התב"ע '
        f'(מגבלת מסלול הטיסה האזרחית — לא תינתן הקלה). חריגה מקסימלית: '
        f'{delta:+.2f} מ\'. '
        f'הערכים אינם משויכים בתשריט לבניין ספציפי — ייתכן שהם מייצגים '
        f'(א) ראש בניין כולל אביזרי גג (פרפט, מתקני אוורור, חדרי מעליות) '
        f'(ב) קווי מעטפת רגולטוריים שצוירו לצורך התייחסות, או '
        f'(ג) בניין שאינו מתויג שאי-אפשר היה לאתר אותו במקורות אחרים. '
        f'יש להבהיר בהגשה הבאה מה מייצג כל ערך, ולוודא עמידה מלאה במפלס '
        f'הקובע כולל כל מבנה הגג.'
    )
    return _build_finding(
        clause_id=f"chatakhim.height_ceiling.plot_{plot_id}",
        plot_id=plot_id,
        indicator="requires_review",
        reasoning=reasoning,
        source_pages=page_list,
        building_id=None,
        check_type="ceiling_plot_level",
        max_top_m=round(max_val, 2),
        ceiling_m=ABSOLUTE_CEILING_M,
        delta_m=round(delta, 2),
        value_list=violations,
    )


def _build_finding(
    *,
    clause_id: str,
    plot_id: Optional[int],
    indicator: str,
    reasoning: str,
    source_pages: List[int],
    building_id: Optional[str],
    check_type: str,
    **extras: Any,
) -> Dict[str, Any]:
    """Sidecar-shaped finding with chatakhim_evidence source marker.

    Compatible with M4 build_m4_document(cad_findings=...) which appends any
    list of sidecar-shaped findings to m4_summary.sidecar_only_findings.
    report_generator splits by source_type to render the right section.
    """
    finding = {
        # M4 sidecar shape:
        "clause_id": clause_id,
        "ta_shetach_takanon": plot_id,
        "compliance_indicator": indicator,
        "reasoning": reasoning,
        "source_pages": source_pages,
        # chatakhim-specific keys (consumed by report_generator section 2ג):
        "source_type": "chatakhim_evidence",
        "building_id": building_id,
        "check_type": check_type,
        "ceiling_m": ABSOLUTE_CEILING_M,
        "ceiling_source_section": "§6.7",
    }
    finding.update(extras)
    return finding


def _consistency_finding_is_real(
    bid: str,
    values: List[Dict[str, Any]],
    paired_above_ground: Dict[Tuple[int, str], float],
) -> Tuple[bool, str]:
    """Phase 7.2 Option-3 surgical filter — migrated in Phase 7.3b to query
    the typed taxonomy fields (source_view, taxonomy_type) instead of M1
    page_type regex. Behavior preserved.

    Decides whether a candidate consistency finding represents a genuine
    drawing inconsistency or a known parser artifact. Returns (is_real, reason).

    Two known false-positive patterns:

    1. **Mixed source views**: the spread mixes cross-section values
       (INTERMEDIATE_LEVEL — partial cut planes) with elevation values
       (TRUE_BUILDING_TOP — full facade). Mixing manufactures false spread
       (e.g. B4 in v24.3: 77.45 + 80.60 cross-section vs 90.05 elevation).

    2. **All-elevation but ground-reference mismatch**: two elevation drawings
       of the same building can use different absolute ground references
       (street grade vs courtyard grade). Above-ground heights match; only the
       absolute baseline differs. Detected via paired relative-absolute labels.
    """
    # Query the typed fields (Phase 7.3b). source_view falls back to page_type
    # for records produced before the refactor or by sub-paths that didn't
    # populate it (none today, but keeps the migration safe).
    source_views = {v.get("source_view") or v.get("page_type") for v in values}
    has_cross_section = "cross_section" in source_views
    has_elevation = "elevation" in source_views

    # Wording preserved verbatim from M7.2 (drop_reason strings are part of the
    # consistency_findings_dropped_as_artifacts log and the byte-identical
    # contract). The corresponding taxonomy labels are:
    #   cross-section "top" → INTERMEDIATE_LEVEL
    #   elevation "top"     → TRUE_BUILDING_TOP
    if has_cross_section and has_elevation:
        return False, (
            "mixed-source artifact: spread combines cross-section cut planes "
            "(not necessarily the building's true top) with elevation drawings "
            "(authoritative full-facade tops)."
        )
    if has_cross_section and not has_elevation:
        return False, (
            "cross-section-only spread: different cut planes through the same "
            "building can show different intermediate 'tops' — not a drawing "
            "inconsistency, just different views."
        )

    # All-elevation pages — check paired above-ground heights
    above_ground_heights: List[float] = []
    for v in values:
        page = v["source_page"]
        ag = paired_above_ground.get((page, bid))
        if ag is None:
            return True, "real (could not derive per-page above-ground heights)"
        above_ground_heights.append(ag)
    if not above_ground_heights:
        return True, "real (no above-ground data to compare)"
    above_ground_spread = max(above_ground_heights) - min(above_ground_heights)
    if above_ground_spread <= CONSISTENCY_THRESHOLD_M:
        return False, (
            f"ground-reference artifact: above-ground heights agree "
            f"({sorted(set(round(h, 2) for h in above_ground_heights))} m, "
            f"spread {above_ground_spread:.2f} m). The absolute spread reflects "
            f"different ground references across drawings, not different building heights."
        )
    return True, f"real (above-ground spread {above_ground_spread:.2f} m exceeds tolerance)"


def produce_chatakhim_findings(manifests_doc: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Top-level orchestrator. Returns (findings, summary_stats).

    Phase 7.2 Option-3 surgical filter applies:
    - consistency findings whose source views are mixed (cross-section + elevation)
      OR all cross-section are dropped (known parser artifact);
    - all-elevation consistency findings are dropped when above-ground heights
      agree (paired relative-absolute label detection);
    - plot-level ceiling findings use requires_review (amber) framing — the
      values may be roof appurtenances, regulatory envelope annotations, or
      unidentified buildings; the engineer must clarify.
    """
    records = collect_height_records(manifests_doc)
    by_bld = aggregate_by_building(records)
    by_plot = aggregate_plot_level_tops(records)
    paired_above_ground = _scan_paired_above_ground(manifests_doc)
    ground_refs_by_bld = _scan_ground_references(manifests_doc)

    # Augment ground refs with INFERRED values from paired top labels.
    # When a top entry has paired (relative, absolute) labels on the same page,
    # ground = absolute_top - above_ground (the paired_above_ground value).
    # Example: A2 p53 has paired (32.85, 77.35) for "absolute elevation building A2"
    # → ground = 77.35 - 32.85 = 44.50 m, even though M1 didn't tag it as "ground".
    _inferred_seen: set[Tuple[str, int, float]] = set()
    for bid, slot in by_bld.items():
        page_type_by_page = {v["source_page"]: v["page_type"] for v in slot["top_values"]}
        for v in slot["top_values"]:
            page = v["source_page"]
            ag = paired_above_ground.get((page, bid))
            if ag is None:
                continue
            inferred_ground = round(v["elevation_m"] - ag, 2)
            if not (GROUND_VALUE_MIN_M <= inferred_ground <= GROUND_VALUE_MAX_M):
                continue
            # Skip if we already have an explicit ground from M1 for this page+building
            existing = ground_refs_by_bld.get(bid, [])
            if any(
                e["page"] == page and abs(e["ground_m"] - inferred_ground) < 0.05
                for e in existing
            ):
                continue
            dup_key = (bid, page, inferred_ground)
            if dup_key in _inferred_seen:
                continue
            _inferred_seen.add(dup_key)
            ground_refs_by_bld.setdefault(bid, []).append({
                "page": page,
                "page_type": page_type_by_page.get(page, "unknown"),
                "ground_m": inferred_ground,
                "context": f"{v['source_context']} (inferred ground = absolute − relative)",
                # Phase 7.3b additive metadata — inferred ground from paired
                # top label is still a GROUND_REFERENCE, just with lower
                # confidence than an explicit annotation.
                "source_view": page_type_by_page.get(page, "unknown"),
                "taxonomy_type": VT_GROUND_REFERENCE,
                "taxonomy_confidence": "medium",
                "taxonomy_reasoning": "inferred from paired (relative_above_ground, absolute_top) label",
            })
    # Re-sort entries by page
    for bid in ground_refs_by_bld:
        ground_refs_by_bld[bid].sort(key=lambda e: e["page"])

    findings: List[Dict[str, Any]] = []
    ceiling_buildings: List[str] = []
    consistency_buildings: List[str] = []
    consistency_dropped: List[Dict[str, str]] = []
    ground_ref_buildings: List[str] = []
    ground_ref_dropped: List[Dict[str, Any]] = []

    for bid, slot in sorted(by_bld.items()):
        values = slot["top_values"]
        if not values:
            continue
        max_top = max(v["elevation_m"] for v in values)
        min_top = min(v["elevation_m"] for v in values)
        spread = max_top - min_top
        plot_id = slot["plot_id"]

        if max_top > ABSOLUTE_CEILING_M + CEILING_TOLERANCE_M:
            findings.append(_build_ceiling_finding(bid, plot_id, values))
            ceiling_buildings.append(bid)
        if spread > CONSISTENCY_THRESHOLD_M:
            is_real, reason = _consistency_finding_is_real(bid, values, paired_above_ground)
            if is_real:
                findings.append(_build_consistency_finding(bid, plot_id, values))
                consistency_buildings.append(bid)
            else:
                consistency_dropped.append({
                    "building_id": bid,
                    "spread_m": round(spread, 2),
                    "drop_reason": reason,
                })

    plot_ceiling_plots: List[int] = []
    for plot_id, values in sorted(by_plot.items()):
        max_top = max(v["elevation_m"] for v in values)
        if max_top > ABSOLUTE_CEILING_M + CEILING_TOLERANCE_M:
            findings.append(_build_plot_ceiling_finding(plot_id, values))
            plot_ceiling_plots.append(plot_id)

    # Phase 7.3a — ground-reference inconsistency findings
    for bid, ground_entries in sorted(ground_refs_by_bld.items()):
        distinct_grounds = sorted({e["ground_m"] for e in ground_entries})
        if len(distinct_grounds) < 2:
            continue
        spread = max(distinct_grounds) - min(distinct_grounds)
        if spread <= GROUND_REF_THRESHOLD_M:
            continue
        # Derive above-ground heights per contributing page (for sanity check).
        # Dedupe by page — multiple ground entries from the same page would
        # otherwise inflate the sample count without adding real evidence.
        ag_by_page: Dict[int, float] = {}
        for e in ground_entries:
            ag = paired_above_ground.get((e["page"], bid))
            if ag is not None:
                ag_by_page[e["page"]] = ag
        above_ground_heights: List[float] = list(ag_by_page.values())
        plot_id = _infer_plot_from_building(bid)
        # Drop if all ground entries are on the same page (no real "between drawings"
        # inconsistency to surface)
        contributing_pages = {e["page"] for e in ground_entries}
        if len(contributing_pages) < 2:
            ground_ref_dropped.append({
                "building_id": bid,
                "spread_m": round(spread, 2),
                "drop_reason": (
                    "single-page artifact: all ground references come from one page; "
                    "no cross-drawing inconsistency to surface."
                ),
            })
            continue
        findings.append(_build_ground_reference_finding(
            bid, plot_id, ground_entries, above_ground_heights,
        ))
        ground_ref_buildings.append(bid)

    summary = {
        "buildings_audited": sorted(by_bld.keys()),
        "buildings_with_top_values": [b for b, s in by_bld.items() if s["top_values"]],
        "plots_with_unlabeled_tops": sorted(by_plot.keys()),
        "ceiling_violations_buildings": sorted(ceiling_buildings),
        "ceiling_violations_plot_level": sorted(plot_ceiling_plots),
        "consistency_warnings_buildings": sorted(consistency_buildings),
        "consistency_findings_dropped_as_artifacts": consistency_dropped,
        "ground_reference_warnings_buildings": sorted(ground_ref_buildings),
        "ground_reference_findings_dropped_as_artifacts": ground_ref_dropped,
        "buildings_with_ground_references": sorted(ground_refs_by_bld.keys()),
        "absolute_ceiling_m": ABSOLUTE_CEILING_M,
        "consistency_threshold_m": CONSISTENCY_THRESHOLD_M,
        "ground_reference_threshold_m": GROUND_REF_THRESHOLD_M,
        "source_pages_used": sorted(ALL_SOURCE_PAGES),
        "total_height_records_parsed": len(records),
    }
    return findings, summary


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _main_cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 7.2 — extract chatakhim/elevation absolute heights from M1 manifests; "
                    "produce M4-compatible ceiling + consistency findings."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--submission-id", required=True)
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Output JSON path. Default: data/projects/<plan>/submissions/<sub>/chatakhim_findings.json",
    )
    args = parser.parse_args(argv)

    manifests_path = (
        PROJECT_ROOT / "data" / "projects" / args.project_id
        / "submissions" / args.submission_id / "page_manifests.json"
    )
    if not manifests_path.exists():
        print(f"ERROR: missing M1 manifests: {manifests_path}", file=sys.stderr)
        return 2
    manifests = json.loads(manifests_path.read_text(encoding="utf-8"))

    findings, summary = produce_chatakhim_findings(manifests)

    output_path = args.output or (
        PROJECT_ROOT / "data" / "projects" / args.project_id
        / "submissions" / args.submission_id / "chatakhim_findings.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "project_id": args.project_id,
        "submission_id": args.submission_id,
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_pages": sorted(ALL_SOURCE_PAGES),
        "absolute_ceiling_m": ABSOLUTE_CEILING_M,
        "consistency_threshold_m": CONSISTENCY_THRESHOLD_M,
        "summary": summary,
        "findings": findings,
    }
    output_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {output_path}")
    print(f"  Records parsed: {summary['total_height_records_parsed']}")
    print(f"  Buildings audited: {len(summary['buildings_audited'])} → {summary['buildings_audited']}")
    print(f"  Ceiling violations (buildings): {summary['ceiling_violations_buildings']}")
    print(f"  Ceiling violations (plot-level): {summary['ceiling_violations_plot_level']}")
    print(f"  Consistency warnings: {summary['consistency_warnings_buildings']}")
    print(f"  Total findings: {len(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main_cli())
