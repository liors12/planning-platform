"""Gate: LTR technical tokens must not be reordered inside Hebrew text.

Hebrew guideline text carries tokens the architect copies verbatim - CAD layer
names, file sizes, standard numbers, filenames. The Unicode bidi algorithm
reorders some of them inside RTL text: "0_LOTS" displays as "LOTS_0", "100 MB"
as "MB 100". The STORED text is correct; only the display is wrong, and it is
wrong identically in the browser and in WeasyPrint/Pango. An architect copying
a layer name off the screen or out of a PDF types the wrong string.

Four render paths carry this text - the app screen, the guidelines PDF, the
דו"ח התייחסות, and the main report's הנחיות section. The rule is implemented
twice, once per language:

    compliance_engine/report_chrome.py : isolate_ltr()   -> all three PDFs
    app/frontend/src/lib/bidi.tsx      : ltrRuns()        -> the app screen

There is no way to share one implementation across Python and TypeScript, so
this file pins them together: both are fed the SAME fixture list and must
segment it identically. Change one without the other and this goes red.

Rendered-order assertions (that the isolate actually fixes the display, in a
browser and in a generated PDF) live in tests/ui-dev/tests/97-bidi.spec.ts,
which needs Playwright and so cannot run here.

TWO BIDI ENGINES, ONE VERDICT (measured in v0.2.2, worth not re-deriving):
the token list was first swept with the BROWSER as the oracle, but three of the
four render paths are WeasyPrint/Pango - a different implementation. Both were
then run over all 84 distinct LTR runs in the 160-row corpus:

    * WeasyPrint flagged exactly the same 9 token shapes as the browser
    * every one of the 20 tokens deliberately left alone - AC1018, EPSG:2039,
      A3, 1:500, 9:00-15:00, PDF, DXF, DWG, RTL, 5281 ... - was safe in BOTH
    * zero disagreements

Measuring WeasyPrint took two attempts and the first was wrong: TextBox.text
holds a run's LOGICAL text, so walking the box tree reproduces logical order
and reports everything as fine. The working method renders the token twice -
inside a <span> and inside a <span> carrying unicode-bidi:isolate - and
compares rasterised pixels. Identical pixels mean the plain render already ran
left-to-right. Holding the markup constant matters: wrapping one side in <bdi>
perturbs layout on its own and reports false breakage.

CONSEQUENCE: one oracle is enough for this rule going forward. The browser is
the cheaper one, so the sweep harness uses it.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from compliance_engine.report_chrome import isolate_ltr, _runs  # noqa: E402

TS_MODULE = ROOT / "app/frontend/src/lib/bidi.tsx"

# Every shape the sweep found broken, plus shapes that must be LEFT ALONE.
FIXTURES = [
    # -- must be isolated (measured broken before the fix) ------------------
    "גבולות תאי השטח יוגשו בשכבה ייעודית: 0_LOTS או תא_שטח_X, כאשר X הוא מספר תא השטח.",
    "קווי הבניין יוגשו בשכבה ייעודית: 0_SETBACK או קו_בניין.",
    "גבולות המגרש יוגשו בשכבה ייעודית: 0_BOUNDARY או קו_מגרש.",
    "מבני המגורים יוגשו בשכבה ייעודית: 0_BLDG או בניין_X.",
    "המרחבים הפתוחים יוגשו בשכבה ייעודית: 0_OPEN_SPACE או שצ”פ.",
    "קובץ החוברת לא יעלה על 100 MB.",
    "יש לוודא שכל קובץ DWG או DXF אינו עולה על 200 MB.",
    "יצורף נספח בנייה ירוקה ת”י 5281 - PDF נפרד.",
    "לדוגמה: 407-1048248_הטייסים_24.3.pdf",
    # -- must be left alone (already render correctly) ----------------------
    "יצורף קובץ CAD בפורמט DXF או DWG בגרסה AC1018 ומעלה.",
    "כל הגיאומטריה תיוצג ביחידות מטרים, במערכת הקואורדינטות (ITM), EPSG:2039.",
    "תכנית הגג תוגש בקנה מידה 1:500 לפחות.",
    "החוברת תכלול ניתוח שמש (21.12, 9:00-15:00).",
    "עמודי החוברת יוגשו בגודל A3 אופקי או A1 אופקי.",
    "פתחי הממ”ד יסומנו במפורש בכל קומה טיפוסית.",
]

MUST_ISOLATE = {
    "0_LOTS", "0_SETBACK", "0_BOUNDARY", "0_BLDG", "0_OPEN_SPACE",
    "100 MB", "200 MB", "5281 - PDF", "407-1048248_הטייסים_24.3.pdf",
}


def _py_spans(text: str) -> list[str]:
    return [text[a:b] for a, b in _runs(text)]


def _ts_spans_all() -> dict[str, list[str]]:
    """Run the REAL TypeScript module through esbuild + node.

    Deliberately not a hand-stripped copy: a gate that tests a mangled version
    of the shipped file proves nothing about the shipped file.
    """
    esbuild = ROOT / "app/frontend/node_modules/.bin/esbuild"
    if not esbuild.exists():
        pytest.skip("esbuild not installed (run npm ci in app/frontend)")
    if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
        pytest.skip("node not available")

    # Harness and bundle live under app/frontend so node resolves react
    # from the frontend's own node_modules.
    fe = ROOT / "app/frontend"
    harness = fe / "src" / "_bidi_entry.tsx"
    harness.write_text(
        'import { ltrRuns } from "./lib/bidi";\n'
        f"const FIX = {json.dumps(FIXTURES, ensure_ascii=False)};\n"
        "const out: Record<string, string[]> = {};\n"
        "for (const t of FIX) out[t] = ltrRuns(t).map(([a, b]) => t.slice(a, b));\n"
        "console.log(JSON.stringify(out));\n",
        encoding="utf-8")
    bundle = fe / "_bidi_bundle.mjs"
    try:
        b = subprocess.run(
            [str(esbuild), str(harness), "--bundle", "--format=esm",
             "--platform=node", "--jsx=automatic", f"--outfile={bundle}",
             "--log-level=error"],
            capture_output=True, text=True, cwd=str(fe))
        if b.returncode != 0:
            pytest.fail(f"esbuild failed:\n{b.stderr}")
        r = subprocess.run(["node", str(bundle)], capture_output=True,
                           text=True, cwd=str(fe))
        if r.returncode != 0:
            pytest.fail(f"TypeScript rule failed to run:\n{r.stderr}")
        return json.loads(r.stdout)
    finally:
        harness.unlink(missing_ok=True)
        bundle.unlink(missing_ok=True)


def test_known_broken_tokens_are_isolated():
    """Each token the sweep measured as reordered must end up inside a bdi."""
    found: set[str] = set()
    for text in FIXTURES:
        found |= set(_py_spans(text))
    missing = sorted(MUST_ISOLATE - found)
    assert not missing, (
        "tokens known to reverse in RTL text are NOT isolated: "
        + ", ".join(missing)
    )


def test_correctly_rendering_text_is_left_alone():
    """Isolating a token that already renders correctly is a regression risk;
    in particular a Hebrew identifier must never be forced to LTR."""
    assert "תא_שטח_X" not in _py_spans(FIXTURES[0])
    assert "קו_בניין" not in _py_spans(FIXTURES[1])
    # a Hebrew word next to Latin must not be swallowed into the run
    spans = _py_spans("יצורף קובץ CAD בפורמט DXF או DWG בגרסה AC1018 ומעלה.")
    assert all("או" not in s for s in spans), spans


def test_sentence_punctuation_stays_outside_the_isolate():
    """A trailing period belongs to the RTL paragraph, not to the token."""
    for text in FIXTURES:
        for s in _py_spans(text):
            assert not s.endswith("."), f"period swallowed into isolate: {s!r}"
            assert not s.startswith("("), f"paren swallowed into isolate: {s!r}"


def test_surrounding_hebrew_is_preserved_exactly():
    """The isolate must add markup only - never change a character of text."""
    for text in FIXTURES:
        html = isolate_ltr(text)
        stripped = re.sub(r"</?bdi[^>]*>", "", html)
        unescaped = (stripped.replace("&amp;", "&").replace("&lt;", "<")
                     .replace("&gt;", ">").replace("&quot;", '"')
                     .replace("&#x27;", "'"))
        assert unescaped == text, f"text changed:\n  in : {text!r}\n  out: {unescaped!r}"


def test_python_and_typescript_rules_agree():
    """Two implementations, one rule. This is the only thing keeping them
    in step - there is no shared code path between Python and the browser."""
    ts = _ts_spans_all()
    mismatches = []
    for text in FIXTURES:
        py = _py_spans(text)
        if ts.get(text) != py:
            mismatches.append(f"\n  text: {text}\n  py: {py}\n  ts: {ts.get(text)}")
    assert not mismatches, (
        "the Python and TypeScript isolation rules diverged:" + "".join(mismatches)
    )
