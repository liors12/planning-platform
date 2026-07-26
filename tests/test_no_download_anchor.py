"""Convention gate: no `<a download>` anchors in the frontend.

Why this is a hard gate and not a style preference: the shipped app runs
inside a Tauri/WebView2 shell that BLOCKS download navigations silently.
An `<a href=... download>` works perfectly in `npm run dev` and in
Playwright's Chromium, and does nothing at all for Ellen on Windows - no
error, no file, no clue. That exact bug shipped in every build from v0.1.0
to v0.2.0 on the guidelines screen (see qa/RELEASE_QA_SKILL.md, bug family
"WebView2 swallows downloads").

The supported pattern: the sidecar writes the file and opens it via
os_open.open_in_default_app, and the UI calls that endpoint with a button.
See /guidelines/open-pdf and /attachments/{id}/open-report.

This gate is deliberately dumb and textual - it cannot be satisfied by a
spec that passes in Chromium, which is the whole point.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app/frontend/src"

# <a ... download ...> across a single tag, attributes in any order.
# `download` must be a standalone attribute, not part of another word
# (e.g. `downloadUrl` or `onDownload` are fine).
ANCHOR_DOWNLOAD = re.compile(
    r"<a\b[^>]*?(?<![A-Za-z0-9_])download(?![A-Za-z0-9_])",
    re.IGNORECASE | re.DOTALL,
)

# Comments are stripped before matching so that documentation *about* this
# rule (which necessarily quotes the forbidden pattern) does not trip it.
# Newlines are preserved so reported line numbers stay accurate.
COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)


def _strip_comments(text: str) -> str:
    return COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _frontend_files():
    yield from SRC.rglob("*.ts")
    yield from SRC.rglob("*.tsx")


def test_no_download_anchor_in_frontend():
    offenders = []
    for f in _frontend_files():
        text = _strip_comments(f.read_text(encoding="utf-8"))
        for m in ANCHOR_DOWNLOAD.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            offenders.append(f"{f.relative_to(ROOT)}:{line_no}")
    assert not offenders, (
        "`<a download>` found in frontend sources. The packaged WebView2 "
        "shell blocks these silently - the user clicks and nothing happens.\n"
        "Use a button calling a sidecar open-endpoint instead "
        "(see openGuidelinesPdf / openAttachmentReport in api.ts).\n"
        "Offenders:\n" + "\n".join(offenders)
    )
