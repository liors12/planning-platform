"""M7.8 one-off surgery on M7.6 Part B HTML.

Three passes:
  1. Per-cell prose rewrites (strip observational lead-ins / banned framing,
     preserve concrete criteria).
  2. Page-reference repositioning: "(עמ' …) BODY" → BODY + <span class="page-ref">(עמ' …)</span>
  3. Status-label + JSON-text replacements (דורש בירור → נדרשת השלמה).

Produces the surgery output AND a before/after table that the user can
spot-check (the critical preservation verification).
"""
from __future__ import annotations
import re
from pathlib import Path

SRC = Path('audit_outputs/407-1048248/v24.3/audit_report_24.3.html')
DST = SRC
REPORT = Path('/tmp/m78_diff_report.txt')

html = SRC.read_text(encoding='utf-8')
print(f'Input: {len(html):,} chars')

# ─────────────────────────────────────────────────────────────────────────────
# Pass 1 — per-cell prose rewrites
#
# Tuples: (cell_id_for_log, old_full_body, new_full_body)
# old_full_body is the EXACT text between "(עמ' …) " and "</td>" in the cell.
# new_full_body is the rewritten directive (still without page ref — that's
# added by Pass 2).
#
# Cells NOT touched (already-correct directives, per user's "do not touch"
# rule): #2, #3, #8, #9, #10, #13, #14, #18, #20, #24.
# ─────────────────────────────────────────────────────────────────────────────

REWRITES: list[tuple[str, str, str]] = [
    ('cell-1',
     'המערכת היא כנראה פניאומטית עם דחיסה בקרקע. יש לציין על תכניות הקומות הטיפוסיות את מיקום חדרי איסוף הפסולת או שוטי הפסולת בכל קומה, ולסמנם בלגנדה',
     'יש לציין על תכניות הקומות הטיפוסיות את מיקום חדרי איסוף הפסולת או שוטי הפסולת בכל קומה, ולסמנם בלגנדה'),

    ('cell-4',
     'תואם ויזואלית. כדאי לאמת תכנון מפורט של הצינורות עם יועץ פסולת',
     'תואם. יש לאמת תכנון מפורט של הצינורות עם יועץ פסולת'),

    ('cell-5',
     'תואם ויזואלית — כניסות מטופלות נופית. עיצוב מפורט (ספסלים, סוגי צמחים) דורש סקירה ע"י אדריכל נוף',
     'כניסות מטופלות נופית. יש להציג עיצוב מפורט (ספסלים, סוגי צמחים) בתיאום עם אדריכל הנוף'),

    ('cell-6',
     'ויזואלית קיימת רצועה — נדרשת מדידה לוודא ≥2מ ומיקום עצים',
     'נדרשת מדידה לוודא ≥2מ ומיקום עצים'),

    ('cell-7',
     'תואם ויזואלית — אין מעבים נראים. כדאי לאמת בפרטי חזית בקנ"מ גדול יותר',
     'לא נראים מעבים. יש לאמת בפרטי חזית בקנ"מ גדול יותר'),

    ('cell-11',
     'נדרשת בדיקה מדויקת של מיקום רחבות הכיבוי ביחס לגבול המגרש — במיוחד תאי שטח 2+4 ו-5',
     'יש לציין במפורש את מיקום רחבות הכיבוי ביחס לגבול המגרש'),

    ('cell-12',
     'ויזואלית הולם — אך נדרשת סקירת מהנדס לוודא כיסוי מלא של כל אזורי הפיתוח',
     'יש לציין כיסוי מלא של כל אזורי הפיתוח'),

    ('cell-15',
     'תוכנית גג ייעודית כנראה חסרה. נדרשת בקשה לתוכנית גג עם סימון פאנלים/דודים',
     'יש לצרף תוכנית גג (חזית חמישית) המציגה את מיקום הדודים, הקולטים, ופאנלים פוטו-ולטאיים'),

    ('cell-16', 'תואם ויזואלית', 'תואם'),

    ('cell-17', 'נדרשת תוכנית גג להוכחה',
                'יש לצרף תוכנית גג'),

    ('cell-19',
     'תואם ויזואלית — לא נראית טקסטורת אבן. נדרש אישור סופי בנספח חומריות',
     'לא נראית טקסטורת אבן. יש לציין סופית בנספח חומריות'),

    ('cell-21',
     'תואם ויזואלית — חלונות בעלי פרופורציה אנכית. כדאי לאמת בחתכים ובפרטי חזית',
     'חלונות בעלי פרופורציה אנכית. יש לאמת בחתכים ובפרטי חזית'),

    ('cell-22', 'תואם ויזואלית', 'תואם'),

    ('cell-23',
     'ויזואלית נקי, אך נדרשת הערה תכנונית מפורשת בתקנון',
     'נדרשת הערה תכנונית מפורשת בתקנון'),

    ('cell-25',
     'נדרשת קביעה בנספח חומריות (שאינו קיים בהגשה הזו)',
     'יש לציין בנספח חומריות (לא קיים בהגשה זו)'),
]

