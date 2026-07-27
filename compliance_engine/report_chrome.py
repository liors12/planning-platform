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
