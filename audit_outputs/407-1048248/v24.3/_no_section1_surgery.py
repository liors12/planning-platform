"""Post-M8.2 surgery — remove §1 ניתוח תכנון עירוני entirely.

Three sites:
  S1 — §1 chapter body block (<div class="chapter" id="sec-1">...</div>)
  S2 — §1 TOC row (<tr ...href="#sec-1">1. ניתוח תכנון עירוני</a>...</tr>)
  S3 — cover-note enumeration: "שלושה פרקים: ניתוח תכנון עירוני, בדיקת..."
       → "שני פרקים: בדיקת תאימות לתב\"ע, ובדיקה רב-תחומית"

Per Lior decision: qualitative planning analysis lives in a separate document;
the engine should not pretend to author §1. Removal applied on the M8.2
Ellen-handoff lineage (HTML surgery; engine baseline + m4.json untouched).
"""
from __future__ import annotations
from pathlib import Path

SRC = Path('audit_outputs/407-1048248/v24.3/audit_report_24.3.html')
html = SRC.read_text(encoding='utf-8')
print(f'Input: {len(html):,} chars')


# ── S1 — chapter body block (lines 1217-1221 in current HTML) ─────────────
# Trailing whitespace pattern verified via repr: </div>\n    \n    where
# the final 4 spaces are sec-2's indent — preserve those by including in NEW_S1.
OLD_S1 = (
    '<div class="chapter" id="sec-1">\n'
    '      <div class="eyebrow">המינהלת להתחדשות עירונית — עיריית נס ציונה</div>'
    '<h2 class="chapter-num-title">1. ניתוח תכנון עירוני</h2>'
    '<p class="chapter-intro">דוח זה סוקר את תוכנית עיצוב גרסה 24.3 אל מול שלוש שכבות הרגולציה הרלוונטיות: תקנון התב"ע (פרמטרים מספריים פר-תא שטח), חוברת ההנחיות העירוניות (בדיקה רב-תחומית בעשר דיסציפלינות), ותשריט הקובץ הסטטוטורי (שלמות תאי שטח וגבהים מוחלטים). מבנה הדוח: פרק 2 — תאימות תוכן פר-תא שטח. פרק 3 — בדיקה רב-תחומית עם תת-פרק 3.11 (מלאי שירותים לדיירים). פרק 4 — סיכום הפעולות הנדרשות.</p>\n'
    '      <p class="chapter-intro">הניתוח התכנוני האיכותי של פרק 1 (שילוב במרקם\n'
    '        הקיים, השפעות תנועה, איכות שצ"פ ומבני ציבור, חזות) יוצג בנפרד.</p>\n'
    '    </div>\n'
    '    \n'
    '    '
)
NEW_S1 = '    '  # preserve sec-2's leading indent
n = html.count(OLD_S1)
assert n == 1, f'S1: expected 1, got {n}'
html = html.replace(OLD_S1, NEW_S1)
print('  ✓ S1: §1 chapter body removed')


# ── S2 — TOC row for §1 ───────────────────────────────────────────────────
OLD_S2 = '<tr><td class="title main"><a href="#sec-1">1. ניתוח תכנון עירוני</a></td><td class="page"><a href="#sec-1"></a></td></tr>'
n = html.count(OLD_S2)
assert n == 1, f'S2: expected 1, got {n}'
html = html.replace(OLD_S2, '')
print('  ✓ S2: §1 TOC row removed')


# ── S3 — cover-note enumeration ────────────────────────────────────────────
OLD_S3 = 'שלושה פרקים: ניתוח תכנון עירוני, בדיקת תאימות לתב"ע, ובדיקה רב-תחומית'
NEW_S3 = 'שני פרקים: בדיקת תאימות לתב"ע ובדיקה רב-תחומית'
n = html.count(OLD_S3)
assert n == 1, f'S3: expected 1, got {n}'
html = html.replace(OLD_S3, NEW_S3)
print('  ✓ S3: cover-note enumeration "שלושה פרקים: ניתוח..." → "שני פרקים: בדיקת..."')


SRC.write_text(html, encoding='utf-8')
print(f'\nOutput: {SRC} ({len(html):,} chars)')
