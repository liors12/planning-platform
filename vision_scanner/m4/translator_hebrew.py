"""Flash-driven English→Hebrew translation for M2/M3 evidence reasoning.

Many M2/M3 findings emit reasoning text in English (e.g. "Page 27 shows the
mature trees appendix is missing"). The audit PDF target audience is Israeli
planning engineers who read Hebrew — English in the reasoning column looks
unfinished and breaks the document's professional voice.

This module:
  1. Detects whether a snippet is predominantly English (>30% Latin chars
     among the alphabetic-ish characters)
  2. Batches English snippets into a single Flash call (1M context comfortably
     fits 100+ short reasoning strings)
  3. Asks Flash to translate using the planning-Hebrew system prompt
  4. Returns the translated strings; passes Hebrew text through unchanged

Cost target: ~$0.05-0.10 for the full M4 v24.3 reasoning corpus
(~110 English snippets at avg 400 chars each ≈ 50K input + 60K output tokens).
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

import google.generativeai as genai
from google.api_core import exceptions as gax_exceptions

from ..config import GeminiKeyRotator


MODEL_NAME = "gemini-2.5-flash"
TRANSLATION_VERSION = "m5-translator-v1"
MAX_OUTPUT_TOKENS = 32768
MAX_JSON_RETRY = 2


_SYSTEM_PROMPT = """אתה מתרגם טכני המתמחה בתכנון ערים בישראל. תפקידך לתרגם נימוקי בדיקת ציות מאנגלית לעברית מקצועית, בשפתם של מתכנני ערים ומהנדסי ועדות מקומיות.

