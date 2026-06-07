"""Part B HTML surgery — Ellen-handoff restructure of audit_report_24.3.html.

Reads the post-A baseline from /tmp/preB_baseline.html, applies B1-B8 in
order, writes the restructured HTML to /tmp/partB_result.html.

This is one-off code for this specific report run. NOT for engine main line.
"""
from __future__ import annotations
import re
from pathlib import Path

SRC = Path('/tmp/preB_baseline.html')
DST = Path('/tmp/partB_result.html')
html = SRC.read_text(encoding='utf-8')

# Track counts as we go. We'll print before/after at the end.
print(f'Input: {len(html):,} chars')

# ============================================================================
# Helper: remove a slice between markers
# ============================================================================
def cut(html_str: str, start_marker: str, end_marker: str, *, end_is_after: bool = True,
        find_from: int = 0) -> tuple[str, int]:
    """Return (html with [start_marker..end of end_marker] removed, removed_chars)."""
    i = html_str.find(start_marker, find_from)
    if i < 0:
        raise RuntimeError(f"start marker not found: {start_marker[:60]!r}")
    if end_is_after:
        # end_marker is "the next occurrence of <X" after start, marking where the
        # next block begins. Cut up to but not including end_marker.
        j = html_str.find(end_marker, i + len(start_marker))
        if j < 0:
            raise RuntimeError(f"end marker not found after start: {end_marker[:60]!r}")
    else:
        # end_marker terminates the block (e.g. closing </div>). Cut up to and
        # including end_marker.
        j = html_str.find(end_marker, i + len(start_marker))
        if j < 0:
            raise RuntimeError(f"end marker not found: {end_marker[:60]!r}")
        j += len(end_marker)
    return html_str[:i] + html_str[j:], j - i


# ============================================================================
# B1 — Remove the three summary-page divs (חסר / תיקונים / הבהרות)
# Keep cover-v2 (which contains the signature table) untouched.
# ============================================================================
# The three summary pages are siblings of cover-v2. They start with
# <div class="summary-page" id="summary-missing"> and end before the TOC chapter.
# Strategy: cut from `<div class="summary-page" id="summary-missing">` to
# the start of TOC `    <div class="chapter">\n      <div class="eyebrow">המינהלת...\n      <h2 class="chapter-num-title">תוכן עניינים</h2>`
TOC_START_MARKER = '<h2 class="chapter-num-title">תוכן עניינים</h2>'
# Walk back from TOC_START to the enclosing `<div class="chapter">`. That div
# precedes by ~30 chars (eyebrow + whitespace). We'll cut up to that div's
# opening tag.
toc_open_re = re.compile(
    r'<div class="chapter">\s*<div class="eyebrow">[^<]*</div>\s*<h2 class="chapter-num-title">תוכן עניינים</h2>',
    re.DOTALL,
)
m = toc_open_re.search(html)
if not m:
    raise RuntimeError('TOC opening pattern not found')
toc_open_pos = m.start()

summary_start = html.find('<div class="summary-page" id="summary-missing">')
if summary_start < 0:
    raise RuntimeError('summary-missing block not found')

removed_summary = toc_open_pos - summary_start
html = html[:summary_start] + html[toc_open_pos:]
print(f'B1 — summary front-matter removed: {removed_summary:,} chars')


# ============================================================================
# B2 — Remove תא שטח 9 (subsection 2.6) and renumber 2.7 → 2.6
# ============================================================================
# sec-2-6 is the plot-9 block. Cut it from start of `<div class="subsection" id="sec-2-6">`
# to the start of the next subsection or chapter.
sec_2_6_start = html.find('<div class="subsection" id="sec-2-6">')
sec_2_7_start = html.find('<div class="subsection" id="sec-2-7">', sec_2_6_start)
if sec_2_6_start < 0 or sec_2_7_start < 0:
    raise RuntimeError('sec-2-6/2-7 markers not found')
removed_plot9 = sec_2_7_start - sec_2_6_start
html = html[:sec_2_6_start] + html[sec_2_7_start:]
print(f'B2 — תא שטח 9 (sec-2-6) removed: {removed_plot9:,} chars')

# Renumber: sec-2-7 → sec-2-6 (id + TOC + heading text)
html = html.replace('id="sec-2-7"', 'id="sec-2-6"')
# The subsection heading currently says "2.7 בדיקות ברמת תכנית" — change to 2.6.
html = html.replace('2.7 בדיקות ברמת תכנית', '2.6 בדיקות ברמת תכנית')
print('B2 — sec-2-7 renumbered to sec-2-6 (plan-wide)')


