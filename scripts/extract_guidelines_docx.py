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
