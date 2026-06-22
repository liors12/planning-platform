"""Architect email PDF extraction — extracts structured corrections from
an architect's email saved as PDF.

Two-step pipeline:
  1. PyMuPDF (fitz): extract raw text from every PDF page.
  2. Claude API (tool-use): structure text into page/change/category rows.

Same fallback pattern as referent_extract.py: when ANTHROPIC_API_KEY is absent
or the API call fails, returns a single catch-all row with the full raw text.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("sidecar.email_extract")

_VALID_CATEGORIES = ["text_addition", "table_update", "drawing_change"]

_SYSTEM_PROMPT = """\
אתה עוזר שמחלץ תיקונים מהודעות דוא"ל של אדריכלים שנשמרו כ-PDF.
קרא את הטקסט שחולץ מה-PDF והפק רשימה מובנית של כל התיקונים שהאדריכל ביצע בתכנית.

לכל תיקון קבע:
1. page_number — מספר העמוד שמוזכר (null אם לא צוין מספר עמוד).
2. change_he — תיאור התיקון בעברית, משפט אחד תמציתי.
3. category — אחד מ:
   - "text_addition"   — הוספה/תיקון של טקסט או הסברים
   - "table_update"    — עדכון טבלה, נתון, או מספר
   - "drawing_change"  — שינוי בשרטוט, תוספת גרפית, עדכון תוכנית

כללים:
- כל תיקון נפרד → שורה נפרדת.
- אם page_number לא מוזכר בטקסט → החזר null.
- change_he לא יעלה על 200 תווים.
- אם ה-PDF אינו מכיל תיקונים ברורים, החזר רשימה ריקה.
"""

_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page_number": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                    },
                    "change_he": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": _VALID_CATEGORIES,
                    },
                },
                "required": ["page_number", "change_he", "category"],
            },
        }
    },
    "required": ["corrections"],
}

_MAX_TEXT_CHARS = 40_000
_SCAN_MIN_CHARS = 30


def _extract_text(pdf_bytes: bytes) -> str:
    try:
        import fitz
    except ImportError:
        log.warning("PyMuPDF not installed — cannot extract email PDF text")
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        for page in doc:
            t = page.get_text()
            if t.strip():
                pages.append(t)
        doc.close()
        return "\n\n".join(pages)
    except Exception as exc:
        log.warning("fitz text extraction failed: %s", exc)
        return ""


def _call_claude(raw_text: str) -> list[dict] | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic SDK not available")
        return None

    snippet = raw_text[:_MAX_TEXT_CHARS]
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": f"חלץ תיקונים מהדוא\"ל הבא:\n\n{snippet}"},
            ],
            tools=[
                {
                    "name": "emit_corrections",
                    "description": "Return the structured architect corrections.",
                    "input_schema": _SCHEMA,
                }
            ],
            tool_choice={"type": "tool", "name": "emit_corrections"},
        )
        for block in resp.content:
            if getattr(block, "type", "") == "tool_use":
                rows: list[dict] = list(block.input.get("corrections", []))
                for row in rows:
                    if len(row.get("change_he", "")) > 200:
                        row["change_he"] = row["change_he"][:197] + "..."
                    if row.get("category") not in _VALID_CATEGORIES:
                        row["category"] = "drawing_change"
                return rows
    except Exception as exc:
        log.warning("Claude API call failed: %s", exc)
    return None


def _fallback_row(raw_text: str) -> list[dict]:
    return [
        {
            "page_number": None,
            "change_he": raw_text.strip()[:200],
            "category": "drawing_change",
        }
    ]


def extract_email_corrections(pdf_bytes: bytes) -> dict[str, Any]:
    """Main entry point.

    Returns:
      {corrections: [...], raw_text: str, used_ai: bool,
       error?: "scan", error_message?: str}
    """
    raw_text = _extract_text(pdf_bytes)
    if len(raw_text.strip()) < _SCAN_MIN_CHARS:
        return {
            "corrections": [],
            "raw_text": raw_text,
            "used_ai": False,
            "error": "scan",
            "error_message": (
                "הקובץ סרוק ואינו מכיל טקסט מחלץ. "
                "נא להעלות קובץ PDF טקסטואלי."
            ),
        }

    ai_rows = _call_claude(raw_text)
    if ai_rows is not None:
        return {"corrections": ai_rows, "raw_text": raw_text, "used_ai": True}

    return {
        "corrections": _fallback_row(raw_text),
        "raw_text": raw_text,
        "used_ai": False,
    }
