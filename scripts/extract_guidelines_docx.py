#!/opt/homebrew/bin/python3.13
"""Extract the approved municipal guidelines docx into the seed JSON.

One-shot generator for app/sidecar/seed/guidelines_seed.json:
walks the document body in order (paragraphs + tables interleaved),
one guideline row per requirement paragraph / table data row, VERBATIM
body text (hyphen normalization only). Section structure = the document's
own Heading-2 parts, in document order.

check_keys: ONLY the 7 pre-existing engine keys are attached, mapped to the
document rows that carry their values. No new keys are invented.

Deliberate skips are collected and printed for the QA report (gate A).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs/הנחיות_עיצוב_נס_ציונה_לגוגל_דוקס.docx"
OUT = ROOT / "app/sidecar/seed/guidelines_seed.json"

SECTION_KEYS = {
    "חלק א": "part_a", "חלק ב": "part_b", "חלק ג": "part_c", "חלק ד": "part_d",
    "חלק ה": "part_e", "חלק ו": "part_f", "חלק ז": "part_g", "חלק ח": "part_h",
    "נספח א": "appendix_a", "נספח ב": "appendix_b",
}

# The 7 existing engine check_keys, mapped to the document rows that carry
# them. Matching is by (section_key, substring of the row's body/title).
# The two PAIRED keys (laundry w+h, paths main+secondary) each live in ONE
# document row; the partner key rides on the closest verbatim row that also
# references the item (reported plainly in the QA report).
CHECK_MAP = [
    ("part_d", "גובה מעקה 105", "glass_railing_min_height_cm", 105.0, 'ס"מ'),
    ("part_d", "רפלקטיביות זיגוג מקסימלית 70%", "glazing_reflectivity_max_pct", 70.0, "%"),
    ("part_c", "מידות 1.8×1.5", "laundry_screen_width_m", 1.8, "מ'"),
    ("part_d", "מסתורי כביסה - מידות וחומר", "laundry_screen_height_m", 1.5, "מ'"),
    ("part_b", "שביל הולכי רגל 3 מ", "path_main_min_m", 3.0, "מ'"),
    ("part_g", "☐ שצ”פ", "path_secondary_min_m", 2.5, "מ'"),
    ("part_c", "צובר גז", "gas_tank_setback_min_m", 2.0, "מ'"),
]

# Paragraph texts to skip (matched by prefix), with reasons for the report.
SKIP_PREFIXES = [
    ("מטרת המסמך", "intro - purpose statement, not a requirement"),
    ("מסמך זה הוא דרישות הגשה", "intro - scope note"),
    ("תקפות:", "intro - applicability clause"),
    ("דרישות לקבצי CAD:", "lead-in to the CAD requirement list"),
    ("הנספחים הבאים יצורפו כקבצי PDF", "lead-in kept? no - lead-in to appendix table (the table rows carry the requirements)"),
    ("לפני העברת ההגשה לבדיקה", "lead-in to the checklist part"),
    ("אם הגשה לא עומדת בדרישות מסמך זה", "lead-in to part-H steps"),
    ("במקרה של ערעור על דרישות הגשה", "lead-in to appeal steps"),
    ("מסמך זה אושר על ידי", "signature block"),
    ("הסעיפים הבאים חולצו", "appendix-B preamble (internal legal-review notes)"),
]
SKIP_SECTIONS = {
    "appendix_b": "נספח ב is internal legal-review commentary (notes-to-reconsider), not architect-facing requirements",
    # v0.2.0 Phase 1b: חלק ח (נוהל החזרת הגשה לא שלמה) removed from the
    # seeded set - process text, not architect-facing plan requirements.
    # Existing installs deactivate these rows via the db.py migration.
    "part_h": "חלק ח removed in v0.2.0 - return-procedure process text, not plan requirements",
}

# ── v0.2.0 Phase 1a: discipline classification ────────────────────────
# Every guideline gets a canonical discipline_key (compliance_engine/
# disciplines.py). Keyword rules run first (order matters - first match
# wins); anything unmatched falls back to its section default; sections
# without a thematic home default to "general".
DISCIPLINE_KEYWORD_RULES: list[tuple[str, str]] = [
    # שפ"ע - waste
    ("אשפה|אצירה|מיחזור|דחסן|תברואה|פינוי פסולת|שוט", "sec-3-1"),
    # גנים ונוף
    ("גנים|נוף|עצים|צמחי|גינון|נטיע", "sec-3-2"),
    # ניקוז וחלחול
    ("ניקוז|חלחול|נגר|השהיה|שיפוע", "sec-3-5"),
    # פיתוח וכבישים - paths, ramps, gas tank (per the learned mapping)
    ("שביל|כביש|רמפה|צובר|מדרכ", "roads-dev"),
    # תנועה - parking & traffic
    ("חני|תנועה|מאזן החניה|רכב", "sec-3-4"),
    # תשתיות
    ("תשתיות|חשמל|תאורה|ביוב|מים |קווי ", "sec-3-3"),
    # מבני ציבור
    ("מבני ציבור|מבנה ציבור|גן ילדים|מעון|כיתות|חצר הגן", "public-buildings"),
    # אדריכלות וחזיתות - facades, railings, glazing, materials, roofs
    ("חזית|מעקה|זיגוג|מסתור|מרפסת|גג|חומרי|צבע|חיפוי|פרגול|סוכך|מזג|חלון", "sec-3-7"),
    # הנחיות סביבתיות
    ("סביבת|אקוסט|קרינה|הצלל|רוח ", "sec-3-8"),
    # שירותים לדיירים
    ("דיירים|לובי|מחסנ|אופניים|עגלות", "sec-3-9"),
]

SECTION_DEFAULT_DISCIPLINE: dict[str, str] = {
    "part_a": "general",       # file-format requirements
    "part_b": "general",       # booklet structure
    "part_c": "general",       # per-plot content (keyword rules catch most)
    "part_d": "sec-3-7",       # facades & sections marking
    "part_e": "general",       # quantitative tables
    "part_f": "general",       # tb"a conformance
    "part_g": "general",       # checklist (keyword rules catch most)
    "appendix_a": "general",   # standards & references
}


def classify_discipline(title: str, body: str, section_key: str) -> str:
    hay = f"{title} {body}"
    for pattern, key in DISCIPLINE_KEYWORD_RULES:
        if re.search(pattern, hay):
            return key
    return SECTION_DEFAULT_DISCIPLINE.get(section_key, "general")

DASHES = {"—": "-", "–": "-"}


def norm(s: str) -> str:
    s = s.strip()
    for a, b in DASHES.items():
        s = s.replace(a, b)
    return s


def short_title(text: str, max_len: int = 60) -> str:
    t = text.lstrip("☐ ").strip()
    # "X: Y" or "X. Y" patterns → X
    for sep in (":", " - "):
        head = t.split(sep, 1)[0].strip()
        if 3 <= len(head) <= max_len:
            return head
    first = re.split(r"[.,(]", t, 1)[0].strip()
    return (first[:max_len]).strip() or t[:max_len]


# ── v0.2.1 content-quality sweep ─────────────────────────────────────────────
# The approved docx is a checklist written for a human reader, so many rows
# arrive with the body repeating the title verbatim, checklist glyphs, or CAD
# layer identifiers. Ellen reads these as guidance, so each row must say what
# is actually required. Rewrites live here, keyed by title, so re-extracting
# from the docx reproduces them.

# 1. Rows whose body merely repeats the title. Each gets an action sentence
# saying what the submission must DO; a few carry nothing beyond the title
# and get an empty body (the UI then shows the title alone).
DUPLICATE_BODY_REWRITES: dict[str, str] = {
    "הקבצים הבאים יצורפו להגשה. ללא קבצי CAD ההגשה לא תתקבל.":
        "יש לצרף את כל קבצי ה-CAD המפורטים להלן. הגשה ללא קבצי CAD לא תתקבל.",
    "גודל קובץ. כל קובץ DWG/DXF מקסימום 200 MB.":
        "יש לוודא שכל קובץ DWG או DXF אינו עולה על 200 MB. קובץ גדול יותר יפוצל או יידחס לפני ההגשה.",
    "גבול תא השטח מסומן בקו כחול מקווקו, מקושר במפורש לתב”ע":
        "יש לסמן את גבול תא השטח בקו כחול מקווקו, ולציין במפורש את ההפניה לתב”ע שממנה נגזר הגבול.",
    "מרחקים בין בניינים באותו תא שטח מסומנים במספרים בקנ”מ":
        "יש לסמן במספרים את המרחק בין כל שני בניינים באותו תא שטח, בקנה המידה של התכנית.",
    "חיפוי לפי נספח חומריות - ללא חיפוי אבן טבעית או דמוית-אבן":
        "יש לציין את חומרי החיפוי בהתאם לנספח החומריות. חיפוי באבן טבעית או דמוית-אבן אינו מאושר.",
    "פתחים אנכיים רצפה-תקרה (לא חלונות רוחביים)":
        "יש לתכנן את הפתחים כפתחים אנכיים מרצפה עד תקרה. חלונות רוחביים אינם מאושרים.",
    "מרפסות משולבות בחזית עם מעקים בנויים בחומר תואם":
        "יש לשלב את המרפסות בחזית הבניין, עם מעקים בנויים מחומר התואם את חומרי החזית.",
    "מסתורי כביסה - מידות וחומר מסומנים":
        "יש לסמן בתכנית את מידות מסתורי הכביסה ואת החומר שממנו ייבנו.",
    "ציון מסגרות חלון, סוג זיגוג, רפלקטיביות זיגוג מקסימלית 70%":
        "יש לציין את סוג מסגרות החלון ואת סוג הזיגוג. רפלקטיביות הזיגוג לא תעלה על 70%.",
    "סימון פאנלים סולאריים בפריסה מותאמת":
        "יש לסמן את הפאנלים הסולאריים בתכנית הגג, בפריסה המותאמת לצורת הגג ולמערכות שעליו.",
    "סימון דודי שמש (לא בחזית, רק בגג)":
        "יש לסמן את מיקום דודי השמש. הדודים ימוקמו על הגג בלבד ולא על חזית הבניין.",
    "סימון מתקני מיזוג מסיביים (מקוררי מים, צ’ילרים)":
        "יש לסמן בתכנית את מיקומם של מתקני המיזוג המסיביים, ובכללם מקוררי מים וצ’ילרים.",
    "מעקה גג + סף קצה":
        "יש לסמן בתכנית הגג את מעקה הגג ואת סף הקצה.",
    "אנטנות תקשורת - אם קיימות":
        "אם מתוכננות אנטנות תקשורת, יש לסמן את מיקומן בתכנית הגג.",
    "ולא טבלה מצרפת לפי בנדים של חדרים בלבד.":
        "יש להציג את הנתונים פר-יחידת דיור. טבלה מצרפת לפי בנדים של חדרים בלבד אינה מספקת.",
    "ניתוח הצללה על שכנים - אסור הצללה משמעותית בתאריך 21.12":
        "יש להגיש ניתוח הצללה על המגרשים השכנים. לא תאושר הצללה משמעותית בתאריך 21.12.",
}

# 2. חלק ז is the intake checklist: every body was a "☐ item" glyph line.
# Rewritten to state what the booklet must contain and what gets checked.
CHECKLIST_TEMPLATE = ("החוברת תכלול {item}. "
                      "בקבלת ההגשה נבדק שהפריט קיים ותואם לנדרש.")

# 3. Internal CAD layer identifiers that leaked into user-facing text.
TECH_ID_REPLACEMENTS: dict[str, str] = {
    "0_OPEN_SPACE": "שכבת המרחבים הפתוחים",
    "SETBACK_0": "שכבת קווי הבניין",
}

# 4. v0.2.2 FULL READABILITY PASS. The docx is a set of tables, so most rows
# arrived as "key: value" fragments, bare numbers, or titles truncated at the
# first colon. The test each row must pass: reading TITLE + BODY alone, is it
# clear (a) what is required and (b) what gets checked?
# Keyed by (section_key, original_title). "t" overrides the title, "b" the body.
READABILITY_REWRITES: dict[tuple[str, str], dict[str, str]] = {
    # ── חלק א: file format ──────────────────────────────────────────────
    ("part_a", "פורמט"): {
        "t": "פורמט קובץ החוברת",
        "b": "חוברת תכנית העיצוב תוגש כקובץ PDF אחד מרובה עמודים."},
    ("part_a", "גודל עמוד"): {
        "b": "עמודי החוברת יוגשו בגודל A3 אופקי או A1 אופקי."},
    ("part_a", "גודל קובץ מירבי"): {
        "t": "גודל קובץ מרבי",
        "b": "קובץ החוברת לא יעלה על 100 MB."},
    ("part_a", "כותרת קובץ"): {
        "t": "שם הקובץ",
        "b": "שם הקובץ יורכב ממספר התכנית, שם המתחם ומספר הגרסה. "
             "לדוגמה: 407-1048248_הטייסים_24.3.pdf"},
    ("part_a", "יישור עברי"): {
        "t": "כיוון הטקסט",
        "b": "הטקסט בחוברת יוצג בכיוון עברי, מימין לשמאל."},
    ("part_a", "גופנים"): {
        "b": "הגופנים יוטמעו בתוך קובץ ה-PDF, כדי שהחוברת תיפתח זהה בכל מחשב."},
    ("part_a", "הדפסה"): {
        "b": "החוברת תהיה ניתנת להדפסה בשחור-לבן ובצבע, ללא איבוד מידע מהותי."},
    ("part_a", "נגישות"): {
        "t": "טקסט מוכל בקובץ",
        "b": "הטקסט בחוברת יהיה טקסט אמיתי הניתן לחיפוש, ולא תמונה סרוקה."},
    # CAD files
    ("part_a", "תכנית פיתוח לכל תא שטח"): {
        "b": "לצורך בדיקת הפיתוח יצורף קובץ CAD בפורמט DXF או DWG בגרסה "
             "AC1018 ומעלה: קובץ נפרד לכל תא שטח, או קובץ מאוחד שבו תאי "
             "השטח מסומנים בשכבות."},
    ("part_a", "תכנית קומה טיפוסית"): {
        "b": "יצורף קובץ CAD בפורמט DXF או DWG של הקומה הטיפוסית, "
             "קובץ נפרד לכל טיפולוגיית בניין."},
    ("part_a", "תכנית מרתף"): {
        "b": "יצורף קובץ CAD בפורמט DXF או DWG של תכנית המרתף, "
             "קובץ נפרד לכל תא שטח."},
    ("part_a", "חזיתות"): {
        "b": "יצורף קובץ CAD בפורמט DXF או DWG ובו חזיתות בארבעה כיוונים "
             "לכל בניין."},
    ("part_a", "חתכים"): {
        "b": "יצורף קובץ CAD בפורמט DXF או DWG ובו לפחות שני חתכים: "
             "אורכי ורוחבי."},
    ("part_a", "גג / חזית חמישית"): {
        "b": "יצורף קובץ CAD בפורמט DXF או DWG של תכנית הגג, עם סימון "
             "פאנלים סולאריים, דודים ומתקנים."},
    ("part_a", "גרסת DWG"): {
        "b": "קבצי DWG יישמרו בגרסה AC1018, כלומר AutoCAD 2004 ומעלה. "
             "קבצים בגרסה ישנה יותר לא יתקבלו."},
    ("part_a", "שכבות לפי סטנדרט מבא”ת"): {
        "b": "שכבות הקובץ ייקראו לפי סטנדרט מבא”ת. שמות השכבות יכולים "
             "להיות בעברית או באנגלית, ולהלן השכבות הנדרשות."},
    # CAD layer names - the identifiers themselves must not reach Ellen.
    ("part_a", "תאי שטח"): {
        "t": "שכבת תאי שטח",
        "b": "גבולות תאי השטח יוגשו בשכבה ייעודית, שתיקרא תא_שטח ומספר "
             "תא השטח, או בשכבת תאי השטח לפי סטנדרט מבא”ת."},
    ("part_a", "קווי בניין"): {
        "t": "שכבת קווי בניין",
        "b": "קווי הבניין יוגשו בשכבה ייעודית שתיקרא קו_בניין, או בשכבת "
             "קווי הבניין לפי סטנדרט מבא”ת."},
    ("part_a", "גבולות מגרש"): {
        "t": "שכבת גבולות מגרש",
        "b": "גבולות המגרש יוגשו בשכבה ייעודית שתיקרא קו_מגרש, או בשכבת "
             "גבולות המגרש לפי סטנדרט מבא”ת."},
    ("part_a", "מבני המגורים"): {
        "t": "שכבת מבני המגורים",
        "b": "מבני המגורים יוגשו בשכבה ייעודית שתיקרא בניין ומספרו, או "
             "בשכבת המבנים לפי סטנדרט מבא”ת."},
    ("part_a", "מרחבים פתוחים"): {
        "t": "שכבת מרחבים פתוחים",
        "b": "המרחבים הפתוחים והשטחים הציבוריים הפתוחים יוגשו בשכבה ייעודית."},
    # Separate appendices
    ("part_a", "נספח חומריות"): {
        "b": "יצורף נספח חומריות כקובץ PDF נפרד בגודל A3, בהיקף של 5 עד 15 "
             "עמודים, בחתימת אדריכל הפרויקט."},
    ("part_a", "רשימת צמחייה (נספח גינון)"): {
        "b": "תצורף רשימת צמחייה כקובץ PDF נפרד בגודל A4, בהיקף של 3 עד 10 "
             "עמודים, בחתימת אדריכל נוף מוסמך."},
    ("part_a", "נספח הידרולוגי"): {
        "b": "יצורף נספח הידרולוגי כקובץ PDF נפרד בגודל A4, בהיקף של 10 עד 30 "
             "עמודים, בחתימת הידרולוג מוסמך."},
    ("part_a", "נספח אקוסטי"): {
        "b": "יצורף נספח אקוסטי כקובץ PDF נפרד בגודל A4, בהיקף של 5 עד 20 "
             "עמודים, בחתימת יועץ אקוסטיקה מוסמך."},
    ("part_a", "ת”י 5281 - בנייה ירוקה"): {
        "b": "יצורף נספח בנייה ירוקה לפי ת”י 5281 כקובץ PDF נפרד בגודל A4, "
             "בחתימת יועץ בנייה ירוקה, בצירוף מבדק חיצוני."},
    ("part_a", "נספח איכות סביבה וקיימות"): {
        "b": "יצורף נספח איכות סביבה וקיימות כקובץ PDF נפרד בגודל A4, בהיקף "
             "של 10 עד 30 עמודים, בחתימת יועץ סביבה מוסמך."},

    # ── חלק ב: booklet structure (bare numeric titles) ──────────────────
    ("part_b", "1"): {
        "t": "שער החוברת",
        "b": "החוברת תיפתח בשער ובו שם הפרויקט, מספר התב”ע, מספר הגרסה והתאריך."},
    ("part_b", "2"): {
        "t": "תוכן עניינים",
        "b": "החוברת תכלול תוכן עניינים מפורט."},
    ("part_b", "3"): {
        "t": "צוות הפרויקט",
        "b": "יוצג צוות הפרויקט: שמות בעלי המקצוע, מספרי הרישוי ופרטי הקשר."},
    ("part_b", "4"): {
        "t": "הקדמה",
        "b": "תוצג הקדמה ובה חזון התכנית ועקרונותיה."},
    ("part_b", "5"): {
        "t": "נתונים כלליים",
        "b": "יוצגו נתוני התכנית: שטח התכנית בדונם, סך יחידות הדיור, סך השטח "
             "העסקי, מספר הבניינים ומספר הקומות המרבי."},
    ("part_b", "לכל תא שטח בתב”ע, יוגשו לפחות 6 העמודים הבאים, בסדר הזה"): {
        "t": "מבנה העמודים לכל תא שטח",
        "b": "לכל תא שטח בתב”ע יוגשו לפחות ששת העמודים המפורטים להלן, "
             "בסדר שבו הם מופיעים."},
    ("part_b", "תכנית פיתוח (קנ”מ 1"): {
        "t": "תכנית פיתוח לתא שטח",
        "b": "תוגש תכנית פיתוח בקנה מידה 1:500: מבט-על על תא השטח ובו עצים, "
             "ריצוף, רחבות, חניות ודרכי גישה."},
    ("part_b", "דיאגרמת אשפה"): {
        "b": "תוצג דיאגרמת אשפה ובה חדרי האשפה, חדרי הדחסניות, רחבת הגזם "
             "ורחבת הכיבוי, חצי תנועה של רכבי האשפה, וסימון גישה תפעולית "
             "נפרדת לשצ”פ הנבדלת מתנועת רכבי האשפה."},
    ("part_b", "דיאגרמת פונקציות"): {
        "b": "תוצג דיאגרמת פונקציות ובה השימוש של כל חלל בקומת הקרקע: מסחר, "
             "מבני ציבור, לובי וחניון תת-קרקעי."},
    ("part_b", "מעונות יום (אם רלוונטי)"): {
        "t": "מעונות יום וגני ילדים",
        "b": "אם מתוכנן מעון יום או גן ילדים בתא השטח, תוגש עבורו תכנית מפורטת."},
    ("part_b", "תכנית מרתף"): {
        "b": "תוגש תכנית מרתף ובה החניון התת-קרקעי, חדרי המערכות והמחסנים, "
             "בצירוף טבלת חניות הכוללת מקומות חניה פרטיים, אופנועים, חניות "
             "נגישות וחניות אופניים."},
    ("part_b", "תכנית קומה טיפוסית"): {
        "b": "תוגש תכנית קומה טיפוסית ובה שטחי הדירות, שטחי השירות, הממ”דים "
             "ומסתורי הכביסה, בצירוף טבלת תמהיל יחידות הדיור."},
    ("part_b", "אם תאי שטח שונים זהים לחלוטין"): {
        "t": "תאי שטח זהים",
        "b": "אם תאי שטח שונים זהים לחלוטין, ניתן להגיש תכנית אחת ולציין בה "
             "במפורש על אילו תאי שטח היא חלה."},
    ("part_b", "זיתות"): {   # docx truncation lost the leading letter
        "t": "חזיתות",
        "b": "יוגשו חזיתות בארבעה כיוונים - צפון, דרום, מזרח ומערב - לכל "
             "טיפולוגיית בניין, בקנה מידה 1:500 ובקנה מידה מפורט 1:50."},
    ("part_b", "חתכים"): {
        "b": "יוגשו לפחות שני חתכים, אורכי ורוחבי, החוצים את כל אזור הפרויקט."},
    ("part_b", "תכנית גג / חזית חמישית"): {
        "b": "תוגש תכנית גג של כל הבניינים, עם סימון פאנלים סולאריים, דודי "
             "שמש, יחידות מיזוג, אנטנות ומעקה גג."},
    ("part_b", "שצ”פ - שטח ציבורי פתוח"): {
        "b": "תוגש תכנית מפורטת של כל השטחים הציבוריים הפתוחים. שלד השצ”פ "
             "יכלול הפרדה בין שביל הולכי הרגל לשביל האופניים, ברצועת הפרדה "
             "הכוללת גינון, תאורה, ספסלים ואשפתונים. רוחב מנחה: 3 מ’ לשביל "
             "הולכי רגל ו-2.5 מ’ לשביל אופניים."},
    ("part_b", "הדמיות (רנדרים)"): {
        "t": "הדמיות",
        "b": "יוגשו לפחות שלוש הדמיות צבעוניות פוטוריאליסטיות. לפחות אחת מהן "
             "תציג את הפרויקט בהקשר עירוני, מרחוב ראשי, ובה מכוניות, הולכי "
             "רגל ועצים."},

    # ── חלק ג: per-plot content ─────────────────────────────────────────
    ("part_c", "לכל תא שטח, התכנית תכלול את הסימונים והכיתובים הבאים"): {
        "t": "סימונים וכיתובים נדרשים בתכנית",
        "b": "לכל תא שטח תכלול התכנית את הסימונים והכיתובים המפורטים להלן."},
    ("part_c", "קווי בניין מותרים מסומנים כקווים מקווקווים נפרדים"): {
        "t": "קווי בניין מותרים",
        "b": "קווי הבניין המותרים יסומנו כקווים מקווקווים נפרדים: קו בניין "
             "קדמי, קו בניין אחורי וקו בניין צדדי."},
    ("part_c", "קווי בניין נדרשים"): {
        "b": "אם קיימת דרישה לקרבה לחזית הרחוב, קווי הבניין הנדרשים יסומנו "
             "בכיתוב מפורש."},
    ("part_c", "חדרי פסולת קומתיים"): {
        "b": "חדרי הפסולת הקומתיים יסומנו במפורש בכל קומה טיפוסית, בנפרד "
             "מסימון הדירות בנות 2 חדרים."},
    ("part_c", "חדרי דחסניות (מערכת פניאומטית)"): {
        "b": "חדרי הדחסניות של המערכת הפניאומטית יסומנו בצבע ייעודי, בנפרד "
             "מחדרי אצירת האשפה."},
    ("part_c", "רחבת גזם ייעודית"): {
        "b": "רחבת הגזם תסומן בקנה מידה 1:500, באבן משתלבת, ברצועה הצמודה "
             "לרחוב, ובסימון נפרד מרחבת כיבוי האש."},
    ("part_c", "רחבת כיבוי אש"): {
        "b": "רחבת כיבוי האש תסומן בתכנית, בצירוף כיתוב של סוג הריצוף - אבן "
             "משתלבת, גוטה גרדן או ריצוף מחלחל - והערה כי הסימון בשטח ייעשה "
             "בשילוט בלבד, ללא צביעה על הקרקע."},
    ("part_c", "צובר גז"): {
        "b": "מיקום צובר הגז יסומן בתת-הקרקע, במרחק של 2 מ’ לפחות מקו המגרש, "
             "ברצועת גינון."},
    ("part_c", "פתחי ממ”ד"): {
        "b": "פתחי הממ”ד יסומנו במפורש בכל קומה טיפוסית, בצירוף כיתוב של "
             "החזית שאליה הם פונים. הפתחים יפנו לחזית משנית ולא לרחוב הראשי."},
    ("part_c", "מסתורי כביסה"): {
        "b": "מסתורי הכביסה יסומנו בחזיתות, במידות 1.8 על 1.5 מ’ בכיתוב. "
             "החומר שממנו ייבנו, שאינו PVC, יצוין בנספח החומריות."},
    ("part_c", "יחידות מיזוג"): {
        "b": "אם מוצגות יחידות מיזוג בחזית, הן יוסתרו בשבכות אדריכליות "
             "ולא ייחשפו לרחוב הראשי."},
    ("part_c", "צנרת חזיתית"): {
        "b": "בחזיתות תותר צנרת גשם בלבד, והיא תסומן בתכנית. כל צנרת אחרת "
             "תתוכנן בתוך המבנה."},
    ("part_c", "שיפועי ניקוז קרקע מסומנים על תכניות הפיתוח באחוזים"): {
        "t": "סימון שיפועי ניקוז",
        "b": "שיפועי ניקוז הקרקע יסומנו על תכניות הפיתוח באחוזים, לדוגמה "
             "2.5%, בצירוף חצים המסמנים את כיווני הזרימה."},
    ("part_c", "שיפוע מינימלי"): {
        "t": "שיפוע ניקוז מזערי",
        "b": "השיפוע המזערי בכל אזורי הפיתוח יהיה 1%."},
    ("part_c", "כל הניקוז יזרום פנימה אל מערך השהיה/חלחול בתא השטח"): {
        "t": "כיוון זרימת הניקוז",
        "b": "כל הניקוז יזרום פנימה אל מערך ההשהיה והחלחול שבתא השטח, "
             "ולא לעבר המגרשים השכנים."},

    # ── חלק ד: facades ──────────────────────────────────────────────────
    ("part_d", "חומרי הגמר והחיפוי בחזיתות יתואמו מול מהנדס/ת העיר ואדריכלית"): {
        "t": "תיאום חומרי גמר וחיפוי",
        "b": "חומרי הגמר והחיפוי בחזיתות יתואמו מול מהנדס/ת העיר ואדריכלית "
             "העיר טרם האישור הסופי."},
    ("part_d", "מרפסת זיזית עם מעקה זכוכית"): {
        "b": "במרפסת זיזית עם מעקה זכוכית יהיה גובה המעקה 105 ס”מ. במרפסת "
             "ובמרצפה זיזית יידרש סינור או עיבוי לפי פרט קונסטרוקטיבי."},
    ("part_d", "ללא יחידות מיזוג"): {
        "t": "מתקנים גלויים בחזית",
        "b": "לא יותקנו בחזית יחידות מיזוג, צנרת חיצונית, ארובות חימום "
             "או דודים גלויים."},
    ("part_d", "תכנית גג בקנ”מ 1"): {
        "t": "קנה מידה לתכנית הגג",
        "b": "תכנית הגג תוגש בקנה מידה 1:500 לפחות."},

    # ── חלק ה: tables ───────────────────────────────────────────────────
    ("part_e", "הטבלה תכלול לכל יחידת דיור (לא ברמת קטגוריה)"): {
        "t": "פירוט הטבלה לכל יחידת דיור",
        "b": "הטבלה תפרט את הנתונים לכל יחידת דיור בנפרד, ולא ברמת קטגוריה."},
    ("part_e", "ה.1. טבלת תמהיל יחידות דיור (חובה - לכל תא שטח)"): {
        "t": "טבלת תמהיל יחידות דיור",
        "b": "טבלת תמהיל יחידות הדיור תוגש לכל תא שטח ותכלול את העמודות: "
             "מספר יחידה, תכנון לפי מספר חדרים, שטח עיקרי במ”ר, שטח שירות "
             "במ”ר, שטח כולל במ”ר, קומה, חזית עיקרית והערות."},
    ("part_e", "הסיבה"): {
        "t": "מטרת טבלת התמהיל",
        "b": "בלי טבלת התמהיל לא ניתן לאמת חישובים כגון אחוז הדירות הקטנות, "
             "המוגדרות כדירות בשטח של עד 75 מ”ר."},
    ("part_e", "ה.2. טבלת שטחים לכל תא שטח (חובה)"): {
        "t": "טבלת שטחים לכל תא שטח",
        "b": "טבלת השטחים תוגש לכל תא שטח ותכלול את העמודות: תא שטח, שטח "
             "עיקרי במ”ר, שטח שירות מעל הקרקע במ”ר, שטח שירות מתחת לקרקע "
             "במ”ר, השטח העיקרי המרבי לפי התב”ע, והסטייה ממנו."},
    ("part_e", "ה.3. טבלת חניה לכל תא שטח (חובה)"): {
        "t": "טבלת חניה לכל תא שטח",
        "b": "טבלת החניה תוגש לכל תא שטח ותכלול את העמודות: תא שטח, חניות "
             "פרטיות, חניות אופנועים, חניות נגישות, חניות אופניים, מספר "
             "יחידות הדיור, היחס הנדרש לפי תקן 3.1 הלאומי, וחישוב ההתאמה."},
    ("part_e", "תקן חניה לאומי 3.1 (ינואר 2023)"): {
        "b": "תקן החניה הלאומי 3.1 מינואר 2023 קובע: לדירה בשטח של עד 120 "
             "מ”ר נדרשות 1.0 עד 1.3 חניות; לדירה בשטח 120 עד 200 מ”ר נדרשות "
             "1.5 חניות; ובתוספת 20% חניות אורחים."},
    ("part_e", "אחוז קרינה ישירה לכל חזית עיקרית"): {
        "t": "אחוז קרינה ישירה בחזיתות",
        "b": "יוצג אחוז הקרינה הישירה לכל חזית עיקרית, לפי תאריך 21.12 "
             "בין השעות 9:00 ל-15:00."},
    ("part_e", "עמידה בת”י 5281"): {
        "b": "התכנית תעמוד בת”י 5281 בדירוג המזערי שנקבע בחוברת ההנחיות, "
             "בדרך כלל מצוין או לפחות טוב מאוד, בצירוף מסמכי הוכחה."},

    # ── חלק ו: TABA compliance ──────────────────────────────────────────
    ("part_f", "תכנית העיצוב כפופה לתב”ע, לא להפך. במקרה של סתירה"): {
        "t": "יחס בין תכנית העיצוב לתב”ע",
        "b": "תכנית העיצוב כפופה לתב”ע ולא להפך. במקרה של סתירה בין השתיים, "
             "קובעת התב”ע."},
    ("part_f", "מספר יחידות דיור מקסימלי לכל תא שטח"): {
        "t": "מספר יחידות דיור מרבי",
        "b": "מספר יחידות הדיור המרבי לכל תא שטח ייבדק מול הקבוע "
             "בתקנון התב”ע."},
    ("part_f", "גובה בניין מקסימלי (מ’ + קומות)"): {
        "t": "גובה בניין מרבי",
        "b": "גובה הבניין המרבי, במטרים ובמספר קומות, ייבדק מול תקנון התב”ע "
             "ומול התשריט."},
    ("part_f", "שטח עיקרי מקסימלי"): {
        "t": "שטח עיקרי מרבי",
        "b": "השטח העיקרי המרבי ייבדק מול הקבוע בתקנון התב”ע."},
    ("part_f", "שטח שירות מקסימלי"): {
        "t": "שטח שירות מרבי",
        "b": "שטח השירות המרבי ייבדק מול הקבוע בתקנון התב”ע."},
    ("part_f", "קווי בניין"): {
        "b": "לצורך בדיקת קווי הבניין יצורף קובץ תשריט התב”ע בפורמט DWG."},
    ("part_f", "יחס חניה"): {
        "b": "יחס החניה ייבדק מול תקנון התב”ע ומול תקן החניה הלאומי."},
    ("part_f", "אחוז דירות קטנות (≤75 מ”ר)"): {
        "t": "אחוז דירות קטנות",
        "b": "אחוז הדירות הקטנות, ששטחן עד 75 מ”ר, ייבדק מול תקנון התב”ע. "
             "בדרך כלל נדרש 20% לפחות."},
    ("part_f", "ייעודי קרקע"): {
        "b": "ייעודי הקרקע ייבדקו מול תשריט התב”ע."},

    # ── נספח א: references ──────────────────────────────────────────────
    ("appendix_a", "תקנים לאומיים מחייבים"): {
        "b": "התכנית תעמוד בתקנים הלאומיים המחייבים: תקנות התכנון והבנייה "
             "(תיקון 23) וחוק התכנון והבנייה; ת”י 5281 לבנייה ירוקה; תקן "
             "החניה הלאומי 3.1 מינואר 2023; תקני כיבוי אש ת”י 1220 על "
             "שלוחותיו; ותקני הנגישות ת”י 1918."},
    ("appendix_a", "מסמכי תכנון תקפים בנס-ציונה"): {
        "b": "המסמכים התקפים בנס-ציונה הם: חוברת הנחיות בינוי ופיתוח לשכונת "
             "צפון מזרח (תכנית 407-0730606, פברואר 2026); ההנחיות המרחביות "
             "של עיריית נס-ציונה (תכנית 130/3/א); ותכניות התב”ע המאושרות "
             "לכל מתחם בנפרד."},
    ("appendix_a", "אנשי קשר במינהלת"): {
        "b": "לפניות בנוגע להגשה ניתן לפנות למהנדס/ת המינהלת או "
             "למזכירות המינהלת."},
}

# חלק ז titles that the docx truncated at the first colon.
CHECKLIST_TITLE_FIXES: dict[str, str] = {
    "חזיתות 4 כיוונים בקנ”מ 1": "חזיתות בארבעה כיוונים",
    "ניתוח שמש (21.12, 9": "ניתוח שמש",
}

_CHECKBOX = "☐"


def apply_content_fixes(rows: list[dict]) -> None:
    """Rewrite bodies that repeat the title, expand חלק ז checklist stubs,
    and strip internal identifiers. Mutates rows in place; prints a
    before/after report for review."""
    dup_fixed, stub_fixed, tech_fixed = [], [], []
    readability_fixed: list[tuple[str, str, str, str, str]] = []

    for r in rows:
        title = r["title"]
        body = r.get("body_text") or ""

        # 0. v0.2.2 readability pass runs FIRST: it replaces whole rows, so
        # the later passes see (and leave alone) the finished text.
        rw = READABILITY_REWRITES.get((r["section_key"], title))
        if rw:
            new_title = rw.get("t", title)
            new_body = rw.get("b", body)
            readability_fixed.append(
                (r["section_key"], title, new_title, body, new_body))
            r["title"] = new_title
            r["body_text"] = new_body
            title, body = new_title, new_body

        # 1. body repeats the title
        if title in DUPLICATE_BODY_REWRITES and norm(body) == norm(title):
            r["body_text"] = DUPLICATE_BODY_REWRITES[title]
            dup_fixed.append((title, body, r["body_text"]))
            body = r["body_text"]

        # 2. חלק ז checklist stubs
        if r["section_key"] == "part_g" and body.lstrip().startswith(_CHECKBOX):
            item = body.lstrip()[len(_CHECKBOX):].strip().rstrip(".")
            # "תא שטח 1: 6 העמודים הנדרשים" reads as a fragment after the
            # template; turn the colon into a phrase that survives it.
            if ": " in item:
                head, tail = item.split(": ", 1)
                item = f"{head} - {tail}"
            r["body_text"] = CHECKLIST_TEMPLATE.format(item=item)
            stub_fixed.append((title, body, r["body_text"]))
            body = r["body_text"]
            if title in CHECKLIST_TITLE_FIXES:
                new_title = CHECKLIST_TITLE_FIXES[title]
                readability_fixed.append(
                    (r["section_key"], title, new_title, body, body))
                r["title"] = new_title

        # 3. internal identifiers in either field
        for field in ("title", "body_text"):
            val = r.get(field) or ""
            new = val
            for tok, human in TECH_ID_REPLACEMENTS.items():
                new = new.replace(tok, human)
            # Any remaining CAPS_UNDERSCORE token is an unmapped leak - the
            # Layer-0 gate will fail on it rather than let it reach Ellen.
            if new != val:
                r[field] = new
                tech_fixed.append((title, field, val, new))

    # Every rewrite key must match a real row, or a docx edit has silently
    # orphaned it and the row Ellen reads stays broken.
    matched = {(s, t) for s, t, _, _, _ in readability_fixed}
    orphans = sorted(set(READABILITY_REWRITES) - matched)
    if orphans:
        print(f"FATAL: {len(orphans)} readability rewrites matched no row: "
              f"{orphans}", file=sys.stderr)
        sys.exit(1)

    print(f"\nCONTENT SWEEP: {len(readability_fixed)} rows rewritten for "
          f"readability, {len(dup_fixed)} duplicate bodies rewritten, "
          f"{len(stub_fixed)} checklist stubs expanded, "
          f"{len(tech_fixed)} technical identifiers replaced")
    for sec, old_t, new_t, old_b, new_b in readability_fixed:
        print(f"  [read/{sec}] {old_t}"
              + (f"  →  {new_t}" if new_t != old_t else "")
              + f"\n        before: {old_b}\n        after:  {new_b}")
    for t, before, after in dup_fixed:
        print(f"  [dup] {t}\n        before: {before}\n        after:  {after}")
    for t, before, after in stub_fixed:
        print(f"  [stub] {t}\n        before: {before}\n        after:  {after}")
    for t, field, before, after in tech_fixed:
        print(f"  [tech] {t} ({field})\n        before: {before}\n        after:  {after}")


def main() -> None:
    d = docx.Document(DOC)
    sections: list[dict] = []
    rows: list[dict] = []
    skipped: list[tuple[str, str]] = []

    cur_key, cur_title, cur_sub = None, None, ""
    sort_order = 0

    def add_row(title: str, body: str, table_item: bool = False) -> None:
        nonlocal sort_order
        if cur_key is None:
            skipped.append((body[:60], "text before the first section heading"))
            return
        if cur_key in SKIP_SECTIONS:
            skipped.append((body[:60], SKIP_SECTIONS[cur_key]))
            return
        sort_order += 1
        rows.append({
            "section_key": cur_key,
            "section_title": cur_title,
            "subsection": cur_sub,
            "title": norm(title),
            "body_text": norm(body),
            "guideline_type": "manual",
            "check_key": None, "check_value": None, "unit": None,
            "sort_order": sort_order,
            "discipline_key": classify_discipline(norm(title), norm(body), cur_key),
        })

    for child in d.element.body.iterchildren():
        if child.tag.endswith("}p"):
            p = Paragraph(child, d)
            text = p.text.strip()
            if not text:
                continue
            style = p.style.name
            if style == "Heading 1":
                continue  # document title
            if style == "Heading 2":
                key = next((v for k, v in SECTION_KEYS.items() if text.startswith(k)), None)
                cur_key, cur_title, cur_sub = key, norm(text), ""
                if key and key not in SKIP_SECTIONS and not any(s["section_key"] == key for s in sections):
                    sections.append({"section_key": key, "section_title": norm(text)})
                continue
            if style == "Heading 3":
                cur_sub = norm(text)
                continue
            reason = next((r for pfx, r in SKIP_PREFIXES if text.startswith(pfx)), None)
            if reason:
                skipped.append((text[:60], reason))
                continue
            add_row(short_title(text), text)
        elif child.tag.endswith("}tbl"):
            t = Table(child, d)
            header = [c.text.strip() for c in t.rows[0].cells]
            if len(t.rows) == 1:
                # Template tables (ה.1-ה.3): the header row IS the requirement
                # (the required columns).
                add_row(cur_sub or "עמודות נדרשות",
                        "עמודות נדרשות בטבלה: " + ", ".join(header), table_item=True)
                continue
            for r in t.rows[1:]:
                cells = [c.text.strip() for c in r.cells]
                item, requirement = cells[0], " / ".join(x for x in cells[1:] if x)
                add_row(item, f"{item}: {requirement}" if requirement else item, table_item=True)

    # Authority additions (addendum 10) - guidelines added by the מינהלת
    # AFTER the approved document, not extracted from the docx. They join
    # the drainage items' section (part_c) at the section's visual end:
    # the UI/PDF group rows by section_title, so a sort_order past the
    # document total keeps them last within their group without renumbering
    # the document rows (renumbering would break the (section, sort_order)
    # placement dedup on existing installs).
    authority_rows = [
        {
            "section_key": "part_c",
            "section_title": next(s["section_title"] for s in sections
                                  if s["section_key"] == "part_c"),
            "subsection": "",
            "title": "פתרון חלחול מלא בתחום המגרש",
            "body_text": ("יוצג פתרון חלחול/השהיה לניהול 100% מנגר הגשם בתחום "
                          "המגרש. אמצעי החלחול וההשהיה יסומנו בתכנית הפיתוח "
                          "כולל נפחים."),
            "guideline_type": "manual",
            "check_key": None, "check_value": None, "unit": None,
            "origin": "מינהלת",
        },
        {
            "section_key": "part_c",
            "section_title": next(s["section_title"] for s in sections
                                  if s["section_key"] == "part_c"),
            "subsection": "",
            "title": "חיבור מערך הניקוז לתשתית העירונית",
            "body_text": ("יוצג חיבור מתוכנן של מערך הניקוז אל התשתית "
                          "העירונית, כולל נקודות התחברות במקרא."),
            "guideline_type": "manual",
            "check_key": None, "check_value": None, "unit": None,
            "origin": "מינהלת",
        },
        # Addendum 12: marking requirements that make the numeric checks
        # verifiable on the plan. part_b hosts the path-width guidelines
        # (the שצ"פ row carrying path_main_min_m); part_c hosts צובר גז.
        {
            "section_key": "part_b",
            "section_title": next(s["section_title"] for s in sections
                                  if s["section_key"] == "part_b"),
            "subsection": "",
            "title": "סימון רוחבי שבילים בתכנית",
            "body_text": ("רוחב כל שביל להולכי רגל יסומן במפורש בתכנית "
                          "הפיתוח במטרים, לצד השביל, באופן המאפשר בדיקה מול "
                          "הרוחב המזערי הנדרש."),
            "guideline_type": "manual",
            "check_key": None, "check_value": None, "unit": None,
            "origin": "מינהלת",
        },
        {
            "section_key": "part_c",
            "section_title": next(s["section_title"] for s in sections
                                  if s["section_key"] == "part_c"),
            "subsection": "",
            "title": "סימון מרחק צובר הגז מהמבנים",
            "body_text": ("מרחק הצובר מכל מבנה סמוך יסומן במפורש בתכנית "
                          "במטרים, באופן המאפשר בדיקה מול המרחק המזערי "
                          "הנדרש."),
            "guideline_type": "manual",
            "check_key": None, "check_value": None, "unit": None,
            "origin": "מינהלת",
        },
    ]

    # Addendum 13: municipal waste-consultant guidelines (source letter:
    # יועץ התברואה מטעם העירייה, סיסטמה הנדסת הסביבה, 13/7/26). Placed in
    # part_c next to the existing waste-room requirements (חדרי דחסניות).
    # Numeric thresholds here are candidates for future check_key wiring
    # once the engine can read room dimensions from תוכנית כתמים - NOT
    # wired now.
    _waste_origin = "הנחיות יועץ התברואה העירוני"
    _pc_title = next(s["section_title"] for s in sections
                     if s["section_key"] == "part_c")
    for t, b in [
        ("חדרי אצירה ומיחזור מבניים במקום מרכזי מיחזור",
         "בוטל השימוש במרכזי מיחזור שכונתיים/מתחמיים. יש לתכנן חדרי "
         "אצירה/מיחזור מבניים בתוך המבנים."),
        ("תוכנית כתמים - תוכן נדרש",
         "תוכנית הכתמים תציג את החדרים לסוגיהם כולל מידותיהם המדויקות, "
         "איפיון דלתות החדרים, ומיקום השוטים - ברמה מבנית, עם צביעת "
         "החדרים."),
        ("תיאום הנדסי לשלב ההיתר",
         "בשלב הבקשות להיתרי בנייה יידרש תיאום הנדסי נוסף והגשת תשריטים "
         "הנדסיים מפורטים כולל חתכים של חדרי האצירה והשוטים (במגדלים)."),
        ("חדר אצירה מרכזי במגדל - רוחב מזערי",
         "רוחב החדר 5.0 מ' נטו לפחות. המידות יוצגו ויצוינו בתוכנית."),
        ("חדר אצירה מרכזי במגדל - אורך מזערי",
         "אורך החדר 8.0 מ' נטו לפחות."),
        ("חדר אצירה מרכזי במגדל - גובה מזערי",
         "יצוין גובה מזערי של 5.0 מ'. הגובה הסופי מותנה בזווית השוט."),
        ("חדר אצירה מרכזי במגדל - דלתות",
         "יצוינו דלתות החדר: דלת חזיתית ודלת שירות צידית."),
        ("חדר אצירה מרכזי במגדל - דחסן ושוט",
         "יצוין (במלל) דחסן נתיק בנפח 14 קוב. יוצג אזור ירידת השוט עד "
         "חיבורו לדחסן, כולל המידה האופקית במטר רץ."),
        ("חדר מיחזור במגדל - מכלים ומידות",
         "בכל חדר יוצבו 5 מכלי 1100 ליטר כתומים, 2 מכלי 1100 ליטר כחולים "
         "ועגלת רשת. מידות החדר: רוחב 4.0 מ', אורך 6.0 מ'."),
        ("חדר מיחזור במגדל - דלת",
         "בחזית החדר תוצג דלת דו-כנפית ברוחב 1.6 מ'."),
        ("חדר אשפה במבנה נמוך - מידות",
         "מידות החדר יוצגו בתוכנית: רוחב 4.0 מ', אורך 9.0 מ', גובה 2.7 מ' "
         "לפחות."),
        ("חדר אשפה במבנה נמוך - דלת",
         "במרכז מידת הרוחב תותקן ותוצג דלת דו-כנפית ברוחב 1.6 מ'."),
    ]:
        authority_rows.append({
            "section_key": "part_c",
            "section_title": _pc_title,
            "subsection": "",
            "title": t,
            "body_text": b,
            "guideline_type": "manual",
            "check_key": None, "check_value": None, "unit": None,
            "origin": _waste_origin,
        })

    # Addenda 14-15: guest parking + public-buildings additions (מינהלת).
    # part_b hosts the traffic/parking rows and the מעונות item. The
    # numeric values (30% guest parking, 200 sqm gan yard) are future
    # check_key candidates (guest_parking_pct, gan_yard_min_sqm) - not
    # wired now.
    _pb_title = next(s["section_title"] for s in sections
                     if s["section_key"] == "part_b")
    for t, b in [
        ("חניות אורחים - תוספת מינהלת",
         "בנוסף לתקן החניה למגורים, תידרש תוספת של 30% חניות אורחים מתוך "
         "תקן החניות למגורים. חניות האורחים יסומנו בתכנית ובמאזן החניה "
         "בנפרד."),
        ("שטח חצר מזערי לגן ילדים",
         'חצר הגן תהיה בשטח של 200 מ"ר לפחות לכל גן. שטח החצר יסומן '
         'בתכנית במ"ר.'),
        ("סימון שטחים ומספר כיתות במבני ציבור",
         'בתכניות מבני ציבור יסומנו שטחי כל החללים הציבוריים במ"ר, כולל '
         "יחידת המידה, וכן מספר הכיתות וחלוקתן."),
    ]:
        authority_rows.append({
            "section_key": "part_b",
            "section_title": _pb_title,
            "subsection": "",
            "title": t,
            "body_text": b,
            "guideline_type": "manual",
            "check_key": None, "check_value": None, "unit": None,
            "origin": "מינהלת",
        })

    for extra in authority_rows:
        sort_order += 1
        extra["sort_order"] = sort_order
        # Authority rows imply their discipline via the same keyword rules
        # (verified: all classify unambiguously).
        extra.setdefault("discipline_key",
                         classify_discipline(extra["title"], extra["body_text"],
                                             extra["section_key"]))
        rows.append(extra)

    # Attach the 7 check_keys.
    attached = set()
    for sec, needle, key, value, unit in CHECK_MAP:
        for row in rows:
            if row["section_key"] == sec and needle in (row["body_text"] + row["title"]) and row["check_key"] is None:
                row.update({"guideline_type": "checkable", "check_key": key,
                            "check_value": value, "unit": unit})
                attached.add(key)
                break
    missing = [k for _, _, k, _, _ in CHECK_MAP if k not in attached]
    if missing:
        print(f"FATAL: check_keys not matched to any row: {missing}", file=sys.stderr)
        sys.exit(1)

    # v0.2.1 content-quality sweep. Applied HERE (not by hand on the JSON) so
    # a re-extraction from the approved docx keeps the improvements. It runs
    # AFTER check_key attachment on purpose: CHECK_MAP needles match the raw
    # docx wording (including the "☐" checklist glyphs) that the sweep
    # rewrites, so sweeping first silently breaks the numeric checks.
    apply_content_fixes(rows)

    OUT.write_text(json.dumps({"sections": sections, "guidelines": rows},
                              ensure_ascii=False, indent=2), encoding="utf-8")

    # Gate-A report
    print(f"TOTAL: {len(rows)} guidelines in {len(sections)} sections → {OUT.relative_to(ROOT)}")
    for s in sections:
        n = sum(1 for r in rows if r["section_key"] == s["section_key"])
        c = sum(1 for r in rows if r["section_key"] == s["section_key"] and r["guideline_type"] == "checkable")
        print(f"  {s['section_title'][:60]:60s} {n:3d} rows ({c} checkable)")
    print(f"\nSKIPPED ({len(skipped)}):")
    for text, reason in skipped:
        print(f"  - [{reason}] {text}")

    # v0.2.0: discipline classification table + ambiguous (fallback) list.
    from collections import Counter
    disc_counts = Counter(r["discipline_key"] for r in rows)
    print("\nDISCIPLINES:")
    for k, n in disc_counts.most_common():
        print(f"  {k:18s} {n:3d}")
    ambiguous = [r for r in rows
                 if r["discipline_key"] == "general"
                 and not any(re.search(p, r["title"] + " " + r["body_text"])
                             for p, _ in DISCIPLINE_KEYWORD_RULES)]
    print(f"\nAMBIGUOUS→general ({len(ambiguous)}):")
    for r in ambiguous[:200]:
        print(f"  - [{r['section_key']}] {r['title'][:60]}")


if __name__ == "__main__":
    main()
