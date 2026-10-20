"""v0.2.0: תכנית-עיצוב attachments (נספחים) + mapped reviews.

An attachment mirrors a submission: typed (canonical discipline), versioned,
with a status flow (הוכן → נשלח → התקבלה תשובה → נסגר) and revisions.

The REVIEW runs only the checks mapped to the attachment's type
(attachment_check_mapping.json, editable data in the data dir):
  * the active guidelines tagged with the type's discipline_key
  * mapped extra guideline check_keys from other disciplines
  * the type's named extra checks (learned cross-links)
  * file-quality checks that always run (text layer, format, page count)
Findings cite guideline title+version exactly like the main audit.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .disciplines import DISCIPLINES  # noqa: I001 - puts compliance_engine on sys.path in dev
from compliance_engine.text_utils import patch_rtl_artifacts
from .models import Attachment, DisciplineComment, Guideline
from .storage import sanitize_upload_filename

log = logging.getLogger(__name__)

_DISC_LABEL = {d["key"]: d["label"] for d in DISCIPLINES}
_STATUS_FLOW = ["prepared", "sent", "response_received", "closed"]
STATUS_HE = {
    "prepared": "הוכן",
    "sent": "נשלח",
    "response_received": "התקבלה תשובה",
    "closed": "נסגר",
}
_MAX_FILE_BYTES = 200 * 1024 * 1024


class AttachmentOut(BaseModel):
    id: int
    project_id: int
    discipline_key: str
    version_string: str
    # v0.2.3: assigned by the server, shown as "גרסה N". None only for a row
    # from before v0.2.3 whose free-text label carries no number.
    version_number: Optional[int] = None
    file_path: str
    status: str
    source_attachment_id: Optional[int]
    has_review: bool
    uploaded_at: Optional[str]


class StatusIn(BaseModel):
    status: str


def version_number_of(version_string: str | None) -> int | None:
    """The number in a version label: "3" -> 3, legacy "v2" -> 2."""
    m = re.fullmatch(r"\s*v?(\d+)\s*", version_string or "")
    return int(m.group(1)) if m else None


def _att_out(att: Attachment) -> "AttachmentOut":
    d = att.to_dict()
    d["version_number"] = version_number_of(att.version_string)
    return AttachmentOut(**d)


def _next_revision_number(sess, src: Attachment) -> int:
    """One more than the highest version in src's revision chain.

    The chain is every attachment reachable through source_attachment_id
    from the same root - so two revisions of one source get 2 and 3, never
    two 2s.
    """
    root = src
    while root.source_attachment_id is not None:
        parent = sess.get(Attachment, root.source_attachment_id)
        if parent is None:
            break
        root = parent
    chain, frontier = {root.id: root}, [root.id]
    while frontier:
        kids = sess.execute(select(Attachment).where(
            Attachment.source_attachment_id.in_(frontier))).scalars().all()
        frontier = [k.id for k in kids if k.id not in chain]
        chain.update({k.id: k for k in kids})
    nums = [version_number_of(a.version_string) or 1 for a in chain.values()]
    return max(nums) + 1


def _load_mapping(cfg) -> dict:
    """Mapping is DATA: the seed copy lands in the data dir (editable);
    fall back to the bundled seed copy."""
    for p in (cfg.data_dir / "attachment_check_mapping.json",
              Path(__file__).resolve().parent.parent / "seed" / "attachment_check_mapping.json"):
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:
                log.warning("bad mapping file %s: %s", p, exc)
    return {"types": {}}


def _file_quality_checks(file_path: Path) -> list[dict]:
    """Checks that always run, regardless of mapping."""
    out: list[dict] = []
    suffix = file_path.suffix.lower()
    if suffix == ".dwf":
        out.append(_finding("FILE_FORMAT", "פורמט קובץ",
                            "requires_review",
                            'הקובץ בפורמט DWF - מומלץ להגיש DWFX או DXF לבדיקה ממוחשבת.'))
    elif suffix not in (".pdf", ".dxf", ".dwfx"):
        out.append(_finding("FILE_FORMAT", "פורמט קובץ", "fail",
                            "פורמט הקובץ אינו נתמך. יש להגיש PDF, DXF או DWFX."))
    else:
        out.append(_finding("FILE_FORMAT", "פורמט קובץ", "pass", "פורמט הקובץ נתמך."))

    if suffix == ".pdf":
        try:
            import fitz  # noqa: PLC0415
            doc = fitz.open(file_path)
            pages = doc.page_count
            states = [_page_state(patch_rtl_artifacts(p.get_text())) for p in doc]
            doc.close()
            out.append(_finding("FILE_PAGES", "מספר עמודים", "pass",
                                f"הקובץ מכיל {pages} עמודים."))
            if "garbled" in states:
                out.append(_finding("FILE_TEXT_LAYER", "שכבת טקסט", "requires_review",
                                    GARBLED_TEXT_NOTICE_HE))
            elif not _has_usable_text(states):
                out.append(_finding("FILE_TEXT_LAYER", "שכבת טקסט", "requires_review",
                                    "לא אותרה שכבת טקסט קריאה - ייתכן שהקובץ סרוק. "
                                    "מומלץ להגיש PDF טקסטואלי."))
            else:
                out.append(_finding("FILE_TEXT_LAYER", "שכבת טקסט", "pass",
                                    "לקובץ שכבת טקסט קריאה."))
        except Exception:
            out.append(_finding("FILE_TEXT_LAYER", "קריאות הקובץ", "requires_review",
                                "לא ניתן היה לקרוא את הקובץ לבדיקה ממוחשבת."))
    return out


def _finding(code: str, name_he: str, verdict: str, notes_he: str,
             *, guideline: dict | None = None, cross_cite: str | None = None) -> dict:
    f = {
        "rule_code": f"ATTACH_{code}",
        "rule_name_he": name_he,
        "verdict": verdict,
        "notes_he": notes_he,
        "remediation_he": None,
        "ta_shetach_id": None,
        "confidence": "HIGH",
    }
    if guideline is not None:
        f["guideline_id"] = guideline["id"]
        f["guideline_version"] = guideline["version"]
    if cross_cite:
        f["notes_he"] += f' (תחום מצוטט: {_DISC_LABEL.get(cross_cite, cross_cite)})'
    return f


# ── v0.2.2 status semantics ──────────────────────────────────────────────────
# "נדרשת בדיקה" used to be the answer to every unmet guideline, which told
# Ellen nothing: a missing sheet and an un-judgeable design decision looked
# identical. Each guideline now declares a check_mode (see
# scripts/extract_guidelines_docx.py) and the verdict follows from it:
#
#   manual        → "נדרשת בדיקה ידנית"  (manual_review) - always
#   needs_context → "נדרשת בדיקה"        (requires_review) - always
#   auto_detect   → depends on what we find in the attachment:
#       no marker evidence at all       → "לא הוגש"       (not_submitted)
#       marker found, value under bar   → "נדרש תיקון"    (fail)
#       marker found, nothing measurable→ "נדרשת בדיקה"   (requires_review)
#
# That last line is the case-1 fall-through: an auto-detectable item that IS
# present but carries no measurable value degrades to needs_context behaviour
# rather than inventing a pass or a failure. "לא הוגש" is reserved for ZERO
# evidence; "נדרש תיקון" is reserved for a MEASURED value below threshold.

# ── When presence detection is NOT allowed to run ────────────────────────────
# Ellen routinely receives DWFX and CAD-exported PDFs whose annotations are
# vector graphics, not text. Those files extract to little or no text, so
# "I could not find this item" means "I cannot read this file", not "the
# architect omitted it". Reporting "לא הוגש" there would accuse an architect
# of omitting everything he actually submitted - the common case, not an edge
# case. So: no usable text layer → presence detection does not run at all,
# and every finding that would have been "לא הוגש" becomes "נדרשת בדיקה".
#
# THE RULE IS PER PAGE, NOT PER DOCUMENT.
# A document-wide threshold is defeated by the exact file it exists to catch:
# a real submission is ~60 CAD sheets, each carrying a title block (project,
# tava, date, scale, sheet number) and nothing else as text. That is ~34
# characters per page but ~2,000 document-wide, which clears any sane
# per-document threshold and re-enables presence detection on a file whose
# every annotation is vector. Measured on the 60-sheet fixture: 2,031 chars
# total, 34 per page.
#
# MIN_TEXT_CHARS_PER_PAGE = 250. A title block, even a verbose one carrying
# project name, address, tava number, date, scale, sheet number and a
# drawn-by/checked-by pair, lands around 100-150 characters. A sheet with
# genuine annotation - room labels, dimension strings, general notes -
# reaches several hundred (the annotated fixture measures 635). 250 sits in
# the gap, above any plausible title block and well below real annotation.
#
# READABLE_PAGE_RATIO = 0.5: the document counts as readable only when at
# least half its pages clear the per-page bar - i.e. the MEDIAN page carries
# real text. Presence detection searches the whole document, so if most pages
# are unreadable then a missing marker says nothing about the submission.
#
# Both constants err deliberately toward suppression. Raising them suppresses
# more, which costs a "נדרשת בדיקה" that a human resolves; lowering them
# risks telling an architect he omitted work he submitted. The asymmetry is
# not close, so when in doubt we suppress.
MIN_TEXT_CHARS_PER_PAGE = 250
READABLE_PAGE_RATIO = 0.5

PARTIAL_TEXT_NOTICE_HE = (
    "בחלק מעמודי הקובץ ({unreadable} מתוך {total}) לא אותר טקסט קריא, ולכן "
    "בדיקת הימצאות הפריטים אינה מכסה אותם. סעיפים שלא אותרו מסומנים כטעונים "
    "בדיקה ולא כחסרים, מכיוון שייתכן שהם מופיעים באותם עמודים."
)

# v0.2.3 (§2, B-25): a text layer can be present and still unreadable. CAD
# exports draw their labels and tables as vector paths and keep a handful of
# labels as text with broken glyph mapping - reversed ("הסינכ" for "כניסה")
# or with letters substituted ("דייריח" for "דיירים"). Such a page clears the
# 250-character bar, so detection ran and every miss became "לא הוגש".
GARBLED_TEXT_TITLE_HE = "לא ניתן לקרוא את הטקסט בקובץ"
GARBLED_TEXT_NOTICE_HE = (
    "לא ניתן לקרוא את הטקסט בקובץ. בקובץ יש טקסט, אבל הוא משובש - האותיות "
    "הפוכות או מוחלפות, כפי שקורה בייצוא מתוכנת שרטוט. לכן בדיקת הימצאות "
    "הפריטים לא בוצעה, והסעיפים מסומנים כטעונים בדיקה ולא כחסרים."
)

NO_TEXT_NOTICE_HE = (
    "לא ניתן היה לקרוא טקסט מהקובץ, ולכן בדיקת הימצאות הפריטים לא בוצעה. "
    "הסעיפים מסומנים כטעונים בדיקה, ואין לראות בהם קביעה שפריט חסר. "
    "ייתכן שהקובץ יוצא מתוכנת שרטוט ללא שכבת טקסט - מומלץ להגיש PDF טקסטואלי."
)


# ── Is a page's text layer READABLE, not merely present? ────────────────────
# Two signals, measured 2026-10-20 on every real PDF at hand (pages with at
# least 10 Hebrew words):
#
#                                     well-formed     known words
#   readable: draft 4.1, Ellen's        99-100%         31-76%
#   report, meeting summary, the 63-    (82% before
#   page submission, נספח השתלבות       abbreviations
#                                       were skipped)
#   garbled: 8 CAD sheets (TRP TS01-     14-75%          0-18%
#   05, the three אאורה traffic sheets,
#   the development plan)
#
# WELL-FORMED: a final letter (ךםןףץ) only at the end of a word, and no word
# ending in its non-final twin (כמנפצ). Real Hebrew obeys this; reversed text
# breaks it at once. Abbreviations (שצ"פ, ת"י) are skipped - the gershayim
# splits them into fragments like "השצ".
# KNOWN: the word, or the word minus one or two prefix letters, occurs in the
# guideline corpus. Catches substitution that stays well-formed ("דייריח",
# or every glyph mapped to one letter).
# A page is GARBLED when it has >= 10 Hebrew words and fails either bar.
# Fewer than 10 Hebrew words is too little evidence either way, so the
# character bar alone decides, as before.
MIN_HEBREW_WORDS_TO_JUDGE = 10
MIN_WELLFORMED_RATIO = 0.90
MIN_KNOWN_WORD_RATIO = 0.25

_FINALS = set("ךםןףץ")
_NONFINAL_TWINS = set("כמנפצ")
_PREFIXES = set("הובלמשכ")
_vocab_cache: set[str] | None = None


def _vocabulary() -> set[str]:
    """Hebrew words of the bundled guideline corpus - the seed, not the live
    table, so the verdict does not drift with Ellen's edits."""
    global _vocab_cache
    if _vocab_cache is None:
        seed = Path(__file__).resolve().parent.parent / "seed" / "guidelines_seed.json"
        words: set[str] = set()
        try:
            for g in json.loads(seed.read_text(encoding="utf-8"))["guidelines"]:
                words.update(re.findall(r"[א-ת]{3,}", f"{g.get('title') or ''} "
                                                       f"{g.get('body_text') or ''}"))
        except Exception as exc:          # no corpus: the known-word bar is off
            log.warning("guideline corpus unavailable for readability: %s", exc)
        _vocab_cache = words
    return _vocab_cache


