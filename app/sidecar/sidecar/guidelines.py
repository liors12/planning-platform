"""Global guidelines editor — city-wide submission rules with versioning + PDF export.

Guidelines are GLOBAL (not project-keyed): one municipal rulebook applies to
every תכנית עיצוב. Routes live at /guidelines, deliberately not under
/projects/.

Pattern: all Pydantic models at MODULE scope (required to avoid the FastAPI
422 bug where locally-scoped models get treated as query params).
"""
from __future__ import annotations

import io
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .models import Guideline

log = logging.getLogger(__name__)

# ── Pydantic models (MODULE scope — must stay here) ──────────────────────────

class GuidelineOut(BaseModel):
    id: int
    discipline: str
    title: str
    body_text: Optional[str]
    guideline_type: str
    check_key: Optional[str]
    check_value: Optional[float]
    unit: Optional[str]
    version: int
    is_active: bool
    edited_by: Optional[str]
    edited_at: Optional[str]
    section_key: Optional[str] = None
    section_title: Optional[str] = None
    sort_order: Optional[int] = None


class GuidelineEditIn(BaseModel):
    title: Optional[str] = None
    body_text: Optional[str] = None
    check_value: Optional[float] = None
    edited_by: str = "user"


# ── DB helpers (reused by queue_worker for audit-time reads) ─────────────────

def load_active_guidelines(engine: Engine) -> list[dict]:
    """The active global guideline set, as plain dicts (engine handoff shape)."""
    with Session(engine) as sess:
        rows = sess.execute(
            select(Guideline)
            .where(Guideline.is_active == 1)
            .order_by(Guideline.sort_order.is_(None), Guideline.sort_order, Guideline.id)
        ).scalars().all()
        return [r.to_dict() for r in rows]


# ── Router factory ────────────────────────────────────────────────────────────

def make_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix="/guidelines", tags=["guidelines"])

    def _session() -> Session:
        return Session(engine)

    # ── GET /guidelines — active set ──────────────────────────────────────────
    @router.get("", response_model=list[GuidelineOut])
    def list_guidelines():
        return [GuidelineOut(**g) for g in load_active_guidelines(engine)]

    # ── GET /guidelines/export-pdf ────────────────────────────────────────────
    # Declared before /{gid} routes so the literal path wins.
    @router.get("/export-pdf")
    def export_guidelines_pdf():
        rows = load_active_guidelines(engine)
        html = _build_guidelines_html(rows)
        pdf_bytes = _render_pdf(html)
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="guidelines.pdf"'},
        )

    # ── POST /guidelines/{gid}/edit — insert version+1, flip is_active ────────
    @router.post("/{gid}/edit", response_model=GuidelineOut, status_code=201)
    def edit_guideline(gid: int, body: GuidelineEditIn):
        with _session() as sess:
            old = sess.get(Guideline, gid)
            if old is None:
                raise HTTPException(status_code=404, detail="הנחיה לא נמצאה")
            if not old.is_active:
                raise HTTPException(status_code=409, detail="ניתן לערוך רק את הגרסה הפעילה")

            new_row = Guideline(
                discipline=old.discipline,
                title=body.title if body.title is not None else old.title,
                body_text=body.body_text if body.body_text is not None else old.body_text,
                guideline_type=old.guideline_type,
                check_key=old.check_key,
                check_value=body.check_value if body.check_value is not None else old.check_value,
                unit=old.unit,
                version=old.version + 1,
                is_active=1,
                edited_by=body.edited_by,
                edited_at=datetime.now(timezone.utc),
                section_key=old.section_key,
                section_title=old.section_title,
                sort_order=old.sort_order,
            )
            old.is_active = 0
            sess.add(new_row)
            sess.commit()
            sess.refresh(new_row)
            return GuidelineOut(**new_row.to_dict())

    # ── GET /guidelines/{gid}/history — all versions of this guideline ────────
    @router.get("/{gid}/history", response_model=list[GuidelineOut])
    def guideline_history(gid: int):
        with _session() as sess:
            anchor = sess.get(Guideline, gid)
            if anchor is None:
                raise HTTPException(status_code=404, detail="הנחיה לא נמצאה")
            # Versions of one guideline share (discipline, title-lineage). The
            # title itself is editable, so lineage is traced via check_key when
            # present, else via (discipline, title).
            if anchor.check_key:
                cond = (Guideline.check_key == anchor.check_key,)
            else:
                cond = (Guideline.discipline == anchor.discipline,
                        Guideline.title == anchor.title)
            rows = sess.execute(
                select(Guideline).where(*cond).order_by(Guideline.version.desc())
            ).scalars().all()
            return [GuidelineOut(**r.to_dict()) for r in rows]

    return router


# ── PDF helpers ───────────────────────────────────────────────────────────────

def _resolve_font_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "assets" / "fonts"
    return Path(__file__).resolve().parent.parent.parent.parent / "assets" / "fonts"


