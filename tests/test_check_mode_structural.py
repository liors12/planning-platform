"""Gate: a guideline's check_mode must come from STRUCTURE, never prose.

check_mode decides what the engine is allowed to say about a row - "לא הוגש"
vs "נדרשת בדיקה ידנית" vs "נדרשת בדיקה". If it is derived from the Hebrew
wording of the title or body, then editing a guideline's phrasing silently
changes how every future submission is judged against it. That is exactly
what happened in the v0.2.2 first cut: the חלק ו tb"a rows were classified
"manual" only because the readability rewrite happened to phrase them
"ייבדק מול", a verb that the classifier read as a judgment marker.

The rule this gate enforces: reword a guideline as much as you like, and its
category must not move. Category may depend on section_key, sort_order,
check_key, guideline_type, check_value - never on title/body text.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "app/sidecar/seed/guidelines_seed.json"


def _load_extractor():
    """Import the extraction script as a module (it is a script, not a
    package member, so importlib rather than a plain import)."""
    path = ROOT / "scripts/extract_guidelines_docx.py"
    spec = importlib.util.spec_from_file_location("extract_guidelines_docx", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows():
    return json.loads(SEED.read_text(encoding="utf-8"))["guidelines"]


# Substantial rewordings that preserve meaning. Each pair is (original
# fragment to find, replacement) applied to BOTH title and body.
REWORDINGS = [
    ("ייבדק מול", "יושווה אל מול הקבוע ב"),
    ("יש לסמן", "תסומן בתכנית"),
    ("יוגש", "יימסר"),
    ("תוגש", "תימסר"),
    ("יצורף", "יימסר בנפרד"),
]


def test_check_mode_survives_rewording():
    """Reword every row that matches a known phrasing pattern; the category
    must be byte-identical before and after."""
    mod = _load_extractor()
    rows = _rows()
    drifted = []
    checked = 0

    for row in rows:
        before = mod.classify_check_mode(row)
        for needle, replacement in REWORDINGS:
            if needle not in row["title"] and needle not in (row.get("body_text") or ""):
                continue
            reworded = dict(row)
            reworded["title"] = row["title"].replace(needle, replacement)
            reworded["body_text"] = (row.get("body_text") or "").replace(
                needle, replacement)
            after = mod.classify_check_mode(reworded)
            checked += 1
            if after != before:
                drifted.append(
                    f"{row['section_key']}/{row['title'][:40]!r}: "
                    f"{before} → {after} (reworded {needle!r} → {replacement!r})")

    assert checked > 0, "no row matched any rewording pattern - test is vacuous"
    assert not drifted, (
        f"check_mode changed under rewording for {len(drifted)} of {checked} "
        "rewordings. Category must derive from structural fields "
        "(section_key, sort_order, check_key, guideline_type), never from "
        "Hebrew text:\n" + "\n".join(drifted)
    )


def test_check_mode_ignores_title_entirely():
    """The strongest form: replace the title with an unrelated string. A
    structural classifier cannot notice."""
    mod = _load_extractor()
    drifted = []
    for row in _rows():
        before = mod.classify_check_mode(row)
        scrambled = dict(row)
        scrambled["title"] = "כותרת חלופית לבדיקה"
        scrambled["body_text"] = "נוסח חלופי לחלוטין לצורך הבדיקה בלבד."
        after = mod.classify_check_mode(scrambled)
        if after != before:
            drifted.append(f"{row['section_key']}/{row['title'][:40]!r}: "
                           f"{before} → {after}")
    assert not drifted, (
        f"{len(drifted)} rows changed category when their text was replaced:\n"
        + "\n".join(drifted[:20])
    )


def test_every_row_has_a_valid_mode():
    modes = {r.get("check_mode") for r in _rows()}
    assert modes <= {"auto_detect", "manual", "needs_context"}, modes
    assert None not in modes, "some rows carry no check_mode"