# ============================================================================
# B3 — Remove §2א, §2ב, §2ג entirely
# ============================================================================
# Each is a `<div class="chapter ...-chapter" id="sec-...">` ending at the
# next chapter open. Easiest: cut from sec-m4-sidecar to sec-3.
sec2alpha_start = html.find('<div class="chapter sidecar-chapter" id="sec-m4-sidecar">')
sec3_start = html.find('<div class="chapter" id="sec-3">')
if sec2alpha_start < 0 or sec3_start < 0:
    raise RuntimeError('§2א or §3 marker not found')
removed_2abg = sec3_start - sec2alpha_start
html = html[:sec2alpha_start] + html[sec3_start:]
print(f'B3 — sections 2א/2ב/2ג removed: {removed_2abg:,} chars')


# ============================================================================
# B4 — Merge 3.7 (arch) + 3.8 (balcony) + 3.9 (laundry) into one section
# ============================================================================
# Strategy:
#   - Capture the <tbody> rows from 3.7, 3.8, 3.9
#   - Replace 3.7's heading with "אדריכלות וחזיתות" (already that title), keep its tbody
#     plus the rows from 3.8 + 3.9 appended
#   - Delete the entire 3.8 and 3.9 subsection divs

def extract_subsection_rows(html_str: str, sec_id: str) -> str:
    """Return the <tr>...</tr> rows inside a subsection's audit table tbody."""
    open_div = html_str.find(f'<div class="subsection" id="{sec_id}">')
    if open_div < 0:
        raise RuntimeError(f'subsection {sec_id} not found')
    # Find <tbody> ... </tbody> within this subsection
    tbody_start = html_str.find('<tbody>', open_div)
    tbody_end = html_str.find('</tbody>', tbody_start)
    return html_str[tbody_start + len('<tbody>'):tbody_end]

rows_3_8 = extract_subsection_rows(html, 'sec-3-8')
rows_3_9 = extract_subsection_rows(html, 'sec-3-9')

# Append 3.8 and 3.9 rows into 3.7's tbody (before </tbody>)
sec_3_7_open = html.find('<div class="subsection" id="sec-3-7">')
sec_3_7_tbody_end = html.find('</tbody>', sec_3_7_open)
html = html[:sec_3_7_tbody_end] + rows_3_8 + rows_3_9 + html[sec_3_7_tbody_end:]

# Delete 3.8 and 3.9 subsections in their entirety
for sec in ('sec-3-8', 'sec-3-9'):
    start = html.find(f'<div class="subsection" id="{sec}">')
    # The subsection closes with </div> matching the opening div. Use a small
    # regex with closing-div counting.
    # Simpler: each subsection follows a fixed pattern. Find the next
    # `<div class="subsection"` or chapter break.
    candidates = [
        html.find('<div class="subsection"', start + 1),
        html.find('<div class="chapter"', start + 1),
        html.find('<div class="appendix-divider', start + 1),
    ]
    candidates = [c for c in candidates if c > 0]
    next_block = min(candidates)
    html = html[:start] + html[next_block:]

print('B4 — sec-3-7 grew (absorbed 3.8 + 3.9 rows); sec-3-8 and sec-3-9 divs removed')


# ============================================================================
# B5 — Create תנועה section, move sec-3-4 content into it
# ============================================================================
# sec-3-4 was "3.4 רחבות כיבוי אש". After B4, the numbering is still original
# at this point — sec-3-4 still exists with that title. Strategy:
#   - Rewrite the subsection heading to "3.4 תנועה — רחבות כיבוי אש"
#     (single subsection inside §3, "discipline section" per user spec)
# That's literally all B5 needs at the structural level.
html = html.replace(
    '<h3 class="subsection-num">3.4 רחבות כיבוי אש</h3>',
    '<h3 class="subsection-num">3.4 תנועה — רחבות כיבוי אש</h3>',
)
print('B5 — sec-3-4 retitled: רחבות כיבוי אש → תנועה — רחבות כיבוי אש')


# ============================================================================
# B6 — Insert architect comments verbatim into the merged sec-3-7 section
# ============================================================================
# Per user instruction: omit section 2 "מבני ציבור (מעונות וגנים)" and keep
# the per-plot table (section 3 of the docx) intact. Block must be labeled
# "הערות אדריכלית העיר — דו"ח מס' 1, 02.06.2026" — verbatim, not subject
# to A1/A2 voice rewriting.

