"""Audit report PDF generator (v8f — WeasyPrint, reference (2) patterns).

CSS lifted verbatim from `v6_design_reference (2).html`. Structural fixes:

  Bug 1 (TOC stacked)               → <table class="toc">
  Bug 2 (badges stacked)            → <table class="badges">
  Bug 3 (priority list misaligned)  → display: table on <li> + <span class="item-content">
  Bug 4 (double footer)             → CSS @page only; no _stamp_footers
  Bug 5 (rows split across pages)   → tr { page-break-inside: avoid } + thead table-header-group
  Bug 6 (letter-spaced Hebrew)      → removed all letter-spacing
  Bug 7 (cramped Hebrew)            → body line-height: 1.7, callout/intro 1.8, table 1.6

Structure: one chapter <div> per section. Subsections flow inside the chapter
with .subsection { page-break-inside: avoid } so each fits on a single page
when possible. WeasyPrint computes pagination + footer + TOC page numbers
(target-counter) automatically.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = PROJECT_ROOT / "assets" / "fonts"

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

EYEBROW = "המינהלת להתחדשות עירונית — עיריית נס ציונה"
DOC_TYPE_LABEL = "טיוטה לסקירה — לא לחתימה"

VERDICT_TO_VCLASS_AND_LABEL: dict[str, tuple[str, str]] = {
    "pass":            ("v-ok",   "תקין"),
    "pass_with_note":  ("v-ok",   "תקין בהערה"),
    "fail":            ("v-fail", "נדרש תיקון"),
    "fail_borderline": ("v-fail", "נדרש תיקון"),
    "not_submitted":   ("v-miss", "לא הוגש"),
    "requires_review": ("v-rev",  "דורש בירור"),
    "unevaluable":     ("v-na",   "לא ניתן לבדיקה"),
    "not_applicable":  ("v-na",   "לא רלוונטי"),
}

DISCIPLINE_NAME_HE: dict[str, str] = {
    "shafa":    'שפ"ע — אשפה ופינוי פסולת',
    "gardens":  "גנים ונוף",
    "infra":    "תשתיות",
    "fire":     "רחבות כיבוי אש",
    "drainage": "ניקוז וחלחול",
    "roofs":    "גגות וגינון על גג",
    "arch":     "אדריכלות וחזיתות",
    "balcony":  "מרפסות",
    "laundry":  "מסתורי כביסה",
    "env":      "הנחיות סביבתיות",
}
DISCIPLINE_ORDER = list(DISCIPLINE_NAME_HE.keys())

HEBREW_MONTHS = {
    1: "ינואר", 2: "פברואר", 3: "מרץ", 4: "אפריל", 5: "מאי", 6: "יוני",
    7: "יולי", 8: "אוגוסט", 9: "ספטמבר", 10: "אוקטובר", 11: "נובמבר", 12: "דצמבר",
}

CONTENT_ROW_ORDER = [
    "CONTENT_UNIT_COUNT",
    "CONTENT_BUILDING_AREA_MAIN",
    "CONTENT_BUILDING_AREA_SERVICE_ABOVE",
    "CONTENT_BUILDING_AREA_SERVICE_BELOW",
    "CONTENT_BUILDING_HEIGHT",
    "CONTENT_SETBACKS",
    "CONTENT_PARKING_RATIO",
    "CONTENT_APARTMENT_MIX_SMALL",
    "CONTENT_PERMEABLE_SURFACES",
]

# ─────────────────────────────────────────────────────────────────────────────
# CSS — verbatim from v6_design_reference (2).html + @font-face for Heebo
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
@font-face {
  font-family: "Heebo";
  src: url("Heebo-Regular.ttf");
  font-weight: 100 900;
  font-style: normal;
}

/* ============================================
   RTL FUNDAMENTALS + Hebrew typography
   ============================================ */
html { direction: rtl; }
body {
  direction: rtl;
  text-align: right;
  font-family: 'Heebo', 'Simple CLM', 'Arial Hebrew', sans-serif;
  margin: 0;
  padding: 0;
  color: #1a1a1a;
  font-size: 11pt;
  line-height: 1.7;
}
* { box-sizing: border-box; }

/* ============================================
   PAGE STRUCTURE — single source of truth for footer
   ============================================ */
@page {
  size: A4;
  margin: 20mm 22mm 22mm 22mm;
  @bottom-right {
    content: "מינהלת התחדשות עירונית נס ציונה — סקירת תוכנית עיצוב";
    font-family: 'Heebo', 'Simple CLM', sans-serif;
    font-size: 8.5pt;
    color: #8A8A8A;
  }
  @bottom-left {
    content: counter(page) " / " counter(pages);
    font-family: 'Heebo', 'Simple CLM', sans-serif;
    font-size: 8.5pt;
    color: #8A8A8A;
  }
}
@page cover {
  margin: 0;
  @bottom-right { content: none; }
  @bottom-left { content: none; }
}
@page appendix-divider {
  @bottom-right { content: none; }
  @bottom-left { content: none; }
}

/* ============================================
   COLOR TOKENS
   ============================================ */
:root {
  --green-dark: #005030;
  --green-brand: #007840;
  --green-accent: #2E7D32;
  --red: #C62828;
  --amber: #F57C00;
  --gray-dark: #424242;
  --gray-mid: #7A7A7A;
  --gray-light: #D6D6D6;
  --gray-bg: #F5F5F5;
  --bg-callout: #FAFAFA;
}

/* ============================================
   CHAPTER PAGE BREAKS
   ============================================ */
.chapter { page-break-before: always; }
.chapter:first-of-type { page-break-before: avoid; }
h2, h3 { page-break-after: avoid; }
p { orphans: 3; widows: 3; }

/* ============================================
   COVER PAGE — full-bleed dark green
   ============================================ */
.cover {
  page: cover;
  background: #005030;
  color: #fff;
  width: 210mm;
  height: 297mm;
  padding: 22mm 22mm 22mm 22mm;
  page-break-after: always;
  position: relative;
}
.cover .logo {
  position: absolute;
  top: 18mm;
  right: 22mm;         /* visual top-right of the cover page */
  height: 21mm;        /* ≈ 80px at 96dpi */
  width: auto;
}
.cover .brand-eyebrow {
  font-size: 10.5pt;
  color: rgba(255,255,255,0.72);
  margin-bottom: 1mm;
}
.cover .brand-name {
  font-size: 19pt;
  font-weight: 700;
  color: #fff;
  margin-bottom: 10mm;
}
.cover hr.rule {
  border: none;
  border-top: 1px solid rgba(255,255,255,0.22);
  margin: 8mm 0;
}
.cover .title {
  font-size: 42pt;
  font-weight: 700;
  color: #fff;
  line-height: 1.15;
  margin: 50mm 0 7mm 0;
}
.cover .subtitle {
  font-size: 15pt;
  color: rgba(255,255,255,0.92);
  line-height: 1.5;
  margin-bottom: 1.5mm;
}
.cover .subtitle:last-of-type { margin-bottom: 14mm; }
.cover .data-block {
  font-size: 11.5pt;
  line-height: 2.0;
  color: rgba(255,255,255,0.92);
  margin-bottom: 12mm;
}
.cover .data-block .label {
  color: rgba(255,255,255,0.62);
  display: inline-block;
  min-width: 36mm;
  font-weight: 700;
}
.cover .pill {
  display: inline-block;
  padding: 2.5mm 8mm;
  border: 1px solid rgba(255,255,255,0.45);
  border-radius: 30px;
  background: rgba(255,255,255,0.06);
  color: #fff;
  font-size: 10.5pt;
  margin-bottom: 12mm;
}
.cover .abstract {
  font-size: 10pt;
  color: rgba(255,255,255,0.78);
  line-height: 1.85;
  max-width: 140mm;
  margin: 0;
}

/* ============================================
   TOC — table-based for deterministic RTL
   ============================================ */
table.toc {
  width: 100%;
  border-collapse: collapse;
  margin-top: 10mm;
  font-size: 11.5pt;
}
table.toc td {
  padding: 3.2mm 0;
  border-bottom: 1px dotted #D6D6D6;
  vertical-align: middle;
}
table.toc td.title {
  text-align: right;
  color: #1a1a1a;
}
table.toc td.title.main {
  font-weight: 700;
  color: var(--green-dark);
  font-size: 12pt;
}
table.toc td.title.sub {
  padding-right: 8mm;
  font-size: 10.5pt;
  color: #424242;
}
table.toc td.page {
  text-align: left;
  color: var(--gray-mid);
  width: 18mm;
}
table.toc a { color: inherit; text-decoration: none; }
table.toc a:hover { text-decoration: underline; }
table.toc td.page a::after { content: target-counter(attr(href), page); }

/* ============================================
   EYEBROW (subtle running header on inner pages)
   ============================================ */
.eyebrow {
  font-size: 9.5pt;
  color: var(--gray-mid);
  margin-bottom: 8mm;
  padding-bottom: 3mm;
  border-bottom: 1px solid var(--gray-light);
}

/* ============================================
   CHAPTER DIVIDER
   ============================================ */
.chapter-num-title {
  font-size: 26pt;
  font-weight: 700;
  color: var(--green-dark);
  margin: 0 0 6mm 0;
  line-height: 1.2;
}
/* .chapter-num-title .num removed in v8h — plain "N. title" text in heading produces the correct
   digit-at-right BIDI order (python-bidi-verified). */
.chapter-intro {
  font-size: 11pt;
  color: var(--gray-dark);
  line-height: 1.8;
  max-width: 160mm;
  margin-bottom: 10mm;
}

/* ============================================
   STATUS SUMMARY BADGES — table-based for reliable RTL row
   ============================================ */
table.badges {
  width: 100%;
  margin: 6mm 0 10mm 0;
  border-collapse: separate;
  border-spacing: 3mm 0;
}
table.badges td {
  background: #fff;
  border: 1px solid var(--gray-light);
  border-radius: 4px;
  padding: 5mm 3mm;
  text-align: center;
  vertical-align: top;
}
table.badges .num {
  font-size: 26pt;
  font-weight: 700;
  line-height: 1;
  margin-bottom: 2mm;
}
table.badges .label {
  font-size: 9pt;
  color: var(--gray-mid);
  line-height: 1.4;
}
table.badges td.ok .num      { color: var(--green-accent); }
table.badges td.fail .num    { color: var(--red); }
table.badges td.review .num  { color: var(--amber); }
table.badges td.unknown .num { color: var(--gray-mid); }
table.badges td.na .num      { color: #B0B0B0; }

/* ============================================
   CALLOUT BOX
   ============================================ */
.callout {
  border: 1px solid var(--gray-light);
  background: var(--bg-callout);
  border-right: 4px solid var(--green-dark);
  padding: 6mm 8mm;
  margin: 8mm 0;
  border-radius: 2px;
}
.callout .callout-title {
  font-size: 13pt;
  font-weight: 700;
  color: var(--green-dark);
  margin-bottom: 3mm;
}
.callout .callout-body {
  font-size: 11pt;
  color: var(--gray-dark);
  line-height: 1.8;
  margin: 0;
}

/* ============================================
   SUBSECTION HEADER
   ============================================ */
.subsection { margin-top: 10mm; page-break-inside: avoid; }
.subsection-num {
  font-size: 15pt;
  font-weight: 700;
  color: var(--green-dark);
  margin: 0 0 2mm 0;
}
.subsection-summary {
  font-size: 12pt;
  font-weight: 500;
  color: var(--green-accent);
  margin-bottom: 1.5mm;
}
.subsection-meta {
  font-size: 10pt;
  color: var(--gray-mid);
  margin-bottom: 4mm;
  line-height: 1.6;
}

/* ============================================
   TABLES — explicit RTL alignment, row break controls
   ============================================ */
table.audit {
  width: 100%;
  border-collapse: collapse;
  direction: rtl;
  margin: 4mm 0 8mm 0;
  font-size: 10pt;
}
table.audit th,
table.audit td {
  border: 1px solid var(--gray-light);
  padding: 3mm 3mm;
  text-align: right;
  vertical-align: top;
  line-height: 1.6;
}
table.audit th {
  background: var(--gray-bg);
  font-weight: 700;
  color: var(--gray-dark);
  border-bottom: 2px solid #909090;
}
table.audit tr { page-break-inside: avoid; break-inside: avoid; }
table.audit thead { display: table-header-group; }

/* Verdict cell styling */
.v-ok    { color: var(--green-accent); font-weight: 600; }
.v-fail  { color: var(--red);          font-weight: 600; }
.v-rev   { color: var(--amber);        font-weight: 600; }
.v-na    { color: var(--gray-mid); }
.v-miss  { color: var(--gray-dark); }

/* ============================================
   VERDICT BANNER (section 4)
   ============================================ */
.verdict-banner {
  background: #FFF3E0;
  border-right: 6px solid var(--red);
  padding: 5mm 8mm;
  margin: 6mm 0 10mm 0;
  border-radius: 2px;
}
.verdict-banner .verdict-text {
  font-size: 13pt;
  font-weight: 700;
  color: var(--red);
  margin: 0;
}
.verdict-banner.green { background: #E8F5E9; border-right-color: var(--green-accent); }
.verdict-banner.green .verdict-text { color: var(--green-accent); }
.verdict-banner.amber { background: #FFF8E1; border-right-color: var(--amber); }
.verdict-banner.amber .verdict-text { color: var(--amber); }

/* ============================================
   PRIORITY LIST — plain markup; numbers are hardcoded in the HTML (v8h).
   No CSS counters or ::before — those re-introduced BIDI bugs.
   ============================================ */
ol.priority-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
ol.priority-list > li {
  margin-bottom: 5mm;
  font-size: 11pt;
  line-height: 1.75;
  color: var(--gray-dark);
  page-break-inside: avoid;
}
ol.priority-list strong { font-weight: 700; color: #1a1a1a; }

/* ============================================
   CLOSING DISCLAIMER
   ============================================ */
.closing-paragraph {
  margin-top: 12mm;
  padding-top: 5mm;
  border-top: 1px solid var(--gray-light);
  font-size: 9.5pt;
  color: var(--gray-mid);
  line-height: 1.8;
  font-style: italic;
}

/* ============================================
   APPENDIX A DIVIDER — no letter-spacing on Hebrew
   ============================================ */
.appendix-divider {
  page: appendix-divider;
  text-align: center;
  padding-top: 70mm;
}
.appendix-divider .label {
  font-size: 11pt;
  color: var(--gray-mid);
  margin-bottom: 14mm;
}
.appendix-divider .big-title {
  font-size: 60pt;
  font-weight: 700;
  color: var(--green-dark);
  margin-bottom: 6mm;
}
.appendix-divider .subtitle {
  font-size: 18pt;
  color: var(--gray-dark);
  margin-bottom: 14mm;
  font-weight: 400;
}
.appendix-divider .note {
  font-size: 11pt;
  color: var(--gray-mid);
  font-style: italic;
  max-width: 130mm;
  margin: 0 auto;
  line-height: 1.8;
}

/* Section-group head inside appendix detail */
.section-group-head {
  font-size: 11pt;
  font-weight: 700;
  color: var(--green-dark);
  margin: 8mm 0 3mm 0;
}

/* Inline discipline feedback callout (when a discipline manager has commented) */
.feedback {
  margin-top: 3mm;
  padding: 3mm 4mm;
  background: #ecf3fb;
  border-right: 3px solid #4a78b0;
  border-radius: 0 2px 2px 0;
  font-size: 9pt;
  color: #1a1a1a;
}
.feedback .flbl {
  font-weight: 700;
  color: #0d3a73;
  display: block;
  margin-bottom: 1mm;
}
"""

