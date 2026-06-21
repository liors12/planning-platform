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
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_font_dir() -> Path:
    """Resolve the font directory, PyInstaller-aware.

    Dev / source-tree: walk up to <repo_root>/assets/fonts/.
    PyInstaller --onedir bundle: sys._MEIPASS is the bundle root; the build
    spec stages assets/fonts/ inside via `datas=[('../../assets/fonts',
    'assets/fonts')]`.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "assets" / "fonts"
    return PROJECT_ROOT / "assets" / "fonts"


def _resolve_logo_path() -> Path:
    """Resolve the Ness Ziona brand logo, PyInstaller-aware.

    Same lookup pattern as _resolve_font_dir. The cover img <src> uses the
    file:// URL of the result; WeasyPrint dereferences it at render time.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "assets" / "nessziona_logo.png"
    return PROJECT_ROOT / "assets" / "nessziona_logo.png"


def _resolve_format_rules_path() -> Path:
    """Resolve submission_format_rules.json — the engine's format-checker
    ruleset. Bundled at the spec-root level via `datas=[('../../submission
    _format_rules.json', '.')]` so it sits at _MEIPASS/submission_format
    _rules.json inside the frozen build.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "submission_format_rules.json"
    return PROJECT_ROOT / "submission_format_rules.json"


FONT_DIR = _resolve_font_dir()

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
    "requires_review": ("v-rev",  "נדרשת השלמה"),
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

/* M8.1 — count-summary badges removed from the report.  The badge tables
   are still rendered (so the engine code path stays stable + future
   reports that want them can override this rule), but hidden by default. */
table.badges { display: none; }

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

/* Phase 2b Module D — referent comment tag in §3 action cells */
.referent-tag {
  display: inline-block;
  margin-inline-start: 4px;
  padding: 0 5px;
  font-size: 8.5pt;
  font-weight: 600;
  color: var(--violet, #3B2666);
  background: #F4EFFB;
  border: 1px solid var(--violet, #3B2666);
  border-radius: 3px;
}

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

/* M7.8 — page references rendered at end of cell, de-emphasized.
   Light grey, same body font size but lighter weight, so the architect's
   eye lands on the directive prose first and the reference recedes. */
.page-ref {
  color: var(--gray-mid);
  font-weight: 400;
  font-size: 9.5pt;
  white-space: nowrap;
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
  left: 22mm;
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
    discipline_comments: list[dict] | None = None,
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
    # M8.2 migration 1/4 — generic structural strips. The §1 qualitative
    # chapter, §2א/2ב/2ג sidecar/CAD/chatakhim chapters, §4 priority list,
    # §5 coverage block, and נספח א format appendix are no longer rendered
    # for ANY project. Architect-summary front-matter (Phase 7.5) also
    # dropped. Project-specific overrides (plot drops, subsection merges,
    # rule-row tweaks) come in Commit 4 via report_overrides.json.
    amenity_inventory = (audit_results.get("m4_summary") or {}).get("amenity_inventory")

    parts: list[str] = []
    parts.append(_render_cover_with_signatures(meta, submission_metadata, plan_number))
    parts.append(_render_toc(
        plan_number, residential_parcels, discipline_results,
        has_amenity_inventory=bool(amenity_inventory),
    ))
    parts.append(_render_section_2(content_results, residential_parcels, plan_number))
    parts.append(_render_section_3(discipline_results, amenity_inventory=amenity_inventory))

    html_doc = (
        '<!DOCTYPE html>'
        '<html lang="he" dir="rtl">'
        '<head><meta charset="utf-8"><title>סקירת תוכנית עיצוב</title></head>'
        '<body>' + "".join(parts) + '</body></html>'
    )
    # Phase 2b Module D — merge referent comments at render time. They live
    # only in the platform DB; never written back into audit_results.
    if discipline_comments:
        html_doc = _inject_discipline_comments(html_doc, discipline_comments)
    _render_to_pdf(html_doc, output_path)
    return output_path


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2b Module D — discipline comment injection
# ─────────────────────────────────────────────────────────────────────────────

_REFERENT_TAG = "(הערת רפרנט)"


def _comment_row_html(comment: dict) -> str:
    """Render a referent comment as a §3 table row. Status maps to the same
    badge classes used by engine rows so colors stay consistent."""
    status = comment.get("status") or ""
    status_class_map = {
        "תקין": "v-ok",
        "לא תקין": "v-fail",
        "נדרשת השלמה": "v-rev",
    }
    cls = status_class_map.get(status, "v-rev")
    topic = _esc(comment.get("topic_he") or "")
    action = _esc(comment.get("action_he") or "")
    status_he = _esc(status)
    return (
        '<tr>'
        f'<td><b>{topic}</b></td>'
        '<td>—</td>'
        f'<td><span class="{cls}">{status_he}</span></td>'
        f'<td>{action} <span class="referent-tag">{_REFERENT_TAG}</span></td>'
        '</tr>'
    )


def _inject_discipline_comments(html: str, comments: list[dict]) -> str:
    """Insert each comment as an extra `<tr>` in the `<tbody>` of the
    matching `<div class="subsection" id="{discipline_key}">` block.

    Comments whose discipline_key has no matching subsection are appended
    in a fallback `<table>` at the end of `<div class="chapter" id="sec-3">`
    so they're never dropped silently.
    """
    if not comments:
        return html
    grouped: dict[str, list[dict]] = {}
    for c in comments:
        grouped.setdefault(c.get("discipline_key", ""), []).append(c)

    orphaned: list[dict] = []
    for key, comment_list in grouped.items():
        if not key:
            orphaned.extend(comment_list)
            continue
        anchor = f'<div class="subsection" id="{key}">'
        anchor_idx = html.find(anchor)
        if anchor_idx < 0:
            orphaned.extend(comment_list)
            continue
        # Find this subsection's </tbody> — it's the first one after anchor_idx.
        tbody_close_idx = html.find("</tbody>", anchor_idx)
        if tbody_close_idx < 0:
            orphaned.extend(comment_list)
            continue
        rows_html = "".join(_comment_row_html(c) for c in comment_list)
        html = html[:tbody_close_idx] + rows_html + html[tbody_close_idx:]

    if orphaned:
        # Append a fallback block at the very end of §3.
        chapter_close = '</div>'
        sec3_idx = html.find('<div class="chapter" id="sec-3">')
        if sec3_idx >= 0:
            sec3_end_idx = html.find('<div class="chapter"', sec3_idx + 1)
            if sec3_end_idx < 0:
                sec3_end_idx = html.find('</body>', sec3_idx)
            fallback_rows = "".join(_comment_row_html(c) for c in orphaned)
            fallback_block = (
                '<div class="subsection" id="sec-3-orphan-comments">'
                '<h3 class="subsection-num">3.X הערות רפרנט ללא דיסציפלינה תואמת</h3>'
                '<table class="audit"><thead><tr>'
                '<th style="width:28%;">נושא</th>'
                '<th style="width:24%;">מצב בהגשה</th>'
                '<th style="width:13%;">ממצא</th>'
                '<th style="width:35%;">פעולה</th>'
                f'</tr></thead><tbody>{fallback_rows}</tbody></table>'
                '</div>'
            )
            html = html[:sec3_end_idx] + fallback_block + html[sec3_end_idx:]
    return html


def _render_to_pdf(html_str: str, output_path: Path) -> None:
    # M7.5.1 — defensive belt-and-braces: rewrite any remaining "§" to "סעיף "
    # in the assembled HTML before WeasyPrint sees it. Catches stray clause
    # refs from upstream JSON or future code that forgot the source-level fix.
    html_str = _normalize_he_text(html_str)
    # M7.6 — also dump the assembled HTML alongside the PDF so it can be
    # surgically edited for one-off report restructures (e.g. Ellen handoffs)
    # and re-rendered with `weasyprint <html> <pdf>` without re-running the
    # whole pipeline. Embedded CSS so the dumped file is self-rendering.
    html_full = html_str.replace(
        "<head>",
        f'<head><style>{_CSS}</style>',
        1,
    )
    output_path.with_suffix(".html").write_text(html_full, encoding="utf-8")
    base = str(FONT_DIR) + "/"

    # Phase 4 (Windows pilot) — WeasyPrint has no installable Python wheel
    # on Windows that brings its native GTK/Pango/Cairo stack. We ship
    # Kozea's official Windows CLI release (weasyprint.exe v68.1+) inside
    # the Tauri bundle and spawn it as a subprocess. The macOS path stays
    # the in-process Python import — unchanged from before this branch.
    if sys.platform == "win32":
        _render_to_pdf_via_subprocess(html_str, output_path, base)
        return

    from weasyprint import HTML, CSS as WeasyCSS
    from weasyprint.text.fonts import FontConfiguration
    font_config = FontConfiguration()
    HTML(string=html_str, base_url=base).write_pdf(
        str(output_path),
        stylesheets=[WeasyCSS(string=_CSS, base_url=base, font_config=font_config)],
        font_config=font_config,
    )


def _resolve_weasyprint_exe() -> Path:
    """Locate Kozea's bundled weasyprint.exe on Windows.

    Resolution order:
      1. WEASYPRINT_EXE_PATH env var (dev / testing override).
      2. <sys.executable parent>/weasyprint/weasyprint.exe — useful when
         the build copies WeasyPrint into the sidecar's own dir.
      3. <sys.executable parent.parent>/weasyprint/weasyprint.exe — the
         default Tauri bundle layout: binaries/sidecar/sidecar.exe is the
         sidecar entry; weasyprint sits at the sibling binaries/weasyprint/
         per `bundle.resources` glob in tauri.conf.json.
    """
    env_path = os.environ.get("WEASYPRINT_EXE_PATH")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return p
    # PyInstaller --onedir: sys.executable is the bundle entry. In the Tauri
    # release layout it lands under <Resources>/binaries/sidecar/sidecar.exe.
    exe_dir = Path(sys.executable).resolve().parent
    for candidate in (
        exe_dir / "weasyprint" / "weasyprint.exe",
        exe_dir.parent / "weasyprint" / "weasyprint.exe",
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "Windows PDF rendering is not available: weasyprint.exe was not "
        "found. Set the WEASYPRINT_EXE_PATH environment variable, or "
        "rebuild the bundle so weasyprint.exe ships at "
        f"{exe_dir.parent / 'weasyprint' / 'weasyprint.exe'} "
        f"(or the sibling-dir variant at {exe_dir / 'weasyprint' / 'weasyprint.exe'})."
    )


def _render_to_pdf_via_subprocess(
    html_str: str, output_path: Path, base_url: str,
) -> None:
    """Windows path: write HTML + CSS to temp files and shell out to
    Kozea's weasyprint.exe CLI. Native deps (Pango / Cairo / GdkPixbuf /
    fontconfig) ship inside the WeasyPrint Windows release; we don't have
    to drag the GTK stack through PyInstaller."""
    exe = _resolve_weasyprint_exe()
    log.info("rendering PDF via Windows weasyprint.exe: %s", exe)
    # UTF-8 BOM on the HTML: paranoid safety against codepage misdetection
    # when the CLI re-opens the file. The CSS is plain UTF-8 (no BOM —
    # CSS parsers don't all tolerate it as well as HTML parsers).
    BOM = "﻿"
    tmp_dir = Path(tempfile.mkdtemp(prefix="wp_render_"))
    try:
        html_path = tmp_dir / "input.html"
        css_path = tmp_dir / "style.css"
        html_path.write_text(BOM + html_str, encoding="utf-8")
        css_path.write_text(_CSS, encoding="utf-8")
        cmd = [
            str(exe),
            "--stylesheet", str(css_path),
            "--base-url", base_url,
            str(html_path),
            str(output_path),
        ]
        log.info("weasyprint.exe cmd: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, check=False)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"weasyprint.exe failed (exit={result.returncode}): "
                f"{stderr[-2000:]}"
            )
    finally:
        # Best-effort cleanup; never let a tempdir failure mask a render error.
        try:
            for p in tmp_dir.iterdir():
                try:
                    p.unlink()
                except OSError:
                    pass
            tmp_dir.rmdir()
        except OSError:
            pass


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


_COVER_STRUCTURAL_NOTE_HE = (
    "הדוח כולל את טבלת החתימות (להלן), תוכן עניינים, ושני פרקים: "
    "בדיקת תאימות לתב\"ע ובדיקה רב-תחומית."
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

    # Use the resolved logo path as a file:// URL so WeasyPrint can find it
    # regardless of where the PDF output lives (dev: ../nessziona_logo.png
    # worked because the PDF sat at audit_outputs/<key>/v<ver>/; in a
    # Windows install the output dir is under cfg.data_dir while the logo
    # lives in _MEIPASS — the relative form would 404). _resolve_logo_path()
    # picks the right copy on either OS.
    logo_url = _resolve_logo_path().as_uri()

    return f"""
    <div class="cover-v2">
      <div class="cover-band">
        <img class="logo" src="{logo_url}" alt="">
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


