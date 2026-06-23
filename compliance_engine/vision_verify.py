"""Targeted vision verification for architect claimed changes.

For each claim (page_number + verification_question), rasterizes the page
from the submission file (PDF or DWFX) and sends the image to Gemini 2.5 Flash
with the question. Returns per-claim: verified, evidence, status (Hebrew).

Requires GEMINI_API_KEY in environment. Falls back to status=דורש בירור when
the key is absent or the API call fails.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("compliance_engine.vision_verify")

_GEMINI_MODEL = "gemini-2.5-flash"
_VERIFY_DPI = 200

_VERIFY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "verified": {
            "type": "string",
            "enum": ["yes", "no", "unclear"],
        },
        "evidence": {"type": "string"},
        "status_he": {
            "type": "string",
            "enum": ["תקין", "דורש תיקון", "דורש בירור"],
        },
    },
    "required": ["verified", "evidence", "status_he"],
}

_SYSTEM_PROMPT = """\
אתה מוודא שינויים של אדריכל בתוכנית בנייה. תקבל תמונה של עמוד מהתוכנית ושאלה ספציפית.
ענה רק על סמך מה שאתה רואה בתמונה — אל תשער ואל תניח.
החזר:
- verified: "yes" אם השינוי קיים ומאושר, "no" אם השינוי לא קיים, "unclear" אם לא ניתן לקבוע
- evidence: תיאור קצר של מה שראית (עד 200 תווים)
- status_he: "תקין" אם verified=yes, "דורש תיקון" אם verified=no, "דורש בירור" אם verified=unclear
"""


def _rasterize_page(file_path: Path, page_number: int, dpi: int = _VERIFY_DPI) -> bytes:
    """Render page (1-indexed) from PDF or DWFX to PNG bytes."""
    try:
        import fitz  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("PyMuPDF (fitz) is required for vision verification") from exc

    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    with fitz.open(str(file_path)) as doc:
        if page_number < 1 or page_number > doc.page_count:
            raise ValueError(
                f"page_number {page_number} out of range [1, {doc.page_count}]"
            )
        page = doc.load_page(page_number - 1)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix.tobytes("png")


_MAX_JSON_RETRY = 2


def _call_gemini_vision(png_bytes: bytes, question: str) -> dict[str, Any] | None:
    """Send page image + question to Gemini. Returns parsed result dict or None.

    Retries on JSON parse errors (thinking-token truncation can produce
    partial JSON on the first attempt; a retry usually succeeds).
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import json  # noqa: PLC0415
        import google.generativeai as genai  # noqa: PLC0415
    except ImportError:
        log.warning("google-generativeai not installed")
        return None

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        _GEMINI_MODEL,
        system_instruction=_SYSTEM_PROMPT,
    )
    generation_config = {
        "response_mime_type": "application/json",
        "response_schema": _VERIFY_SCHEMA,
        "temperature": 0.0,
        "max_output_tokens": 4096,
    }
    contents = [question, {"mime_type": "image/png", "data": png_bytes}]

    json_failures = 0
    while True:
        try:
            resp = model.generate_content(contents, generation_config=generation_config)
            return json.loads(resp.text)
        except json.JSONDecodeError:
            json_failures += 1
            if json_failures > _MAX_JSON_RETRY:
                log.warning("Gemini vision: JSON parse failed after %d retries", json_failures)
                return None
            log.debug("Gemini vision: JSON truncated, retry %d", json_failures)
        except Exception as exc:
            log.warning("Gemini vision call failed: %s", exc)
            return None


def _no_key_result(claim: dict) -> dict:
    return {
        "page_number": claim.get("page_number"),
        "claim_text": claim.get("claim_text", ""),
        "verification_question": claim.get("verification_question", ""),
        "verified": "unclear",
        "evidence": "מפתח API חסר — לא ניתן לבצע אימות חזותי",
        "status": "דורש בירור",
    }


def verify_claimed_changes(
    file_path: Path,
    claims: list[dict],
) -> list[dict]:
    """Verify each claim by rasterizing its page and asking Gemini.

    Each claim dict must have:
      - page_number (int, 1-indexed)
      - claim_text (str)
      - verification_question (str)

    Returns list of result dicts with the original claim fields plus:
      - verified: "yes" / "no" / "unclear"
      - evidence: str
      - status: "תקין" / "דורש תיקון" / "דורש בירור"
    """
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        log.warning("GEMINI_API_KEY not set — returning דורש בירור for all claims")
        return [_no_key_result(c) for c in claims]

    file_path = Path(file_path)
    results = []
    for claim in claims:
        page_number = int(claim.get("page_number", 1))
        claim_text = claim.get("claim_text", "")
        question = claim.get("verification_question", "")

        base = {
            "page_number": page_number,
            "claim_text": claim_text,
            "verification_question": question,
        }

        try:
            png_bytes = _rasterize_page(file_path, page_number)
        except Exception as exc:
            log.warning("Failed to rasterize page %d from %s: %s", page_number, file_path, exc)
            results.append({
                **base,
                "verified": "unclear",
                "evidence": f"לא ניתן לעבד את העמוד: {exc}",
                "status": "דורש בירור",
            })
            continue

        gemini_result = _call_gemini_vision(png_bytes, question)
        if gemini_result is None:
            results.append({
                **base,
                "verified": "unclear",
                "evidence": "קריאת Gemini נכשלה",
                "status": "דורש בירור",
            })
            continue

        results.append({
            **base,
            "verified": gemini_result.get("verified", "unclear"),
            "evidence": gemini_result.get("evidence", ""),
            "status": gemini_result.get("status_he", "דורש בירור"),
        })

    return results
