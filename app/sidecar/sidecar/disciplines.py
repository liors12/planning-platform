"""Single source of truth for the 9 referent disciplines surfaced in the UI.

`discipline_key` maps to the HTML section anchor that `report_generator`
emits for §3 subsections (`id="sec-3-{N}"`). The mapping is contractual:
the FastAPI router validates against `DISCIPLINE_KEYS`, the React dropdown
reads `DISCIPLINES` via `/disciplines`, and the render-time injection
matches `discipline_key` against the same id in the rendered HTML.
"""
from __future__ import annotations

# Addendum 8: the list itself lives in compliance_engine/disciplines.py -
# the single canonical source shared by the platform, the extraction
# prompts and the Excel export. "הערות אדריכלית העיר" was merged into
# "אדריכלות וחזיתות" there (same discipline in Ellen's practice).
# In dev the sidecar's cwd is app/sidecar, so the repo root (where
# compliance_engine lives) may not be on sys.path yet - same trick the
# render path uses.
try:
    from compliance_engine.disciplines import (  # noqa: F401
        CANONICAL_DISCIPLINES, LEGACY_DISCIPLINE_ALIASES,
    )
except ModuleNotFoundError:  # dev layout - add repo root and retry
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from compliance_engine.disciplines import (  # noqa: F401
        CANONICAL_DISCIPLINES, LEGACY_DISCIPLINE_ALIASES,
    )

DISCIPLINES: list[dict] = CANONICAL_DISCIPLINES

DISCIPLINE_KEYS: frozenset[str] = frozenset(d["key"] for d in DISCIPLINES)

STATUSES: list[str] = ["תקין", "לא תקין", "נדרשת השלמה"]
STATUS_SET: frozenset[str] = frozenset(STATUSES)

TOPIC_MAX_LEN: int = 60
