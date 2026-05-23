"""Parse a single case block into a structured dict matching the gold-standard
JSON schema (data/corpus/extracted/tlv-2-22-0009-findings.json)."""
from __future__ import annotations

import re
from .case_splitter import CaseBlock
from .verdict_classifier import classify as classify_verdict, fuzzy_hebrew
from .findings_extractor import extract_findings, Finding
from .conditions_parser import parse_conditions


# Procedural subtype anchors. Detect the structural shape of the case
# (e.g. "דיון נוסף" = a re-examination of a prior decision) so the
# downstream classifier can be specialized later if these cases prove
# systematically harder to verdict-classify than first-time decisions.
SUBSEQUENT_DISCUSSION_RE = re.compile(fuzzy_hebrew("דיון נוסף"))


# ── Field anchors ─────────────────────────────────────────────────────
# Each entry: (output_key, regex). The regex must capture group(1) = value.
# Values come AFTER the label in PyMuPDF output (label-then-value, the
# "old format" layout). We grab the first non-empty line that follows
# the anchor (within ~120 chars).

FIELD_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("gush",          re.compile(r"גוש\s*[:.]?\s*\n?\s*(\d{3,5})", re.MULTILINE)),
    ("helka",         re.compile(r"חלקה\s*[:.]?\s*(\d{1,5})", re.MULTILINE)),
    ("neighborhood",  re.compile(r"שכונה\s*[:.]?\s*\n?\s*([^\n]+)")),
    ("file_id",       re.compile(r"תיק\s*בני(?:י)?ן\s*[:.]?\s*\n?\s*([\w\-]+)")),
    ("request_type",  re.compile(r"סיווג\s*[:.]?\s*\n?\s*([^\n]+)")),
    ("request_date",  re.compile(r"תאריך\s*בקשה\s*[:.]?\s*\n?\s*(\d{1,2}/\d{1,2}/\d{4})")),
]

# NEW format (≥2-23-0003) places gush+helka on a single line as
# "<gush>/<helka>  גוש/חלקה  <case_id>" with values BEFORE the label
# (PyMuPDF RTL artifact — the visual order is preserved in extracted text).
# This pattern tries that layout when the old anchor fails. The label
# "גוש/חלקה" is the disambiguator: it never appears in old-format text,
# so this regex is safe to evaluate as a fallback on every case.
GUSH_HELKA_NEW_RE = re.compile(
    r"(\d{3,5})\s*/\s*(\d{1,5})\s+גוש\s*/\s*חלקה\s+\d{2}-\d{4}"
)

# Applicant: takes the line after "מבקש הבקשה". The applicant name is the
# first line; subsequent lines are address.
APPLICANT_RE = re.compile(r"מבקש\s*הבקשה[:\s]+\n?\s*([^\n]+)")

# Decision metadata: "ועדת משנה לתכנון ובניה / מספר 2-22-0009 / מתאריך 25/05/2022"
SESSION_META_RE = re.compile(
    r"ועדת\s+משנה\s+לתכנון\s+ובני(?:י)?ה\s*\n?\s*מספר\s*\n?\s*(\d-\d{2}-\d{4})\s*\n?\s*מתאריך\s*\n?\s*(\d{1,2}/\d{1,2}/\d{4})",
    re.MULTILINE,
)

# Vote outcome
VOTE_PATTERNS = [
    ("unanimous",    re.compile(r"ההחלטה\s*התקבלה\s*פה\s*אחד")),
    ("majority",     re.compile(r"ההחלטה\s*התקבלה\s*ברוב")),
]

# The standard closing line is "הערה: טיוטת חוות דעת מהנדס הועדה...". Some
# rejection variants say "טיוטת על חוות שלילית של מהנדס הועדה" — both share
# the "הערה" + "מהנדס" + "ועדה" + "נשלחה" signal.
DRAFT_OPINION_RE = re.compile(
    r"הערה[:\s]+טיוטת[^\n]*?(?:חוות[^\n]*?(?:דעת|שלילית)|מהנדס)[^\n]*?נשלחה[^\n]*",
    re.MULTILINE,
)


def _grab_field(text: str, pat: re.Pattern) -> str | None:
    m = pat.search(text)
    if not m:
        return None
    val = m.group(1).strip()
    val = re.sub(r"\s+", " ", val)
    return val or None


