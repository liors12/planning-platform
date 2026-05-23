"""Extract full text from a Tel Aviv subcommittee protocol PDF.

PyMuPDF returns Hebrew text in logical reading order. We do minimal
normalization — collapse blank lines, strip trailing whitespace, and patch
two recurring PyMuPDF artifacts in mixed-direction Hebrew/digit text:

  1. Colon or period wedged INSIDE a Hebrew word, with a Hebrew letter on
     each side. Examples seen in 2-22-0009: "לאש:ר" (לאשר), "מ:ספר" (מספר),
     "לאש:ר" (לאשר). These come from RTL renderer placing punctuation in
     visual order. Strip them — they are never legitimate Hebrew.
  2. Number-period markers ("1.", "2.") that get split across line breaks
     when followed by a digit-and-Hebrew run. Left intact in the joined
     text; the list-item parser accepts both forms.

Structural newlines and field anchors are preserved.
"""
from __future__ import annotations

import re
from pathlib import Path

import fitz


PAGE_SEP = "\n\n[[PAGE_BREAK]]\n\n"


# Punctuation wedged between two Hebrew letters — never legitimate.
_INLINE_HEBREW_PUNCT = re.compile(r"(?<=[֐-׿])[:](?=[֐-׿])")

# Stray period wedged INSIDE a Hebrew word with NO whitespace on either side.
# This is a PyMuPDF artifact (e.g. "הוראו.ת" instead of "הוראות"). Legitimate
# uses of period in Hebrew planning text always have whitespace adjacent —
# sentence boundaries ("X. Y"), abbreviations marked with quotes ("ת\"א",
# "מ\"ר") never use periods, and apostrophes ("קומה א'") are a different
# character. The "no whitespace either side" guard is what makes this safe.
_INLINE_HEBREW_PERIOD = re.compile(r"(?<=[֐-׿])\.(?=[֐-׿])")


def _patch_artifacts(text: str) -> str:
    """Remove colons and stray periods wedged inside Hebrew words.

    Both patterns require a Hebrew letter on each side with no whitespace —
    the signature of PyMuPDF's RTL rendering quirk. Legitimate Hebrew text
    never produces these forms.
    """
    text = _INLINE_HEBREW_PUNCT.sub("", text)
    text = _INLINE_HEBREW_PERIOD.sub("", text)
    return text


def extract_text(pdf_path: Path) -> tuple[str, list[str]]:
    """Return (joined_text, per_page_text). Pages joined by PAGE_SEP marker."""
    doc = fitz.open(pdf_path)
    pages = [doc.load_page(i).get_text() for i in range(doc.page_count)]
    doc.close()

    cleaned = []
    for p in pages:
        lines = [ln.rstrip() for ln in p.splitlines()]
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = _patch_artifacts(text)
        cleaned.append(text)

    joined = PAGE_SEP.join(cleaned)
    return joined, cleaned