def _hebrew_words(text: str) -> list[str]:
    """Hebrew words of 3+ letters, abbreviations (with gershayim) skipped."""
    out = []
    for tok in re.findall(r"[א-ת\"'\u05f3\u05f4]+", text):
        if any(q in tok for q in "\"'\u05f3\u05f4"):
            continue
        if len(tok) >= 3:
            out.append(tok)
    return out


def _known(word: str, vocab: set[str]) -> bool:
    if word in vocab:
        return True
    for i in (1, 2):
        if (len(word) - i >= 3 and all(c in _PREFIXES for c in word[:i])
                and word[i:] in vocab):
            return True
    return False


def _wellformed(word: str) -> bool:
    return (not any(c in _FINALS for c in word[:-1])
            and word[-1] not in _NONFINAL_TWINS)


def _page_state(text: str) -> str:
    """"readable" | "sparse" (below the character bar) | "garbled"."""
    if len(text.strip()) < MIN_TEXT_CHARS_PER_PAGE:
        return "sparse"
    words = _hebrew_words(text)
    if len(words) < MIN_HEBREW_WORDS_TO_JUDGE:
        return "readable"
    wellformed = sum(map(_wellformed, words)) / len(words)
    vocab = _vocabulary()
    known = (sum(_known(w, vocab) for w in words) / len(words)) if vocab else 1.0
    if wellformed < MIN_WELLFORMED_RATIO or known < MIN_KNOWN_WORD_RATIO:
        return "garbled"
    return "readable"


