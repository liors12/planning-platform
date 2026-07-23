"""Layer 0b — jargon lexicon gate.

Fails when a forbidden term (qa/jargon-lexicon.txt) appears in a
Hebrew-containing line of frontend source or sidecar/engine Python — those
lines are user-facing strings. False positives go in qa/jargon-whitelist.txt.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEBREW = re.compile(r"[֐-׿]")


def _load(path):
    return [
        l.strip() for l in (ROOT / path).read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.strip().startswith("#")
    ]


LEXICON = _load("qa/jargon-lexicon.txt")
WHITELIST = [tuple(l.split(":", 1)) for l in _load("qa/jargon-whitelist.txt")]


def _whitelisted(path: str, line: str) -> bool:
    return any(p in path and s in line for p, s in WHITELIST)


def _files():
    yield from (ROOT / "app/frontend/src").rglob("*.tsx")
    yield from (ROOT / "app/frontend/src").rglob("*.ts")
    yield from (ROOT / "app/sidecar/sidecar").rglob("*.py")
    yield from (ROOT / "compliance_engine").glob("*.py")


def test_no_jargon_in_hebrew_strings():
    offenders = []
    for f in _files():
        rel = str(f.relative_to(ROOT))
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not HEBREW.search(line):
                continue
            stripped = line.strip()
            # Comment-only lines are not user-facing.
            if stripped.startswith(("#", "//", "/*", "*", "•")):
                continue
            for term in LEXICON:
                if term in line and not _whitelisted(rel, line):
                    offenders.append(f"{rel}:{i}: [{term}] {line.strip()[:90]}")
    assert not offenders, (
        "jargon found in user-facing Hebrew lines (fix the string or whitelist "
        "a false positive in qa/jargon-whitelist.txt):\n" + "\n".join(offenders)
    )