NBSP_NUM = "&nbsp;&nbsp;"  # spacing between number and title (per reference)

# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_audit_pdf(
    audit_results: dict,
    project_schema: dict,
    submission_metadata: dict,
    output_path: Path,
    options: dict | None = None,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    project = project_schema.get("project", {})
    meta = project.get("meta", {})
    plan_number = meta.get("plan_number", "")
    parcels = project.get("parcels", []) or []
    residential_parcels = _residential_parcels(parcels)

    content_results = audit_results.get("content", []) or []
    discipline_results = audit_results.get("disciplines", []) or []
    format_results = audit_results.get("format", []) or []

    parts: list[str] = []
    parts.append(_render_cover(meta, submission_metadata, plan_number))
    parts.append(_render_toc(plan_number, residential_parcels, discipline_results))
    parts.append(_render_section_1())
    parts.append(_render_section_2(content_results, residential_parcels, plan_number))
    parts.append(_render_section_3(discipline_results))
    parts.append(_render_section_4(content_results, discipline_results, format_results,
                                    residential_parcels=residential_parcels))
    parts.append(_render_appendix_divider())
    parts.append(_render_appendix_detail(format_results))

    html_doc = (
        '<!DOCTYPE html>'
        '<html lang="he" dir="rtl">'
        '<head><meta charset="utf-8"><title>סקירת תוכנית עיצוב</title></head>'
        '<body>' + "".join(parts) + '</body></html>'
    )
    _render_to_pdf(html_doc, output_path)
    return output_path


