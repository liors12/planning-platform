"""Phase 7.5 spike — standalone architect-facing summary PDF.

Walks all evidence sources for v24.3 + curates a tight ~15-25 item list
categorized into חסר / תיקונים / הבהרות. Outputs:
  data/projects/<plan>/submissions/<sub>/architect_summary_inventory.json
  audit_outputs/<plan>/<sub>/architect_summary_spike.pdf

Standalone — does NOT modify the main 53-page audit report.

Voice rules (HARD):
- Direct address to architect ("יש לצרף", "יש לתקן", "יש להבהיר")
- Architect vocabulary (תוכנית פיתוח, תשריט חזית, נספח חומריות)
- No internal references (engine, vision, critic, M-numbers)
- Active present-tense action verbs
- ≤ 25 Hebrew words per item
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Item curation — domain-specific, judgment-driven for the spike.
# Each item: (id, category, statement_he, severity, source_section, source_page)
# Categories: MISSING / FIX / CLARIFY
# Severity: high / medium / low (used for sort within category)
# source_page is the page in the main 53-page report where the architect
# can drill down for technical detail.
# ─────────────────────────────────────────────────────────────────────────────

ITEMS_CURATED: List[Dict[str, Any]] = [
    # ============== MISSING (חסר) — documents/drawings ==============
    {
        "id": "M01", "category": "MISSING", "severity": "high",
        "statement_he": "יש לצרף ששת הנספחים החיצוניים הנדרשים: נספח חומריות, רשימת צמחייה מפורטת, נספח הידרולוגי, נספח אקוסטי, נספח איכות סביבה וקיימות, ונספח ת״י 5281 (בנייה ירוקה).",
        "source_section": "פרק 4 פעולה #1 + פרק 3 (דיסציפלינות)",
        "source_page": 40,
    },
    {
        "id": "M02", "category": "MISSING", "severity": "high",
        "statement_he": "יש לצרף תכניות פיתוח עבור תאי שטח 6, 7, 8, 9, 10, ו-20 — אלו חלק סטטוטורי מהתב״ע ולא מופיעים בהגשה הנוכחית.",
        "source_section": "פרק 2ב (CAD)",
        "source_page": 24,
    },
    {
        "id": "M03", "category": "MISSING", "severity": "high",
        "statement_he": "יש לצרף טבלת שטחי בנייה מפורטת לכל תא שטח: שטח עיקרי, שטח שירות מעל הקרקע, שטח שירות תת-קרקעי — בנפרד מטבלת תמהיל הדירות.",
        "source_section": "פרק 4 פעולות #4/#10/#11",
        "source_page": 40,
    },
    {
        "id": "M04", "category": "MISSING", "severity": "high",
        "statement_he": "יש לצרף נספח עצים בוגרים. נספח זה מוזכר בתקנון אך אינו כלול בהגשה.",
        "source_section": "פרק 2א סעיף 6.5.1",
        "source_page": 21,
    },
    {
        "id": "M05", "category": "MISSING", "severity": "high",
        "statement_he": "יש לצרף תכנית שלביות ביצוע מפורטת לכלל תאי השטח (סעיף 7.1.1). ההגשה הנוכחית כוללת התייחסות חלקית לשצ״פ בלבד.",
        "source_section": "פרק 2א סעיף 7.1.1",
        "source_page": 22,
    },
    {
        "id": "M06", "category": "MISSING", "severity": "high",
        "statement_he": "יש לצרף תכנית ניקוז מפורטת עם חישוב נפח השהיה כולל של 450 מ״ק (סעיף 6.4.2), כולל מערכות החדרה ומפת אזורי חלחול.",
        "source_section": "פרק 2א סעיף 6.4.2 + פרק 3.5",
        "source_page": 21,
    },
    {
        "id": "M07", "category": "MISSING", "severity": "high",
        "statement_he": "יש לצרף ניתוח חשיפה לשמש (21.12, 09:00–15:00) וחישוב פוטנציאל פאנלים פוטו-וולטאיים בגג ובחזיתות.",
        "source_section": "פרק 4 פעולה #7 + פרק 3.10",
        "source_page": 41,
    },
    {
        "id": "M08", "category": "MISSING", "severity": "medium",
        "statement_he": "יש לסמן בכל תא שטח רחבת גזם ייעודית בקנ״מ 1:500, באבן משתלבת, ברצועה הצמודה לרחוב.",
        "source_section": "פרק 4 פעולה #12 + פרק 3.1",
        "source_page": 42,
    },
    {
        "id": "M09", "category": "MISSING", "severity": "medium",
        "statement_he": "יש לצרף את ששת פרקי המעטפת בחוברת ההגשה: פרק טיפולוגיות, פרק פיתוח, פרק מעטפת בניינים, פרק הנחיות סביבתיות, פרק הנחיות תשתיות ותנועה, פרק צוות הפרויקט.",
        "source_section": "נספח א (פורמט) §6.8 + §6.4",
        "source_page": 51,
    },
    {
        "id": "M10", "category": "MISSING", "severity": "medium",
        "statement_he": "יש להוסיף בעמוד הראשון של כל פרק מקצועי מקום ייעודי לחתימת רפרנט עירוני מהדיסציפלינה הרלוונטית.",
        "source_section": "נספח א (פורמט) §6.10",
        "source_page": 52,
    },

    # ============== FIX (תיקונים) — wrong, must be changed ==============
    {
        "id": "F01", "category": "FIX", "severity": "high",
        "statement_he": "יש להוסיף בתשריטי תא שטח 2 (עמ׳ 37 + עמ׳ 34) זיקת הנאה תת-קרקעית למעבר רכב מתא שטח 2 לתא שטח 12 הסמוך (סעיף 6.6.4) — כיום לא מוצגת בהגשה.",
        "source_section": "פרק 2א סעיף 6.6.4",
        "source_page": 21,
    },
    {
        "id": "F02", "category": "FIX", "severity": "high",
        "statement_he": "יש לציין במפורש בעמוד השער את תאריך ההגשה ואת מספר התב״ע בפורמט 407-1048248 — שניהם חסרים או לא תקניים בהגשה הנוכחית.",
        "source_section": "נספח א (פורמט) §6.3",
        "source_page": 49,
    },
    {
        "id": "F03", "category": "FIX", "severity": "high",
        "statement_he": "יש לצרף בעמוד השער טבלת חתימות הכוללת את 6 הדיסציפלינות הנדרשות: שפ״ע כבישים ופיתוח, תנועה, גנים ונוף, אדריכלות, תאגיד, יו״ר הוועדה.",
        "source_section": "נספח א (פורמט) §6.3",
        "source_page": 49,
    },
    {
        "id": "F04", "category": "FIX", "severity": "medium",
        "statement_he": "יש להחליף ב-18 עמודי הגשה רקעים שאינם לבנים (גוונים, באנרים, גרדיאנטים). דרישה: רקע לבן בכל עמודי החוברת.",
        "source_section": "נספח א (פורמט) §6.1",
        "source_page": 49,
    },
    {
        "id": "F05", "category": "FIX", "severity": "medium",
        "statement_he": "יש לציין בכותרת כל תוכנית מקצועית את קנה המידה 1:250 ולוודא שהפלט מודפס בקנ״מ זה — הדרישה מעוגנת גם בסעיף 6.1 לתקנון התב״ע.",
        "source_section": "נספח א (פורמט) §6.10",
        "source_page": 52,
    },
    {
        "id": "F06", "category": "FIX", "severity": "medium",
        "statement_he": "יש להוסיף סימוני מידות מפורשים על תוכניות הפיתוח, הקומה הטיפוסית והמרתפים (גובה בניין, מרחקי קווי בניין, מידות חזית) — חסרים בעמודים מקצועיים רבים.",
        "source_section": "נספח א (פורמט) §6.10",
        "source_page": 52,
    },

    # ============== CLARIFY (הבהרות) — needs explanation ==============
    {
        "id": "C01", "category": "CLARIFY", "severity": "high",
        "statement_he": "תא שטח 5 — שני מפלסים בתשריטים מציגים גובה מוחלט מעל תקרת §6.7 (91.00 מ׳ מעל פני הים): 91.30 מ׳ בעמ׳ 50 ו-91.80 מ׳ בעמ׳ 58. יש להבהיר האם מדובר באביזרי גג (פרפט, מעליות), בקווי מעטפת רגולטוריים, או בחריגה אמיתית.",
        "source_section": "פרק 2ג (חתכים)",
        "source_page": 25,
    },
    {
        "id": "C02", "category": "CLARIFY", "severity": "medium",
        "statement_he": "מבנה A2 — שני תשריטי חזית מציגים גובה קרקע מוחלט שונה: 44.50 מ׳ (עמ׳ 53) מול 42.00 מ׳ (עמ׳ 57). גובה המבנה זהה (32.85 מ׳). יש להבהיר מהו קו האפס הקנוני ולעדכן בהתאם.",
        "source_section": "פרק 2ג (חתכים)",
        "source_page": 26,
    },
    {
        "id": "C03", "category": "CLARIFY", "severity": "medium",
        "statement_he": "מבנה B4 — שני תשריטים מציגים גובה קרקע מוחלט שונה (47.75 מ׳ ו-49.10 מ׳). בעמ׳ 57 קיימת סתירה פנימית: הקרקע המסומנת היא 49.10 מ׳ אך החישוב מהפרשי המפלסים מצביע על 47.75 מ׳. יש להבהיר ולעדכן.",
        "source_section": "פרק 2ג (חתכים)",
        "source_page": 27,
    },
    {
        "id": "C04", "category": "CLARIFY", "severity": "high",
        "statement_he": "טבלת \"ריכוז תמהיל דירות\" מציגה מספר יחידות דיור (232) במקומות בהם תקנון התב״ע (טבלת הזכויות וההוראות) מצפה לשטחי בנייה. יש להציג בנפרד את שטחי הבנייה כדי לאפשר אימות מול תקרת התב״ע.",
        "source_section": "פרק 2א — כרטיסי טבלת הזכויות",
        "source_page": 22,
    },
    {
        "id": "C05", "category": "CLARIFY", "severity": "high",
        "statement_he": "אחוז דירות קטנות — האדריכל מצהיר על 21% (147/700) על בסיס הגדרה רחבה (≤81 מ״ר). אימות מול דרישת 20% מצריך טבלת תמהיל עם שטח לכל יחידת דיור — כיום אינה קיימת.",
        "source_section": "פרק 4 פעולה #2",
        "source_page": 40,
    },
    {
        "id": "C06", "category": "CLARIFY", "severity": "high",
        "statement_he": "יחס חניה — מחושב 1.42 (330/232 יח״ד), מעל הסף האיכותי 1.3. אימות התאמה לתקן חניה לאומי 3.1 (1.0–1.5 לפי גודל דירה + 20% אורחים) מצריך טבלת שטחים פר יחידת דיור — חסרה.",
        "source_section": "פרק 4 פעולה #8 + פרק 2",
        "source_page": 41,
    },
    {
        "id": "C07", "category": "CLARIFY", "severity": "high",
        "statement_he": "קווי בניין (כל תאי השטח) — לא ניתן לאמת אוטומטית ללא קובץ DWG מפורק. עד אז נדרשת השלמת אימות ידני של מהנדס/ת המינהלת מול התשריט.",
        "source_section": "פרק 4 פעולה #9 + פרק 2",
        "source_page": 41,
    },
    {
        "id": "C08", "category": "CLARIFY", "severity": "medium",
        "statement_he": "בדיאגרמות הפונקציות (עמ׳ 26, 36, 41, 45) לא זוהו חדר ועד בית ולא חדר תאי דואר. יש להבהיר האם אלה קיימים בעמודים אחרים, אינם נדרשים על-פי הנחיות נס ציונה, או שיש להוסיפם בהגשה הבאה.",
        "source_section": "פרק 3.11 + פרק 4",
        "source_page": 42,
    },
    {
        "id": "C09", "category": "CLARIFY", "severity": "medium",
        "statement_he": "צבע כותרות הפרקים הראשיים — נדרש אימות ויזואלי שכל הכותרות בצבע טורקיז אחיד, כנדרש בחוברת ההנחיות (§6.2).",
        "source_section": "נספח א (פורמט)",
        "source_page": 49,
    },
    {
        "id": "C10", "category": "CLARIFY", "severity": "medium",
        "statement_he": "חץ צפון — נדרש אימות ויזואלי שחץ צפון מסומן בבירור על כל תוכנית מקצועית (פיתוח, מפלסים, מרתף, קומה טיפוסית).",
        "source_section": "נספח א (פורמט) §6.10",
        "source_page": 52,
    },
    {
        "id": "C11", "category": "CLARIFY", "severity": "low",
        "statement_he": "תוכן עניינים — נדרש אימות ויזואלי שעמוד תוכן העניינים מאורגן בשלוש עמודות (כל פרק ראשי מתחיל בעמודה, ללא המשך משורה קודמת בעמודה אחרת).",
        "source_section": "נספח א (פורמט) §6.5",
        "source_page": 49,
    },
    {
        "id": "C12", "category": "CLARIFY", "severity": "medium",
        "statement_he": "טבלת חניות במרתף ופירוט תמהיל יח״ד בקומה הטיפוסית — נדרשת השלמת מבנה הטבלה: חניות פר תא שטח (פרטיות / אופנועים / נגישות / אופניים) ופירוט יח״ד לפי גודל דירה.",
        "source_section": "נספח א (פורמט) §6.9",
        "source_page": 51,
    },
]


CATEGORY_LABELS_HE = {
    "MISSING":  "חסר — מסמכים ונספחים שיש לצרף",
    "FIX":      "תיקונים — שינויים בהגשה הנוכחית",
    "CLARIFY":  "הבהרות — שאלות הדורשות תשובה",
}
CATEGORY_SHORT_HE = {
    "MISSING": "חסר",
    "FIX":     "תיקונים",
    "CLARIFY": "הבהרות",
}
CATEGORY_ORDER = ["MISSING", "FIX", "CLARIFY"]
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


# ─────────────────────────────────────────────────────────────────────────────
# Inventory builder
# ─────────────────────────────────────────────────────────────────────────────

def build_inventory() -> Dict[str, Any]:
    items = list(ITEMS_CURATED)
    # Sort within each category by severity then id
    items.sort(key=lambda x: (CATEGORY_ORDER.index(x["category"]),
                              SEVERITY_RANK.get(x["severity"], 9),
                              x["id"]))
    grouped: Dict[str, List[Dict[str, Any]]] = {c: [] for c in CATEGORY_ORDER}
    for it in items:
        grouped[it["category"]].append(it)
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project_id": "407-1048248",
        "submission_id": "v24.3",
        "audit_milestone": "M7.5-spike",
        "main_report_pages": 53,
        "main_report_sha256": "f40ea29ca8fd940ecb2162030969c01cdbbe3aec6b707b842c5dbc415998832d",
        "counts": {c: len(grouped[c]) for c in CATEGORY_ORDER},
        "items_by_category": grouped,
        "all_items": items,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PDF render (WeasyPrint)
# ─────────────────────────────────────────────────────────────────────────────

CSS = """
@font-face {
  font-family: 'Heebo';
  src: url('Heebo-Regular.ttf');
  font-weight: 100 900;
}
@page {
  size: A4;
  margin: 18mm 22mm 18mm 22mm;
  @bottom-center {
    content: "סקירת תוכנית עיצוב v24.3 — מסמך לעיון האדריכל";
    font-family: 'Heebo', sans-serif;
    font-size: 8pt;
    color: #888;
  }
  @bottom-right {
    content: counter(page) " / " counter(pages);
    font-family: 'Heebo', sans-serif;
    font-size: 8pt;
    color: #888;
  }
}
@page cover {
  size: A4;
  margin: 22mm 22mm 18mm 22mm;
  @bottom-center { content: none; }
  @bottom-right { content: none; }
}
html { direction: rtl; }
body {
  direction: rtl;
  text-align: right;
  font-family: 'Heebo', 'Simple CLM', 'Arial Hebrew', sans-serif;
  margin: 0;
  padding: 0;
  color: #1a1a1a;
  font-size: 11pt;
  line-height: 1.65;
}
* { box-sizing: border-box; }

