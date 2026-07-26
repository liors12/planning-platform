"""Open a file in the OS default application.

Why this exists: the packaged app runs inside a Tauri/WebView2 shell that
silently blocks `<a download>` navigations and swallows target="_blank".
Every "download this PDF" affordance therefore routes through the sidecar,
which already has OS access via Python. See qa/RELEASE_QA_SKILL.md, bug
family "WebView2 swallows downloads".

Callers build the path server-side. Never pass a user-supplied path here.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def open_in_default_app(path: Path) -> None:
    """Fire-and-forget open. Failures are logged, never raised: the worst
    case is "user clicks, nothing opens", which the caller can re-prompt
    for, whereas raising would turn a cosmetic miss into a failed request."""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))          # type: ignore[attr-defined]
        else:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen(
                [opener, str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception as exc:
        log.warning("OS open failed for %s: %s", path, exc)


def exports_dir(cfg) -> Path:
    """`<data_dir>/exports/` - where on-demand PDFs are written before the
    OS opens them. Kept out of the per-submission folders because these are
    regenerated artifacts, not submission content."""
    d = cfg.data_dir / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d
