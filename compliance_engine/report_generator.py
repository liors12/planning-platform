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
import json
import re
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
    "fail":            ("v-fail", "לא תקין"),
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
@page signature {
  size: A4;
  margin: 20mm 22mm 22mm 22mm;
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

/* M4 confidence chip — appears next to verdict when M4 override applied
   with non-HIGH confidence. HIGH confidence shows nothing (default state). */
.conf-chip {
  display: inline-block;
  margin-right: 6px;
  padding: 1px 6px;
  font-size: 8.5pt;
  font-weight: 500;
  border-radius: 8px;
  vertical-align: middle;
  white-space: nowrap;
}
.conf-chip.conf-medium { background: #FFF3E0; color: #B8651A; }
.conf-chip.conf-low    { background: #FFE0E0; color: #9C2929; }

/* M4 sidecar callout section — between section 2 and section 3 */
.sidecar-chapter {
  page-break-before: always;
}
.sidecar-card {
  margin: 6mm 0;
  padding: 6mm 7mm;
  border: 1px solid var(--gray-light);
  border-right: 4px solid var(--red);
  border-radius: 4px;
  background: #FFFAFA;
  page-break-inside: avoid;
}
.sidecar-card.sidecar-missing {
  border-right-color: var(--amber);
  background: #FFF8E1;
}
.sidecar-card .sidecar-head {
  font-size: 12pt;
  font-weight: 700;
  color: var(--red);
  margin-bottom: 2mm;
}
.sidecar-card.sidecar-missing .sidecar-head {
  color: #B8651A;
}
.sidecar-card .sidecar-meta {
  font-size: 9.5pt;
  color: var(--gray-mid);
  margin-bottom: 3mm;
}
.sidecar-card .sidecar-reasoning {
  font-size: 10.5pt;
  color: var(--gray-dark);
  line-height: 1.5;
}
.sidecar-card .sidecar-pages {
  font-size: 9pt;
  color: var(--gray-mid);
  margin-top: 2mm;
}

/* M5 — Section 5 coverage transparency */
.cov-table {
  width: 100%;
  border-collapse: collapse;
  margin: 4mm 0 8mm 0;
  font-size: 10pt;
}
.cov-table th {
  text-align: right;
  background: var(--green-dark);
  color: #fff;
  padding: 2mm 3mm;
  font-weight: 600;
  font-size: 10pt;
}
.cov-table td {
  text-align: right;
  padding: 2mm 3mm;
  border-bottom: 1px solid var(--gray-light);
  vertical-align: top;
}
.cov-table tbody tr:nth-child(even) td { background: #FAFAFA; }
.cov-help {
  font-size: 10pt;
  color: var(--gray-mid);
  margin-bottom: 2mm;
}
.cov-help.cov-warn {
  color: var(--red);
  font-weight: 600;
}
.cov-full     { color: var(--green-accent); font-weight: 600; }
.cov-partial  { color: var(--amber);         font-weight: 600; }
.cov-none     { color: var(--red);           font-weight: 600; }
.cov-pages td { font-size: 9pt; }
.cov-gap-list { margin: 4mm 0 8mm 0; }
.cov-gap-card {
  padding: 4mm 6mm;
  margin: 3mm 0;
  background: #FFF3E0;
  border-right: 3px solid var(--amber);
  border-radius: 3px;
  page-break-inside: avoid;
}
.cov-gap-title {
  font-size: 11pt;
  font-weight: 700;
  color: #8A4500;
  margin-bottom: 2mm;
}
.cov-gap-detail {
  font-size: 10pt;
  color: var(--gray-dark);
  line-height: 1.5;
}
.cov-gap-task {
  font-size: 9pt;
  color: var(--gray-mid);
  margin-top: 2mm;
  font-style: italic;
}
.cov-disclaimer {
  font-size: 10.5pt;
  color: var(--gray-dark);
  background: #F5F5F5;
  border-right: 3px solid var(--green-dark);
  padding: 5mm 7mm;
  margin: 4mm 0;
  line-height: 1.6;
}

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

/* ============================================
   SIGNATURE PAGE — cover #2, sits between cover and TOC
   ============================================ */
.signature-page {
  page: signature;
  page-break-before: always;
  page-break-after: always;
  direction: rtl;
  text-align: right;
}
.signature-page .eyebrow {
  font-size: 10pt;
  color: var(--gray-mid);
  margin-bottom: 6mm;
  letter-spacing: 0.5px;
}
.signature-page h1.sig-title {
  font-size: 22pt;
  font-weight: 700;
  color: var(--green-dark);
  margin: 0 0 4mm 0;
}
.signature-page .sig-subtitle {
  font-size: 10.5pt;
  color: var(--gray-mid);
  margin-bottom: 8mm;
  line-height: 1.5;
}
table.signature-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 4mm;
  table-layout: fixed;
}
table.signature-table th {
  background: var(--gray-bg);
  border: 1px solid var(--gray-light);
  padding: 3mm 4mm;
  font-size: 10.5pt;
  font-weight: 700;
  color: var(--gray-dark);
  text-align: right;
}
table.signature-table td {
  border: 1px solid var(--gray-light);
  padding: 2mm 4mm;
  font-size: 11pt;
  color: var(--gray-dark);
  vertical-align: middle;
  /* Tall enough for a wet signature (~14 mm) */
  height: 14mm;
}
table.signature-table td.discipline-cell {
  background: #FAFAFA;
  font-weight: 600;
  width: 28%;
}
table.signature-table td.name-cell    { width: 22%; }
table.signature-table td.date-cell    { width: 18%; }
table.signature-table td.signature-cell { width: 32%; }

.signature-page .sig-footnote {
  margin-top: 6mm;
  padding-top: 3mm;
  border-top: 1px solid var(--gray-light);
  font-size: 9.5pt;
  color: var(--gray-mid);
  font-style: italic;
  line-height: 1.6;
}

/* ============================================
   SECTION 2ב — CAD-evidence section (Phase 7.1)
   Visual identity: blue accent (vs red/amber for sidecar). Signals
   "geometric source of truth from the planning authority's own CAD."
   ============================================ */
.cad-chapter { page-break-before: always; }
.cad-chapter .chapter-intro {
  margin-bottom: 4mm;
}
.cad-chapter .cad-provenance {
  margin-bottom: 6mm;
  padding: 4mm 5mm;
  background: #EFF4FA;
  border-right: 3px solid #1E5AA8;
  border-radius: 2px;
  font-size: 9.5pt;
  color: #294F7D;
  line-height: 1.55;
}
.cad-card {
  margin: 6mm 0;
  padding: 6mm 7mm;
  border: 1px solid var(--gray-light);
  border-right: 4px solid #1E5AA8;  /* CAD-blue */
  border-radius: 4px;
  background: #F7FAFD;
  page-break-inside: avoid;
}
.cad-card .cad-head {
  font-size: 12pt;
  font-weight: 700;
  color: #1E5AA8;
  margin-bottom: 2mm;
}
.cad-card .cad-meta {
  font-size: 9.5pt;
  color: var(--gray-mid);
  margin-bottom: 3mm;
}
.cad-card .cad-reasoning {
  font-size: 10.5pt;
  color: var(--gray-dark);
  line-height: 1.55;
  margin-bottom: 4mm;
}
table.cad-missing-plots {
  width: 100%;
  border-collapse: collapse;
  margin-top: 3mm;
  direction: rtl;
}
table.cad-missing-plots th {
  background: #E6EDF6;
  border: 1px solid #BCCBE0;
  padding: 2mm 3mm;
  font-size: 10pt;
  font-weight: 700;
  color: #1E5AA8;
  text-align: right;
}
table.cad-missing-plots td {
  border: 1px solid #D8E1ED;
  padding: 2mm 3mm;
  font-size: 10pt;
  color: var(--gray-dark);
  text-align: right;
}
table.cad-missing-plots td.cellno-cell {
  font-weight: 700;
  width: 12%;
}
table.cad-missing-plots td.code-cell {
  width: 18%;
  color: var(--gray-mid);
  font-variant-numeric: tabular-nums;
}
table.cad-missing-plots td.area-cell {
  width: 24%;
  font-variant-numeric: tabular-nums;
}

/* ============================================
   SECTION 2ג — Chatakhim (cross-section) height-audit findings (Phase 7.2)
   Visual identity: purple accent (#5D3A9B border + lavender background)
   distinct from 2א (red/amber sidecars) and 2ב (blue CAD).
   ============================================ */
.chat-chapter { page-break-before: always; }
.chat-chapter .chapter-intro { margin-bottom: 4mm; }
.chat-chapter .chat-provenance {
  margin-bottom: 6mm;
  padding: 4mm 5mm;
  background: #F3EEFA;
  border-right: 3px solid #5D3A9B;
  border-radius: 2px;
  font-size: 9.5pt;
  color: #3B2666;
  line-height: 1.55;
}
.chat-card {
  margin: 6mm 0;
  padding: 6mm 7mm;
  border: 1px solid var(--gray-light);
  border-right: 4px solid #5D3A9B;
  border-radius: 4px;
  background: #FAF7FE;
  page-break-inside: avoid;
}
.chat-card.chat-ceiling { border-right-color: #B71C1C; background: #FDF5F5; }
.chat-card.chat-consistency { border-right-color: #B8651A; background: #FFFAF0; }
.chat-card.chat-clean { border-right-color: #2E7D32; background: #F2FAF4; }
.chat-card .chat-head {
  font-size: 12pt;
  font-weight: 700;
  color: #3B2666;
  margin-bottom: 2mm;
}
.chat-card.chat-ceiling .chat-head { color: #B71C1C; }
.chat-card.chat-consistency .chat-head { color: #B8651A; }
.chat-card.chat-clean .chat-head { color: #2E7D32; }
.chat-card .chat-meta {
  font-size: 9.5pt;
  color: var(--gray-mid);
  margin-bottom: 3mm;
}
.chat-card .chat-reasoning {
  font-size: 10.5pt;
  color: var(--gray-dark);
  line-height: 1.55;
  margin-bottom: 4mm;
}
table.chat-values {
  width: 100%;
  border-collapse: collapse;
  margin-top: 3mm;
  direction: rtl;
  table-layout: fixed;
}
table.chat-values th {
  background: #ECE3F6;
  border: 1px solid #C8B6E0;
  padding: 2mm 3mm;
  font-size: 10pt;
  font-weight: 700;
  color: #3B2666;
  text-align: right;
}
table.chat-values td {
  border: 1px solid #DCD0EC;
  padding: 2mm 3mm;
  font-size: 10pt;
  color: var(--gray-dark);
  text-align: right;
}
table.chat-values td.elev-cell {
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  width: 22%;
}
table.chat-values td.elev-cell.over-ceiling { color: #B71C1C; }
table.chat-values td.page-cell { width: 18%; }
table.chat-values td.context-cell { color: var(--gray-mid); font-size: 9.5pt; }

/* ============================================
   SECTION 3.N — AMENITY INVENTORY (Phase 7.4, Architecture C)
   No accent — inherits §3 styling. Soft policy, no verdicts.
   ============================================ */
.amen-subsection .amen-provenance,
.amen-subsection .amen-coverage,
.amen-subsection .amen-note {
  font-size: 9.5pt;
  color: var(--gray-mid);
  line-height: 1.6;
  margin: 0 0 3mm 0;
}
.amen-subsection .amen-note {
  font-style: italic;
}
table.amen-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 4mm;
  direction: rtl;
  font-size: 9pt;
}
table.amen-table th {
  background: var(--gray-bg);
  border: 1px solid var(--gray-light);
  padding: 2mm 2.5mm;
  font-weight: 700;
  color: var(--gray-dark);
  text-align: right;
  vertical-align: middle;
}
table.amen-table td {
  border: 1px solid var(--gray-light);
  padding: 2mm 2.5mm;
  vertical-align: middle;
  text-align: right;
}
table.amen-table td.amen-name-cell { font-weight: 600; width: 18%; }
table.amen-table th.amen-plot-cell,
table.amen-table td.amen-plot-cell { width: 8%; text-align: center; }
table.amen-table td.amen-anchor-cell { width: 18%; font-size: 8.5pt; color: var(--gray-mid); }
table.amen-table td.amen-note-cell   { width: 18%; font-size: 8.5pt; color: var(--gray-mid); }
table.amen-table td.amen-yes  { color: var(--green-brand); font-weight: 600; text-align: center; }
table.amen-table td.amen-no   { color: var(--gray-mid); text-align: center; font-size: 11pt; }
table.amen-table td.amen-na   { color: var(--gray-light); text-align: center; font-style: italic; }
table.amen-table .amen-raw {
  display: block;
  color: var(--gray-mid);
  font-size: 8pt;
  font-weight: 400;
  margin-top: 0.5mm;
}

/* §4 amenity-clarification block — soft, not a violation */
.amen-clarification {
  margin: 3mm 0;
  padding: 5mm 6mm;
  background: #F4FAF6;
  border-right: 3px solid var(--gray-mid);
  border-radius: 2px;
  font-size: 10pt;
  color: var(--gray-dark);
  line-height: 1.7;
  white-space: pre-line;
}

/* ============================================
   APPENDIX A passing-rules summary (M6 Phase 6.D)
   ============================================ */
.passing-summary {
  margin-top: 10mm;
  padding: 5mm 6mm;
  background: #F4FAF6;
  border-right: 3px solid var(--green-brand);
  border-radius: 2px;
  page-break-inside: avoid;
}
.passing-summary-head {
  font-size: 11pt;
  font-weight: 700;
  color: var(--green-dark);
  margin: 0 0 3mm 0;
}
ul.passing-summary-list {
  margin: 0;
  padding-right: 6mm;
  font-size: 10pt;
  color: var(--gray-dark);
  line-height: 1.6;
  column-count: 2;
  column-gap: 10mm;
}
ul.passing-summary-list li {
  margin-bottom: 1mm;
  break-inside: avoid;
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

/* ============================================
   PHASE 7.5 — INTEGRATED COVER (cover + signatures + structural note)
   Replaces the old full-bleed dark-green cover + separate signature page.
   Top band stays dark-green (brand). Lower body is white and holds the
   meta table, structural note, and the 10-row signature table.
   ============================================ */
.cover-v2 {
  page: cover;
  width: 210mm;
  height: 297mm;
  margin: 0;
  padding: 0;
  page-break-after: always;
  position: relative;
}
.cover-v2 .cover-band {
  background: #005030;
  color: #fff;
  padding: 18mm 22mm 12mm 22mm;
  position: relative;
}
.cover-v2 .cover-band .logo {
  position: absolute;
  top: 12mm;
  right: 22mm;
  height: 18mm;
  width: auto;
}
.cover-v2 .cover-band .brand-eyebrow {
  font-size: 9.5pt;
  color: rgba(255,255,255,0.72);
  margin-bottom: 1mm;
}
.cover-v2 .cover-band .brand-name {
  font-size: 15pt;
  font-weight: 700;
  margin: 0 0 7mm 0;
}
.cover-v2 .cover-band hr.rule {
  border: none;
  border-top: 1px solid rgba(255,255,255,0.22);
  margin: 4mm 0 5mm 0;
}
.cover-v2 .cover-band .title {
  font-size: 28pt;
  font-weight: 700;
  color: #fff;
  line-height: 1.15;
  margin: 0 0 3mm 0;
}
.cover-v2 .cover-band .subtitle {
  font-size: 12pt;
  color: rgba(255,255,255,0.92);
  line-height: 1.4;
  margin-bottom: 1mm;
}
.cover-v2 .cover-band .pill {
  display: inline-block;
  margin-top: 4mm;
  padding: 1.5mm 6mm;
  border: 1px solid rgba(255,255,255,0.45);
  border-radius: 30px;
  background: rgba(255,255,255,0.06);
  color: #fff;
  font-size: 10pt;
}
.cover-v2 .cover-body {
  padding: 8mm 22mm 14mm 22mm;
  color: #1a1a1a;
}
.cover-v2 .cover-meta {
  font-size: 10.5pt;
  line-height: 1.7;
  color: var(--gray-dark);
  margin-bottom: 5mm;
}
.cover-v2 .cover-meta .label {
  color: var(--gray-mid);
  display: inline-block;
  min-width: 36mm;
  font-weight: 700;
}
.cover-v2 .cover-note {
  padding: 3.5mm 5mm;
  background: #F4FAF6;
  border-right: 3px solid var(--green-brand);
  border-radius: 2px;
  font-size: 9.5pt;
  color: var(--gray-dark);
  line-height: 1.6;
  margin-bottom: 6mm;
}
.cover-v2 .cover-sig-title {
  font-size: 12pt;
  font-weight: 700;
  color: var(--green-dark);
  margin: 0 0 2mm 0;
}
.cover-v2 .cover-sig-sub {
  font-size: 9.5pt;
  color: var(--gray-mid);
  margin: 0 0 3mm 0;
  line-height: 1.5;
}
.cover-v2 table.signature-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
.cover-v2 table.signature-table th {
  background: var(--gray-bg);
  border: 1px solid var(--gray-light);
  padding: 1.5mm 4mm;
  font-size: 10pt;
  font-weight: 700;
  color: var(--gray-dark);
  text-align: right;
}
.cover-v2 table.signature-table td {
  border: 1px solid var(--gray-light);
  padding: 1mm 4mm;
  font-size: 10pt;
  color: var(--gray-dark);
  vertical-align: middle;
  height: 8.5mm;
}
.cover-v2 table.signature-table td.discipline-cell {
  background: #FAFAFA;
  font-weight: 600;
  width: 28%;
}
.cover-v2 table.signature-table td.name-cell      { width: 22%; }
.cover-v2 table.signature-table td.date-cell      { width: 18%; }
.cover-v2 table.signature-table td.signature-cell { width: 32%; }

/* ============================================
   PHASE 7.5 — ARCHITECT SUMMARY FRONT-MATTER (pages 2-N)
   Three category pages (חסר / תיקונים / הבהרות) + map.
   Each item links to a detail anchor via <a href="#sec-...">; WeasyPrint
   converts these into PDF internal navigation. Page-numbers next to each
   link come from CSS target-counter (same mechanism the TOC uses).
   ============================================ */
.summary-page {
  page-break-before: always;
  page-break-after: always;
  direction: rtl;
  text-align: right;
}
.summary-page .summary-eyebrow {
  font-size: 9.5pt;
  color: var(--gray-mid);
  margin-bottom: 4mm;
  padding-bottom: 2mm;
  border-bottom: 1px solid var(--gray-light);
}
.summary-page h2.summary-title {
  font-size: 22pt;
  font-weight: 700;
  color: var(--green-dark);
  margin: 0 0 3mm 0;
  line-height: 1.2;
}
.summary-page .summary-intro {
  font-size: 10.5pt;
  color: var(--gray-dark);
  margin-bottom: 6mm;
  line-height: 1.6;
}
ol.summary-items {
  list-style: none;
  padding: 0;
  margin: 0;
}
/* M7.5.1: items render as a clean numbered list — no severity colored
   accents, no sev-tag, no item ID prefix. Severity field still controls
   within-category sort order (set by the inventory parser, not the CSS). */
ol.summary-items > li {
  margin-bottom: 2.5mm;
  padding: 2.5mm 5mm 2.5mm 5mm;
  background: var(--bg-callout);
  border-radius: 2px;
  page-break-inside: avoid;
}
ol.summary-items > li .item-head {
  margin-bottom: 0.5mm;
}
ol.summary-items > li .seq-num {
  display: inline-block;
  font-size: 11pt;
  font-weight: 700;
  color: var(--green-dark);
  vertical-align: middle;
  min-width: 6mm;
}
ol.summary-items > li .item-text {
  font-size: 9.5pt;
  color: var(--gray-dark);
  line-height: 1.55;
  margin: 0 0 1.5mm 0;
}
ol.summary-items > li a.item-link {
  font-size: 9pt;
  color: var(--gray-mid);
  text-decoration: underline;
  font-weight: 400;
}
/* Map page */
.summary-page table.summary-map {
  width: 100%;
  border-collapse: collapse;
  margin: 4mm 0 8mm 0;
}
.summary-page table.summary-map th,
.summary-page table.summary-map td {
  padding: 3mm 4mm;
  border: 1px solid var(--gray-light);
  font-size: 10pt;
  text-align: right;
  vertical-align: middle;
}
.summary-page table.summary-map th {
  background: var(--gray-bg);
  font-weight: 700;
  color: var(--gray-dark);
}
.summary-page table.summary-map td.cat-cell { width: 65%; }
.summary-page table.summary-map td.count-cell {
  text-align: center;
  font-weight: 700;
  width: 18mm;
  font-variant-numeric: tabular-nums;
}
.summary-page table.summary-map tr.total-row td {
  background: #FAFAFA;
  font-weight: 700;
}
.summary-page h3.summary-subhead {
  font-size: 13pt;
  font-weight: 700;
  color: var(--green-dark);
  margin: 8mm 0 3mm 0;
}
.summary-page ul.summary-legend {
  list-style: none;
  padding: 0;
  margin: 0;
  font-size: 10pt;
  color: var(--gray-dark);
  line-height: 2.0;
}
.summary-page ul.summary-legend .sev-dot {
  display: inline-block;
  width: 4mm;
  height: 4mm;
  border-radius: 50%;
  margin-left: 3mm;
  vertical-align: middle;
}
.summary-page ul.summary-legend .sev-dot.sev-high   { background: var(--red); }
.summary-page ul.summary-legend .sev-dot.sev-medium { background: var(--amber); }
.summary-page ul.summary-legend .sev-dot.sev-low    { background: var(--gray-mid); }
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

    # Determine presence of M4 sidecar + M5 coverage data first, so TOC reflects them.
    all_sidecar_findings = (
        (audit_results.get("m4_summary") or {}).get("sidecar_only_findings") or []
    )
    # Phase 7.1: split CAD-evidence findings out of the standard 2א sidecar list
    # — they get their own section 2ב with a distinct visual identity (blue
    # accent, CAD-provenance explainer).
    # Phase 7.2: chatakhim-evidence findings get their own section 2ג (purple).
    cad_findings = [f for f in all_sidecar_findings if f.get("source_type") == "cad_evidence"]
    chatakhim_findings = [f for f in all_sidecar_findings if f.get("source_type") == "chatakhim_evidence"]
    sidecar_findings = [
        f for f in all_sidecar_findings
        if f.get("source_type") not in ("cad_evidence", "chatakhim_evidence")
    ]
    # Phase 7.4 — amenity inventory (Architecture C, soft policy, rendered as §3.11)
    amenity_inventory = (audit_results.get("m4_summary") or {}).get("amenity_inventory")
    coverage_report = _load_coverage_report(output_path)
    # Phase 7.5 Step 1 — architect summary front-matter (categorized inventory)
    architect_summary = _load_architect_summary(output_path)

    parts: list[str] = []
    # Phase 7.5: cover now carries the signature table (separate sig page dropped).
    parts.append(_render_cover_with_signatures(meta, submission_metadata, plan_number))
    # Phase 7.5: architect summary front-matter (חסר / תיקונים / הבהרות / map)
    if architect_summary:
        parts.append(_render_architect_summary_pages(architect_summary))
    parts.append(_render_toc(
        plan_number, residential_parcels, discipline_results,
        has_sidecar=bool(sidecar_findings),
        has_cad=bool(cad_findings),
        has_chatakhim=bool(chatakhim_findings),
        has_section_5=bool(coverage_report),
        has_amenity_inventory=bool(amenity_inventory),
    ))
    parts.append(_render_section_1())
    parts.append(_render_section_2(content_results, residential_parcels, plan_number))
    if sidecar_findings:
        parts.append(_render_sidecar_section(sidecar_findings))
    if cad_findings:
        parts.append(_render_cad_section(cad_findings))
    if chatakhim_findings:
        parts.append(_render_chatakhim_section(chatakhim_findings))
    parts.append(_render_section_3(discipline_results, amenity_inventory=amenity_inventory))
    parts.append(_render_section_4(content_results, discipline_results, format_results,
                                    residential_parcels=residential_parcels,
                                    amenity_inventory=amenity_inventory))
    if coverage_report:
        parts.append(_render_section_5_coverage(coverage_report))
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
    # M7.5.1 — defensive belt-and-braces: rewrite any remaining "§" to "סעיף "
    # in the assembled HTML before WeasyPrint sees it. Catches stray clause
    # refs from upstream JSON or future code that forgot the source-level fix.
    html_str = _normalize_he_text(html_str)
    from weasyprint import HTML, CSS as WeasyCSS
    from weasyprint.text.fonts import FontConfiguration
    font_config = FontConfiguration()
    base = str(FONT_DIR) + "/"
    HTML(string=html_str, base_url=base).write_pdf(
        str(output_path),
        stylesheets=[WeasyCSS(string=_CSS, base_url=base, font_config=font_config)],
        font_config=font_config,
    )


# M7.5.1 — § → סעיף normalize.  Architect can't accept § (regulatory section
# symbol) in the document; this helper rewrites every occurrence to "סעיף ".
# Source-level fixes were applied in 5 modules; this is the belt-and-braces.
_SECTION_SIGN_RE = re.compile(r"§\s*")


def _normalize_he_text(text: str) -> str:
    """Replace every '§' (with optional trailing space) with 'סעיף '."""
    if not text or "§" not in text:
        return text
    return _SECTION_SIGN_RE.sub("סעיף ", text)


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
# Signature page — sits between cover and TOC (Fix 10)
# ─────────────────────────────────────────────────────────────────────────────

# Ordered list of the 10 disciplines that must sign the חוות דעת.
# Order is intentional (operational → strategic → executive) and matches what
# the מינהלת sends for routing.
_SIGNATURE_DISCIPLINES_HE: list[str] = [
    'שפ"ע',
    "כבישים ופיתוח",
    "תנועה",
    "ניקוז",
    "גנים ונוף",
    "אדריכלות",
    "תאגיד",
    "מינהלת ההתחדשות העירונית",
    "מהנדס העיר",
    'יו"ר הוועדה',
]


def _render_signature_page() -> str:
    rows = "".join(
        f"""
        <tr>
          <td class="discipline-cell">{_esc(disc)}</td>
          <td class="name-cell"></td>
          <td class="date-cell"></td>
          <td class="signature-cell"></td>
        </tr>"""
        for disc in _SIGNATURE_DISCIPLINES_HE
    )
    return f"""
    <div class="signature-page">
      <div class="eyebrow">{_esc(EYEBROW)}</div>
      <h1 class="sig-title">טבלת חתימות — חוות דעת רב-תחומית</h1>
      <p class="sig-subtitle">לאישור הדוח על-ידי בעלי התפקידים במינהלת ההתחדשות העירונית בעיריית נס ציונה.</p>
      <table class="signature-table">
        <thead>
          <tr>
            <th>דיסציפלינה</th>
            <th>שם</th>
            <th>תאריך</th>
            <th>חתימה</th>
          </tr>
        </thead>
        <tbody>{rows}
        </tbody>
      </table>
      <p class="sig-footnote">כל חתימה מעידה על סקירת הדוח על-ידי הדיסציפלינה המתאימה והסכמתה לממצאים המוצגים.</p>
    </div>
    """


# ─────────────────────────────────────────────────────────────────────────────
# Phase 7.5 Step 1 — INTEGRATED COVER + SIGNATURES (page 1)
# Replaces _render_cover() + _render_signature_page() in the parts list.
# The old functions are retained for reference but no longer called from
# generate_audit_pdf().
# ─────────────────────────────────────────────────────────────────────────────

_COVER_STRUCTURAL_NOTE_HE = (
    "מסמך זה מחולק לשניים: בעמודים הראשונים — סיכום פעולות נדרשות מהאדריכל לפי "
    "קטגוריות (חסר / תיקונים / הבהרות). לאחר מכן — דוח מקצועי מפורט עם הממצאים "
    "והאסמכתאות. פריטים בסיכום מקושרים — לחיצה על פריט תעביר אותך לסעיף המתאים בדוח."
)


def _render_cover_with_signatures(
    meta: dict, submission_metadata: dict, plan_number: str,
) -> str:
    """Single-page cover that combines brand band + meta + structural note +
    signature table. Replaces the old full-bleed cover + separate sig page.
    """
    version = submission_metadata.get("submission_version", "")
    sub_date = submission_metadata.get("submission_date", "")
    sub_month_year = _sub_month_year_he(sub_date)
    architect_full = (meta.get("architect_of_record") or "").strip()
    architect_short = _format_architect_short(architect_full)
    approval_label = _approval_label(meta)

    sig_rows = "".join(
        f'<tr>'
        f'<td class="discipline-cell">{_esc(disc)}</td>'
        f'<td class="name-cell"></td>'
        f'<td class="date-cell"></td>'
        f'<td class="signature-cell"></td>'
        f'</tr>'
        for disc in _SIGNATURE_DISCIPLINES_HE
    )

    return f"""
    <div class="cover-v2">
      <div class="cover-band">
        <img class="logo" src="../nessziona_logo.png" alt="">
        <div class="brand-eyebrow">NZC | מינהלת ההתחדשות העירונית</div>
        <div class="brand-name">נס ציונה</div>
        <hr class="rule">
        <h1 class="title">סקירת תוכנית עיצוב</h1>
        <div class="subtitle">תכנית בינוי ופיתוח — מתחם הטייסים-ההסתדרות</div>
        <div class="subtitle">תכנית עיצוב גרסה {_esc(version)} · {_esc(sub_month_year)}</div>
        <div class="pill">{_esc(DOC_TYPE_LABEL)}</div>
      </div>
      <div class="cover-body">
        <div class="cover-meta">
          <div><span class="label">תכנית סטטוטורית:</span> {_esc(plan_number)} {_esc(approval_label)}</div>
          <div><span class="label">עורך התכנית:</span> אדריכלים {_esc(architect_short)}</div>
          <div><span class="label">תאריך הסקירה:</span> {_today_he()}</div>
        </div>
        <div class="cover-note">{_esc(_COVER_STRUCTURAL_NOTE_HE)}</div>
        <h2 class="cover-sig-title">טבלת חתימות — חוות דעת רב-תחומית</h2>
        <p class="cover-sig-sub">לאישור הדוח על-ידי בעלי התפקידים במינהלת ההתחדשות העירונית בעיריית נס ציונה.</p>
        <table class="signature-table">
          <thead>
            <tr>
              <th>דיסציפלינה</th>
              <th>שם</th>
              <th>תאריך</th>
              <th>חתימה</th>
            </tr>
          </thead>
          <tbody>{sig_rows}</tbody>
        </table>
      </div>
    </div>
    """


# ─────────────────────────────────────────────────────────────────────────────
# Phase 7.5 Step 1 — ARCHITECT SUMMARY FRONT-MATTER (pages 2-N)
# Reads inventory JSON written by vision_scanner.parsers.architect_summary_inventory.
# Each item renders as a card with severity tag + ID + one-line text + link.
# Links use <a href="#sec-...">; CSS target-counter inserts the page number.
# ─────────────────────────────────────────────────────────────────────────────

_SEVERITY_LABELS_HE: dict[str, str] = {
    "high":   "דחיפות גבוהה",
    "medium": "דחיפות בינונית",
    "low":    "דחיפות נמוכה",
}


def _load_architect_summary(pdf_output_path: Path) -> dict | None:
    """Load architect_summary_inventory.json from the submission's data dir.

    Same path resolution as _load_coverage_report — the PDF lives in
    audit_outputs/{plan}/v{ver}/ but the inventory JSON lives in
    data/projects/{plan}/submissions/v{ver}/.
    """
    try:
        v_dir = pdf_output_path.parent
        plan = v_dir.parent.name
        ver = v_dir.name
        repo_root = v_dir.parent.parent.parent
        candidate = (
            repo_root / "data" / "projects" / plan / "submissions" / ver
            / "architect_summary_inventory.json"
        )
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _render_architect_summary_pages(summary: dict) -> str:
    """Render the architect summary front-matter — one page per category plus
    a final map page."""
    items_by_cat = summary.get("items_by_category", {}) or {}
    category_order = summary.get("category_order", ["MISSING", "FIX", "CLARIFY"])
    cat_labels = summary.get("category_labels_he", {})
    cat_intros = summary.get("category_intros_he", {})
    counts = summary.get("counts", {})

    pages: list[str] = []
    for cat in category_order:
        items = items_by_cat.get(cat) or []
        if not items:
            continue
        pages.append(
            _render_summary_category_page(
                cat,
                cat_labels.get(cat, cat),
                cat_intros.get(cat, ""),
                items,
            )
        )
    # Phase 7.5 Step 1 follow-up (Lior decision post-spike): map page dropped.
    # _render_summary_map_page() is intentionally retained below but no longer
    # called — kept for a possible future stats/summary layout per Ellen.
    return "".join(pages)


def _render_summary_category_page(
    cat: str, label_he: str, intro_he: str, items: list[dict],
) -> str:
    """One page per category. Items inherit category ordering from inventory
    (already sorted by severity then id) — we don't re-sort here.

    M7.5.1 polish:
      - severity label/colored accent dropped from render (severity still
        controls within-category sort order via the inventory parser)
      - item ID (M01/F02/C01...) dropped from render — replaced with a per-
        category sequence number (1, 2, ..., N).  IDs remain in the JSON
        as record keys for future anchor use.
      - page reference replaced with simple "לפרטים נוספים" hyperlink to
        the detail-content anchor.
    """
    lis: list[str] = []
    for seq, item in enumerate(items, start=1):
        anchor = (item.get("anchor_target_id") or "").strip()
        text = item.get("one_line_he") or ""
        item_id = item.get("id") or ""
        link_html = ""
        if anchor:
            link_html = (
                f'<a class="item-link" href="#{_esc(anchor)}">לפרטים נוספים</a>'
            )
        # data-item-id preserves the internal ID on the rendered HTML for
        # future anchor use without surfacing it to the architect.
        lis.append(f"""
        <li data-item-id="{_esc(item_id)}">
          <div class="item-head">
            <span class="seq-num">{seq}.</span>
          </div>
          <p class="item-text">{_esc(text)}</p>
          {link_html}
        </li>""")

    return f"""
    <div class="summary-page" id="summary-{_esc(cat.lower())}">
      <div class="summary-eyebrow">{_esc(EYEBROW)}</div>
      <h2 class="summary-title">{_esc(label_he)}</h2>
      <p class="summary-intro">{_esc(intro_he)}</p>
      <ol class="summary-items">{''.join(lis)}</ol>
    </div>
    """


def _render_summary_map_page(
    category_order: list[str], cat_labels: dict, counts: dict,
) -> str:
    rows: list[str] = []
    total = 0
    for cat in category_order:
        n = int(counts.get(cat) or 0)
        total += n
        label = cat_labels.get(cat, cat)
        rows.append(
            f'<tr>'
            f'<td class="cat-cell">{_esc(label)}</td>'
            f'<td class="count-cell">{n}</td>'
            f'</tr>'
        )
    rows.append(
        f'<tr class="total-row">'
        f'<td class="cat-cell">סה״כ פעולות נדרשות</td>'
        f'<td class="count-cell">{total}</td>'
        f'</tr>'
    )
    intro = (
        f"סיכום מספרי של {total} הפעולות הנדרשות מהאדריכל, מחולקות לשלוש קטגוריות. "
        "כל פעולה מפורטת בעמודים הקודמים וכוללת קישור לסעיף המתאים בדוח המפורט. "
        "סדר הפעולות בכל קטגוריה — לפי דחיפות."
    )
    return f"""
    <div class="summary-page" id="summary-map">
      <div class="summary-eyebrow">{_esc(EYEBROW)}</div>
      <h2 class="summary-title">מפת פעולות נדרשות</h2>
      <p class="summary-intro">{_esc(intro)}</p>
      <table class="summary-map">
        <thead><tr><th>קטגוריה</th><th class="count-cell">מס׳ פריטים</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
      <h3 class="summary-subhead">דירוג דחיפות</h3>
      <ul class="summary-legend">
        <li><span class="sev-dot sev-high"></span> דחיפות גבוהה — נדרש לפני ההגשה הבאה</li>
        <li><span class="sev-dot sev-medium"></span> דחיפות בינונית — להשלמה לקראת הסקירה הבאה</li>
        <li><span class="sev-dot sev-low"></span> דחיפות נמוכה — להשלמה לפני הסקירה הסופית</li>
      </ul>
    </div>
    """


# ─────────────────────────────────────────────────────────────────────────────
# TOC — table-based, target-counter for page numbers
# ─────────────────────────────────────────────────────────────────────────────

def _render_toc(plan_number: str, residential_parcels: list[dict],
                discipline_results: list[dict],
                *,
                has_sidecar: bool = False,
                has_cad: bool = False,
                has_chatakhim: bool = False,
                has_section_5: bool = False,
                has_amenity_inventory: bool = False) -> str:
    rows: list[str] = []
    rows.append(_toc_row("1.", "ניתוח תכנון עירוני", "#sec-1", "main"))
    rows.append(_toc_row("2.", f'בדיקת תאימות תוכן לתב"ע {plan_number}', "#sec-2", "main"))
    for i, p in enumerate(residential_parcels, start=1):
        rows.append(_toc_row(f"2.{i}", _parcel_label_he(p), f"#sec-2-{i}", "sub"))
    pw_idx = len(residential_parcels) + 1
    rows.append(_toc_row(f"2.{pw_idx}", "בדיקות ברמת תכנית", f"#sec-2-{pw_idx}", "sub"))

    # M4: 2א sidecar (only when m4 enrichment present)
    if has_sidecar:
        rows.append(_toc_row("2א.", "ממצאי בדיקה ויזואלית נוספים", "#sec-m4-sidecar", "main"))
    # Phase 7.1: 2ב CAD-evidence section (only when CAD findings present)
    if has_cad:
        rows.append(_toc_row("2ב.", 'ממצאי בדיקה מבוססת תשריט CAD', "#sec-cad", "main"))
    # Phase 7.2: 2ג chatakhim height audit (only when chatakhim findings present)
    if has_chatakhim:
        rows.append(_toc_row("2ג.", 'ממצאי בדיקת חתכים — אימות גבהים מוחלטים', "#sec-chat", "main"))

    rows.append(_toc_row("3.", "בדיקה רב-תחומית לפי חוברת הנחיות עירונית", "#sec-3", "main"))
    seen = set()
    disc_i = 0
    for code in DISCIPLINE_ORDER:
        if any(r.get("discipline") == code for r in discipline_results) and code not in seen:
            disc_i += 1
            seen.add(code)
            rows.append(_toc_row(f"3.{disc_i}", DISCIPLINE_NAME_HE[code],
                                  f"#sec-3-{disc_i}", "sub"))
    # Phase 7.4: amenity inventory as §3.{N+1} (only when present)
    if has_amenity_inventory:
        amenity_idx = disc_i + 1
        rows.append(_toc_row(f"3.{amenity_idx}", "שירותים לדיירים",
                              "#sec-3-amenities", "sub"))

    rows.append(_toc_row("4.", "סיכום וממצאים סופיים", "#sec-4", "main"))
    # M5: section 5 coverage transparency (only when coverage_report.json present)
    if has_section_5:
        rows.append(_toc_row("5.", "היקף הבדיקה האוטומטית", "#sec-5", "main"))
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
    # Phase 7.5 Step 2 — rewritten as a report-wide architect-facing abstract.
    # Previously claimed "ארבעה פרקים" (legacy from the original cover abstract,
    # itself now removed by the Step 1 cover restructure). Honestly enumerates
    # the three regulation layers checked and the five main report sections.
    intro = (
        'דוח זה הוא סקירה של תוכנית עיצוב גרסה 24.3 אל מול שלוש שכבות הרגולציה '
        'הרלוונטיות: תקנון התב"ע (בדיקה מספרית פר-תא שטח), חוברת ההנחיות '
        'העירוניות (בדיקה רב-תחומית בעשר דיסציפלינות), ותשריט הקובץ הסטטוטורי '
        'בקבצי CAD (בדיקה גיאומטרית של תאי שטח וגבהים מוחלטים). מבנה הדוח: '
        'פרק 2 — תאימות תוכן פר-תא שטח, כולל תתי-פרקים 2א (בדיקה ויזואלית של '
        'מסמכי ההגשה), 2ב (תשריט CAD) ו-2ג (אימות גבהים מחתכים וחזיתות). פרק 3 '
        '— בדיקה רב-תחומית עם תת-פרק 3.11 (מלאי שירותים לדיירים). פרק 4 — סיכום '
        'הפעולות הנדרשות. פרק 5 — שקיפות כיסוי הבדיקה האוטומטית. נספח א — '
        'ליקויי פורמט בחוברת ההגשה.'
    )
    return f"""
    <div class="chapter" id="sec-1">
      {_chapter_open("1", "ניתוח תכנון עירוני", intro)}
      <div class="callout">
        <div class="callout-title">פרק זה דורש השלמה ידנית של מהנדס/ת המינהלת</div>
        <p class="callout-body">הניתוח התכנוני האיכותי של פרק 1 (שילוב במרקם הקיים, השפעות
          תנועה, איכות שצ"פ ומבני ציבור, חזות) אינו ניתן לאוטומציה ומחייב שיפוט מקצועי.
          ההשלמה תתבצע על-ידי מהנדס/ת הוועדה לפני הפיכת הדוח לחוות דעת רשמית.</p>
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
    # M4: confidence chip — surfaces only when the engine output's confidence
    # has been overridden to MEDIUM or LOW by M4 (means a Pro vision finding
    # drove the verdict with less than full certainty).
    conf_chip = _confidence_chip_html(r.get("confidence"))
    return {
        "label": label,
        "verdict_html": f'<span class="{vclass}">{vlabel}</span>{conf_chip}',
        "submission": sub_display,
        "schema": schema_display,
        "note_html": f'{_esc(note)}{feedback}',
    }


def _confidence_chip_html(confidence: str | None) -> str:
    """Render the M4 confidence chip when needed. HIGH (or missing) → empty."""
    c = (confidence or "").upper()
    if c not in ("MEDIUM", "LOW"):
        return ""
    cls = "conf-medium" if c == "MEDIUM" else "conf-low"
    label = "רמת ביטחון: בינונית" if c == "MEDIUM" else "רמת ביטחון: נמוכה"
    return f'<span class="conf-chip {cls}">{label}</span>'


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
# M4 sidecar section — between §2 and §3 when M4 surfaces findings that
# don't map to any engine rule (e.g. non_compliant items in categories the
# engine doesn't cover: easements, tree preservation, phasing).
# ─────────────────────────────────────────────────────────────────────────────

_SIDECAR_CLAUSE_TITLES_HE: dict[str, str] = {
    "6.5.1":  "נספח עצים בוגרים",
    "6.6.4":  "זיקת הנאה תת-קרקעית מתא שטח 2 לחלקה 12",
    "6.4.2":  'נפח איגום נדרש 450 מ"ק',
    "7.1.1":  "תוכנית שלביות (שלב א/ב)",
    "4.2.2.4": "מעבר להולכי רגל ברוחב 3 מ' בתא שטח 9",
    "4.3.2.2": "רוחב שצ\"פ בתא שטח 7 ≥ 10 מ'",
    "5.table": "טבלת הזכויות וההוראות — מקור הנתונים",
}


def _sidecar_clause_title(clause_id: str) -> str:
    return _SIDECAR_CLAUSE_TITLES_HE.get(clause_id, clause_id)


def _format_clause_ref_he(clause_id: str) -> str:
    """Format a clause reference for display. Slugs like '5.table' get the
    human Hebrew name; numeric clause IDs render as 'סעיף X.Y.Z'."""
    if clause_id == "5.table":
        return 'טבלת הזכויות וההוראות (סעיף 5)'
    return f"סעיף {clause_id}"


def _sidecar_indicator_label(indicator: str) -> str:
    return {
        "non_compliant":           "לא תקין",
        "missing":                 "לא נמצא בהגשה",
        "compliant":               "תקין",
        "requires_review":         "דורש בירור",
        "deferred_to_dwg":         'דורש בדיקה בקובץ DWG',
        # Bug A guard spawns — engine deterministic pass holds, but evidence /
        # provenance signals from M3 critic or M2 deserve מהנדס/ת attention.
        "table_format_concern":    "הערה על מקור הנתונים",
        "m2_provenance_concern":   "הערה על מקור הנתונים",
    }.get(indicator, indicator or "—")


def _render_sidecar_section(sidecar_findings: list[dict]) -> str:
    """Render M4 sidecar findings as a chapter between sections 2 and 3."""
    cards: list[str] = []
    for f in sidecar_findings:
        clause_id = f.get("clause_id") or "—"
        plot = f.get("ta_shetach_takanon")
        plot_label = f"תא שטח {plot}" if plot else "ברמת תכנית"
        indicator = (f.get("compliance_indicator") or "").lower()
        ind_label = _sidecar_indicator_label(indicator)
        title = _sidecar_clause_title(clause_id)
        reasoning = f.get("reasoning") or ""
        pages = f.get("source_pages") or []
        pages_str = ", ".join(str(p) for p in pages) if pages else "—"
        # Amber styling (sidecar-missing class) for "softer" indicators —
        # missing data + provenance concerns. Red (default) stays for
        # non_compliant findings.
        css_extra = (
            "sidecar-missing"
            if indicator in ("missing", "table_format_concern", "m2_provenance_concern")
            else ""
        )
        cards.append(f"""
        <div class="sidecar-card {css_extra}">
          <div class="sidecar-head">{_esc(title)} — {_esc(ind_label)}</div>
          <div class="sidecar-meta">{_esc(_format_clause_ref_he(clause_id))} בתקנון התב"ע · {_esc(plot_label)}</div>
          <div class="sidecar-reasoning">{_esc(reasoning)}</div>
          <div class="sidecar-pages">עמודי הגשה: {_esc(pages_str)}</div>
        </div>
        """)
    intro = (
        "פרק זה מאגד ממצאי בדיקה ויזואלית של מסמכי ההגשה שלא ניתן היה לשלבם כעדכון "
        "של שורת בדיקה קיימת בטבלאות שלעיל — בדרך כלל משום שאין סעיף ייעודי לנושא "
        "במנוע הבדיקה. נדרשת תשומת לב מיוחדת של מהנדס/ת הוועדה לפני אישור ההגשה."
    )
    return f"""
    <div class="chapter sidecar-chapter" id="sec-m4-sidecar">
      <div class="eyebrow">{_esc(EYEBROW)}</div>
      <h2 class="chapter-num-title">2א. ממצאי בדיקה ויזואלית נוספים</h2>
      <p class="chapter-intro">{_esc(intro)}</p>
      {''.join(cards)}
    </div>
    """


# ─────────────────────────────────────────────────────────────────────────────
# Section 2ב — CAD-evidence findings (Phase 7.1)
# These come from direct reading of the planning authority's CAD source files
# (DWG tashrit, EPSG:2039 Israeli ITM). They are the MOST AUTHORITATIVE
# findings the system produces — geometric truth from the system-of-record.
# ─────────────────────────────────────────────────────────────────────────────


_CAD_CLAUSE_TITLES_HE: dict[str, str] = {
    "cad.plot_completeness": 'שלמות תאי שטח לפי תשריט התב"ע',
}


_CAD_INDICATOR_LABELS_HE: dict[str, str] = {
    "non_compliant":   "לא תקין",
    "missing":         "לא נמצא בהגשה",
    "compliant":       "תקין",
    "requires_review": "דורש בירור",
}


def _render_cad_card(finding: dict) -> str:
    clause_id = finding.get("clause_id") or "—"
    indicator = (finding.get("compliance_indicator") or "").lower()
    title = _CAD_CLAUSE_TITLES_HE.get(clause_id, clause_id)
    ind_label = _CAD_INDICATOR_LABELS_HE.get(indicator, indicator or "—")
    reasoning_raw = finding.get("reasoning") or ""

    # The reasoning string from plot_completeness.py contains an inline
    # pseudo-table built with " | " separators (one row per missing plot).
    # If present, split it out so we can render an actual HTML table.
    prose_html = ""
    missing_table_html = ""

    # Prefer the structured `missing_plots` payload if available
    missing = finding.get("missing_plots") or []
    if missing:
        # Strip the inline pseudo-table from the prose to avoid duplication
        prose_lines = []
        for line in reasoning_raw.split("\n"):
            if " | " in line:
                continue
            prose_lines.append(line)
        prose_html = _esc("\n".join(prose_lines).strip())
        rows = "".join(
            f"""
            <tr>
              <td class="cellno-cell">{int(m['cellno'])}</td>
              <td>{_esc(m.get('code_description_he', '—'))}</td>
              <td class="code-cell">{_esc(str(m.get('code', '—')))}</td>
              <td class="area-cell">{float(m.get('area_m2', 0)):,.0f}</td>
            </tr>"""
            for m in sorted(missing, key=lambda x: int(x.get("cellno", 0)))
        )
        missing_table_html = f"""
        <table class="cad-missing-plots">
          <thead>
            <tr>
              <th>תא שטח</th>
              <th>ייעוד</th>
              <th>קוד תב"ע</th>
              <th>שטח קנוני (מ"ר)</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>"""
    else:
        prose_html = _esc(reasoning_raw)

    crs = finding.get("source_crs") or "EPSG:2039"
    return f"""
    <div class="cad-card">
      <div class="cad-head">{_esc(title)} — {_esc(ind_label)}</div>
      <div class="cad-meta">מקור: תשריט התב"ע (קבצי DWG · CRS {_esc(crs)})</div>
      <div class="cad-reasoning">{prose_html}</div>
      {missing_table_html}
    </div>
    """


def _render_cad_section(cad_findings: list[dict]) -> str:
    """Render Phase 7.1 CAD-evidence findings as section 2ב."""
    cards = "".join(_render_cad_card(f) for f in cad_findings)
    intro = (
        "ממצאים אלה מבוססים על קריאה ישירה של תשריט התב\"ע (קבצי DWG "
        "במערכת הקואורדינטות הישראלית EPSG:2039 — ITM). הם הקבילים ביותר "
        "מבחינה תכנונית — מקור הנתון הוא בסיס הרישום הגאומטרי של רשות "
        "התכנון עצמה."
    )
    provenance = (
        'הערכים בטבלאות שלהלן (שטחי תאי השטח, ייעודי הקרקע) חולצו ישירות '
        'מהפוליגונים הגאומטריים של התשריט (חישוב שטח באמצעות Shapely). '
        'תכונת "AREA" המופיעה בבלוקי הטקסט של ה-CAD אינה בשימוש כסמכותית '
        'מאחר שזוהו בה אי-עקביות במספר תאי שטח (ראו לוג פנימי).'
    )
    return f"""
    <div class="chapter cad-chapter" id="sec-cad">
      <div class="eyebrow">{_esc(EYEBROW)}</div>
      <h2 class="chapter-num-title">2ב. ממצאי בדיקה מבוססת תשריט CAD</h2>
      <p class="chapter-intro">{_esc(intro)}</p>
      <div class="cad-provenance">{_esc(provenance)}</div>
      {cards}
    </div>
    """


# ─────────────────────────────────────────────────────────────────────────────
# Section 2ג — Chatakhim (cross-section) height-audit findings (Phase 7.2)
# Derived from the M1 chatakhim_height_parser. Two finding types:
#   - ceiling      → red card (non_compliant): max top elevation > 91 m
#   - consistency  → amber card (requires_review): drawings disagree by >0.5 m
# ─────────────────────────────────────────────────────────────────────────────

# Phase 7.5 Step 2 (Leak 3) — translate the M1 English source_context strings
# to architect-facing Hebrew. The mapping covers every string observed in the
# v24.3 corpus (7 distinct) plus the spec-anticipated variants for forward
# compat. Unmapped strings warn and fall back to the raw English (audit-safe).

import logging as _logging
_chat_logger = _logging.getLogger("report_generator.chatakhim")

_CHAT_CONTEXT_HE_MAP: dict[str, str] = {
    # ── strings observed in v24.3 corpus ──
    "absolute elevation, top of building 5":
        "מפלס מוחלט, ראש מבנה 5",
    "absolute elevation, floor 13, plot 5":
        "מפלס מוחלט, קומה 13, תא שטח 5",
    "absolute elevation, building B4 top (inferred ground = absolute − relative)":
        "מפלס מוחלט, ראש מבנה B4 (קרקע נגזרת = מוחלט − יחסי)",
    "absolute elevation, building B4 ground":
        "מפלס קרקע מוחלט, מבנה B4",
    "absolute ground level elevation for building B4":
        "מפלס קרקע מוחלט, מבנה B4",
    "absolute elevation, building A2 ground":
        "מפלס קרקע מוחלט, מבנה A2",
    "absolute elevation building A2 (inferred ground = absolute − relative)":
        "מפלס מוחלט, מבנה A2 (קרקע נגזרת = מוחלט − יחסי)",
    # ── spec-anticipated variants (forward compat) ──
    "absolute top level elevation for building B4":
        "מפלס מוחלט עליון, מבנה B4",
    "absolute elevation, building B4 top":
        "מפלס מוחלט, ראש מבנה B4",
    "absolute elevation building A2":
        "מפלס מוחלט, מבנה A2",
    "absolute elevation, building A2 top":
        "מפלס מוחלט, ראש מבנה A2",
}


def _translate_chat_context_he(raw: str) -> str:
    """Map an M1 chatakhim source_context string from English to Hebrew.

    On miss: emit a warning and return the original raw string (no silent
    failure — audit can spot unmapped strings in PDF or logs).
    """
    if not raw:
        return ""
    stripped = raw.strip()
    he = _CHAT_CONTEXT_HE_MAP.get(stripped)
    if he is not None:
        return he
    _chat_logger.warning(
        "Unmapped §2ג context string (falling back to English): %r", stripped,
    )
    return stripped


def _render_chatakhim_card(finding: dict) -> str:
    check_type = finding.get("check_type") or "unknown"
    indicator = (finding.get("compliance_indicator") or "").lower()
    building_id = finding.get("building_id")
    plot_id = finding.get("ta_shetach_takanon")
    reasoning = finding.get("reasoning") or ""
    value_list = finding.get("value_list") or []
    ceiling_m = float(finding.get("ceiling_m", 91.0))

    # Color driven by indicator severity, not check type:
    #   non_compliant  → red (chat-ceiling)
    #   requires_review → amber (chat-consistency) — covers reframed plot-level
    #   ceiling and any consistency finding
    #   compliant     → green (chat-clean)
    if indicator == "non_compliant":
        css_extra = "chat-ceiling"
    elif indicator == "requires_review":
        css_extra = "chat-consistency"
    elif indicator == "compliant":
        css_extra = "chat-clean"
    else:
        css_extra = ""

    if check_type in ("ceiling", "ceiling_plot_level"):
        if indicator == "non_compliant":
            title_severity = "חריגה מתקרה מוחלטת"
        else:
            title_severity = "ערכים מעל התקרה — דרושה הבהרת האדריכל"
        title = (
            f"בניין {building_id} — {title_severity}"
            if building_id
            else f"תא שטח {plot_id} — {title_severity} (בניין לא מתויג)"
        )
    elif check_type == "consistency":
        title = f"בניין {building_id} — חוסר עקביות בין תשריטים"
    elif check_type == "ground_reference":
        title = f"מבנה {building_id} — חוסר עקביות בגובה הקרקע המוחלט בין תשריטים"
    else:
        title = finding.get("clause_id") or "ממצא חתכים"

    meta_pieces = []
    if plot_id is not None:
        meta_pieces.append(f"תא שטח {plot_id}")
    if building_id:
        meta_pieces.append(f"מבנה {building_id}")
    if check_type == "ground_reference":
        spread_m = finding.get("spread_m")
        if spread_m is not None:
            meta_pieces.append(f"פער מקסימלי: {float(spread_m):.2f} מ׳")
    else:
        meta_pieces.append(f"תקרת סעיף 6.7: {ceiling_m:.2f} מ׳ מעל פני הים")
    meta = " · ".join(meta_pieces)

    # Value table
    rows = ""
    for v in sorted(value_list, key=lambda x: (x.get("source_page", 0), x.get("elevation_m", 0))):
        elev = float(v.get("elevation_m", 0))
        page = v.get("source_page", "—")
        # Phase 7.5 Step 2 (Leak 3): translate M1 English context to Hebrew.
        raw_ctx = v.get("source_context") or ""
        ctx = _translate_chat_context_he(raw_ctx)[:80]
        over_cls = " over-ceiling" if elev > ceiling_m else ""
        rows += (
            f"<tr>"
            f'<td class="elev-cell{over_cls}">{elev:,.2f} מ׳</td>'
            f'<td class="page-cell">עמ׳ {page}</td>'
            f'<td class="context-cell">{_esc(ctx)}</td>'
            f"</tr>"
        )
    table_html = (
        f"""
        <table class="chat-values">
          <thead>
            <tr><th>גובה מוחלט</th><th>מקור</th><th>הקשר בתשריט</th></tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>"""
        if rows
        else ""
    )

    return f"""
    <div class="chat-card {css_extra}">
      <div class="chat-head">{_esc(title)}</div>
      <div class="chat-meta">{_esc(meta)}</div>
      <div class="chat-reasoning">{_esc(reasoning)}</div>
      {table_html}
    </div>
    """


def _render_chatakhim_section(chatakhim_findings: list[dict]) -> str:
    """Render Phase 7.2 chatakhim-evidence findings as section 2ג.

    If the list is empty (caller guards this), shows a green-tinted summary card.
    Otherwise renders one purple card per ceiling/consistency finding.
    """
    cards = "".join(_render_chatakhim_card(f) for f in chatakhim_findings)

    n_ceiling = sum(
        1 for f in chatakhim_findings
        if f.get("check_type") in ("ceiling", "ceiling_plot_level")
    )
    n_consistency = sum(
        1 for f in chatakhim_findings if f.get("check_type") == "consistency"
    )
    n_ground_ref = sum(
        1 for f in chatakhim_findings if f.get("check_type") == "ground_reference"
    )
    n_total = n_ceiling + n_consistency + n_ground_ref
    summary_he = (
        f"נבדקו {n_total} ממצאים: "
        f"{n_ceiling} חריגות מהתקרה המוחלטת, "
        f"{n_consistency} חוסרי עקביות בין תשריטים, "
        f"{n_ground_ref} חוסרי עקביות בקו האפס."
    )
    intro = (
        "פרק זה מאגד בדיקות גובה מוחלט שחולצו מתשריטי החתכים והחזיתות בהגשה "
        "(עמ׳ 48-51 לחתכים, 52-62 לחזיתות). שלושה סוגי בדיקות:"
        " (1) השוואה מול תקרת סעיף 6.7 לתב\"ע (91 מ׳ מעל פני הים — מגבלת מסלול טיסה, "
        "לא תינתן הקלה);"
        " (2) השוואה בין-מקורית: האם תשריטים שונים של אותו מבנה מציגים את אותו גובה;"
        " (3) עקביות קו אפס: האם תשריטים שונים של אותו מבנה מתייחסים לאותו "
        "קו אפס מוחלט (מעל פני הים)."
    )
    provenance = (
        "הערכים בטבלאות שלהלן חולצו ישירות מהציטוטים הוויזואליים של מספרי-מפלסים "
        "בתשריטי ההגשה (קריאת תוויות אבסולוטיות בלבד; ערכים יחסיים סוננו). "
        "מקור הנתון מצוטט פר ערך בעמודה 'הקשר בתשריט'."
    )
    return f"""
    <div class="chapter chat-chapter" id="sec-chat">
      <div class="eyebrow">{_esc(EYEBROW)}</div>
      <h2 class="chapter-num-title">2ג. ממצאי בדיקת חתכים — אימות גבהים מוחלטים</h2>
      <p class="chapter-intro">{_esc(intro)}</p>
      <div class="chat-provenance">{_esc(provenance)}<br>{_esc(summary_he)}</div>
      {cards}
    </div>
    """


# ─────────────────────────────────────────────────────────────────────────────
# M5 Section 5 — coverage transparency
# ─────────────────────────────────────────────────────────────────────────────

def _load_coverage_report(pdf_output_path: Path) -> dict | None:
    """Look for a coverage_report.json alongside the PDF (in the submission's
    data/ dir, not in audit_outputs/). The PDF is written to
    audit_outputs/{plan}/v{ver}/, but the coverage data lives in
    data/projects/{plan}/submissions/v{ver}/."""
    # Walk up from pdf path; the audit_outputs structure mirrors the data tree.
    try:
        # audit_outputs/{plan}/v{ver}/audit_report_{ver}.pdf → extract plan + ver
        v_dir = pdf_output_path.parent
        plan = v_dir.parent.name  # e.g. 407-1048248
        ver = v_dir.name  # e.g. v24.3
        # Repo root = audit_outputs/.. (the PDF dir is rooted at audit_outputs)
        repo_root = v_dir.parent.parent.parent
        candidate = repo_root / "data" / "projects" / plan / "submissions" / ver / "coverage_report.json"
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _verdict_count_summary_he(vc: dict) -> str:
    """Render a tiny inline verdict-count summary like 'תקין 8 · דורש בירור 3'."""
    pieces: list[str] = []
    for v, lbl in [
        ("pass", "תקין"),
        ("fail", "לא תקין"),
        ("requires_review", "דורש בירור"),
        ("not_submitted", "לא הוגש"),
        ("not_applicable", "לא רלוונטי"),
    ]:
        n = vc.get(v) or 0
        if n:
            pieces.append(f"{lbl} {n}")
    return " · ".join(pieces) or "—"


def _render_section_5_coverage(report: dict) -> str:
    summary = report.get("summary") or {}
    full = report.get("section_5_1_full") or []
    partial = report.get("section_5_2_partial") or []
    none = report.get("section_5_3_none") or []
    gaps = report.get("section_5_3_highlighted_gaps") or []
    page_rows = report.get("section_5_4_page_rows") or []
    disclaimer = report.get("section_5_5_disclaimer_he") or ""
    page_cov = summary.get("page_coverage") or {}

    # 5.1 full
    full_rows = "".join(
        f"<tr><td>{_esc(e.get('category_he') or '')}</td>"
        f"<td>{int(e.get('normative_clauses') or 0)}</td>"
        f"<td>{_esc(_verdict_count_summary_he(e.get('verdict_counts') or {}))}</td></tr>"
        for e in full
    )
    # 5.2 partial
    partial_rows = "".join(
        f"<tr><td>{_esc(e.get('category_he') or '')}</td>"
        f"<td>{int(e.get('normative_clauses') or 0)}</td>"
        f"<td>{_esc(_verdict_count_summary_he(e.get('verdict_counts') or {}))}</td></tr>"
        for e in partial
    )
    # 5.3 none — categories + highlighted gap cards
    none_rows = "".join(
        f"<tr><td>{_esc(e.get('category_he') or '')}</td>"
        f"<td>{int(e.get('normative_clauses') or 0)}</td></tr>"
        for e in none
    )
    # Note: g.get('task_ref') is intentionally NOT rendered — task IDs are
    # internal-only. Ellen sees only the Hebrew title + detail.
    gap_cards = "".join(
        f"""<div class="cov-gap-card">
          <div class="cov-gap-title">{_esc(g.get('title') or '')}</div>
          <div class="cov-gap-detail">{_esc(g.get('detail') or '')}</div>
        </div>"""
        for g in gaps
    )
    # 5.4 page rows
    cov_label = {"FULL": "מלא", "PARTIAL": "חלקי", "UNADDRESSED": "לא נבדק"}
    cov_class = {"FULL": "cov-full", "PARTIAL": "cov-partial", "UNADDRESSED": "cov-none"}
    page_table_rows = "".join(
        f"<tr><td>{int(r.get('page_number') or 0)}</td>"
        f"<td>{_esc(r.get('page_type_he') or '')}</td>"
        f"<td>{_esc(', '.join(str(x) for x in (r.get('ta_shetach_refs') or [])) or '—')}</td>"
        f"<td class=\"{cov_class.get(r.get('coverage'), '')}\">{_esc(cov_label.get(r.get('coverage'), '—'))}</td></tr>"
        for r in page_rows
    )

    return f"""
    <div class="chapter" id="sec-5">
      <div class="eyebrow">{_esc(EYEBROW)}</div>
      <h2 class="chapter-num-title">5. היקף הבדיקה האוטומטית</h2>
      <p class="chapter-intro">
        סעיף זה מתעד באופן שקוף את היקף הבדיקה האוטומטית שבוצעה על ההגשה — מה נבדק
        במלואו, מה נבדק חלקית, ומה לא נבדק כלל. מטרתו לוודא שמהנדס/ת הוועדה
        המקומית מקבל/ת תמונה מלאה לפני אישור ההגשה.
      </p>

      <h3 class="subsection-num">5.0 מקורות הראיות</h3>
      <p class="cov-help">
        הבדיקה האוטומטית מורכבת מחמישה מקורות עצמאיים. כל ממצא בדוח נשען לפחות
        על אחד מהם; חלק מהממצאים נשענים על שילוב של שניים ומעלה.
      </p>
      <table class="cov-table">
        <thead><tr><th>מקור</th><th>תפקיד בדוח</th></tr></thead>
        <tbody>
          <tr>
            <td><b>מנוע הציות הדטרמיניסטי</b></td>
            <td>בדיקה מספרית פר-תא שטח של פרמטרים מהתקנון (יח"ד, שטחי בנייה, גובה, חניה, תמהיל, שטחים מחלחלים). מזין את פרק 2.</td>
          </tr>
          <tr>
            <td><b>סקירה ויזואלית של מסמכי ההגשה</b></td>
            <td>קריאת תכניות, חזיתות וטבלאות באמצעות מודל ראייה. מזין את פרק 2א ומשמש כמקור עזר לחלק מבדיקות פרק 2.</td>
          </tr>
          <tr>
            <td><b>מבקר ויזואלי</b></td>
            <td>אימות צולב של הסקירה הראשונית — מקטין את הסיכון לטעויות חיזוי. מזין הצלבות בפרק 2א ובחלק מטענות הציטוט בפרק 3.</td>
          </tr>
          <tr>
            <td><b>בדיקה גיאומטרית מבוססת תשריט (CAD)</b></td>
            <td>קריאה ישירה של קבצי DWG מהקובץ הסטטוטורי (CRS ישראלי EPSG:2039). מזינה את פרק 2ב — שלמות תאי שטח ושטחים קנוניים.</td>
          </tr>
          <tr>
            <td><b>אימות גבהים מוחלטים מחתכים וחזיתות</b></td>
            <td>חילוץ תוויות מפלסים מוחלטים מתשריטי החתכים והחזיתות. מזין את פרק 2ג — בדיקת תקרת סעיף 6.7 ועקביות בין-תשריטית.</td>
          </tr>
        </tbody>
      </table>

      <h3 class="subsection-num">5.1 קטגוריות שנבדקו במלואן</h3>
      <p class="cov-help">קטגוריות אלו כוסו על-ידי כללי בדיקה ייעודיים במנוע התאימות, בשילוב בדיקה ויזואלית ומשלימה של מסמכי ההגשה.</p>
      <table class="cov-table">
        <thead><tr><th>קטגוריה</th><th>סעיפים נורמטיביים</th><th>פילוח ממצאים</th></tr></thead>
        <tbody>{full_rows or '<tr><td colspan="3">—</td></tr>'}</tbody>
      </table>

      <h3 class="subsection-num">5.2 קטגוריות שנבדקו חלקית</h3>
      <p class="cov-help">כיסוי חלקי — חלק מהסעיפים נבדקו, חלק דורשים השלמה ידנית או קובץ DWG.</p>
      <table class="cov-table">
        <thead><tr><th>קטגוריה</th><th>סעיפים נורמטיביים</th><th>פילוח ממצאים</th></tr></thead>
        <tbody>{partial_rows or '<tr><td colspan="3">—</td></tr>'}</tbody>
      </table>

      <h3 class="subsection-num">5.3 קטגוריות שלא נבדקו אוטומטית — דורש בדיקה ידנית של מהנדס/ת</h3>
      <p class="cov-help cov-warn">⚠ הסעיפים שלהלן אינם נבדקים על-ידי המנוע. נדרשת בדיקה ידנית של מהנדס/ת המינהלת לפני חתימה על חוות דעת.</p>
      <table class="cov-table">
        <thead><tr><th>קטגוריה</th><th>סעיפים נורמטיביים</th></tr></thead>
        <tbody>{none_rows or '<tr><td colspan="2">—</td></tr>'}</tbody>
      </table>
      <div class="cov-gap-list">{gap_cards}</div>

      <h3 class="subsection-num">5.4 כיסוי לפי עמודי ההגשה</h3>
      <p class="cov-help">מפת כיסוי לפי עמודים בהגשה: כל אחד מ-63 העמודים מסומן כ"מלא" / "חלקי" / "לא נבדק". העמודים בקטגוריה "לא נבדק" דורשים תשומת לב.</p>
      <table class="cov-table cov-pages">
        <thead><tr><th>עמוד</th><th>סוג עמוד</th><th>תאי שטח</th><th>כיסוי</th></tr></thead>
        <tbody>{page_table_rows}</tbody>
      </table>

      <h3 class="subsection-num">5.5 הסתייגות</h3>
      <p class="cov-disclaimer">{_esc(disclaimer)}</p>
    </div>
    """


# ─────────────────────────────────────────────────────────────────────────────
# §3
# ─────────────────────────────────────────────────────────────────────────────

def _render_section_3(
    discipline_results: list[dict],
    *,
    amenity_inventory: dict | None = None,
) -> str:
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

    # Phase 7.4 — append amenity inventory as §3.{disc_i+1}
    if amenity_inventory:
        amenity_idx = disc_i + 1
        subs.append(_render_amenity_inventory_subsection(
            f"3.{amenity_idx}", "sec-3-amenities", amenity_inventory,
        ))

    return f"""
    <div class="chapter" id="sec-3">
      {_chapter_open("3", "בדיקה רב-תחומית לפי חוברת הנחיות עירונית", intro)}
      {badges}
      {''.join(subs)}
    </div>
    """


def _render_amenity_inventory_subsection(
    num: str, anchor_id: str, inventory: dict,
) -> str:
    """Phase 7.4 — §3.N "שירותים לדיירים" inventory table (no verdicts).

    Visual identity: inherits §3's standard sub-section styling. NOT a new
    evidence source (cf. §2א/2ב/2ג which have their own accent colors) — this
    is a soft-policy inventory whose role is to surface what the architect
    drew without claiming compliance.
    """
    amenities = inventory.get("amenities") or []
    residential_plots = inventory.get("residential_plots") or [1, 2, 3, 4, 5]
    source_pages = inventory.get("source_pages") or [26, 36, 41, 45]

    provenance_he = (
        f"ממצאי מלאי של שירותים לדיירים שזוהו בדיאגרמות הפונקציות "
        f"(עמ' 26 לתא שטח 1; עמ' 36 לתאי שטח 2+4; עמ' 41 לתא שטח 3; "
        f"עמ' 45 לתא שטח 5)."
    )
    coverage_explainer_he = (
        'בבסיס הידע הנגיש למערכת לא נמצאו דרישות מקודדות עבור רוב הקטגוריות '
        'בטבלה. ייתכן שדרישות אלו קיימות בחוברת ההנחיות המרחביות של נס ציונה '
        'או במסמכי מדיניות מקומיים נוספים. הטבלה מוצגת לסקירה ולא לבדיקת '
        'ציות; בעתיד תתווסף עמודת חיווי ציות עם טעינת הדרישות המלאות.'
    )
    table_note_he = (
        'הטבלה להלן מוצגת לסקירת הצוות, ללא חיווי ציות. עמודת "הערה" '
        'תאוכלס בעתיד עם דרישות מקודדות.'
    )

    # Header row
    plot_headers = "".join(
        f'<th class="amen-plot-cell">תא שטח {p}</th>' for p in residential_plots
    )
    header_html = f"""
    <thead>
      <tr>
        <th class="amen-name-cell">שירות</th>
        {plot_headers}
        <th class="amen-anchor-cell">אסמכתא רגולטורית</th>
        <th class="amen-note-cell">הערה</th>
      </tr>
    </thead>
    """

    def _cell_for(amen, plot_id):
        cell = amen["per_plot"].get(str(plot_id), {}) or {}
        if cell.get("non_residential"):
            return '<td class="amen-na">לא רלוונטי</td>'
        if cell.get("detected"):
            page = cell.get("source_page", "—")
            raw = cell.get("raw_label", "")
            # If the raw label adds information (e.g. "מתקני כושר" vs the canonical
            # "חדר כושר"), surface it in parentheses
            raw_display = ""
            if raw and raw.strip() not in (amen.get("hebrew") or ""):
                raw_display = f' <span class="amen-raw">({_esc(raw)})</span>'
            return f'<td class="amen-yes">✓ עמ\' {page}{raw_display}</td>'
        return '<td class="amen-no">—</td>'

    body_rows = []
    for amen in amenities:
        cells = "".join(_cell_for(amen, p) for p in residential_plots)
        anchor = _esc(amen.get("regulatory_anchor") or "—")
        note = _esc(amen.get("audit_note") or "")
        body_rows.append(f"""
        <tr>
          <td class="amen-name-cell">{_esc(amen["hebrew"])}</td>
          {cells}
          <td class="amen-anchor-cell">{anchor}</td>
          <td class="amen-note-cell">{note}</td>
        </tr>
        """)

    return f"""
    <div class="subsection amen-subsection" id="{anchor_id}">
      <h3 class="subsection-num">{_esc(num)} שירותים לדיירים</h3>
      <p class="amen-provenance">{_esc(provenance_he)}</p>
      <p class="amen-coverage">{_esc(coverage_explainer_he)}</p>
      <p class="amen-note">{_esc(table_note_he)}</p>
      <table class="amen-table">
        {header_html}
        <tbody>{''.join(body_rows)}</tbody>
      </table>
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
          <th style="width:28%;">מדיניות</th>
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
                       residential_parcels: list[dict] | None = None,
                       *,
                       amenity_inventory: dict | None = None) -> str:
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

    # Phase 7.4 — soft clarification request for amenity gaps. NOT a non_compliance
    # claim — separated from the priority list to make the framing clear.
    clarification_html = ""
    if amenity_inventory and amenity_inventory.get("clarification_needed"):
        cn = amenity_inventory["clarification_needed"]
        clarification_html = f"""
        <h3 class="subsection-num" style="margin-top:8mm">דרישות לעיון — שירותים לדיירים</h3>
        <div class="amen-clarification">
          {_esc(cn.get("hebrew") or "")}
        </div>
        """

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
      {clarification_html}
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

    # Passing-rules summary — single-line summary + bulleted list (M6 Phase 6.D)
    passing = [r for r in format_results if _format_verdict_kind(r) == "pass"]
    if passing:
        bullets = "".join(
            f"<li>{_esc(_format_rule_title(r))}</li>"
            for r in sorted(passing, key=lambda x: x.get("rule_code", ""))
        )
        passing_block = f"""
        <div class="passing-summary">
          <p class="passing-summary-head">כללי פורמט נוספים שעברו את הבדיקה: {len(passing)}</p>
          <ul class="passing-summary-list">{bullets}</ul>
        </div>
        """
    else:
        passing_block = ""

    body = f"""
    <div class="chapter">
      <div class="eyebrow">{_esc(EYEBROW)}</div>
      <h2 class="chapter-num-title">נספח א — ליקויי פורמט שזוהו</h2>
      <p class="chapter-intro">{_esc(intro)}</p>
      {badges}
      {''.join(blocks) if blocks else '<p style="color:#7A7A7A;">לא נמצאו ליקויי פורמט.</p>'}
      {passing_block}
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
