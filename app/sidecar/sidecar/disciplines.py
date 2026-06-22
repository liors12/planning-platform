"""Single source of truth for the 9 referent disciplines surfaced in the UI.

`discipline_key` maps to the HTML section anchor that `report_generator`
emits for §3 subsections (`id="sec-3-{N}"`). The mapping is contractual:
the FastAPI router validates against `DISCIPLINE_KEYS`, the React dropdown
reads `DISCIPLINES` via `/disciplines`, and the render-time injection
matches `discipline_key` against the same id in the rendered HTML.
"""
from __future__ import annotations

DISCIPLINES: list[dict] = [
    {"key": "sec-3-1",        "label": 'שפ"ע — אשפה ופינוי פסולת'},
    {"key": "sec-3-2",        "label": "גנים ונוף"},
    {"key": "sec-3-3",        "label": "תשתיות"},
    {"key": "sec-3-4",        "label": "תנועה"},
    {"key": "sec-3-5",        "label": "ניקוז וחלחול"},
    {"key": "sec-3-7",        "label": "אדריכלות וחזיתות"},
    {"key": "sec-3-8",        "label": "הנחיות סביבתיות"},
    {"key": "sec-3-9",        "label": "שירותים לדיירים"},
    {"key": "city-arch",      "label": "הערות אדריכלית העיר"},
    {"key": "public-buildings", "label": "מבני ציבור"},
    {"key": "general",          "label": "כללי"},
]

DISCIPLINE_KEYS: frozenset[str] = frozenset(d["key"] for d in DISCIPLINES)

STATUSES: list[str] = ["תקין", "לא תקין", "נדרשת השלמה"]
STATUS_SET: frozenset[str] = frozenset(STATUSES)

TOPIC_MAX_LEN: int = 60
