"""Phase 7.5 Step 1 — architect-facing summary inventory.

Curated, domain-specific categorization of v24.3 findings into three buckets:
  - חסר (MISSING)    — documents/drawings to add
  - תיקונים (FIX)    — items provided but wrong
  - הבהרות (CLARIFY) — questions needing answer

Output: data/projects/<plan>/submissions/<sub>/architect_summary_inventory.json

The report_generator picks this up at render time and emits 4 front-matter
pages (חסר / תיקונים / הבהרות / map) right after the cover.

Voice rules (HARD):
- Direct architect address ("יש לצרף", "יש לתקן", "יש להבהיר")
- ≤25 Hebrew words per item
- Architect vocabulary (תכנית פיתוח, תשריט חזית, נספח חומריות)
- No internal references (engine, vision, critic, M-numbers, json files)
- Anchor IDs link to detail-section anchors (set by report_generator)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]


CATEGORY_ORDER = ["MISSING", "FIX", "CLARIFY"]
CATEGORY_LABELS_HE = {
    "MISSING": "חסר — מסמכים ותכניות שיש לצרף בהגשה הבאה",
    "FIX":     "תיקונים — שינויים נדרשים בהגשה הקיימת",
    "CLARIFY": "הבהרות — שאלות שיש להבהיר בהגשה הבאה",
}
CATEGORY_INTROS_HE = {
    "MISSING": "הקטגוריות הבאות לא נמצאו בהגשה הנוכחית ויש לצרפן בהגשה הבאה.",
    "FIX":     "פריטים שהוגשו אך דורשים שינוי.",
    "CLARIFY": "פריטים הדורשים הבהרה או אישור מצד האדריכל.",
}
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


# ─────────────────────────────────────────────────────────────────────────────
# Curated item list — judgment-driven for v24.3
# ─────────────────────────────────────────────────────────────────────────────

ITEMS_CURATED: List[Dict[str, Any]] = [
    # ============== MISSING ==============
    {
        "id": "M01", "category": "MISSING", "severity": "high",
        "one_line_he": "יש לצרף ששת הנספחים החיצוניים הנדרשים: נספח חומריות, רשימת צמחייה מפורטת, נספח הידרולוגי, נספח אקוסטי, נספח איכות סביבה וקיימות, ונספח ת״י 5281 (בנייה ירוקה).",
        "source_section": "פרק 4 פעולה #1 + פרק 3",
        "anchor_target_id": "sec-4",
    },
    {
        "id": "M02", "category": "MISSING", "severity": "high",
        "one_line_he": "יש לצרף תכניות פיתוח עבור תאי שטח 6, 7, 8, 9, 10, ו-20 — אלו חלק סטטוטורי מהתב״ע ואינם מופיעים בהגשה.",
        "source_section": "פרק 2ב (CAD)",
        "anchor_target_id": "sec-cad",
    },
    {
        "id": "M03", "category": "MISSING", "severity": "high",
        "one_line_he": "יש לצרף טבלת שטחי בנייה מפורטת לכל תא שטח: שטח עיקרי, שטח שירות מעל הקרקע, שטח שירות תת-קרקעי — בנפרד מטבלת תמהיל הדירות.",
        "source_section": "פרק 4 פעולות #4/#10/#11",
        "anchor_target_id": "sec-4",
    },
    {
        "id": "M04", "category": "MISSING", "severity": "high",
        "one_line_he": "יש לצרף נספח עצים בוגרים. נספח זה מוזכר בתקנון אך אינו כלול בהגשה.",
        "source_section": "פרק 2א סעיף 6.5.1",
        "anchor_target_id": "sec-m4-sidecar",
    },
    {
        "id": "M05", "category": "MISSING", "severity": "high",
        "one_line_he": "יש לצרף תכנית שלביות ביצוע מפורטת לכלל תאי השטח (סעיף 7.1.1). ההגשה הנוכחית כוללת התייחסות חלקית לשצ״פ בלבד.",
        "source_section": "פרק 2א סעיף 7.1.1",
        "anchor_target_id": "sec-m4-sidecar",
    },
    {
        "id": "M06", "category": "MISSING", "severity": "high",
        "one_line_he": "יש לצרף תכנית ניקוז מפורטת עם חישוב נפח השהיה כולל של 450 מ״ק (סעיף 6.4.2), כולל מערכות החדרה ומפת אזורי חלחול.",
        "source_section": "פרק 2א סעיף 6.4.2 + פרק 3.5",
        "anchor_target_id": "sec-3-5",
    },
    {
        "id": "M07", "category": "MISSING", "severity": "high",
        "one_line_he": "יש לצרף ניתוח חשיפה לשמש (21.12, 09:00–15:00) וחישוב פוטנציאל פאנלים פוטו-וולטאיים בגג ובחזיתות.",
        "source_section": "פרק 4 פעולה #7 + פרק 3.10",
        "anchor_target_id": "sec-3-10",
    },
    {
        "id": "M08", "category": "MISSING", "severity": "medium",
        "one_line_he": "יש לסמן בכל תא שטח רחבת גזם ייעודית בקנ״מ 1:500, באבן משתלבת, ברצועה הצמודה לרחוב.",
        "source_section": "פרק 4 פעולה #12 + פרק 3.1",
        "anchor_target_id": "sec-3-1",
    },
    {
        "id": "M09", "category": "MISSING", "severity": "medium",
        "one_line_he": "יש לצרף את ששת פרקי המעטפת בחוברת ההגשה: טיפולוגיות בינוי, פיתוח, מעטפת בניינים, הנחיות סביבתיות, הנחיות תשתיות ותנועה, צוות הפרויקט.",
        "source_section": "נספח א (פורמט)",
        "anchor_target_id": "sec-appendix-a",
    },
    {
        "id": "M10", "category": "MISSING", "severity": "medium",
        "one_line_he": "יש להוסיף בעמוד הראשון של כל פרק מקצועי מקום ייעודי לחתימת רפרנט עירוני מהדיסציפלינה הרלוונטית.",
        "source_section": "נספח א (פורמט)",
        "anchor_target_id": "sec-appendix-a",
    },

    # ============== FIX ==============
    {
        "id": "F01", "category": "FIX", "severity": "high",
        "one_line_he": "יש להוסיף בתשריטי תא שטח 2 (עמ׳ 37 + עמ׳ 34) זיקת הנאה תת-קרקעית למעבר רכב מתא שטח 2 לתא שטח 12 הסמוך (סעיף 6.6.4) — כיום לא מוצגת בהגשה.",
        "source_section": "פרק 2א סעיף 6.6.4",
        "anchor_target_id": "sec-m4-sidecar",
    },
    {
        "id": "F02", "category": "FIX", "severity": "high",
        "one_line_he": "יש לציין במפורש בעמוד השער את תאריך ההגשה ואת מספר התב״ע בפורמט 407-1048248 — שניהם חסרים או לא תקניים בהגשה.",
        "source_section": "נספח א (פורמט)",
        "anchor_target_id": "sec-appendix-a",
    },
    {
        "id": "F03", "category": "FIX", "severity": "high",
        "one_line_he": "יש לצרף בעמוד השער טבלת חתימות הכוללת את 6 הדיסציפלינות הנדרשות: שפ״ע/כבישים, תנועה, גנים ונוף, אדריכלות, תאגיד, יו״ר הוועדה.",
        "source_section": "נספח א (פורמט)",
        "anchor_target_id": "sec-appendix-a",
    },
    {
        "id": "F04", "category": "FIX", "severity": "medium",
        "one_line_he": "יש להחליף ב-18 עמודי הגשה רקעים שאינם לבנים. דרישה: רקע לבן בכל עמודי החוברת.",
        "source_section": "נספח א (פורמט)",
        "anchor_target_id": "sec-appendix-a",
    },
    {
        "id": "F05", "category": "FIX", "severity": "medium",
        "one_line_he": "יש לציין בכותרת כל תוכנית מקצועית את קנה המידה 1:250 ולוודא שהפלט מודפס בקנ״מ זה — הדרישה מעוגנת גם בסעיף 6.1 לתקנון התב״ע.",
        "source_section": "נספח א (פורמט)",
        "anchor_target_id": "sec-appendix-a",
    },
    {
        "id": "F06", "category": "FIX", "severity": "medium",
        "one_line_he": "יש להוסיף סימוני מידות מפורשים על תוכניות הפיתוח, הקומה הטיפוסית והמרתפים (גובה בניין, מרחקי קווי בניין, מידות חזית).",
        "source_section": "נספח א (פורמט)",
        "anchor_target_id": "sec-appendix-a",
    },

    # ============== CLARIFY ==============
    {
        "id": "C01", "category": "CLARIFY", "severity": "high",
        "one_line_he": "תא שטח 5 — שני מפלסים בתשריטים מציגים גובה מוחלט מעל תקרת סעיף 6.7 (91.00 מ׳ מעל פני הים): 91.30 מ׳ ו-91.80 מ׳. יש להבהיר האם אביזרי גג, קווי מעטפת, או חריגה אמיתית.",
        "source_section": "פרק 2ג (חתכים)",
        "anchor_target_id": "sec-chat",
    },
    {
        "id": "C02", "category": "CLARIFY", "severity": "medium",
        "one_line_he": "מבנה A2 — שני תשריטי חזית מציגים גובה קרקע מוחלט שונה (44.50 מ׳ מול 42.00 מ׳). גובה המבנה זהה. יש להבהיר מהו קו האפס הקנוני.",
        "source_section": "פרק 2ג (חתכים)",
        "anchor_target_id": "sec-chat",
    },
    {
        "id": "C03", "category": "CLARIFY", "severity": "medium",
        "one_line_he": "מבנה B4 — פער של 1.35 מ׳ בגובה הקרקע בין תשריטים, כולל סתירה פנימית בעמ׳ 57. יש להבהיר ולעדכן.",
        "source_section": "פרק 2ג (חתכים)",
        "anchor_target_id": "sec-chat",
    },
    {
        "id": "C04", "category": "CLARIFY", "severity": "high",
        "one_line_he": "טבלת ״ריכוז תמהיל דירות״ מציגה מספר יחידות דיור (232) במקומות שטבלת הזכויות בתקנון מצפה לשטחי בנייה. יש להציג בנפרד את שטחי הבנייה.",
        "source_section": "פרק 2א — כרטיסי טבלת הזכויות",
        "anchor_target_id": "sec-m4-sidecar",
    },
    {
        "id": "C05", "category": "CLARIFY", "severity": "high",
        "one_line_he": "אחוז דירות קטנות — האדריכל מצהיר על 21% (147/700) על בסיס הגדרה רחבה (≤81 מ״ר). אימות מול דרישת 20% מצריך טבלת תמהיל עם שטח לכל יחידת דיור.",
        "source_section": "פרק 4 פעולה #2",
        "anchor_target_id": "sec-4",
    },
    {
        "id": "C06", "category": "CLARIFY", "severity": "high",
        "one_line_he": "יחס חניה — מחושב 1.42 (330/232 יח״ד), מעל הסף האיכותי 1.3. אימות התאמה לתקן חניה לאומי 3.1 מצריך טבלת שטחים פר יחידת דיור.",
        "source_section": "פרק 4 פעולה #8",
        "anchor_target_id": "sec-4",
    },
    {
        "id": "C07", "category": "CLARIFY", "severity": "high",
        "one_line_he": "יש לצרף בהגשה הבאה טבלת קווי בניין מפורטת לכל תא שטח (קדמי / צידי / אחורי) כך שניתן יהיה לאמתם מול תקנון התב\"ע.",
        "source_section": "פרק 4 פעולה #9",
        "anchor_target_id": "sec-4",
    },
    {
        "id": "C08", "category": "CLARIFY", "severity": "medium",
        "one_line_he": "בדיאגרמות הפונקציות (עמ׳ 26, 36, 41, 45) לא זוהו חדר ועד בית וחדר תאי דואר. יש להבהיר האם קיימים בעמודים אחרים, אינם נדרשים, או חסרים.",
        "source_section": "פרק 3.11",
        "anchor_target_id": "sec-3-amenities",
    },
    {
        "id": "C09", "category": "CLARIFY", "severity": "medium",
        "one_line_he": "צבע כותרות הפרקים הראשיים — נדרש אימות ויזואלי שכל הכותרות בצבע טורקיז אחיד, כנדרש בחוברת ההנחיות (סעיף 6.2).",
        "source_section": "נספח א (פורמט)",
        "anchor_target_id": "sec-appendix-a",
    },
    {
        "id": "C10", "category": "CLARIFY", "severity": "medium",
        "one_line_he": "חץ צפון — נדרש אימות ויזואלי שחץ צפון מסומן בבירור על כל תוכנית מקצועית.",
        "source_section": "נספח א (פורמט)",
        "anchor_target_id": "sec-appendix-a",
    },
    {
        "id": "C11", "category": "CLARIFY", "severity": "low",
        "one_line_he": "תוכן עניינים — נדרש אימות ויזואלי שעמוד תוכן העניינים מאורגן בשלוש עמודות.",
        "source_section": "נספח א (פורמט)",
        "anchor_target_id": "sec-appendix-a",
    },
    {
        "id": "C12", "category": "CLARIFY", "severity": "medium",
        "one_line_he": "טבלת חניות במרתף ופירוט תמהיל יח״ד בקומה הטיפוסית — נדרשת השלמת מבנה הטבלה: חניות פר תא שטח ופירוט יח״ד לפי גודל דירה.",
        "source_section": "נספח א (פורמט)",
        "anchor_target_id": "sec-appendix-a",
    },
]


def build_inventory(project_id: str = "407-1048248",
                     submission_id: str = "v24.3") -> Dict[str, Any]:
    items = list(ITEMS_CURATED)
    items.sort(key=lambda x: (CATEGORY_ORDER.index(x["category"]),
                              SEVERITY_RANK.get(x["severity"], 9),
                              x["id"]))
    grouped: Dict[str, List[Dict[str, Any]]] = {c: [] for c in CATEGORY_ORDER}
    for it in items:
        grouped[it["category"]].append(it)
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project_id": project_id,
        "submission_id": submission_id,
        "audit_milestone": "M7.5-step1-integrated",
        "category_order": CATEGORY_ORDER,
        "category_labels_he": CATEGORY_LABELS_HE,
        "category_intros_he": CATEGORY_INTROS_HE,
        "counts": {c: len(grouped[c]) for c in CATEGORY_ORDER},
        "items_by_category": grouped,
    }


def _main_cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 7.5 — build architect summary inventory."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    inv = build_inventory(args.project_id, args.submission_id)
    out_path = args.output or (
        PROJECT_ROOT / "data" / "projects" / args.project_id
        / "submissions" / args.submission_id
        / "architect_summary_inventory.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(inv, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {out_path}", flush=True)
    print(f"  counts: {inv['counts']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main_cli())
