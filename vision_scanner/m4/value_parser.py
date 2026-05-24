"""Parse M2 extraction.value strings into typed numerics.

M2 emits values as strings (preserving the model's reading); the engine
overlay schema expects typed ints/floats. This parser handles common formats.
Used for diagnostic/sidecar output — does NOT mutate engine state in M4 v1
since architecture B+ doesn't replace extracts.json.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple


_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def parse_first_number(value: str) -> Optional[float]:
    """Return the first numeric token in `value` as a float, or None."""
    if value is None:
        return None
    s = str(value).replace(",", "").strip()
    m = _NUMBER_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def parse_range(value: str) -> Optional[Tuple[float, float]]:
    """Parse a range string like '10-14' or '9-13' into (low, high). None if not a range."""
    if value is None:
        return None
    s = str(value).strip()
    m = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)\s*[-–]\s*([-+]?\d+(?:\.\d+)?)\s*$", s)
    if not m:
        return None
    try:
        return float(m.group(1)), float(m.group(2))
    except ValueError:
        return None


def coerce_to_int(value: str) -> Optional[int]:
    """Coerce string → int if a single integer is present (no fractional part). Else None."""
    f = parse_first_number(value)
    if f is None:
        return None
    if f != int(f):
        return None
    return int(f)