דרישות:
- השתמש במונחים מקצועיים: בינוי, פיתוח, תא שטח, תכליות, זכויות בנייה, חישובי שטחים, יעוד, גובה מותר, קווי בניין, תקנון מחייב, נספח, היתר בנייה, חוות דעת, תשריט, גובה מקסימלי, שטח עיקרי, שטחי שירות, יחס חניה, תקן חניה לאומי, מערכת ניקוז, השהיה, חלחול, זיקת הנאה, שלביות ביצוע, שצ"פ, חזית, מעטפת, ממ"ד
- אל תתרגם מילולית — נסח כפי שמתכנן בכיר היה מנסח חוות דעת
- שמור על טון דקלרטיבי-מקצועי, לא דיבורי
- שמר ציטוטי מקור (מספרי עמודים, ציטוטי תקנון) ללא שינוי
- תוצאה: עברית בלבד. ללא הקדמה, ללא הסבר, רק התרגום
"""


_LATIN_RE = re.compile(r"[A-Za-z]")
_HEBREW_RE = re.compile(r"[֐-׿]")
_ALPHA_RE = re.compile(r"[A-Za-z֐-׿]")


def is_predominantly_english(text: str, threshold: float = 0.30) -> bool:
    """Heuristic: text counts as English if Latin chars are >threshold of
    alphabetic-ish characters AND there are at least 4 Latin chars (avoids
    flagging Hebrew text with stray English tokens like 'DWG' as English)."""
    if not text:
        return False
    latin = len(_LATIN_RE.findall(text))
    hebrew = len(_HEBREW_RE.findall(text))
    alpha = len(_ALPHA_RE.findall(text))
    if alpha == 0:
        return False
    if latin < 4:
        return False
    return (latin / alpha) >= threshold


_MAX_DEADLINE_RETRIES = 2  # split batch in half on each DeadlineExceeded
_MIN_BATCH_SIZE_FOR_SPLIT = 2  # don't split below this


def _call_flash_translate_one_batch(
    rotator: GeminiKeyRotator,
    snippets: List[str],
) -> List[str]:
    """Single Flash call for a batch of snippets. Raises on irrecoverable error."""
    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(snippets))
    user_text = (
        "להלן רשימה ממוספרת של נימוקים באנגלית. החזר את כל הרשימה כ-JSON "
        "במבנה {\"translations\": [\"<מספר 1 בעברית>\", \"<מספר 2 בעברית>\", ...]}. "
        "שמור על אותו סדר ועל אותו מספר פריטים בדיוק.\n\n"
        + numbered
    )
    schema = {
        "type": "object",
        "properties": {
            "translations": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["translations"],
    }

    attempts = 0
    json_failures = 0
    while True:
        attempts += 1
        genai.configure(api_key=rotator.current())
        model = genai.GenerativeModel(MODEL_NAME, system_instruction=_SYSTEM_PROMPT)
        try:
            response = model.generate_content(
                user_text,
                generation_config={
                    "response_mime_type": "application/json",
                    "response_schema": schema,
                    "temperature": 0.0,
                    "max_output_tokens": MAX_OUTPUT_TOKENS,
                },
            )
        except (gax_exceptions.ResourceExhausted,
                gax_exceptions.TooManyRequests) as exc:
            next_key = rotator.rotate()
            if next_key is None:
                raise RuntimeError(
                    f"[m5-translator] all Gemini API keys hit quota: {exc}"
                ) from exc
            print(f"[m5-translator: RETRY #{attempts}] 429, rotating key", flush=True)
            continue

        payload = response.text
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            json_failures += 1
            if json_failures <= MAX_JSON_RETRY:
                print(
                    f"[m5-translator: RETRY #{json_failures} json] {exc}",
                    flush=True,
                )
                continue
            raise RuntimeError(
                f"[m5-translator] non-JSON output after {json_failures} attempts:\n"
                f"{payload[:600]}"
            ) from exc

        translations = data.get("translations") or []
        if len(translations) != len(snippets):
            json_failures += 1
            if json_failures <= MAX_JSON_RETRY:
                print(
                    f"[m5-translator: RETRY #{json_failures}] count mismatch: "
                    f"expected {len(snippets)}, got {len(translations)}",
                    flush=True,
                )
                continue
            raise RuntimeError(
                f"[m5-translator] count mismatch persists: "
                f"expected {len(snippets)}, got {len(translations)}"
            )
        return [str(t) for t in translations]


def _call_flash_translate(
    rotator: GeminiKeyRotator,
    snippets: List[str],
    *,
    deadline_split_depth: int = 0,
) -> List[str]:
    """Resilient batch translator.

    On DeadlineExceeded (504) — a Flash latency hiccup, not a workload issue —
    split the batch in half and recurse. Up to _MAX_DEADLINE_RETRIES splits.
    Final fallback: return originals (English) for snippets that can't be
    translated, with a `[translation_failed]` marker so the auditor sees what
    happened rather than silently shipping English.
    """
    try:
        return _call_flash_translate_one_batch(rotator, snippets)
    except gax_exceptions.DeadlineExceeded as exc:
        print(f"[m5-translator] DeadlineExceeded on batch of {len(snippets)} "
              f"(depth={deadline_split_depth}): {exc}", flush=True)
        if (deadline_split_depth >= _MAX_DEADLINE_RETRIES
                or len(snippets) < _MIN_BATCH_SIZE_FOR_SPLIT):
            print(f"[m5-translator] fallback — returning originals with marker", flush=True)
            return [f"[translation_failed] {s}" for s in snippets]
        mid = len(snippets) // 2
        print(f"[m5-translator] splitting batch {len(snippets)} → "
              f"{mid} + {len(snippets) - mid}", flush=True)
        left = _call_flash_translate(
            rotator, snippets[:mid], deadline_split_depth=deadline_split_depth + 1
        )
        right = _call_flash_translate(
            rotator, snippets[mid:], deadline_split_depth=deadline_split_depth + 1
        )
        return left + right


def translate_batch(snippets: List[str]) -> List[str]:
    """Translate a list of English snippets via one Flash call."""
    if not snippets:
        return []
    rotator = GeminiKeyRotator()
    if not rotator.has_keys:
        raise RuntimeError(
            "[m5-translator] No GEMINI_API_KEY env vars set."
        )
    return _call_flash_translate(rotator, snippets)


def build_translation_map(texts: List[str]) -> Dict[str, str]:
    """For a list of texts, return {original_english: translated_hebrew} for
    the English-predominant ones. Hebrew texts are skipped (not in the map).

    Deduplicates: identical English strings are translated once.
    """
    english_unique = list({t for t in texts if t and is_predominantly_english(t)})
    if not english_unique:
        return {}
    translations = translate_batch(english_unique)
    return dict(zip(english_unique, translations))


def translate_to_planning_hebrew(text: str) -> str:
    """Single-snippet convenience: translate if English, passthrough if Hebrew."""
    if not text or not is_predominantly_english(text):
        return text
    return translate_batch([text])[0]
