"""M8.0 one-off surgery on M7.9 HTML — rev 2.

Idempotent: dedup (old, new) pairs so identical cell-content rules (e.g. all 5
building-area cells share text) are replaced in one shot. Strict assertions
on minimum match counts catch regressions.
"""
from __future__ import annotations
import json
from pathlib import Path

SRC = Path('audit_outputs/407-1048248/v24.3/audit_report_24.3.html')
html = SRC.read_text(encoding='utf-8')
extracts = json.load(open('/tmp/m80_extracts.json', encoding='utf-8'))
print(f'Input: {len(html):,} chars')


# ============================================================================
# CHANGE 1 — Project rename
# ============================================================================
for old, new in [
    ('מתחם הטייסים-ההסתדרות', 'מתחם ההסתדרות'),
    ('מתחם הטייסים (ההסתדרות), נס ציונה', 'מתחם ההסתדרות, נס ציונה'),
]:
    n = html.count(old)
    if n:
        html = html.replace(old, new)
        print(f'  rename: {n}× "{old[:35]}…" → "{new[:35]}…"')


# ============================================================================
# CHANGE 2 — Condense Section 2 הערה cells (dedup'd)
# ============================================================================
# Build (old, new, label, expected_count) tuples. dedup'd on `old`.
edits: list[tuple[str, str, str, int]] = []

# 2a — parking (5 distinct per plot)
PARKING_RATIOS = {1: ('1.42', '330/232'), 2: ('1.48', '65/44'),
                  3: ('1.43', '186/130'), 4: ('1.41', '138/98'),
                  5: ('1.43', '280/196')}
for plot, (ratio, fraction) in PARKING_RATIOS.items():
    new = (f'יחס חניה פרטית מחושב: {ratio} ({fraction} יח"ד), '
           f'מעל בסיס 1.3. אימות מדויק מול תקן חניה לאומי 3.1 מצריך '
           f'טבלת שטחים פר יחידת דיור — לא קיימת בהגשה. '
           f'יש לצרף טבלת שטחים פר יח״ד.')
    edits.append((extracts[f'plot{plot}_יחס חניה'], new,
                  f'parking plot {plot}', 1))

# 2b — building areas (each rule identical across 5 plots)
AREA_RULES = [
    ('שטח עיקרי (מ"ר)',
     'לא נכלל בהגשה. יש לצרף טבלת שטחי בנייה מפורטת (עיקרי / שירות) פר תא שטח ולהתאים לתקרת התב"ע.'),
    ('שטח שירות מעל (מ"ר)',
     'לא נכלל בהגשה. יש לצרף בטבלת שטחים מפורטת את שטחי השירות מעל הקרקע פר תא שטח ולהתאים לתקרת התב"ע.'),
    ('שטח שירות מתחת (מ"ר)',
     'לא נכלל בהגשה. יש לצרף בטבלת שטחים מפורטת את שטחי השירות התת-קרקעיים פר תא שטח.'),
]
for rule, new in AREA_RULES:
    edits.append((extracts[f'plot1_{rule}'], new,
                  f'{rule} (all plots)', 5))

# 2c — heights: plots 1+4 share, plots 2+3 share, plot 5 unique
HEIGHTS_GENERIC = 'גובה הבניין המוצע לא יעלה על הגובה המותר בתב"ע.'
# Add per-plot to handle whatever distinct old strings exist
height_seen: set[str] = set()
for plot in [1, 2, 3, 4]:
    old = extracts[f'plot{plot}_גובה ביחס לקרקע / קומות']
    if old not in height_seen:
        height_seen.add(old)
        n_expected = sum(1 for p in [1,2,3,4]
                         if extracts[f'plot{p}_גובה ביחס לקרקע / קומות'] == old)
        edits.append((old, HEIGHTS_GENERIC,
                      f'height plots 1-4 (×{n_expected})', n_expected))

# Plot 5 — EXCEEDANCE PRESERVED
HEIGHT_5_NEW = (
    'אי התאמה בסעיף 6.7.4 בתקנון התב"ע: גובה מבנה A5 כפי שמופיע בסולם '
    'הגבהים (חזית ימנית, מפלס 13) הוא +91.80 מ\' מעל פני הים, חורג '
    'מהתקרה של 91 מ\' המותרים.'
)
edits.append((extracts['plot5_גובה ביחס לקרקע / קומות'], HEIGHT_5_NEW,
              'height plot 5 (EXCEEDANCE preserved)', 1))

# 2d — unit count (5 distinct), setback (1 identical), 2.6 (2 cells)
UNIT_COUNTS = {1: '232', 2: '44', 3: '130', 4: '98', 5: '196'}
for plot, n in UNIT_COUNTS.items():
    new = f'{n} יח"ד תואם את תקרת התב"ע לתא שטח {plot}.'
    edits.append((extracts[f'plot{plot}_כמות יח"ד'], new,
                  f'unit count plot {plot}', 1))

SETBACKS_NEW = (
    'יש לצרף בהגשה הבאה טבלת קווי בניין מפורטת (קדמי / צידי / אחורי) '
    'כדי שניתן יהיה לאמת מול תקנון התב"ע. סעיף 4.1.2.4 דורש מרחק '
    'מינימלי של 9 מ\' בין מבנים.'
)
edits.append((extracts['plot1_קווי בניין'], SETBACKS_NEW,
              'setbacks (all plots ×5)', 5))

edits.append((
    extracts['plot6_אחוז דירות קטנות'],
    'מאומתות לפחות 17 דירות קטנות (2.43% מ-700 יח"ד) לפי הגדרה ≤75 מ"ר. '
    'האדריכל מצהיר על 21% (147/700) בהגדרה רחבה יותר (≤81 מ"ר). '
    'יש לצרף טבלת תמהיל עם שטח לכל יחידת דיור לסגירת הספק מול דרישת 20%.',
    '2.6 small apartments %', 1))
edits.append((
    extracts['plot6_אחוז שטחים מחלחלים'],
    'יש לצרף חישובי שטחים מדויקים בהגשה הבאה. סעיף 4.5.2.1 בתקנון התב"ע '
    'מגביל את שטח הבינוי של תשתיות עיליות בשטחי זיקת הנאה ל-5%.',
    '2.6 permeable %', 1))


# Apply
print()
print('--- Cell condense pass ---')
for old, new, label, expected_n in edits:
    old_wrap = f'<td>{old}</td>'
    new_wrap = f'<td>{new}</td>'
    n = html.count(old_wrap)
    assert n == expected_n, f'{label}: expected {expected_n} match, found {n}'
    html = html.replace(old_wrap, new_wrap)
    print(f'  ✓ {label} ({n} cell{"s" if n>1 else ""})')

SRC.write_text(html, encoding='utf-8')
print(f'\nOutput: {SRC} ({len(html):,} chars)')