ARCHITECT_BLOCK = '''
      <div class="architect-block" style="margin: 8mm 0 6mm 0; padding: 6mm 8mm; border: 1px solid #C8B6E0; border-right: 4px solid #5D3A9B; background: #F8F4FD; border-radius: 3px; page-break-inside: avoid;">
        <div style="font-size: 13pt; font-weight: 700; color: #3B2666; margin-bottom: 2mm;">הערות אדריכלית העיר — דו"ח מס' 1, 02.06.2026</div>
        <div style="font-size: 9.5pt; color: #5D3A9B; margin-bottom: 5mm;">מסמך הערות לתכנית עיצוב — מתחם הטייסים (ההסתדרות), נס ציונה · תכנית מס' 407-1048248 · מתכננים: קיקה ברא"ז אדריכלים ומתכנני ערים</div>

        <h4 style="font-size: 12pt; font-weight: 700; color: #3B2666; margin: 4mm 0 2mm 0;">חלק א': פיתוח, העמדה וחיבוריות בקרקע</h4>
        <h5 style="font-size: 11pt; font-weight: 700; color: #3B2666; margin: 3mm 0 2mm 0;">1. הערות פיתוח כלליות למרחב הציבורי</h5>
        <ul style="font-size: 10pt; line-height: 1.6; color: #1a1a1a; margin: 1mm 0; padding-right: 7mm;">
          <li>פיתוח השצ"פ הינו בתאום מול אדריכל הנוף אהוד נדל – יש להשלים תהליך תאום.</li>
          <li>יש להוסיף נספח שימור/טיפול בעצים בתחום התב"ע.</li>
          <li>הקשר סביבתי: יש להשלים בתכניות את הבינוי והפיתוח במגרשים הגובלים (מחוץ לקו הכחול), המופיעים כעת כרקע לבן. כמו כן נדרש להבהיר את הקשר התכנוני, התנועתי והנופי לסביבה הקיימת והמתוכננת.</li>
          <li>חתכים במרחב השצ"פ: בחתכים מזרח-מערב החוצים את השצ"פ המרכזי, יש להציג את החתך ברציפות עד קו חזית המבנים מ-2 הצדדים, כולל מפלסי הפיתוח.</li>
          <li>רוחב דרכים וגינון: ניכר כי בחלק מהחתכים רוחב הדרך מכיל שבילי הליכה ואופניים בלבד ללא רצועות גינון, תוך יצירת "מעבר חומות" בין השצ"פ למבנים. יש לבחון שילוב רצועות גינון לאורך הדרכים, בהתאם לרוחב הזמין.</li>
          <li>פירוט מפלסים: יש לציין מפלסי פיתוח מוחלטים ויחסיים בכל החזיתות והחתכים הארוכים (כולל גדרות, פיתוח, מדרגות).</li>
          <li>רמפות לחניונים: יש להציג את תכנון ומופע הרמפות. אנו ממליצים לבחון שילוב של פרגולות מחופות צמחייה כדי למתן את המראה ה"אספלטי" של הרמפות במרחב הציבורי. (ראו תמונות מצורפות להמחשה — בקובץ המקור)</li>
        </ul>

        <h5 style="font-size: 11pt; font-weight: 700; color: #3B2666; margin: 4mm 0 2mm 0;">פונקציות בקומת הקרקע</h5>
        <ul style="font-size: 10pt; line-height: 1.6; color: #1a1a1a; margin: 1mm 0; padding-right: 7mm;">
          <li>רחבות גיזום: מה משמעותן בפועל? יש להציג תכנון וחזית כלפי הרחוב/השצ"פ לרבות פרטי הסתרה נאותים.</li>
          <li>רחבות כיבוי אש: יש למקם בתחום המגרש הפרטי ועם אפשרות לגינון.</li>
          <li>חדרי אשפה: נדרש תאום מלא מול מחלקת שפ"ע.</li>
          <li>הצגת חדר הטרפו והמופע שלו בתנוחה ובחתך.</li>
          <li>כניסות למבני המגורים: הכניסות ללובאים יפנו ככל הניתן לשצ"פ. במבנים שלא ניתן, נדרשת פתיחת מעבר להולכי רגל מהבניין לשצ"פ.</li>
          <li>מעליות במבני המגורים יוכלו להכיל זוג אופניים – דרישת מהנדס העיר.</li>
          <li>מועדוני דיירים: יש לאפשר גישה גם מתוך השצ"פ/חזית הרחוב כדי לייצר דופן עירונית פעילה. (בתא 5 למשל, הפיכת כיוון המועדונים לפנות חוצה אל השצ"פ.)</li>
          <li>חדרי אופניים ועגלות: מומלץ לייצר יציאה חיצונית ישירה לשצ"פ/רחוב בנוסף לגישה דרך הלובי הראשי.</li>
          <li>מערכות: יש להציג בצורה מובחנת את מיקומי פתרי אוורור החניונים, חדרי טרפו, מאגרי גז ומתקני אשפה.</li>
        </ul>

        <h5 style="font-size: 11pt; font-weight: 700; color: #3B2666; margin: 4mm 0 2mm 0;">3. הערות פרטניות לתאי השטח</h5>
        <table style="width: 100%; border-collapse: collapse; margin: 2mm 0 4mm 0; font-size: 9.5pt; direction: rtl;">
          <thead>
            <tr>
              <th style="background: #ECE3F6; border: 1px solid #C8B6E0; padding: 2mm 3mm; color: #3B2666; text-align: right; width: 22%;">תא שטח</th>
              <th style="background: #ECE3F6; border: 1px solid #C8B6E0; padding: 2mm 3mm; color: #3B2666; text-align: right;">פירוט והנחיות</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top; font-weight: 600;">תא שטח 1</td>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top;">יש להוסיף מפלסים בחצרות הפרטיות ולהבהיר את המושג "דירת גן ללא ניקוז".<br>רחבות כיבוי אש: יש למקם בתחום המגרש הפרטי.</td>
            </tr>
            <tr>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top; font-weight: 600;">תא שטח 2</td>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top;">נדרש להציג את ההקשרים הסביבתיים (מבנים קיימים, תוואי מדרכה מצפון וממזרח למבנה).</td>
            </tr>
            <tr>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top; font-weight: 600;">תא שטח 3</td>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top;">פורטל הכניסה מדרום חוסם לכאורה את המדרכה — נדרש תכנון המבטיח מעבר חופשי.<br>המעבר צריך להישאר ברוחב הדרוש לפי הנחיות התנועה.</td>
            </tr>
            <tr>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top; font-weight: 600;">תא שטח 4</td>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top;">הכניסה לבניין A מסומנת מול חדר האשפה (יש לתקן).<br>מבנה B מפנה חזית אטומה ("גב") לרחוב — יש לפתוח אותה למרחב הציבורי.</td>
            </tr>
            <tr>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top; font-weight: 600;">הערה חוצה (תאים 3, 4, 5)</td>
              <td style="border: 1px solid #DCD0EC; padding: 2mm 3mm; vertical-align: top;">(ברנדה/אלן): קיימת תכנית לסגירת גדרות של דירות גן בקו "אפס" כלפי הרחוב. יש לקבוע מדיניות אחידה למפלסי הגדרות, יחס לפיתוח הציבורי וטיפול בקשר ויזואלי לרחוב.</td>
            </tr>
          </tbody>
        </table>

        <h4 style="font-size: 12pt; font-weight: 700; color: #3B2666; margin: 6mm 0 2mm 0;">חלק ב': עיצוב חזיתות המבנים ושפה אדריכלית</h4>
        <p style="font-size: 10pt; line-height: 1.6; color: #1a1a1a; margin: 1.5mm 0;">אנו מעריכים את המאמץ והחשיבה שהושקעו בתכנון על מנת לייצר סביבת מגורים ייחודית ולשבור את המאסות הבנויות. יחד עם זאת, ניכר כי השפה האדריכלית הנוכחית עמוסה ויש מקום ללטשה ולהפיכתה ליותר מאופקת.</p>

        <h5 style="font-size: 11pt; font-weight: 700; color: #3B2666; margin: 4mm 0 2mm 0;">1. השקטת החזיתות והשפה החומרית</h5>
        <ul style="font-size: 10pt; line-height: 1.6; color: #1a1a1a; margin: 1mm 0; padding-right: 7mm;">
          <li>עומס ויזואלי: העיצוב הנוכחי מתאפיין בריבוי אלמנטים ("קופסתיות"), חומרים וקפיצות במפלסי החלונות. שילוב של רפפות שחורות, אלמנטים כהים וגיוון רב יוצר עומס. מומלץ למתן את האלמנטים, להפחית את מספר הצבעוניות והחומרים, ולהשתמש בשפה אחידה ומאופקת.</li>
          <li>צבעוניות: השימוש הנרחב באלמנטים כהים, חיפויים שחורים וזכוכיות כהות, יוצר מופע כללי מעט כבד. מומלץ לבחון חלופות של זיגוג בהיר יותר וחיפויים בגוונים טבעיים.</li>
        </ul>

        <h5 style="font-size: 11pt; font-weight: 700; color: #3B2666; margin: 4mm 0 2mm 0;">2. עיצוב המרפסות</h5>
        <ul style="font-size: 10pt; line-height: 1.6; color: #1a1a1a; margin: 1mm 0; padding-right: 7mm;">
          <li>מסגור אלמנטים: השימוש בעמודים ופרגולות ענק הממסגרים את המרפסות יוצר משקל ויזואלי כבד. בנוסף, קורות מרחפות בולטות עשויות ליצור תחושה של אי-יציבות. מומלץ לשקול הקטנה של ממדי המסגרת ואת היחס בין המסגרת לפתח המרפסת.</li>
          <li>מרפסות זיזיות: נשמח לבחון גישה עיצובית של מרפסות "משוחררות" וזיזיות יותר, אשר אינן כלואות בתוך מסגרות קשיחות. בתכנון חלופי, ניתן לבחון מרפסות הפונות לכיוונים שונים ובגדלים שונים.</li>
        </ul>

        <h5 style="font-size: 11pt; font-weight: 700; color: #3B2666; margin: 4mm 0 2mm 0;">3. הנחיות להגשת תוצרים לשלב הבא</h5>
        <p style="font-size: 10pt; line-height: 1.6; color: #1a1a1a; margin: 1.5mm 0;">על מנת שנוכל לבחון את החלופות בצורה מדויקת, אנו מבקשים:</p>
        <ul style="font-size: 10pt; line-height: 1.6; color: #1a1a1a; margin: 1mm 0; padding-right: 7mm;">
          <li>הגשת אבטיפוס: במקום להציג את כלל המבנים יחד, אנו מבקשים לפתח ולעבד עד רמת פירוט גבוהה יותר בניין אבטיפוס יחיד. הבניין יוצג עם פירוט מלא של חזיתות, חומרים, מרפסות, ופרטי גמר.</li>
          <li>חלופות עיצוביות: יש להציג 2-3 חלופות קונספטואליות לחזית הבניין, מלוות בהסבר מתודולוגי קצר. החלופות יתייחסו להערות לעיל (השקטה, צבעוניות, מרפסות).</li>
          <li>דיוק בהדמיות: רצוי לספק מספר מצומצם של הדמיות איכותיות ומדויקות, אשר מציינות באופן ברור את כיוון המבט, תא השטח המצולם (כפי שמופיע בתב"ע), והגובה הרלוונטי. נא לכלול הדמיה לפחות אחת ממפלס הקרקע (גובה הולך רגל).</li>
        </ul>

        <p style="font-size: 10pt; line-height: 1.6; color: #1a1a1a; margin: 4mm 0 1mm 0; font-style: italic;">אנו עומדים לרשותכם לכל התייעצות או הבהרה.<br>מנהלת התחדשות עירונית, נס ציונה.</p>
      </div>
'''

