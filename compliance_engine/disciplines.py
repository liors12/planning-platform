"""Canonical referent-discipline list — the ONE source of truth.

Every consumer derives from here (addendum 8):
  * sidecar/disciplines.py re-exports it → the FastAPI /disciplines
    endpoint → the React comments-tab dropdown
  * the Gemini extraction prompts (referent_extract / meeting_extract)
    build their discipline instructions from the sidecar list
  * excel_export maps discipline keys to labels via the sidecar list

Ellen's-workflow merge: "הערות אדריכלית העיר" is NOT a separate
discipline - it is the same practice as "אדריכלות וחזיתות" (sec-3-7).
Legacy rows tagged with the old key are remapped at startup
(see sidecar/db.py) and the alias below keeps old snapshot files
readable.
"""
from __future__ import annotations

CANONICAL_DISCIPLINES: list[dict] = [
    {"key": "sec-3-1",          "label": 'שפ"ע - אשפה ופינוי פסולת'},
    {"key": "sec-3-2",          "label": "גנים ונוף"},
    {"key": "sec-3-3",          "label": "תשתיות"},
    {"key": "sec-3-4",          "label": "תנועה"},
    {"key": "sec-3-5",          "label": "ניקוז וחלחול"},
    {"key": "sec-3-7",          "label": "אדריכלות וחזיתות"},
    {"key": "sec-3-8",          "label": "הנחיות סביבתיות"},
    {"key": "sec-3-9",          "label": "שירותים לדיירים"},
    {"key": "public-buildings", "label": "מבני ציבור"},
    {"key": "general",          "label": "כללי"},
]

# Old key → canonical key. Applied by the DB migration and by any reader
# that may still meet the old key in persisted artifacts.
LEGACY_DISCIPLINE_ALIASES: dict[str, str] = {
    "city-arch": "sec-3-7",
}

CANONICAL_KEYS: frozenset[str] = frozenset(d["key"] for d in CANONICAL_DISCIPLINES)
