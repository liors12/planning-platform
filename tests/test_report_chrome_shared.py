"""Gate: every municipal PDF renders in the same chrome.

Three reports carry the municipality's name - the main סקירת תוכנית עיצוב, the
guidelines export, and the דו"ח התייחסות per attachment. Before v0.2.2 the two
sidecar reports had their own stylesheet and a bare <h1> where the main report
has a branded cover, so an architect receiving both got two documents that did
not look like they came from the same office.

The fix was to share one stylesheet and one cover builder. This gate stops them
drifting apart again. It asserts STRUCTURE - the same header element tree and
the same CSS class names - not pixels, because a rendering diff would be a
WeasyPrint test, and because the only sanctioned difference between the covers
is the title line.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "app" / "sidecar")]

from compliance_engine.report_chrome import (  # noqa: E402
    chrome_css, cover_html, document_html,
)

CSS_PATH = ROOT / "compliance_engine" / "templates" / "report_chrome.css"

# Every class the shared cover emits. A report that grows its own header would
# either miss one of these or introduce a class of its own.
COVER_CLASSES = {
    "cover-v2", "cover-band", "logo", "brand-eyebrow", "brand-name", "rule",
    "title", "cover-body", "cover-meta",
}


def _classes(html: str) -> set[str]:
    out: set[str] = set()
    for attr in re.findall(r'class="([^"]+)"', html):
        out.update(attr.split())
    return out


def _strip_py_comments(text: str) -> str:
    """Blank comments and DOCSTRINGS, keeping every other string literal.

    Docstrings must go too - report_generator's module docstring says
    "CSS @page only", which is documentation of this very rule. But ordinary
    string literals must stay: a stylesheet smuggled back in would live in one,
    and a gate blind to its own subject is the download-anchor bug again.
    """
    import ast

    lines = text.split("\n")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        doc = node.body[0] if node.body else None
        if (isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant)
                and isinstance(doc.value.value, str)):
            for i in range(doc.lineno - 1, doc.end_lineno):
                lines[i] = ""
    return "\n".join(l for l in lines if not l.lstrip().startswith("#"))


def _shape(html: str) -> list[tuple[str, str]]:
    """Element tree as (tag, class) pairs, with consecutive duplicates
    collapsed - a cover with two subtitle lines is the same SHAPE as one with
    a single subtitle, and the number of subtitles is content, not chrome."""
    pairs = [(m.group(1), m.group(2) or "")
             for m in re.finditer(r"<(\w+)(?:\s+class=\"([^\"]*)\")?", html)]
    out: list[tuple[str, str]] = []
    for pair in pairs:
        if not out or out[-1] != pair:
            out.append(pair)
    return out


def _sample_covers() -> dict[str, str]:
    """One cover per report family, built the way each report builds it."""
    return {
        "main": cover_html(
            title="סקירת תוכנית עיצוב",
            subtitles=["תכנית בינוי ופיתוח", "גרסה 24.3"],
            pill="חוות דעת",
            meta_rows=[("תכנית סטטוטורית:", "407-0730606")],
            note="הערה",
            body_extra='<table class="signature-table"><tbody></tbody></table>',
        ),
        "guidelines": cover_html(
            title="הנחיות עירוניות לתוכנית העיצוב",
            subtitles=["מסמך ההנחיות המלא, לפי תחום"],
            pill="הנחיות עירוניות",
            meta_rows=[("גרסת ההנחיות:", "3")],
        ),
        "attachment": cover_html(
            title='דו"ח התייחסות לנספח',
            subtitles=["תנועה", "גרסה 2"],
            pill='דו"ח התייחסות',
            meta_rows=[("תחום:", "תנועה")],
        ),
    }


def test_one_stylesheet_file_exists_and_is_what_reports_load():
    assert CSS_PATH.exists(), "the shared stylesheet is missing"
    assert chrome_css() == CSS_PATH.read_text(encoding="utf-8")


def test_no_report_carries_its_own_stylesheet():
    """A second stylesheet is how the reports drifted apart the first time."""
    offenders = []
    for rel in ("app/sidecar/sidecar/guidelines.py",
                "app/sidecar/sidecar/attachments.py",
                "compliance_engine/report_generator.py"):
        text = _strip_py_comments((ROOT / rel).read_text(encoding="utf-8"))
        # A local stylesheet shows up as @font-face / @page / a body{} rule
        # written inline in Python rather than read from the shared file.
        # Comments are stripped first: the modules DOCUMENT this rule, and a
        # gate that trips on its own explanation is the download-anchor bug.
        for marker in ("@font-face", "@page", "font-family:"):
            if marker in text:
                offenders.append(f"{rel}: inline CSS ({marker})")
    assert not offenders, (
        "report modules must not define CSS - it belongs in "
        "compliance_engine/templates/report_chrome.css:\n" + "\n".join(offenders)
    )


def test_every_cover_emits_the_same_element_structure():
    shapes = {n: _shape(h) for n, h in _sample_covers().items()}
    main = shapes["main"]
    for name in ("guidelines", "attachment"):
        # The main report adds a signature table via body_extra; compare the
        # header portion, which is what "identical but for the title" means.
        head_len = min(len(main), len(shapes[name]))
        assert shapes[name][:head_len] == main[:head_len], (
            f"the {name} cover's header markup diverged from the main report's"
        )


def test_every_cover_uses_the_shared_class_names():
    for name, html in _sample_covers().items():
        missing = sorted(COVER_CLASSES - _classes(html))
        assert not missing, f"{name} cover is missing shared classes: {missing}"


def test_covers_differ_only_in_their_title_line():
    covers = _sample_covers()

    assert _shape(covers["attachment"]) == _shape(covers["guidelines"]), (
        "attachment and guidelines covers differ in more than their text"
    )


def test_classes_used_by_reports_exist_in_the_stylesheet():
    """A class name with no rule renders unstyled and looks like a bug."""
    css = chrome_css()
    used: set[str] = set()
    for html in _sample_covers().values():
        used |= _classes(html)
    used |= {"chapter", "signature-table"}
    unstyled = sorted(c for c in used if f".{c}" not in css)
    assert not unstyled, (
        "class names emitted by reports have no rule in report_chrome.css: "
        + ", ".join(unstyled)
    )


def test_document_shell_wraps_cover_before_content():
    html = document_html(cover="<div class='cover-v2'></div>", content="<p>x</p>")
    assert html.index("cover-v2") < html.index("<p>x</p>")
    assert html.startswith("<html>") and html.endswith("</body></html>")