# Insert the architect block at the end of sec-3-7 (merged אדריכלות) — right
# before the closing </div> of the subsection. The subsection ends with
# `</table>\n    </div>` (table + close).
sec_3_7_open = html.find('<div class="subsection" id="sec-3-7">')
# Find the </div> that closes this subsection. The structure is:
#   <div class="subsection" id="sec-3-7">
#     <h3>...</h3>
#     <table class="audit">...</table>
#   </div>
sec_3_7_table_end = html.find('</table>', sec_3_7_open)
# The closing </div> of the subsection follows shortly (whitespace + </div>).
sec_3_7_close_div = html.find('</div>', sec_3_7_table_end)
# Insert architect block AFTER </table> and BEFORE the closing </div>.
insert_at = sec_3_7_table_end + len('</table>')
html = html[:insert_at] + ARCHITECT_BLOCK + html[insert_at:]
print(f'B6 — architect block inserted into sec-3-7: +{len(ARCHITECT_BLOCK):,} chars')


# ============================================================================
# B7 — Remove §5 and נספח א (everything from id="sec-5" to end of body)
# ============================================================================
sec5_start = html.find('<div class="chapter" id="sec-5">')
if sec5_start < 0:
    raise RuntimeError('§5 marker not found')
# Find the end of body
body_close = html.find('</body>', sec5_start)
removed_5_app = body_close - sec5_start
html = html[:sec5_start] + html[body_close:]
print(f'B7 — §5 + נספח א removed: {removed_5_app:,} chars')