def _render_to_pdf(html_str: str, output_path: Path) -> None:
    from weasyprint import HTML, CSS as WeasyCSS
    from weasyprint.text.fonts import FontConfiguration
    font_config = FontConfiguration()
    base = str(FONT_DIR) + "/"
    HTML(string=html_str, base_url=base).write_pdf(
        str(output_path),
        stylesheets=[WeasyCSS(string=_CSS, base_url=base, font_config=font_config)],
        font_config=font_config,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cover (page: cover)
# ─────────────────────────────────────────────────────────────────────────────

def _render_cover(meta: dict, submission_metadata: dict, plan_number: str) -> str:
    version = submission_metadata.get("submission_version", "")
    sub_date = submission_metadata.get("submission_date", "")
    sub_month_year = _sub_month_year_he(sub_date)
    architect_full = (meta.get("architect_of_record") or "").strip()
    architect_short = _format_architect_short(architect_full)
    approval_label = _approval_label(meta)

    return f"""
    <div class="cover">
      <img class="logo" src="../nessziona_logo.png" alt="">
      <div class="brand-eyebrow">NZC | מינהלת ההתחדשות העירונית</div>
      <div class="brand-name">נס ציונה</div>
      <hr class="rule">
      <h1 class="title">סקירת תוכנית עיצוב</h1>
      <div class="subtitle">תכנית בינוי ופיתוח — מתחם הטייסים-ההסתדרות</div>
      <div class="subtitle">תכנית עיצוב גרסה {_esc(version)} · {_esc(sub_month_year)}</div>

      <div class="data-block">
        <div><span class="label">תכנית סטטוטורית:</span> {_esc(plan_number)} {_esc(approval_label)}</div>
        <div><span class="label">עורך התכנית:</span> אדריכלים {_esc(architect_short)}</div>
        <div><span class="label">תאריך הסקירה:</span> {_today_he()}</div>
        <div><span class="label">סוג הדוח:</span> סקירה אוטומטית לפני חוות דעת רשמית</div>
      </div>

      <div class="pill">{_esc(DOC_TYPE_LABEL)}</div>
      <hr class="rule">

      <p class="abstract">דוח זה מציג בדיקה אוטומטית של הציות התכנוני לתב"ע {_esc(plan_number)}.
        הוא כולל ארבעה פרקים: ניתוח תכנון עירוני, בדיקת תאימות לתב"ע, בדיקה רב-תחומית לפי חוברת
        ההנחיות העירונית, ונספח טכני של תאימות פורמט. הדוח מהווה טיוטה מקדימה לחוות דעת מהנדס
        הוועדה המקומית.</p>
    </div>
    """


def _format_architect_short(architect_of_record: str) -> str:
    if not architect_of_record:
        return ""
    name = architect_of_record.split("אדריכלים")[0].strip()
    for trail in ('אדריכלים ומתכנני ערים בע"מ', "אדריכלים ומתכנני ערים",
                  'אדריכלים בע"מ', 'בע"מ'):
        if name.endswith(trail):
            name = name[:-len(trail)].strip()
    return name or architect_of_record


def _approval_label(meta: dict) -> str:
    verified = (meta.get("approval_gazette_verified") is True
                or not meta.get("approval_gazette_verification_note"))
    date_iso = meta.get("approval_gazette_date") or ""
    if verified and date_iso:
        try:
            d = dt.date.fromisoformat(date_iso)
            return f"(אושרה {d.strftime('%d.%m.%Y')})"
        except ValueError:
            pass
    return "(אושרה)"


# ─────────────────────────────────────────────────────────────────────────────
# TOC — table-based, target-counter for page numbers
# ─────────────────────────────────────────────────────────────────────────────

def _render_toc(plan_number: str, residential_parcels: list[dict],
                discipline_results: list[dict]) -> str:
    rows: list[str] = []
    rows.append(_toc_row("1.", "ניתוח תכנון עירוני", "#sec-1", "main"))
    rows.append(_toc_row("2.", f'בדיקת תאימות תוכן לתב"ע {plan_number}', "#sec-2", "main"))
    for i, p in enumerate(residential_parcels, start=1):
        rows.append(_toc_row(f"2.{i}", _parcel_label_he(p), f"#sec-2-{i}", "sub"))
    pw_idx = len(residential_parcels) + 1
    rows.append(_toc_row(f"2.{pw_idx}", "בדיקות ברמת תכנית", f"#sec-2-{pw_idx}", "sub"))

    rows.append(_toc_row("3.", "בדיקה רב-תחומית לפי חוברת הנחיות עירונית", "#sec-3", "main"))
    seen = set()
    disc_i = 0
    for code in DISCIPLINE_ORDER:
        if any(r.get("discipline") == code for r in discipline_results) and code not in seen:
            disc_i += 1
            seen.add(code)
            rows.append(_toc_row(f"3.{disc_i}", DISCIPLINE_NAME_HE[code],
                                  f"#sec-3-{disc_i}", "sub"))

    rows.append(_toc_row("4.", "סיכום וממצאים סופיים", "#sec-4", "main"))
    rows.append(_toc_row("נספח א", "ליקויי פורמט בחוברת ההגשה", "#sec-appendix-a", "main"))

    return f"""
    <div class="chapter">
      <div class="eyebrow">{_esc(EYEBROW)}</div>
      <h2 class="chapter-num-title">תוכן עניינים</h2>
      <table class="toc">
        {''.join(rows)}
      </table>
    </div>
    """


def _toc_row(num: str, title: str, href: str, css_kind: str) -> str:
    """Title cell wraps an <a> for clickability. Plain text with regular space — no BIDI wrapper."""
    return (
        f'<tr>'
        f'<td class="title {css_kind}">'
        f'<a href="{_esc(href)}">{_esc(num)} {_esc(title)}</a>'
        f'</td>'
        f'<td class="page"><a href="{_esc(href)}"></a></td>'
        f'</tr>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Chapter divider helper
# ─────────────────────────────────────────────────────────────────────────────

def _chapter_open(num_label: str, title: str, intro: str) -> str:
    # Plain "N. title" — no <span>, no dir=ltr, regular space. BIDI puts the digit at the right edge.
    return (
        f'<div class="eyebrow">{_esc(EYEBROW)}</div>'
        f'<h2 class="chapter-num-title">{_esc(num_label)}. {_esc(title)}</h2>'
        f'<p class="chapter-intro">{_esc(intro)}</p>'
    )


def _badges_table(items: list[tuple[int, str, str]]) -> str:
    cells = []
    for count, label, css_class in items:
        cells.append(
            f'<td class="{css_class}">'
            f'<div class="num">{count}</div>'
            f'<div class="label">{label}</div>'
            f'</td>'
        )
    return f'<table class="badges"><tr>{"".join(cells)}</tr></table>'


# ─────────────────────────────────────────────────────────────────────────────
# §1
# ─────────────────────────────────────────────────────────────────────────────

def _render_section_1() -> str:
    intro = ('פרק זה בוחן את האיכות התכנונית של ההצעה — שילוב במרקם, תנועה, מרחב ציבורי, '
             'חזות. דורש שיפוט מקצועי של מהנדס/ת המינהלת.')
    return f"""
    <div class="chapter" id="sec-1">
      {_chapter_open("1", "ניתוח תכנון עירוני", intro)}
      <div class="callout">
        <div class="callout-title">דורש השלמה ידנית של מהנדס/ת המינהלת</div>
        <p class="callout-body">הניתוח התכנוני האיכותי (שילוב בסביבה, תנועה, שצ"פ, מבני ציבור, חזות,
          אשפה) דורש שיפוט מקצועי שאינו ניתן לאוטומציה. הוא לב הסקירה ויושלם לפני הפיכת הסקירה
          לחוות דעת רשמית.</p>
      </div>
    </div>
    """


# ─────────────────────────────────────────────────────────────────────────────
# §2 — content compliance
# ─────────────────────────────────────────────────────────────────────────────

def _render_section_2(content_results, residential_parcels, plan_number) -> str:
    intro = (
        f'פרק זה משווה את ערכי ההגשה (יח"ד, שטחים, גובה, חניה, תמהיל, שטחים מחלחלים) מול '
        f'התקרות והדרישות המוגדרות בתב"ע {plan_number}. בכל סעיף — ההגשה הנוכחית, הדרישה, והפעולה הנדרשת.'
    )
    badges = _badges_table(_content_badge_counts(content_results))
    sec2_title = f'בדיקת תאימות תוכן לתב"ע {plan_number}'

    by_parcel: dict[str, list[dict]] = {}
    plan_wide: list[dict] = []
    for r in content_results:
        pid = r.get("ta_shetach_id")
        if pid is None:
            plan_wide.append(r)
        else:
            by_parcel.setdefault(pid, []).append(r)

    subs = []
    for i, parcel in enumerate(residential_parcels, start=1):
        subs.append(_parcel_subsection(f"2.{i}", f"sec-2-{i}", parcel,
                                       by_parcel.get(parcel["parcel_id"], [])))
    pw_idx = len(residential_parcels) + 1
    subs.append(_plan_wide_subsection(f"2.{pw_idx}", f"sec-2-{pw_idx}", plan_wide))

    return f"""
    <div class="chapter" id="sec-2">
      {_chapter_open("2", sec2_title, intro)}
      {badges}
      {''.join(subs)}
    </div>
    """


def _parcel_subsection(num: str, anchor_id: str, parcel: dict, results: list[dict]) -> str:
    label = _parcel_label_he(parcel)
    units_max = (parcel.get("units") or {}).get("max_units")
    height_max = (parcel.get("height") or {}).get("max_height_m")
    floors_max = (parcel.get("height") or {}).get("max_floors_above_entry")
    primary_max = (parcel.get("building_rights") or {}).get("primary_sqm")

    unit_result = next((r for r in results if r.get("rule_code") == "CONTENT_UNIT_COUNT"), None)
    summary = _parcel_headline_he(label, unit_result, units_max)

    meta_parts = []
    if units_max is not None:
        meta_parts.append(f'תקרת תב"ע: {units_max} יח"ד')
    if height_max is not None:
        meta_parts.append(f'גובה {height_max} מ\'')
    if floors_max is not None:
        meta_parts.append(f'{floors_max} קומות')
    if primary_max is not None:
        meta_parts.append(f'שטח עיקרי {_format_int(primary_max)} מ"ר')
    meta = " · ".join(meta_parts)

    rows = _parcel_table_rows(results, parcel)
    table = _content_table_html(rows)
    return f"""
    <div class="subsection" id="{anchor_id}">
      <h3 class="subsection-num">{_esc(num)} {_esc(label)}</h3>
      <div class="subsection-summary">{_esc(summary)}</div>
      <div class="subsection-meta">{_esc(meta)}</div>
      {table}
    </div>
    """


def _parcel_headline_he(label: str, unit_result: dict | None, units_max: int | None) -> str:
    if unit_result and unit_result.get("verdict") not in (None, "not_submitted", "unevaluable"):
        sub = unit_result.get("evidence", {}).get("submission_value")
        if sub is not None:
            return f'{sub} יח"ד מוצעות ב{label}'
    if units_max is not None:
        return f'{label} — עד {units_max} יח"ד לפי תב"ע'
    return label


def _parcel_table_rows(results: list[dict], parcel: dict) -> list[dict]:
    by_code = {r["rule_code"]: r for r in results}
    out = []
    for code in CONTENT_ROW_ORDER:
        r = by_code.get(code)
        if r is None or r.get("verdict") == "not_applicable":
            continue
        out.append(_content_row(r, parcel))
    return out


def _content_row(r: dict, parcel: dict) -> dict:
    code = r["rule_code"]
    label = _content_rule_label(code)
    v = r.get("verdict", "")
    vclass, vlabel = VERDICT_TO_VCLASS_AND_LABEL.get(v, ("v-na", "—"))
    sub_display, schema_display = _content_value_pair(r, parcel)
    note = r.get("notes_he", "") or r.get("remediation_he", "")
    feedback = _feedback_html(r)
    return {
        "label": label,
        "verdict_html": f'<span class="{vclass}">{vlabel}</span>',
        "submission": sub_display,
        "schema": schema_display,
        "note_html": f'{_esc(note)}{feedback}',
    }


def _content_table_html(rows: list[dict]) -> str:
    if not rows:
        return '<p style="color:#7A7A7A;">אין בדיקות פעילות לתא שטח זה.</p>'
    body = "".join(
        f"<tr>"
        f"<td>{_esc(r['label'])}</td>"
        f"<td>{r['verdict_html']}</td>"
        f"<td>{_esc(r['submission'])}</td>"
        f"<td>{_esc(r['schema'])}</td>"
        f"<td>{r['note_html']}</td>"
        f"</tr>"
        for r in rows
    )
    return f"""
    <table class="audit">
      <thead><tr>
        <th style="width:17%;">נושא בדיקה</th>
        <th style="width:13%;">ממצא</th>
        <th style="width:14%; white-space: nowrap;">בתוכנית&nbsp;עיצוב</th>
        <th style="width:14%;">בתב"ע</th>
        <th style="width:42%;">הערה</th>
      </tr></thead>
      <tbody>{body}</tbody>
    </table>
    """


def _content_value_pair(r: dict, parcel: dict) -> tuple[str, str]:
    ev = r.get("evidence", {}) or {}
    code = r["rule_code"]
    verdict = r.get("verdict", "")
    if verdict == "not_submitted":
        sub_display = "—"
    elif "submission_value" in ev and ev["submission_value"] is not None:
        sub_display = _format_value(ev["submission_value"], _unit_for(code))
    elif "submission_max_height_m" in ev:
        sub_display = f'{ev["submission_max_height_m"]} מ\''
    elif verdict == "requires_review":
        sub_display = "—"
    elif verdict == "unevaluable":
        sub_display = "לא ניתן לחילוץ"
    else:
        sub_display = "—"
    return sub_display, _schema_value_for(code, parcel)


def _schema_value_for(code: str, parcel: dict) -> str:
    br = parcel.get("building_rights") or {}
    h = parcel.get("height") or {}
    u = parcel.get("units") or {}
    if code == "CONTENT_UNIT_COUNT":
        m = u.get("max_units")
        return f'{m} יח"ד' if m is not None else "—"
    if code == "CONTENT_BUILDING_AREA_MAIN":
        v = br.get("primary_sqm")
        return f'{_format_int(v)} מ"ר' if v is not None else "—"
    if code == "CONTENT_BUILDING_AREA_SERVICE_ABOVE":
        v = br.get("service_above_sqm")
        return f'{_format_int(v)} מ"ר' if v is not None else "—"
    if code == "CONTENT_BUILDING_AREA_SERVICE_BELOW":
        v = br.get("service_below_sqm")
        return f'{_format_int(v)} מ"ר' if v is not None else "—"
    if code == "CONTENT_BUILDING_HEIGHT":
        v = h.get("max_height_m")
        f = h.get("max_floors_above_entry")
        if v is not None and f is not None:
            return f'{v} מ\' / {f} קומות'
        if v is not None:
            return f'{v} מ\''
        if f is not None:
            return f'{f} קומות'
        return "—"
    if code == "CONTENT_SETBACKS":
        return "לפי תשריט (DWG)"
    if code == "CONTENT_PARKING_RATIO":
        return "תקן חניה לאומי"
    return "—"


def _content_rule_label(code: str) -> str:
    return {
        "CONTENT_UNIT_COUNT": 'כמות יח"ד',
        "CONTENT_BUILDING_AREA_MAIN": 'שטח עיקרי (מ"ר)',
        "CONTENT_BUILDING_AREA_SERVICE_ABOVE": 'שטח שירות מעל (מ"ר)',
        "CONTENT_BUILDING_AREA_SERVICE_BELOW": 'שטח שירות מתחת (מ"ר)',
        "CONTENT_BUILDING_HEIGHT": "גובה ביחס לקרקע / קומות",
        "CONTENT_SETBACKS": "קווי בניין",
        "CONTENT_PARKING_RATIO": "יחס חניה",
        "CONTENT_APARTMENT_MIX_SMALL": "אחוז דירות קטנות",
        "CONTENT_PERMEABLE_SURFACES": "אחוז שטחים מחלחלים",
    }.get(code, code)


def _unit_for(code: str) -> str:
    return {
        "CONTENT_UNIT_COUNT": 'יח"ד',
        "CONTENT_BUILDING_AREA_MAIN": 'מ"ר',
        "CONTENT_BUILDING_AREA_SERVICE_ABOVE": 'מ"ר',
        "CONTENT_BUILDING_AREA_SERVICE_BELOW": 'מ"ר',
        "CONTENT_BUILDING_HEIGHT": "מ'",
        "CONTENT_APARTMENT_MIX_SMALL": "%",
        "CONTENT_PERMEABLE_SURFACES": "%",
    }.get(code, "")


def _format_value(v: Any, unit: str) -> str:
    if isinstance(v, (int, float)):
        return f"{_format_number(v)} {unit}".strip()
    return f"{v} {unit}".strip()


def _format_int(v: Any) -> str:
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v)


def _format_number(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, int):
        return f"{v:,}"
    return f"{v}"


def _plan_wide_subsection(num: str, anchor_id: str, plan_wide: list[dict]) -> str:
    visible = [r for r in plan_wide if r.get("verdict") != "not_applicable"]
    rows = [_content_row(r, parcel={}) for r in sorted(visible, key=lambda x: x["rule_code"])]
    table = _content_table_html(rows)
    return f"""
    <div class="subsection" id="{anchor_id}">
      <h3 class="subsection-num">{_esc(num)} בדיקות ברמת תכנית</h3>
      <div class="subsection-meta">בדיקות שאינן ייחודיות לתא שטח מסוים — תמהיל יח"ד, שטחים מחלחלים כוללים.</div>
      {table}
    </div>
    """


def _content_badge_counts(content_results: list[dict]) -> list[tuple[int, str, str]]:
    c = {"ok": 0, "fail": 0, "review": 0, "unknown": 0, "na": 0}
    for r in content_results:
        v = r.get("verdict")
        if v in ("pass", "pass_with_note"):
            c["ok"] += 1
        elif v in ("fail", "fail_borderline", "not_submitted"):
            c["fail"] += 1
        elif v == "requires_review":
            c["review"] += 1
        elif v == "unevaluable":
            c["unknown"] += 1
        elif v == "not_applicable":
            c["na"] += 1
    return [
        (c["ok"],      "תקינים בתוכן",       "ok"),
        (c["fail"],    "ליקויים בתוכן",       "fail"),
        (c["review"],  "דורשים בירור",        "review"),
        (c["unknown"], "לא ניתנים לבדיקה",    "unknown"),
        (c["na"],      "לא רלוונטיים",        "na"),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# §3
# ─────────────────────────────────────────────────────────────────────────────

def _render_section_3(discipline_results: list[dict]) -> str:
    intro = (
        'פרק זה בוחן את ההגשה מול חוברת ההנחיות העירונית של נס ציונה (407-0730606, פברואר 2026). '
        'הבדיקה מאורגנת בעשר דיסציפלינות. במקום בו התקבל פידבק ממנהל הדיסציפלינה — הוא משולב בתא ההערה.'
    )
    badges = _badges_table(_discipline_badge_counts(discipline_results))

    by_disc: dict[str, list[dict]] = {}
    for r in discipline_results:
        by_disc.setdefault(r.get("discipline", "unknown"), []).append(r)

    subs = []
    disc_i = 0
    for code in DISCIPLINE_ORDER:
        rules = by_disc.get(code)
        if not rules:
            continue
        disc_i += 1
        subs.append(_discipline_subsection(f"3.{disc_i}", f"sec-3-{disc_i}", code, rules))

    return f"""
    <div class="chapter" id="sec-3">
      {_chapter_open("3", "בדיקה רב-תחומית לפי חוברת הנחיות עירונית", intro)}
      {badges}
      {''.join(subs)}
    </div>
    """


def _discipline_subsection(num: str, anchor_id: str, code: str, rules: list[dict]) -> str:
    name = DISCIPLINE_NAME_HE.get(code, code)
    rows = "".join(_discipline_row_html(r) for r in sorted(rules, key=lambda x: x["rule_code"]))
    return f"""
    <div class="subsection" id="{anchor_id}">
      <h3 class="subsection-num">{_esc(num)} {_esc(name)}</h3>
      <table class="audit">
        <thead><tr>
          <th style="width:28%;">מדיניות בחוברת ההנחיות</th>
          <th style="width:24%;">מצב בהגשה 24.3</th>
          <th style="width:13%;">ממצא</th>
          <th style="width:35%;">הערה / פעולה נדרשת</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """


def _discipline_row_html(r: dict) -> str:
    title = r.get("rule_name_he", r.get("rule_code", ""))
    v = r.get("verdict", "")
    vclass, vlabel = VERDICT_TO_VCLASS_AND_LABEL.get(v, ("v-na", "—"))
    feedback = _feedback_html(r)

    ev = r.get("evidence", {}) or {}
    cowork_sourced = ev.get("source") == "cowork_discipline_findings_v24.3"

    # Left col (policy column): show the rule policy text always.
    # When Cowork findings are wired in, `notes_he` carries the compliance note
    # (with page prefix), so fall back to remediation_he / policy_he for the
    # policy half so we don't duplicate the same sentence in two columns.
    if cowork_sourced:
        # The compliance note moves to the rightmost column; left col shows policy.
        policy = r.get("remediation_he", "") or ""
    else:
        policy = r.get("notes_he", "")

    submission_state = _submission_state_he(r)
    note = _action_note_he(r)
    return f"""
    <tr>
      <td><b>{_esc(title)}</b><br>{_esc(policy)}</td>
      <td>{_esc(submission_state)}</td>
      <td><span class="{vclass}">{vlabel}</span></td>
      <td>{_esc(note)}{feedback}</td>
    </tr>
    """


def _submission_state_he(r: dict) -> str:
    ev = r.get("evidence", {}) or {}
    # v8j: when Cowork's hand-extracted findings supplied the verdict, show
    # the visual description verbatim — it's the human-verified ground truth.
    if ev.get("source") == "cowork_discipline_findings_v24.3":
        visual = (r.get("evidence_visual") or ev.get("evidence_visual") or "").strip()
        if visual:
            return visual
        return "—"
    ct = ev.get("check_type")
    if ct == "text_pattern":
        if ev.get("found_any"):
            pgs = sorted({pg for v in ev.get("matched_pages", {}).values() for pg in v})
            return f"אותרו אזכורים בעמודים: {pgs[:6]}"
        # v8i: don't expose the engine's keyword-search failure as a "finding".
        return "פריט ויזואלי — לא ניתן לבדיקה אוטומטית."
    if ct == "annex_required":
        if ev.get("annex_found"):
            pgs = sorted({pg for v in ev.get("matched_pages", {}).values() for pg in v})
            return f"נספח אותר (עמודים: {pgs[:6]})."
        return "הנספח לא אותר בהגשה."
    if ct == "manual_review":
        return "בדיקה ויזואלית — לא מבוצעת אוטומטית."
    return "—"


def _action_note_he(r: dict) -> str:
    """Right-column action note. v8j: prefer Cowork's compliance_note prefixed
    with `(עמ' N, M)` from evidence_pages when available."""
    ev = r.get("evidence", {}) or {}
    if ev.get("source") == "cowork_discipline_findings_v24.3":
        pages = r.get("evidence_pages") or ev.get("evidence_pages") or []
        note = (r.get("compliance_note") or ev.get("compliance_note") or "").strip()
        if pages and note:
            return f"(עמ' {', '.join(str(p) for p in pages)}) {note}"
        if pages:
            return f"(עמ' {', '.join(str(p) for p in pages)})"
        if note:
            return note
        return r.get("remediation_he", "") or "—"
    v = r.get("verdict", "")
    return r.get("remediation_he", "") if v != "pass" else "ראה ראיות."


def _discipline_badge_counts(discipline_results: list[dict]) -> list[tuple[int, str, str]]:
    c = {"ok": 0, "fail": 0, "review": 0, "unknown": 0}
    for r in discipline_results:
        v = r.get("verdict")
        if v == "pass":
            c["ok"] += 1
        elif v in ("fail", "fail_borderline", "not_submitted"):
            c["fail"] += 1
        elif v == "requires_review":
            c["review"] += 1
        elif v == "unevaluable":
            c["unknown"] += 1
    return [
        (c["ok"],      "תקינים במדיניות",     "ok"),
        (c["fail"],    "סטיות ממדיניות",      "fail"),
        (c["review"],  "דורשים בירור",        "review"),
        (c["unknown"], "לא ניתנים לבדיקה",    "unknown"),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# §4
# ─────────────────────────────────────────────────────────────────────────────

def _render_section_4(content_results, discipline_results, format_results,
                       residential_parcels: list[dict] | None = None) -> str:
    intro = "פרק זה מסכם את ממצאי הסקירה ומדרג את הפעולות הנדרשות מכם לפני הסקירה הבאה."
    badges = _badges_table(_summary_badge_counts(content_results, discipline_results))
    banner = _verdict_banner_html(content_results, discipline_results)

    valid_pids = {p["parcel_id"] for p in (residential_parcels or [])}
    items = _priority_items(content_results, discipline_results, valid_pids=valid_pids)
    if items:
        list_html = '<ol class="priority-list">' + "".join(
            f'<li>{i + 1}. <strong>{_esc(it["title_with_plots"])}.</strong> {_esc(it["body"])}</li>'
            for i, it in enumerate(items)
        ) + '</ol>'
    else:
        list_html = '<p style="color:#7A7A7A;">אין פעולות נדרשות.</p>'

    disclaimer = (
        'דוח זה נערך ע"י מנוע הבדיקה האוטומטי של פלטפורמת המינהלת. הדוח דורש סקירה וחתימה של '
        'מהנדס/ת הוועדה המקומית טרם הפיכתו לחוות דעת רשמית.'
    )

    return f"""
    <div class="chapter" id="sec-4">
      {_chapter_open("4", "סיכום וממצאים סופיים", intro)}
      {badges}
      {banner}
      <h3 class="subsection-num" style="margin-top:8mm">פעולות הנדרשות מכם לפני הסקירה הבאה</h3>
      {list_html}
      <p class="closing-paragraph">{_esc(disclaimer)}</p>
    </div>
    """


def _summary_badge_counts(content_results, discipline_results) -> list[tuple[int, str, str]]:
    def count(results, predicate) -> int:
        return sum(1 for r in results if predicate(r.get("verdict")))
    is_fail = lambda v: v in ("fail", "fail_borderline", "not_submitted")
    is_review = lambda v: v == "requires_review"
    is_pass = lambda v: v in ("pass", "pass_with_note")
    return [
        (count(content_results, is_pass) + count(discipline_results, is_pass), "תקינים", "ok"),
        (count(content_results, is_fail) + count(discipline_results, is_fail), "נדרשים תיקונים", "fail"),
        (count(content_results, is_review) + count(discipline_results, is_review), "דורשים בירור", "review"),
    ]


def _verdict_banner_html(content_results, discipline_results) -> str:
    any_fail = any(r.get("verdict") in ("fail", "fail_borderline", "not_submitted")
                   for r in content_results + discipline_results)
    any_review = any(r.get("verdict") == "requires_review"
                     for r in content_results + discipline_results)
    if any_fail:
        text = 'נדרשים תיקונים מהותיים — ההגשה אינה מוכנה לחתימה'
        cls = ""
    elif any_review:
        text = 'נדרשים הבהרות לפני חתימה'
        cls = "amber"
    else:
        text = 'ההגשה מוכנה לחתימה — אין ליקויים מהותיים'
        cls = "green"
    return f'<div class="verdict-banner {cls}"><p class="verdict-text">{_esc(text)}</p></div>'


def _priority_items(content_results, discipline_results,
                     *, valid_pids: set[str] | None = None) -> list[dict]:
    """Build the §4 priority list.

    - Skip results for plot IDs outside the project's valid set (residential +
      mixed-use; excludes שצ"פ, road, path). Plan-wide rules are always kept.
    - Bug 6 consolidation: CONTENT_SETBACKS gets ONE row with a DWG-deferral
      body — no per-plot enumeration — since the blocker is the same for all
      plots (DWG parsing not yet implemented).
    """
    valid_pids = valid_pids if valid_pids is not None else set()
    grouped: dict[str, dict] = {}

    def bucket(rule_code, severity, title, body, plot_label, override_plots: str | None = None,
               sort_rank: int = 5):
        slot = grouped.setdefault(rule_code, {
            "severity": severity, "title": title, "body": body, "plots": [],
            "override_plots_label": override_plots, "sort_rank": sort_rank,
        })
        if override_plots:
            slot["override_plots_label"] = override_plots
        if plot_label and plot_label not in slot["plots"]:
            slot["plots"].append(plot_label)

    for r in content_results:
        v = r.get("verdict")
        if v not in ("fail", "fail_borderline", "not_submitted", "requires_review"):
            continue
        pid = r.get("ta_shetach_id")
        if pid and valid_pids and pid not in valid_pids:
            continue  # silently drop שצ"פ/road/path entries

        code = r["rule_code"]

        # Bug 6 consolidation — single setbacks entry with DWG-deferral note
        if code == "CONTENT_SETBACKS":
            bucket(
                code, "major", "קווי בניין",
                'בדיקה זו דורשת פירוק קובץ DWG (תכונה דחויה ל-v8a-3). עד אז — אימות ידני.',
                None,
                override_plots="כל תאי השטח",
            )
            continue

        if code == "CONTENT_APARTMENT_MIX_SMALL":
            sev = "critical"   # the single most important extraction-derived finding
        elif code in ("CONTENT_UNIT_COUNT", "CONTENT_BUILDING_AREA_MAIN"):
            sev = "critical"
        else:
            sev = "major"

        title = _content_rule_label(code)
        # For ambiguous (requires_review) rules — use the rule's own notes_he
        # which contains the per-rule explanation (e.g., architect-vs-strict gap).
        body = r.get("notes_he") if v == "requires_review" else r.get("remediation_he", "")
        plot_lbl = _plot_label_he(pid) if pid else "ברמת תכנית"
        bucket(code, sev, title, body or "", plot_lbl)

    # v8j: Cowork JSON emits missing-annex situations as `fail` (not
    # `not_submitted`). Collect every discipline fail/not_submitted, then peel
    # off the annex-pattern ones into a single critical-severity row at the
    # top — same consolidation pattern as DWG-deferred setbacks.
    annex_fails: list[dict] = []
    for r in discipline_results:
        if r.get("verdict") not in ("fail", "not_submitted"):
            continue
        name = r.get("rule_name_he", "")
        is_annex = ("נספח" in name) or ("רשימת צמחייה" in name) or ("5281" in name)
        if is_annex:
            annex_fails.append(r)
            continue
        sev = r.get("severity", "minor")
        disc = DISCIPLINE_NAME_HE.get(r.get("discipline", ""), r.get("discipline", ""))
        title = f"{disc} — {r.get('rule_name_he', r['rule_code'])}"
        bucket(r["rule_code"], sev, title, r.get("remediation_he", ""), None)

    if annex_fails:
        bucket(
            "DISC_ANNEXES_BUNDLE",
            "critical",
            "כל הנספחים החיצוניים חסרים",
            'ההגשה היא 63 עמודי תוכניות אדריכליות בלבד, ללא ששת הנספחים הנדרשים: '
            'חומריות, צמחייה, הידרולוגי, אקוסטי, ת"י 5281, איכות סביבה וקיימות. '
            'יש להגיש את כל הנספחים בגרסה הבאה — תיקון מהותי.',
            None,
            override_plots="ברמת תכנית",
            sort_rank=0,  # pin to the very top of the critical tier
        )

    order = {"critical": 0, "major": 1, "minor": 2, "info": 3}
    items = sorted(
        grouped.values(),
        key=lambda x: (order.get(x["severity"], 9), x.get("sort_rank", 5), x["title"]),
    )
    out = []
    for it in items:
        if it.get("override_plots_label"):
            plots = it["override_plots_label"]
        else:
            plots = ", ".join(it["plots"]) if it["plots"] else ""
        title_full = it["title"] + (f" — {plots}" if plots else "")
        out.append({"title_with_plots": title_full, "body": it["body"]})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Appendix A (divider + detail)
# ─────────────────────────────────────────────────────────────────────────────

def _render_appendix_divider() -> str:
    return f"""
    <div class="appendix-divider chapter" id="sec-appendix-a">
      <div class="label">{_esc(EYEBROW)}</div>
      <div class="big-title">נספח א</div>
      <div class="subtitle">ליקויי פורמט בחוברת ההגשה</div>
      <p class="note">סעיפי פורמט הסוטים מהסטנדרט שנקבע בחוברת ההנחיות העירונית.<br>
        <em>סעיפים תקינים — אינם מוצגים.</em></p>
    </div>
    """


def _render_appendix_detail(format_results: list[dict]) -> str:
    visible = [r for r in format_results if _format_verdict_kind(r) in ("fail", "review", "missing")]
    badges = _badges_table(_format_badge_counts(format_results))
    intro = (
        f'מנוע הפורמט בדק את ההגשה מול {len(format_results)} כללי פורמט. '
        f'{len(visible)} כללים הניבו ממצא של אי-תאימות או הצריכו בדיקה ידנית. '
        'שאר הכללים — תקינים ואינם מוצגים בנספח זה.'
    )
    groups: dict[str, list[dict]] = {}
    for r in visible:
        sec = _format_rule_section(r)
        groups.setdefault(sec, []).append(r)

    blocks = []
    for sec in sorted(groups.keys(), key=_sec_sort_key):
        rows_html = "".join(_format_row_html(r) for r in sorted(groups[sec], key=lambda x: x["rule_code"]))
        blocks.append(f"""
        <div class="section-group-head">סעיף {_esc(sec)} ({len(groups[sec])} ליקויים)</div>
        <table class="audit">
          <thead><tr>
            <th style="width:30%;">הכלל</th>
            <th style="width:14%;">ממצא</th>
            <th style="width:30%;">ראיות</th>
            <th style="width:26%;">הערה</th>
          </tr></thead>
          <tbody>{rows_html}</tbody>
        </table>
        """)

    body = f"""
    <div class="chapter">
      <div class="eyebrow">{_esc(EYEBROW)}</div>
      <h2 class="chapter-num-title">נספח א — ליקויי פורמט שזוהו</h2>
      <p class="chapter-intro">{_esc(intro)}</p>
      {badges}
      {''.join(blocks) if blocks else '<p style="color:#7A7A7A;">לא נמצאו ליקויי פורמט.</p>'}
    </div>
    """
    return body


def _format_badge_counts(format_results: list[dict]) -> list[tuple[int, str, str]]:
    c = {"ok": 0, "fail": 0, "review": 0, "unknown": 0}
    for r in format_results:
        k = _format_verdict_kind(r)
        if k == "pass":
            c["ok"] += 1
        elif k == "fail":
            c["fail"] += 1
        elif k == "review":
            c["review"] += 1
        elif k == "missing":
            c["unknown"] += 1
    return [
        (c["fail"],    "טעויות בפורמט",        "fail"),
        (c["review"],  "דורשים בירור",          "review"),
        (c["unknown"], "לא ניתנים לבדיקה",      "unknown"),
        (c["ok"],      "ללא טעויות (לא מוצגים)", "ok"),
    ]


def _format_verdict_kind(r: dict) -> str:
    v = r.get("verdict")
    ev = r.get("evidence", {}) or {}
    if v in ("pass", "pass_with_note"):
        return "pass"
    if v == "requires_review":
        return "review" if ev.get("check_method") == "manual_review" else "fail"
    if v in ("fail", "fail_borderline", "not_submitted"):
        return "fail"
    if v == "unevaluable":
        return "missing"
    return "missing"


def _format_row_html(r: dict) -> str:
    title = _format_rule_title(r)
    kind = _format_verdict_kind(r)
    label_css = {"fail": ("נדרש תיקון", "v-fail"),
                 "review": ("דורש בירור", "v-rev"),
                 "missing": ("לא ניתן לבדיקה", "v-miss")}.get(kind, ("—", "v-na"))
    evidence = _format_evidence_he(r)
    note = r.get("notes_he", "")
    return f"""
    <tr>
      <td>{_esc(title)}</td>
      <td><span class="{label_css[1]}">{label_css[0]}</span></td>
      <td>{_esc(evidence)}</td>
      <td>{_esc(note)}</td>
    </tr>
    """


def _format_evidence_he(r: dict) -> str:
    ev = r.get("evidence", {}) or {}
    if ev.get("check_method") == "manual_review":
        return "דורש בדיקה ויזואלית של מהנדס/ת"
    pages = ev.get("pages_checked") or []
    if r.get("verdict") in ("fail", "fail_borderline"):
        if pages:
            short = pages[:4]
            return f'לא נמצאו התאמות · עמ\' [{", ".join(str(p) for p in short)}{"…" if len(pages) > 4 else ""}]'
        return "לא נמצאו התאמות"
    if r.get("failure_mode") == "ENGINE_ERROR":
        return f'שגיאת מנוע — {ev.get("extracted_values", {}).get("error", "")}'
    return "—"


def _format_rule_section(r: dict) -> str:
    section_map = {
        "FORMAT_PAGE_SIZE_A3_LANDSCAPE": "6.1", "FORMAT_TEXT_DIRECTION_RTL": "6.1",
        "FORMAT_BACKGROUND_WHITE": "6.1", "FORMAT_FONT_HEBREW_SANS_SERIF": "6.2",
        "FORMAT_HEADER_COLOR_CYAN": "6.2", "FORMAT_COVER_TITLE_TEXT": "6.3",
        "FORMAT_COVER_PLAN_NUMBER": "6.3", "FORMAT_COVER_DATE": "6.3",
        "FORMAT_COVER_SIGNATURE_TABLE": "6.3", "FORMAT_COVER_AERIAL_IMAGE": "6.3",
        "FORMAT_TEAM_PAGE_EXISTS": "6.4", "FORMAT_TEAM_REQUIRED_DISCIPLINES": "6.4",
        "FORMAT_TOC_EXISTS": "6.5", "FORMAT_TOC_THREE_COLUMNS": "6.5",
        "FORMAT_CHAPTER_DIVIDER_PAGES": "6.6", "FORMAT_FOOTER_PRESENT_ALL_PAGES": "6.7",
        "FORMAT_FOOTER_PAGE_NUMBERS": "6.7", "FORMAT_FOOTER_PROJECT_NAME": "6.7",
        "FORMAT_LOGOS_FOOTER": "6.7", "FORMAT_CHAPTER_NUMBERING": "6.8",
        "FORMAT_REQUIRED_CHAPTERS_TYPOLOGIES": "6.8", "FORMAT_REQUIRED_CHAPTER_ENVELOPE": "6.8",
        "FORMAT_REQUIRED_CHAPTER_DEVELOPMENT": "6.8", "FORMAT_REQUIRED_CHAPTER_ENVIRONMENTAL": "6.8",
        "FORMAT_REQUIRED_CHAPTER_INFRASTRUCTURE": "6.8", "FORMAT_TYPICAL_FLOOR_MIX_TABLE": "6.9",
        "FORMAT_PARKING_TABLE": "6.9", "FORMAT_RENDERINGS_PRESENT": "6.9",
        "FORMAT_LEGEND_ON_DEVELOPMENT_PAGES": "6.9", "FORMAT_SCALE_ANNOTATIONS": "6.10",
        "FORMAT_NORTH_ARROW": "6.10", "FORMAT_REFERENT_SIGNATURE_PLACEHOLDERS": "6.10",
        "FORMAT_VERSION_NOTATION": "6.10", "FORMAT_DIMENSIONS_ON_PLANS": "6.10",
    }
    return section_map.get(r.get("rule_code", ""), "אחר")


def _format_rule_title(r: dict) -> str:
    titles = {
        "FORMAT_PAGE_SIZE_A3_LANDSCAPE": "גודל עמוד A3 לרוחב",
        "FORMAT_TEXT_DIRECTION_RTL": "כיוון טקסט מימין לשמאל",
        "FORMAT_BACKGROUND_WHITE": "רקע לבן",
        "FORMAT_FONT_HEBREW_SANS_SERIF": "גופן עברי סנס-סריף",
        "FORMAT_HEADER_COLOR_CYAN": "כותרות בצבע טורקיז",
        "FORMAT_COVER_TITLE_TEXT": "שער — כותרת ראשית",
        "FORMAT_COVER_PLAN_NUMBER": "שער — מספר תכנית",
        "FORMAT_COVER_DATE": "שער — תאריך הגשה",
        "FORMAT_COVER_SIGNATURE_TABLE": "שער — טבלת חתימות",
        "FORMAT_COVER_AERIAL_IMAGE": "שער — הדמיה מרכזית",
        "FORMAT_TEAM_PAGE_EXISTS": "עמוד צוות הפרויקט",
        "FORMAT_TEAM_REQUIRED_DISCIPLINES": "צוות — דיסציפלינות נדרשות",
        "FORMAT_TOC_EXISTS": "תוכן עניינים",
        "FORMAT_TOC_THREE_COLUMNS": "תוכן עניינים — שלוש עמודות",
        "FORMAT_CHAPTER_DIVIDER_PAGES": "עמודי מעבר לפרקים",
        "FORMAT_FOOTER_PRESENT_ALL_PAGES": "כותרת תחתונה בכל עמוד",
        "FORMAT_FOOTER_PAGE_NUMBERS": "מספרי עמודים בכותרת תחתונה",
        "FORMAT_FOOTER_PROJECT_NAME": "שם הפרויקט בכותרת תחתונה",
        "FORMAT_LOGOS_FOOTER": "לוגואים בכותרת תחתונה",
        "FORMAT_CHAPTER_NUMBERING": "מספור פרקים X.Y",
        "FORMAT_REQUIRED_CHAPTERS_TYPOLOGIES": "פרקי טיפולוגיות",
        "FORMAT_REQUIRED_CHAPTER_ENVELOPE": "פרק מעטפת בניינים",
        "FORMAT_REQUIRED_CHAPTER_DEVELOPMENT": "פרק פיתוח",
        "FORMAT_REQUIRED_CHAPTER_ENVIRONMENTAL": "פרק הנחיות סביבתיות",
        "FORMAT_REQUIRED_CHAPTER_INFRASTRUCTURE": "פרק הנחיות תשתיות",
        "FORMAT_TYPICAL_FLOOR_MIX_TABLE": 'טבלת תמהיל יח"ד',
        "FORMAT_PARKING_TABLE": "טבלת חניות במרתף",
        "FORMAT_RENDERINGS_PRESENT": "הדמיות תלת-ממדיות",
        "FORMAT_LEGEND_ON_DEVELOPMENT_PAGES": "מקרא לעמודי פיתוח",
        "FORMAT_SCALE_ANNOTATIONS": "קני מידה 1:250",
        "FORMAT_NORTH_ARROW": "חץ צפון על תוכניות",
        "FORMAT_REFERENT_SIGNATURE_PLACEHOLDERS": "מקום לחתימת רפרנט עירוני",
        "FORMAT_VERSION_NOTATION": "ציון גרסה ותאריך עדכון",
        "FORMAT_DIMENSIONS_ON_PLANS": "מידות מסומנות על תוכניות",
    }
    return titles.get(r.get("rule_code", ""), r.get("rule_code", ""))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _residential_parcels(parcels: list[dict]) -> list[dict]:
    keep = []
    for p in parcels:
        uses = p.get("uses") or []
        if any(u in ("residential", "public_facility", "public_facility_mixed", "commercial") for u in uses):
            keep.append(p)
    return keep


def _parcel_label_he(parcel: dict) -> str:
    pid = parcel.get("parcel_id", "")
    suffix = pid.replace("plot_", "")
    label = f"תא שטח {suffix}"
    raw = parcel.get("display_label") or ""
    if "(" in raw and ")" in raw:
        paren = raw[raw.find("("):raw.rfind(")") + 1]
        label = f"{label} {paren}"
    return label


def _plot_label_he(parcel_id: str | None) -> str:
    if not parcel_id:
        return ""
    return f"תא שטח {parcel_id.replace('plot_', '')}"


def _feedback_html(r: dict) -> str:
    fb = r.get("feedback_text_he")
    if not fb:
        return ""
    src = r.get("feedback_discipline_name_he", "מנהל הדיסציפלינה")
    return f'<div class="feedback"><span class="flbl">פידבק מ{_esc(src)}:</span>{_esc(fb)}</div>'


def _sub_month_year_he(date_iso: str) -> str:
    if not date_iso:
        return ""
    try:
        d = dt.date.fromisoformat(date_iso)
        return f"{HEBREW_MONTHS[d.month]} {d.year}"
    except (ValueError, KeyError):
        return date_iso


def _today_he() -> str:
    return dt.date.today().strftime("%d.%m.%Y")


def _esc(s: Any) -> str:
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _sec_sort_key(s: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in s.split("."))
    except ValueError:
        return (10**9,)
