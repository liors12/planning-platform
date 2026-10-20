"""Gate: an unreadable text layer never produces "לא הוגש" (B-25).

Ellen's traffic sheet 12753.1/3 has its parking table and basement plans
drawn as vector paths; its text layer holds 518 characters of garbled labels
("הסינכ" for "כניסה", "דייריח" for "דיירים"). 518 clears the 250-character
page bar, so presence detection ran, found none of the words, and told the
architect the basement plan and the parking table were missing - both are on
the sheet.

A false "לא הוגש" tells an architect they omitted work they submitted. The
conservative answer to "we could not read it" is "נדרשת בדיקה".
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "app" / "sidecar")]

from sidecar import attachments as A  # noqa: E402

# Real Hebrew, the register of a sheet's notes and a guideline (≥10 words,
# >250 chars). Abbreviations with gershayim included on purpose.
READABLE = (
    "תכנית מרתף ובה החניון התת קרקעי, חדרי המערכות והמחסנים. טבלת חניה לכל "
    "תא שטח הכוללת חניות פרטיות, חניות אופנועים, חניות נגישות וחניות אופניים. "
    "יחס החניה למגורים לפי תקן החניה הלאומי. רמפת הכניסה לחניון וגבהים "
    "חופשיים. שצ\"פ ושב\"צ יסומנו בתכנית הפיתוח, כולל שבילים ומעברים. "
) * 2
# The same text as a CAD export garbles it.
REVERSED = " ".join(w[::-1] for w in READABLE.split())
# The real sheet's two faults together: reversed, and every final mem as ח.
REVERSED_SUBSTITUTED = REVERSED.replace("ם", "ח")
# MEASURED LIMIT, not a gate: substituting a FEW letters in otherwise-correct
# text leaves 32% of words recognisable (every word without those letters),
# and real readable pages go as low as 31% - so no threshold separates them.
# Such text is caught only if it is also malformed. Kept as a documented
# expectation so a future change that does separate them shows up.
LIGHT_SUBSTITUTION = READABLE.replace("ם", "ח").replace("ן", "ח").replace("ת", "ל")
ONE_GLYPH = "".join("ל" if "א" <= c <= "ת" else c for c in READABLE)
# The real thing, verbatim from the sheet's text layer (first labels).
REAL_GARBLE = ("הסינכ הסינ מנ חדריח: הפשכ הישסייח חדר27.79 תוליע חדר דייריח "
               "מיתדימ 6חדריח מתעכ מיקיח הסינכ מתעכ מיקיח הסינכ מחזיר "
               "קרניסיח יזח מנ חדריח יזח מנ חדריח חצר חצר חצר חצר ורתימ "
               "לחסיימ הסינכ רמשכ דייריח מיתדימ הפשכ הישסייח חצר ") * 2
LATIN = ("ROOM SCHEDULE lobby 24.5 sqm storage 8.2 sqm plant room 11.0 sqm "
         "corridor width 1.80 m clear headroom 2.40 m finished floor level ") * 4

# Real sheet 12753.1/3 - kept outside the public repo (tests/fixtures/real/README.md).
import os  # noqa: E402
REAL_SHEET = Path(os.environ.get("GOLDEN_FIXTURES_DIR",
                                 Path.home() / "planning-platform-fixtures" / "real")
                  ) / "traffic-12753.1-3_ts-2.pdf"


@pytest.mark.parametrize("text", [READABLE, LATIN], ids=["hebrew", "latin"])
def test_readable_text_stays_readable(text):
    assert A._page_state(text) == "readable"


@pytest.mark.parametrize("text", [REVERSED, REVERSED_SUBSTITUTED, ONE_GLYPH, REAL_GARBLE],
                         ids=["reversed", "reversed+substituted", "one-glyph", "real-sheet"])
def test_garbled_text_is_unreadable(text):
    assert len(text) >= A.MIN_TEXT_CHARS_PER_PAGE, "fixture must clear the char bar"
    assert A._page_state(text) == "garbled"


def test_light_substitution_is_a_known_blind_spot():
    assert A._page_state(LIGHT_SUBSTITUTION) == "readable"


def test_title_block_alone_is_still_sparse():
    assert A._page_state("TAVA 407-1048248 v24.3 SHEET 3/60") == "sparse"


def _guideline(title):
    return SimpleNamespace(id=1, title=title, version=1, check_mode="auto_detect",
                           guideline_type="manual", check_value=None, unit=None,
                           to_dict=lambda: {"id": 1, "title": title, "version": 1})


def test_garbled_page_never_yields_not_submitted():
    """The red-green spec: run the real decision path on the real garble."""
    states = [A._page_state(REAL_GARBLE)]
    text_ok = A._detection_allowed(states)
    f = A._guideline_finding(_guideline("תכנית מרתף"), REAL_GARBLE, text_ok)
    assert f["verdict"] == "requires_review", f
    assert "לא ניתן לקרוא את הטקסט בקובץ" in f["notes_he"]


def test_readable_page_still_says_not_submitted_when_absent():
    """The gate must not switch detection off for text it CAN read."""
    states = [A._page_state(READABLE)]
    f = A._guideline_finding(_guideline("דיאגרמת אשפה"), READABLE,
                             A._detection_allowed(states))
    assert f["verdict"] == "not_submitted"


@pytest.mark.skipif(not REAL_SHEET.exists(), reason="real sheet not on this machine")
def test_real_traffic_sheet_is_garbled_end_to_end():
    states = [A._page_state(t) for t in A._page_texts(REAL_SHEET)]
    assert states == ["garbled"]
    quality = {c["rule_code"]: c for c in A._file_quality_checks(REAL_SHEET)}
    assert quality["ATTACH_FILE_TEXT_LAYER"]["verdict"] == "requires_review"
