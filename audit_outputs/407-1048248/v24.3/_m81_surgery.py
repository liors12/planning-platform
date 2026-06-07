"""M8.1 one-off surgery on M8.0 HTML (with M8.1 engine merged in).

Changes:
  1. §3 title text — already engine, but HTML text in this run's dump
     still has the long version; replace.
  2. Remove all <table class="badges">…</table> blocks (3 expected).
  3. Add תשתיות row "יש להציג תוכנית קווי תשתית על גבי נספח הפיתוח."
  4. Remove "נספח אקוסטי" row from §3.10 (rendered as §3.8).
  5. Logo CSS — engine-level (already in merged HTML embedded <style>).
  6. Dissolve architect block; distribute 12 condensed rows into
     §3.1/3.2/3.3/3.4/3.7; emit "כלליות" + "פרטני" standalone blocks
     at end of §3.
  7. Drop "מבני ציבור (מעונות וגנים)" block (subset of 6).
  9. Delete §4 chapter + amenity-clarification appendix (everything
     from <div class="chapter" id="sec-4"> to </body>).
"""
from __future__ import annotations
import re
from pathlib import Path

SRC = Path('audit_outputs/407-1048248/v24.3/audit_report_24.3.html')
html = SRC.read_text(encoding='utf-8')
print(f'Input: {len(html):,} chars')


# ────────────────────────────────────────────────────────────────────────────
# Helpers — discipline-row HTML template (matches existing engine output)
# ────────────────────────────────────────────────────────────────────────────

def disc_row(title: str, policy: str, state: str, verdict_cls: str,
             verdict_label: str, action: str) -> str:
    """Render a discipline row matching the existing 4-column template."""
    return (
        f'<tr>\n'
        f'      <td><b>{title}</b><br>{policy}</td>\n'
        f'      <td>{state}</td>\n'
        f'      <td><span class="{verdict_cls}">{verdict_label}</span></td>\n'
        f'      <td>{action}</td>\n'
        f'    </tr>'
    )


def insert_row_at_subsection_end(html: str, sec_id: str, row_html: str) -> str:
    """Insert a new <tr> just before </tbody></table> in the named subsection."""
    sec_start = html.find(f'<div class="subsection" id="{sec_id}">')
    assert sec_start > 0, f'subsection {sec_id} not found'
    tbody_end = html.find('</tbody>', sec_start)
    assert tbody_end > 0, f'</tbody> not found inside {sec_id}'
    # Insert immediately before </tbody>
    return html[:tbody_end] + '    ' + row_html + '\n      ' + html[tbody_end:]


# ────────────────────────────────────────────────────────────────────────────
# CHANGE 1 — §3 title text in this run's HTML
# ────────────────────────────────────────────────────────────────────────────
n = html.count('3. בדיקה רב-תחומית לפי חוברת הנחיות עירונית')
print(f'  C1: §3 title — {n} hits to replace')
html = html.replace('3. בדיקה רב-תחומית לפי חוברת הנחיות עירונית',
                    '3. בדיקה רב-תחומית')


# ────────────────────────────────────────────────────────────────────────────
# CHANGE 2 — Remove <table class="badges">…</table> blocks
# ────────────────────────────────────────────────────────────────────────────
badge_re = re.compile(r'<table class="badges">.*?</table>', re.DOTALL)
n_badges = len(badge_re.findall(html))
html = badge_re.sub('', html)
print(f'  C2: removed {n_badges} <table class="badges">…</table> blocks')


# ────────────────────────────────────────────────────────────────────────────
# CHANGE 4 — Remove נספח אקוסטי row from sec-3-10 (rendered §3.8)
# ────────────────────────────────────────────────────────────────────────────
# Match the entire <tr>…</tr> whose title is "נספח אקוסטי".
sec310 = html.find('<div class="subsection" id="sec-3-10">')
sec310_end = html.find('<div class="chapter"', sec310 + 1)
sec_body = html[sec310:sec310_end]
m = re.search(r'<tr>\s*<td><b>נספח אקוסטי</b>.*?</tr>', sec_body, re.DOTALL)
assert m, 'נספח אקוסטי row not found in sec-3-10'
old_row = m.group(0)
n = html.count(old_row)
assert n == 1, f'expected 1 נספח אקוסטי row, got {n}'
html = html.replace(old_row, '', 1)
print(f'  C4: removed נספח אקוסטי row')


