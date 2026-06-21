"""Shared constants for the compliance engine.

Single source of truth for discipline names and ordering so that the HTML
report (report_generator.py) and the Excel export (excel_export.py) always
use identical labels and section order. Previously each file had its own
hardcoded dict that drifted out of sync — any future label change goes here.
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
