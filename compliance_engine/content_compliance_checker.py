"""Content compliance checker.

Compares values extracted from the submission PDF against the project schema
(תב"ע limits). Pure-Python and deterministic given the cached extraction +
schema; no LLM calls in this module.

Result shape mirrors format rule results so the report renderer can consume
both arrays uniformly:
  {
    "rule_code": str,
    "ta_shetach_id": str | None,
    "verdict": "pass" | "pass_with_note" | "fail" | "fail_borderline"
               | "requires_review" | "unevaluable" | "not_applicable",
    "failure_mode": "NONE" | "OVERRUN" | "UNDERRUN" | "MISSING_DATA" | "ENGINE_ERROR",
    "confidence": "HIGH" | "MEDIUM" | "LOW",
    "evidence": {...},
    "notes_he": str,
    "remediation_he": str | None,
  }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .submission_data_extractor import (
    ExtractedSubmissionData,
    PlanWideData,
    TAShetachData,
)


VERDICT_PASS = "pass"
VERDICT_PASS_WITH_NOTE = "pass_with_note"
VERDICT_FAIL = "fail"
VERDICT_FAIL_BORDERLINE = "fail_borderline"
VERDICT_REQUIRES_REVIEW = "requires_review"
VERDICT_UNEVALUABLE = "unevaluable"
VERDICT_NOT_APPLICABLE = "not_applicable"
VERDICT_NOT_SUBMITTED = "not_submitted"

FAILURE_NONE = "NONE"
FAILURE_OVERRUN = "OVERRUN"
FAILURE_UNDERRUN = "UNDERRUN"
FAILURE_MISSING = "MISSING_DATA"
FAILURE_NOT_PROVIDED = "DOCUMENT_NOT_PROVIDED"
FAILURE_ENGINE = "ENGINE_ERROR"


def run_content_compliance(
    extracted: ExtractedSubmissionData,
    project_schema: dict,
    content_rules: list[dict],
    *,
    extracts: dict | None = None,
) -> list[dict]:
    """`extracts` is the hand-extracted JSON overlay (see submission_extracts.py).
    When present, its per-plot values are merged into `extracted.ta_shetach_data`
    before the rule dispatch — so the existing per-rule checks see real values
    instead of nulls."""
    extracts = extracts or {}
    if extracts:
        _overlay_extracts(extracted, extracts)

    project = project_schema.get("project", {})
    parcels_index = {p["parcel_id"]: p for p in project.get("parcels", []) if p.get("parcel_id")}
    plan_meta = project.get("meta", {})
    regulatory_mode = plan_meta.get("regulatory_mode")

    # Tag plots flagged NOT_IN_SUBMISSION so individual rule checks can emit a
    # specialized note rather than generic "לא הוגש". Status is a descriptive
    # string that *starts with* the enum-like token.
    not_in_submission: set[str] = set()
    for pid, plot in (extracts.get("plots") or {}).items():
        status = ((plot or {}).get("_status") or "").strip()
        if status.startswith("NOT_IN_SUBMISSION"):
            not_in_submission.add(pid)

    results: list[dict] = []
    for rule in content_rules:
        gate = rule.get("applies_when") or {}
        if gate.get("regulatory_mode") and gate["regulatory_mode"] != regulatory_mode:
            results.append(_na(rule, reason="rule applies only in a different regulatory mode"))
            continue

        scope = rule.get("scope", "per_ta_shetach")
        if scope == "per_ta_shetach":
            for ta in extracted.ta_shetach_data:
                parcel = parcels_index.get(ta.ta_shetach_id, {})
                if ta.ta_shetach_id in not_in_submission:
                    results.append(_not_in_submission_result(rule, ta.ta_shetach_id))
                else:
                    results.append(_dispatch_single(rule, ta, parcel, project, extracted))
        elif scope == "plan_wide":
            results.append(_dispatch_plan_wide(rule, extracted, project, extracts=extracts))
        else:
            results.append(_engine_error(rule, f"unknown scope: {scope}"))

    results.sort(key=lambda r: (r["rule_code"], r.get("ta_shetach_id") or ""))
    return results


def _overlay_extracts(extracted: ExtractedSubmissionData, extracts: dict) -> None:
    """Mutate `extracted.ta_shetach_data` and `extracted.plan_wide_data` with
    values from the hand-extracted JSON. Only fields present in the JSON are
    overwritten."""
    plots = (extracts.get("plots") or {})
    for ta in extracted.ta_shetach_data:
        plot = plots.get(ta.ta_shetach_id)
        if not plot:
            continue
        # Per-plot numeric values
        for src_key, dst_attr in [
            ("units_proposed", "unit_count"),
            ("primary_area_sqm", "area_main_m2"),
            ("service_area_above_sqm", "area_service_above_m2"),
            ("service_area_below_sqm", "area_service_below_m2"),
            ("permeable_surface_sqm", "permeable_surface_m2"),
        ]:
            if plot.get(src_key) is not None:
                setattr(ta, dst_attr, plot[src_key])
        if plot.get("height_m") is not None:
            ta.heights_m = [plot["height_m"]]
        parking = plot.get("parking") or {}
        if parking.get("private") is not None:
            ta.parking_private = parking["private"]
        if parking.get("motorcycle") is not None:
            ta.parking_motorcycle = parking["motorcycle"]
        if parking.get("accessible") is not None:
            ta.parking_accessible = parking["accessible"]
        if parking.get("bicycle") is not None:
            ta.parking_bike = parking["bicycle"]

    pw = extracts.get("plan_wide") or {}
    if pw.get("total_units_proposed") is not None:
        extracted.plan_wide_data.unit_count_total = pw["total_units_proposed"]


def _not_in_submission_result(rule: dict, parcel_id: str) -> dict:
    suffix = parcel_id.replace("plot_", "")
    note = (
        f'תא שטח {suffix} אינו מופיע בגרסה הנוכחית של תכנית העיצוב. '
        f'נדרש לפי תב"ע ויש להוסיפו בגרסה הבאה.'
    )
    return {
        "rule_code": rule["rule_code"],
        "rule_name_he": rule.get("rule_name_he", "") or "",
        "ta_shetach_id": parcel_id,
        "verdict": VERDICT_NOT_SUBMITTED,
        "failure_mode": FAILURE_NOT_PROVIDED,
        "confidence": "HIGH",
        "evidence": {
            "reason": f"plot {parcel_id} absent from submission",
            "required_artifact_he": rule.get("required_artifact_he", ""),
        },
        "notes_he": note,
        "remediation_he": rule.get("remediation_he", ""),
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _dispatch_single(rule: dict, ta: TAShetachData, parcel: dict, project: dict, extracted: ExtractedSubmissionData) -> dict:
    code = rule["rule_code"]
    if code == "CONTENT_UNIT_COUNT":
        return _check_unit_count(rule, ta, parcel, extracted)
    if code == "CONTENT_BUILDING_AREA_MAIN":
        return _check_numeric_le(
            rule, ta,
            submission_value=ta.area_main_m2,
            schema_value=_path(parcel, "building_rights.primary_sqm"),
            unit="m2",
        )
    if code == "CONTENT_BUILDING_AREA_SERVICE_ABOVE":
        return _check_numeric_le(
            rule, ta,
            submission_value=ta.area_service_above_m2,
            schema_value=_path(parcel, "building_rights.service_above_sqm"),
            unit="m2",
        )
    if code == "CONTENT_BUILDING_AREA_SERVICE_BELOW":
        return _check_numeric_le(
            rule, ta,
            submission_value=ta.area_service_below_m2,
            schema_value=_path(parcel, "building_rights.service_below_sqm"),
            unit="m2",
        )
    if code == "CONTENT_BUILDING_HEIGHT":
        return _check_height(rule, ta, parcel)
    if code == "CONTENT_SETBACKS":
        return _check_setbacks(rule, ta, parcel)
    if code == "CONTENT_PARKING_RATIO":
        return _check_parking(rule, ta, parcel)
    return _engine_error(rule, f"no handler for {code} (per_ta_shetach)")


def _dispatch_plan_wide(rule: dict, extracted: ExtractedSubmissionData, project: dict,
                         *, extracts: dict | None = None) -> dict:
    code = rule["rule_code"]
    if code == "CONTENT_APARTMENT_MIX_SMALL":
        return _check_apartment_mix(rule, extracted, project, extracts=extracts or {})
    if code == "CONTENT_PERMEABLE_SURFACES":
        return _check_permeable(rule, extracted, project)
    return _engine_error(rule, f"no handler for {code} (plan_wide)")


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def _check_unit_count(rule: dict, ta: TAShetachData, parcel: dict, extracted: ExtractedSubmissionData) -> dict:
    schema_max = _path(parcel, "units.max_units")
    if schema_max is None:
        # Non-residential parcels have no unit cap → not applicable
        return _na(rule, ta_shetach_id=ta.ta_shetach_id, reason="לא רלוונטי לסוג מגרש זה")
    if ta.unit_count is None:
        return _missing(rule, ta_shetach_id=ta.ta_shetach_id, reason="submission unit_count missing")
    overrun = ta.unit_count - schema_max
    if overrun <= 0:
        return _result(rule, VERDICT_PASS, ta.ta_shetach_id, evidence={
            "submission_value": ta.unit_count,
            "schema_value": schema_max,
            "comparison": "submission_le_schema",
            "source_pages": ta.extraction_pages.get("parcel_pages", []),
            "extraction_method": ta.extraction_methods.get("unit_count"),
        })
    return _result(rule, VERDICT_FAIL, ta.ta_shetach_id, failure_mode=FAILURE_OVERRUN, evidence={
        "submission_value": ta.unit_count,
        "schema_value": schema_max,
        "overrun": overrun,
        "comparison": "submission_le_schema",
        "source_pages": ta.extraction_pages.get("parcel_pages", []),
        "extraction_method": ta.extraction_methods.get("unit_count"),
    })


def _check_numeric_le(
    rule: dict,
    ta: TAShetachData,
    *,
    submission_value: float | int | None,
    schema_value: float | int | None,
    unit: str,
) -> dict:
    if schema_value is None:
        return _na(rule, ta_shetach_id=ta.ta_shetach_id, reason="לא רלוונטי לסוג מגרש זה")
    if submission_value is None:
        return _missing(rule, ta_shetach_id=ta.ta_shetach_id, reason="submission value missing")
    tol = rule.get("tolerance", {}) or {}
    borderline_pct = float(tol.get("fail_borderline_pct", 0))
    fail_pct = float(tol.get("fail_above_pct", borderline_pct))
    overrun = float(submission_value) - float(schema_value)
    overrun_pct = (overrun / float(schema_value) * 100.0) if schema_value else 0.0

    if overrun <= 0:
        verdict = rule.get("verdict_on_pass", VERDICT_PASS)
        failure_mode = FAILURE_NONE
    elif overrun_pct <= borderline_pct and overrun_pct <= fail_pct:
        verdict = rule.get("verdict_on_borderline", VERDICT_FAIL_BORDERLINE)
        failure_mode = FAILURE_OVERRUN
    else:
        verdict = rule.get("verdict_on_fail", VERDICT_FAIL)
        failure_mode = FAILURE_OVERRUN
    return _result(rule, verdict, ta.ta_shetach_id, failure_mode=failure_mode, evidence={
        "submission_value": submission_value,
        "schema_value": schema_value,
        "overrun_pct": round(overrun_pct, 3),
        "unit": unit,
        "extraction_method": ta.extraction_methods.get(rule["check_spec"]["submission_value"]),
    })


def _check_height(rule: dict, ta: TAShetachData, parcel: dict) -> dict:
    schema_max_m = _path(parcel, "height.max_height_m")
    if schema_max_m is None:
        floors = _path(parcel, "height.max_floors_above_entry")
        if floors is not None:
            factor = float(rule.get("check_spec", {}).get("floors_to_meters_factor", 3.0))
            schema_max_m = float(floors) * factor
    if schema_max_m is None:
        return _na(rule, ta_shetach_id=ta.ta_shetach_id, reason="לא רלוונטי לסוג מגרש זה")
    if not ta.heights_m:
        return _missing(rule, ta_shetach_id=ta.ta_shetach_id, reason="submission heights missing")
    submission_max = max(ta.heights_m)
    overrun_m = submission_max - float(schema_max_m)
    tol = rule.get("tolerance", {}) or {}
    border = float(tol.get("fail_borderline_above_m", 0.5))
    fail_above = float(tol.get("fail_above_m", border))

    # Note text is built around the actual relationship between submitted height
    # and the ceiling. v8h had a boilerplate "borderline" sentence on every pass,
    # which was wrong — drop it unless we're actually within `border` meters of the cap.
    base_note = 'גובה הבניין המוצע (מקסימום בין החזיתות/חתכים) לא יעלה על הגובה המותר בתב"ע.'
    note = base_note
    if overrun_m <= 0:
        verdict = rule.get("verdict_on_pass", VERDICT_PASS)
        failure_mode = FAILURE_NONE
        headroom = float(schema_max_m) - submission_max
        if headroom < border:
            note += f' חריגה של עד {border} מ\' מהתקרה ({schema_max_m} מ\') — נדרש תיקון גבולי.'
    elif overrun_m <= border and overrun_m <= fail_above:
        verdict = rule.get("verdict_on_borderline", VERDICT_FAIL_BORDERLINE)
        failure_mode = FAILURE_OVERRUN
        note += f' חריגה של {overrun_m:.2f} מ\' מהתקרה ({schema_max_m} מ\') — נדרש תיקון גבולי.'
    else:
        verdict = rule.get("verdict_on_fail", VERDICT_FAIL)
        failure_mode = FAILURE_OVERRUN
        note += f' חריגה של {overrun_m:.2f} מ\' מהתקרה ({schema_max_m} מ\') — נדרש תיקון.'

    return _result(rule, verdict, ta.ta_shetach_id, failure_mode=failure_mode, evidence={
        "submission_max_height_m": submission_max,
        "submission_heights_m": ta.heights_m,
        "schema_max_height_m": schema_max_m,
        "overrun_m": round(overrun_m, 3),
        "extraction_method": ta.extraction_methods.get("heights_m"),
    }, note_he_override=note)


def _check_setbacks(rule: dict, ta: TAShetachData, parcel: dict) -> dict:
    note = rule.get("always_note_he", "")
    return _result(
        rule,
        rule.get("always_verdict", VERDICT_REQUIRES_REVIEW),
        ta.ta_shetach_id,
        evidence={
            "submission_setback_front_m": ta.setback_front_m,
            "submission_setback_side_m": ta.setback_side_m,
            "submission_setback_rear_m": ta.setback_rear_m,
            "schema_setbacks": (parcel.get("setbacks") or {}),
            "reason": "DWG parsing not implemented",
        },
        note_he_override=note,
    )


PARKING_BASELINE_RATIO = 1.3  # baseline per the v8h handoff until the engineer pins the national standard


def _check_parking(rule: dict, ta: TAShetachData, parcel: dict) -> dict:
    """Compute parking ratio (private / units_proposed) and compare to the
    1.3 baseline derived from the prevailing national standard at permit time.

    If the project schema's parking_standard exposes a numeric `private_per_unit`,
    that value overrides the baseline.
    """
    standard = parcel.get("parking_standard") or {}
    private_per_unit = standard.get("private_per_unit")
    baseline_ratio = float(private_per_unit) if private_per_unit is not None else PARKING_BASELINE_RATIO

    if ta.unit_count in (None, 0) or ta.parking_private is None:
        return _missing(rule, ta_shetach_id=ta.ta_shetach_id,
                        reason="submission parking_private or unit_count missing")

    actual_ratio = ta.parking_private / float(ta.unit_count)
    pretty = (f'{ta.parking_private} חניות פרטיות, {ta.parking_motorcycle or 0} אופנועים, '
              f'{ta.parking_accessible or 0} נגישות, {ta.parking_bike or 0} אופניים')
    evidence = {
        "submission_value": pretty,
        "submission_parking_private": ta.parking_private,
        "submission_parking_motorcycle": ta.parking_motorcycle,
        "submission_parking_accessible": ta.parking_accessible,
        "submission_parking_bike": ta.parking_bike,
        "submission_unit_count": ta.unit_count,
        "actual_ratio": round(actual_ratio, 3),
        "baseline_ratio": baseline_ratio,
    }
    transparent_note = (
        f'יחס חניה פרטית מחושב: {actual_ratio:.2f} ({ta.parking_private}/{ta.unit_count} יח"ד). '
        f'מעל בסיס איכותי של {baseline_ratio} — תקין על בדיקה ראשונית. '
        'תקן חניה לאומי 3.1 (ינואר 2023, בתוקף בעת ההיתר) דורש 1.0-1.5 חניות פר יח"ד לפי גודל הדירה '
        '(עד 120 מ"ר: 1.0-1.3; 120-200 מ"ר: 1.5), בתוספת 20% חניות אורחים. '
        'אימות התאמה מדויקת לתקן דורש טבלת שטחים פר יחידת דיור — לא קיימת בהגשה זו.'
    )
    if actual_ratio >= baseline_ratio:
        return _result(rule, rule.get("verdict_on_pass", VERDICT_PASS), ta.ta_shetach_id,
                       evidence=evidence, note_he_override=transparent_note)
    deficit = round((baseline_ratio - actual_ratio) * ta.unit_count)
    fail_note = (
        f'יחס חניה פרטית מחושב: {actual_ratio:.2f} ({ta.parking_private}/{ta.unit_count} יח"ד). '
        f'מתחת לבסיס איכותי של {baseline_ratio}; חוסר משוער של {deficit} חניות. '
        'יש להוסיף או לעדכן בהגשה הבאה.'
    )
    return _result(rule, rule.get("verdict_on_fail", VERDICT_FAIL),
                   ta.ta_shetach_id, failure_mode=FAILURE_UNDERRUN,
                   evidence=dict(evidence, deficit_spaces=deficit),
                   note_he_override=fail_note)


def _check_apartment_mix(rule: dict, extracted: ExtractedSubmissionData, project: dict,
                          *, extracts: dict | None = None) -> dict:
    """Plan-wide small-apartment % check.

    Strict ≤75 m² count = sum of all plot unit_mix.count_56_to_75sqm (non-null).
    If any plot's bucket is null the strict count is a lower-bound only and we
    return 'requires_review' with a detailed Hebrew explanation including the
    architect's broader (≤81 m²) self-reported percentage.
    """
    # Support both legacy (min_pct, max_sqm) and split-tier (min_pct_le_55sqm
    # + min_pct_56_to_75sqm) schema shapes. תב"ע 407-1048248 uses the split form;
    # we sum the two tiers to get the effective ≤75 m² combined requirement.
    schema_min_pct = _path(project, "global_rules.small_apartments.min_pct")
    threshold_m2 = _path(project, "global_rules.small_apartments.max_sqm")
    if schema_min_pct is None:
        a = _path(project, "global_rules.small_apartments.min_pct_le_55sqm") or 0
        b = _path(project, "global_rules.small_apartments.min_pct_56_to_75sqm") or 0
        combined = (a or 0) + (b or 0)
        schema_min_pct = combined if combined > 0 else None
    if threshold_m2 is None:
        # 407-1048248 implies the upper band is 56-75 m², so threshold = 75
        threshold_m2 = 75 if schema_min_pct is not None else None
    if schema_min_pct is None or threshold_m2 is None:
        return _na(rule, reason="schema lacks small_apartments policy fields")

    extracts = extracts or {}
    pw = extracts.get("plan_wide") or {}
    total = pw.get("total_units_proposed")
    if total is None:
        return _missing(rule, reason="total_units_proposed not in extracts")

    plot_ids = ["plot_1", "plot_2", "plot_3", "plot_4", "plot_5"]
    strict_count = 0
    has_ambiguous = False
    ambiguous_plots: list[str] = []
    for pid in plot_ids:
        mix = ((extracts.get("plots") or {}).get(pid) or {}).get("unit_mix") or {}
        c_56_75 = mix.get("count_56_to_75sqm")
        c_le_55 = mix.get("count_le_55sqm") or 0
        if c_56_75 is None:
            has_ambiguous = True
            ambiguous_plots.append(pid.replace("plot_", ""))
        else:
            strict_count += int(c_56_75)
        # ≤55 is also "small"
        strict_count += int(c_le_55)

    architect_count = pw.get("small_apartments_count")
    architect_pct = pw.get("small_apartments_percent_calculated")

    if has_ambiguous:
        # Architect's self-reported value vs strict lower-bound
        strict_pct = strict_count / total * 100.0 if total else 0.0
        ambig_str = ", ".join(ambiguous_plots)
        body = (
            f'גבול תחתון: לפי הקריאה המחמירה של התב"ע (≤{int(threshold_m2)} מ"ר), מאומתות לכל הפחות '
            f'{strict_count} דירות קטנות = {strict_pct:.2f}% מסך {total} יח"ד.'
        )
        if architect_count is not None and architect_pct is not None:
            body += (
                f' האדריכל מצהיר על {architect_pct:.0f}% ({architect_count}/{total}) בהסתמך על הגדרה '
                f'רחבה יותר (≤81 מ"ר) הכוללת גם את שורות 2.5 חד\' / 3 קטנה.'
            )
        body += (
            f' ההפרש נובע מטווחי שטח חופפים בטבלת התמהיל (62-81 מ"ר) בתאי שטח {ambig_str}, '
            f'שלא ניתן לפצל ללא שטחי דירות פרטניים. יש לבקש מהאדריכל טבלת תמהיל מפורטת עם שטח '
            f'לכל יחידת דיור כדי לסגור את הספק. אם הדרישה היא {int(schema_min_pct)}% — עלולה ההגשה לא לעמוד בה.'
        )
        return _result(
            rule, VERDICT_REQUIRES_REVIEW, None,
            evidence={
                "submission_value": f'לפחות {strict_count} ({strict_pct:.2f}%) — לפי הגדרה מחמירה ≤{int(threshold_m2)} מ"ר',
                "schema_min_pct": schema_min_pct,
                "threshold_m2": threshold_m2,
                "strict_count_lower_bound": strict_count,
                "total_units": total,
                "ambiguous_plots": ambiguous_plots,
                "architect_count": architect_count,
                "architect_pct": architect_pct,
            },
            note_he_override=body,
        )

    # Clean case (no ambiguity)
    pct = strict_count / total * 100.0
    if pct >= float(schema_min_pct):
        verdict = rule.get("verdict_on_pass", VERDICT_PASS)
        failure_mode = FAILURE_NONE
    else:
        verdict = rule.get("verdict_on_fail", VERDICT_FAIL)
        failure_mode = FAILURE_UNDERRUN
    return _result(rule, verdict, None, failure_mode=failure_mode, evidence={
        "submission_value": f'{strict_count} ({pct:.1f}%)',
        "submission_small_apartment_pct": round(pct, 2),
        "schema_min_pct": schema_min_pct,
        "threshold_m2": threshold_m2,
        "small_units": strict_count,
        "total_units": total,
    })


def _bucket_max_m2(key: str) -> float | None:
    """Parse '60_m2' → 60. Returns None if key doesn't encode a size cap."""
    import re
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m2|sqm)", key)
    return float(m.group(1)) if m else None