def _page_texts(file_path: Path) -> list[str]:
    """Text per page, after the shared RTL cleanup. Empty list when the file
    is not a readable PDF at all."""
    if file_path.suffix.lower() != ".pdf":
        return []
    try:
        import fitz  # noqa: PLC0415
        doc = fitz.open(file_path)
        texts = [patch_rtl_artifacts(p.get_text()) for p in doc]
        doc.close()
        return texts
    except Exception:
        return []


def _page_census(states: list[str]) -> tuple[int, int]:
    """(readable pages, unreadable pages). Garbled counts as unreadable."""
    readable = sum(1 for s in states if s == "readable")
    return readable, len(states) - readable


def _has_usable_text(states: list[str]) -> bool:
    """Is the document readable ENOUGH to be worth scanning at all? Used for
    the file-quality warning and to choose which notice to show. Detection
    permission is a stricter test - see _detection_allowed."""
    if not states:
        return False
    readable, _ = _page_census(states)
    return readable / len(states) >= READABLE_PAGE_RATIO


def _detection_allowed(states: list[str]) -> bool:
    """"לא הוגש" requires that we could read EVERY page.

    The ratio rule alone leaves a silent hole: a submission half-exported with
    a text layer and half vector-only passes at 50%, suppression switches off,
    and any item living only on the unreadable half is reported "לא הוגש" -
    with nothing on screen to warn anyone. That is worse than the fully-vector
    file, which at least announces itself with a notice.

    The same reasoning that justifies suppression justifies this: if we cannot
    read a page, a missing marker says nothing about what is drawn on it. We
    genuinely do not know which items live on the unreadable sheets, so we
    cannot claim absence for ANY of them.

    The cost of this choice is that one unreadable sheet in a 60-sheet
    submission downgrades every "לא הוגש" to "נדרשת בדיקה" - detection becomes
    all-or-nothing. We accept that: the downgrade costs a check a human
    resolves, while the alternative tells an architect he omitted work he
    submitted, in a form that looks entirely credible. Only the second kind of
    error damages trust in the tool.
    """
    if not states:
        return False
    _, unreadable = _page_census(states)
    return unreadable == 0


