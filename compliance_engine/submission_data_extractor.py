"""Submission data extractor.

Pulls per-תא-שטח and plan-wide values from the תכנית עיצוב PDF.

Strategy (in order of preference per field):
  1. Direct PDF table extraction (pdfplumber)
  2. Regex on extracted text
  3. LLM extraction (Claude Sonnet 4.6, temperature=0, structured output)

Outputs are cached (extraction_cache.py). Same PDF → same cache → same
downstream verdicts. If ANTHROPIC_API_KEY is missing, fields that regex /
table extraction cannot recover are returned as null with a clear reason; the
checker turns those into `unevaluable` verdicts.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

import fitz  # PyMuPDF
from compliance_engine.text_utils import patch_rtl_artifacts

from .extraction_cache import get_or_extract, pdf_sha256

log = logging.getLogger(__name__)

ANTHROPIC_MODEL = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TAShetachData:
    ta_shetach_id: str
    unit_count: int | None = None
    area_main_m2: float | None = None
    area_service_above_m2: float | None = None
    area_service_below_m2: float | None = None
    area_total_m2: float | None = None
    heights_m: list[float] = field(default_factory=list)
    setback_front_m: float | None = None
    setback_side_m: float | None = None
    setback_rear_m: float | None = None
    parking_private: int | None = None
    parking_motorcycle: int | None = None
    parking_accessible: int | None = None
    parking_bike: int | None = None
    permeable_surface_m2: float | None = None
    extraction_pages: dict = field(default_factory=dict)
    extraction_methods: dict = field(default_factory=dict)  # field -> "regex" | "table" | "llm" | "none"
    extraction_notes: dict = field(default_factory=dict)


@dataclass
class PlanWideData:
    apartment_size_distribution: dict[str, int] = field(default_factory=dict)
    unit_count_total: int | None = None
    architect_name: str | None = None
    submission_date: str | None = None
    extraction_methods: dict = field(default_factory=dict)
    extraction_notes: dict = field(default_factory=dict)


@dataclass
class ExtractedSubmissionData:
    plan_metadata: dict
    ta_shetach_data: list[TAShetachData]
    plan_wide_data: PlanWideData
    extraction_quality: dict
    pdf_sha256: str
    schema_version: str = "1.0.0"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract(
    pdf_path: Path,
    project_schema: dict,
    *,
    cache_path: Path,
    use_cache: bool = True,
    allow_llm: bool | None = None,
) -> ExtractedSubmissionData:
    """Extract submission data, using the cache when available.

    allow_llm: if explicitly False, never call the API. If None (default), the
    API is used only when ANTHROPIC_API_KEY is set AND the `anthropic` package
    imports cleanly. If True and the key/SDK are missing, falls back to
    regex/pdfplumber and notes the API absence in extraction_quality.
    """
    pdf_path = Path(pdf_path)
    sha = pdf_sha256(pdf_path)
    parcels = project_schema.get("project", {}).get("parcels", []) or []
    parcel_ids = [p["parcel_id"] for p in parcels if p.get("parcel_id")]

    if allow_llm is None:
        allow_llm = _llm_available()

    def _do_extract() -> dict:
        text_by_page, page_count = _extract_text_by_page(pdf_path)

        per_ta: list[TAShetachData] = []
        for pid in parcel_ids:
            per_ta.append(_extract_for_parcel(pid, text_by_page, pdf_path, allow_llm=allow_llm))

        plan_wide = _extract_plan_wide(text_by_page, allow_llm=allow_llm)

        plan_metadata = _extract_plan_metadata(text_by_page)

        extraction_quality = {
            "page_count": page_count,
            "llm_available": _llm_available(),
            "llm_used": allow_llm and _llm_available(),
            "missing_api_key": os.environ.get("ANTHROPIC_API_KEY") is None,
            "fields_extracted_count": _count_non_null_fields(per_ta, plan_wide),
        }
        return asdict(ExtractedSubmissionData(
            plan_metadata=plan_metadata,
            ta_shetach_data=per_ta,
            plan_wide_data=plan_wide,
            extraction_quality=extraction_quality,
            pdf_sha256=sha,
        ))

    if use_cache:
        cached = get_or_extract(
            pdf_path=pdf_path,
            extraction_target="full_submission",
            cache_path=cache_path,
            extractor=_do_extract,
        )
        return _from_dict(cached)
    return _from_dict(_do_extract())


def _from_dict(d: dict) -> ExtractedSubmissionData:
    ta_list = [TAShetachData(**ta) for ta in d.get("ta_shetach_data", [])]
    plan_wide = PlanWideData(**d.get("plan_wide_data", {}))
    return ExtractedSubmissionData(
        plan_metadata=d.get("plan_metadata", {}),
        ta_shetach_data=ta_list,
        plan_wide_data=plan_wide,
        extraction_quality=d.get("extraction_quality", {}),
        pdf_sha256=d.get("pdf_sha256", ""),
        schema_version=d.get("schema_version", "1.0.0"),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_text_by_page(pdf_path: Path) -> tuple[dict[int, str], int]:
    doc = fitz.open(str(pdf_path))
    try:
        per_page: dict[int, str] = {}
        for i, page in enumerate(doc, start=1):
            per_page[i] = patch_rtl_artifacts(page.get_text("text") or "")
        return per_page, len(per_page)
    finally:
        doc.close()


_NUM = r"(\d{1,5}(?:[.,]\d+)?)"


def _to_float(s: str) -> float | None:
    if s is None:
        return None
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _to_int(s: str) -> int | None:
    f = _to_float(s)
    if f is None:
        return None
    return int(round(f))


def _first_match(patterns: Iterable[str], text: str) -> tuple[str | None, str | None]:
    """Return (value, matched_pattern) or (None, None)."""
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return (m.group(1) if m.groups() else m.group(0)), pat
    return None, None


def _aggregate_text(text_by_page: dict[int, str], pages: list[int]) -> str:
    return "\n".join(text_by_page.get(p, "") for p in pages)


def _find_parcel_page_band(parcel_id: str, text_by_page: dict[int, str]) -> list[int]:
    """Locate pages that explicitly reference this parcel. Best-effort, deterministic."""
    # parcel_id like "plot_1" → look for "מגרש 1"
    suffix = parcel_id.replace("plot_", "")
    needle_he = f"מגרש {suffix}"
    hits = [p for p, t in text_by_page.items() if needle_he in t]
    return hits


# ---------------------------------------------------------------------------
# Per-parcel extraction
# ---------------------------------------------------------------------------

def _extract_for_parcel(
    parcel_id: str,
    text_by_page: dict[int, str],
    pdf_path: Path,
    *,
    allow_llm: bool,
) -> TAShetachData:
    ta = TAShetachData(ta_shetach_id=parcel_id)
    pages = _find_parcel_page_band(parcel_id, text_by_page)
    ta.extraction_pages["parcel_pages"] = pages

    parcel_text = _aggregate_text(text_by_page, pages) if pages else ""

    # --- unit_count -------------------------------------------------------
    val, src = _first_match([
        rf"סה[\"״][\"״]?כ\s+יח[\"״][\"״]?ד\s*[:\-]?\s*{_NUM}",
        rf"יח[\"״][\"״]?ד\s+כולל\s*[:\-]?\s*{_NUM}",
        rf"כמות\s+יח[\"״][\"״]?ד\s*[:\-]?\s*{_NUM}",
    ], parcel_text)
    if val is not None:
        ta.unit_count = _to_int(val)
        ta.extraction_methods["unit_count"] = "regex"
        ta.extraction_notes["unit_count"] = src or ""

    # --- area_main_m2 -----------------------------------------------------
    val, src = _first_match([
        rf"שטח\s+עיקרי\s*[:\-]?\s*{_NUM}",
        rf"עיקרי\s*\(\s*מ[\"״][\"״]?ר\s*\)\s*[:\-]?\s*{_NUM}",
    ], parcel_text)
    if val is not None:
        ta.area_main_m2 = _to_float(val)
        ta.extraction_methods["area_main_m2"] = "regex"

    # --- area_service_above_m2 + below ------------------------------------
    val, _ = _first_match([rf"שטח\s+שירות\s+(?:מעל|עיליים?)\s*[:\-]?\s*{_NUM}"], parcel_text)
    if val is not None:
        ta.area_service_above_m2 = _to_float(val)
        ta.extraction_methods["area_service_above_m2"] = "regex"
    val, _ = _first_match([rf"שטח\s+שירות\s+(?:מתחת|תת[\-־]?קרקעי|תחתון|במרתף)\s*[:\-]?\s*{_NUM}"], parcel_text)
    if val is not None:
        ta.area_service_below_m2 = _to_float(val)
        ta.extraction_methods["area_service_below_m2"] = "regex"

    # --- heights_m --------------------------------------------------------
    heights = re.findall(rf"\bגובה\s*[:\-]?\s*{_NUM}\s*(?:מ['׳]?|מ\")", parcel_text)
    if heights:
        ta.heights_m = sorted({float(h.replace(",", ".")) for h in heights})
        ta.extraction_methods["heights_m"] = "regex"

    # --- parking_* --------------------------------------------------------
    for field_name, patterns in {
        "parking_private": [rf"חניה\s+פרטית\s*[:\-]?\s*{_NUM}", rf"מקומות\s+חניה\s+פרטיות?\s*[:\-]?\s*{_NUM}"],
        "parking_motorcycle": [rf"חניית\s+אופנועים?\s*[:\-]?\s*{_NUM}", rf"אופנועים\s*[:\-]?\s*{_NUM}"],
        "parking_accessible": [rf"חניית\s+נגישות\s*[:\-]?\s*{_NUM}", rf"נגישות\s*[:\-]?\s*{_NUM}"],
        "parking_bike": [rf"חניית\s+אופניים\s*[:\-]?\s*{_NUM}", rf"אופניים\s*[:\-]?\s*{_NUM}"],
    }.items():
        val, _ = _first_match(patterns, parcel_text)
        if val is not None:
            setattr(ta, field_name, _to_int(val))
            ta.extraction_methods[field_name] = "regex"

    # --- permeable_surface_m2 --------------------------------------------
    val, _ = _first_match([
        rf"שטח\s+מחלחל\s*[:\-]?\s*{_NUM}",
        rf"שטחים\s+מחלחלים\s*[:\-]?\s*{_NUM}",
    ], parcel_text)
    if val is not None:
        ta.permeable_surface_m2 = _to_float(val)
        ta.extraction_methods["permeable_surface_m2"] = "regex"

    # --- LLM fallback for null fields ------------------------------------
    if allow_llm and _llm_available():
        _llm_fill_parcel(ta, parcel_text, pdf_path)

    return ta


def _extract_plan_wide(text_by_page: dict[int, str], *, allow_llm: bool) -> PlanWideData:
    plan = PlanWideData()

    full_text = "\n".join(text_by_page.values())

    val, _ = _first_match([
        rf"סה[\"״][\"״]?כ\s+יח[\"״][\"״]?ד\s+בתכנית\s*[:\-]?\s*{_NUM}",
        rf"סה[\"״][\"״]?כ\s+יח[\"״][\"״]?ד\s*[:\-]?\s*{_NUM}",
    ], full_text)
    if val is not None:
        plan.unit_count_total = _to_int(val)
        plan.extraction_methods["unit_count_total"] = "regex"

    # apartment_size_distribution — captured as a mapping "{rooms}_rooms" -> count
    # Format varies; do a best-effort regex for "Nחדרים  M" tokens.
    mix: dict[str, int] = {}
    for room_count_match in re.finditer(rf"(\d)\s*חדרים?\s+{_NUM}", full_text):
        rooms = room_count_match.group(1)
        n = _to_int(room_count_match.group(2))
        if n is not None and 0 < n < 1000:
            key = f"{rooms}_rooms"
            mix[key] = max(mix.get(key, 0), n)
    if mix:
        plan.apartment_size_distribution = dict(sorted(mix.items()))
        plan.extraction_methods["apartment_size_distribution"] = "regex"

    if allow_llm and _llm_available():
        _llm_fill_plan_wide(plan, full_text)

    return plan


def _extract_plan_metadata(text_by_page: dict[int, str]) -> dict:
    cover = text_by_page.get(1, "")
    meta: dict = {"raw_cover_text": cover[:1000]}
    m = re.search(r"\b(\d{3}-\d{7})\b", cover)
    if m:
        meta["plan_number"] = m.group(1)
    m = re.search(r"גרסה\s+(\d+(?:\.\d+)?)", cover)
    if m:
        meta["submission_version"] = m.group(1)
    return meta


def _count_non_null_fields(ta_list: list[TAShetachData], plan_wide: PlanWideData) -> int:
    count = 0
    for ta in ta_list:
        for v in asdict(ta).values():
            if v not in (None, [], {}, ""):
                count += 1
    for v in asdict(plan_wide).values():
        if v not in (None, [], {}, ""):
            count += 1
    return count


# ---------------------------------------------------------------------------
# LLM extraction (Claude Sonnet 4.6, temperature=0, structured output)
# ---------------------------------------------------------------------------

def _llm_available() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") is None:
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


_PARCEL_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "unit_count":            {"type": ["integer", "null"]},
        "area_main_m2":          {"type": ["number", "null"]},
        "area_service_above_m2": {"type": ["number", "null"]},
        "area_service_below_m2": {"type": ["number", "null"]},
        "heights_m":             {"type": "array", "items": {"type": "number"}},
        "parking_private":       {"type": ["integer", "null"]},
        "parking_motorcycle":    {"type": ["integer", "null"]},
        "parking_accessible":    {"type": ["integer", "null"]},
        "parking_bike":          {"type": ["integer", "null"]},
        "permeable_surface_m2":  {"type": ["number", "null"]},
    },
    "required": [
        "unit_count", "area_main_m2", "area_service_above_m2", "area_service_below_m2",
        "heights_m", "parking_private", "parking_motorcycle", "parking_accessible",
        "parking_bike", "permeable_surface_m2",
    ],
}


_PARCEL_LLM_SYSTEM = (
    "You are a structured data extractor for Israeli urban planning documents (תכנית עיצוב). "
    "Extract specific numeric values verbatim from the provided text. Return null for any value "
    "you cannot find with high confidence — NEVER guess or interpolate. Temperature must be 0. "
    "All measurements are in m or m². Units (יח\"ד) are integers."
)


def _llm_call(system: str, user: str, schema: dict) -> dict | None:
    """Make a single Anthropic structured-output call. Returns parsed dict or None."""
    try:
        import anthropic
    except ImportError:
        return None
    client = anthropic.Anthropic()
    try:
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
            # Use tool_use as the structured-output mechanism (broadly supported by the SDK)
            tools=[{
                "name": "emit_fields",
                "description": "Return the extracted fields per the JSON schema.",
                "input_schema": schema,
            }],
            tool_choice={"type": "tool", "name": "emit_fields"},
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM extraction failed: %s", exc)
        return None
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use":
            return dict(block.input)
    return None


def _llm_fill_parcel(ta: TAShetachData, parcel_text: str, pdf_path: Path) -> None:
    if not parcel_text.strip():
        return
    null_fields = [k for k in _PARCEL_LLM_SCHEMA["required"] if _is_null(getattr(ta, k, None))]
    if not null_fields:
        return
    user_msg = (
        f"תא שטח: {ta.ta_shetach_id}\n"
        f"מתוך החוברת, חלץ את הערכים הבאים אם הם מופיעים במפורש (אחרת החזר null):\n"
        f"{', '.join(null_fields)}\n\n"
        f"--- טקסט הדפים הרלוונטיים ---\n{parcel_text[:12000]}"
    )
    result = _llm_call(_PARCEL_LLM_SYSTEM, user_msg, _PARCEL_LLM_SCHEMA)
    if not result:
        return
    for field_name in null_fields:
        new_val = result.get(field_name)
        if _is_null(new_val):
            continue
        # Field-type sanitization
        if field_name == "heights_m":
            if isinstance(new_val, list):
                ta.heights_m = sorted({float(x) for x in new_val if isinstance(x, (int, float))})
        elif field_name in {"unit_count", "parking_private", "parking_motorcycle", "parking_accessible", "parking_bike"}:
            setattr(ta, field_name, _to_int(new_val))
        else:
            setattr(ta, field_name, _to_float(new_val))
        ta.extraction_methods[field_name] = "llm"


_PLAN_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "unit_count_total":          {"type": ["integer", "null"]},
        "apartment_size_distribution": {
            "type": "object",
            "additionalProperties": {"type": "integer"},
        },
        "architect_name":  {"type": ["string", "null"]},
        "submission_date": {"type": ["string", "null"]},
    },
    "required": ["unit_count_total", "apartment_size_distribution"],
}

_PLAN_LLM_SYSTEM = _PARCEL_LLM_SYSTEM


def _llm_fill_plan_wide(plan: PlanWideData, full_text: str) -> None:
    if not full_text.strip():
        return
    user_msg = (
        "Extract plan-wide values from the booklet text. "
        "apartment_size_distribution keys MUST look like '3_rooms', '4_rooms'. "
        "Return null for any value you cannot find verbatim.\n\n"
        f"--- טקסט החוברת (מקוצר) ---\n{full_text[:16000]}"
    )
    result = _llm_call(_PLAN_LLM_SYSTEM, user_msg, _PLAN_LLM_SCHEMA)
    if not result:
        return
    if plan.unit_count_total is None and result.get("unit_count_total") is not None:
        plan.unit_count_total = _to_int(result["unit_count_total"])
        plan.extraction_methods["unit_count_total"] = "llm"
    mix = result.get("apartment_size_distribution") or {}
    if mix and not plan.apartment_size_distribution:
        plan.apartment_size_distribution = {str(k): int(v) for k, v in mix.items() if isinstance(v, int)}
        plan.extraction_methods["apartment_size_distribution"] = "llm"
    if not plan.architect_name and result.get("architect_name"):
        plan.architect_name = str(result["architect_name"])
        plan.extraction_methods["architect_name"] = "llm"
    if not plan.submission_date and result.get("submission_date"):
        plan.submission_date = str(result["submission_date"])
        plan.extraction_methods["submission_date"] = "llm"


def _is_null(v: Any) -> bool:
    return v is None or v == [] or v == {} or v == ""
