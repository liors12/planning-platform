"""Classify the verdict of a case from its decision text.

PyMuPDF text extraction inserts various artifacts inside Hebrew words on
this corpus: spaces ("ל אשר" for "לאשר"), parens ("הבק)שה" for "הבקשה"),
colons ("לאש:ר") and so on. We build verdict patterns using `fuzzy_hebrew`,
which inserts an optional [\\s\\W]{0,2} between every pair of consecutive
Hebrew letters of a keyword.
"""
from __future__ import annotations

import re


HEBREW_RANGE = "֐-׿"
_FUZZY_GAP = r"[\s\W_]{0,2}"


def fuzzy_hebrew(phrase: str) -> str:
    """Build a regex fragment that matches a Hebrew phrase even when stray
    whitespace, punctuation, or newlines are wedged inside or between words.

    Word boundaries → `[\\s:.,()\\-'"]+` (allows colon/period/apostrophe/
    quote etc.). Within a word, consecutive Hebrew letters get a
    `[\\s\\W_]{0,2}` gap so PyMuPDF artifacts (e.g. "ל אשר", "לאש:ר",
    "לאשר ,'את") still match. Apostrophes and quotes are never legitimate
    inside a Hebrew word, so allowing them in the separator is safe.
    """
    out: list[str] = []
    for word in phrase.split():
        chars = list(word)
        out.append(_FUZZY_GAP.join(re.escape(c) for c in chars))
    return r"""[\s:.,()\-'"]+""".join(out)


VERDICT_PATTERNS = [
    # Each entry: (verdict_label, pattern). The classifier finds the earliest
    # match in the decision text — first verdict statement wins, ignoring
    # later mentions like "לדחות את ההתנגדויות" inside an approval.
    #
    # Note: rejection patterns specifically require "הבקשה" — "לדחות את
    # ההתנגדויות" (rejecting objections) is part of an approval, not a
    # case rejection.
    ("partial_approve",          re.compile(fuzzy_hebrew("לקבל את ההתנגדות"))),
    ("deferred",                 re.compile(fuzzy_hebrew("לשוב ולדון"))),
    ("rejected",                 re.compile(fuzzy_hebrew("לא ניתן לאשר") + r"\s+" + fuzzy_hebrew("את הבקשה"))),
    ("rejected",                 re.compile(fuzzy_hebrew("לדחות את הבקשה"))),
    # "לא לאשר את הבקשה" — observed variant rejection
    ("rejected",                 re.compile(fuzzy_hebrew("לא לאשר") + r"\s+" + fuzzy_hebrew("את הבקשה"))),
    ("approved_with_conditions", re.compile(fuzzy_hebrew("לאשר את הבקשה") + r".*?" + fuzzy_hebrew("בכפוף לכל דין"), re.DOTALL)),
    ("approved",                 re.compile(fuzzy_hebrew("לאשר את הבקשה"))),
    # Approve a correction of a prior decision (e.g. 18-0356, "לאשר את
    # תיקון החלטת הוועדה שמספרה …"). Locked to this exact phrasing — uses
    # fuzzy_hebrew only to absorb intra-word spacing artifacts (PyMuPDF
    # renders "לאשר" as "ל אשר" on this corpus), not to broaden the match.
    ("approved",                 re.compile(fuzzy_hebrew("לאשר את תיקון החלטת הוועדה"))),
    # Cancel prior concessions and re-classify rights under תמ"א 38
    # (e.g. 17-2030, 18-0965, 18-0966 — "לבטל … הקלות אלו אינן הקלות … מאושרות
    # מכוח תמ"א 38"). The triple anchor "לבטל" + "אינן הקלות" + "מאושרות"
    # makes the pattern specific to this re-classification approval.
    # fuzzy_hebrew used on each keyword to absorb intra-word spacing artifacts
    # (e.g. PyMuPDF renders "הקלות" as "ה קלות" on this corpus).
    ("approved",                 re.compile(
        fuzzy_hebrew("לבטל") + r".{0,800}?"
        + fuzzy_hebrew("הקלות אלו אינן הקלות") + r".{0,150}?"
        + fuzzy_hebrew("מאושרות"),
        re.DOTALL,
    )),
    # Correction + approve (e.g. 18-1509 "לתקן את ההחלטה ... ולאשר את הבלטת
    # מרפסות …", 19-0856 "לתקן את ההחלטה ... ולאשר את הקטנת קו בניין …").
    # The "לתקן ... ולאשר" pairing is unique to this re-examination flow —
    # not used in rejections.
    ("approved",                 re.compile(
        fuzzy_hebrew("לתקן את ההחלטה") + r".{0,300}?" + fuzzy_hebrew("ולאשר"),
        re.DOTALL,
    )),
    # Continuation + approve (e.g. 19-1456 "בהמשך להחלטת רשות הרישוי ... לאשר
    # פטור מהסדר חניה …", 19-0950 "בהמשך להחלטת הוועדה … לאשר שינוי צורת
    # הדיפון", 20-0173 "בהמשך להחלטת הוועדה … לאשר את שינוי מיקום בריכת
    # השחייה"). N=3 instances observed in 2021–2022 protocols. Same shape
    # as patterns 1–3 — a subsequent discussion of a prior committee decision.
    ("approved",                 re.compile(
        fuzzy_hebrew("בהמשך להחלטת") + r".{0,300}?" + fuzzy_hebrew("לאשר"),
        re.DOTALL,
    )),
]


def classify(decision_text: str) -> tuple[str, str | None, float]:
    """Return (verdict, verdict_text, confidence).

    Strategy: find ALL pattern hits, pick the one with the earliest start
    offset. Tie-broken by pattern-list order (so approved_with_conditions
    wins over approved when both fire at the same spot).
    """
    best: tuple[int, int, str, str] | None = None  # (offset, list_index, label, span)
    for idx, (verdict, pat) in enumerate(VERDICT_PATTERNS):
        m = pat.search(decision_text)
        if m is None:
            continue
        span = m.group(0).strip()
        if len(span) > 120:
            span = span[:120].rstrip() + "…"
        candidate = (m.start(), idx, verdict, span)
        if best is None or candidate < best:
            best = candidate

    if best is None:
        return "unknown", None, 0.0
    return best[2], best[3], 0.95