def _check_permeable(rule: dict, extracted: ExtractedSubmissionData, project: dict) -> dict:
    # Try direct global rule first
    schema_min_pct = _path(project, "global_rules.permeable_surface_min_pct")
    # Fallback: compliance_rules[rule_code=PERMEABLE_SURFACES_MIN].threshold
    if schema_min_pct is None:
        for rule_def in (project.get("compliance_rules") or []):
            if rule_def.get("rule_code") == "PERMEABLE_SURFACES_MIN":
                schema_min_pct = rule_def.get("threshold")
                break
    if schema_min_pct is None:
        return _na(rule, reason="schema has no permeable_surface_min_pct (neither global_rules nor compliance_rules)")

    # Compute submission permeable % from per-parcel data
    total_plot_area = 0.0
    total_permeable = 0.0
    missing_pcts: list[str] = []
    for ta in extracted.ta_shetach_data:
        parcel = next((p for p in project.get("parcels", []) if p.get("parcel_id") == ta.ta_shetach_id), None)
        plot_area = float(parcel.get("plot_area_sqm") or 0) if parcel else 0
        if not plot_area:
            continue
        if ta.permeable_surface_m2 is None:
            missing_pcts.append(ta.ta_shetach_id)
            continue
        total_plot_area += plot_area
        total_permeable += float(ta.permeable_surface_m2)
    if total_plot_area == 0:
        return _missing(rule, reason=f"no parcels with extractable permeable_surface (missing for: {missing_pcts})")
    pct = (total_permeable / total_plot_area) * 100.0
    verdict = rule.get("verdict_on_pass", VERDICT_PASS) if pct >= float(schema_min_pct) else rule.get("verdict_on_fail", VERDICT_FAIL)
    failure_mode = FAILURE_NONE if verdict == VERDICT_PASS else FAILURE_UNDERRUN
    return _result(rule, verdict, None, failure_mode=failure_mode, evidence={
        "submission_permeable_pct": round(pct, 2),
        "schema_min_pct": schema_min_pct,
        "total_plot_area_sqm": total_plot_area,
        "total_permeable_sqm": total_permeable,
        "parcels_with_missing_data": missing_pcts,
    })


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