def _extract_address(case_text: str, case_id: str) -> str | None:
    """Address sits between the protocol header and the gush/חלקה or 'בקשה
    מספר' line. Two banner layouts are supported:

      OLD format (≤2-23-0002):
          ...פרוטוקול<newlines>החלטות...<newlines>
          <ADDRESS line>
          ...
          :בקשה מספר   ← anchor closing the window

      NEW format (≥2-23-0003):
          פרוטוקול ועדת משנה לתכנון ובניה
          <ADDRESS line>
          <gush>/<helka>  גוש/חלקה  <case_id>   ← anchor closing the window

    Try old first; fall back to new if no address is recovered.
    """
    addr = _extract_address_old(case_text)
    if addr:
        return addr
    return _extract_address_new(case_text)


def _extract_address_old(case_text: str) -> str | None:
    header_m = re.search(r"פרוטוקול\s*\n*\s*החלטות", case_text)
    anchor_m = re.search(r"בקשה\s*[\W]*?מ[\W]*?ספר", case_text)
    if not (header_m and anchor_m and header_m.end() < anchor_m.start()):
        return None
    window = case_text[header_m.end():anchor_m.start()]
    return _pick_address_line(window)


def _extract_address_new(case_text: str) -> str | None:
    header_m = re.search(r"פרוטוקול\s+ועדת\s+משנה\s+לתכנון\s+ובני(?:י)?ה",
                         case_text)
    # Anchor on the gush/חלקה digits line that follows the address.
    anchor_m = re.search(r"\d{3,5}\s*/\s*\d{1,5}\s+גוש\s*/\s*חלקה", case_text)
    if not (header_m and anchor_m and header_m.end() < anchor_m.start()):
        return None
    window = case_text[header_m.end():anchor_m.start()]
    return _pick_address_line(window)


def _pick_address_line(window: str) -> str | None:
    """Pick the first plausible address line (Hebrew letters + digit) from a
    window of text, skipping Hebrew/Gregorian date lines and city/department
    boilerplate."""
    DATE_RE = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{4}\s*$")
    HEBREW_DATE_RE = re.compile(r"^[א-ת]['\"]?\s+[א-ת]+\s+תשפ['\"]?[א-ת]\s*$")
    for raw in window.splitlines():
        line = raw.strip()
        if not line or len(line) < 3:
            continue
        if any(kw in line for kw in ("החלטות", "ועדת", "מינהל", "ההנדסה",
                                      "חוק התכנון", "עיריית", "פרוטוקול",
                                      "תל אביב", "ת\"א", "אגף רישוי",
                                      "תלֿאביב", "תל–אביב")):
            continue
        if DATE_RE.match(line) or HEBREW_DATE_RE.match(line):
            continue
        if re.search(r"[א-ת]", line) and re.search(r"\d", line):
            line = re.sub(r"([א-ת])(\d)", r"\1 \2", line)
            m = re.match(r"^([^\d]+\d+)", line)
            if m:
                return m.group(1).strip()
            return line
    return None


def _extract_decision_text(case_text: str) -> str:
    """The decision body sits between 'ההחלטה' (alone on a line) and the
    closing 'הערה: טיוטת...' or 'ההחלטה התקבלה...' marker.

    Robust to variants seen in 2-22-0009:
      - "ההחלטה" alone, then "החלטה מספר N"
      - "ההחלטה : החלטה מספר N" on one line
      - "החלטה מספר N" without the bare "ההחלטה" header
    """
    candidates = [
        re.compile(r"\n\s*ההחלטה\s*\n"),
        re.compile(r"\n\s*ההחלטה\s*:\s*החלטה\s+מספר\s*\d+"),
        re.compile(r"החלטה\s+מספר\s*\d+"),
    ]
    start = None
    for pat in candidates:
        m = pat.search(case_text)
        if m:
            start = m.end()
            break
    if start is None:
        return ""

    body = case_text[start:]
    end_idx = len(body)
    for pat in (DRAFT_OPINION_RE,
                re.compile(r"ההחלטה\s+התקבלה")):
        em = pat.search(body)
        if em:
            end_idx = min(end_idx, em.start())
    return body[:end_idx].strip()


def _classify_decision_basis(verdict: str, findings: list[Finding]) -> str:
    if verdict == "rejected":
        return "multiple_violations" if len(findings) > 1 else "single_violation"
    if verdict == "approved_with_conditions":
        return "policy_compliance"
    if verdict == "deferred":
        return "incomplete_submission"
    if verdict == "approved":
        return "policy_compliance"
    if verdict == "partial_approve":
        return "partial_acceptance"
    return "unknown"