# ============================================================================
# Trim §1 abstract — drop references to §5 and נספח א (now removed)
# ============================================================================
html = html.replace(
    'פרק 4 — סיכום הפעולות הנדרשות. פרק 5 — היקף הסקירה. נספח א — ליקויי פורמט בחוברת ההגשה.',
    'פרק 4 — סיכום הפעולות הנדרשות.',
)
print('§1 abstract — trimmed refs to §5 + נספח א')


# ============================================================================
# Rewrite the TOC entirely with the new structure + numbering
# ============================================================================
NEW_TOC_ROWS = '''<tr><td class="title main"><a href="#sec-1">1. ניתוח תכנון עירוני</a></td><td class="page"><a href="#sec-1"></a></td></tr><tr><td class="title main"><a href="#sec-2">2. בדיקת תאימות תוכן לתב"ע 407-1048248</a></td><td class="page"><a href="#sec-2"></a></td></tr><tr><td class="title sub"><a href="#sec-2-1">2.1 תא שטח 1</a></td><td class="page"><a href="#sec-2-1"></a></td></tr><tr><td class="title sub"><a href="#sec-2-2">2.2 תא שטח 2</a></td><td class="page"><a href="#sec-2-2"></a></td></tr><tr><td class="title sub"><a href="#sec-2-3">2.3 תא שטח 3</a></td><td class="page"><a href="#sec-2-3"></a></td></tr><tr><td class="title sub"><a href="#sec-2-4">2.4 תא שטח 4</a></td><td class="page"><a href="#sec-2-4"></a></td></tr><tr><td class="title sub"><a href="#sec-2-5">2.5 תא שטח 5</a></td><td class="page"><a href="#sec-2-5"></a></td></tr><tr><td class="title sub"><a href="#sec-2-6">2.6 בדיקות ברמת תכנית</a></td><td class="page"><a href="#sec-2-6"></a></td></tr><tr><td class="title main"><a href="#sec-3">3. בדיקה רב-תחומית לפי חוברת הנחיות עירונית</a></td><td class="page"><a href="#sec-3"></a></td></tr><tr><td class="title sub"><a href="#sec-3-1">3.1 שפ"ע — אשפה ופינוי פסולת</a></td><td class="page"><a href="#sec-3-1"></a></td></tr><tr><td class="title sub"><a href="#sec-3-2">3.2 גנים ונוף</a></td><td class="page"><a href="#sec-3-2"></a></td></tr><tr><td class="title sub"><a href="#sec-3-3">3.3 תשתיות</a></td><td class="page"><a href="#sec-3-3"></a></td></tr><tr><td class="title sub"><a href="#sec-3-4">3.4 תנועה — רחבות כיבוי אש</a></td><td class="page"><a href="#sec-3-4"></a></td></tr><tr><td class="title sub"><a href="#sec-3-5">3.5 ניקוז וחלחול</a></td><td class="page"><a href="#sec-3-5"></a></td></tr><tr><td class="title sub"><a href="#sec-3-6">3.6 גגות וגינון על גג</a></td><td class="page"><a href="#sec-3-6"></a></td></tr><tr><td class="title sub"><a href="#sec-3-7">3.7 אדריכלות וחזיתות</a></td><td class="page"><a href="#sec-3-7"></a></td></tr><tr><td class="title sub"><a href="#sec-3-10">3.8 הנחיות סביבתיות</a></td><td class="page"><a href="#sec-3-10"></a></td></tr><tr><td class="title sub"><a href="#sec-3-amenities">3.9 שירותים לדיירים</a></td><td class="page"><a href="#sec-3-amenities"></a></td></tr><tr><td class="title main"><a href="#sec-4">4. סיכום וממצאים סופיים</a></td><td class="page"><a href="#sec-4"></a></td></tr>'''
# Replace the existing TOC tbody content. The current TOC starts with the
# big single line containing all the <tr> rows. Find that and replace.
toc_table_open_re = re.compile(r'<table class="toc">\s*', re.DOTALL)
toc_table_close = '</table>'
m = toc_table_open_re.search(html)
if not m:
    raise RuntimeError('TOC table not found')
