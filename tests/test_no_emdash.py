"""Convention gate (first-look round 1, item 2): no em/en dashes in
user-facing strings.

Ellen's approved document style uses plain hyphens. This gate fails the suite
if U+2014 (em dash) or U+2013 (en dash) reappears in:
  * ANY frontend source file (app/frontend/src/**/*.ts{,x}) — strings and
    comments alike; banning them wholesale keeps the check trivial and the
    cost is zero.
  * Python lines that contain Hebrew (sidecar + compliance engine) — those
    are user-facing message strings (report text, API detail strings).
    English-only code comments keep their dashes.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHES = ("—", "–")
HEBREW = re.compile(r"[֐-׿]")


def _frontend_files():
    yield from (ROOT / "app/frontend/src").rglob("*.ts")
    yield from (ROOT / "app/frontend/src").rglob("*.tsx")


def _python_files():
    yield from (ROOT / "app/sidecar/sidecar").rglob("*.py")
    yield from (ROOT / "compliance_engine").glob("*.py")


def test_no_emdash_in_frontend_sources():
    offenders = []
    for f in _frontend_files():
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if any(d in line for d in DASHES):
                offenders.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()[:80]}")
    assert not offenders, (
        "em/en dashes found in frontend sources (use plain '-'):\n"
        + "\n".join(offenders)
    )


def test_no_emdash_in_hebrew_python_strings():
    offenders = []
    for f in _python_files():
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if any(d in line for d in DASHES) and HEBREW.search(line):
                offenders.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()[:80]}")
    assert not offenders, (
        "em/en dashes found on Hebrew (user-facing) Python lines (use plain '-'):\n"
        + "\n".join(offenders)
    )
