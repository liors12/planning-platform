"""M7.9 one-off surgery on M7.8 HTML.

Three small text-level edits — no engine changes. Run on the fast path
(--from-html, ~2 sec re-render).

  Edit 1: cell-11 — restore "תאי שטח 2, 4 ו-5" plot pointer
  Edit 2: cell-4, cell-5 — flatten residual soft framing
  Edit 3: insert "מבני ציבור (מעונות וגנים)" block in city-architect section
"""
from __future__ import annotations
from pathlib import Path

SRC = Path('audit_outputs/407-1048248/v24.3/audit_report_24.3.html')
html = SRC.read_text(encoding='utf-8')
print(f'Input: {len(html):,} chars')


# ============================================================================
# Edit 1 — cell-11: restore plot pointer (dropped in M7.8)
# ============================================================================
EDIT1_OLD = 'יש לציין במפורש את מיקום רחבות הכיבוי ביחס לגבול המגרש'
EDIT1_NEW = 'יש לציין במפורש את מיקום רחבות הכיבוי ביחס לגבול המגרש, ובמיוחד בתאי שטח 2, 4 ו-5'
n1 = html.count(EDIT1_OLD)
# Be careful: replace only the EXACT string. The new string includes the old as a prefix,
# so str.replace on the old string would not be idempotent if EDIT1_NEW is already there.
# Avoid double-application: check if EDIT1_NEW is already present.
if EDIT1_NEW in html:
    print(f'  Edit 1: already applied (idempotent) — skipping')
elif n1 == 1:
    html = html.replace(EDIT1_OLD, EDIT1_NEW)
    print(f'  Edit 1: restored plot pointer in cell-11 ✓')
elif n1 == 0:
    raise RuntimeError('Edit 1: cell-11 OLD not found and NEW not present — bail')
else:
    raise RuntimeError(f'Edit 1: cell-11 OLD found {n1}× (expected 1)')


# ============================================================================
# Edit 2a — cell-4: "יש לאמת… עם יועץ פסולת" → "יש לציין… בנספח"
# ============================================================================
EDIT2A_OLD = 'תואם. יש לאמת תכנון מפורט של הצינורות עם יועץ פסולת'
EDIT2A_NEW = 'תואם. יש לציין תכנון מפורט של הצינורות בנספח'
n2a = html.count(EDIT2A_OLD)
assert n2a == 1, f'Edit 2a: cell-4 OLD found {n2a}× (expected 1)'
html = html.replace(EDIT2A_OLD, EDIT2A_NEW)
print(f'  Edit 2a: cell-4 flattened ✓')


# ============================================================================
# Edit 2b — cell-5: drop "בתיאום עם אדריכל הנוף" coordination clause
# (preserved in city-architect block verbatim line 8)
# ============================================================================
EDIT2B_OLD = ('כניסות מטופלות נופית. יש להציג עיצוב מפורט (ספסלים, '
              'סוגי צמחים) בתיאום עם אדריכל הנוף')
EDIT2B_NEW = ('כניסות מטופלות נופית. יש להציג עיצוב מפורט (ספסלים, '
              'סוגי צמחים)')
n2b = html.count(EDIT2B_OLD)
assert n2b == 1, f'Edit 2b: cell-5 OLD found {n2b}× (expected 1)'
html = html.replace(EDIT2B_OLD, EDIT2B_NEW)
print(f'  Edit 2b: cell-5 flattened (coordination preserved in architect block) ✓')


# ============================================================================
# Edit 3 — insert "מבני ציבור (מעונות וגנים)" block verbatim
# from /Users/liorlevin/Downloads/ההסתדרות_דוח_01.docx
# Placement: between her per-plot table (חלק א' section 3) and חלק ב'.
# Styled to match the rest of the architect block (violet palette).
# ============================================================================

MAVNEI_BLOCK = '''
        <h5 style="font-size: 11pt; font-weight: 700; color: #3B2666; margin: 5mm 0 2mm 0;">2. מבני ציבור (מעונות וגנים)</h5>
        <p style="font-size: 10pt; line-height: 1.6; color: #1a1a1a; margin: 1.5mm 0;">השטח המוקצה נראה שאריתי ואינו תואם את הסטנדרטים הנדרשים לאישור משרד החינוך:</p>
        <ul style="font-size: 10pt; line-height: 1.6; color: #1a1a1a; margin: 1mm 0; padding-right: 7mm;">
          <li><strong>שטחי חצרות:</strong> נדרשים 175 מ"ר חצר לכל כיתת גן, ו-80 עד 150 מ"ר לכיתת מעון (בהתאם לגיל). החצרות חייבות להיות צמודות לכל כיתה, עם חיבור מיטבי בין פנים לחוץ.</li>
          <li><strong>חלוקה פנימית:</strong> החלוקה הפנימית הקיימת כעת נקטעת על ידי שני גרעיני ממ"דים גדולים, מה שפוגע ברציפות הפונקציונלית, השטח במבנה צר וארוך ואינו יעיל. הקשר בין החלל הציבורי לחצר אינו מספק.</li>
          <li><strong>קומה 1:</strong> הקשר בין החלל הציבורי בקומה זו לחצר הוא מינימלי ואינו ישים למוסד חינוכי תקני.</li>
        </ul>
'''

# Find insertion point: end of per-plot table (3. הערות פרטניות לתאי השטח),
# right before the חלק ב' heading.
PART_B_HEADING_MARKER = '<h4 style="font-size: 12pt; font-weight: 700; color: #3B2666; margin: 6mm 0 2mm 0;">חלק ב\': עיצוב חזיתות המבנים ושפה אדריכלית</h4>'
idx = html.find(PART_B_HEADING_MARKER)
if idx < 0:
    raise RuntimeError('Edit 3: Part B heading marker not found — placement anchor missing')

# Idempotency check
if 'מבני ציבור (מעונות וגנים)' in html:
    print(f'  Edit 3: block already present — skipping')
else:
    html = html[:idx] + MAVNEI_BLOCK + html[idx:]
    print(f'  Edit 3: מבני ציבור block inserted '
          f'before חלק ב\' heading (+{len(MAVNEI_BLOCK):,} chars) ✓')


SRC.write_text(html, encoding='utf-8')
print(f'\nOutput: {SRC} ({len(html):,} chars)')
