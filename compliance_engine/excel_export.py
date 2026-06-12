"""Excel export of audit findings for architect response workflow.

Reads the same ``audit_results`` dict that :func:`generate_audit_pdf` consumes
(from ``audit_results.m4.sanitized.json`` in the canonical render path) and
emits a single-sheet RTL Excel workbook where each row is one finding. The
architect fills two columns ("סטטוס טיפול" + "הערות האדריכל") and returns the
file; the rest of the columns are read-only context.

Visual identity matches the v24.3 PDF (Ness Ziona green ``#005030``, gray-light
borders ``#D6D6D6``, gray-bg alt rows ``#F5F5F5``) — these are sourced from
``compliance_engine/report_generator.py``'s ``_CSS`` CSS-variable block. Only
the architect-input columns and the read-only warning banner deviate to draw
the eye (peach + light yellow, respectively).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import (
    Alignment,
    Border,
    Font,
    PatternFill,
    Side,
)
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation


# ─────────────────────────────────────────────────────────────────────────────
# Brand palette — sourced from compliance_engine/report_generator.py:_CSS
# ─────────────────────────────────────────────────────────────────────────────
COLOR_HEADER_BG = "FF005030"        # --green-dark (PDF table headers + cover)
COLOR_HEADER_TEXT = "FFFFFFFF"
COLOR_BORDER = "FFD6D6D6"           # --gray-light
COLOR_ALT_ROW = "FFF5F5F5"          # --gray-bg
COLOR_ARCHITECT_BG = "FFFCE4D6"     # peach — architect input columns
COLOR_WARNING_BG = "FFFFF2CC"       # light yellow — read-only banner
COLOR_WARNING_TEXT = "FFC62828"     # --red

FONT_FAMILY = "Arial"


# ─────────────────────────────────────────────────────────────────────────────
# Domain mappings
# ─────────────────────────────────────────────────────────────────────────────
DISCIPLINE_HE = {
    "arch": "אדריכלות",
    "env": "סביבה ונוף",
    "fire": "כיבוי אש",
    "infra": "תשתיות",
    "drainage": "ניקוז",
    "shafa": 'שפ"א',
    "balcony": "מרפסות",
    "laundry": "מתקני כביסה",
    "roofs": "גגות",
    "gardens": "גינות",
}

STATUS_HE = {
    "fail": "נכשל",
    "pass": "עובר",
    "requires_review": "דורש בדיקה",
    "not_applicable": "לא רלוונטי",
    "not_submitted": "לא הוגש",
    "missing": "חסר",
    "non_compliant": "אי-התאמה",
    "table_format_concern": "בעיית מבנה טבלה",
    "m2_provenance_concern": "בעיית מקור",
}

# Sort priority — lower number sorts earlier (worst at top, "not relevant" at
# bottom). Anything we don't recognize falls in the middle so it stays visible.
STATUS_PRIORITY = {
    "נכשל": 0,
    "דורש בדיקה": 1,
    "חסר": 2,
    "לא הוגש": 2,
    "אי-התאמה": 2,
    "בעיית מבנה טבלה": 2,
    "בעיית מקור": 2,
    "עובר": 3,
    "לא רלוונטי": 4,
}

# Architect-input dropdown values for column 9 (סטטוס טיפול)
ARCHITECT_STATUS_OPTIONS = ["טופל", "לא טופל", "בטיפול", "לא רלוונטי"]


# ─────────────────────────────────────────────────────────────────────────────
# Column layout
# ─────────────────────────────────────────────────────────────────────────────
# (header, width). Order matters — column 1 is "#", column 10 is the architect
# free-text column.
COLUMNS: list[tuple[str, int]] = [
    ("#", 6),
    ("דיסציפלינה", 14),
    ("שם הממצא", 30),
    ("סטטוס ממצא", 14),
    ("תיאור הממצא", 55),
    ("דרישת תיקון", 45),
    ("תא שטח", 10),
    ("עמודים בתוכנית העיצוב", 14),
    ("סטטוס טיפול", 14),
    ("הערות האדריכל", 40),
]
ARCHITECT_COL_INDICES = (9, 10)  # 1-based


# ─────────────────────────────────────────────────────────────────────────────
# Row builders — one per source bucket
# ─────────────────────────────────────────────────────────────────────────────
def _format_plot(raw: Any) -> str:
    """Normalize a plot id into 'תא שטח N' form.

    Accepts:
      - ``None`` / empty → ``""``
      - ``"plot_3"`` (content[] convention) → ``"תא שטח 3"``
      - ``"9"`` (sidecar convention)        → ``"תא שטח 9"``
      - any other non-empty string          → ``"תא שטח <as-is>"``
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    if s.startswith("plot_"):
        s = s[len("plot_"):]
    return f"תא שטח {s}"


