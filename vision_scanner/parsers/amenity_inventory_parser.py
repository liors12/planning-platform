"""Phase 7.4 — Resident-amenities inventory (Architecture C).

Scope: scan the four `functions_diagram` pages (26, 36, 41, 45) in M1's
manifest, parse each page's `visible_text_labels`, and build a per-amenity ×
per-plot matrix. No new extraction (zero API cost) — pure regex over M1 data.

Output: data/projects/<plan>/submissions/<sub>/amenity_inventory.json
Render path: compliance_engine.report_generator → §3.11 "שירותים לדיירים"

No compliance verdicts. The knowledge base encodes one soft requirement
(§4.1.2.12 — bike rooms) and that's already audited by the main engine. This
parser produces an INVENTORY for the reviewer to consider; gaps surface as
a soft clarification action item in §4, never as non_compliance.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ─────────────────────────────────────────────────────────────────────────────
# Amenity taxonomy — fixed list + label patterns
# ─────────────────────────────────────────────────────────────────────────────
# Each entry: (key, hebrew, [label_pattern, ...], regulatory_anchor, audit_note)
# `label_patterns` are simple substrings that must appear in M1's
# visible_text_labels to count as a detection. Multiple patterns = OR.
#
# Row order in the rendered table is INTENTIONAL: amenities with regulatory
# anchors first, then always-detected, then partial, then never-detected.
# This makes gaps visually apparent at the bottom of the table.

AMENITIES: List[Dict[str, Any]] = [
    # NOTE: דירת גן (garden apartment) is a unit type, not a shared resident
    # service — excluded from this inventory per Lior 2026-05-25.
    # NOTE: לובי (lobby) is structurally a given on every residential floor
    # plan — 5/5 detection isn't informative — excluded for the same reason.
    # Both stay parseable from M1 visible_text_labels if a future audit
    # dimension needs them; the AMENITIES list controls the §3.11 table only.
    {
        "key": "bike_room",
        "hebrew": "חדר אופניים",
        "label_patterns": ["אופניים"],
        "regulatory_anchor": "§4.1.2.12 לתקנון התב\"ע — הוראה רכה",
        "audit_note": "נבדק כתקין במסגרת מנוע הציות (סעיף 4.1.2.12).",
    },
    {
        "key": "stroller_room",
        "hebrew": "חדר עגלות",
        "label_patterns": ["עגלות"],
        "regulatory_anchor": None,
        "audit_note": None,
    },
    {
        "key": "clubhouse",
        "hebrew": "מועדון דיירים",
        "label_patterns": ["מועדון"],
        "regulatory_anchor": None,
        "audit_note": None,
    },
    {
        "key": "gym",
        "hebrew": "חדר כושר / מתקני כושר",
        "label_patterns": ["כושר"],
        "regulatory_anchor": None,
        "audit_note": None,
    },
    {
        "key": "private_storage",
        "hebrew": "מחסן (ברמת מבנה)",
        "label_patterns": ["מחסן"],
        "regulatory_anchor": "§5 הערת שוליים בתקנון — ≤6 מ\"ר ליח\"ד (מחסן פרטי, לא ברמת מבנה)",
        "audit_note": "מצוין בנפרד מנושא שטחי הבנייה.",
    },
    {
        "key": "hoa_room",
        "hebrew": "חדר ועד בית",
        "label_patterns": ["ועד בית", "חדר ועד"],
        "regulatory_anchor": None,
        "audit_note": None,
    },
    {
        "key": "mailbox_room",
        "hebrew": "חדר תאי דואר",
        "label_patterns": ["תאי דואר", "דואר"],
        "regulatory_anchor": None,
        "audit_note": None,
    },
]


# Residential plots — the only ones for which amenity questions make sense.
# Plots 6, 7, 8 (שצ"פ), 9 (מבני ציבור), 10 (דרך), 20 (שביל) are non-residential
# and are marked "לא רלוונטי" in the inventory table.
RESIDENTIAL_PLOTS = [1, 2, 3, 4, 5]
NON_RESIDENTIAL_PLOTS = [6, 7, 8, 9, 10, 20]


# Pages we mine. Each is M1-classified as `functions_diagram` and lists the
# amenity rooms in its visible_text_labels field.
FUNCTIONS_DIAGRAM_PAGES = (26, 36, 41, 45)


# ─────────────────────────────────────────────────────────────────────────────
# Core matrix builder
# ─────────────────────────────────────────────────────────────────────────────

def _functions_pages_by_plot(manifests_doc: Dict[str, Any]) -> Dict[int, List[Dict[str, Any]]]:
    """Group functions_diagram pages by the residential plot(s) they cover.

    Returns { plot_id: [ {page_number, labels:[...]} , ... ] }
    """
    out: Dict[int, List[Dict[str, Any]]] = {p: [] for p in RESIDENTIAL_PLOTS}
    for p in manifests_doc.get("manifests", []) or []:
        n = p.get("page_number")
        if n not in FUNCTIONS_DIAGRAM_PAGES:
            continue
        if p.get("page_type") != "functions_diagram":
            continue
        refs = p.get("ta_shetach_refs") or []
        labels = p.get("visible_text_labels") or []
        for plot_id in refs:
            try:
                pid_int = int(plot_id)
            except (TypeError, ValueError):
                continue
            if pid_int in out:
                out[pid_int].append({"page_number": n, "labels": list(labels)})
    return out


def _match_amenity_on_page(
    page: Dict[str, Any],
    patterns: List[str],
) -> Optional[Dict[str, Any]]:
    """If any of `patterns` is a substring of one of the page's labels,
    return a hit dict with the matching raw_label + source_page. Else None.
    """
    for label in page.get("labels", []):
        if not isinstance(label, str):
            continue
        for pat in patterns:
            if pat in label:
                return {
                    "detected": True,
                    "source_page": page["page_number"],
                    "raw_label": label,
                }
    return None


def build_amenity_matrix(manifests_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Top-level: scan M1 manifests, produce the inventory matrix.

    Output structure:
      {
        "project_id": ...,
        "generated_at": "<iso8601 utc>",
        "source_pages": [26, 36, 41, 45],
        "residential_plots": [1, 2, 3, 4, 5],
        "amenities": [
          {
            "key": "bike_room",
            "hebrew": "חדר אופניים",
            "regulatory_anchor": "§4.1.2.12 ...",
            "audit_note": "נבדק כתקין ...",
            "per_plot": {
              "1": {"detected": True, "source_page": 26, "raw_label": "..."},
              ...
              "6": {"detected": False, "non_residential": True},
              ...
            },
            "detection_rate": 5,
            "detected_anywhere": True
          }, ...
        ],
        "gaps_summary": {
          "never_detected": ["hoa_room", "mailbox_room"],
          "always_detected": ["bike_room", "stroller_room", "clubhouse", "lobby"],
          "partial": ["gym", "private_storage", "garden_apartment"]
        },
        "clarification_needed": {
          "hebrew": "...",   # set when there are gaps that warrant Ellen's flag
          "missing_categories": ["חדר ועד בית", "חדר תאי דואר"]
        }
      }
    """
    pages_by_plot = _functions_pages_by_plot(manifests_doc)

    out_amenities = []
    for amenity in AMENITIES:
        per_plot: Dict[str, Dict[str, Any]] = {}
        for plot_id in RESIDENTIAL_PLOTS:
            hit = None
            for page in pages_by_plot.get(plot_id, []):
                hit = _match_amenity_on_page(page, amenity["label_patterns"])
                if hit:
                    break
            per_plot[str(plot_id)] = hit or {"detected": False}
        for plot_id in NON_RESIDENTIAL_PLOTS:
            per_plot[str(plot_id)] = {"detected": False, "non_residential": True}

        detection_rate = sum(
            1 for pid in RESIDENTIAL_PLOTS
            if per_plot[str(pid)].get("detected")
        )
        out_amenities.append({
            "key": amenity["key"],
            "hebrew": amenity["hebrew"],
            "regulatory_anchor": amenity["regulatory_anchor"],
            "audit_note": amenity["audit_note"],
            "per_plot": per_plot,
            "detection_rate": detection_rate,
            "detected_anywhere": detection_rate > 0,
        })

    # Sort: anchored first, then always-detected, then partial, then never
    def _sort_key(a):
        # primary: has anchor → 0, else 1
        anchor_tier = 0 if a["regulatory_anchor"] else 1
        # secondary: detection rate (desc)
        rate_tier = -a["detection_rate"]
        # tertiary: stable by Hebrew name
        return (anchor_tier, rate_tier, a["hebrew"])
    out_amenities.sort(key=_sort_key)

    never_detected = [a["key"] for a in out_amenities if a["detection_rate"] == 0]
    always_detected = [
        a["key"] for a in out_amenities
        if a["detection_rate"] == len(RESIDENTIAL_PLOTS)
    ]
    partial = [
        a["key"] for a in out_amenities
        if 0 < a["detection_rate"] < len(RESIDENTIAL_PLOTS)
    ]

    # Clarification item: only when notable gaps exist (HOA / mailbox typically)
    missing_hebrew_names = [
        a["hebrew"] for a in out_amenities
        if a["detection_rate"] == 0
    ]
    clarification = None
    if missing_hebrew_names:
        bullet = "\n".join(f"- {n}" for n in missing_hebrew_names)
        clarification = {
            "missing_categories": missing_hebrew_names,
            "hebrew": (
                "דרישה לעיון: לא זוהו בדיאגרמות הפונקציות בעמודי "
                "26, 36, 41, 45 הקטגוריות הבאות:\n"
                f"{bullet}\n\n"
                "ייתכן שמדובר באלמנטים נדרשים שאינם מתוארים בדיאגרמות "
                "הקיימות. יש להבהיר האם:\n"
                "א. אלמנטים אלה קיימים בהגשה ומתוארים בעמודים אחרים;\n"
                "ב. אלמנטים אלה אינם נדרשים על-פי הנחיות נס ציונה;\n"
                "ג. אלמנטים אלה חסרים ויש להוסיפם בהגשה הבאה."
            ),
        }

    return {
        "project_id": manifests_doc.get("plan_id"),
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_pages": list(FUNCTIONS_DIAGRAM_PAGES),
        "residential_plots": RESIDENTIAL_PLOTS,
        "amenities": out_amenities,
        "gaps_summary": {
            "always_detected": always_detected,
            "partial": partial,
            "never_detected": never_detected,
        },
        "clarification_needed": clarification,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _project_data_dir(project_id: str) -> Path:
    return PROJECT_ROOT / "data" / "projects" / project_id


def _main_cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 7.4 — build amenity inventory from M1 manifests."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    manifests_path = (
        _project_data_dir(args.project_id) / "submissions" / args.submission_id
        / "page_manifests.json"
    )
    if not manifests_path.exists():
        print(f"ERROR: page_manifests.json missing at {manifests_path}", flush=True)
        return 2

    manifests_doc = json.loads(manifests_path.read_text(encoding="utf-8"))
    matrix = build_amenity_matrix(manifests_doc)

    out_path = args.output or (
        _project_data_dir(args.project_id) / "submissions" / args.submission_id
        / "amenity_inventory.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {out_path}", flush=True)

    # Summary to stdout
    print(f"  amenities tracked: {len(matrix['amenities'])}")
    for a in matrix["amenities"]:
        marker = "✓" if a["detected_anywhere"] else "—"
        print(f"    {marker} {a['hebrew']:<35} ({a['detection_rate']}/{len(RESIDENTIAL_PLOTS)} plots)")
    g = matrix["gaps_summary"]
    print(f"  always_detected: {g['always_detected']}")
    print(f"  partial:         {g['partial']}")
    print(f"  never_detected:  {g['never_detected']}")
    if matrix["clarification_needed"]:
        print(f"  ⚠ clarification needed for: {matrix['clarification_needed']['missing_categories']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main_cli())