# ────────────────────────────────────────────────────────────────────────────
# CHANGE 3 — Add new תשתיות row to sec-3-3
# ────────────────────────────────────────────────────────────────────────────
TASHTITS_ROW = disc_row(
    title='תוכנית קווי תשתית על גבי נספח הפיתוח',
    policy='יש להציג תוכנית קווי תשתית על גבי נספח הפיתוח כדי לאמת תיאום בין מערכות לבין הפיתוח.',
    state='—',
    verdict_cls='v-rev', verdict_label='נדרשת השלמה',
    action='יש להציג תוכנית קווי תשתית על גבי נספח הפיתוח.',
)
html = insert_row_at_subsection_end(html, 'sec-3-3', TASHTITS_ROW)
print(f'  C3: added תשתיות policy row')


# ────────────────────────────────────────────────────────────────────────────
# CHANGE 6 — Distribute 12 architect rows + emit standalone blocks
# ────────────────────────────────────────────────────────────────────────────
# Tag used on every distributed architect cell so the reader knows provenance.
TAG = '(הערת אדריכלית העיר)'

# Each tuple: (sec_id, title, policy, action)
DISTRIBUTED_ROWS = [
    # §3.1 שפ"ע — 2 rows
    ('sec-3-1',
     f'רחבות גיזום — {TAG}',
     'רחבות גיזום קיימות אך לא ברור תפקודן בפועל ועיצובן מול הרחוב/השצ"פ.',
     'יש להציג תכנון וחזית רחבות הגיזום כלפי הרחוב/השצ"פ, לרבות פרטי הסתרה נאותים.'),
    ('sec-3-1',
     f'תיאום חדרי אשפה — {TAG}',
     'יש לוודא שמיקום ותכנון חדרי האשפה תואמים את דרישות שפ"ע.',
     'יש להשלים תיאום מלא של חדרי האשפה מול מחלקת שפ"ע.'),

    # §3.2 גנים ונוף — 3 rows
    ('sec-3-2',
     f'תיאום שצ"פ עם אדריכל הנוף — {TAG}',
     'פיתוח השצ"פ הינו בתאום מול אדריכל הנוף אהוד נדל.',
     'יש להשלים תהליך תיאום פיתוח השצ"פ עם אדריכל הנוף אהוד נדל.'),
    ('sec-3-2',
     f'נספח שימור עצים — {TAG}',
     'נדרש נספח שימור/טיפול בעצים בתחום התב"ע.',
     'יש להוסיף נספח שימור/טיפול בעצים בתחום התב"ע.'),
    ('sec-3-2',
     f'רוחב דרכים ורצועות גינון — {TAG}',
     'בחלק מהחתכים רוחב הדרך מכיל שבילי הליכה ואופניים בלבד, ללא רצועות גינון — '
     'יוצר "מעבר חומות" דו-צדדי (לדוגמה, חתכים א-א בתאי שטח 3 ו-5). '
     'מצב זה עלול להחמיר כאשר דיירים יוסיפו הגבהות לגדרות.',
     'יש להציג פתרון תכנוני (הרחבת שטח, דירוג טופוגרפי) ופרט אדריכלי מחייב לסגירת '
     'דירות גן הכולל חומריות, חתך, ואפשרות הגבהה מוסדרת.'),

    # §3.3 תשתיות — 2 rows
    ('sec-3-3',
     f'חדר טרפו — {TAG}',
     'נדרשת הצגה של חדר הטרפו ומופעו בתשריטים.',
     'יש להציג את חדר הטרפו ומופעו בתנוחה ובחתך.'),
    ('sec-3-3',
     f'מיקום מערכות — {TAG}',
     'יש לציין באופן מובחן את מיקומי המערכות העיליות והתת-קרקעיות.',
     'יש להציג בצורה מובחנת את מיקומי פתחי אוורור החניונים, חדרי טרפו, מאגרי גז '
     'ומתקני אשפה.'),

    # §3.4 תנועה — 2 rows
    ('sec-3-4',
     f'רחבות כיבוי בתחום המגרש — {TAG}',
     'רחבות כיבוי אש ימוקמו בתחום המגרש הפרטי, עם אפשרות לגינון.',
     'יש למקם את רחבות הכיבוי בתחום המגרש הפרטי, עם אפשרות לגינון.'),
    ('sec-3-4',
     f'רמפות חניונים — {TAG}',
     'יש להציג את תכנון ומופע הרמפות לחניונים תת-קרקעיים.',
     'יש להציג תכנון ומופע הרמפות. מומלץ לבחון שילוב פרגולות מחופות צמחייה '
     'למתן המראה האספלטי.'),

    # §3.7 אדריכלות — 3 rows (Part B condensed)
    ('sec-3-7',
     f'השקטת חזיתות ושפה חומרית — {TAG}',
     'העיצוב הנוכחי מתאפיין בריבוי אלמנטים, חומרים וקפיצות במפלסי חלונות. '
     'השימוש הנרחב באלמנטים כהים יוצר מופע כללי כבד.',
     'יש להפחית את מספר האלמנטים השונים בחזיתות (קופסתיות, רפפות שחורות, ריבוי '
     'חומרים) ולייצר שפה הומוגנית ורגועה. מומלץ לבחון זיגוג בהיר וגוונים '
     'מוארים יותר.'),
    ('sec-3-7',
     f'עיצוב מרפסות — {TAG}',
     'מסגור המרפסות בעמודים ופרגולות יוצר משקל ויזואלי כבד; קורות מרחפות בולטות '
     'עשויות להפריע ויזואלית.',
     'יש לבחון מרפסות זיזיות "משוחררות" יותר במקום מסגרות קשיחות, תוך פתרון '
     'אדריכלי מובנה לסגירת חורף בוויטרינות שלא יפגע באחידות החזית.'),
    ('sec-3-7',
     f'תוצרים נדרשים לשלב הבא — {TAG}',
     'לבחינת חלופות עיצוביות נדרשים תוצרים מפורטים יותר.',
     'יש להגיש: (1) בניין אבטיפוס יחיד מ-4 חזיתות עם פירוט מלא של פיתוח קומת '
     'הקרקע, מרפסות, מערכות וגריד חלונות; (2) 2-3 חלופות קונספטואליות לחזית; '
     '(3) הדמיות מדויקות עם כיוון מבט, תא שטח, כיווני שמש, והשתלבות במרקם '
     'הסביבתי הקיים.'),
]

