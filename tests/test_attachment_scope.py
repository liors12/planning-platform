"""Gate: an attachment review runs only checks that belong to its type (B-23).

Ellen ran a traffic appendix (sheet 12753.1/3) and got 44 checks, 31 of them
"לא הוגש" - fonts, page size, Hebrew alignment, DXF/XREF rules, the hydrology
annex, green building. Cause: the mapping marked the whole כללי section
'חלק א - פורמט קבצים' (25 rows) as always-on for every attachment type, and
matched it by its HEBREW TITLE. Those rows are the booklet's file rules and
required-files list, not properties of one sheet.

This file runs the REAL selection (attachments.select_guidelines) over the
REAL seed and the REAL mapping - no copies.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "app" / "sidecar")]

from sidecar.attachments import select_guidelines  # noqa: E402

SEED = ROOT / "app/sidecar/seed/guidelines_seed.json"
MAPPING = ROOT / "app/sidecar/seed/attachment_check_mapping.json"
HEBREW = re.compile(r"[֐-׿]")


def _guidelines():
    rows = json.loads(SEED.read_text(encoding="utf-8"))["guidelines"]
    return [SimpleNamespace(id=i, **{k: r.get(k) for k in (
        "title", "discipline_key", "section_key", "sort_order", "check_key")})
        for i, r in enumerate(rows, 1)]


def _mapping():
    return json.loads(MAPPING.read_text(encoding="utf-8"))


def _types():
    return list(_mapping()["types"])


def test_traffic_attachment_runs_only_traffic_checks():
    """The red-green spec: one non-traffic row in a traffic review fails it."""
    m = _mapping()
    extra_keys = set(m["types"]["sec-3-4"].get("extra_guideline_check_keys", []))
    picked = select_guidelines(m, "sec-3-4", _guidelines())
    foreign = [f"{g.discipline_key}/{g.section_key}#{g.sort_order} {g.title}"
               for g in picked
               if g.discipline_key != "sec-3-4" and g.check_key not in extra_keys]
    assert not foreign, ("non-traffic checks in a traffic review:\n  "
                         + "\n  ".join(foreign))
    assert picked, "a traffic review that runs no guideline is not a fix"


def test_ground_floor_function_diagram_is_not_a_traffic_check():
    picked = select_guidelines(_mapping(), "sec-3-4", _guidelines())
    assert ("part_b", 42) not in {(g.section_key, g.sort_order) for g in picked}


def test_function_diagram_runs_on_architecture_instead():
    """Taken out of traffic, it must land somewhere - not vanish."""
    picked = select_guidelines(_mapping(), "sec-3-7", _guidelines())
    assert ("part_b", 42) in {(g.section_key, g.sort_order) for g in picked}


@pytest.mark.parametrize("dtype", _types())
def test_no_general_row_rides_along_on_another_type(dtype):
    if dtype == "general":
        pytest.skip("a כללי attachment runs its own rows")
    m = _mapping()
    extra_keys = set(m["types"][dtype].get("extra_guideline_check_keys", []))
    leaked = [g.title for g in select_guidelines(m, dtype, _guidelines())
              if g.discipline_key == "general" and g.check_key not in extra_keys]
    assert not leaked, f"{dtype}: כללי rows leaked in: {leaked}"


@pytest.mark.parametrize("dtype", _types())
def test_submission_only_sections_never_reach_an_attachment(dtype):
    m = _mapping()
    blocked = set(m["attachment_scope"]["submission_only_sections"])
    hit = [f"{g.section_key}#{g.sort_order} {g.title}"
           for g in select_guidelines(m, dtype, _guidelines())
           if g.section_key in blocked]
    assert not hit, f"{dtype}: booklet-only rows on an attachment: {hit}"


def test_scope_is_keyed_structurally_not_by_hebrew_title():
    """The pattern behind B-13/B-16: a Hebrew display string used as a key
    breaks silently the day the text is reworded."""
    m = _mapping()
    assert "general_subgroups" not in m, "the Hebrew-title subgroup keys are back"
    keys = list(m["attachment_scope"]["submission_only_sections"])
    for t in m["types"].values():
        keys += t.get("exclude_sections", [])
        keys += [e["section_key"] for e in t.get("exclude_guidelines", [])
                 + t.get("include_guidelines", [])]
    hebrew = [k for k in keys if HEBREW.search(k)]
    assert not hebrew, f"scope keyed on Hebrew text: {hebrew}"


def test_every_exclusion_points_at_a_real_row_of_that_type():
    """A stale (section_key, sort_order) excludes nothing and fails silently."""
    rows = {(g.section_key, g.sort_order): g for g in _guidelines()}
    stale = []
    for dtype, t in _mapping()["types"].items():
        for e in t.get("include_guidelines", []):
            if (e["section_key"], e["sort_order"]) not in rows:
                stale.append(f"{dtype} include: {e['section_key']}#{e['sort_order']}")
        for e in t.get("exclude_guidelines", []):
            g = rows.get((e["section_key"], e["sort_order"]))
            if g is None or g.discipline_key != dtype:
                stale.append(f"{dtype}: {e['section_key']}#{e['sort_order']}")
    assert not stale, f"exclusions that match no row of their type: {stale}"
