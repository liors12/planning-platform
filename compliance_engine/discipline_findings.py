"""Loader for Cowork's hand-extracted multi-discipline findings.

The architect's PDF for v24.3 is rasterized, so automated discipline checks
fall back to `requires_review`. A hand-extracted JSON
(`discipline_findings.json`) sitting next to the PDF in the submission
directory acts as the temporary source of truth until the vision-LLM
discipline extractor lands.

Schema (top-level):
  disciplines: {
    "3.1_garbage": {
      "name": "...",
      "findings": [
        {
          "rule_hebrew": "...",
          "verdict": "pass" | "fail" | "requires_review",
          "evidence_pages": [int, ...],
          "evidence_visual": "...",
          "compliance_note": "...",
        },
        ...
      ]
    },
    ...
  }

The engine's `discipline_rules.json` rule names (`rule_name_he`) don't always
match Cowork's `rule_hebrew` verbatim — qualifiers in parentheses, em-dash
suffixes, and an occasional missing/extra word are common. `find_finding()`
applies a tiered matcher:

  1. exact match after whitespace + Hebrew-quote normalization
  2. match after stripping qualifiers (drop from first `(`; drop em-dash tail)
  3. token Jaccard ≥ 0.7
  4. squash equality (remove all whitespace + punctuation)

Returns the matching finding dict, or `None` when no tier hits.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


# Hebrew gershayim (U+05F4) and curly quotes → ASCII double-quote
_QUOTE_VARIANTS = {
    "״": '"',
    "“": '"',
    "”": '"',
    "″": '"',
    "׳": "'",
    "‘": "'",
    "’": "'",
}

_TOKEN_SPLIT_RE = re.compile(r"[\s,/()]+")
_SQUASH_RE = re.compile(r"[\s,/()\-—–.]+")
_EM_DASH_SUFFIX_RE = re.compile(r"\s+[—–-]\s+.*$")
_PAREN_RE = re.compile(r"\([^)]*\)")


def load_discipline_findings(submission_dir: Path | str) -> dict:
    """Load the discipline findings JSON for a submission directory.

    Returns an empty dict when no file exists — caller falls back to the
    engine's default `requires_review` behavior.
    """
    path = Path(submission_dir) / "discipline_findings.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def iter_findings(findings_doc: dict):
    """Yield every finding dict across all disciplines."""
    for discipline in (findings_doc.get("disciplines") or {}).values():
        for finding in discipline.get("findings", []) or []:
            yield finding


def find_finding(findings_doc: dict, rule_name_he: str) -> dict | None:
    """Locate a Cowork finding that matches the engine's rule name.

    Applies a 4-tier matcher; returns the first hit, or `None`.
    """
    if not findings_doc or not rule_name_he:
        return None
    candidates = list(iter_findings(findings_doc))
    if not candidates:
        return None

    target_norm = _normalize(rule_name_he)

    # Tier 1: exact match after normalize.
    for f in candidates:
        if _normalize(f.get("rule_hebrew", "")) == target_norm:
            return f

    # Tier 2: match after stripping qualifiers.
    target_stripped = _strip_qualifiers(target_norm)
    for f in candidates:
        if _strip_qualifiers(_normalize(f.get("rule_hebrew", ""))) == target_stripped:
            return f

    # Tier 3: token Jaccard ≥ 0.7.
    target_tokens = _tokens(target_stripped)
    best_score = 0.0
    best_finding: dict | None = None
    for f in candidates:
        cand_tokens = _tokens(_strip_qualifiers(_normalize(f.get("rule_hebrew", ""))))
        score = _jaccard(target_tokens, cand_tokens)
        if score > best_score:
            best_score = score
            best_finding = f
    if best_finding is not None and best_score >= 0.7:
        return best_finding

    # Tier 4: squash equality.
    target_squashed = _squash(target_norm)
    for f in candidates:
        if _squash(_normalize(f.get("rule_hebrew", ""))) == target_squashed:
            return f

    return None


def _normalize(s: str) -> str:
    for src, dst in _QUOTE_VARIANTS.items():
        s = s.replace(src, dst)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _strip_qualifiers(s: str) -> str:
    # Drop every parenthetical group (qualifier in-line or trailing).
    s = _PAREN_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Drop em-dash / en-dash / hyphen suffix (with surrounding spaces).
    s = _EM_DASH_SUFFIX_RE.sub("", s).strip()
    # Drop comma-suffix (qualifier-style trailing clause).
    idx = s.find(",")
    if idx != -1:
        s = s[:idx].strip()
    return s


def _tokens(s: str) -> set[str]:
    return {t for t in _TOKEN_SPLIT_RE.split(s) if t}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _squash(s: str) -> str:
    return _SQUASH_RE.sub("", s)
