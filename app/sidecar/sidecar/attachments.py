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
            text_len = sum(len(p.get_text()) for p in doc)
            doc.close()
            out.append(_finding("FILE_PAGES", "מספר עמודים", "pass",
                                f"הקובץ מכיל {pages} עמודים."))
            if text_len < 50:
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

    seen_ids = set()
    for g in own + extras + general_always:
        if g.id in seen_ids:
            continue
        seen_ids.add(g.id)
        gd = g.to_dict()
        cite = f'הנחיה: "{g.title}" (גרסה {g.version})'
        if g.guideline_type == "checkable" and g.check_value is not None:
            thr = f"{g.check_value:g}"
            notes = (f'נדרשת בדיקה מול הנספח: הסף הנדרש הוא {thr} {g.unit or ""}. {cite}')
        else:
            notes = f'נדרשת בדיקה מול הנספח. {cite}'
        checks.append(_finding(f"GUIDE_{g.id}", g.title, "requires_review", notes,
                               guideline=gd))

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
}


def _build_attachment_report_html(att: Attachment, review: dict,
                                  comments: list) -> str:
    from html import escape
    label = _DISC_LABEL.get(att.discipline_key, att.discipline_key)
    now_str = datetime.now().strftime("%d/%m/%Y")
    parts = [
        "<html><head><meta charset='utf-8'></head><body>",
        f"<div class='pdf-footer'>דו\"ח התייחסות לנספח {escape(label)} · "
        f"גרסה {escape(att.version_string)} · {now_str}</div>",
        f"<h1>דו\"ח התייחסות לנספח {escape(label)} - גרסה {escape(att.version_string)}</h1>",
        f"<p class='meta'>הופק: {now_str}</p>",
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
        parts.append("<table><thead><tr><th>נושא</th><th>סטטוס</th><th>פעולה נדרשת</th></tr></thead><tbody>")
        for cm in comments:
            parts.append(
                f"<tr><td>{escape(cm.topic_he)}</td><td>{escape(cm.status)}</td>"
                f"<td>{escape(cm.action_he)}</td></tr>"
            )
        parts.append("</tbody></table>")

    total = sum(counts.values())
    summary = " · ".join(f"{_VERDICT_HE.get(k, k)}: {n}" for k, n in counts.items())
    parts.append(f"<h2>סיכום</h2><p>נבדקו {total} סעיפים. {summary}.</p>")
    parts.append("</body></html>")
    return "".join(parts)