toc_content_start = m.end()
toc_content_end = html.find(toc_table_close, toc_content_start)
html = html[:toc_content_start] + NEW_TOC_ROWS + '\n      ' + html[toc_content_end:]
print('TOC — rewritten with new numbering (no 2.6 plot 9, no §2א/ב/ג, no §5, no נספח)')


# Rewrite remaining §3.x subsection-num headings to match new numbering.
# After B4 + B5 + section removals, the actual elements still have their
# original numbering in their <h3> text. Reassign:
# Old → new heading text:
heading_renames = [
    ('3.10 הנחיות סביבתיות', '3.8 הנחיות סביבתיות'),
    ('3.11 שירותים לדיירים', '3.9 שירותים לדיירים'),
]
for old, new in heading_renames:
    html = html.replace(old, new)


# ============================================================================
# Trim "(DWG)" tail from "לפי תשריט (DWG)" schema cells (per A3)
# ============================================================================
html = html.replace('לפי תשריט (DWG)', 'לפי תשריט')
# Also: §3.11 amenity-table audit_note that mentions "מנוע הציות"
html = html.replace('נבדק כתקין במסגרת מנוע הציות', 'נבדק כתקין')


# ============================================================================
# B8 — Recompute count badges by walking surviving content
# ============================================================================
# Each <table class="audit"> row has a <td><span class="v-XXX">label</span></td>
# Plus we need the §3 amenity table (different structure — no verdicts).
# Plus §2's plan-wide subsection.

