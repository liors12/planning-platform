"""Gate: every engine check_key must be attached to a guideline row.

The extraction script binds each of the 7 engine check_keys to a docx row by
searching that row's raw text for a hard-coded Hebrew substring (CHECK_MAP).
The script has its own FATAL guard - but that only fires when a human runs the
extractor by hand. Nothing catches a broken binding in CI, so a guideline
rewording that erased a needle would ship silently: the row would still be
displayed, Ellen could still edit its value, and no check would ever run
against it.

This gate closes that hole. It asserts against the SHIPPED SEED - the artifact
the sidecar actually loads - not against the extractor's in-memory state.

Note on what this does and does not prove:
  * it proves each key is BOUND to a row carrying a threshold;
  * it does NOT prove the engine executes the check (see
    compliance_engine/guideline_checker.run_guideline_checks), nor that a
    measured value exists to compare against (see B-13 and the extracts
    coverage note in the backlog).
Three different claims; this gate covers only the first.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "app/sidecar/seed/guidelines_seed.json"

# The 7 keys the engine knows how to evaluate. Mirrors CHECK_MAP in
# scripts/extract_guidelines_docx.py and _WIRED_CHECK_KEYS in
# compliance_engine/guideline_checker.py.
EXPECTED_CHECK_KEYS = {
    "glass_railing_min_height_cm",
    "glazing_reflectivity_max_pct",
    "laundry_screen_width_m",
    "laundry_screen_height_m",
    "path_main_min_m",
    "path_secondary_min_m",
    "gas_tank_setback_min_m",
}


def _rows():
    return json.loads(SEED.read_text(encoding="utf-8"))["guidelines"]


def test_every_check_key_is_attached_to_a_row():
    attached = {r["check_key"]: r for r in _rows() if r.get("check_key")}
    missing = sorted(EXPECTED_CHECK_KEYS - set(attached))
    assert not missing, (
        "check_keys NOT attached to any guideline row: " + ", ".join(missing) +
        "\nThese checks cannot run. The usual cause is a guideline rewording "
        "that erased the CHECK_MAP needle in "
        "scripts/extract_guidelines_docx.py. Re-run the extraction and fix "
        "the needle, or key it structurally (backlog B-13)."
    )


def test_no_unexpected_check_keys():
    """A key the engine has no handler for would display a threshold Ellen
    can edit while nothing evaluates it."""
    found = {r["check_key"] for r in _rows() if r.get("check_key")}
    unexpected = sorted(found - EXPECTED_CHECK_KEYS)
    assert not unexpected, (
        "guideline rows carry check_keys the engine cannot evaluate: "
        + ", ".join(unexpected)
    )


def test_attached_rows_are_checkable_and_carry_a_threshold():
    """A bound key with no check_value yields 'unevaluable' at runtime, which
    looks like a working check and is not."""
    problems = []
    for r in _rows():
        key = r.get("check_key")
        if not key:
            continue
        if r.get("guideline_type") != "checkable":
            problems.append(f"{key}: guideline_type={r.get('guideline_type')!r}")
        if r.get("check_value") is None:
            problems.append(f"{key}: check_value is None")
    assert not problems, "bound rows unusable at runtime:\n" + "\n".join(problems)


def test_each_check_key_attached_exactly_once():
    counts: dict[str, int] = {}
    for r in _rows():
        if r.get("check_key"):
            counts[r["check_key"]] = counts.get(r["check_key"], 0) + 1
    dupes = {k: n for k, n in counts.items() if n > 1}
    assert not dupes, f"check_key attached to more than one row: {dupes}"