# Hebrew stopwords - too common to be evidence that an item is present.
_STOPWORDS = {
    "יש", "לא", "של", "על", "את", "כל", "או", "עם", "לפי", "בכל", "אל",
    "מן", "אם", "גם", "רק", "בין", "תוך", "יהיה", "תהיה", "יוגש", "תוגש",
    "יסומן", "יסומנו", "תסומן", "יצורף", "יוצג", "יוצגו", "נדרש", "נדרשת",
    "החוברת", "התכנית", "בתכנית", "הקובץ", "לכל", "לפחות", "מ", "ב", "ה",
}


def _content_words(title: str) -> list[str]:
    """Words from the title that could plausibly appear as a label in the
    submission. Short words and stopwords carry no evidential weight."""
    words = re.findall(r"[א-ת]{3,}", title)
    return [w for w in words if w not in _STOPWORDS]


def _extract_text(file_path: Path) -> str:
    """All text in the attachment, lowercased-equivalent for Hebrew (no case).
    Empty string when the file has no text layer - which is exactly the
    blank-PDF case that must yield "לא הוגש", not "נדרשת בדיקה"."""
    if file_path.suffix.lower() != ".pdf":
        return ""
    try:
        import fitz  # noqa: PLC0415
        doc = fitz.open(file_path)
        text = " ".join(patch_rtl_artifacts(p.get_text()) for p in doc)
        doc.close()
        return text
    except Exception:
        return ""