for sec_id, title, policy, action in DISTRIBUTED_ROWS:
    row = disc_row(title=title, policy=policy, state='—',
                   verdict_cls='v-rev', verdict_label='נדרשת השלמה',
                   action=action)
    html = insert_row_at_subsection_end(html, sec_id, row)
print(f'  C6: distributed {len(DISTRIBUTED_ROWS)} architect rows into §3.1/3.2/3.3/3.4/3.7')


# ────────────────────────────────────────────────────────────────────────────
# CHANGE 6 epilogue + CHANGE 7 — Replace standalone architect block with
# two compact blocks: "כלליות" (leftover, 7 items) + "פרטני" (per-plot table).
# מבני ציבור block (Change 7) gets dropped — not included anywhere.
# ────────────────────────────────────────────────────────────────────────────

LEFTOVER_BLOCK = '''
      <div class="architect-block" style="margin: 8mm 0 6mm 0; padding: 5mm 7mm; border: 1px solid #C8B6E0; border-right: 4px solid #5D3A9B; background: #F8F4FD; border-radius: 3px; page-break-inside: avoid;">
        <div style="font-size: 12pt; font-weight: 700; color: #3B2666; margin-bottom: 2mm;">הערות אדריכלית העיר — כלליות</div>
        <div style="font-size: 9pt; color: #5D3A9B; margin-bottom: 4mm;">דו"ח מס' 1 · 02.06.2026 · נקודות שאינן ניתנות לשיוך לדיסציפלינה ספציפית.</div>
        <ul style="font-size: 10pt; line-height: 1.6; color: #1a1a1a; margin: 1mm 0; padding-right: 7mm;">
          <li><strong>הקשר סביבתי:</strong> יש להשלים בתכניות את הבינוי והפיתוח במגרשים הגובלים (מחוץ לקו הכחול), המופיעים כעת כרקע לבן. נדרש להטמיע את התכנון העקרוני של השצ"פ בתב"ע הצמודה ממזרח שמשלימה את השצ"פ כולו.</li>
          <li><strong>חתכים במרחב השצ"פ:</strong> בחתכים מזרח-מערב החוצים את השצ"פ המרכזי, יש להציג את החתך ברציפות עד קו חזית המבנים מ-2 הצדדים, כולל גובה המבנים. חסר חתך פיתוח אורכי לאורך השצ"פ להמחשת טיפול בהפרשי הגבהים וחזית רציפה של גדרות דירות הגן.</li>
          <li><strong>פירוט מפלסים:</strong> יש לציין מפלסי פיתוח מוחלטים ויחסיים בכל החזיתות והחתכים הארוכים (כולל גדרות, פיתוח, מדרגות).</li>
          <li><strong>כניסות למבני המגורים:</strong> הכניסות ללובאים יפנו ככל הניתן לשצ"פ. במבנים שלא ניתן — נדרשת פתיחת מעבר להולכי רגל מהבניין לשצ"פ.</li>
          <li><strong>מעליות במבני המגורים:</strong> המעליות יוכלו להכיל זוג אופניים — דרישת מהנדס העיר.</li>
          <li><strong>מועדוני דיירים:</strong> יש לאפשר גישה גם מתוך השצ"פ/חזית הרחוב לייצור דופן עירונית פעילה (בתא 5 — הפיכת כיוון המועדונים במבנים A ו-B לכיוון המעבר הדרומי).</li>
          <li><strong>חדרי אופניים ועגלות:</strong> מומלץ לייצר יציאה חיצונית ישירה לשצ"פ/רחוב בנוסף לגישה דרך הלובי הראשי.</li>
        </ul>
      </div>
      <div class="architect-block" style="margin: 6mm 0; padding: 5mm 7mm; border: 1px solid #C8B6E0; border-right: 4px solid #5D3A9B; background: #F8F4FD; border-radius: 3px; page-break-inside: avoid;">
        <div style="font-size: 12pt; font-weight: 700; color: #3B2666; margin-bottom: 2mm;">הערות אדריכלית העיר — פרטני לתאי שטח</div>
        <div style="font-size: 9pt; color: #5D3A9B; margin-bottom: 4mm;">דו"ח מס' 1 · 02.06.2026 · הערות פר-תא שטח.</div>
        <table style="width: 100%; border-collapse: collapse; font-size: 9.5pt; direction: rtl;">
          <thead><tr>
            <th style="background: #ECE3F6; border: 1px solid #C8B6E0; padding: 2mm 3mm; color: #3B2666; text-align: right; width: 22%;">תא שטח</th>
            <th style="background: #ECE3F6; border: 1px solid #C8B6E0; padding: 2mm 3mm; color: #3B2666; text-align: right;">פירוט והנחיות</th>
          </tr></thead>
          <tbody>
            <tr>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top; font-weight: 600;">תא שטח 1</td>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top;">יש להוסיף מפלסים בחצרות הפרטיות ולהבהיר את המושג "דירת גן ללא ניקוז".<br><strong>רחבות כיבוי אש מתוכננות על גבי שטח גינון — כיצד יסתדרו השניים?</strong></td>
            </tr>
            <tr>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top; font-weight: 600;">תא שטח 2</td>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top;">נדרש להציג את ההקשרים הסביבתיים (מבנים קיימים, תוואי מדרכה מצפון וממזרח למבנה).</td>
            </tr>
            <tr>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top; font-weight: 600;">תא שטח 3</td>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top;">פורטל הכניסה מדרום חוסם לכאורה את המדרכה — נדרש תכנון המבטיח מעבר חופשי. <strong>המעבר ציר מזרח-מערב נראה כ"מסדרון"</strong> — מומלץ לשלב פתרונות נופיים/אורבניים שירככו את התחושה.</td>
            </tr>
            <tr>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top; font-weight: 600;">תא שטח 4</td>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top;">הכניסה לבניין A מסומנת מול חדר האשפה — <strong>יש לתקן</strong>. <strong>מבנה B מפנה חזית אטומה ("גב") לרחוב הצפוני</strong> — מומלץ לנצל חזית זו להפניית מעבר/חזית פעילה לרחוב.</td>
            </tr>
            <tr>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top; font-weight: 600;">הערה חוצה (תאים 3, 4, 5)</td>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top;">(ברנדה/אלן): קיימת תכנית לסגירת גדרות של דירות גן בקו "אפס" כלפי הרחוב. <strong>יש לקבוע מדיניות עירונית ברורה בנושא</strong>; במידה ומאושר, יש לקבוע פרט אדריכלי מחייב.</td>
            </tr>
          </tbody>
        </table>
      </div>
'''

