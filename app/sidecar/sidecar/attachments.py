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

from .disciplines import DISCIPLINES
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
    file_path: str
    status: str
    source_attachment_id: Optional[int]
    has_review: bool
    uploaded_at: Optional[str]


class StatusIn(BaseModel):
    status: str


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
            page_lens = [len(p.get_text().strip()) for p in doc]
            doc.close()
            out.append(_finding("FILE_PAGES", "מספר עמודים", "pass",
                                f"הקובץ מכיל {pages} עמודים."))
            if not _has_usable_text(page_lens):
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

NO_TEXT_NOTICE_HE = (
    "לא ניתן היה לקרוא טקסט מהקובץ, ולכן בדיקת הימצאות הפריטים לא בוצעה. "
    "הסעיפים מסומנים כטעונים בדיקה, ואין לראות בהם קביעה שפריט חסר. "
    "ייתכן שהקובץ יוצא מתוכנת שרטוט ללא שכבת טקסט - מומלץ להגיש PDF טקסטואלי."
)


def _page_text_lengths(file_path: Path) -> list[int]:
    """Extractable characters per page. Empty list when the file is not a
    readable PDF at all."""
    if file_path.suffix.lower() != ".pdf":
        return []
    try:
        import fitz  # noqa: PLC0415
        doc = fitz.open(file_path)
        lengths = [len(p.get_text().strip()) for p in doc]
        doc.close()
        return lengths
    except Exception:
        return []


def _page_census(page_lengths: list[int]) -> tuple[int, int]:
    """(readable pages, unreadable pages) by the per-page bar."""
    readable = sum(1 for n in page_lengths if n >= MIN_TEXT_CHARS_PER_PAGE)
    return readable, len(page_lengths) - readable


def _has_usable_text(page_lengths: list[int]) -> bool:
    """Is the document readable ENOUGH to be worth scanning at all? Used for
    the file-quality warning and to choose which notice to show. Detection
    permission is a stricter test - see _detection_allowed."""
    if not page_lengths:
        return False
    readable, _ = _page_census(page_lengths)
    return readable / len(page_lengths) >= READABLE_PAGE_RATIO


def _detection_allowed(page_lengths: list[int]) -> bool:
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
    if not page_lengths:
        return False
    _, unreadable = _page_census(page_lengths)
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
        text = " ".join(p.get_text() for p in doc)
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
                f"לא בוצעה בדיקת הימצאות אוטומטית - לא נקרא טקסט מהקובץ. {cite}",
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


