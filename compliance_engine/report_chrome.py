"""Shared report chrome: the one place the branded look is defined.

Three PDFs carry the municipality's name - the main סקירת תוכנית עיצוב, the
guidelines export, and the דו"ח התייחסות per attachment. Before v0.2.2 the
sidecar reports had their own black-on-white stylesheet, so an architect who
received both got two documents that did not look like they came from the same
office.

Everything visual lives here or in templates/report_chrome.css: fonts, @page
rules, colour tokens, the cover, section and table styling, the footer. Nothing
is duplicated per report - a report supplies its TITLE and its CONTENT, and
gets the chrome for free.
"""
from __future__ import annotations

import re
import sys
from html import escape
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _bundled(*parts: str) -> Path:
    """Resolve an asset under both the source tree and a PyInstaller bundle.

    The build spec stages assets/ and compliance_engine/templates/ inside
    _MEIPASS; in the source tree they sit under PROJECT_ROOT.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).joinpath(*parts)
    return PROJECT_ROOT.joinpath(*parts)


def resolve_font_dir() -> Path:
    return _bundled("assets", "fonts")


def resolve_logo_path() -> Path:
    return _bundled("assets", "nessziona_logo.png")


def chrome_css() -> str:
    """The stylesheet, read from the single shared file."""
    return _bundled("compliance_engine", "templates",
                    "report_chrome.css").read_text(encoding="utf-8")


# The eyebrow and organisation name are municipal identity, not per-report
# text: every document the מינהלת issues carries them unchanged.
BRAND_EYEBROW = "NZC | מינהלת ההתחדשות העירונית"
BRAND_NAME = "נס ציונה"


def cover_html(*, title: str, subtitles: list[str] | None = None,
               pill: str | None = None,
               meta_rows: list[tuple[str, str]] | None = None,
               note: str | None = None, body_extra: str = "") -> str:
    """The branded cover, identical for every report but the title line.

    Emits the same element tree and the same class names in every case, so the
    structural-equality spec (tests/test_report_chrome_shared.py) can assert
    that no report has quietly grown its own header markup.
    """
    logo_url = resolve_logo_path().as_uri()
    subs = "".join(f'<div class="subtitle">{escape(s)}</div>'
                   for s in (subtitles or []))
    pill_html = f'<div class="pill">{escape(pill)}</div>' if pill else ""
    meta = "".join(
        f'<div><span class="label">{escape(label)}</span> {escape(value)}</div>'
        for label, value in (meta_rows or [])
    )
    note_html = f'<div class="cover-note">{escape(note)}</div>' if note else ""
    return f"""
    <div class="cover-v2">
      <div class="cover-band">
        <img class="logo" src="{logo_url}" alt="">
        <div class="brand-eyebrow">{BRAND_EYEBROW}</div>
        <div class="brand-name">{BRAND_NAME}</div>
        <hr class="rule">
        <h1 class="title">{escape(title)}</h1>
        {subs}
        {pill_html}
      </div>
      <div class="cover-body">
        <div class="cover-meta">{meta}</div>
        {note_html}
        {body_extra}
      </div>
    </div>
    """


def document_html(*, cover: str, content: str) -> str:
    """Wrap a cover plus body content in the shared document shell."""
    return ("<html><head><meta charset='utf-8'></head><body>"
            f"{cover}{content}</body></html>")


# ─────────────────────────────────────────────────────────────────────────────
# Bidi isolation for LTR technical tokens
# ─────────────────────────────────────────────────────────────────────────────
# Hebrew guideline text carries Latin/numeric tokens the architect must copy
# exactly - CAD layer names, file sizes, standard numbers, filenames. Inside an
# RTL paragraph the Unicode bidi algorithm reorders some of them: "0_LOTS"
# displays as "LOTS_0" and "100 MB" as "MB 100". The stored text is correct;
# only the display is wrong, in the browser AND in WeasyPrint/Pango, which
# implement the same algorithm. An architect copying a layer name off the
# screen or out of the PDF types the wrong string.
#
# The fix is markup: wrap each such run in <bdi dir="ltr">, which opens a
# directional isolate so the run is laid out on its own and cannot be
# reordered against its Hebrew neighbours.
#
# TWO IMPLEMENTATIONS, ONE RULE. This function serves every PDF; the app screen
# needs the same rule in TypeScript (app/frontend/src/lib/bidi.tsx). They are
# kept in step by tests/test_bidi_isolation.py, which asserts both segment an
# identical fixture list the same way.

# Implemented as a word scanner rather than one regex: the rule has to be
# ported to TypeScript verbatim, and a scanner is far easier to keep in step.

_CONNECTORS = "_.:+-/\u00d7"          # chars that may sit INSIDE a run
_TRIM = " \t,;()[]\u201c\u201d\u2019\"'\u05f4\u05f3.!?\u00b7"   # never inside an isolate


def _is_hebrew(ch: str) -> bool:
    return "\u0590" <= ch <= "\u05ff"


def _ascii_tok(w: str) -> bool:
    """A word made only of ASCII alnum and connectors (100, MB, 0_LOTS, -)."""
    return bool(w) and all(
        (c.isascii() and c.isalnum()) or c in _CONNECTORS for c in w)


def _mixed_token(w: str) -> bool:
    """A FILENAME mixing Hebrew with ASCII - 407-1048248_הטייסים_24.3.pdf.
    Rendering it as one LTR run is what makes it read as a filename.

    Deliberately narrow: it must carry a dot-extension. A Hebrew identifier
    like תא_שטח_X renders correctly today, and forcing LTR on it would change
    output that is not broken.
    """
    return (any(_is_hebrew(c) for c in w)
            and re.search(r"\.[A-Za-z0-9]{2,4}$", w) is not None
            and any(c.isascii() and c.isalnum() for c in w))


def _runs(text: str) -> list[tuple[int, int]]:
    """Character spans to isolate, as (start, end) over `text`."""
    spans: list[list] = []      # [start, end, mergeable_ascii_run]
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        j = i
        while j < n and not text[j].isspace():
            j += 1
        word, ws, we = text[i:j], i, j
        # strip punctuation that must stay OUTSIDE the isolate, so a sentence
        # period keeps its normal RTL placement
        while ws < we and text[ws] in _TRIM:
            ws += 1
        while we > ws and text[we - 1] in _TRIM:
            we -= 1
        core = text[ws:we]
        if core and (_ascii_tok(core) or _mixed_token(core)):
            # merge with the previous span when only blanks lie between and
            # both sides are ASCII ("100 MB", "5281 - PDF" are one run;
            # "DXF או DWG" is not, because Hebrew breaks the chain)
            if (spans and _ascii_tok(core) and spans[-1][2]
                    and text[spans[-1][1]:ws] != ""
                    and text[spans[-1][1]:ws].strip() == ""):
                spans[-1][1] = we
            else:
                spans.append([ws, we, _ascii_tok(core)])
        i = j
    return [(a, b) for a, b, _ in spans
            if any(c.isascii() and c.isalnum() for c in text[a:b])]


def isolate_ltr(text: str) -> str:
    """HTML-escape `text` and wrap LTR technical runs in a bidi isolate.

    Returns HTML. Callers must NOT escape again.
    """
    out, last = [], 0
    for a, b in _runs(text):
        out.append(escape(text[last:a]))
        out.append(f'<bdi dir="ltr">{escape(text[a:b])}</bdi>')
        last = b
    out.append(escape(text[last:]))
    return "".join(out)
