"""Referent-comments PDF extraction — Phase 2b Module D extension.

Two-step pipeline:
  1. PyMuPDF (fitz): extract raw text from every PDF page.
  2. Claude API (tool-use): structure the text into discipline/status/topic/action rows.

When ANTHROPIC_API_KEY is absent from os.environ or the API call fails, returns
a single catch-all row with the full raw text in action_he and empty
discipline/status fields so Ellen can fill them in from the editable preview table.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from .disciplines import DISCIPLINES, STATUS_SET

log = logging.getLogger("sidecar.referent_extract")

_DISCIPLINE_ENUM = [d["key"] for d in DISCIPLINES]

_DISC_LEGEND = " | ".join(f"{d['key']} = {d['label']}" for d in DISCIPLINES)
_STATUS_LIST = " / ".join(sorted(STATUS_SET))

_SYSTEM_PROMPT = f"""\
אתה עוזר שמחלץ הערות רפרנטים ממסמכי תכנון עירוניים ישראלים.
קרא את הטקסט שחולץ מ-PDF של הערות רפרנט והפק רשימה מובנית של כל ההערות, הדרישות, והתנאים.

לכל הערה קבע:
1. discipline_key — הנושא המתאים מתוך הרשימה:
   {_DISC_LEGEND}
2. status — אחד מ: {_STATUS_LIST}
   "לא תקין" כאשר יש דרישה לתיקון, "נדרשת השלמה" כאשר חסר מידע, "תקין" כאשר הרפרנט אישר.
3. topic_he — תיאור קצר בעברית, עד 60 תווים.
4. action_he — הדרישה או הפעולה המלאה בעברית.
5. confidence — "high" כאשר שיוך הדיסציפלינה והסטטוס ברורים מהטקסט; "low" כאשר נדרש ניחוש או שהמידע חסר.

כללים:
- כל הערה/דרישה/תנאי נפרד → שורה נפרדת.
- אם לא ברור לאיזה discipline שייכת הערה, בחר את הקרוב ביותר והגדר confidence=low.
- החזר רק ערכים תקינים עבור discipline_key ו-status (מתוך הרשימות שלעיל).
"""

_EXTRACT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "discipline_key": {
                        "type": "string",
                        "enum": _DISCIPLINE_ENUM,
                    },
                    "status": {
                        "type": "string",
                        "enum": sorted(STATUS_SET),
                    },
                    "topic_he": {"type": "string"},
                    "action_he": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "low"],
                    },
                },
                "required": ["discipline_key", "status", "topic_he", "action_he", "confidence"],
            },
        }
    },
    "required": ["comments"],
}

# Claude claude-sonnet-4-6 supports 200K context; 50K gives a comfortable margin
# while fitting ~80-100 pages of dense referent text.
_MAX_TEXT_FOR_CLAUDE = 50_000

# PDFs with fewer than this many non-whitespace characters across all pages
# are treated as scanned/image-only — no text to analyse.
_SCAN_MIN_CHARS = 50


def extract_text(pdf_bytes: bytes) -> str:
    """Extract RTL-cleaned text from all PDF pages using PyMuPDF."""
    try:
        import fitz  # noqa: PLC0415 — lazy import; PyMuPDF
    except ImportError:
        log.warning("PyMuPDF not installed — cannot extract PDF text")
        return ""
    try:
        from compliance_engine.text_utils import patch_rtl_artifacts  # noqa: PLC0415
    except ImportError:
        patch_rtl_artifacts = lambda t: t  # noqa: E731 — fallback if not available

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        for page in doc:
            text = patch_rtl_artifacts(page.get_text())
            if text.strip():
                pages.append(text)
        doc.close()
        return "\n\n".join(pages)
    except Exception as exc:
        log.warning("fitz text extraction failed: %s", exc)
        return ""


def _call_claude(raw_text: str) -> list[dict[str, str]] | None:
    """Send text to Claude via tool-use and return structured rows, or None."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import anthropic  # noqa: PLC0415 — optional; only when key is set
    except ImportError:
        log.warning("anthropic SDK not available")
        return None

    snippet = raw_text[:_MAX_TEXT_FOR_CLAUDE]

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": f"חלץ הערות רפרנטים מהטקסט הבא:\n\n{snippet}"},
            ],
            tools=[
                {
                    "name": "emit_comments",
                    "description": "Return the structured referent comments.",
                    "input_schema": _EXTRACT_SCHEMA,
                }
            ],
            tool_choice={"type": "tool", "name": "emit_comments"},
        )
        for block in resp.content:
            if getattr(block, "type", "") == "tool_use":
                rows: list[dict[str, str]] = list(block.input.get("comments", []))
                for row in rows:
                    # Clamp topic_he to 60 chars — model sometimes exceeds it.
                    if len(row.get("topic_he", "")) > 60:
                        row["topic_he"] = row["topic_he"][:57] + "..."
                return rows
    except Exception as exc:
        log.warning("Claude API call failed: %s", exc)
    return None


def _fallback_row(raw_text: str) -> list[dict[str, str]]:
    return [
        {
            "discipline_key": "",
            "status": "",
            "topic_he": "",
            "action_he": raw_text.strip()[:4000],
            "confidence": "low",
        }
    ]


def extract_referent_comments(pdf_bytes: bytes) -> dict[str, Any]:
    """Main entry point — returns the extraction result dict.

    Shape:
      {comments: [...], raw_text: str, used_ai: bool,
       error?: "scan", error_message?: str, truncation_warning?: str}

    "scan" error means the PDF yielded no extractable text (likely a scanned image).
    When present, error_message contains a user-facing Hebrew explanation.
    truncation_warning is set when the PDF text exceeded _MAX_TEXT_FOR_CLAUDE chars
    and only the first portion was sent to Claude.
    """
    raw_text = extract_text(pdf_bytes)
    if len(raw_text.strip()) < _SCAN_MIN_CHARS:
        return {
            "comments": [],
            "raw_text": raw_text,
            "used_ai": False,
            "error": "scan",
            "error_message": (
                "הקובץ סרוק ואינו מכיל טקסט מחלץ. "
                "נא להעלות קובץ PDF טקסטואלי (לא סריקה)."
            ),
        }

    truncation_warning: str | None = None
    if len(raw_text) > _MAX_TEXT_FOR_CLAUDE:
        truncation_warning = (
            f"הקובץ מכיל {len(raw_text):,} תווים. "
            f"רק 50,000 הראשונים נותחו. "
            "ייתכן שהערות מעמודים אחרונים חסרות."
        )
        log.info(
            "PDF text truncated from %d to %d chars before Claude call",
            len(raw_text),
            _MAX_TEXT_FOR_CLAUDE,
        )

    ai_rows = _call_claude(raw_text)
    if ai_rows is not None:
        result: dict[str, Any] = {"comments": ai_rows, "raw_text": raw_text, "used_ai": True}
        if truncation_warning:
            result["truncation_warning"] = truncation_warning
        return result

    result = {
        "comments": _fallback_row(raw_text),
        "raw_text": raw_text,
        "used_ai": False,
    }
    if truncation_warning:
        result["truncation_warning"] = truncation_warning
    return result