# Apply Pass 1 rewrites — match the full cell-body text and substitute.
# Important: cell-16 and cell-22 both have body == "תואם ויזואלית".
# Both should be rewritten — Python's str.replace covers all occurrences.
applied_count = 0
for cell_id, old, new in REWRITES:
    if old not in html:
        # Some cells may be hit by a broader-context match earlier; warn.
        print(f'  ! {cell_id}: OLD body not found verbatim')
        continue
    n = html.count(old)
    html = html.replace(old, new)
    applied_count += n
    print(f'  {cell_id}: replaced {n}×')
print(f'Pass 1 — {applied_count} prose substitutions applied')


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2 — page-reference repositioning
#
# After Pass 1, the 25 affected cells look like:
#     <td>(עמ' N, M) BODY</td>
# Pass 2 transforms each into:
#     <td>BODY <span class="page-ref">(עמ' N, M)</span></td>
# ─────────────────────────────────────────────────────────────────────────────

# Pattern: <td>(עמ' …) BODY</td> — capture the page-ref and the body.
PAGE_REF_TD = re.compile(
    r'<td>(\(עמ\' [^)]+\))\s+([^<]+)</td>'
)

def reposition(m: re.Match) -> str:
    page_ref, body = m.group(1), m.group(2).rstrip()
    return f'<td>{body} <span class="page-ref">{page_ref}</span></td>'

before_cells = len(PAGE_REF_TD.findall(html))
html = PAGE_REF_TD.sub(reposition, html)
after_cells = len(PAGE_REF_TD.findall(html))
print(f'Pass 2 — repositioned {before_cells} page-ref cells, '
      f'{after_cells} still prepended (should be 0)')


# ─────────────────────────────────────────────────────────────────────────────
# Pass 3 — status label rename + JSON-prose "דורש בירור" cleanup
# ─────────────────────────────────────────────────────────────────────────────

# Order matters: replace plural before singular so partial-prefix collisions
# don't mangle the singular form mid-replacement.
before_birur = html.count('בירור')
html = html.replace("דורשים בירור", "נדרשת השלמה")
html = html.replace("דורש בירור", "נדרשת השלמה")
# Also remove embedded quote-style references to the old label inside prose:
html = html.replace("'דורש בירור'", "'נדרשת השלמה'")
html = html.replace("ל'דורש בירור'", "ל'נדרשת השלמה'")
after_birur = html.count('בירור')
print(f'Pass 3 — "בירור" hits: {before_birur} → {after_birur}')


# ─────────────────────────────────────────────────────────────────────────────
# Pass 4 (extra safety) — any banned-phrase cells we may have missed
# ─────────────────────────────────────────────────────────────────────────────

banned_remaining = []
for needle in ['נדרשת בדיקה', 'ויזואלית קיימת', 'ויזואלית הולם',
               'המערכת היא כנראה', 'נדרשת סקירת מהנדס',
               'בדיקת מהנדס', 'מהנדס לוודא',
               'נדרשת הבהרה']:
    n = html.count(needle)
    if n:
        banned_remaining.append((needle, n))
if banned_remaining:
    print('Pass 4 — banned-phrase survivors:')
    for needle, n in banned_remaining:
        print(f'  ! "{needle}": {n}')
else:
    print('Pass 4 — no banned-phrase survivors ✓')


# Output
DST.write_text(html, encoding='utf-8')
print(f'\nOutput: {DST} ({len(html):,} chars)')


# Before/after table for human review
REPORT.write_text(
    'M7.8 surgery before/after table\n'
    '=' * 78 + '\n\n'
    + '\n\n'.join(
        f'{cell_id}\n'
        f'  BEFORE: {old}\n'
        f'  AFTER:  {new}'
        for cell_id, old, new in REWRITES
    ) + '\n',
    encoding='utf-8',
)
print(f'Diff report: {REPORT}')
