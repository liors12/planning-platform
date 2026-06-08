"""M8.2 one-off surgery on M8.1 HTML — 5 targeted fixes resolving the
contradiction + 3 redundancies from M8.1's sweep."""
from __future__ import annotations
from pathlib import Path

SRC = Path('audit_outputs/407-1048248/v24.3/audit_report_24.3.html')
html = SRC.read_text(encoding='utf-8')
print(f'Input: {len(html):,} chars')


# ────────────────────────────────────────────────────────────────────────────
# C1 — Balcony row status תקין → נדרשת השלמה
# ────────────────────────────────────────────────────────────────────────────
OLD_C1 = '''<tr>
      <td><b>עיצוב מרפסות משולב בחזית</b><br>יש להציג עיצוב מרפסות משולב במלואו בחזית, עם פירוט מעקות וחומריות.</td>
      <td>המרפסות נראות משולבות בחזית עם מעקים בנויים בצבע ובחומר תואמים למעטפת הכללית</td>
      <td><span class="v-ok">תקין</span></td>
      <td>תואם <span class="page-ref">(עמ' 52, 53, 54, 58, 60, 62, 63)</span></td>
    </tr>'''
NEW_C1 = '''<tr>
      <td><b>עיצוב מרפסות משולב בחזית</b><br>יש להציג עיצוב מרפסות משולב במלואו בחזית, עם פירוט מעקות וחומריות.</td>
      <td>המרפסות נראות משולבות בחזית עם מעקים בנויים בצבע ובחומר תואמים למעטפת הכללית</td>
      <td><span class="v-rev">נדרשת השלמה</span></td>
      <td>תואם <span class="page-ref">(עמ' 52, 53, 54, 58, 60, 62, 63)</span></td>
    </tr>'''
n = html.count(OLD_C1)
assert n == 1, f'C1: expected 1, got {n}'
html = html.replace(OLD_C1, NEW_C1)
print('  ✓ C1: balcony status תקין → נדרשת השלמה')


# ────────────────────────────────────────────────────────────────────────────
# C2 — Landscape strip row: adopt architect's "מעבר חומות" framing
# ────────────────────────────────────────────────────────────────────────────
OLD_C2 = '''<tr>
      <td><b>רצועת גינון רחבה הצמודה למגרש</b><br>יש לסמן בתכנית הפיתוח רצועת גינון ברוחב 2 מ' לפחות בגבול המגרש, ולציין את שטחה.</td>
      <td>בתוכניות הפיתוח נראית רצועה ירוקה בין קו המגרש (קו כחול מקווקו) לבין הכביש/מדרכה, עם עצים מסומנים</td>
      <td><span class="v-rev">נדרשת השלמה</span></td>
      <td>נדרשת מדידה לוודא ≥2מ ומיקום עצים <span class="page-ref">(עמ' 10, 24, 34, 39, 44)</span></td>
    </tr>'''
# Replace הערה cell with architect's framing (condensed from docx [12]) +
# preserve the ≥2מ requirement from the engine row + the page-ref.
NEW_C2 = '''<tr>
      <td><b>רצועת גינון רחבה הצמודה למגרש</b><br>יש לסמן בתכנית הפיתוח רצועת גינון ברוחב 2 מ' לפחות בגבול המגרש, ולציין את שטחה.</td>
      <td>בחלק מהחתכים (לדוגמה חתכים א-א בתאי שטח 3 ו-5) רוחב הדרך מכיל שבילי הליכה ואופניים בלבד ללא רצועות גינון, יוצר "מעבר חומות" דו-צדדי</td>
      <td><span class="v-rev">נדרשת השלמה</span></td>
      <td>יש להציג פתרון תכנוני (הרחבת שטח, דירוג טופוגרפי וכד') לרצועת גינון ברוחב ≥2מ הצמודה למגרש; ולספק פרט אדריכלי מחייב לסגירת דירות הגן (חומריות, חתך, אפשרות הגבהה מוסדרת). <span class="page-ref">(עמ' 10, 24, 34, 39, 44)</span></td>
    </tr>'''
n = html.count(OLD_C2)
assert n == 1, f'C2: expected 1, got {n}'
html = html.replace(OLD_C2, NEW_C2)
print('  ✓ C2: landscape strip — adopted "מעבר חומות" framing, ≥2מ preserved')


# ────────────────────────────────────────────────────────────────────────────
# C3 — Fire-staging §3.4: merge engine + architect into one row
# ────────────────────────────────────────────────────────────────────────────
# Step 3a — update the engine row's action text (keep title + state) and
# add the (הערת אדריכלית העיר) tag since the architect content is now merged in.
OLD_C3A = '''<tr>
      <td><b>רחבת כיבוי בתחום המגרש הפרטי</b><br>יש לסמן רחבת כיבוי אש בתוך תחום המגרש הפרטי בכל תא שטח, בהתאם להנחיות כיבוי אש.</td>
      <td>בעמ' 25 (תא שטח 1) הרחבות החומות נראות בתוך גבולות המגרש (בין הבניינים)</td>
      <td><span class="v-rev">נדרשת השלמה</span></td>
      <td>יש לציין במפורש את מיקום רחבות הכיבוי ביחס לגבול המגרש, ובמיוחד בתאי שטח 2, 4 ו-5 <span class="page-ref">(עמ' 25, 35, 40, 44)</span></td>
    </tr>'''
