"""M5 coverage transparency assembler — section 5 source data.

Reads M0 + M1 + M2 + M3 + M4 + docs/known_issues.md and produces a
structured `coverage_report.json` that report_generator._render_section_5
consumes to render the new transparency section.

Section 5 layout (all in planning Hebrew):
  5.1 קטגוריות שנבדקו במלואן
  5.2 קטגוריות שנבדקו חלקית — explicit limitations listed
  5.3 קטגוריות שלא נבדקו אוטומטית — what Ellen MUST check manually
  5.4 כיסוי לפי עמודי ההגשה — 63-row per-page table
  5.5 הסתייגות — explicit Hebrew disclaimer
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ─────────────────────────────────────────────────────────────────────────────
# Hebrew category labels (for section 5.1 / 5.2 / 5.3)
# ─────────────────────────────────────────────────────────────────────────────

CATEGORY_HE: Dict[str, str] = {
    "identification":             "זיהוי וסיווג",
    "objectives":                 "מטרות",
    "land_use_zoning":            "ייעוד קרקע",
    "building_geometry":          "גאומטריית בינוי וקווי בניין",
    "building_rights":            "זכויות בנייה (טבלת זכויות)",
    "building_use":               "תכליות בנייה",
    "parking":                    "חניה",
    "infrastructure":             "תשתיות",
    "stormwater":                 "ניקוז ונגר",
    "tree_preservation":          "שימור עצים בוגרים",
    "unification_subdivision":    "איחוד וחלוקה",
    "public_areas":               "שטחי ציבור",
    "easements":                  "זיקות הנאה",
    "building_height_safety":     "בטיחות גובה בנייה",
    "phasing":                    "שלביות ביצוע",
    "procedural":                 "הוראות פרוצדורליות",
}


# Categories the engine ACTIVELY checks (M2/M4 + engine rules cover them well)
FULL_COVERAGE_CATEGORIES = {
    "building_geometry", "building_use", "parking", "building_rights",
    "building_height_safety", "identification", "procedural",
}

# Categories partially checked (rule density low or requires DWG)
PARTIAL_COVERAGE_CATEGORIES = {
    "infrastructure",      # has discipline coverage but no content rule for many sub-clauses
    "stormwater",          # 6.4.x covered but 75% runoff calc requires DWG
    "public_areas",        # mostly covered via gardens discipline but missing per-clause checks
    "tree_preservation",   # 6.5.1 caught but most other clauses uncovered
}

# Categories with zero or near-zero automated coverage — Ellen MUST check
NO_COVERAGE_CATEGORIES = {
    "easements",                # 8 clauses, zero engine rules (Task #28)
    "phasing",                  # 3 clauses, zero engine rules (Task #29)
    "land_use_zoning",          # not in normative set normally
    "unification_subdivision",  # procedural, no design check
    "objectives",
}

# Specific known coverage gaps to highlight in 5.3
HIGHLIGHTED_GAPS_HE: List[Dict[str, str]] = [
    {
        "title": "מעונות יום",
        "detail": "ההגשה מציגה מעונות יום בתא שטח 1 (עמודים 27-28) אך אין במנוע התאימות כלל ייעודי לבדיקת תקנות מעונות יום (שטח לכל ילד, חצרות, נגישות).",
        "task_ref": "Task #31",
    },
    {
        "title": 'זיקות הנאה (פינוי תת-קרקעי)',
        "detail": "תקנון מכיל 8 סעיפים נורמטיביים בקטגוריית זיקות הנאה — אף אחד מהם אינו מקבל בדיקה אוטומטית. ממצא חמור: זיקת הנאה מתא שטח 2 לחלקה 12 (סעיף 6.6.4) לא ממוצגת בהגשה.",
        "task_ref": "Task #28",
    },
    {
        "title": "שלביות ביצוע",
        "detail": "תקנון מציין תוכנית שלביות (שלב א/ב) בסעיף 7.1.1; אין שלביות בהגשה ואין במנוע כלל לבדיקה.",
        "task_ref": "Task #29",
    },
    {
        "title": "שטחי בנייה (עיקרי / שירות מעל / שירות מתחת)",
        "detail": "ההגשה אינה כוללת טבלת שטחים מפורטת. כל 33 שורות הבדיקה בקטגוריות אלו מציגות 'לא הוגש' (11 תאי שטח × 3 שדות). יש לצרף בהגשה הבאה טבלת שטחים מפורטת (שטח עיקרי / שטחי שירות מעל / שטחי שירות מתחת) פר תא שטח.",
        "task_ref": None,
    },
    {
        "title": "תאי שטח 6, 7, 8, 9, 10 ו-20",
        "detail": "תוכנית עיצוב v24.3 מתייחסת רק לתאי שטח 1-5. תאי השטח 6-10 (מבני ציבור, דרכים, שצ\"פ) ותא שטח 20 (דרך) מקבלים סטטוס 'לא הוגש' בכל הבדיקות. נדרשת הגשה משלימה או הצדקה לאי-הכללתם.",
        "task_ref": "Task #30",
    },
    {
        "title": "פירוט תמהיל דירות (קטנות / בינוניות / גדולות)",
        "detail": "ההגשה מציגה התפלגות לפי מספר חדרים, אך טבלת הזכויות וההוראות בתקנון התב\"ע (סעיף 5) מצריכה פילוח לפי שטח (≤55 מ\"ר / 56-75 / 76-99 / ≥100). בחלק מתאי השטח לא ניתן לפצל ללא שטח לכל יחידת דיור.",
        "task_ref": None,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Per-page coverage classification (mirrors submission_coverage_report.md heuristics)
# ─────────────────────────────────────────────────────────────────────────────

PAGE_TYPE_HE: Dict[str, str] = {
    "cover":                       "שער",
    "table_of_contents":           "תוכן עניינים",
    "summary":                     "סיכום",
    "site_plan_per_ta_shetach":    "תוכנית פיתוח פר תא שטח",
    "waste_diagram":               "דיאגרמת אשפה",
    "functions_diagram":           "דיאגרמת פונקציות",
    "daycare":                     "מעונות יום",
    "basement_with_parking_table": "מרתף עם טבלת חניה",
    "typical_floor":               "קומה טיפוסית",
    "cross_section":               "חתך",
    "elevation":                   "חזית",
    "public_open_space":           'שצ"פ',
    "rendering":                   "הדמיה",
    "legend_or_key":               "מקרא",
    "other":                       "אחר",
}


def _classify_page(manifest: Dict[str, Any]) -> str:
    """Return one of: FULL / PARTIAL / UNADDRESSED."""
    pt = manifest.get("page_type")
    refs = manifest.get("ta_shetach_refs") or []
    takanon_refs = [r for r in refs if r in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20}]
    unmapped = [r for r in refs if r not in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20}]

    # Cover-like pages, TOC, legends — always FULL (format-checked)
    if pt in {"cover", "table_of_contents", "legend_or_key", "rendering"}:
        return "FULL"
    if pt == "other":
        return "UNADDRESSED"
    if pt == "daycare":
        return "PARTIAL"  # no daycare-specific rules
    if pt == "summary":
        return "PARTIAL"
    # Cadastral-only pages (Task #27 unreconciled labels) — page has content,
    # just couldn't be linked to takanon plots. Treat as PARTIAL, not UNADDRESSED.
    if pt in {"public_open_space", "site_plan_per_ta_shetach"} and unmapped:
        return "PARTIAL"
    if unmapped and not takanon_refs:
        return "UNADDRESSED"
    if unmapped:
        return "PARTIAL"
    if takanon_refs:
        return "FULL"
    # No plot refs at all
    if pt in {"public_open_space", "waste_diagram"}:
        return "FULL"
    return "PARTIAL"


# ─────────────────────────────────────────────────────────────────────────────
# known_issues.md parser (extracts Task #28-#34 short descriptions)
# ─────────────────────────────────────────────────────────────────────────────

_TASK_HEADING_RE = re.compile(
    r"^#{2,3}\s*Task #(\d+)\s*—\s*(.+?)(?:\s*\(.*?\))?\s*$",
    re.MULTILINE,
)


def _parse_known_issues(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    out: Dict[str, str] = {}
    for m in _TASK_HEADING_RE.finditer(text):
        out[f"Task #{m.group(1)}"] = m.group(2).strip()
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Main assembler
# ─────────────────────────────────────────────────────────────────────────────


def assemble_coverage_report(
    *,
    canonical_clauses_path: Path,
    page_manifests_path: Path,
    vision_findings_path: Path,
    critic_findings_path: Path,
    audit_results_m4_path: Path,
    known_issues_path: Optional[Path] = None,
) -> Dict[str, Any]:
    cc_doc = json.loads(canonical_clauses_path.read_text(encoding="utf-8"))
    pm_doc = json.loads(page_manifests_path.read_text(encoding="utf-8"))
    vf_doc = json.loads(vision_findings_path.read_text(encoding="utf-8"))
    cf_doc = json.loads(critic_findings_path.read_text(encoding="utf-8"))
    m4_doc = json.loads(audit_results_m4_path.read_text(encoding="utf-8"))

    # Normative clauses by category
    normative = [c for c in cc_doc.get("clauses", []) if c.get("is_normative")]
    cat_counts: Dict[str, int] = Counter(c.get("category") for c in normative)

    # M4 content findings → per-category verdict counts
    content = m4_doc.get("content", []) or []
    # Build clause_id → category lookup from canonical_clauses
    clause_to_cat: Dict[str, str] = {
        c.get("clause_id"): c.get("category") for c in cc_doc.get("clauses", [])
    }
    # Engine rule_code → category mapping (manual — short)
    RULE_TO_CAT = {
        "CONTENT_UNIT_COUNT":                "building_rights",
        "CONTENT_BUILDING_AREA_MAIN":        "building_rights",
        "CONTENT_BUILDING_AREA_SERVICE_ABOVE": "building_rights",
        "CONTENT_BUILDING_AREA_SERVICE_BELOW": "building_rights",
        "CONTENT_BUILDING_HEIGHT":           "building_geometry",
        "CONTENT_SETBACKS":                  "building_geometry",
        "CONTENT_PARKING_RATIO":             "parking",
        "CONTENT_APARTMENT_MIX_SMALL":       "building_use",
        "CONTENT_PERMEABLE_SURFACES":        "stormwater",
    }

    cat_verdicts: Dict[str, Counter] = defaultdict(Counter)
    for f in content:
        cat = RULE_TO_CAT.get(f.get("rule_code"))
        if cat:
            cat_verdicts[cat][f.get("verdict")] += 1

    # 5.1 / 5.2 / 5.3 buckets
    def _bucket_for(cat: str) -> str:
        if cat in FULL_COVERAGE_CATEGORIES:
            return "full"
        if cat in PARTIAL_COVERAGE_CATEGORIES:
            return "partial"
        if cat in NO_COVERAGE_CATEGORIES:
            return "none"
        return "partial"

    full_list: List[Dict[str, Any]] = []
    partial_list: List[Dict[str, Any]] = []
    none_list: List[Dict[str, Any]] = []

    for cat, n_clauses in sorted(cat_counts.items()):
        bucket = _bucket_for(cat)
        entry = {
            "category": cat,
            "category_he": CATEGORY_HE.get(cat, cat),
            "normative_clauses": n_clauses,
            "verdict_counts": dict(cat_verdicts.get(cat, Counter())),
        }
        {"full": full_list, "partial": partial_list, "none": none_list}[bucket].append(entry)

    # 5.4 — per-page coverage table
    page_rows: List[Dict[str, Any]] = []
    for m in pm_doc.get("manifests", []):
        page_rows.append({
            "page_number": m.get("page_number"),
            "page_type": m.get("page_type"),
            "page_type_he": PAGE_TYPE_HE.get(m.get("page_type"), m.get("page_type") or ""),
            "ta_shetach_refs": m.get("ta_shetach_refs") or [],
            "coverage": _classify_page(m),
        })

    # 5.5 — disclaimer (single Hebrew block)
    disclaimer_he = (
        "סקירה אוטומטית זו אינה תחליף לבדיקה ידנית של מהנדס/ת המינהלת. "
        "הקטגוריות בסעיף 5.3 דורשות בדיקה אישית. סעיף זה נועד להבטיח שקיפות "
        "מלאה על היקף הבדיקה — מה נבדק אוטומטית, מה נבדק חלקית, ומה לא נבדק כלל."
    )

    # known_issues references (so 5.3 cards can footnote them)
    known_tasks = _parse_known_issues(known_issues_path) if known_issues_path else {}

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "m4_version": m4_doc.get("m4_version"),
        "summary": {
            "total_normative_clauses": len(normative),
            "engine_content_rules": len(RULE_TO_CAT),
            "page_count": len(page_rows),
            "page_coverage": dict(Counter(r["coverage"] for r in page_rows)),
        },
        "section_5_1_full":    full_list,
        "section_5_2_partial": partial_list,
        "section_5_3_none":    none_list,
        "section_5_3_highlighted_gaps": HIGHLIGHTED_GAPS_HE,
        "section_5_4_page_rows": page_rows,
        "section_5_5_disclaimer_he": disclaimer_he,
        "known_tasks": known_tasks,
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M5 coverage assembler.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--canonical-clauses", type=Path, default=None,
        help="default: data/projects/{project-id}/canonical_clauses.json",
    )
    parser.add_argument(
        "--page-manifests", type=Path, default=None,
        help="default: data/projects/{project-id}/submissions/{submission-id}/page_manifests.json",
    )
    parser.add_argument(
        "--vision-findings", type=Path, default=None,
        help="default: data/projects/{project-id}/submissions/{submission-id}/vision_findings.json",
    )
    parser.add_argument(
        "--critic-findings", type=Path, default=None,
        help="default: data/projects/{project-id}/submissions/{submission-id}/critic_findings.json",
    )
    parser.add_argument(
        "--audit-results-m4", type=Path, default=None,
        help="default: audit_outputs/{project-id}/{submission-id}/audit_results.m4.json",
    )
    parser.add_argument(
        "--known-issues", type=Path,
        default=PROJECT_ROOT / "docs" / "known_issues.md",
    )
    args = parser.parse_args(argv)

    sub_dir = PROJECT_ROOT / "data" / "projects" / args.project_id / "submissions" / args.submission_id
    audit_dir = PROJECT_ROOT / "audit_outputs" / args.project_id / args.submission_id

    cc = args.canonical_clauses or (PROJECT_ROOT / "data" / "projects" / args.project_id / "canonical_clauses.json")
    pm = args.page_manifests or (sub_dir / "page_manifests.json")
    vf = args.vision_findings or (sub_dir / "vision_findings.json")
    cf = args.critic_findings or (sub_dir / "critic_findings.json")
    m4 = args.audit_results_m4 or (audit_dir / "audit_results.m4.json")

    for p in (cc, pm, vf, cf, m4):
        if not p.exists():
            print(f"ERROR: missing input: {p}", file=sys.stderr)
            return 2

    report = assemble_coverage_report(
        canonical_clauses_path=cc,
        page_manifests_path=pm,
        vision_findings_path=vf,
        critic_findings_path=cf,
        audit_results_m4_path=m4,
        known_issues_path=args.known_issues,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = report["summary"]
    print(
        f"M5 coverage assembled → {args.output}\n"
        f"  full:    {len(report['section_5_1_full'])} categories\n"
        f"  partial: {len(report['section_5_2_partial'])} categories\n"
        f"  none:    {len(report['section_5_3_none'])} categories\n"
        f"  page rows: {summary['page_count']} "
        f"({summary['page_coverage']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