.cover {
  page: cover;
  padding-top: 30mm;
}
.cover .eyebrow {
  font-size: 10pt;
  color: #888;
  margin-bottom: 8mm;
}
.cover h1 {
  font-size: 26pt;
  font-weight: 700;
  color: #1a1a1a;
  margin: 0 0 4mm 0;
  line-height: 1.25;
}
.cover .plan-meta {
  font-size: 13pt;
  color: #424242;
  margin-bottom: 14mm;
  line-height: 1.6;
}
.cover .plan-meta strong { font-weight: 700; }
.cover .summary-counts {
  display: flex;
  gap: 12mm;
  margin: 14mm 0 18mm 0;
}
.cover .count-block {
  flex: 1;
  padding: 6mm 5mm;
  border: 1px solid #d6d6d6;
  border-radius: 3px;
  text-align: center;
}
.cover .count-block .num {
  font-size: 32pt;
  font-weight: 700;
  color: #1a1a1a;
  line-height: 1;
  margin-bottom: 2mm;
}
.cover .count-block .label {
  font-size: 11pt;
  color: #424242;
  line-height: 1.3;
}
.cover .context {
  margin-top: 14mm;
  padding: 6mm 7mm;
  background: #fafafa;
  border-right: 3px solid #888;
  font-size: 11pt;
  color: #424242;
  line-height: 1.7;
}
.cover .context p { margin: 0 0 3mm 0; }
.cover .context p:last-child { margin-bottom: 0; }