NEW_C3A = '''<tr>
      <td><b>רחבת כיבוי בתחום המגרש הפרטי — (הערת אדריכלית העיר)</b><br>יש לסמן רחבת כיבוי אש בתוך תחום המגרש הפרטי בכל תא שטח, בהתאם להנחיות כיבוי אש.</td>
      <td>בעמ' 25 (תא שטח 1) הרחבות החומות נראות בתוך גבולות המגרש (בין הבניינים)</td>
      <td><span class="v-rev">נדרשת השלמה</span></td>
      <td>יש למקם את רחבות הכיבוי בתחום המגרש הפרטי, עם אפשרות לגינון; לציין במפורש מיקום ביחס לגבול המגרש, ובמיוחד בתאי שטח 2, 4 ו-5. <span class="page-ref">(עמ' 25, 35, 40, 44)</span></td>
    </tr>'''
n = html.count(OLD_C3A)
assert n == 1, f'C3a: expected 1, got {n}'
html = html.replace(OLD_C3A, NEW_C3A)
print('  ✓ C3a: engine fire-staging row — merged architect content + tag')

# Step 3b — delete the standalone architect fire-staging row
OLD_C3B = '''<tr>
      <td><b>רחבות כיבוי בתחום המגרש — (הערת אדריכלית העיר)</b><br>רחבות כיבוי אש ימוקמו בתחום המגרש הפרטי, עם אפשרות לגינון.</td>
      <td>—</td>
      <td><span class="v-rev">נדרשת השלמה</span></td>
      <td>יש למקם את רחבות הכיבוי בתחום המגרש הפרטי, עם אפשרות לגינון.</td>
    </tr>'''
n = html.count(OLD_C3B)
assert n == 1, f'C3b: expected 1, got {n}'
html = html.replace(OLD_C3B, '', 1)
# Clean up the blank line left behind
html = html.replace('    \n    \n    \n      \n      ', '    \n      ')
print('  ✓ C3b: dropped standalone architect fire-staging row')


# ────────────────────────────────────────────────────────────────────────────
# C4 — Waste §3.1: fold architect coordination row into floor-level row
# ────────────────────────────────────────────────────────────────────────────
# The "חדרי פסולת קומתיים" engine row is the closest topical match.
# Append the architect coordination instruction to its action cell.
OLD_C4A_FRAG = '''יש לציין על תכניות הקומות הטיפוסיות את מיקום חדרי איסוף הפסולת או שוטי הפסולת בכל קומה, ולסמנם בלגנדה <span class="page-ref">'''
NEW_C4A_FRAG = '''יש לציין על תכניות הקומות הטיפוסיות את מיקום חדרי איסוף הפסולת או שוטי הפסולת בכל קומה, ולסמנם בלגנדה. (הערת אדריכלית העיר) יש להשלים תיאום מלא של חדרי האשפה מול מחלקת שפ"ע. <span class="page-ref">'''
n = html.count(OLD_C4A_FRAG)
assert n == 1, f'C4 merge fragment: expected 1, got {n}'
html = html.replace(OLD_C4A_FRAG, NEW_C4A_FRAG)
print('  ✓ C4a: folded architect coordination into חדרי פסולת קומתיים row')

# Delete the standalone architect waste-coordination row
OLD_C4B = '''<tr>
      <td><b>תיאום חדרי אשפה — (הערת אדריכלית העיר)</b><br>יש לוודא שמיקום ותכנון חדרי האשפה תואמים את דרישות שפ"ע.</td>
      <td>—</td>
      <td><span class="v-rev">נדרשת השלמה</span></td>
      <td>יש להשלים תיאום מלא של חדרי האשפה מול מחלקת שפ"ע.</td>
    </tr>'''
n = html.count(OLD_C4B)
assert n == 1, f'C4b: expected 1, got {n}'
html = html.replace(OLD_C4B, '', 1)
print('  ✓ C4b: dropped standalone architect waste-coordination row')


# ────────────────────────────────────────────────────────────────────────────
# C5 — Per-plot block plot 1: replace fire-staging sentence with verbatim docx wording
# ────────────────────────────────────────────────────────────────────────────
OLD_C5 = 'רחבות כיבוי אש מתוכננות על גבי שטח גינון — כיצד יסתדרו השניים?'
NEW_C5 = 'רחבות כיבוי אש מתוכננות על גבי שטח גינון — כיצד יסומנו וכיצד יתאפשר תפקודן ללא פגיעה בפיתוח?'
n = html.count(OLD_C5)
assert n == 1, f'C5: expected 1, got {n}'
html = html.replace(OLD_C5, NEW_C5)
print('  ✓ C5: per-plot תא 1 fire-staging — adopted docx wording')


SRC.write_text(html, encoding='utf-8')
print(f'\nOutput: {SRC} ({len(html):,} chars)')
