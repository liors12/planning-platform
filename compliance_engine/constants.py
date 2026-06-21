"""Shared constants for the compliance engine.

Single source of truth for discipline names, section ordering, and status
label mappings so that the HTML report (report_generator.py) and the Excel
export (excel_export.py) always produce identical labels. Any future label
change goes here — never in either consumer.
"""
from __future__ import annotations

# ─── Discipline labels (Hebrew) ───────────────────────────────────────────────
# Keys are the engine's internal discipline codes; values are the Hebrew names
# Ellen reviewed and approved. Order in this dict IS the canonical section
# order used by the HTML report (§3.1 = shafa, §3.2 = gardens, …).
DISCIPLINE_NAME_HE: dict[str, str] = {
    "shafa":    'שפ"ע — אשפה ופינוי פסולת',
    "gardens":  "גנים ונוף",
    "infra":    "תשתיות",
    "fire":     "רחבות כיבוי אש",
    "drainage": "ניקוז וחלחול",
    "roofs":    "גגות וגינון על גג",
    "arch":     "אדריכלות וחזיתות",
    "balcony":  "מרפסות",
    "laundry":  "מסתורי כביסה",
    "env":      "הנחיות סביבתיות",
}

# Insertion order of DISCIPLINE_NAME_HE is the canonical section order.
DISCIPLINE_ORDER: list[str] = list(DISCIPLINE_NAME_HE.keys())


# ─── Status / verdict label mapping (Hebrew) ──────────────────────────────────
# Maps engine-internal verdict strings → Hebrew labels used in the Excel export
# and HTML report. The canonical reference set is the M8.2 Excel Ellen approved:
#   תקין | לא תקין | נדרשת השלמה | לא הוגש | הערת פגישה | לא רלוונטי
#
# Several internal verdicts collapse to the same reference label (e.g. both
# "fail" and "non_compliant" → "לא תקין"). The fallback in callers should be
# STATUS_MAP.get(verdict, verdict) so unknown future verdicts pass through
# rather than silently dropping to an empty string.
STATUS_MAP: dict[str, str] = {
    "pass":                  "תקין",
    "pass_with_note":        "תקין",
    "fail":                  "לא תקין",
    "fail_borderline":       "לא תקין",
    "non_compliant":         "לא תקין",
    "requires_review":       "נדרשת השלמה",
    "table_format_concern":  "נדרשת השלמה",
    "m2_provenance_concern": "נדרשת השלמה",
    "unevaluable":           "נדרשת השלמה",
    "not_submitted":         "לא הוגש",
    "missing":               "לא הוגש",
    "not_applicable":        "לא רלוונטי",
}