def _render_toc(plan_number: str, residential_parcels: list[dict],
                discipline_results: list[dict],
                *,
                has_amenity_inventory: bool = False) -> str:
    # M8.2 migration 1/4 — TOC rows for §1, §2א/2ב/2ג, §4, §5, נספח א removed
    # at the same time as their renderers. The kwargs that gated them
    # (has_sidecar / has_cad / has_chatakhim / has_section_5) went with them.
    rows: list[str] = []
    rows.append(_toc_row("2.", f'בדיקת תאימות תוכן לתב"ע {plan_number}', "#sec-2", "main"))
    for i, p in enumerate(residential_parcels, start=1):
        rows.append(_toc_row(f"2.{i}", _parcel_label_he(p), f"#sec-2-{i}", "sub"))
    pw_idx = len(residential_parcels) + 1
    rows.append(_toc_row(f"2.{pw_idx}", "בדיקות ברמת תכנית", f"#sec-2-{pw_idx}", "sub"))

    rows.append(_toc_row("3.", "בדיקה רב-תחומית", "#sec-3", "main"))
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


def _render_section_2(content_results, residential_parcels, plan_number) -> str:
    intro = (
        f'פרק זה משווה את ערכי ההגשה (יח"ד, שטחים, גובה, חניה, תמהיל, שטחים מחלחלים) מול '
        f'התקרות והדרישות המוגדרות בתב"ע {plan_number}. בכל סעיף — ההגשה הנוכחית, הדרישה, והפעולה הנדרשת.'
    )
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
        return "לפי תשריט"
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