# Strategy: parse each chapter's content, count verdict-class hits.
# Verdict classes: v-ok (pass), v-fail (fail/not-submitted), v-rev (req-review),
# v-na (n/a), v-miss (missing).
# Map to badge buckets (per existing badge code):
#   §2 (content): ok / fail / review / unknown / na
#   §3 (discipline): ok / fail / review / unknown
#   §4 final summary: total ok / total fail / total review

# Use regex over chapter slices.
def count_verdicts(html_slice: str) -> dict[str, int]:
    counts = {'v-ok': 0, 'v-fail': 0, 'v-rev': 0, 'v-na': 0, 'v-miss': 0}
    for cls in counts:
        # Match <span class="v-XX">...</span> regardless of trailing text
        counts[cls] = len(re.findall(rf'class="{cls}">', html_slice))
    return counts

# Bound each chapter
sec2_open = html.find('<div class="chapter" id="sec-2">')
sec3_open = html.find('<div class="chapter" id="sec-3">')
sec4_open = html.find('<div class="chapter" id="sec-4">')
sec_after = html.find('</body>')

sec2_slice = html[sec2_open:sec3_open]
sec3_slice = html[sec3_open:sec4_open]

c2 = count_verdicts(sec2_slice)
c3 = count_verdicts(sec3_slice)

# §2 has its badges table BEFORE its subsections — at the top of the chapter.
# Need to count rows INSIDE its subsection tables, not the chapter-level badges.
# But badges contain digit text wrapped in <div class="num">N</div>. The verdict
# rows inside audit tables are what we count. Since the badge cells don't carry
# `class="v-XX"`, our count_verdicts() correctly tallies only the row verdicts.

# Map to badge cell labels (in existing badge tables):
# §2 cells (5): ok / fail / review / unknown / na
# §3 cells (4): ok / fail / review / unknown
# §4 final cells (3): ok (pass) / fail / review

# §4 totals = §2 (excluding na, per engine) + §3 totals
sec2_ok = c2['v-ok']
sec2_fail = c2['v-fail'] + c2['v-miss']  # missing = not_submitted = fail bucket
sec2_review = c2['v-rev']
sec2_unknown = 0  # v-na NOT shown as "unknown" in this engine; engine maps "unevaluable"→unknown but rare
sec2_na = c2['v-na']

sec3_ok = c3['v-ok']
sec3_fail = c3['v-fail'] + c3['v-miss']
sec3_review = c3['v-rev']
sec3_unknown = 0

final_ok = sec2_ok + sec3_ok
final_fail = sec2_fail + sec3_fail
final_review = sec2_review + sec3_review

print()
print('=== B8 RECOMPUTED COUNTS ===')
print(f'§2 verdict-row tally: v-ok={c2["v-ok"]}, v-fail={c2["v-fail"]}, v-rev={c2["v-rev"]}, v-na={c2["v-na"]}, v-miss={c2["v-miss"]}')
print(f'  → §2 badges: ok={sec2_ok}, fail={sec2_fail}, review={sec2_review}, unknown={sec2_unknown}, na={sec2_na}')
print(f'§3 verdict-row tally: v-ok={c3["v-ok"]}, v-fail={c3["v-fail"]}, v-rev={c3["v-rev"]}, v-na={c3["v-na"]}, v-miss={c3["v-miss"]}')
print(f'  → §3 badges: ok={sec3_ok}, fail={sec3_fail}, review={sec3_review}, unknown={sec3_unknown}')
print(f'§4 final badges: ok={final_ok}, fail={final_fail}, review={final_review}')


# Replace the badge numbers. The badges are rendered as:
#   <td class="ok"><div class="num">N</div><div class="label">תקינים בתוכן</div></td>
# We need to surgically rewrite the N for each badge cell. The labels are:
#   §2: "תקינים בתוכן", "ליקויים בתוכן", "דורשים בירור", "לא ניתנים לבדיקה", "לא רלוונטיים"
#   §3: "תקינים במדיניות", "סטיות ממדיניות", "דורשים בירור", "לא ניתנים לבדיקה"
#   §4: "תקינים", "נדרשים תיקונים", "דורשים בירור"

def replace_badge(html_str: str, label_he: str, new_n: int, scope_start: int, scope_end: int) -> str:
    """Find the badge cell with `label_he` within [scope_start, scope_end] and
    replace its <div class="num">N</div> value with new_n."""
    scope = html_str[scope_start:scope_end]
    # Pattern: <td class="X"><div class="num">DIGITS</div><div class="label">label_he</div></td>
    pat = re.compile(
        r'(<td class="[a-z]+"><div class="num">)\d+(</div><div class="label">' + re.escape(label_he) + r'</div></td>)'
    )
    new_scope, n_subs = pat.subn(rf'\g<1>{new_n}\g<2>', scope, count=1)
    if n_subs == 0:
        print(f'  ⚠ badge "{label_he}" not found in scope (expected 1; got 0)')
        return html_str
    return html_str[:scope_start] + new_scope + html_str[scope_end:]

