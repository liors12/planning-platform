"""Hand-curated mapping of M2 clause_ids to engine rule_codes.

Each entry is a dict describing one M2 → engine route. The processor uses
`select_matches(rule_code, ta_shetach_id, m2_findings)` to find all M2
findings that should inform a given engine finding.

m4-v1 Round 2 (expanded): 17 mappings covering all 9 engine content rule_codes
where M2 has any usable evidence. Documented coverage gaps inline below.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Mapping entries — each is one M2 → engine route
# ─────────────────────────────────────────────────────────────────────────────
#
# Fields per entry:
#   m2_clause_id        — clause_id in vision_findings.json (string)
#   m2_unit_match       — optional. If set, only M2 findings whose extraction.unit
#                         matches (case-sensitive) are picked. Used to disambiguate
#                         5.table rows where the same clause emits multiple findings
#                         per plot (one for units, one for floors).
#   engine_rule_code    — engine rule_code to override (None = sidecar-only,
#                         surfaces in m4_summary.sidecar_only_findings but doesn't
#                         override any engine row)
#   plot_scope          — how to bind plot:
#                           "per_plot_passthrough" — engine plot must equal M2's
#                                                    ta_shetach_takanon (as "plot_N")
#                           "plan_wide_to_plot_N"  — M2 finding is plan-wide but
#                                                    we apply it to a specific engine
#                                                    plot
#                           "all_engine_plots"     — M2 finding (plan-wide) applies to
#                                                    every engine plot for the rule
#                           "engine_plan_wide"     — engine finding has ta_shetach_id=null
#                           "sidecar"              — surface in m4_summary, no engine override
#   notes               — human-readable
#
# To extend: append entries to MAPPINGS. The processor reads this list at
# import time; no other code changes are needed.

MAPPINGS: List[Dict[str, Any]] = [
    # ═══════════════════════════════════════════════════════════════════════════
    # CONTENT_UNIT_COUNT (per-plot, 11 engine findings)
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "m2_clause_id": "5.table",
        "m2_unit_match": 'יח"ד',
        "engine_rule_code": "CONTENT_UNIT_COUNT",
        "plot_scope": "per_plot_passthrough",
        "notes": "5.table row 'units' for plot N → CONTENT_UNIT_COUNT plot_N (covers plots 1-5)",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # CONTENT_BUILDING_HEIGHT (per-plot, 11 engine findings)
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "m2_clause_id": "5.table",
        "m2_unit_match": "floors",
        "engine_rule_code": "CONTENT_BUILDING_HEIGHT",
        "plot_scope": "per_plot_passthrough",
        "notes": "5.table row 'floors' (e.g. 10-14) for plot N → CONTENT_BUILDING_HEIGHT plot_N",
    },
    {
        "m2_clause_id": "4.1.2.1",
        "engine_rule_code": "CONTENT_BUILDING_HEIGHT",
        "plot_scope": "per_plot_passthrough",
        "notes": "4.1.2.1 per-plot height (9 floors Tayasim, 10 Histadrut)",
    },
    {
        "m2_clause_id": "6.7.4",
        "engine_rule_code": "CONTENT_BUILDING_HEIGHT",
        "plot_scope": "plan_wide_to_plot_N",
        "plan_wide_to_plot": "plot_5",
        "notes": "6.7.4 (max 91m absolute) — M2 plan-wide, applies to plot_5 (A5 = tallest). Triggers M3 critic disagreement escalation.",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # CONTENT_SETBACKS (per-plot, 11 engine findings)
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "m2_clause_id": "4.1.2.4",
        "engine_rule_code": "CONTENT_SETBACKS",
        "plot_scope": "all_engine_plots",
        "notes": "4.1.2.4 (9m min between buildings) — M2 verified compliant; annotate all CONTENT_SETBACKS plots",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # CONTENT_BUILDING_AREA_MAIN (per-plot, 11 engine findings)
    # ═══════════════════════════════════════════════════════════════════════════
    # GAP: M2 has no direct extraction. The current extracts.json explicitly notes:
    #   "No שטח עיקרי / שטח שירות table is present in this submission. Architect's
    #   submission is a design plan (תכנית עיצוב), not a quantitative areas table."
    # Engine emits `not_submitted` for these; M4 cannot improve without per-plot
    # area numbers that don't exist in the source. No mapping added.

    # ═══════════════════════════════════════════════════════════════════════════
    # CONTENT_BUILDING_AREA_SERVICE_ABOVE (per-plot, 11 engine findings)
    # ═══════════════════════════════════════════════════════════════════════════
    # GAP: same as AREA_MAIN — no service-area tables in submission. No mapping.

    # ═══════════════════════════════════════════════════════════════════════════
    # CONTENT_BUILDING_AREA_SERVICE_BELOW (per-plot, 11 engine findings)
    # ═══════════════════════════════════════════════════════════════════════════
    # GAP: same — no service-area tables. No mapping.

    # ═══════════════════════════════════════════════════════════════════════════
    # CONTENT_PARKING_RATIO (per-plot, 11 engine findings)
    # ═══════════════════════════════════════════════════════════════════════════
    # M2 has parking-related qualitative findings (6.2.1, 6.2.2, 6.2.3) but no
    # ratio-numeric extraction (e.g. cars per unit). These are annotation-only
    # — medium-confidence won't trigger verdict flips per the processor's policy.
    {
        "m2_clause_id": "6.2.1",
        "engine_rule_code": "CONTENT_PARKING_RATIO",
        "plot_scope": "all_engine_plots",
        "notes": "6.2.1 (residents+guests parking underground) — qualitative compliant, annotation across plots",
    },
    {
        "m2_clause_id": "6.2.2",
        "engine_rule_code": "CONTENT_PARKING_RATIO",
        "plot_scope": "all_engine_plots",
        "notes": "6.2.2 (one parking entrance from Tayasim) — M2 says 0 entrances visible, medium confidence",
    },
    {
        "m2_clause_id": "6.2.3",
        "engine_rule_code": "CONTENT_PARKING_RATIO",
        "plot_scope": "all_engine_plots",
        "notes": "6.2.3 (guest parking separation) — requires_review, annotation across plots",
    },
    {
        "m2_clause_id": "4.1.2.10",
        "engine_rule_code": "CONTENT_PARKING_RATIO",
        "plot_scope": "per_plot_passthrough",
        "notes": "4.1.2.10 plot_1 daycare/public-use parking separation — compliant high — overrides plot_1 only",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # CONTENT_PERMEABLE_SURFACES (plan-wide, 1 engine finding)
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "m2_clause_id": "6.5.4.א",
        "engine_rule_code": "CONTENT_PERMEABLE_SURFACES",
        "plot_scope": "engine_plan_wide",
        "notes": "6.5.4.א (≥50% שצ\"פ unpaved) — M2 medium-confidence compliant via visual estimation",
    },
    {
        "m2_clause_id": "4.5.2.1",
        "engine_rule_code": "CONTENT_PERMEABLE_SURFACES",
        "plot_scope": "engine_plan_wide",
        "notes": "4.5.2.1 — permeability calculation deferred_to_dwg, annotation",
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # CONTENT_APARTMENT_MIX_SMALL (plan-wide, 1 engine finding)
    # ═══════════════════════════════════════════════════════════════════════════
    # GAP: M2 has no direct clause covering "small-apartments percentage". The
    # takanon's small-apt threshold is in 5.table (numeric ranges per plot) but
    # M2's 5.table extractions are per-plot unit counts and floors, not unit-mix
    # breakdowns. The engine's CONTENT_APARTMENT_MIX_SMALL currently relies on
    # `unit_mix.count_56_to_75sqm` etc. from extracts.json (Lior-curated, with
    # many ambiguous "null" entries). M2 doesn't override here. No mapping.

    # ═══════════════════════════════════════════════════════════════════════════
    # Sidecar-only — surfaced in m4_summary.sidecar_only_findings
    # ═══════════════════════════════════════════════════════════════════════════
    {
        "m2_clause_id": "6.5.1",
        "engine_rule_code": None,
        "plot_scope": "sidecar",
        "notes": "6.5.1 mature-trees appendix non_compliant — no engine rule; surface in m4_summary",
    },
    {
        "m2_clause_id": "6.6.4",
        "engine_rule_code": None,
        "plot_scope": "sidecar",
        "notes": "6.6.4 plot_2 → חלקה 12 underground easement non_compliant — no engine rule",
    },
    {
        "m2_clause_id": "4.2.2.4",
        "engine_rule_code": None,
        "plot_scope": "sidecar",
        "notes": "4.2.2.4 plot_9 pedestrian passage missing — plot_9 not in submission, surface in sidecar",
    },
    {
        "m2_clause_id": "4.3.2.2",
        "engine_rule_code": None,
        "plot_scope": "sidecar",
        "notes": "4.3.2.2 plot_7 שצ\"פ width missing — plot_7 not in submission",
    },
    {
        "m2_clause_id": "6.4.2",
        "engine_rule_code": None,
        "plot_scope": "sidecar",
        "notes": "6.4.2 stormwater retention 450 m³ missing — high-impact infrastructure gap",
    },
    {
        "m2_clause_id": "7.1.1",
        "engine_rule_code": None,
        "plot_scope": "sidecar",
        "notes": "7.1.1 phasing plan missing — Task #29 (phasing category has 0 engine rules)",
    },
]


def select_matches(
    engine_rule_code: str,
    engine_ta_shetach_id: Optional[str],
    m2_findings: List[Dict[str, Any]],
    *,
    enabled_clause_ids: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """Return M2 findings that should inform the given engine (rule, plot)."""
    out: List[Dict[str, Any]] = []
    for entry in MAPPINGS:
        if entry.get("engine_rule_code") != engine_rule_code:
            continue
        if enabled_clause_ids is not None and entry["m2_clause_id"] not in enabled_clause_ids:
            continue
        for f in m2_findings:
            if f.get("clause_id") != entry["m2_clause_id"]:
                continue
            unit_match = entry.get("m2_unit_match")
            if unit_match is not None:
                f_unit = (f.get("extraction") or {}).get("unit")
                if f_unit != unit_match:
                    continue
            if _plot_binding_holds(entry, engine_ta_shetach_id, f):
                out.append(f)
    return out


def sidecar_only_entries(
    m2_findings: List[Dict[str, Any]],
    *,
    enabled_clause_ids: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """Return M2 findings flagged for sidecar-only surfacing (no engine override)."""
    out: List[Dict[str, Any]] = []
    sidecar_clauses = {e["m2_clause_id"] for e in MAPPINGS if e["plot_scope"] == "sidecar"}
    for f in m2_findings:
        cid = f.get("clause_id")
        if cid not in sidecar_clauses:
            continue
        if enabled_clause_ids is not None and cid not in enabled_clause_ids:
            continue
        out.append(f)
    return out


def _plot_binding_holds(
    entry: Dict[str, Any],
    engine_ta_shetach_id: Optional[str],
    m2_finding: Dict[str, Any],
) -> bool:
    scope = entry.get("plot_scope")
    m2_plot = m2_finding.get("ta_shetach_takanon")  # "1".. or None

    if scope == "per_plot_passthrough":
        if m2_plot is None or engine_ta_shetach_id is None:
            return False
        return engine_ta_shetach_id == f"plot_{m2_plot}"

    if scope == "plan_wide_to_plot_N":
        target = entry.get("plan_wide_to_plot")
        return m2_plot is None and engine_ta_shetach_id == target

    if scope == "all_engine_plots":
        # M2 plan-wide; apply to every per-plot engine finding for the rule
        return m2_plot is None and engine_ta_shetach_id is not None

    if scope == "engine_plan_wide":
        return m2_plot is None and engine_ta_shetach_id is None

    return False


def all_enabled_clauses() -> set:
    """All clause_ids referenced in MAPPINGS (used as default 'enabled' set)."""
    return {e["m2_clause_id"] for e in MAPPINGS}