def _render_section_3(
    discipline_results: list[dict],
    *,
    amenity_inventory: dict | None = None,
) -> str:
    intro = (
        'פרק זה בוחן את ההגשה מול חוברת ההנחיות העירונית של נס ציונה (407-0730606, פברואר 2026). '
        'הבדיקה מאורגנת בעשר דיסציפלינות. במקום בו התקבל פידבק ממנהל הדיסציפלינה — הוא משולב בתא ההערה.'
    )

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
      {_chapter_open("3", "בדיקה רב-תחומית", intro)}
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
        'הטבלה שלהלן מציגה את הזיהוי של חדרי שירות ייעודיים לדיירים בכל תא '
        'שטח. היא מובאת לסקירת האדריכל בלבד.'
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
    # M7.8 — _action_note_he now returns (body, page_ref); render page_ref
    # at the END of the cell in a light-grey de-emphasized span.
    note_body, note_pages = _action_note_he(r)
    page_ref_html = (
        f' <span class="page-ref">{_esc(note_pages)}</span>'
        if note_pages else ''
    )
    return f"""
    <tr>
      <td><b>{_esc(title)}</b><br>{_esc(policy)}</td>
      <td>{_esc(submission_state)}</td>
      <td><span class="{vclass}">{vlabel}</span></td>
      <td>{_esc(note_body)}{page_ref_html}{feedback}</td>
    </tr>
    """