def _marker_found(title: str, doc_text: str) -> bool:
    """Is there ANY evidence this item appears in the submission? Deliberately
    generous: one content word from the title is enough. A false "present"
    downgrades to "נדרשת בדיקה" (honest), whereas a false "absent" would
    accuse the architect of omitting something they submitted."""
    if not doc_text:
        return False
    return any(w in doc_text for w in _content_words(title))


def _guideline_finding(g, doc_text: str, text_ok: bool) -> dict:
    """Verdict for one guideline against one attachment, per its check_mode.

    text_ok=False means the file has no usable text layer, so presence
    detection did not run and NO finding may claim "לא הוגש"."""
    gd = g.to_dict()
    cite = f'הנחיה: "{g.title}" (גרסה {g.version})'
    mode = getattr(g, "check_mode", None) or "needs_context"
    code = f"GUIDE_{g.id}"

    if mode == "manual":
        return _finding(code, g.title, "manual_review",
                        f"סעיף זה נבדק בבדיקה ידנית של המינהלת. {cite}",
                        guideline=gd)

    if mode == "auto_detect":
        if not text_ok:
            # Suppressed: we cannot read the file, so absence proves nothing.
            return _finding(
                code, g.title, "requires_review",
                f"לא בוצעה בדיקת הימצאות אוטומטית - לא ניתן לקרוא את הטקסט בקובץ. {cite}",
                guideline=gd)
        if not _marker_found(g.title, doc_text):
            return _finding(code, g.title, "not_submitted",
                            f"לא נמצא סימון או אזכור של הפריט בנספח. {cite}",
                            guideline=gd)
        # Present. Measurable?
        if g.guideline_type == "checkable" and g.check_value is not None:
            thr = f"{g.check_value:g} {g.unit or ''}".strip()
            return _finding(
                code, g.title, "requires_review",
                f"הפריט נמצא בנספח, אך לא אותר ערך מדיד להשוואה. "
                f"הסף הנדרש הוא {thr}. {cite}",
                guideline=gd)
        return _finding(code, g.title, "requires_review",
                        f"הפריט נמצא בנספח ונדרשת בדיקה של התאמתו לנדרש. {cite}",
                        guideline=gd)

    # needs_context
    if g.guideline_type == "checkable" and g.check_value is not None:
        thr = f"{g.check_value:g} {g.unit or ''}".strip()
        return _finding(code, g.title, "requires_review",
                        f"נדרשת בדיקה מול הנספח. הסף הנדרש הוא {thr}. {cite}",
                        guideline=gd)
    return _finding(code, g.title, "requires_review",
                    f"נדרשת בדיקה מול הנספח. {cite}", guideline=gd)


def attachment_scope(full_mapping: dict, discipline_key: str):
    """Predicate: may this guideline row run on an attachment of this type?

    Keyed on section_key (+ sort_order), the structural row identity - never
    on the Hebrew section title, which is display text and has been reworded
    before (the pattern behind B-13 and B-16).
    """
    scope = full_mapping.get("attachment_scope", {})
    mapping = full_mapping.get("types", {}).get(discipline_key, {})
    blocked_sections = (set(scope.get("submission_only_sections", []))
                        | set(mapping.get("exclude_sections", [])))
    blocked_rows = {(e["section_key"], e["sort_order"])
                    for e in mapping.get("exclude_guidelines", [])}

    def in_scope(g) -> bool:
        if g.section_key in blocked_sections:
            return False
        return (g.section_key, g.sort_order) not in blocked_rows
    return in_scope