def _result(
    rule: dict,
    verdict: str,
    ta_shetach_id: str | None,
    *,
    failure_mode: str = FAILURE_NONE,
    confidence: str = "HIGH",
    evidence: dict | None = None,
    note_he_override: str | None = None,
) -> dict:
    return {
        "rule_code": rule["rule_code"],
        "rule_name_he": rule.get("rule_name_he", "") or "",
        "ta_shetach_id": ta_shetach_id,
        "verdict": verdict,
        "failure_mode": failure_mode,
        "confidence": confidence,
        "evidence": evidence or {},
        "notes_he": note_he_override or rule.get("description_he", ""),
        "remediation_he": rule.get("remediation_he", ""),
    }


def _na(rule: dict, *, ta_shetach_id: str | None = None, reason: str = "") -> dict:
    return _result(
        rule, VERDICT_NOT_APPLICABLE, ta_shetach_id,
        evidence={"reason": reason},
    )


def _missing(rule: dict, *, ta_shetach_id: str | None = None, reason: str = "") -> dict:
    """Document/artifact expected in submission but not present → not_submitted."""
    artifact = rule.get("required_artifact_he") or rule.get("description_he", "")
    note = f"{artifact} לא נכלל בגרסה הנוכחית של תכנית העיצוב. " + (rule.get("remediation_he", "") or "")
    return {
        "rule_code": rule["rule_code"],
        "rule_name_he": rule.get("rule_name_he", "") or "",
        "ta_shetach_id": ta_shetach_id,
        "verdict": VERDICT_NOT_SUBMITTED,
        "failure_mode": FAILURE_NOT_PROVIDED,
        "confidence": "HIGH",
        "evidence": {"reason": reason, "required_artifact_he": artifact},
        "notes_he": note.strip(),
        "remediation_he": rule.get("remediation_he", ""),
    }


def _engine_error(rule: dict, message: str) -> dict:
    return _result(
        rule, VERDICT_UNEVALUABLE, None,
        failure_mode=FAILURE_ENGINE,
        evidence={"error": message},
    )


def _path(obj: Any, dotted: str) -> Any:
    """Look up a dotted path inside a dict tree. Missing → None."""
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur
