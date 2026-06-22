"""Shared text-cleaning utilities for Hebrew PDF extraction.

Centralises PyMuPDF RTL artifact cleanup so that referent_extract.py,
discipline_policy_checker.py, and submission_data_extractor.py all apply
identical normalisation immediately after fitz.get_text().
"""
from __future__ import annotations

import re

# Colon wedged between two Hebrew letters — PyMuPDF RTL rendering quirk.
# Seen as "לאש:ר" (→ "לאשר"), "מ:ספר" (→ "מספר").
_INLINE_HEBREW_PUNCT = re.compile(r"(?<=[֐-׿])[:](?=[֐-׿])")

# Stray period inside a Hebrew word with no whitespace on either side.
# Seen as "הוראו.ת" (→ "הוראות"). Legitimate periods in Hebrew planning
# text always have adjacent whitespace; the no-whitespace guard is what
# makes this safe to strip unconditionally.
_INLINE_HEBREW_PERIOD = re.compile(r"(?<=[֐-׿])\.(?=[֐-׿])")


def patch_rtl_artifacts(text: str) -> str:
    """Remove colons and stray periods wedged inside Hebrew words.

    Both patterns require a Hebrew letter on each side with no whitespace —
    the signature of PyMuPDF's RTL rendering quirk. Legitimate Hebrew text
    never produces these forms.
    """
    text = _INLINE_HEBREW_PUNCT.sub("", text)
    text = _INLINE_HEBREW_PERIOD.sub("", text)
    return text