def select_guidelines(full_mapping: dict, discipline_key: str, active) -> list:
    """The guideline rows a review of this attachment type runs, in order.

    1. guidelines tagged with THIS discipline;
    2. mapped extra check_keys and include_guidelines from other
       disciplines - the ONLY ways a row from another discipline (כללי
       included) reaches this type. Until
       v0.2.2 every כללי row of 'חלק א' rode along on every type: 25 rows a
       traffic sheet answered 'לא הוגש' to (B-23);
    3. minus anything attachment_scope() rules out.
    """
    mapping = full_mapping.get("types", {}).get(discipline_key, {})
    in_scope = attachment_scope(full_mapping, discipline_key)
    own = [g for g in active if g.discipline_key == discipline_key]
    extra_keys = set(mapping.get("extra_guideline_check_keys", []))
    extras = [g for g in active
              if g.check_key in extra_keys and g.discipline_key != discipline_key]
    # A row tagged to another discipline that belongs to this type, named by
    # its structural identity (the function diagram: tagged תנועה, belongs to
    # architecture).
    wanted = {(e["section_key"], e["sort_order"])
              for e in mapping.get("include_guidelines", [])}
    extras += [g for g in active if (g.section_key, g.sort_order) in wanted]
    out, seen = [], set()
    for g in own + extras:
        if g.id not in seen and in_scope(g):
            seen.add(g.id)
            out.append(g)
    return out


def run_attachment_review(cfg, engine: Engine, att: Attachment) -> dict:
    """Execute ONLY the mapped checks for this attachment's type."""
    full_mapping = _load_mapping(cfg)
    mapping = full_mapping.get("types", {}).get(att.discipline_key, {})
    checks: list[dict] = []

    with Session(engine) as sess:
        active = sess.execute(
            select(Guideline).where(Guideline.is_active == 1)
        ).scalars().all()
    candidates = select_guidelines(full_mapping, att.discipline_key, active)

    # v0.2.2 status semantics: read the attachment ONCE, then let each
    # guideline's declared check_mode decide what we are allowed to say.
    doc_text = _extract_text(Path(att.file_path))
    states = [_page_state(t) for t in _page_texts(Path(att.file_path))]
    readable_pages, unreadable_pages = _page_census(states)
    text_ok = _detection_allowed(states)
    mostly_readable = _has_usable_text(states)

    # The notice leads the list so it is the first thing Ellen reads, on the
    # screen and at the top of the דו"ח התייחסות.
    notice_he = None
    if not text_ok:
        if "garbled" in states:
            # Text is there but scrambled - say so; "no text" would be untrue.
            notice_he = GARBLED_TEXT_NOTICE_HE
            notice_title = GARBLED_TEXT_TITLE_HE
        elif mostly_readable and readable_pages:
            # Mixed document: readable overall, but some sheets are vector.
            notice_he = PARTIAL_TEXT_NOTICE_HE.format(
                unreadable=unreadable_pages, total=len(states))
            notice_title = "בדיקת הימצאות חלקית"
        else:
            notice_he = NO_TEXT_NOTICE_HE
            notice_title = "בדיקת הימצאות לא בוצעה"
        checks.append(_finding("NO_TEXT_LAYER_NOTICE", notice_title,
                               "requires_review", notice_he))

    for g in candidates:
        checks.append(_guideline_finding(g, doc_text, text_ok))

    # 3. The type's named extra checks (learned cross-links).
    for c in mapping.get("extra_checks", []):
        checks.append(_finding(c["id"].upper().replace("-", "_"), c["title_he"],
                               "requires_review", c["instruction_he"],
                               cross_cite=c.get("cross_cite")))

    # 4. File-quality checks - always run.
    checks.extend(_file_quality_checks(Path(att.file_path)))

    return {
        "attachment_id": att.id,
        "discipline_key": att.discipline_key,
        "text_layer_ok": text_ok,
        "readable_pages": readable_pages,
        "unreadable_pages": unreadable_pages,
        "notice_he": notice_he,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }


def _version_he(att: Attachment) -> str:
    n = version_number_of(att.version_string)
    return f"גרסה {n}" if n is not None else f"גרסה {att.version_string}"


