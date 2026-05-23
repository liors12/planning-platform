"""Split conditions block into 3 layers (permit / work_start / completion)."""
from __future__ import annotations

import re


SECTION_ANCHORS = [
    ("permit_conditions",                  re.compile(r"תנאים\s+בהיתר")),
    ("work_start_conditions",              re.compile(r"תנאים\s+להתחלת\s+עבודות")),
    # Two spellings of "occupancy" appear across the corpus: "אכלוס" (no yod,
    # older protocols) and "איכלוס" (with yod, common in 2024+ new-format
    # protocols). Optional yod catches both without breaking anything else.
    ("completion_certificate_conditions",  re.compile(r"תנאים\s+ל(?:תעודת\s+גמר|א[י]?כלוס|טופס\s+4)")),
]


# Sentinel to mark end of conditions block
END_ANCHORS = [
    re.compile(r"הערה:\s*טיוטת"),
    re.compile(r"ההחלטה\s+התקבלה"),
    re.compile(r"נציגים\s+בעלי\s+דעה\s+מייעצת"),
]


def parse_conditions(decision_text: str) -> dict:
    """Return dict with 3 keys, each a list of condition strings."""
    out = {label: [] for label, _ in SECTION_ANCHORS}

    # Find each anchor's offset
    anchor_positions = []
    for label, pat in SECTION_ANCHORS:
        m = pat.search(decision_text)
        if m:
            anchor_positions.append((label, m.start(), m.end()))

    if not anchor_positions:
        return out

    anchor_positions.sort(key=lambda t: t[1])

    # Identify global cut at first end-anchor
    cut = len(decision_text)
    for ea in END_ANCHORS:
        m = ea.search(decision_text)
        if m and m.start() > anchor_positions[0][1]:
            cut = min(cut, m.start())

    for i, (label, _start, header_end) in enumerate(anchor_positions):
        next_start = anchor_positions[i + 1][1] if i + 1 < len(anchor_positions) else cut
        section_text = decision_text[header_end:next_start]
        out[label] = _split_items(section_text)
    return out


# Numbered list item — same tolerant pattern as findings_extractor.
# Forms observed in this corpus (PyMuPDF artifacts):
#   ".1 text"           — period before number, same line
#   "1. text"           — period after number, same line
#   "1.\n text"         — period after number on its own line, body next
#   "1\n.\n text"       — number alone, period alone, body after
#   "1\n.\n.text"       — number alone, period alone, body with stray leading period
# Bullet markers ("- text", "• text") preserved as a fallback.
_LIST_MARKER = re.compile(
    r"^\s*(?:\.\s*(\d{1,2})|(\d{1,2})\s*\.)\s*$"          # marker spans 1+ lines
    r"|"
    r"^\s*(?:\.\s*(\d{1,2})|(\d{1,2})\s*\.)\s+(.+)$"      # marker + same-line body
    r"|"
    r"^\s*[-•]\s+(.+)$",                                   # bullet
    re.MULTILINE,
)


def _split_items(text: str) -> list[str]:
    """Split a section body into individual conditions, slicing between
    numbered list markers (the marker may span multiple lines)."""
    matches = list(_LIST_MARKER.finditer(text))
    items: list[str] = []
    if matches:
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            raw = text[m.start():end]
            # Strip leading "1." / ".1" / bullet marker (and any solitary period
            # left on the next line by RTL rendering)
            raw = re.sub(r"^\s*(?:\.\s*\d{1,2}|\d{1,2}\s*\.|[-•])\s*", "", raw)
            raw = re.sub(r"^\s*\.\s*", "", raw)
            raw = re.sub(r"\s*\n\s*", " ", raw).strip()
            raw = raw.rstrip(".").strip()
            if 4 < len(raw) < 1200:  # roomier ceiling — multi-clause conditions exist
                items.append(raw)
        return items

    # Fallback: split on blank lines (no numbered markers present)
    for chunk in re.split(r"\n\s*\n", text):
        c = re.sub(r"\s+", " ", chunk).strip()
        if 4 < len(c) < 1200:
            items.append(c)
    return items