# Replace the M7.9 architect-block div with these two blocks.
# Find the old div (single architect-block from M7.9). Bounds:
old_arch_start = html.find('<div class="architect-block"')
assert old_arch_start > 0, 'no architect-block div found'
old_arch_end = html.find('</div>', old_arch_start)
# walk forward — each architect-block div contains nested divs (header, body).
# Simpler: find the matching closing </div> by scanning balanced. Use the
# fact that the original block ends right before the next `<table class="audit">`
# closing or the next `<div class="subsection"` / `<div class="chapter"`.
# The M7.9 block ends with `</div>` immediately before
# `<div class="subsection"` or `<div class="chapter"`.
# Pragmatic: scan for `</div>` then check if next non-whitespace is `<div class="subsection"` or `<div class="chapter"`.
pos = old_arch_start
depth = 0
while pos < len(html):
    open_div = html.find('<div', pos)
    close_div = html.find('</div>', pos)
    if close_div < 0:
        raise RuntimeError('unbalanced architect-block')
    if 0 < open_div < close_div:
        depth += 1
        pos = open_div + 4
    else:
        depth -= 1
        pos = close_div + 6
        if depth == 0:
            old_arch_end = pos
            break

old_arch_html = html[old_arch_start:old_arch_end]
print(f'  C6 epilogue: identified old architect-block ({len(old_arch_html):,} chars)')
# Confirm it contains the M7.9-restored content as expected
assert 'מבני ציבור (מעונות וגנים)' in old_arch_html, 'expected מבני ציבור in old block'
html = html[:old_arch_start] + LEFTOVER_BLOCK.strip() + html[old_arch_end:]
print(f'  C6 + C7: replaced with כלליות + פרטני blocks ({len(LEFTOVER_BLOCK):,} chars)')
print(f'           (מבני ציבור block dropped per C7)')


# ────────────────────────────────────────────────────────────────────────────
# CHANGE 9 — Delete §4 chapter + amenity-clarification appendix (to </body>)
# ────────────────────────────────────────────────────────────────────────────
sec4_start = html.find('<div class="chapter" id="sec-4">')
assert sec4_start > 0, 'sec-4 chapter not found'
body_close = html.find('</body>', sec4_start)
n_removed = body_close - sec4_start
html = html[:sec4_start] + html[body_close:]
print(f'  C9: removed §4 + appendix ({n_removed:,} chars)')

# Also drop §4 from TOC
toc_pattern = re.compile(r'<tr><td class="title main"><a href="#sec-4">[^<]+</a></td><td class="page"><a href="#sec-4"></a></td></tr>')
n = len(toc_pattern.findall(html))
html = toc_pattern.sub('', html)
print(f'           removed §4 TOC entry: {n} row(s)')


SRC.write_text(html, encoding='utf-8')
print(f'\nOutput: {SRC} ({len(html):,} chars)')