.category-page {
  page-break-before: always;
}
.category-page h2 {
  font-size: 20pt;
  font-weight: 700;
  color: #1a1a1a;
  margin: 0 0 2mm 0;
  border-bottom: 2px solid #1a1a1a;
  padding-bottom: 3mm;
}
.category-page .cat-intro {
  font-size: 10pt;
  color: #888;
  margin-bottom: 8mm;
  font-style: italic;
}
.category-page .item-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.category-page .item {
  margin-bottom: 6mm;
  padding-bottom: 6mm;
  border-bottom: 1px solid #eee;
  page-break-inside: avoid;
}
.category-page .item:last-child {
  border-bottom: none;
}
.category-page .item-num {
  font-size: 12pt;
  font-weight: 700;
  color: #1a1a1a;
  margin-left: 2mm;
}
.category-page .item-text {
  font-size: 11pt;
  color: #1a1a1a;
  line-height: 1.7;
}
.category-page .item-text strong { font-weight: 700; }
.category-page .item-meta {
  margin-top: 2mm;
  font-size: 9.5pt;
  color: #888;
}
.category-page .item-meta .anchor {
  color: #555;
}
.category-page .sev-high { border-right: 3px solid #c62828; padding-right: 4mm; }
.category-page .sev-medium { border-right: 3px solid #f57c00; padding-right: 4mm; }
.category-page .sev-low { border-right: 3px solid #d6d6d6; padding-right: 4mm; }

.map-page { page-break-before: always; }
.map-page h2 {
  font-size: 20pt;
  font-weight: 700;
  margin: 0 0 6mm 0;
  border-bottom: 2px solid #1a1a1a;
  padding-bottom: 3mm;
}
.map-page .map-intro {
  font-size: 11pt;
  color: #424242;
  margin-bottom: 8mm;
  line-height: 1.7;
}
table.map-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 4mm;
}
table.map-table th, table.map-table td {
  border-bottom: 1px solid #eee;
  padding: 3mm 4mm;
  text-align: right;
  font-size: 10.5pt;
}
table.map-table th {
  font-weight: 700;
  color: #1a1a1a;
  background: #fafafa;
}
table.map-table td.section-cell { font-weight: 600; width: 22%; }
table.map-table td.page-cell { width: 14%; color: #555; }

.closing {
  margin-top: 10mm;
  padding-top: 6mm;
  border-top: 1px solid #d6d6d6;
  font-size: 9.5pt;
  color: #888;
  font-style: italic;
  line-height: 1.7;
}
"""


def _esc(s: Any) -> str:
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def _render_cover(inv: Dict[str, Any]) -> str:
    counts = inv["counts"]
    today = dt.datetime.now().strftime("%d.%m.%Y")
    return f"""
    <div class="cover">
      <div class="eyebrow">המינהלת להתחדשות עירונית — עיריית נס ציונה</div>
      <h1>סיכום פעולות נדרשות לאדריכל</h1>
      <div class="plan-meta">
        <strong>תכנית סטטוטורית:</strong> 407-1048248 — מתחם הטייסים-ההסתדרות<br>
        <strong>הגשה:</strong> תוכנית עיצוב v24.3<br>
        <strong>תאריך הסקירה:</strong> {today}<br>
        <strong>סוג מסמך:</strong> מסמך עזר לעיון האדריכל (טיוטה)
      </div>
      <div class="summary-counts">
        <div class="count-block">
          <div class="num">{counts['MISSING']}</div>
          <div class="label">חסר<br>(מסמכים לצירוף)</div>
        </div>
        <div class="count-block">
          <div class="num">{counts['FIX']}</div>
          <div class="label">תיקונים<br>(שינויים בהגשה)</div>
        </div>
        <div class="count-block">
          <div class="num">{counts['CLARIFY']}</div>
          <div class="label">הבהרות<br>(שאלות לתשובה)</div>
        </div>
      </div>
      <div class="context">
        <p>מסמך זה מסכם את הפעולות הנדרשות מצד האדריכל בעקבות סקירת הגשה v24.3.
        הפעולות מחולקות לשלוש קטגוריות לסקירה מהירה.</p>
        <p>למסמך המלא, כולל פירוט מקצועי של כל ממצא ועיגון לסעיפי התקנון
        ולחוברת ההנחיות העירונית, ראה הדו"ח המלא של {inv['main_report_pages']} העמודים
        המצורף — בכל פריט להלן מצוין מספר העמוד הרלוונטי בדו"ח המלא.</p>
        <p>מסמך זה אינו מהווה חוות דעת רשמית של מהנדס/ת הוועדה המקומית.
        חוות הדעת תינתן לאחר סקירה וחתימה של בעלי התפקידים המוסמכים על הדו"ח המלא.</p>
      </div>
    </div>
    """


def _render_category_page(category: str, items: List[Dict[str, Any]]) -> str:
    if category == "MISSING":
        intro = "מסמכים, תכניות ונספחים שיש לצרף בהגשה הבאה. ממוינים לפי דחיפות."
    elif category == "FIX":
        intro = "פריטים שהוגשו אך דורשים שינוי. ממוינים לפי דחיפות."
    else:  # CLARIFY
        intro = "פריטים הדורשים הבהרה או אישור מצד האדריכל. ממוינים לפי דחיפות."

    items_html = []
    for i, it in enumerate(items, 1):
        sev_class = f"sev-{it['severity']}"
        statement = _esc(it["statement_he"])
        # Make "יש לצרף" / "יש לתקן" / "יש להבהיר" bold for scan-ability
        for verb in ["יש לצרף", "יש לתקן", "יש להבהיר", "יש להוסיף",
                     "יש לציין", "יש להחליף", "יש לסמן"]:
            statement = statement.replace(verb, f"<strong>{verb}</strong>", 1)
        anchor = (
            f"→ ראה {_esc(it['source_section'])} "
            f"(עמ׳ {it['source_page']} בדו״ח המלא)"
        )
        items_html.append(f"""
        <li class="item {sev_class}">
          <div class="item-text">
            <span class="item-num">{i}.</span>{statement}
          </div>
          <div class="item-meta">
            <span class="anchor">{anchor}</span>
          </div>
        </li>
        """)

    title = CATEGORY_LABELS_HE[category]
    return f"""
    <div class="category-page">
      <h2>{_esc(title)}</h2>
      <p class="cat-intro">{_esc(intro)} סה״כ {len(items)} פריטים.</p>
      <ul class="item-list">
        {''.join(items_html)}
      </ul>
    </div>
    """


def _render_map_page() -> str:
    rows = [
        ("פרק 1", "ניתוח תכנון עירוני (לבדיקה ידנית של מהנדס/ת המינהלת)", 5),
        ("פרק 2", 'בדיקת תאימות תוכן לתב"ע — פירוט פר תא שטח', 6),
        ("פרק 2א", "ממצאי בדיקה ויזואלית נוספים (סעיפים ללא כלל בדיקה ייעודי)", 20),
        ("פרק 2ב", 'ממצאי בדיקה מבוססת תשריט CAD (תאי שטח חסרים)', 24),
        ("פרק 2ג", "ממצאי בדיקת חתכים — אימות גבהים מוחלטים", 25),
        ("פרק 3", "בדיקה רב-תחומית לפי חוברת ההנחיות העירונית", 28),
        ("פרק 3.11", "מלאי שירותים לדיירים", 39),
        ("פרק 4", "סיכום וממצאים סופיים — רשימת פעולות מפורטת", 40),
        ("פרק 5", "היקף הבדיקה האוטומטית — שקיפות הכיסוי", 43),
        ("נספח א", "ליקויי פורמט בחוברת ההגשה", 48),
    ]
    table_rows = "".join(
        f"<tr><td class='section-cell'>{_esc(s)}</td>"
        f"<td>{_esc(t)}</td>"
        f"<td class='page-cell'>עמ׳ {p}</td></tr>"
        for s, t, p in rows
    )
    return f"""
    <div class="map-page">
      <h2>מפת הדו״ח המלא</h2>
      <p class="map-intro">המסמך שלפניכם הוא תמצית. הדו״ח המלא (53 עמודים) כולל את הפרקים הבאים —
      בכל פריט בעמודים הקודמים מצוין העמוד הרלוונטי לפירוט המקצועי.</p>
      <table class="map-table">
        <thead>
          <tr><th>פרק</th><th>תוכן</th><th>עמוד</th></tr>
        </thead>
        <tbody>{table_rows}</tbody>
      </table>
      <p class="closing">מסמך זה נוצר על-ידי מערכת הסקירה האוטומטית של המינהלת. הוא נועד לסייע
      לאדריכל לזהות במהירות את הפעולות הנדרשות לקראת הגשה מתוקנת. אינו מהווה חוות
      דעת רשמית; חוות הדעת תינתן לאחר חתימת בעלי התפקידים המוסמכים על הדו״ח המלא.</p>
    </div>
    """


def render_pdf(inv: Dict[str, Any], out_path: Path) -> None:
    grouped = inv["items_by_category"]
    parts = [_render_cover(inv)]
    for cat in CATEGORY_ORDER:
        parts.append(_render_category_page(cat, grouped[cat]))
    parts.append(_render_map_page())

    html_doc = (
        '<!DOCTYPE html><html lang="he" dir="rtl"><head>'
        f'<style>{CSS}</style></head><body>'
        + ''.join(parts)
        + '</body></html>'
    )

    # Use WeasyPrint with font fallback to repo's Heebo TTF
    from weasyprint import HTML
    HTML(string=html_doc, base_url=str(ROOT / "compliance_engine")).write_pdf(str(out_path))


def main() -> int:
    inv = build_inventory()
    inv_path = (
        ROOT / "data" / "projects" / "407-1048248" / "submissions" / "v24.3"
        / "architect_summary_inventory.json"
    )
    inv_path.parent.mkdir(parents=True, exist_ok=True)
    inv_path.write_text(json.dumps(inv, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote inventory: {inv_path}")
    print(f"  counts: {inv['counts']}")

    pdf_path = (
        ROOT / "audit_outputs" / "407-1048248" / "v24.3"
        / "architect_summary_spike.pdf"
    )
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    render_pdf(inv, pdf_path)

    import subprocess
    size = pdf_path.stat().st_size
    sha = subprocess.check_output(["shasum", "-a", "256", str(pdf_path)]).decode().split()[0]
    # page count via fitz
    import fitz
    npages = len(fitz.open(str(pdf_path)))
    print(f"Wrote PDF: {pdf_path}")
    print(f"  size: {size:,} bytes  pages: {npages}  sha256: {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
