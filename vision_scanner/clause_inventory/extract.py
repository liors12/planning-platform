"""Clause extraction: PDF → text → Gemini 2.5 Pro → ClausesResponse.

Single-call extraction. The PDF is rendered to text via PyMuPDF, page
boundaries are marked with `<<PAGE N>>`, and the whole document is sent
to Gemini Pro with the Pydantic ClausesResponse as `response_schema`.

On HTTP 429 / ResourceExhausted, the GeminiKeyRotator advances to the
next backup key and the call is retried.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import google.generativeai as genai
from google.api_core import exceptions as gax_exceptions

from ..config import GeminiKeyRotator
from .schema import ClausesResponse

MODEL_NAME = "gemini-2.5-pro"
EXTRACTOR_VERSION = "m0-v1"
PROMPT_VERSION = "m0-v1"

# Pydantic's JSON schema includes keys (`default`, `title`, `$defs`,
# `additionalProperties`, ...) that Gemini's Schema protobuf rejects. We walk
# the schema, resolve `$ref`s inline, fold `anyOf: [X, null]` into
# `nullable: true`, and strip every unsupported key.
_GEMINI_UNSUPPORTED_KEYS = frozenset({
    "default", "title", "$defs", "definitions", "additionalProperties",
    "examples", "discriminator", "$id", "$schema", "deprecated", "readOnly",
    "writeOnly",
})


def _gemini_clean(node: Any, defs: Dict[str, Any]) -> Any:
    if isinstance(node, list):
        return [_gemini_clean(item, defs) for item in node]
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        ref = node["$ref"]
        prefix = "#/$defs/"
        if not ref.startswith(prefix):
            raise ValueError(f"Unsupported $ref form: {ref!r}")
        name = ref[len(prefix):]
        if name not in defs:
            raise ValueError(f"$ref points at missing def: {name!r}")
        return _gemini_clean(defs[name], defs)

    if "anyOf" in node:
        options = node["anyOf"]
        non_null = [o for o in options if not (isinstance(o, dict) and o.get("type") == "null")]
        has_null = len(non_null) != len(options)
        if len(non_null) == 1:
            cleaned = _gemini_clean(non_null[0], defs)
            if isinstance(cleaned, dict) and has_null:
                cleaned = {**cleaned, "nullable": True}
            for k, v in node.items():
                if k == "anyOf" or k in _GEMINI_UNSUPPORTED_KEYS:
                    continue
                if isinstance(cleaned, dict) and k not in cleaned:
                    cleaned[k] = _gemini_clean(v, defs)
            return cleaned

    out: Dict[str, Any] = {}
    for k, v in node.items():
        if k in _GEMINI_UNSUPPORTED_KEYS:
            continue
        out[k] = _gemini_clean(v, defs)
    return out


def pydantic_to_gemini_schema(model_cls: Any) -> Dict[str, Any]:
    """Convert a Pydantic model to a Gemini-compatible schema dict."""
    raw = model_cls.model_json_schema()
    defs = raw.get("$defs", {}) or raw.get("definitions", {}) or {}
    return _gemini_clean(raw, defs)

EXTRACTION_PROMPT = """You are extracting clauses from an Israeli urban planning regulation
document (תקנון של תב"ע) in Hebrew.

The document is divided into numbered sections (1, 2, 3...), subsections
(1.1, 4.1.2...), lettered subsections (א, ב, ג), and numbered points.

For EVERY identifiable clause, emit one JSON object per the schema.

CRITICAL RULES:
1. Preserve Hebrew text faithfully — no translation, no paraphrasing,
   no summarization. clause_text is verbatim from the source.
2. clause_id reflects hierarchy: "4.1.2.א.4" means section 4 → 4.1 →
   4.1.2 → letter א → item 4
3. category MUST be from this exact list (15 values):
   [identification, objectives, land_use_zoning, building_geometry,
    building_rights, building_use, parking, infrastructure, stormwater,
    tree_preservation, unification_subdivision, public_areas, easements,
    building_height_safety, phasing, procedural]
4. is_quantitative=true ONLY when clause text contains a checkable
   number/threshold (e.g., "9 מטרים", "75%", "5 קומות"). false for
   text-only or descriptive content.
5. is_normative=true when the clause imposes a requirement
   (allow/forbid/must/shall). false for identification, description,
   or pure section headers without operative content.
6. Section headers WITHOUT operative content ARE clauses with both
   is_normative=false and is_quantitative=false. They are needed so
   child clauses' parent_id references resolve.
7. For the §5 building rights table (around page 16): emit ONE clause
   with clause_id="5.table" containing nested structured_values array
   + general_footnotes (lettered notes א-ד) + cell_footnotes (numbered 1-4).
8. page is 1-indexed from <<PAGE N>> markers.
9. parent_id is the immediate parent (e.g. parent of "4.1.2.א.4"
   is "4.1.2.א", parent of "4.1.2.א" is "4.1.2"). null for top-level
   (sections 1-7).

OUTPUT: {clauses: [...]}
"""


@dataclass
class ExtractionResult:
    document: Dict[str, Any]
    raw_text: str
    page_count: int
    file_sha256: str
    text_sha256: str
    usage_metadata: Optional[Dict[str, Any]]
    key_attempts: int


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_pdf_text(pdf_path: Path) -> Tuple[str, int]:
    """Open PDF, return (text_with_page_markers, page_count)."""
    parts: List[str] = []
    with fitz.open(pdf_path) as doc:
        page_count = doc.page_count
        for i in range(page_count):
            page = doc.load_page(i)
            parts.append(f"<<PAGE {i + 1}>>")
            parts.append(page.get_text())
    return "\n".join(parts), page_count


def _call_gemini(
    rotator: GeminiKeyRotator,
    document_text: str,
) -> Tuple[ClausesResponse, Optional[Dict[str, Any]], int]:
    """Send the extraction prompt to Gemini, rotating keys on 429.

    Returns (parsed_response, usage_metadata_dict, attempts).
    """
    attempts = 0
    last_error: Optional[Exception] = None
    while True:
        attempts += 1
        genai.configure(api_key=rotator.current())
        model = genai.GenerativeModel(MODEL_NAME)
        try:
            response = model.generate_content(
                [EXTRACTION_PROMPT, document_text],
                generation_config={
                    "response_mime_type": "application/json",
                    "response_schema": pydantic_to_gemini_schema(ClausesResponse),
                    "temperature": 0.0,
                },
            )
        except gax_exceptions.ResourceExhausted as exc:
            last_error = exc
            next_key = rotator.rotate()
            if next_key is None:
                raise RuntimeError(
                    f"All {attempts} Gemini API keys hit quota (429). Last error: {exc}"
                ) from exc
            continue
        except gax_exceptions.TooManyRequests as exc:  # pragma: no cover - alt name
            last_error = exc
            next_key = rotator.rotate()
            if next_key is None:
                raise RuntimeError(
                    f"All {attempts} Gemini API keys hit quota (429). Last error: {exc}"
                ) from exc
            continue

        usage = None
        if getattr(response, "usage_metadata", None) is not None:
            um = response.usage_metadata
            usage = {
                "prompt_token_count": getattr(um, "prompt_token_count", None),
                "candidates_token_count": getattr(um, "candidates_token_count", None),
                "total_token_count": getattr(um, "total_token_count", None),
            }

        payload = response.text
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Gemini returned non-JSON output: {exc}\n---\n{payload[:500]}"
            ) from exc
        parsed = ClausesResponse.model_validate(data)
        return parsed, usage, attempts


def extract_clauses(pdf_path: Path, plan_id: str) -> ExtractionResult:
    """Full extraction pipeline. Raises on any failure."""
    pdf_path = pdf_path.resolve()
    pdf_bytes = pdf_path.read_bytes()
    file_sha = _sha256_bytes(pdf_bytes)
    text, page_count = extract_pdf_text(pdf_path)
    text_sha = _sha256_bytes(text.encode("utf-8"))

    rotator = GeminiKeyRotator()
    if not rotator.has_keys:
        raise RuntimeError(
            "No GEMINI_API_KEY env vars set. Export GEMINI_API_KEY (and optionally "
            "GEMINI_API_KEY_BACKUP_1/2/3) before running."
        )

    parsed, usage, attempts = _call_gemini(rotator, text)

    document = {
        "plan_id": plan_id,
        "source_doc": pdf_path.name,
        "source_doc_sha256": file_sha,
        "source_doc_text_sha256": text_sha,
        "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "extractor": MODEL_NAME,
        "extractor_version": EXTRACTOR_VERSION,
        "page_count": page_count,
        "clauses": [c.model_dump(exclude_none=True) for c in parsed.clauses],
    }

    return ExtractionResult(
        document=document,
        raw_text=text,
        page_count=page_count,
        file_sha256=file_sha,
        text_sha256=text_sha,
        usage_metadata=usage,
        key_attempts=attempts,
    )
