"""Unified comments-document extraction (round-2 addendum 6).

ONE upload button in the UI feeds this module. A single Gemini call first
CLASSIFIES the document - a single-referent comment sheet vs a multi-speaker
meeting summary - and then extracts discipline comments accordingly (the two
legacy prompts folded into one instruction with a doc_type branch). Both
document types produce the same referent-comment row shape, so the existing
editable preview + save flow applies unchanged.

The two legacy endpoints (extract-referent-pdf, upload-meeting-pdf) keep
working for backward compatibility; the UI now calls only this one.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from .disciplines import DISCIPLINES, STATUS_SET
from .referent_extract import extract_text, _MAX_TEXT_CHARS, _SCAN_MIN_CHARS

log = logging.getLogger("sidecar.unified_extract")

_MODEL_NAME = "gemini-2.5-flash"
_DISCIPLINE_ENUM = [d["key"] for d in DISCIPLINES]
_DISC_LEGEND = " | ".join(f"{d['key']} = {d['label']}" for d in DISCIPLINES)
_STATUS_LIST = " / ".join(sorted(STATUS_SET))

_SYSTEM_PROMPT = f"""\
אתה עוזר שמחלץ הערות ממסמכי תכנון עירוניים ישראלים.

שלב 1 - סיווג המסמך. קבע doc_type:
- "referent" - גיליון הערות של רפרנט יחיד (גורם מקצועי אחד שכתב הערות על תכנית)
- "meeting"  - סיכום ישיבה או פרוטוקול עם מספר דוברים/גורמים

שלב 2 - חילוץ. הפק רשימה מובנית של כל ההערות, הדרישות, ההחלטות והתנאים.
במסמך referent רוב ההערות שייכות בדרך כלל לדיסציפלינה אחת; בסיכום ישיבה
ההערות מתפזרות בין דיסציפלינות שונות לפי הדובר/הנושא. החלטות ומשימות
מסיכום ישיבה מנוסחות כהערה עם הפעולה הנדרשת (כולל גורם אחראי ומועד אם צוינו).

לכל הערה קבע:
1. discipline_key - הנושא המתאים מתוך הרשימה:
   {_DISC_LEGEND}
2. status - אחד מ: {_STATUS_LIST}
   "לא תקין" כאשר יש דרישה לתיקון, "נדרשת השלמה" כאשר חסר מידע, "תקין" כאשר אושר.
3. topic_he - תיאור קצר בעברית, עד 60 תווים.
4. action_he - הדרישה/ההחלטה/הפעולה המלאה בעברית.
5. confidence - "high" כאשר השיוך ברור מהטקסט; "low" כאשר נדרש ניחוש.

כללים:
- כל הערה/דרישה/החלטה נפרדת → שורה נפרדת.
- החזר רק ערכים תקינים עבור discipline_key ו-status (מתוך הרשימות שלעיל).
"""

_GEMINI_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": ["referent", "meeting"]},
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "discipline_key": {"type": "string", "enum": _DISCIPLINE_ENUM},
                    "status": {"type": "string", "enum": sorted(STATUS_SET)},
                    "topic_he": {"type": "string"},
                    "action_he": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "low"]},
                },
                "required": ["discipline_key", "status", "topic_he", "action_he", "confidence"],
            },
        },
    },
    "required": ["doc_type", "comments"],
}


def _call_gemini(raw_text: str) -> dict | None:
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
        model = genai.GenerativeModel(_MODEL_NAME, system_instruction=_SYSTEM_PROMPT)
        resp = model.generate_content(
            f"סווג את המסמך וחלץ את ההערות מהטקסט הבא:\n\n{snippet}",
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": _GEMINI_SCHEMA,
                "temperature": 0.0,
                "max_output_tokens": 8192,
            },
        )
        data = json.loads(resp.text)
        rows = list(data.get("comments", []))
        for row in rows:
            if len(row.get("topic_he", "")) > 60:
                row["topic_he"] = row["topic_he"][:57] + "..."
        return {"doc_type": data.get("doc_type") or "referent", "comments": rows}
    except Exception as exc:
        log.warning("unified Gemini call failed: %s", exc)
    return None


def extract_comments_unified(pdf_bytes: bytes) -> dict[str, Any]:
    """Classify + extract. Result shape mirrors extract_referent_comments
    plus doc_type ("referent"/"meeting"/None when AI was unavailable)."""
    raw_text = extract_text(pdf_bytes)
    if len(raw_text.strip()) < _SCAN_MIN_CHARS:
        return {
            "doc_type": None,
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
    if len(raw_text) > _MAX_TEXT_CHARS:
        truncation_warning = (
            f"הקובץ מכיל {len(raw_text):,} תווים. רק 50,000 הראשונים נותחו. "
            "ייתכן שהערות מעמודים אחרונים חסרות."
        )

    ai = _call_gemini(raw_text)
    if ai is not None:
        result: dict[str, Any] = {
            "doc_type": ai["doc_type"],
            "comments": ai["comments"],
            "raw_text": raw_text,
            "used_ai": True,
        }
        if truncation_warning:
            result["truncation_warning"] = truncation_warning
        return result

    # No AI available - same editable catch-all row the legacy path used.
    result = {
        "doc_type": None,
        "comments": [{
            "discipline_key": "",
            "status": "",
            "topic_he": "",
            "action_he": raw_text.strip()[:4000],
            "confidence": "low",
        }],
        "raw_text": raw_text,
        "used_ai": False,
    }
    if truncation_warning:
        result["truncation_warning"] = truncation_warning
    return result
