"""Critical-finding filter for the M3 critic.

A finding is `critical` (worth Flash-critiquing) when EITHER:

  Base rule — `compliance_indicator ∈ {compliant, non_compliant}` AND
              `confidence == "high"` AND
              `extraction.value` contains a digit AND
              `source_pages` is non-empty.

  5.table exception — `clause_id` starts with "5.table" AND
                      `confidence == "high"` AND
                      `extraction.value` contains a digit AND
                      `source_pages` is non-empty.

The 5.table exception (added in m3-v2) brings the rights-table per-plot
row extractions into critique scope despite their `requires_review`
indicator. M2 correctly defers row-vs-takanon threshold comparison to M4
by emitting `requires_review`, but the EXTRACTED VALUES on those rows are
still numeric reads from drawings — exactly the kind of mis-read the
critic is best at catching. The critic's role on table rows is to
double-check the value (not the compliance verdict).

Other `requires_review` / `missing` / `deferred_to_dwg` findings remain
out-of-scope — they're not actionable verdicts and most have no specific
numeric to second-guess.
"""

from __future__ import annotations

import re
from typing import Any, Dict


_HAS_DIGIT = re.compile(r"[-+]?\d")


def has_digit(s: Any) -> bool:
    return bool(_HAS_DIGIT.search(str(s or "")))


def is_critical(m2_finding: Dict[str, Any]) -> bool:
    """Return True if this M2 finding should be sent to the critic."""
    confidence = m2_finding.get("confidence")
    pages = m2_finding.get("source_pages") or []
    extraction = m2_finding.get("extraction") or {}
    val = extraction.get("value") or ""

    if confidence != "high" or not pages or not has_digit(val):
        return False

    indicator = m2_finding.get("compliance_indicator")
    base = indicator in ("compliant", "non_compliant")

    cid = m2_finding.get("clause_id") or ""
    table_exception = isinstance(cid, str) and cid.startswith("5.table")

    return base or table_exception
