"""CAD geometry compliance checks.

Runs four geometric checks against a DXFGeometry result and the project schema:

  1. CAD_SETBACK         — building footprint respects per-parcel setback lines
  2. CAD_BUILDING_COVERAGE — footprint area ≤ schema max_building_coverage_pct
  3. CAD_PUBLIC_SPACE    — public-space polygons don't overlap building footprint
  4. CAD_PARKING_COUNT   — count of detected parking stalls ≥ schema min_parking_count

Schema fields driving checks are all optional (null → not_applicable). This
lets the checker run gracefully on schemas that predate the geometric fields.

The result list uses the same dict shape as content_compliance_checker.py so
the report renderer can consume both arrays uniformly.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Verdict strings mirror content_compliance_checker.py
_PASS = "pass"
_FAIL = "fail"
_REVIEW = "requires_review"
_NA = "not_applicable"
_UNEVALUABLE = "unevaluable"

_NONE = "NONE"
_OVERRUN = "OVERRUN"
_UNDERRUN = "UNDERRUN"
_MISSING = "MISSING_DATA"


def _result(
    rule_code: str,
    verdict: str,
    *,
    failure_mode: str = _NONE,
    confidence: str = "HIGH",
    evidence: dict | None = None,
    notes_he: str = "",
    remediation_he: str = "",
    ta_shetach_id: str | None = None,
) -> dict:
    return {
        "rule_code": rule_code,
        "rule_name_he": _RULE_NAMES.get(rule_code, rule_code),
        "ta_shetach_id": ta_shetach_id,
        "verdict": verdict,
        "failure_mode": failure_mode,
        "confidence": confidence,
        "evidence": evidence or {},
        "notes_he": notes_he,
        "remediation_he": remediation_he,
    }


_RULE_NAMES: dict[str, str] = {
    "CAD_SETBACK":           "קווי בניין — מרחק מגבול המגרש",
    "CAD_BUILDING_COVERAGE": "תכסית בנייה",
    "CAD_PUBLIC_SPACE":      'חפיפה עם שטח ציבורי פתוח (שצ"פ)',
    "CAD_PARKING_COUNT":     "ספירת מקומות חנייה",
}


def _path(obj: Any, dotted: str) -> Any:
    """Traverse a dot-separated path through nested dicts/lists."""
    for key in dotted.split("."):
        if obj is None:
            return None
        if isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
    return obj


def _no_cad(rule_code: str) -> dict:
    return _result(
        rule_code, _REVIEW,
        failure_mode=_MISSING,
        confidence="HIGH",
        notes_he="קובץ CAD לא הועלה — הבדיקה הגיאומטרית לא הופעלה.",
        remediation_he='העלי קובץ DXF בלשונית "הגשות" והפעילי מחדש את הבדיקה.',
    )


def _no_mapping(rule_code: str) -> dict:
    return _result(
        rule_code, _REVIEW,
        failure_mode=_MISSING,
        confidence="HIGH",
        notes_he="מיפוי שכבות CAD לא הושלם — נדרש אישור שכבת גבול המגרש לפחות.",
        remediation_he='עברי ללשונית "שכבות CAD" ואשרי את מיפוי השכבות.',
    )


# ─────────────────────────────────────────────────────────────────────────────
# Check 1: Setbacks
# ─────────────────────────────────────────────────────────────────────────────

def check_setback(
    geometry,          # DXFGeometry | None
    project_schema: dict,
) -> dict:
    """Compare building footprint distance from plot boundary to required setbacks.

    Schema lookup (per first parcel): setbacks.front_min_m, setbacks.side_min_m,
    setbacks.rear_min_m. All null → not_applicable.
    """
    rule_code = "CAD_SETBACK"

    if geometry is None:
        return _no_cad(rule_code)
    if not geometry.has_plot_boundary or not geometry.has_building_footprint:
        return _no_mapping(rule_code)

    parcels = _path(project_schema, "project.parcels") or []
    # Aggregate the most restrictive (smallest) non-null setback across all parcels
    front_req: float | None = None
    side_req: float | None = None
    rear_req: float | None = None
    for parcel in parcels:
        sb = parcel.get("setbacks") or {}
        for attr, req_holder in [
            ("front_min_m", "front"),
            ("side_min_m", "side"),
            ("rear_min_m", "rear"),
        ]:
            val = sb.get(attr)
            if val is not None:
                if req_holder == "front" and (front_req is None or val < front_req):
                    front_req = float(val)
                elif req_holder == "side" and (side_req is None or val < side_req):
                    side_req = float(val)
                elif req_holder == "rear" and (rear_req is None or val < rear_req):
                    rear_req = float(val)

    if front_req is None and side_req is None and rear_req is None:
        return _result(
            rule_code, _NA,
            notes_he="קווי בניין לא הוגדרו כמספרים בסכמת הפרויקט — בדיקת קו הבניין אינה ישימה.",
        )

    # Use setback lines from the DXF if available, otherwise use the
    # overall minimum distance from footprint to plot boundary.
    try:
        bp = geometry.building_footprint
        pb = geometry.plot_boundary.boundary

        results_detail: list[str] = []
        violations: list[str] = []

        for label, setback_lines, req, side_he in [
            ("front", geometry.setback_front_lines, front_req, "קדמי"),
            ("side",  geometry.setback_side_lines,  side_req,  "צדדי"),
            ("rear",  geometry.setback_rear_lines,  rear_req,  "אחורי"),
        ]:
            if req is None:
                continue
            if setback_lines:
                # Measure distance from building footprint to the explicit setback line
                from shapely.ops import unary_union
                line = unary_union(setback_lines)
                dist = float(bp.distance(line))
            else:
                # Fallback: overall distance from building to plot boundary
                dist = float(bp.distance(pb))

            dist_r = round(dist, 2)
            results_detail.append(f"קו בניין {side_he}: נמדד {dist_r} מ' (נדרש ≥{req} מ')")
            if dist < req - 0.05:  # 5cm tolerance
                violations.append(f"{side_he}: {dist_r} מ' < {req} מ' נדרש")

        if violations:
            return _result(
                rule_code, _FAIL,
                failure_mode=_UNDERRUN,
                confidence="MEDIUM",
                evidence={"violations": violations, "details": results_detail},
                notes_he=f"קווי הבניין אינם עומדים בדרישות: {'; '.join(violations)}.",
                remediation_he="יש לבחון את מיקום הבניין ביחס לגבולות המגרש.",
            )
        return _result(
            rule_code, _PASS,
            confidence="MEDIUM",
            evidence={"details": results_detail},
            notes_he=f"קווי הבניין עומדים בדרישות. {'; '.join(results_detail)}.",
        )
    except Exception as exc:
        log.warning("check_setback error: %s", exc)
        return _result(
            rule_code, _UNEVALUABLE,
            evidence={"error": str(exc)},
            notes_he="שגיאה בחישוב קווי הבניין — נדרשת בדיקה ידנית.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Check 2: Building coverage
# ─────────────────────────────────────────────────────────────────────────────

def check_building_coverage(
    geometry,
    project_schema: dict,
) -> dict:
    """Footprint area / plot area ≤ max_building_coverage_pct from schema.

    Schema lookup: first parcel's building_rights.max_coverage_pct (optional,
    null → not_applicable).
    """
    rule_code = "CAD_BUILDING_COVERAGE"

    if geometry is None:
        return _no_cad(rule_code)
    if not geometry.has_plot_boundary or not geometry.has_building_footprint:
        return _no_mapping(rule_code)

    # Look for max_coverage_pct across parcels
    parcels = _path(project_schema, "project.parcels") or []
    max_pct: float | None = None
    for p in parcels:
        val = _path(p, "building_rights.max_coverage_pct")
        if val is not None:
            max_pct = float(val)
            break

    footprint_sqm = geometry.building_footprint_area_sqm
    plot_sqm = geometry.plot_boundary_area_sqm

    if max_pct is None:
        return _result(
            rule_code, _NA,
            evidence={"footprint_sqm": footprint_sqm, "plot_sqm": plot_sqm},
            notes_he="אחוז תכסית מרבי לא הוגדר בסכמת הפרויקט — הבדיקה אינה ישימה.",
        )

    if plot_sqm is None or plot_sqm <= 0:
        return _result(rule_code, _REVIEW, failure_mode=_MISSING,
                       notes_he="לא ניתן לחשב שטח מגרש מגבול המגרש שהוגדר.")

    actual_pct = footprint_sqm / plot_sqm * 100
    evidence = {
        "footprint_sqm": round(footprint_sqm, 1),
        "plot_sqm": round(plot_sqm, 1),
        "actual_coverage_pct": round(actual_pct, 1),
        "max_coverage_pct": max_pct,
    }

    if actual_pct <= max_pct + 0.5:  # 0.5% tolerance
        return _result(
            rule_code, _PASS,
            confidence="MEDIUM",
            evidence=evidence,
            notes_he=f"תכסית: {actual_pct:.1f}% (מותר: ≤{max_pct}%).",
        )
    return _result(
        rule_code, _FAIL,
        failure_mode=_OVERRUN,
        confidence="MEDIUM",
        evidence=evidence,
        notes_he=f"תכסית: {actual_pct:.1f}% — חורגת מהמותר של {max_pct}%.",
        remediation_he="יש לצמצם את תכסית הבנייה להתאמה לדרישות התב\"ע.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Check 3: Public space overlap
# ─────────────────────────────────────────────────────────────────────────────

def check_public_space_overlap(
    geometry,
    project_schema: dict,
) -> dict:
    """Verify public-space polygons don't overlap with the building footprint."""
    rule_code = "CAD_PUBLIC_SPACE"

    if geometry is None:
        return _no_cad(rule_code)

    if not geometry.public_space_polygons:
        return _result(
            rule_code, _NA,
            notes_he="לא זוהו שכבות שטח ציבורי פתוח בקובץ ה-DXF — הבדיקה אינה ישימה.",
        )
    if not geometry.has_building_footprint:
        return _no_mapping(rule_code)

    try:
        from shapely.ops import unary_union

        public_union = unary_union(geometry.public_space_polygons)
        building = geometry.building_footprint

        if not public_union.intersects(building):
            return _result(
                rule_code, _PASS,
                confidence="MEDIUM",
                evidence={"public_space_sqm": round(float(public_union.area), 1)},
                notes_he="הבניין אינו חופף עם שטחי ציבור פתוח.",
            )

        overlap_area = float(public_union.intersection(building).area)
        return _result(
            rule_code, _FAIL,
            failure_mode=_OVERRUN,
            confidence="MEDIUM",
            evidence={
                "overlap_sqm": round(overlap_area, 1),
                "public_space_sqm": round(float(public_union.area), 1),
            },
            notes_he=f"הבניין חופף עם שטח ציבורי פתוח ב-{overlap_area:.1f} מ\"ר.",
            remediation_he='יש לבחון את גבולות הבנייה ביחס לשטחי שצ"פ.',
        )
    except Exception as exc:
        log.warning("check_public_space_overlap error: %s", exc)
        return _result(
            rule_code, _UNEVALUABLE,
            evidence={"error": str(exc)},
            notes_he="שגיאה בבדיקת חפיפה עם שצ\"פ — נדרשת בדיקה ידנית.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Check 4: Parking count
# ─────────────────────────────────────────────────────────────────────────────

def check_parking_count(
    geometry,
    project_schema: dict,
) -> dict:
    """Count detected parking-stall polygons vs schema min_parking_count.

    Schema lookup: first parcel's parking_standard.min_total_spaces (optional).
    """
    rule_code = "CAD_PARKING_COUNT"

    if geometry is None:
        return _no_cad(rule_code)

    if not geometry.parking_polygons:
        return _result(
            rule_code, _NA,
            notes_he="לא זוהו שכבות חנייה בקובץ ה-DXF — הבדיקה אינה ישימה.",
        )

    parcels = _path(project_schema, "project.parcels") or []
    min_count: int | None = None
    for p in parcels:
        val = _path(p, "parking_standard.min_total_spaces")
        if val is not None:
            try:
                min_count = int(val)
                break
            except (TypeError, ValueError):
                pass

    detected = len(geometry.parking_polygons)

    if min_count is None:
        return _result(
            rule_code, _NA,
            evidence={"detected_parking_polygons": detected},
            notes_he=f"מינימום מקומות חנייה לא הוגדר בסכמה — זוהו {detected} פוליגוני חנייה (בדיקה אינה ישימה).",
        )

    evidence = {"detected_parking_polygons": detected, "min_required": min_count}

    if detected >= min_count:
        return _result(
            rule_code, _PASS,
            confidence="MEDIUM",
            evidence=evidence,
            notes_he=f"זוהו {detected} מקומות חנייה (נדרש לפחות {min_count}).",
        )
    return _result(
        rule_code, _FAIL,
        failure_mode=_UNDERRUN,
        confidence="MEDIUM",
        evidence=evidence,
        notes_he=f"זוהו {detected} מקומות חנייה — מתחת לנדרש ({min_count}).",
        remediation_he="יש לוודא שמקומות החנייה מצוינים בשכבה הנכונה ושמספרם עומד בדרישה.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_cad_compliance(
    geometry,            # DXFGeometry | None
    project_schema: dict,
) -> list[dict]:
    """Run all four CAD compliance checks and return a list of finding dicts."""
    return [
        check_setback(geometry, project_schema),
        check_building_coverage(geometry, project_schema),
        check_public_space_overlap(geometry, project_schema),
        check_parking_count(geometry, project_schema),
    ]