def _submission_state_he(r: dict) -> str:
    # M7.6 Part A (A2) — "מצב בהגשה" must be terse: ≤1 sentence, no narrative
    # explanation, no method framing (no "בדיקה ויזואלית"/"אוטומטית"). The
    # surviving long visual descriptions get trimmed to their first clause.
    ev = r.get("evidence", {}) or {}
    if ev.get("source") == "cowork_discipline_findings_v24.3":
        visual = (r.get("evidence_visual") or ev.get("evidence_visual") or "").strip()
        if visual:
            return _terse_state(visual)
        return "—"
    ct = ev.get("check_type")
    if ct == "text_pattern":
        if ev.get("found_any"):
            pgs = sorted({pg for v in ev.get("matched_pages", {}).values() for pg in v})
            return f"אותר בעמ' {', '.join(str(p) for p in pgs[:4])}"
        return "—"
    if ct == "annex_required":
        if ev.get("annex_found"):
            pgs = sorted({pg for v in ev.get("matched_pages", {}).values() for pg in v})
            return f"נספח אותר (עמ' {', '.join(str(p) for p in pgs[:4])})"
        return "לא הוגש"
    if ct == "manual_review":
        return "—"
    return "—"


def _terse_state(text: str, max_chars: int = 120) -> str:
    """Reduce a long submission-state cell to a single short factual clause.

    Strips parentheticals, page-number lists, and trailing rationale; keeps
    only the first sentence-ish segment (split on period, semicolon, or em-dash).
    Caps total length at max_chars.
    """
    if not text:
        return ""
    s = text.strip()
    # Take only the first clause / sentence
    for sep in (". ", "; ", " — ", " · "):
        idx = s.find(sep)
        if 0 < idx < max_chars:
            s = s[:idx]
            break
    s = s.strip().rstrip(".;:,")
    if len(s) > max_chars:
        s = s[:max_chars].rsplit(" ", 1)[0] + "…"
    return s


def _action_note_he(r: dict) -> tuple[str, str]:
    """Right-column action note.  M7.8: returns ``(body, page_ref)`` so the
    renderer can put the page reference at the END of the cell in a
    de-emphasized ``<span class="page-ref">`` instead of prepending it.

    For Cowork-sourced findings the page list comes from ``evidence_pages``;
    for other findings the page reference is empty (page numbers, if any,
    are baked into ``notes_he`` from the translator output and surfaced via
    the surrounding cell text).
    """
    ev = r.get("evidence", {}) or {}
    if ev.get("source") == "cowork_discipline_findings_v24.3":
        pages = r.get("evidence_pages") or ev.get("evidence_pages") or []
        note = (r.get("compliance_note") or ev.get("compliance_note") or "").strip()
        page_ref = f"(עמ' {', '.join(str(p) for p in pages)})" if pages else ""
        body = note or r.get("remediation_he", "") or "—"
        return body, page_ref
    v = r.get("verdict", "")
    body = r.get("remediation_he", "") if v != "pass" else "ראה ראיות."
    return body, ""


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
