"""Per-page vision extraction: PDF page → PNG → Gemini Flash → PageManifest.

One Gemini call per page. PyMuPDF rasterizes each page to a 300-DPI PNG
held in memory, which is sent inline as a multimodal part alongside the
text prompt. The GeminiKeyRotator advances to the next backup key on
HTTP 429 / ResourceExhausted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import fitz  # PyMuPDF
import google.generativeai as genai
from google.api_core import exceptions as gax_exceptions

from ..config import GeminiKeyRotator
from ..clause_inventory.extract import pydantic_to_gemini_schema
from .schema import PageManifest, PageManifestResponse

MODEL_NAME = "gemini-2.5-flash"
EXTRACTOR_VERSION = "m1-v1"
PROMPT_VERSION = "m1-v1"
RASTER_DPI = 300


EXTRACTION_PROMPT = """You are analyzing a single page from an Israeli urban planning design document (תכנית עיצוב) in Hebrew.

This document type follows a standard structure where each plot (תא שטח) has up to 6 page types repeating: site plan (פיתוח), waste diagram (דיאגרמת אשפה), functions diagram (דיאגרמת פונקציות), daycare (מעונות יום), basement+parking table (מרתף), typical floor (קומה טיפוסית). Plus document-level pages: cover, summary, cross-sections (חתכים), elevations (חזיתות), public open space (שצ"פ), renderings (הדמיות).

Analyze the page image and produce a structured manifest:

1. page_type — pick ONE from this exact list (15 values):
   cover, table_of_contents, summary, site_plan_per_ta_shetach, waste_diagram, functions_diagram, daycare, basement_with_parking_table, typical_floor, cross_section, elevation, public_open_space, rendering, legend_or_key, other.

2. ta_shetach_refs — array of plot numbers (1-9) this page references. Look for labels like "מגרש X", "תא שטח X", or "תא X". Empty array if no specific plot reference.

3. visible_text_labels — 5-15 prominent Hebrew labels (titles, callouts, area names, key terms). Not every word; just the important ones a reader would notice first.

4. visible_dimensions — array of measurements with units. Each: {value: number, unit: string ("m", "m²", "cm"), context: 1-3 words}.

5. tables_present — array of tables on the page: {title: string, estimated_rows: integer}.

6. diagrams_present — array of drawings: {type: string (site_plan/floor_plan/section/elevation/diagram), description: 1-2 sentence}.

7. page_quality — one of: ok, illegible, incomplete, draft, blank.

RULES:
- Preserve Hebrew text — no translation
- Numbers are numeric values, not text
- Do not hallucinate — describe only what you see
- When ambiguous: prefer "other" + low-detail over confident guesses
- page_quality="draft" only if a visible "DRAFT/טיוטה" marker is present

OUTPUT: {manifest: {...}}
The page_number field on the manifest will be set by the caller; you may leave it 0 or echo a value, it will be overwritten.
"""


@dataclass
class PageUsage:
    prompt_token_count: Optional[int] = None
    candidates_token_count: Optional[int] = None
    total_token_count: Optional[int] = None


@dataclass
class PageResult:
    page_number: int
    manifest: Dict[str, Any]
    usage: Optional[PageUsage]
    key_attempts: int


@dataclass
class ExtractionResult:
    document: Dict[str, Any]
    page_count: int
    pages_processed: List[int]
    file_sha256: str
    aggregate_usage: Dict[str, int]
    total_key_attempts: int
    per_page: List[PageResult] = field(default_factory=list)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_pages_spec(spec: str, page_count: int) -> List[int]:
    """Convert a --pages spec ("1,13,26,39,52" or "all") to a sorted list
    of 1-indexed page numbers."""
    s = spec.strip().lower()
    if s == "all":
        return list(range(1, page_count + 1))
    out: List[int] = []
    for token in s.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            lo, hi = token.split("-", 1)
            lo_i = int(lo)
            hi_i = int(hi)
            if lo_i > hi_i:
                raise ValueError(f"Invalid range in --pages: {token!r}")
            out.extend(range(lo_i, hi_i + 1))
        else:
            out.append(int(token))
    deduped = sorted(set(out))
    for p in deduped:
        if p < 1 or p > page_count:
            raise ValueError(
                f"Page {p} out of range [1, {page_count}] in --pages spec"
            )
    return deduped


def rasterize_page(pdf_path: Path, page_number: int, dpi: int = RASTER_DPI) -> bytes:
    """Render page (1-indexed) to PNG bytes at given DPI."""
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    with fitz.open(pdf_path) as doc:
        if page_number < 1 or page_number > doc.page_count:
            raise ValueError(
                f"page_number {page_number} out of range [1, {doc.page_count}]"
            )
        page = doc.load_page(page_number - 1)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix.tobytes("png")


def _call_gemini_for_page(
    rotator: GeminiKeyRotator,
    page_number: int,
    png_bytes: bytes,
    schema: Dict[str, Any],
) -> Tuple[PageManifest, Optional[PageUsage], int]:
    """Send one page to Gemini Flash, rotating keys on 429."""
    attempts = 0
    while True:
        attempts += 1
        genai.configure(api_key=rotator.current())
        model = genai.GenerativeModel(MODEL_NAME)
        try:
            response = model.generate_content(
                [
                    EXTRACTION_PROMPT,
                    {"mime_type": "image/png", "data": png_bytes},
                ],
                generation_config={
                    "response_mime_type": "application/json",
                    "response_schema": schema,
                    "temperature": 0.0,
                },
            )
        except gax_exceptions.ResourceExhausted as exc:
            next_key = rotator.rotate()
            if next_key is None:
                raise RuntimeError(
                    f"All Gemini API keys hit quota (429) on page {page_number}. "
                    f"Last error: {exc}"
                ) from exc
            continue
        except gax_exceptions.TooManyRequests as exc:  # pragma: no cover
            next_key = rotator.rotate()
            if next_key is None:
                raise RuntimeError(
                    f"All Gemini API keys hit quota (429) on page {page_number}. "
                    f"Last error: {exc}"
                ) from exc
            continue

        usage: Optional[PageUsage] = None
        if getattr(response, "usage_metadata", None) is not None:
            um = response.usage_metadata
            usage = PageUsage(
                prompt_token_count=getattr(um, "prompt_token_count", None),
                candidates_token_count=getattr(um, "candidates_token_count", None),
                total_token_count=getattr(um, "total_token_count", None),
            )

        payload = response.text
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Gemini returned non-JSON output on page {page_number}: {exc}\n"
                f"---\n{payload[:500]}"
            ) from exc

        parsed = PageManifestResponse.model_validate(data)
        return parsed.manifest, usage, attempts


def extract_manifests(
    pdf_path: Path,
    plan_id: str,
    submission_id: str,
    pages: Sequence[int],
) -> ExtractionResult:
    """Full extraction pipeline. One Gemini call per requested page."""
    pdf_path = pdf_path.resolve()
    pdf_bytes = pdf_path.read_bytes()
    file_sha = _sha256_bytes(pdf_bytes)
    with fitz.open(pdf_path) as doc:
        page_count = doc.page_count

    rotator = GeminiKeyRotator()
    if not rotator.has_keys:
        raise RuntimeError(
            "No GEMINI_API_KEY env vars set. Export GEMINI_API_KEY (and optionally "
            "GEMINI_API_KEY_BACKUP_1/2/3) before running."
        )

    schema = pydantic_to_gemini_schema(PageManifestResponse)

    per_page: List[PageResult] = []
    aggregate_prompt = 0
    aggregate_candidates = 0
    aggregate_total = 0
    total_key_attempts = 0
    manifests_out: List[Dict[str, Any]] = []

    for page_number in pages:
        png_bytes = rasterize_page(pdf_path, page_number, dpi=RASTER_DPI)
        manifest_obj, usage, attempts = _call_gemini_for_page(
            rotator, page_number, png_bytes, schema
        )
        # Force page_number on the model to be the actual page we sent.
        manifest_obj = manifest_obj.model_copy(update={"page_number": page_number})
        manifest_dict = manifest_obj.model_dump()
        manifests_out.append(manifest_dict)
        per_page.append(
            PageResult(
                page_number=page_number,
                manifest=manifest_dict,
                usage=usage,
                key_attempts=attempts,
            )
        )
        total_key_attempts += attempts
        if usage is not None:
            aggregate_prompt += usage.prompt_token_count or 0
            aggregate_candidates += usage.candidates_token_count or 0
            aggregate_total += usage.total_token_count or 0

    document = {
        "plan_id": plan_id,
        "submission_id": submission_id,
        "source_pdf": pdf_path.name,
        "source_pdf_sha256": file_sha,
        "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "extractor": MODEL_NAME,
        "extractor_version": EXTRACTOR_VERSION,
        "page_count": page_count,
        "page_numbers_processed": list(pages),
        "manifests": manifests_out,
    }

    return ExtractionResult(
        document=document,
        page_count=page_count,
        pages_processed=list(pages),
        file_sha256=file_sha,
        aggregate_usage={
            "prompt_token_count": aggregate_prompt,
            "candidates_token_count": aggregate_candidates,
            "total_token_count": aggregate_total,
        },
        total_key_attempts=total_key_attempts,
        per_page=per_page,
    )
