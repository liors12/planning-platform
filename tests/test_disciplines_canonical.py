"""Addendum-8 drift gate: the discipline list has ONE source of truth.

The comments dropdown reads /disciplines, which serves
sidecar.disciplines.DISCIPLINES, which must be EXACTLY the canonical list
in compliance_engine/disciplines.py. A future edit in one place that
doesn't flow through the canonical module fails here.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app" / "sidecar"))

from compliance_engine.disciplines import (  # noqa: E402
    CANONICAL_DISCIPLINES, CANONICAL_KEYS, LEGACY_DISCIPLINE_ALIASES,
)
from sidecar.disciplines import DISCIPLINES, DISCIPLINE_KEYS  # noqa: E402


def test_sidecar_list_is_the_canonical_list():
    assert DISCIPLINES is CANONICAL_DISCIPLINES


def test_city_arch_is_gone_and_aliased():
    assert "city-arch" not in DISCIPLINE_KEYS
    assert all("אדריכלית העיר" != d["label"] for d in DISCIPLINES)
    assert LEGACY_DISCIPLINE_ALIASES["city-arch"] == "sec-3-7"
    assert LEGACY_DISCIPLINE_ALIASES["city-arch"] in CANONICAL_KEYS


def test_merged_discipline_present_once():
    labels = [d["label"] for d in DISCIPLINES]
    assert labels.count("אדריכלות וחזיתות") == 1
    assert len(labels) == len(set(labels)), "duplicate discipline labels"


def test_roads_dev_discipline_adjacent_to_traffic():
    # Addendum 11: "פיתוח וכבישים" (key roads-dev) exists, with the FINAL
    # corrected name (not the earlier "כבישים וגאומטריה" wording), placed
    # right after תנועה.
    labels = [d["label"] for d in DISCIPLINES]
    assert "פיתוח וכבישים" in labels
    assert "כבישים וגאומטריה" not in labels
    assert labels.index("פיתוח וכבישים") == labels.index("תנועה") + 1
    assert "roads-dev" in DISCIPLINE_KEYS