def _format_pages(pages: Any) -> str:
    if not pages:
        return ""
    return ", ".join(str(p) for p in pages)


def _row_from_discipline(f: dict) -> dict:
    disc_key = f.get("discipline") or ""
    verdict = f.get("verdict") or ""
    return {
        "discipline": DISCIPLINE_HE.get(disc_key, disc_key),
        "name": f.get("rule_name_he") or f.get("rule_code") or "",
        "status": STATUS_HE.get(verdict, verdict),
        "description": f.get("notes_he") or "",
        "remediation": f.get("remediation_he") or "",
        "plot": "",
        "pages": _format_pages(f.get("booklet_pages")),
    }


def _row_from_content(f: dict) -> dict:
    verdict = f.get("verdict") or ""
    return {
        "discipline": "",
        "name": f.get("rule_name_he") or f.get("rule_code") or "",
        "status": STATUS_HE.get(verdict, verdict),
        "description": f.get("notes_he") or "",
        "remediation": f.get("remediation_he") or "",
        "plot": _format_plot(f.get("ta_shetach_id")),
        "pages": "",
    }


def _row_from_sidecar(f: dict) -> dict:
    indicator = f.get("compliance_indicator") or ""
    clause_id = f.get("clause_id") or ""
    return {
        "discipline": "",
        "name": f"סעיף {clause_id}" if clause_id else "",
        "status": STATUS_HE.get(indicator, indicator),
        "description": f.get("reasoning") or "",
        "remediation": "",
        "plot": _format_plot(f.get("ta_shetach_takanon")),
        "pages": _format_pages(f.get("source_pages")),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────
def export_findings_to_excel(
    audit_results: dict,
    output_path: Path,
    report_version: str = "",
) -> Path:
    """Build the architect-response workbook.

    Layout
    ------
    Row 1: read-only warning banner (merged A1:J1, light yellow, bold red)
    Row 2: column headers (dark green Ness Ziona band, white bold text)
    Row 3+: data rows, sorted by status severity
    Row N+1: blank
    Row N+2: bold summary footer

    Auto-filter ref starts at row 2 so the dropdown arrows sit on the styled
    column-header row. The warning band (row 1) is intentionally outside the
    filter range — it can never be hidden by a filter selection.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    disciplines = list(audit_results.get("disciplines") or [])
    content = list(audit_results.get("content") or [])
    sidecar = list(
        (audit_results.get("m4_summary") or {}).get("sidecar_only_findings") or []
    )
    expected_total = len(disciplines) + len(content) + len(sidecar)

    # Build flat row list, then sort by status priority
    rows: list[dict] = (
        [_row_from_discipline(f) for f in disciplines]
        + [_row_from_content(f) for f in content]
        + [_row_from_sidecar(f) for f in sidecar]
    )
    rows.sort(key=lambda r: STATUS_PRIORITY.get(r["status"], 2))

    if len(rows) != expected_total:
        raise RuntimeError(
            f"Excel export row count mismatch: built {len(rows)} rows but "
            f"input had {expected_total} findings "
            f"(disciplines={len(disciplines)}, content={len(content)}, "
            f"sidecar={len(sidecar)}). Refusing to write a partial workbook."
        )

    # ── Workbook + sheet ────────────────────────────────────────────────
    wb = Workbook()
    ws = wb.active
    ws.title = f"הערות סקירה v{report_version}".strip()
    ws.sheet_view.rightToLeft = True

    # Column widths
    for col_idx, (_, width) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    # Reusable styles
    thin = Side(style="thin", color=COLOR_BORDER)
    cell_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_font = Font(name=FONT_FAMILY, size=11, bold=True, color=COLOR_HEADER_TEXT)
    header_fill = PatternFill("solid", fgColor=COLOR_HEADER_BG)
    header_align = Alignment(
        horizontal="center", vertical="center", wrap_text=True, readingOrder=2
    )
    data_font = Font(name=FONT_FAMILY, size=10)
    data_align = Alignment(
        horizontal="right", vertical="center", wrap_text=True, readingOrder=2
    )
    alt_fill = PatternFill("solid", fgColor=COLOR_ALT_ROW)
    architect_fill = PatternFill("solid", fgColor=COLOR_ARCHITECT_BG)
    warning_fill = PatternFill("solid", fgColor=COLOR_WARNING_BG)
    warning_font = Font(
        name=FONT_FAMILY, size=11, bold=True, color=COLOR_WARNING_TEXT
    )
    warning_align = Alignment(
        horizontal="center", vertical="center", wrap_text=True, readingOrder=2
    )

    # Row layout: warning row 1, column headers row 2, data row 3+. This
    # ordering lets the auto-filter dropdowns sit on the styled header row
    # (row 2) while keeping the warning band outside the filter range.
    WARNING_ROW = 1
    HEADER_ROW = 2
    DATA_START_ROW = 3
    n_cols = len(COLUMNS)

    # ── Row 1: read-only warning (merged, NOT part of filter) ──────────
    warning_text = (
        "אין לשנות או למחוק עמודות ונתונים בגיליון זה. "
        "יש למלא אך ורק את העמודות: ״סטטוס טיפול״ ו-״הערות האדריכל״"
    )
    ws.merge_cells(
        start_row=WARNING_ROW, start_column=1,
        end_row=WARNING_ROW, end_column=n_cols,
    )
    ws.row_dimensions[WARNING_ROW].height = 32
    wc = ws.cell(row=WARNING_ROW, column=1, value=warning_text)
    wc.font = warning_font
    wc.fill = warning_fill
    wc.alignment = warning_align
    # Fill + border every cell in the merge so RTL/print views don't reveal
    # un-merged white cells underneath.
    for col_idx in range(1, n_cols + 1):
        ws.cell(row=WARNING_ROW, column=col_idx).border = cell_border
        ws.cell(row=WARNING_ROW, column=col_idx).fill = warning_fill

    # ── Row 2: column headers (filter anchor) ───────────────────────────
    ws.row_dimensions[HEADER_ROW].height = 30
    for col_idx, (header, _) in enumerate(COLUMNS, start=1):
        c = ws.cell(row=HEADER_ROW, column=col_idx, value=header)
        c.font = header_font
        c.fill = header_fill
        c.alignment = header_align
        c.border = cell_border

    # ── Data rows ───────────────────────────────────────────────────────
    for i, row in enumerate(rows, start=1):
        excel_row = DATA_START_ROW + (i - 1)
        ws.row_dimensions[excel_row].height = 45
        is_alt = (i % 2 == 0)
        row_fill = alt_fill if is_alt else None

        values = [
            i,
            row["discipline"],
            row["name"],
            row["status"],
            row["description"],
            row["remediation"],
            row["plot"],
            row["pages"],
            "",  # architect: status
            "",  # architect: free-text comments
        ]
        for col_idx, v in enumerate(values, start=1):
            c = ws.cell(row=excel_row, column=col_idx, value=v)
            c.font = data_font
            c.alignment = data_align
            c.border = cell_border
            if col_idx in ARCHITECT_COL_INDICES:
                c.fill = architect_fill
            elif row_fill is not None:
                c.fill = row_fill

    last_data_row = DATA_START_ROW + len(rows) - 1

    # ── Summary footer (blank row, then bold count) ─────────────────────
    footer_row = last_data_row + 2
    fc = ws.cell(row=footer_row, column=1, value=f'סה"כ ממצאים: {len(rows)}')
    fc.font = Font(name=FONT_FAMILY, size=11, bold=True)
    fc.alignment = Alignment(horizontal="right", vertical="center", readingOrder=2)

    # ── Freeze panes + auto-filter ──────────────────────────────────────
    # Freeze BELOW the warning band so the architect always sees the column
    # headers AND the warning while scrolling.
    ws.freeze_panes = f"A{DATA_START_ROW}"

    # Filter range = column-header row (row 2) through last data row, so
    # the dropdown arrows render on the styled green band. Row 1 (warning)
    # sits outside the range and cannot be hidden by filter selections.
    ws.auto_filter.ref = (
        f"A{HEADER_ROW}:{get_column_letter(n_cols)}{last_data_row}"
    )

    # ── Architect status dropdown (column 9) ────────────────────────────
    # openpyxl wants the list as a comma-joined string in double quotes.
    dv = DataValidation(
        type="list",
        formula1='"' + ",".join(ARCHITECT_STATUS_OPTIONS) + '"',
        allow_blank=True,
        showErrorMessage=True,
        errorTitle="ערך לא חוקי",
        error="יש לבחור מתוך הרשימה",
    )
    dv.add(f"I{DATA_START_ROW}:I{last_data_row}")
    ws.add_data_validation(dv)

    wb.save(output_path)
    return output_path