def _att_dir(cfg, project_id: int, att_id: int) -> Path:
    p = cfg.data_dir / "attachments" / str(project_id) / str(att_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def make_router(cfg, engine: Engine) -> APIRouter:
    router = APIRouter(tags=["attachments"])

    def _session() -> Session:
        return Session(engine)

    @router.get("/projects/{project_id}/attachments",
                response_model=list[AttachmentOut])
    def list_attachments_of_project(project_id: int):
        with _session() as sess:
            rows = sess.execute(
                select(Attachment).where(Attachment.project_id == project_id)
                .order_by(Attachment.id)
            ).scalars().all()
            return [_att_out(r) for r in rows]

    @router.post("/projects/{project_id}/attachments",
                 response_model=AttachmentOut, status_code=201)
    async def upload_attachment(project_id: int,
                                discipline_key: str = Form(...),
                                file: UploadFile = File(...)):
        if discipline_key not in _DISC_LABEL:
            raise HTTPException(422, "יש לבחור סוג נספח מהרשימה")
        content = await file.read()
        if len(content) > _MAX_FILE_BYTES:
            raise HTTPException(413, "הקובץ גדול מדי - עד 200MB")
        with _session() as sess:
            att = Attachment(project_id=project_id,
                             discipline_key=discipline_key,
                             version_string="1",   # v0.2.3: a new attachment is גרסה 1
                             file_path="", status="prepared")
            sess.add(att)
            sess.flush()
            leaf = sanitize_upload_filename(file.filename or "attachment.pdf")
            dst = _att_dir(cfg, project_id, att.id) / leaf
            dst.write_bytes(content)
            att.file_path = str(dst)
            sess.commit()
            sess.refresh(att)
            return _att_out(att)

    @router.post("/attachments/{att_id}/run-review")
    def run_review(att_id: int):
        with _session() as sess:
            att = sess.get(Attachment, att_id)
            if att is None:
                raise HTTPException(404, "הנספח לא נמצא")
            review = run_attachment_review(cfg, engine, att)
            dest = _att_dir(cfg, att.project_id, att.id) / "review.json"
            dest.write_text(json.dumps(review, ensure_ascii=False, indent=1),
                            encoding="utf-8")
            att.review_json_path = str(dest)
            sess.commit()
            return review

    @router.get("/attachments/{att_id}/review")
    def get_review(att_id: int):
        with _session() as sess:
            att = sess.get(Attachment, att_id)
            if att is None:
                raise HTTPException(404, "הנספח לא נמצא")
            if not att.review_json_path or not Path(att.review_json_path).exists():
                raise HTTPException(409, "טרם הופעלה בדיקה על נספח זה")
            return json.loads(Path(att.review_json_path).read_text(encoding="utf-8"))

    @router.post("/attachments/{att_id}/revision",
                 response_model=AttachmentOut, status_code=201)
    async def upload_revision(att_id: int,
                              file: UploadFile = File(...)):
        content = await file.read()
        if len(content) > _MAX_FILE_BYTES:
            raise HTTPException(413, "הקובץ גדול מדי - עד 200MB")
        with _session() as sess:
            src = sess.get(Attachment, att_id)
            if src is None:
                raise HTTPException(404, "הנספח לא נמצא")
            att = Attachment(project_id=src.project_id,
                             discipline_key=src.discipline_key,
                             version_string=str(_next_revision_number(sess, src)),
                             file_path="", status="prepared",
                             source_attachment_id=src.id)
            sess.add(att)
            sess.flush()
            leaf = sanitize_upload_filename(file.filename or "attachment.pdf")
            dst = _att_dir(cfg, src.project_id, att.id) / leaf
            dst.write_bytes(content)
            att.file_path = str(dst)
            # Revision auto-runs the mapped review.
            review = run_attachment_review(cfg, engine, att)
            rdest = _att_dir(cfg, src.project_id, att.id) / "review.json"
            rdest.write_text(json.dumps(review, ensure_ascii=False, indent=1),
                             encoding="utf-8")
            att.review_json_path = str(rdest)
            sess.commit()
            sess.refresh(att)
            return _att_out(att)

    @router.post("/attachments/{att_id}/status", response_model=AttachmentOut)
    def set_status(att_id: int, body: StatusIn):
        if body.status not in _STATUS_FLOW:
            raise HTTPException(422, "סטטוס לא מוכר")
        with _session() as sess:
            att = sess.get(Attachment, att_id)
            if att is None:
                raise HTTPException(404, "הנספח לא נמצא")
            att.status = body.status
            sess.commit()
            sess.refresh(att)
            return _att_out(att)

    def _build_attachment_report_pdf(att_id: int) -> bytes:
        from .guidelines import _render_pdf
        with _session() as sess:
            att = sess.get(Attachment, att_id)
            if att is None:
                raise HTTPException(404, "הנספח לא נמצא")
            if not att.review_json_path or not Path(att.review_json_path).exists():
                raise HTTPException(409, "יש להריץ בדיקה לפני הפקת דו\"ח התייחסות")
            review = json.loads(Path(att.review_json_path).read_text(encoding="utf-8"))
            comments = sess.execute(
                select(DisciplineComment)
                .where(DisciplineComment.attachment_id == att.id)
            ).scalars().all()
            html = _build_attachment_report_html(att, review, comments)
        return _render_pdf(html)

    @router.get("/attachments/{att_id}/report-pdf")
    def report_pdf(att_id: int):
        import io
        pdf = _build_attachment_report_pdf(att_id)
        return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf",
                                 headers={"Content-Disposition":
                                          'attachment; filename="attachment_report.pdf"'})

    # ── POST /attachments/{id}/open-report ───────────────────────────────────
    # Same reason as guidelines/open-pdf: the packaged WebView2 shell blocks
    # `<a download>`, so the sidecar writes the file and the OS opens it.
    @router.post("/attachments/{att_id}/open-report", status_code=204)
    def open_attachment_report(att_id: int):
        from .os_open import exports_dir, open_in_default_app
        pdf = _build_attachment_report_pdf(att_id)
        path = exports_dir(cfg) / f"attachment_{att_id}_report.pdf"
        path.write_bytes(pdf)
        open_in_default_app(path)
        return Response(status_code=204)

    return router