def parse_case(block: CaseBlock) -> tuple[dict, float, list[str]]:
    """Return (case_dict, confidence, warnings)."""
    text = block.text
    warnings: list[str] = []

    # Metadata fields — try old-format label-then-value patterns first.
    fields = {}
    for key, pat in FIELD_PATTERNS:
        v = _grab_field(text, pat)
        if v:
            fields[key] = v

    # Fall back to new-format gush+helka layout (value-then-label, single
    # line) when either field is missing. Only triggers for new-format
    # protocols, where the old anchors don't fire.
    if "gush" not in fields or "helka" not in fields:
        m = GUSH_HELKA_NEW_RE.search(text)
        if m:
            fields.setdefault("gush", m.group(1))
            fields.setdefault("helka", m.group(2))

    address = _extract_address(text, block.case_id)
    if not address:
        warnings.append("address not detected")

    applicant_m = APPLICANT_RE.search(text)
    applicant = None
    if applicant_m:
        applicant = applicant_m.group(1).strip()
        applicant = re.sub(r"\s+", " ", applicant)

    # Decision body
    decision = _extract_decision_text(text)
    if not decision:
        warnings.append("decision body not located")

    # Procedural subtype — detect "דיון נוסף" (re-examination of a prior
    # decision). This is informational only; does not affect verdict or
    # findings extraction.
    procedural_subtype = None
    head = (decision[:200] if decision else text[:600])
    if SUBSEQUENT_DISCUSSION_RE.search(head):
        procedural_subtype = "subsequent_discussion"

    verdict, verdict_text, verdict_conf = classify_verdict(decision or text)
    if verdict == "unknown":
        warnings.append("verdict not classified — no known pattern matched")

    findings_list = extract_findings(decision, verdict)
    if not findings_list and verdict in ("rejected", "deferred", "approved",
                                          "approved_with_conditions"):
        warnings.append(f"no findings extracted (verdict={verdict})")

    conditions = parse_conditions(decision) if verdict in (
        "approved", "approved_with_conditions", "partial_approve"
    ) else {}

    # Vote
    vote = None
    for label, pat in VOTE_PATTERNS:
        if pat.search(text):
            vote = label
            break

    # Draft opinion status
    draft_m = DRAFT_OPINION_RE.search(text)
    draft_status = re.sub(r"\s+", " ", draft_m.group(0)).strip() if draft_m else None
    if not draft_status:
        warnings.append("draft-opinion 'הערה' line not found — case may be truncated")

    # Decision basis
    decision_basis = _classify_decision_basis(verdict, findings_list)

    # ── Confidence score ──
    # Start at 1.0; deduct for missing pieces.
    conf = 1.0
    if verdict == "unknown":
        conf -= 0.4
    elif verdict_conf < 0.9:
        conf -= 0.1
    if not address:
        conf -= 0.1
    if not applicant:
        conf -= 0.05
    if not findings_list and verdict in ("rejected",):
        conf -= 0.2
    if not draft_status:
        conf -= 0.1
    if not fields.get("gush"):
        conf -= 0.05
    conf = max(0.0, min(1.0, conf))

    # Build dict
    out = {
        "case_id": block.case_id,
        "address": address,
        "gush": fields.get("gush"),
        "helka": fields.get("helka"),
        "neighborhood": fields.get("neighborhood"),
        "request_type": fields.get("request_type"),
        "applicant": applicant,
    }
    if procedural_subtype:
        out["procedural_subtype"] = procedural_subtype
    out.update({
        "verdict": verdict,
        "verdict_text": verdict_text,
        "decision_basis": decision_basis,
        "findings": [_finding_to_dict(f) for f in findings_list],
        "conditions": conditions,
        "vote": vote,
        "draft_opinion_status": draft_status,
        "extraction_method": "automated",
        "extraction_confidence": round(conf, 2),
        "extraction_warnings": warnings,
    })
    return out, conf, warnings


def _finding_to_dict(f: Finding) -> dict:
    d = {
        "finding_id": f.finding_id,
        "type": f.type,
        "text": f.text,
        "rule_basis": f.rule_basis,
        "reason_class": f.reason_class,
    }
    if f.needs_classification:
        d["needs_classification"] = True
    if f.finding_subtype:
        d["finding_subtype"] = f.finding_subtype
    return d
