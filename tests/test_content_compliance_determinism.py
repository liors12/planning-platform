"""
Determinism and verdict-logic tests for content compliance.

Three groups:
  1. Extraction cache: same PDF -> byte-identical cache file.
  2. Schema-driven verdict logic: synthetic above/below/at-limit inputs land
     on pass / fail_borderline / fail per spec.
  3. Manual override flow: editing a cached value flips the verdict on re-run.

The existing 4 format determinism tests are not touched.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

import fitz
import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from compliance_engine.content_compliance_checker import (  # noqa: E402
    run_content_compliance,
    VERDICT_PASS, VERDICT_FAIL, VERDICT_FAIL_BORDERLINE, VERDICT_REQUIRES_REVIEW,
    VERDICT_UNEVALUABLE, VERDICT_NOT_APPLICABLE,
)
from compliance_engine.submission_data_extractor import (  # noqa: E402
    ExtractedSubmissionData, PlanWideData, TAShetachData, extract,
)
from compliance_engine.extraction_cache import (  # noqa: E402
    apply_override, pdf_sha256,
)


RULES_PATH = PROJECT_ROOT / "content_rules.json"


@pytest.fixture(scope="session")
def content_rules() -> list[dict]:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]


@pytest.fixture(scope="session")
def split_schema() -> dict:
    """Synthetic split-mode project schema with two residential parcels."""
    return {
        "project": {
            "meta": {
                "plan_number": "TEST-000",
                "regulatory_mode": "split",
                "total_units": 80,
            },
            "parcels": [
                {
                    "parcel_id": "plot_A",
                    "plot_area_sqm": 1000,
                    "building_rights": {
                        "primary_sqm": 5000,
                        "service_above_sqm": 2000,
                        "service_below_sqm": 3000,
                    },
                    "units": {"max_units": 50, "small_apartment_min_pct": 20, "small_apartment_max_sqm": 80},
                    "height": {"max_height_m": 30.0, "max_floors_above_entry": 10},
                    "setbacks": {"front_min_m": None, "side_min_m": None, "rear_min_m": None},
                    "parking_standard": {
                        "status": "deferred_to_national_standard",
                        "source_quote": "test",
                        "source_page": 17,
                    },
                },
                {
                    "parcel_id": "plot_B",
                    "plot_area_sqm": 500,
                    "building_rights": {
                        "primary_sqm": 2500,
                        "service_above_sqm": 1000,
                        "service_below_sqm": 1500,
                    },
                    "units": {"max_units": 30},
                    "height": {"max_height_m": 20.0},
                    "setbacks": {},
                    "parking_standard": {
                        "status": "deferred_to_national_standard",
                        "source_quote": "test",
                        "source_page": 17,
                    },
                },
            ],
            "global_rules": {
                "small_apartments": {"min_pct": 20, "max_sqm": 80},
            },
            "compliance_rules": [
                {"rule_code": "PERMEABLE_SURFACES_MIN", "threshold": 15},
            ],
        }
    }


def _extracted(
    plot_A: dict | None = None,
    plot_B: dict | None = None,
    plan_wide_kwargs: dict | None = None,
) -> ExtractedSubmissionData:
    ta_a = TAShetachData(ta_shetach_id="plot_A", **(plot_A or {}))
    ta_b = TAShetachData(ta_shetach_id="plot_B", **(plot_B or {}))
    pw = PlanWideData(**(plan_wide_kwargs or {}))
    return ExtractedSubmissionData(
        plan_metadata={"plan_number": "TEST-000"},
        ta_shetach_data=[ta_a, ta_b],
        plan_wide_data=pw,
        extraction_quality={"llm_available": False, "llm_used": False, "fields_extracted_count": 0, "page_count": 0, "missing_api_key": True},
        pdf_sha256="0" * 64,
    )


def _by_code_and_parcel(results: list[dict], code: str, parcel: str | None = None) -> dict | None:
    for r in results:
        if r["rule_code"] == code and r.get("ta_shetach_id") == parcel:
            return r
    return None


# -------------------------------------------------------------------------
# 1. Pure verdict-logic tests (schema-driven)
# -------------------------------------------------------------------------

def test_unit_count_pass_at_limit(split_schema, content_rules):
    ex = _extracted(plot_A={"unit_count": 50}, plot_B={"unit_count": 30})
    results = run_content_compliance(ex, split_schema, content_rules)
    assert _by_code_and_parcel(results, "CONTENT_UNIT_COUNT", "plot_A")["verdict"] == VERDICT_PASS
    assert _by_code_and_parcel(results, "CONTENT_UNIT_COUNT", "plot_B")["verdict"] == VERDICT_PASS


def test_unit_count_fail_over(split_schema, content_rules):
    ex = _extracted(plot_A={"unit_count": 60}, plot_B={"unit_count": 30})
    r = _by_code_and_parcel(run_content_compliance(ex, split_schema, content_rules), "CONTENT_UNIT_COUNT", "plot_A")
    assert r["verdict"] == VERDICT_FAIL
    assert r["evidence"]["overrun"] == 10


def test_unit_count_missing_data(split_schema, content_rules):
    ex = _extracted(plot_A={}, plot_B={"unit_count": 30})
    r = _by_code_and_parcel(run_content_compliance(ex, split_schema, content_rules), "CONTENT_UNIT_COUNT", "plot_A")
    assert r["verdict"] == VERDICT_UNEVALUABLE
    assert r["failure_mode"] == "MISSING_DATA"


def test_area_main_borderline(split_schema, content_rules):
    # 2% over -> fail_borderline; >2% -> fail
    ex = _extracted(plot_A={"area_main_m2": 5100})  # +2% on 5000
    r = _by_code_and_parcel(run_content_compliance(ex, split_schema, content_rules), "CONTENT_BUILDING_AREA_MAIN", "plot_A")
    assert r["verdict"] == VERDICT_FAIL_BORDERLINE


def test_area_main_hard_fail(split_schema, content_rules):
    ex = _extracted(plot_A={"area_main_m2": 5500})  # +10%
    r = _by_code_and_parcel(run_content_compliance(ex, split_schema, content_rules), "CONTENT_BUILDING_AREA_MAIN", "plot_A")
    assert r["verdict"] == VERDICT_FAIL


def test_height_at_borderline(split_schema, content_rules):
    ex = _extracted(plot_A={"heights_m": [30.4]})  # +0.4m
    r = _by_code_and_parcel(run_content_compliance(ex, split_schema, content_rules), "CONTENT_BUILDING_HEIGHT", "plot_A")
    assert r["verdict"] == VERDICT_FAIL_BORDERLINE


def test_height_real_fail(split_schema, content_rules):
    ex = _extracted(plot_A={"heights_m": [31.5]})
    r = _by_code_and_parcel(run_content_compliance(ex, split_schema, content_rules), "CONTENT_BUILDING_HEIGHT", "plot_A")
    assert r["verdict"] == VERDICT_FAIL


def test_setbacks_always_requires_review(split_schema, content_rules):
    ex = _extracted(plot_A={"setback_front_m": 3.0}, plot_B={"setback_front_m": 3.0})
    for parcel in ("plot_A", "plot_B"):
        r = _by_code_and_parcel(run_content_compliance(ex, split_schema, content_rules), "CONTENT_SETBACKS", parcel)
        assert r["verdict"] == VERDICT_REQUIRES_REVIEW


def test_parking_deferred_when_status_is_deferred(split_schema, content_rules):
    ex = _extracted(plot_A={"parking_private": 100, "unit_count": 50})
    r = _by_code_and_parcel(run_content_compliance(ex, split_schema, content_rules), "CONTENT_PARKING_RATIO", "plot_A")
    assert r["verdict"] == VERDICT_REQUIRES_REVIEW
    assert "תקנון" in r["notes_he"]


def test_split_mode_only_rules_run(split_schema, content_rules):
    # Switch to total mode → split-only rules become not_applicable
    total_schema = json.loads(json.dumps(split_schema))
    total_schema["project"]["meta"]["regulatory_mode"] = "total"
    ex = _extracted(plot_A={"area_main_m2": 4000})
    r = _by_code_and_parcel(run_content_compliance(ex, total_schema, content_rules), "CONTENT_BUILDING_AREA_MAIN", None)
    assert r["verdict"] == VERDICT_NOT_APPLICABLE


def test_permeable_pass(split_schema, content_rules):
    # 16% permeable across A+B -> pass at min_pct=15
    ex = _extracted(
        plot_A={"permeable_surface_m2": 200},  # 20% of 1000
        plot_B={"permeable_surface_m2": 40},   # 8%  of 500
    )
    # Total: 240 / 1500 = 16%
    r = _by_code_and_parcel(run_content_compliance(ex, split_schema, content_rules), "CONTENT_PERMEABLE_SURFACES", None)
    assert r["verdict"] == VERDICT_PASS


def test_permeable_fail(split_schema, content_rules):
    ex = _extracted(
        plot_A={"permeable_surface_m2": 100},   # 10%
        plot_B={"permeable_surface_m2": 30},    # 6%
    )
    r = _by_code_and_parcel(run_content_compliance(ex, split_schema, content_rules), "CONTENT_PERMEABLE_SURFACES", None)
    assert r["verdict"] == VERDICT_FAIL


# -------------------------------------------------------------------------
# 2. Extraction-cache determinism
# -------------------------------------------------------------------------

@pytest.fixture(scope="session")
def small_pdf(tmp_path_factory) -> Path:
    """A tiny synthetic PDF that the extractor can walk without LLM."""
    out = tmp_path_factory.mktemp("content_fix") / "small.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 40), "מגרש 1\nסה\"כ יח\"ד: 235\nשטח עיקרי: 22000\nגובה: 49 מ׳", fontsize=12)
    doc.save(str(out))
    doc.close()
    return out


def test_extraction_cache_is_byte_identical(small_pdf, tmp_path):
    schema = {"project": {"parcels": [{"parcel_id": "plot_1"}]}}
    cache = tmp_path / "cache.json"
    e1 = extract(small_pdf, schema, cache_path=cache, use_cache=True, allow_llm=False)
    blob1 = cache.read_bytes()
    e2 = extract(small_pdf, schema, cache_path=cache, use_cache=True, allow_llm=False)
    blob2 = cache.read_bytes()
    assert blob1 == blob2
    assert asdict(e1) == asdict(e2)


def test_manual_override_changes_verdict(small_pdf, tmp_path, content_rules):
    """Pre-populate the cache directly, then exercise the override flow.

    The synthetic PDF is just a vehicle for a SHA — Hebrew extraction quality
    is covered by the live audit, not here.
    """
    schema = {
        "project": {
            "meta": {"regulatory_mode": "split"},
            "parcels": [{
                "parcel_id": "plot_1",
                "plot_area_sqm": 1000,
                "building_rights": {"primary_sqm": 22105, "service_above_sqm": 9365, "service_below_sqm": 23255},
                "units": {"max_units": 235},
                "height": {"max_height_m": 50.0},
                "setbacks": {},
                "parking_standard": {"status": "deferred_to_national_standard", "source_quote": "x", "source_page": 17},
            }],
            "global_rules": {"small_apartments": {"min_pct": 20, "max_sqm": 80}},
            "compliance_rules": [{"rule_code": "PERMEABLE_SURFACES_MIN", "threshold": 15}],
        },
    }
    cache = tmp_path / "cache.json"

    # Seed cache with unit_count=200 (under the 235 cap → pass).
    sha = pdf_sha256(small_pdf)
    seed = {
        "_schema_version": "1.0.0",
        "entries": {
            f"{sha}:full_submission": {
                "pdf_sha256": sha,
                "extraction_target": "full_submission",
                "extraction_data": {
                    "plan_metadata": {},
                    "ta_shetach_data": [{
                        "ta_shetach_id": "plot_1",
                        "unit_count": 200,
                        "area_main_m2": None, "area_service_above_m2": None, "area_service_below_m2": None, "area_total_m2": None,
                        "heights_m": [], "setback_front_m": None, "setback_side_m": None, "setback_rear_m": None,
                        "parking_private": None, "parking_motorcycle": None, "parking_accessible": None, "parking_bike": None,
                        "permeable_surface_m2": None, "extraction_pages": {}, "extraction_methods": {}, "extraction_notes": {},
                    }],
                    "plan_wide_data": {
                        "apartment_size_distribution": {}, "unit_count_total": None, "architect_name": None,
                        "submission_date": None, "extraction_methods": {}, "extraction_notes": {},
                    },
                    "extraction_quality": {"llm_available": False, "llm_used": False, "missing_api_key": True, "page_count": 1, "fields_extracted_count": 1},
                    "pdf_sha256": sha,
                    "schema_version": "1.0.0",
                },
                "extraction_metadata": {"manually_overridden": False},
            }
        },
    }
    cache.write_text(json.dumps(seed, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    e1 = extract(small_pdf, schema, cache_path=cache, use_cache=True, allow_llm=False)
    res1 = run_content_compliance(e1, schema, content_rules)
    assert _by_code_and_parcel(res1, "CONTENT_UNIT_COUNT", "plot_1")["verdict"] == VERDICT_PASS

    # Manually override the cached unit_count to 250 (above the 235 cap).
    cache_data = json.loads(cache.read_text(encoding="utf-8"))
    key = next(iter(cache_data["entries"]))
    cache_data["entries"][key]["extraction_data"]["ta_shetach_data"][0]["unit_count"] = 250
    cache_data["entries"][key]["extraction_metadata"]["manually_overridden"] = True
    cache.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    e2 = extract(small_pdf, schema, cache_path=cache, use_cache=True, allow_llm=False)
    res2 = run_content_compliance(e2, schema, content_rules)
    r = _by_code_and_parcel(res2, "CONTENT_UNIT_COUNT", "plot_1")
    assert r["verdict"] == VERDICT_FAIL
    assert r["evidence"]["overrun"] == 15


def test_no_api_key_yields_unevaluable_for_missing_fields(split_schema, content_rules):
    """Without extracted values, all data-dependent rules are unevaluable."""
    ex = _extracted()  # everything null
    results = run_content_compliance(ex, split_schema, content_rules)
    # CONTENT_SETBACKS is requires_review, CONTENT_PARKING_RATIO is requires_review
    # All other rules should be unevaluable, not_applicable, or similar — none "fail"
    for r in results:
        assert r["verdict"] in (VERDICT_UNEVALUABLE, VERDICT_REQUIRES_REVIEW, VERDICT_NOT_APPLICABLE), (
            f"{r['rule_code']}/{r.get('ta_shetach_id')} returned {r['verdict']} with no extracted data"
        )
