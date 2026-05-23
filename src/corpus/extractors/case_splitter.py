"""Split protocol text into per-case blocks.

The most reliable anchor in the Tel Aviv subcommittee format is the per-page
header that introduces every case page:

    עיריית תל אביב– יפו
    חוק התכנון והבניה התשכ"ה1965
    מינהל           ההנדסה
    <CASE_ID>
    'עמN

We match `מינהל ההנדסה` followed by a case_id line followed by `'עמ\d+`.
This is the page banner that appears on every page of every case, so we
dedup by case_id (first occurrence wins) and slice between consecutive
unique case_ids to get per-case blocks.

Why not "בקשה מספר": that anchor is also present in the agenda table on
pages 1–2 (column header), and PyMuPDF can corrupt it on individual pages
(e.g. case 22-0634 in 2-22-0009 renders as 'בקשה מ :ספר' — colon wedged
into the middle of the word).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# Per-page banner anchors. Tel Aviv reorganized the planning department
# from "מינהל ההנדסה" to "אגף רישוי ופיקוח על הבניה" between protocol
# 2-23-0002 and 2-23-0003 (mid-2023), then again to "מינהל הנדסה" (single
# ה) by early 2024. The per-page banner layout changed at the first
# transition; the case body, verdict structure, and conditions structure
# survived intact. Both banner layouts are supported here so a single
# corpus pipeline can ingest protocols across the entire timeline.
#
# OLD format (≤2-23-0002, "מינהל ההנדסה" department):
#     מינהל ההנדסה
#     <case_id>
#     'עמN
#
# NEW format (≥2-23-0003, "אגף רישוי ופיקוח על הבניה" department):
#     <case_id> : בקשת רישוי<online_id> :הגשה מקוונת
#     N ' עמ
#     <contact strip>
#     אגף רישוי ופיקוח על הבניה
#
# Each pattern captures group(1) = case_id. split_cases() runs both,
# merges hits, and dedups by case_id (first occurrence per id wins).

OLD_PAGE_HEADER_RE = re.compile(
    r"מינהל\s+ההנדסה\s*\n+\s*"            # "מינהל ההנדסה" with arbitrary spacing
    r"(\d{2}-\d{3,4})\s*\n+\s*"            # case_id on its own line
    r"['\"]?\s*עמ\s*\d+",                  # "'עמN" page-number indicator
    re.MULTILINE,
)

# NEW format banner is stable from 2-23-0003 onward across two department-
# name variants (mid-2023: "אגף רישוי ופיקוח על הבניה", 2024: "מינהל הנדסה").
# The reliable anchor is the front of the banner — case_id + "בקשת רישוי" +
# "הגשה מקוונת" + page indicator "N 'עמ" — which all three 2023+ variants share.
# We do NOT depend on the department name; that's been changed twice already.
NEW_PAGE_HEADER_RE = re.compile(
    r"(\d{2}-\d{3,4})\s*:\s*"               # case_id at start of banner line
    r"בקשת\s+רישוי\s*\d+\s*:\s*"            # "בקשת רישוי<online_id>"
    r"הגשה\s+מקוונת\s*\n+\s*"                # "הגשה מקוונת" then newline
    r"\d+\s*['\"]?\s*עמ",                   # page number indicator "N ' עמ"
    re.MULTILINE,
)

# Backward-compatible alias — modules importing PAGE_HEADER_RE still work.
PAGE_HEADER_RE = OLD_PAGE_HEADER_RE


@dataclass
class CaseBlock:
    case_id: str
    start: int           # offset in full text
    end: int             # offset in full text
    text: str            # text[start:end]


def split_cases(full_text: str) -> list[CaseBlock]:
    """Return ordered case blocks. The end of case N is the start of case N+1
    (or end of document). Dedup by case_id — first occurrence is the case start;
    later occurrences are continuation-page headers.

    Tries both the old-format (`מינהל ההנדסה`) and new-format (`אגף רישוי
    ופיקוח על הבניה`) banner anchors. A protocol always uses one format
    or the other, so in practice only one regex contributes hits per file.
    """
    # Run both anchors and merge their hits.
    matches = list(OLD_PAGE_HEADER_RE.finditer(full_text))
    matches += list(NEW_PAGE_HEADER_RE.finditer(full_text))

    # First occurrence of each case_id wins (sort by offset).
    matches.sort(key=lambda m: m.start())
    first_offsets: dict[str, int] = {}
    for m in matches:
        cid = m.group(1)
        year = int(cid.split("-")[0])
        if not (15 <= year <= 30):
            continue
        if cid not in first_offsets:
            first_offsets[cid] = m.start()

    ordered = sorted(first_offsets.items(), key=lambda kv: kv[1])

    blocks: list[CaseBlock] = []
    for i, (cid, offset) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else len(full_text)
        blocks.append(CaseBlock(case_id=cid, start=offset, end=end,
                                text=full_text[offset:end]))
    return blocks