def run_attachment_review(cfg, engine: Engine, att: Attachment) -> dict:
    """Execute ONLY the mapped checks for this attachment's type."""
    full_mapping = _load_mapping(cfg)
    mapping = full_mapping.get("types", {}).get(att.discipline_key, {})
    subgroup_cfg = full_mapping.get("general_subgroups", {})
    always_on = set(subgroup_cfg.get("always_on_attachments", []))
    checks: list[dict] = []

    with Session(engine) as sess:
        active = sess.execute(
            select(Guideline).where(Guideline.is_active == 1)
        ).scalars().all()

    # 1. Guidelines tagged with THIS discipline.
    own = [g for g in active if g.discipline_key == att.discipline_key]
    # 2. Mapped extra guideline check_keys from other disciplines.
    extra_keys = set(mapping.get("extra_guideline_check_keys", []))
    extras = [g for g in active
              if g.check_key in extra_keys and g.discipline_key != att.discipline_key]
    # 3. v0.2.1: כללי sub-groups marked always_on_attachments (file formats)
    # apply to every attachment type. The booklet-structure and checklist
    # sub-groups are submission-only and deliberately never reach here.
    general_always = [
        g for g in active
        if g.discipline_key == "general"
        and (g.section_title or "").strip() in always_on
    ]

    # v0.2.2 status semantics: read the attachment ONCE, then let each
    # guideline's declared check_mode decide what we are allowed to say.
    doc_text = _extract_text(Path(att.file_path))
    page_lengths = _page_text_lengths(Path(att.file_path))
    readable_pages, unreadable_pages = _page_census(page_lengths)
    text_ok = _detection_allowed(page_lengths)
    mostly_readable = _has_usable_text(page_lengths)

    # The notice leads the list so it is the first thing Ellen reads, on the
    # screen and at the top of the דו"ח התייחסות.
    notice_he = None
    if not text_ok:
        if mostly_readable and readable_pages:
            # Mixed document: readable overall, but some sheets are vector.
            notice_he = PARTIAL_TEXT_NOTICE_HE.format(
                unreadable=unreadable_pages, total=len(page_lengths))
            notice_title = "בדיקת הימצאות חלקית"
        else:
            notice_he = NO_TEXT_NOTICE_HE
            notice_title = "בדיקת הימצאות לא בוצעה"
        checks.append(_finding("NO_TEXT_LAYER_NOTICE", notice_title,
                               "requires_review", notice_he))

    seen_ids = set()
    for g in own + extras + general_always:
        if g.id in seen_ids:
            continue
        seen_ids.add(g.id)
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
            return [AttachmentOut(**r.to_dict()) for r in rows]

    @router.post("/projects/{project_id}/attachments",
                 response_model=AttachmentOut, status_code=201)
    async def upload_attachment(project_id: int,
                                discipline_key: str = Form(...),
                                version_string: str = Form(...),
                                file: UploadFile = File(...)):
        if discipline_key not in _DISC_LABEL:
            raise HTTPException(422, "יש לבחור סוג נספח מהרשימה")
        content = await file.read()
        if len(content) > _MAX_FILE_BYTES:
            raise HTTPException(413, "הקובץ גדול מדי - עד 200MB")
        with _session() as sess:
            att = Attachment(project_id=project_id,
                             discipline_key=discipline_key,
                             version_string=version_string.strip() or "v1",
                             file_path="", status="prepared")
            sess.add(att)
            sess.flush()
            leaf = sanitize_upload_filename(file.filename or "attachment.pdf")
            dst = _att_dir(cfg, project_id, att.id) / leaf
            dst.write_bytes(content)
            att.file_path = str(dst)
            sess.commit()
            sess.refresh(att)
            return AttachmentOut(**att.to_dict())

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
                              version_string: str = Form(...),
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
                             version_string=version_string.strip() or "v2",
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
            return AttachmentOut(**att.to_dict())

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
            return AttachmentOut(**att.to_dict())

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
    from compliance_engine.report_chrome import cover_html, document_html

    label = _DISC_LABEL.get(att.discipline_key, att.discipline_key)
    now_str = datetime.now().strftime("%d/%m/%Y")

    cover = cover_html(
        title="דו\"ח התייחסות לנספח",
        subtitles=[label, f"גרסה {att.version_string}"],
        pill="דו\"ח התייחסות",
        meta_rows=[("תחום:", label),
                   ("גרסת הנספח:", att.version_string),
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
            f"<tr><td>{escape(c.get('rule_name_he', ''))}</td>"
            f"<td>{escape(_VERDICT_HE.get(v, v))}</td>"
            f"<td>{escape(c.get('notes_he', ''))}</td></tr>"
        )
    parts.append("</tbody></table>")

    if comments:
        parts.append("<h2>הערות מקושרות</h2>")
        parts.append("<table><thead><tr><th>נושא</th><th>סטטוס</th>"
                     "<th>פעולה נדרשת</th></tr></thead><tbody>")
        for cm in comments:
            parts.append(
                f"<tr><td>{escape(cm.topic_he)}</td><td>{escape(cm.status)}</td>"
                f"<td>{escape(cm.action_he)}</td></tr>"
            )
        parts.append("</tbody></table>")

    total = sum(counts.values())
    summary = " \u00b7 ".join(f"{_VERDICT_HE.get(k, k)}: {n}"
                             for k, n in counts.items())
    parts.append(f"<h2>סיכום</h2><p>נבדקו {total} סעיפים. {summary}.</p>")
    parts.append("</div>")
    return document_html(cover=cover, content="".join(parts))