# Re-locate chapter bounds AFTER all the prior edits (offsets shifted).
sec2_open = html.find('<div class="chapter" id="sec-2">')
sec3_open = html.find('<div class="chapter" id="sec-3">')
sec4_open = html.find('<div class="chapter" id="sec-4">')
sec_end = html.find('</body>', sec4_open)

# §2 badges
html = replace_badge(html, 'תקינים בתוכן', sec2_ok, sec2_open, sec3_open)
html = replace_badge(html, 'ליקויים בתוכן', sec2_fail, sec2_open, sec3_open)
html = replace_badge(html, 'דורשים בירור', sec2_review, sec2_open, sec3_open)
html = replace_badge(html, 'לא ניתנים לבדיקה', sec2_unknown, sec2_open, sec3_open)
html = replace_badge(html, 'לא רלוונטיים', sec2_na, sec2_open, sec3_open)

# Re-locate after each edit (offsets shifted)
sec3_open = html.find('<div class="chapter" id="sec-3">')
sec4_open = html.find('<div class="chapter" id="sec-4">')

# §3 badges
html = replace_badge(html, 'תקינים במדיניות', sec3_ok, sec3_open, sec4_open)
html = replace_badge(html, 'סטיות ממדיניות', sec3_fail, sec3_open, sec4_open)
html = replace_badge(html, 'דורשים בירור', sec3_review, sec3_open, sec4_open)
html = replace_badge(html, 'לא ניתנים לבדיקה', sec3_unknown, sec3_open, sec4_open)

# Re-locate §4 bounds
sec4_open = html.find('<div class="chapter" id="sec-4">')
sec_end = html.find('</body>', sec4_open)

# §4 badges
html = replace_badge(html, 'תקינים', final_ok, sec4_open, sec_end)
html = replace_badge(html, 'נדרשים תיקונים', final_fail, sec4_open, sec_end)
html = replace_badge(html, 'דורשים בירור', final_review, sec4_open, sec_end)


# ============================================================================
# §4 priority items — drop "תא שטח 9" mentions, drop items only about removed
# content. Renumber the surviving items.
# ============================================================================
# Priority items are <li>1. <strong>title</strong> body</li> in the ordered
# list `ol.priority-list`. Strategy: parse the list, drop items mentioning
# "תא שטח 9", renumber, write back.

m_ol_start = re.search(r'<ol class="priority-list">', html)
m_ol_end = re.search(r'</ol>', html[m_ol_start.end():])
ol_start_pos = m_ol_start.end()
ol_end_pos = m_ol_start.end() + m_ol_end.start()
ol_content = html[ol_start_pos:ol_end_pos]
# Each item: <li>N. <strong>title</strong> body</li>
items = re.findall(r'<li>.*?</li>', ol_content, re.DOTALL)
print(f'\n§4 priority list — {len(items)} items before filter')

surviving = []
for it in items:
    # Drop items whose title or body mentions "תא שטח 9" — they're about the removed plot
    if 'תא שטח 9' in it:
        # Try to keep it if it ALSO references other plots. Check the
        # comma-separated plot list (e.g. "תא שטח 9, תא שטח 5").
        # Heuristic: if the item lists other plots, strip "תא שטח 9" from
        # the list; else drop the item entirely.
        cleaned = re.sub(r'תא שטח 9(?:\s*\([^)]*\))?[,\s]*', '', it)
        # If the cleaned version no longer says "תא שטח" at all, the item was
        # only about plot 9 — drop. Otherwise keep cleaned.
        if 'תא שטח' in cleaned and 'תא שטח 9' not in cleaned:
            surviving.append(cleaned)
            print(f'  cleaned: "תא שטח 9" stripped from list-style item')
        else:
            print(f'  dropped: {it[:80]}...')
            continue
    else:
        surviving.append(it)
print(f'§4 priority list — {len(surviving)} items after filter')

# Renumber. Each item starts with "<li>N. <strong>..." — replace the digit.
renumbered = []
for i, it in enumerate(surviving, start=1):
    new = re.sub(r'^<li>\d+\.\s', f'<li>{i}. ', it, count=1)
    renumbered.append(new)

html = html[:ol_start_pos] + ''.join(renumbered) + html[ol_end_pos:]


# Write result
DST.write_text(html, encoding='utf-8')
print(f'\nOutput: {DST} ({len(html):,} chars)')
print(f'Delta from input: {len(html) - SRC.stat().st_size:+,} chars')