_VERDICT_HE = {
    "pass": "תקין",
    "fail": "נדרש תיקון",
    "requires_review": "נדרשת בדיקה",
    "manual_review": "נדרשת בדיקה ידנית",
    "not_submitted": "לא הוגש",
}


def _build_attachment_report_html(att: Attachment, review: dict,
                                  comments: list) -> str:
    """The דו"ח התייחסות, in the same chrome as the main סקירת תוכנית עיצוב.

    v0.2.2: this report used to render in a bespoke black-on-white stylesheet
    with a bare <h1>. Ellen sends it to the same architects who receive the
    main report, so it now uses the shared cover, colours, fonts, section and
    table styling from compliance_engine/report_chrome. Only the title line
    differs.
    """
    from html import escape
    from compliance_engine.report_chrome import (cover_html, document_html,
                                                 isolate_ltr as _iso)

    label = _DISC_LABEL.get(att.discipline_key, att.discipline_key)
    now_str = datetime.now().strftime("%d/%m/%Y")

    cover = cover_html(
        title="דו\"ח התייחסות לנספח",
        subtitles=[label, _version_he(att)],
        pill="דו\"ח התייחסות",
        meta_rows=[("תחום:", label),
                   ("גרסת הנספח:", _version_he(att)),
                   ("תאריך הפקה:", now_str)],
        note=review.get("notice_he") or None,
    )

    parts: list[str] = [
        '<div class="chapter">',
        "<h2>ממצאי הבדיקה</h2>",
        "<table><thead><tr><th>סעיף</th><th>מצב</th><th>פירוט</th></tr></thead><tbody>",
    ]
    counts: dict[str, int] = {}
    for c in review.get("checks", []):
        v = c.get("verdict", "requires_review")
        counts[v] = counts.get(v, 0) + 1
        parts.append(
            f"<tr><td>{_iso(c.get('rule_name_he', ''))}</td>"
            f"<td>{escape(_VERDICT_HE.get(v, v))}</td>"
            f"<td>{_iso(c.get('notes_he', ''))}</td></tr>"
        )
    parts.append("</tbody></table>")

    if comments:
        parts.append("<h2>הערות מקושרות</h2>")
        parts.append("<table><thead><tr><th>נושא</th><th>סטטוס</th>"
                     "<th>פעולה נדרשת</th></tr></thead><tbody>")
        for cm in comments:
            parts.append(
                f"<tr><td>{_iso(cm.topic_he)}</td><td>{escape(cm.status)}</td>"
                f"<td>{_iso(cm.action_he)}</td></tr>"
            )
        parts.append("</tbody></table>")

    total = sum(counts.values())
    summary = " \u00b7 ".join(f"{_VERDICT_HE.get(k, k)}: {n}"
                             for k, n in counts.items())
    parts.append(f"<h2>סיכום</h2><p>נבדקו {total} סעיפים. {summary}.</p>")
    parts.append("</div>")
    return document_html(cover=cover, content="".join(parts))