# Style spec: Ellen's approved municipal look — black-on-white only. Black bold
# headings (16/14/12pt), full 0.5pt black table grid, bold white header row, no
# shading/banding, no colored accents, hyphens (never em-dash) in template text.
_PDF_CSS = """
@font-face {
    font-family: "Heebo";
    src: url("Heebo-Regular.ttf");
    font-weight: normal;
}
@font-face {
    font-family: "Heebo";
    src: url("Heebo-Bold.ttf");
    font-weight: bold;
}
@page {
    size: A4;
    margin: 2cm 2cm 2.5cm 2cm;
    @bottom-right { content: element(pdf-footer); }
}
html { direction: rtl; }
body {
    font-family: "Heebo", "Arial Hebrew", sans-serif;
    direction: rtl;
    text-align: right;
    font-size: 11pt;
    color: #000000;
}
h1 { font-size: 16pt; font-weight: bold; color: #000000; margin-bottom: 4pt; }
h2 { font-size: 14pt; font-weight: bold; color: #000000;
     margin-top: 16pt; margin-bottom: 6pt; }
.meta { color: #000000; font-size: 9pt; margin-bottom: 14pt; }
.pdf-footer { position: running(pdf-footer); font-size: 8pt; color: #000000;
              direction: rtl; }
table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 12pt;
}
th, td {
    border: 0.5pt solid #000000;
    padding: 4pt 6pt;
    text-align: right;
    vertical-align: top;
    font-size: 10pt;
    color: #000000;
    background: #ffffff;
}
th { font-weight: bold; }
td { font-weight: normal; }
.body-text { white-space: pre-wrap; }
"""


def _dash(s: str) -> str:
    """Ellen's dash convention: regular hyphen, never em/en-dash. Applied at
    render time so DB content is displayed per the approved style without
    being mutated in storage."""
    return s.replace("—", "-").replace("–", "-")


def _build_guidelines_html(rows: list[dict]) -> str:
    from html import escape

    now_str = datetime.now().strftime("%d/%m/%Y")
    max_version = max((g["version"] for g in rows), default=1)
    parts = [
        "<html><head><meta charset='utf-8'></head><body>",
        f"<div class='pdf-footer'>הנחיות עירוניות לתוכנית העיצוב · גרסה {max_version} · {now_str}</div>",
        "<h1>הנחיות עירוניות לתוכנית העיצוב</h1>",
        f"<p class='meta'>הופק: {now_str}</p>",
    ]

    by_discipline: dict[str, list[dict]] = {}
    for r in rows:
        group = r.get("section_title") or r["discipline"]
        by_discipline.setdefault(group, []).append(r)

    header = (
        "<thead><tr>"
        "<th>הנחיה</th><th>תיאור</th><th>סוג בדיקה</th><th>ערך נדרש</th><th>גרסה</th>"
        "</tr></thead>"
    )
    for disc, items in by_discipline.items():
        parts.append(f"<h2>{escape(disc)}</h2>")
        parts.append(f"<table>{header}<tbody>")
        for g in items:
            checkable = g["guideline_type"] == "checkable"
            type_label = "נבדקת אוטומטית" if checkable else "ידנית"
            if checkable and g["check_value"] is not None:
                value_cell = f"{g['check_value']:g} {escape(g['unit'] or '')}"
            else:
                value_cell = "-"
            body = escape(_dash(g["body_text"] or "-"))
            parts.append(
                "<tr>"
                f"<td>{escape(_dash(g['title']))}</td>"
                f"<td class='body-text'>{body}</td>"
                f"<td>{type_label}</td>"
                f"<td>{value_cell}</td>"
                f"<td>{g['version']}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")

    parts.append("</body></html>")
    return "\n".join(parts)


def _render_pdf(html: str) -> bytes:
    font_dir = _resolve_font_dir()
    base_url = str(font_dir) + os.sep

    if sys.platform == "win32" and getattr(sys, "frozen", False):
        # Frozen Windows bundle deliberately does NOT include the weasyprint
        # Python package — it ships Kozea's weasyprint.exe alongside the
        # sidecar instead (same split as compliance_engine/report_generator).
        import subprocess
        import tempfile

        exe = _resolve_weasyprint_exe()
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "guidelines.html"
            css_path = Path(tmp) / "style.css"
            out_path = Path(tmp) / "out.pdf"
            html_path.write_text(html, encoding="utf-8")
            css_path.write_text(_PDF_CSS, encoding="utf-8")
            subprocess.run(
                [str(exe), "--stylesheet", str(css_path),
                 "--base-url", base_url, str(html_path), str(out_path)],
                check=True, capture_output=True,
            )
            return out_path.read_bytes()

    from weasyprint import CSS as WeasyCSS, HTML as WeasyHTML
    from weasyprint.text.fonts import FontConfiguration

    font_config = FontConfiguration()
    css_obj = WeasyCSS(string=_PDF_CSS, base_url=base_url, font_config=font_config)
    buf = io.BytesIO()
    WeasyHTML(string=html, base_url=base_url).write_pdf(
        buf, stylesheets=[css_obj], font_config=font_config,
    )
    return buf.getvalue()


def _resolve_weasyprint_exe() -> Path:
    """Same lookup order as compliance_engine.report_generator."""
    from compliance_engine.report_generator import _resolve_weasyprint_exe as _r
    return _r()
