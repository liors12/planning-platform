"""Extract findings from a case decision and classify their reason_class.

Findings come from two places:
  - Rejections: numbered list following "לא ניתן לאשר את הבקשה כפי שהוגשה שכן:"
  - Approvals/Deferrals: subject-matter description and any concession/judgment text

We use **only the four reason_class values** observed in the manual gold standard:
  source_missing_or_incomplete, numeric_rule_violation,
  non_conformance_with_plan, qualitative_judgment.

Anything that doesn't match → reason_class=null + needs_classification=true.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .verdict_classifier import fuzzy_hebrew


# ── Reason-class regex library ────────────────────────────────────────
# Patterns are evaluated in order; first match wins. Be conservative —
# false positives are worse than misses (which fall through to None).

# Order matters: numeric beats non-conformance when both signals appear in
# the same finding (e.g. "5.72 מ' במקום 5.00 מ' המותרים בניגוד להוראות ג1/" —
# the specific numeric overrun is the primary classification).
REASON_CLASSIFIERS: list[tuple[str, list[re.Pattern]]] = [
    ("numeric_rule_violation", [
        re.compile(r"במקום\s+\S+\s*(?:מ['\"׳״]|מטר|מ׳)?\s*המותר"),
        re.compile(r"בגובה\s+של\s+\S+\s*(?:מ['\"׳״]|מטר|מ׳)?\s*במקום"),
        re.compile(r"מעל\s+\d[\d.,]*\s*(?:מ['\"׳״]|מטר|מ׳)?\s*המותר"),
        re.compile(r"כולל\s+\S.*?מעל\s+\d[\d.,]*\s*(?:מ['\"׳״]|מטר|מ׳)?\s*המותר", re.DOTALL),
        re.compile(r"\d[\d.,]*\s*(?:מ['\"׳״]|מטר|מ׳)\s+במקום\s+\d"),
        re.compile(r"חורג\s+מהמותר"),
    ]),
    ("non_conformance_with_plan", [
        # "אינה תואמת תוכנית …" / "אינה תואמת ג1/ …" / "אינה תואמת ל1 …"
        # Note: classification text is normalized to insert space between
        # Hebrew letter and digit (e.g. "ג1" → "ג 1"), so we allow optional ws.
        re.compile(r"אינה\s+תואמת\s+(?:תוכנית|תכנית|ל\s?\S+|\S+/|[א-ת]\s?\d)"),
        re.compile(r"בניגוד\s+להוראות"),
        # Verb forms of "contradicts" (added 2026-05-01 from sample-30 review).
        # Catches "נוגדת הוראות התכנית", "נוגד הנחיות העיצוב", etc.
        re.compile(r"\bנוגד(?:ת|ים|ות)?\s+(?:הוראות|הוראה|תכנית|תוכנית|תקנות|מדיניות|הנחיות|את\s+הוראות)"),
        # "בניגוד ל..." with explicit object (regulations/policy/guidelines).
        # The bare "בניגוד להוראות" already exists; these are the other
        # frequent collocations we missed.
        re.compile(r"בניגוד\s+ל(?:תקנות|תקנה|מדיניות|הנחיות|הנחיה)"),
    ]),
    ("source_missing_or_incomplete", [
        re.compile(r"הוגשה\s+ללא\s"),
        re.compile(r"לא\s+הוגש\b"),
        re.compile(r"לא\s+הוצג(?:ה|ו|ת)?\b"),
        re.compile(r"ללא\s+חישוב"),
        re.compile(r"לא\s+ניתן\s+לבדוק"),
        # Patterns added 2026-05-01 from sample-30 review:
        # "ללא הצגת X" — explicit absence of presentation
        re.compile(r"ללא\s+הצגת\s"),
        # "אין התייחסות ל..." — absence of treatment / reference
        re.compile(r"\bאין\s+התייחסות\s+ל"),
        # "לא הוכח" — proof not demonstrated (requires substantiating evidence)
        re.compile(r"\bלא\s+הוכח\b"),
        # "לא חושבו" — calculations not performed
        re.compile(r"\bלא\s+חושבו\b"),
    ]),
    ("qualitative_judgment", [
        re.compile(r"לא\s+מומלץ\s+לאשר"),
        re.compile(r"נוצרת\s+פגיעה"),
        re.compile(r"בהתאם\s+ל(?:חוות\s+דעת|המלצת)\s+צוות\s+התכנון"),
        re.compile(r"דבר\s+שלא\s+מומלץ"),
        re.compile(r"דבר\s+(?:אשר\s+)?לא\s+ניתן\s+לאשר"),
    ]),
]


# Anchors that mark the start of itemized rejection reasons. We allow the
# intro to span up to ~250 chars including newlines because PyMuPDF often
# breaks the intro line across many vertical fragments before the closing
# "שכן".
REJECTION_INTRO = re.compile(
    r"(?:" + fuzzy_hebrew("לא ניתן לאשר") + r"|" + fuzzy_hebrew("לא לאשר") + r")"
    r".{0,300}?" + fuzzy_hebrew("שכן"),
    re.DOTALL,
)

# Numbered list item. Forms observed in this corpus (PyMuPDF artifacts):
#   ".1 text"           — period before number, same line
#   "1. text"           — period after number, same line
#   "1.\n\n.text"       — period after number on its own line, body next
#   "10\n.\n.text"      — number alone, period on next line, body after
# This pattern handles all four. The first alternative is a "marker line"
# (number-and-period spanning 1–2 lines, no body); the second is "marker
# plus body on same line".
LIST_ITEM_RE = re.compile(
    r"^\s*(?:\.\s*(\d{1,2})|(\d{1,2})\s*\.)\s*$"         # marker spans 1+ lines
    r"|"
    r"^\s*(?:\.\s*(\d{1,2})|(\d{1,2})\s*\.)\s+(.+)$",    # marker + same-line body
    re.MULTILINE,
)


@dataclass
class Finding:
    finding_id: str
    type: str
    text: str
    rule_basis: str | None = None
    reason_class: str | None = None
    needs_classification: bool = False
    finding_subtype: str | None = None  # documentary tag, e.g. "concession"


_HEB = "֐-׿"

def _normalize_for_classification(s: str) -> str:
    """Insert spaces at Hebrew↔digit boundaries and strip stray punctuation
    wedged between digits and Hebrew letters. PyMuPDF artifacts on this corpus
    routinely produce 'במקום5.00' or '5.00 /מ'' which break unit-aware regex.
    Used internally for classification only — does not affect output text.
    """
    s = re.sub(rf"([{_HEB}])(\d)", r"\1 \2", s)
    s = re.sub(rf"(\d)([{_HEB}])", r"\1 \2", s)
    s = re.sub(rf"(?<=\d)\s*[./]\s*(?=[{_HEB}])", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def classify_reason(text: str) -> str | None:
    norm = _normalize_for_classification(text)
    for cls_name, patterns in REASON_CLASSIFIERS:
        for pat in patterns:
            if pat.search(norm):
                return cls_name
    return None


def detect_rule_basis(text: str) -> str | None:
    """Try to detect which plan/regulation a finding refers to.

    Handles common PyMuPDF RTL artifacts on this corpus:
      - The `/` that belongs at the end of "ג1/" sometimes renders detached
        and floats to the start of the previous or next line ("/ג1", or
        "/" alone on its own line preceding "ג1"). Both forms are normalized
        back to "ג1/".
      - Plan codes referenced bare (without "תוכנית" prefix) after anchors
        like "אינה תואמת" or "בניגוד להוראות".
    """
    # ── Normalize detached slash artifacts ──
    # "/ג1" → "ג1/"  (slash before letter+digits, no whitespace)
    norm = re.sub(r"/([א-ת]\.?\s*\d+(?:[א-ת]\d*)?)", r"\1/", text)

    # PyMuPDF RTL wrap: a "/" that should belong to the end of a plan code
    # (e.g. "ג1/") sometimes wraps to a position before a different word,
    # ending up adjacent to a Hebrew letter rather than digit (e.g. "/הבקשה",
    # " /מ' המותרים"). The signature is a slash with whitespace OR line-start
    # before it AND a Hebrew letter immediately after — this never happens in
    # legitimate text where slashes follow digits ("ג1/", "תמ"א 38/3").
    has_orphan_slash = bool(re.search(r"(?:^|\s|\n)/(?=[א-ת])", text))
    if has_orphan_slash:
        # Tag any plain "ג1" / "ג.1" / "תוכנית ג1" forms with a trailing slash,
        # only when they appear after a non-conformance/violation anchor and
        # don't already have a slash.
        norm = re.sub(
            r"((?:אינה\s+תואמת|בניגוד\s+ל(?:הוראות\s+)?|להוראות\s+)"
            r"\s*(?:תוכנית\s+|תכנית\s+)?"
            r"[א-ת]\.?\s*\d+(?:[א-ת]\d*)?)(?!\s*/)",
            r"\1/",
            norm,
        )

    # תמ"א N (possibly with /M)
    m = re.search(r"תמ['\"]?א\s*\d+(?:/\d+)?", norm)
    if m:
        return m.group(0).strip()

    # Local plans introduced by "תוכנית"/"תכנית" — letter(s) + digit(s) + optional slash
    m = re.search(r"(?:תוכנית|תכנית)\s+([א-ת]+\.?\s*\d+(?:[א-ת]\d*)?\s*/?\s*\d*)",
                  norm)
    if m:
        code = re.sub(r"\s+", "", m.group(1)).rstrip("/")
        # Re-attach a trailing slash if present in the captured group
        if "/" in m.group(1):
            code += "/"
        return f"תוכנית {code}"

    # Bare plan code after non-conformance anchors. Looks for letter+digit
    # forms like "ג1", "ג.1/", "ע1", "ל1" within the cited part.
    m = re.search(
        r"(?:אינה\s+תואמת|בניגוד\s+ל(?:הוראות\s+)?(?:תוכנית\s+)?)"
        r"\s*([א-ת]\.?\s*\d+(?:[א-ת]\d*)?\s*/?\s*\d*)",
        norm,
    )
    if m:
        code = re.sub(r"\s+", "", m.group(1)).rstrip("/")
        if "/" in m.group(1):
            code += "/"
        return f"תוכנית {code}"

    # Statutory plan numbers (NNN-NNNN…)
    m = re.search(r"\b(\d{3}-\d{4,7})\b", norm)
    if m:
        return m.group(1)

    # Combined "regulations + committee policy" reference
    if re.search(r"תקנות\s+(?:ה?חוק|התכנון|חניה)", text) and re.search(
            r"מדיניות\s+הו?ועדה", text):
        return "תקנות + מדיניות הועדה"

    return None


def extract_rejection_findings(decision_text: str) -> list[Finding]:
    """For rejections: parse the numbered list of reasons after the intro line."""
    intro = REJECTION_INTRO.search(decision_text)
    if not intro:
        return []
    body = decision_text[intro.end():]

    # Cut at the standard "הערה: טיוטת" closing line
    cut = re.search(r"הערה:\s*טיוטת", body)
    if cut:
        body = body[:cut.start()]
    # Also cut at the next "ההחלטה התקבלה"
    cut2 = re.search(r"ההחלטה\s+התקבלה", body)
    if cut2:
        body = body[:cut2.start()]

    findings: list[Finding] = []
    matches = list(LIST_ITEM_RE.finditer(body))
    if not matches:
        return []

    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        item_text = body[m.start():end].strip()
        # Strip leading marker (".1", "1.", or bare-line forms)
        item_text = re.sub(r"^\s*(?:\.\d+|\d+\.)\s*", "", item_text)
        # Strip leading-line stray period (RTL artifact)
        item_text = re.sub(r"^\s*\.\s*", "", item_text)
        # Squash internal newlines into spaces
        item_text = re.sub(r"\s*\n\s*", " ", item_text).strip()
        # Trim a trailing period
        item_text = item_text.rstrip(".").strip()
        if len(item_text) < 6:
            continue
        findings.append(_make_finding(item_text, len(findings) + 1, "rejection_reason"))
    return findings


def _make_finding(text: str, n: int, ftype: str) -> Finding:
    rc = classify_reason(text)
    return Finding(
        finding_id=f"f{n:03d}",
        type=ftype,
        text=text,
        rule_basis=detect_rule_basis(text),
        reason_class=rc,
        needs_classification=(rc is None),
    )


def extract_approval_findings(decision_text: str) -> list[Finding]:
    """For approvals: extract subject-matter line + any concession/judgment text.

    The first finding is always the approval scope ("approval_subject_matter").
    Additional findings are any "הקלה" (concession) or qualitative-judgment text
    that appears within the decision body.
    """
    findings: list[Finding] = []

    # Subject-matter: from "לאשר את הבקשה" forward, until בכפוף / הקלה / end.
    sub = re.search(
        fuzzy_hebrew("לאשר את הבקשה") + r"\s*(.+?)"
        r"(?:" + fuzzy_hebrew("בכפוף לכל דין") +
        r"|" + fuzzy_hebrew("כולל ההקלות הבאות") +
        r"|הקלה|הקלות|$)",
        decision_text,
        re.DOTALL,
    )
    if sub:
        text = re.sub(r"\s*\n\s*", " ", sub.group(1)).strip()
        text = text.rstrip(",.;:")
        findings.append(Finding(
            finding_id="f001",
            type="approval_subject_matter",
            text=f"לאשר את הבקשה {text}"[:400],
            rule_basis=detect_rule_basis(decision_text[:1500]),
            reason_class=None,
            needs_classification=False,
        ))

    # Concessions: a "הקלה:" / "הקלות:" line OR a "כולל ההקלות הבאות:" intro
    # followed by numbered items.
    concession_intros = [
        re.compile(r"(?:^|\n)\s*(?:הקלה|הקלות)\s*:[\s\n]+(.+?)(?:\n\s*\n|הערה:|בכפוף\s+לכל\s+דין)", re.DOTALL),
        re.compile(fuzzy_hebrew("כולל ההקלות הבאות") + r"\s*:?\s*\n?(.+?)(?:" + fuzzy_hebrew("בכפוף לכל דין") + r"|הערה:|$)", re.DOTALL),
    ]
    for pat in concession_intros:
        for m in pat.finditer(decision_text):
            body = m.group(1)
            # If body has numbered items, split them; else take whole block
            items = list(re.finditer(r"^\s*(?:\.\d+|\d+\.)\s*(.+?)$", body, re.MULTILINE))
            if items:
                texts = []
                marks = list(re.finditer(r"^\s*(?:\.\d+|\d+\.)\s*", body, re.MULTILINE))
                for i, mk in enumerate(marks):
                    end = marks[i+1].start() if i+1 < len(marks) else len(body)
                    seg = body[mk.end():end]
                    seg = re.sub(r"\s*\n\s*", " ", seg).strip().rstrip(".,;:")
                    if len(seg) > 4:
                        texts.append(seg)
                for seg in texts:
                    # Concessions get reason_class=null intentionally — they
                    # don't fit any of the four observed empirical classes
                    # without inventing one. They surface as findings with
                    # needs_classification=true so they're easy to find later.
                    findings.append(Finding(
                        finding_id=f"f{len(findings)+1:03d}",
                        type="discretionary_concession",
                        text=f"הקלה: {seg}"[:400],
                        rule_basis=detect_rule_basis(seg),
                        reason_class=None,
                        needs_classification=True,
                        finding_subtype="concession",
                    ))
            else:
                text = re.sub(r"\s*\n\s*", " ", body).strip()[:400]
                if len(text) > 4:
                    findings.append(Finding(
                        finding_id=f"f{len(findings)+1:03d}",
                        type="discretionary_concession",
                        text=f"הקלה: {text}",
                        rule_basis=detect_rule_basis(text),
                        reason_class=None,
                        needs_classification=True,
                        finding_subtype="concession",
                    ))
            # Don't double-fire on the same case from both patterns
            if findings:
                break
        if any(f.type == "discretionary_concession" for f in findings):
            break

    return findings


def extract_deferral_findings(decision_text: str) -> list[Finding]:
    """For deferred decisions: capture the deferral cause/condition.

    The full pattern is "לשוב ולדון בעוד <timeframe>, לאחר <substantive cause>".
    The substantive cause after "לאחר" is the actual finding; the timing
    phrase before it is metadata (already encoded in verdict_text).
    """
    m = re.search(r"לשוב\s+ולדון\s+(?:בעוד\s+)?(.+?)(?:הערה:|ההחלטה\s+התקבלה|$)",
                  decision_text, re.DOTALL)
    if not m:
        return []
    text = re.sub(r"\s*\n\s*", " ", m.group(1)).strip()
    # Collapse PyMuPDF "לאחר לאחר" duplication artifact
    text = re.sub(r"\bלאחר\s+לאחר\b", "לאחר", text)

    # Prefer the substantive cause: everything after the first "לאחר" /
    # "בכפוף ל" / "בתנאי ש" anchor. Falls back to the full span if no anchor.
    cause = re.search(r"(?:לאחר|בכפוף\s+ל|בתנאי\s+ש)\s+(.+)", text, re.DOTALL)
    if cause:
        text = cause.group(1).strip()

    text = text.rstrip(",.;:").strip()[:400]
    if not text:
        return []
    return [Finding(
        finding_id="f001",
        type="deferral_reason",
        text=text,
        rule_basis=None,
        reason_class="source_missing_or_incomplete",
        needs_classification=False,
    )]


def extract_findings(decision_text: str, verdict: str) -> list[Finding]:
    if verdict == "rejected":
        return extract_rejection_findings(decision_text)
    if verdict == "deferred":
        return extract_deferral_findings(decision_text)
    if verdict in ("approved", "approved_with_conditions", "partial_approve"):
        return extract_approval_findings(decision_text)
    return []
