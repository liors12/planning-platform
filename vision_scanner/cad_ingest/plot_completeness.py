"""Produce the M4-compatible plot-completeness finding from the CAD dataset.

This is the Phase 7.1 deliverable: a single authoritative finding that lists
which plots are statutorily part of the תב"ע but absent from the architect's
submission, with their canonical CODE + AREA from the planning-authority CAD.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List


def produce_plot_completeness_finding(
    takanon_dataset: Dict[str, Any],
    submitted_plots: Iterable[int],
) -> Dict[str, Any]:
    """Build an M4-compatible cad_evidence finding for missing plots.

    Args:
      takanon_dataset: output of build_takanon_plot_dataset() — must contain
        'plots' with cellno/code/code_description_he/area_m2.
      submitted_plots: iterable of plot numbers (ints) the architect did submit
        (e.g. [1, 2, 3, 4, 5] for v24.3).

    Returns a finding dict in the same shape as sidecar_only_findings entries
    (clause_id, ta_shetach_takanon, compliance_indicator, reasoning, source_pages)
    plus three CAD-specific keys (source_type, missing_plots, source_paths).
    """
    plots_by_id = {p["cellno"]: p for p in takanon_dataset.get("plots", [])}
    submitted = set(int(p) for p in submitted_plots)
    all_plots = set(plots_by_id.keys())
    missing = sorted(all_plots - submitted)

    if not missing:
        return _build_finding(
            takanon_dataset,
            missing_records=[],
            reasoning_he=(
                "הוגשו תכניות לכל תאי השטח המופיעים בתשריט התב"
                "״ע. בדיקת השלמות מסתיימת ללא ממצא."
            ),
            indicator="compliant",
        )

    missing_records = [plots_by_id[c] for c in missing]
    reasoning_he = _build_reasoning_he(missing_records)
    return _build_finding(
        takanon_dataset,
        missing_records=missing_records,
        reasoning_he=reasoning_he,
        indicator="non_compliant",
    )


def _build_reasoning_he(missing_records: List[Dict[str, Any]]) -> str:
    """Architect-facing Hebrew reasoning + an inline table of missing plots.

    Voice: direct instruction to the architect (per M6 translator voice rules).
    """
    table_lines = ["תא שטח | ייעוד (קוד תב״ע) | שטח קנוני (מ״ר)"]
    for r in sorted(missing_records, key=lambda x: x["cellno"]):
        desc = r.get("code_description_he", "—")
        code = r.get("code", "—")
        area = r.get("area_m2", 0.0)
        table_lines.append(f"{r['cellno']} | {desc} ({code}) | {area:,.0f}")

    header = (
        f"בתשריט התב״ע נכללים {len(missing_records)} תאי שטח שלא נמצאו "
        f"בהגשה הנוכחית (גרסה 24.3 כיסתה רק את תאי השטח שמיועדים למגורים "
        f"בקוד 140). השטחים שלהלן הם חלק סטטוטורי מהתב״ע — יש לצרף "
        f"בהגשה הבאה תכניות פיתוח עבור כל אחד מהם, כולל מפרטי שצ״פ, "
        f"מסלולי תנועה, מבני ציבור והשבילים. הערכים בטבלה שלהלן חולצו "
        f"מתשריט התב״ע (קבצי DWG, מערכת קואורדינטות ITM ישראלית) "
        f"והם הסמכותיים."
    )
    return header + "\n\n" + "\n".join(table_lines)


def _build_finding(
    takanon_dataset: Dict[str, Any],
    *,
    missing_records: List[Dict[str, Any]],
    reasoning_he: str,
    indicator: str,
) -> Dict[str, Any]:
    return {
        # M4 sidecar shape (so report_generator's existing renderer can pick it up):
        "clause_id": "cad.plot_completeness",
        "ta_shetach_takanon": None,  # plan-wide finding
        "compliance_indicator": indicator,
        "reasoning": reasoning_he,
        "source_pages": [],
        # CAD-specific keys (consumed by report_generator's CAD-aware branch):
        "source_type": "cad_evidence",
        "missing_plots": [
            {
                "cellno": r["cellno"],
                "code": r["code"],
                "code_description_he": r.get("code_description_he", ""),
                "area_m2": r["area_m2"],
            }
            for r in missing_records
        ],
        "source_dwg_paths": takanon_dataset.get("source_dwg_paths", []),
        "source_crs": takanon_dataset.get("crs", "EPSG:2039"),
    }
