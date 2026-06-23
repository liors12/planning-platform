"""Meeting-notes PDF extraction.

Two-step pipeline:
  1. PyMuPDF (fitz): extract raw text from every PDF page.
  2. Gemini API (structured output): parse into decision/action-item rows
     (row_type, topic_he, decision_he, responsible_he, deadline_he).

Fallback: when GEMINI_API_KEY is absent or the API call fails, returns a
single catch-all row with the full raw text in decision_he.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("sidecar.meeting_extract")

_MODEL_NAME = "gemini-2.5-flash"
_VALID_ROW_TYPES = ["decision", "action_item", "open_issue"]

_SYSTEM_PROMPT = """\
אתה עוזר שמחלץ החלטות ומשימות מסיכומי ישיבות תכנון עירוניות ישראליות.
קרא את הטקסט שחולץ מ-PDF של סיכום ישיבה או פרוטוקול ועדה והפק רשימה מובנית
של כל ההחלטות, המשימות, והנושאים הפתוחים.

לכל פריט קבע:
1. row_type — סוג הפריט:
   - "decision"    — החלטה שהתקבלה בישיבה
   - "action_item" — משימה שמוטלת על גורם מסוים
   - "open_issue"  — נושא שנדרש בירור נוסף
2. topic_he — נושא קצר בעברית, עד 60 תווים.
3. decision_he — ניסוח מלא של ההחלטה/המשימה/הנושא בעברית.
4. responsible_he — שם הגורם האחראי לביצוע (null אם לא צוין).
5. deadline_he — מועד יעד לביצוע כפי שנרשם (null אם לא צוין).

כללים:
- כל החלטה/משימה נפרדת → שורה נפרדת.
- topic_he לא יעלה על 60 תווים.
- decision_he לא יעלה על 500 תווים.
- אם ה-PDF אינו מכיל פריטי סיכום ישיבה ברורים, החזר רשימה ריקה.
"""

_GEMINI_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "row_type": {
                        "type": "string",
                        "enum": _VALID_ROW_TYPES,
                    },
                    "topic_he": {"type": "string"},
                    "decision_he": {"type": "string"},
                    "responsible_he": {"type": "string", "nullable": True},
                    "deadline_he": {"type": "string", "nullable": True},
                },
                "required": ["row_type", "topic_he", "decision_he",
                             "responsible_he", "deadline_he"],
            },
        }
    },
    "required": ["items"],
}

_MAX_TEXT_CHARS = 50_000
_SCAN_MIN_CHARS = 30


def _extract_text(pdf_bytes: bytes) -> str:
    try:
        import fitz  # noqa: PLC0415
    except ImportError:
        log.warning("PyMuPDF not installed — cannot extract PDF text")
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


def _call_gemini(raw_text: str) -> list[dict] | None:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import json  # noqa: PLC0415
        import google.generativeai as genai  # noqa: PLC0415
    except ImportError:
        log.warning("google-generativeai SDK not available")
        return None

    snippet = raw_text[:_MAX_TEXT_CHARS]
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            _MODEL_NAME,
            system_instruction=_SYSTEM_PROMPT,
        )
        resp = model.generate_content(
            f"חלץ פריטים מסיכום הישיבה הבא:\n\n{snippet}",
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": _GEMINI_SCHEMA,
                "temperature": 0.0,
                "max_output_tokens": 4096,
            },
        )
        data = json.loads(resp.text)
        rows: list[dict] = list(data.get("items", []))
        for row in rows:
            if len(row.get("topic_he", "")) > 60:
                row["topic_he"] = row["topic_he"][:57] + "..."
            if len(row.get("decision_he", "")) > 500:
                row["decision_he"] = row["decision_he"][:497] + "..."
            if row.get("row_type") not in _VALID_ROW_TYPES:
                row["row_type"] = "action_item"
        return rows
    except Exception as exc:
        log.warning("Gemini API call failed: %s", exc)
    return None


def _fallback_row(raw_text: str) -> list[dict]:
    return [
        {
            "row_type": "action_item",
            "topic_he": "",
            "decision_he": raw_text.strip()[:500],
            "responsible_he": None,
            "deadline_he": None,
        }
    ]


def extract_meeting_notes(pdf_bytes: bytes) -> dict[str, Any]:
    """Main entry point.

    Returns:
      {items: [...], raw_text: str, used_ai: bool,
       error?: "scan", error_message?: str, truncation_warning?: str}
    """
    raw_text = _extract_text(pdf_bytes)
    if len(raw_text.strip()) < _SCAN_MIN_CHARS:
        return {
            "items": [],
            "raw_text": raw_text,
            "used_ai": False,
            "error": "scan",
            "error_message": (
                "הקובץ סרוק ואינו מכיל טקסט מחלץ. "
                "נא להעלות קובץ PDF טקסטואלי."
            ),
        }

    truncation_warning: str | None = None
    if len(raw_text) > _MAX_TEXT_CHARS:
        truncation_warning = (
            f"הקובץ מכיל {len(raw_text):,} תווים. "
            "רק 50,000 הראשונים נותחו. "
            "ייתכן שפריטים מעמודים אחרונים חסרים."
        )

    ai_rows = _call_gemini(raw_text)
    if ai_rows is not None:
        result: dict[str, Any] = {"items": ai_rows, "raw_text": raw_text, "used_ai": True}
        if truncation_warning:
            result["truncation_warning"] = truncation_warning
        return result

    result = {
        "items": _fallback_row(raw_text),
        "raw_text": raw_text,
        "used_ai": False,
    }
    if truncation_warning:
        result["truncation_warning"] = truncation_warning
    return result
