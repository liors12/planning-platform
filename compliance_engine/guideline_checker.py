"""Checks driven by the editable GLOBAL municipal guidelines (הנחיות).

The sidecar reads the active guideline set from platform.db at audit time and
passes it into `run_full_audit(guidelines=...)`; this module turns that set
into findings. The engine itself stays DB-free (it can't open the platform's
SQLCipher DB and must stay runnable standalone), so the values arrive as plain
dicts — but they originate from the DB on every run, never from hardcoded
constants.

Slice-first: only `glass_railing_min_height_cm` is wired end-to-end.
TODO (deliberately unwired in this PR — next slices):
  * glazing_reflectivity_max_pct
  * laundry_screen_width_m + laundry_screen_height_m
  * path_main_min_m + path_secondary_min_m
  * gas_tank_setback_min_m

Manual-type guidelines produce no pass/fail — they are surfaced as a
"לבדיקה ידנית" list so the report is honest about what is not auto-checked.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# check_keys with an implemented handler. Everything else checkable is
# reported as awaiting automation (no fake verdicts).
_WIRED_CHECK_KEYS = {"glass_railing_min_height_cm"}


def run_guideline_checks(
    guidelines: list[dict],
    *,
    extracts: dict | None = None,
) -> dict:
    """Evaluate the active guideline set against the submission.

    Args:
        guidelines: active global guideline rows (dicts with id, title,
            guideline_type, check_key, check_value, unit, version, ...).
        extracts: the hand-extracted overlay (extracts.json) — the current
            source for measured submission values.

    Returns:
        {
          "checks":   [finding dicts — content-result shape],
          "manual":   [{title, discipline, version} for manual guidelines],
          "snapshot": [{guideline_id, version, check_key, title} for ALL
                       active guidelines this run enforced/surfaced],
        }
    """
    extracts = extracts or {}
    checks: list[dict] = []
    manual: list[dict] = []
    snapshot: list[dict] = []

    for g in guidelines:
        snapshot.append({
            "guideline_id": g["id"],
            "version": g["version"],
            "check_key": g.get("check_key"),
            "title": g["title"],
        })
        if g["guideline_type"] == "manual":
            manual.append({
                "title": g["title"],
                "discipline": g.get("discipline", ""),
                "version": g["version"],
            })
            continue
        key = g.get("check_key")
        if key == "glass_railing_min_height_cm":
            checks.append(_check_glass_railing(g, extracts))
        elif key not in _WIRED_CHECK_KEYS:
            # Checkable but not yet automated — surface honestly.
            checks.append(_awaiting_automation(g))

    return {"checks": checks, "manual": manual, "snapshot": snapshot}


def _citation(g: dict) -> str:
    return f'הנחיה: "{g["title"]}" (גרסה {g["version"]})'


def _check_glass_railing(g: dict, extracts: dict) -> dict:
    """Minimum glass-railing height. Threshold comes from the guideline row
    (Ellen-editable), never hardcoded. Measured value is read from the
    extracts overlay when available; absent → requires_review with the
    current threshold cited so the reviewer knows what to measure against."""
    threshold = g.get("check_value")
    unit = g.get("unit") or ""
    plan_wide = extracts.get("plan_wide") or {}
    measured = plan_wide.get("glass_railing_height_cm")

    base = {
        "rule_code": "GUIDELINE_GLASS_RAILING_HEIGHT",
        "rule_name_he": g["title"],
        "guideline_id": g["id"],
        "guideline_version": g["version"],
        "ta_shetach_id": None,
    }
    threshold_str = f"{threshold:g}" if threshold is not None else "—"

    if threshold is None:
        return {
            **base,
            "verdict": "unevaluable",
            "failure_mode": "MISSING_DATA",
            "confidence": "HIGH",
            "evidence": {"reason": "guideline has no check_value"},
            "notes_he": f'לא הוגדר ערך סף להנחיה. {_citation(g)}',
            "remediation_he": None,
        }
    if measured is None:
        return {
            **base,
            "verdict": "requires_review",
            "failure_mode": "MISSING_DATA",
            "confidence": "HIGH",
            "evidence": {
                "threshold": threshold,
                "unit": unit,
                "measured": None,
                "comparison": "measured_ge_threshold",
            },
            "notes_he": (
                f'נדרשת בדיקה: גובה גדר הזכוכית לא אותר בהגשה. '
                f'הסף הנדרש הוא {threshold_str} {unit} לפחות. {_citation(g)}'
            ),
            "remediation_he": (
                f'יש לוודא שגובה גדר הזכוכית בכל המרפסות והגגות הוא '
                f'{threshold_str} {unit} לפחות, ולסמן זאת בתכנית.'
            ),
        }

    passed = measured >= threshold
    measured_str = f"{measured:g}"
    if passed:
        notes = (
            f'גובה גדר הזכוכית בהגשה ({measured_str} {unit}) עומד בסף '
            f'הנדרש ({threshold_str} {unit} לפחות). {_citation(g)}'
        )
    else:
        notes = (
            f'גובה גדר הזכוכית בהגשה ({measured_str} {unit}) נמוך מהסף '
            f'הנדרש ({threshold_str} {unit} לפחות). {_citation(g)}'
        )
    return {
        **base,
        "verdict": "pass" if passed else "fail",
        "failure_mode": "NONE" if passed else "UNDERRUN",
        "confidence": "HIGH",
        "evidence": {
            "threshold": threshold,
            "unit": unit,
            "measured": measured,
            "comparison": "measured_ge_threshold",
        },
        "notes_he": notes,
        "remediation_he": None if passed else (
            f'יש להגביה את גדר הזכוכית ל-{threshold_str} {unit} לפחות '
            f'בגרסה הבאה של תכנית העיצוב.'
        ),
    }


def _awaiting_automation(g: dict) -> dict:
    threshold = g.get("check_value")
    threshold_str = f"{threshold:g}" if threshold is not None else "—"
    unit = g.get("unit") or ""
    return {
        "rule_code": f"GUIDELINE_{(g.get('check_key') or 'UNKNOWN').upper()}",
        "rule_name_he": g["title"],
        "guideline_id": g["id"],
        "guideline_version": g["version"],
        "ta_shetach_id": None,
        "verdict": "requires_review",
        "failure_mode": "MISSING_DATA",
        "confidence": "HIGH",
        "evidence": {"threshold": threshold, "unit": unit,
                     "reason": "automated check not yet implemented"},
        "notes_he": (
            f'בדיקה אוטומטית להנחיה זו תתווסף בעדכון הבא; בינתיים נדרשת '
            f'בדיקה ידנית מול הסף {threshold_str} {unit}. {_citation(g)}'
        ),
        "remediation_he": None,
    }
