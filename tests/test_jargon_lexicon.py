"""Layer 0b — jargon lexicon gate.

Fails when a forbidden term (qa/jargon-lexicon.txt) appears in a
Hebrew-containing line of frontend source or sidecar/engine Python — those
lines are user-facing strings. False positives go in qa/jargon-whitelist.txt.
"""
from __future__ import annotations

import json
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
    yield ROOT / "app/sidecar/seed/guidelines_seed.json"


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


# v0.2.1: internal identifiers (CAD layer names, rule codes) are jargon that
# no lexicon can enumerate - they are invented ad hoc. Match the SHAPE
# instead. Seeded guideline text is what Ellen reads as municipal guidance,
# so a leaked "SETBACK_0" there is a content bug.
#
# v0.2.2: the original pattern required two capitals BEFORE the underscore,
# so the docx's own layer names - 0_LOTS, 0_OPEN_SPACE - never matched it.
# The gate was blind to the exact shape the guidelines use. Widened to catch
# the leading-digit form too. Five of those names are approved content (the
# architect must know which layer to name in the CAD file), so they are
# whitelisted BY NAME - not by loosening the pattern back.
TECH_ID = re.compile(r"(?<![A-Za-z0-9_])(?:[A-Z]{2,}|\d+)_[A-Z0-9_]+")

# Approved CAD layer names, quoted verbatim from the docx (חלק א, 2.א קבצי CAD).
# Ellen's architects submit files whose layers must carry these exact strings,
# so the identifier IS the guidance. Anything not on this list is still a leak.
ALLOWED_TECH_IDS = {
    "0_LOTS",
    "0_SETBACK",
    "0_BOUNDARY",
    "0_BLDG",
    "0_OPEN_SPACE",
}


def test_no_technical_identifiers_in_guideline_text():
    seed = json.loads(
        (ROOT / "app/sidecar/seed/guidelines_seed.json").read_text(encoding="utf-8")
    )
    offenders = []
    for row in seed["guidelines"]:
        for field in ("title", "body_text"):
            value = row.get(field) or ""
            for hit in TECH_ID.findall(value):
                if hit in ALLOWED_TECH_IDS:
                    continue
                offenders.append(f"{row['title']!r} ({field}): {hit}")
    assert not offenders, (
        "internal identifiers found in guideline text Ellen reads. Map them to "
        "Hebrew wording in TECH_ID_REPLACEMENTS (scripts/extract_guidelines_docx.py) "
        "and re-run the extraction:\n" + "\n".join(offenders)
    )
