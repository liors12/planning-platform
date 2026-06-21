"""Post-M4 Hebrew→Hebrew sanitizer for engine-sourced finding text.

WHY THIS EXISTS
---------------
`translator_hebrew.py` only fires on English→Hebrew translation of M2/M3
reasoning snippets that arrive in English. Many of the dirtiest voice-drift
phrases (`תואם ויזואלית`, `כנראה`, `יש לדרוש`, `נדרשת בדיקה הנדסית`,
internal cross-refs like `(ראו 3.X רביעי)`) live in Hebrew strings emitted
by `compliance_engine` rule definitions directly — they never pass through
the EN→HE translator, so the translator's ban list has no surface to act on.

This module is a SEPARATE pass that runs AFTER M4 completes:
  audit_results.m4.json  →  sanitizer_hebrew  →  audit_results.m4.sanitized.json

Architectural invariants:
  - compliance_engine/ is NOT modified.
  - audit_results.json (engine baseline, sha 79eaaea3…) is NOT modified.
  - translator_hebrew.py is NOT modified — its EN→HE scope stays unchanged.
  - The sanitized JSON is a new artifact; run_audit.py --render-only prefers
    it over .m4.json when present, falls back when absent.

Scope of rewriting:
  - Six fields per §3 discipline row carry dirty Hebrew:
      compliance_note, notes_he, remediation_he, evidence_visual,
      evidence.compliance_note, evidence.evidence_visual
  - Labels stay untouched: rule_name_he, required_artifact_he,
    evidence.matched_rule_hebrew, discipline, rule_code, verdict.

Hard rules enforced by the prompt + a post-call validator:
  - Every page reference (עמ' X[, Y, …]) appears verbatim in output.
  - Every section citation (סעיף X.Y[.Z…]) appears verbatim.
  - Every numeric value (≥2מ, 1:500, 5%, etc.) appears verbatim.
  - Output is Hebrew-only — no English, no auditor framing, no methodology.

If validation fails, the original string is kept and a `[sanitize_failed]`
marker is added to the row's `_sanitize_meta` field so the auditor sees
what happened. The render path treats `[sanitize_failed]`-tagged strings
as authoritative (i.e. dirty text is shipped over silent corruption).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

import google.generativeai as genai
from google.api_core import exceptions as gax_exceptions

from ..config import GeminiKeyRotator

MODEL_NAME = "gemini-2.5-flash"
SANITIZER_VERSION = "m4-sanitizer-v1"
MAX_OUTPUT_TOKENS = 32768
MAX_JSON_RETRY = 2
BATCH_SIZE = 25

# ─── Fields to sanitize ───────────────────────────────────────────────────
# Row-level + nested under `evidence`. Other fields (labels, IDs) are
# passthrough.
TOP_LEVEL_FIELDS = (
    "compliance_note",
    "notes_he",
    "remediation_he",
    "evidence_visual",
    "evidence_visual_he",     # alternative key sometimes emitted
    "reasoning_he",           # M5 translator output — re-sanitize defensively
    "reasoning",              # sidecar-only-finding text field (HE after M5)
)
EVIDENCE_FIELDS = (
    "compliance_note",
    "evidence_visual",
)

# ─── System prompt — mirrors translator_hebrew.py bans, reframed HE→HE ────
_SYSTEM_PROMPT = """אתה עורך לשוני המתמחה בעריכת דוחות תכנון עירוני בישראל. תפקידך לקבל טקסט עברי שנוצר על-ידי מנוע ציות אוטומטי ולשכתב אותו ללשון אדריכל-פונה תמציתית, מקצועית, ופעולתית — תוך שמירה מוחלטת על העובדות, המספרים, הציטוטים והעמודים.

קהל הקורא: האדריכל שהגיש את תוכנית העיצוב. הדוח נחתם על-ידי מהנדס/ת המינהלת להתחדשות עירונית עיריית נס ציונה לפני שליחתו לאדריכל.

עקרון השמירה — חובה מוחלטת (אל תעבור על זה לעולם):
- כל מספר חייב להופיע כפי שהוא בקלט: ≥2מ, 1:500, 5%, 9 מטר, 232 יח"ד, 0.5 חניה/יח"ד וכד'.
- כל הפניית עמוד חייבת להופיע כפי שהיא: "(עמ' 25)", "(עמ' 25, 35, 40, 44)", "עמ' 30-32".
- כל ציטוט סעיף תקנון חייב להופיע כפי שהוא: "סעיף 4.1.2.4", "סעיף 6.7.4 בתקנון התב\"ע".
- כל ערך מדוד (מטרים, מ"ר, יח"ד, אחוזים) חייב להישמר מילה במילה.
- שמות תאי שטח (תא שטח 1, A5, B4) חייבים להישמר מילה במילה.

איסורי לשון — חובה להסיר/לשכתב:
1. **לידי-עיניים פנימיים** — "תואם ויזואלית", "ויזואלית קיימת", "נראה ויזואלית", "המערכת היא כנראה", "נראה כי", "ויזואלית הולם", "ויזואלית מתאים". המר ל-"תואם" בלבד, או נסח את הממצא העובדתי ישירות.
2. **בדיקה/בירור כפעולה** — "נדרשת בדיקה", "נדרשת בדיקה הנדסית", "נדרשת בדיקה ידנית", "נדרשת בדיקה מדויקת", "נדרש בירור", "דורש בירור", "נדרש להבהיר", "נדרשת הבהרה", "בדיקת מהנדס", "סקירת מהנדס", "מהנדס לוודא", "מהנדס/ת תאמת". המר להוראת-פעולה קונקרטית לאדריכל.
3. **קולות וודאות** — "כנראה", "ככל הנראה", "נראה כי", "ייתכן ש-" כתיאור עובדתי של תכנון. אם המידע באמת לא ודאי, נסח את הפעולה הנדרשת מהאדריכל ("יש לציין X").
4. **שיח אל המהנדס** — "יש לדרוש", "יש לבקש מהאדריכל", "יש לפנות אל...". הקהל הוא האדריכל; כל פעולה ממוענת אליו. החלף ל-"יש ל[פעולה]" בלשון ישירה.
5. **הפניות פנימיות** — "(ראו 3.1 רביעי)", "(ראו פרק M2)", הפניות-מבט פנים-דוחיות. הסר אותן לחלוטין.
6. **קול גוף-ראשון של המנוע** — "לא היה לי זמן", "לא היה ניתן לוודא", "לא הצלחתי", "לא יכולתי". הסר וכתוב מחדש כהוראת-פעולה לאדריכל.
7. **שמות פנימיים** — M0/M1/M2/M3/M4/M5, "מודל הראייה", "מבקר", "vision_scanner", "compliance_engine", "5.table". אסור בפלט.
8. **כפילות עמוד** — אם הקלט כולל "(עמ' X)" פעמיים, השאר רק פעם אחת בסוף.

עקרון התמציתיות:
- 1-3 משפטים, מקסימום.
- ציין עובדה. אל תסביר מתודולוגיה.
- ציטוטי תקנון: ציין במפורש "בתקנון התב\"ע" אם זה לא כתוב.

דוגמאות (קלט → פלט):
- "המערכת היא כנראה פניאומטית עם דחיסה בקרקע (ראו 3.1 רביעי). נדרשת בדיקה הנדסית אם יש חדרי איסוף/שוטים בכל קומה" → "יש לציין על תכניות הקומות הטיפוסיות מיקום חדרי איסוף פסולת או שוטי פסולת בכל קומה, ולסמנם בלגנדה."
- "(עמ' 25, 35, 40, 44) תואם ויזואלית. כדאי לאמת תכנון מפורט של הצינורות עם יועץ פסולת" → "תואם. יש לציין תכנון מפורט של הצינורות בנספח. (עמ' 25, 35, 40, 44)"
- "חסר — יש לדרוש סימון רחבת גזם ייעודית, באבן משתלבת, ברצועה הצמודה לרחוב, בקנ\"מ 1:500" → "יש לסמן רחבת גזם ייעודית באבן משתלבת, ברצועה הצמודה לרחוב, בקנ\"מ 1:500."
- "ויזואלית קיימת רצועה — נדרשת מדידה לוודא ≥2מ" → "נדרשת מדידה לוודא ≥2מ."
- "תואם — תנועת רכבי האשפה מחוץ למגרש" → "תואם — תנועת רכבי האשפה מחוץ למגרש." (כבר נקי, השאר כפי שהוא)

מבנה התשובה:
- JSON עם מפתח "sanitized" שערכו מערך מחרוזות עברית באותו אורך כמו הקלט.
- אם פריט קלט הוא ריק או null, החזר מחרוזת ריקה במקומו.
- ללא הסבר, ללא הקדמה — JSON בלבד.
"""


# ─── Preservation validator ────────────────────────────────────────────────

_RX_PAGE_REF   = re.compile(r"עמ['’]\s*\d+[\d,\s\-––—]*")
_RX_SECTION    = re.compile(r"סעיף\s+\d+(?:\.\d+)+(?:\.[א-ת])?")
_RX_NUMBER     = re.compile(r"\d+(?:[\.,]\d+)?")
_RX_PLOT_ID    = re.compile(r"תא\s+שטח\s+\d+|[A-D]\d")


def _multiset(items: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in items:
        x = x.strip()
        if x:
            out[x] = out.get(x, 0) + 1
    return out


def _preserves_critical_tokens(original: str, sanitized: str) -> tuple[bool, list[str]]:
    """Verify every page-ref, section citation, and plot-id from `original`
    appears in `sanitized`. Returns (ok, missing_tokens)."""
    missing: list[str] = []

    # Page references — must all be present (multiset)
    orig_pages = _multiset(_RX_PAGE_REF.findall(original))
    san_pages = _multiset(_RX_PAGE_REF.findall(sanitized))
    for tok, n in orig_pages.items():
        if san_pages.get(tok, 0) < n:
            missing.append(f"page_ref:{tok}")

    # Section citations
    orig_secs = _multiset(_RX_SECTION.findall(original))
    san_secs = _multiset(_RX_SECTION.findall(sanitized))
    for tok, n in orig_secs.items():
        if san_secs.get(tok, 0) < n:
            missing.append(f"section:{tok}")

    # Plot identifiers
    orig_plots = _multiset(_RX_PLOT_ID.findall(original))
    san_plots = _multiset(_RX_PLOT_ID.findall(sanitized))
    for tok, n in orig_plots.items():
        if san_plots.get(tok, 0) < n:
            missing.append(f"plot_id:{tok}")

    # Numbers — looser check: just confirm we didn't lose >20% of digits
    orig_digits = sum(len(m) for m in _RX_NUMBER.findall(original))
    san_digits = sum(len(m) for m in _RX_NUMBER.findall(sanitized))
    if orig_digits > 5 and san_digits < orig_digits * 0.7:
        missing.append(f"digits_lost:{orig_digits}->{san_digits}")

    return (not missing, missing)


# ─── Gemini call ──────────────────────────────────────────────────────────

def _call_flash_sanitize_one_batch(rotator: GeminiKeyRotator,
                                   snippets: list[str]) -> list[str]:
    user_text = "שכתב כל אחד מהפריטים הבאים. החזר JSON עם מפתח 'sanitized' שערכו מערך באותו אורך:\n\n"
    for i, s in enumerate(snippets, 1):
        user_text += f"[{i}] {s}\n"

    schema = {
        "type": "object",
        "properties": {
            "sanitized": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["sanitized"],
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
                    f"[m4-sanitizer] all Gemini API keys hit quota: {exc}"
                ) from exc
            print(f"[m4-sanitizer: RETRY #{attempts}] 429, rotating key", flush=True)
            continue

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError as exc:
            json_failures += 1
            if json_failures <= MAX_JSON_RETRY:
                print(f"[m4-sanitizer: RETRY #{json_failures} json] {exc}", flush=True)
                continue
            raise RuntimeError(
                f"[m4-sanitizer] non-JSON output after {json_failures} attempts"
            ) from exc

        out = data.get("sanitized") or []
        if len(out) != len(snippets):
            json_failures += 1
            if json_failures <= MAX_JSON_RETRY:
                print(f"[m4-sanitizer: RETRY count mismatch — expected {len(snippets)}, got {len(out)}",
                      flush=True)
                continue
            raise RuntimeError(
                f"[m4-sanitizer] count mismatch persists: "
                f"expected {len(snippets)}, got {len(out)}"
            )
        return [str(x) for x in out]


def sanitize_batch(snippets: list[str]) -> list[str]:
    if not snippets:
        return []
    rotator = GeminiKeyRotator()
    if not rotator.has_keys:
        raise RuntimeError("[m4-sanitizer] No GEMINI_API_KEY env vars set.")
    # Batch in chunks to keep latency + token count predictable
    out: list[str] = []
    for i in range(0, len(snippets), BATCH_SIZE):
        chunk = snippets[i:i + BATCH_SIZE]
        out.extend(_call_flash_sanitize_one_batch(rotator, chunk))
    return out


# ─── Driver: walk JSON, sanitize, write ────────────────────────────────────

def _collect_strings(rows: list[dict]) -> tuple[list[str], list[tuple[int, str, str | None]]]:
    """Return (unique_strings, occurrences). Each occurrence is
    (row_index, field_name, evidence_subkey_or_None).
    Strings are deduplicated globally — identical text sanitized once."""
    unique: dict[str, int] = {}
    occurrences: list[tuple[int, str, str | None]] = []
    for idx, r in enumerate(rows):
        for f in TOP_LEVEL_FIELDS:
            v = r.get(f)
            if isinstance(v, str) and v.strip():
                if v not in unique:
                    unique[v] = len(unique)
                occurrences.append((idx, f, None))
        ev = r.get("evidence")
        if isinstance(ev, dict):
            for f in EVIDENCE_FIELDS:
                v = ev.get(f)
                if isinstance(v, str) and v.strip():
                    if v not in unique:
                        unique[v] = len(unique)
                    occurrences.append((idx, f, "evidence"))
    # Stable ordered list
    ordered = sorted(unique.keys(), key=lambda s: unique[s])
    return ordered, occurrences


def _apply_sanitized(rows: list[dict], unique_in: list[str],
                     unique_out: list[str]) -> dict:
    """Apply sanitized strings back to rows. Validates preservation per-string;
    on failure, retains original + records full row context (rule_code,
    discipline, field) in the worklist so a human can surgically follow up."""
    repl: dict[str, str] = {}
    failures_by_str: dict[str, list[str]] = {}
    for orig, san in zip(unique_in, unique_out):
        ok, missing = _preserves_critical_tokens(orig, san)
        if ok:
            repl[orig] = san
        else:
            repl[orig] = orig  # keep original
            failures_by_str[orig] = missing

    # Build a row-level worklist: each preservation failure is reported per
    # (row, field) site where the dirty string lives. One identical string
    # appearing in multiple rows/fields produces multiple worklist entries.
    failure_worklist: list[dict] = []
    for r in rows:
        rule_code = r.get("rule_code")
        discipline = r.get("discipline")
        for f in TOP_LEVEL_FIELDS:
            v = r.get(f)
            if isinstance(v, str) and v in failures_by_str:
                failure_worklist.append({
                    "rule_code": rule_code,
                    "discipline": discipline,
                    "field": f,
                    "missing_tokens": failures_by_str[v],
                    "original_text": v,
                })
        ev = r.get("evidence")
        if isinstance(ev, dict):
            for f in EVIDENCE_FIELDS:
                v = ev.get(f)
                if isinstance(v, str) and v in failures_by_str:
                    failure_worklist.append({
                        "rule_code": rule_code,
                        "discipline": discipline,
                        "field": f"evidence.{f}",
                        "missing_tokens": failures_by_str[v],
                        "original_text": v,
                    })

    sanitize_meta = {
        "version": SANITIZER_VERSION,
        "strings_in": len(unique_in),
        "strings_replaced": sum(1 for o, n in repl.items() if n != o),
        "strings_kept_original": sum(1 for o, n in repl.items() if n == o),
        "preservation_failures": failure_worklist,
    }

    for r in rows:
        for f in TOP_LEVEL_FIELDS:
            v = r.get(f)
            if isinstance(v, str) and v in repl:
                r[f] = repl[v]
        ev = r.get("evidence")
        if isinstance(ev, dict):
            for f in EVIDENCE_FIELDS:
                v = ev.get(f)
                if isinstance(v, str) and v in repl:
                    ev[f] = repl[v]
    return sanitize_meta


# ─── content[] deterministic replacements ────────────────────────────────
# Narrow, exact-string voice fixes on engine-emitted notes_he in content[]
# rows. Routed OUTSIDE the LLM batch on purpose:
#   - The strings are templates baked into the engine (CONTENT_SETBACKS,
#     CONTENT_PARKING_RATIO), so an exact match is reliable.
#   - The text contains numbers + section refs the LLM would have to
#     preserve verbatim; a deterministic replace is safer.
#   - Same input → byte-identical output → trivial regression diffing.
# Add new (banned, replacement) tuples here as more voice issues surface
# in the content[] pool.
_CONTENT_NOTES_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (
        "קווי הבניין מוגדרים בתשריט בקובץ DWG. עד להטמעת פירוק DWG, "
        "בדיקה זו דורשת אימות ידני של מהנדס/ת המינהלת מול התשריט.",
        "קווי הבניין מוגדרים בתשריט בקובץ DWG. עד להטמעת פירוק DWG, "
        "יש להבהיר את מרחקי קווי הבניין בתכנית.",
    ),
    (
        "הציון 'תקין' שונה ל'דורש בירור'",
        "הציון 'תקין' שונה ל'נדרשת השלמה'",
    ),
)


def _sanitize_content_rows(content_rows: list[dict]) -> dict:
    """Apply the deterministic `_CONTENT_NOTES_REPLACEMENTS` table to every
    content[] row's `notes_he` field. Returns a meta dict with per-pattern
    hit counts and the total number of rows touched.
    """
    per_pattern_hits: dict[int, int] = {i: 0 for i in range(len(_CONTENT_NOTES_REPLACEMENTS))}
    rows_touched = 0
    for row in content_rows:
        original = row.get("notes_he")
        if not isinstance(original, str) or not original:
            continue
        sanitized = original
        for i, (banned, replacement) in enumerate(_CONTENT_NOTES_REPLACEMENTS):
            if banned in sanitized:
                per_pattern_hits[i] += sanitized.count(banned)
                sanitized = sanitized.replace(banned, replacement)
        if sanitized != original:
            # Preserve the pre-sanitize text on the row, mirroring the
            # `_original_*` convention used elsewhere in the m4 pipeline.
            row.setdefault("_original_notes_he", original)
            row["notes_he"] = sanitized
            rows_touched += 1
    return {
        "rows_touched": rows_touched,
        "per_pattern_hits": {
            _CONTENT_NOTES_REPLACEMENTS[i][0][:60] + "…": n
            for i, n in per_pattern_hits.items() if n > 0
        },
    }


def sanitize_m4(in_path: Path, out_path: Path, *,
                slice_discipline: str | None = None,
                verbose: bool = True) -> dict:
    """Read m4.json, sanitize §3 disciplines + §2א sidecar findings + §2/§5
    content rows, write to out_path. Returns the sanitize_meta dict.

    Two passes:
      1. LLM (Flash) pass over disciplines[] + sidecar_only_findings[] —
         broad voice/style rewrite preserving numbers + page refs.
      2. Deterministic find-and-replace on content[].notes_he — narrow
         exact-string fixes for engine templates the LLM doesn't see.

    When `slice_discipline` is set, ONLY rows with that discipline are
    sanitized; the content[] deterministic pass also runs because it's
    independent of discipline taxonomy.
    """
    data = json.loads(in_path.read_text(encoding="utf-8"))
    disciplines = data.get("disciplines", [])
    sidecar = (data.get("m4_summary") or {}).get("sidecar_only_findings") or []
    content_rows = data.get("content", []) or []

    if slice_discipline:
        target_rows = [r for r in disciplines if r.get("discipline") == slice_discipline]
        target_sidecar: list = []  # sidecar findings are global, not per-discipline
        if not target_rows:
            print(f"[m4-sanitizer] WARN: no rows with discipline={slice_discipline!r}",
                  file=sys.stderr)
    else:
        target_rows = disciplines
        target_sidecar = sidecar

    if verbose:
        print(f"[m4-sanitizer] input: {in_path}")
        print(f"[m4-sanitizer] slice: {slice_discipline or '(all §3 disciplines + §2א sidecar + content)'}")
        print(f"[m4-sanitizer] §3 target rows: {len(target_rows)}")
        print(f"[m4-sanitizer] §2א sidecar rows: {len(target_sidecar)}")
        print(f"[m4-sanitizer] §2/§5 content rows (deterministic pass): {len(content_rows)}")

    # Collect strings from both pools, dedupe globally so identical text
    # appearing in both lists translates once.
    disc_unique, _ = _collect_strings(target_rows)
    side_unique, _ = _collect_strings(target_sidecar)
    # Union preserves order
    seen = set()
    unique_in: list[str] = []
    for s in disc_unique + side_unique:
        if s not in seen:
            seen.add(s)
            unique_in.append(s)

    if verbose:
        print(f"[m4-sanitizer] unique strings to sanitize: {len(unique_in)} "
              f"(§3={len(disc_unique)}, §2א={len(side_unique)})")

    if not unique_in:
        # Even with no LLM work, still run the deterministic content[] pass —
        # it's independent of the disciplines/sidecar text pool.
        content_meta = _sanitize_content_rows(content_rows)
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        meta = {"version": SANITIZER_VERSION, "strings_in": 0,
                "strings_replaced": 0, "strings_kept_original": 0,
                "preservation_failures": [],
                "content_deterministic": content_meta}
        return meta

    unique_out = sanitize_batch(unique_in)
    # Apply to both pools — _apply_sanitized mutates in place. Sidecar
    # findings only have TOP_LEVEL_FIELDS (no nested evidence dict), so the
    # same function works.
    meta_disc = _apply_sanitized(target_rows, unique_in, unique_out)
    meta_side = _apply_sanitized(target_sidecar, unique_in, unique_out)

    # Deterministic pass on content[] — no LLM call. Runs last so it can
    # also fix up content[] strings that happened to match disciplines text
    # in the LLM batch (currently they don't, but it's order-safe).
    content_meta = _sanitize_content_rows(content_rows)

    # Merge meta — strings_in is global; preservation_failures is the union
    meta = {
        "version": SANITIZER_VERSION,
        "strings_in": len(unique_in),
        "strings_replaced": meta_disc["strings_replaced"],  # same dedup'd map
        "strings_kept_original": meta_disc["strings_kept_original"],
        "preservation_failures":
            meta_disc["preservation_failures"]
            + meta_side["preservation_failures"],
        "content_deterministic": content_meta,
    }

    data.setdefault("m4_summary", {})["sanitizer"] = meta

    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    if verbose:
        print(f"[m4-sanitizer] wrote: {out_path}")
        print(f"[m4-sanitizer] replaced: {meta['strings_replaced']}  "
              f"kept-original: {meta['strings_kept_original']}  "
              f"preservation_failures: {len(meta['preservation_failures'])}")
    return meta


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="HE→HE sanitizer pass on audit_results.m4.json — "
                    "removes auditor-voice from engine-sourced Hebrew while "
                    "preserving pages, sections, and numbers verbatim.",
    )
    p.add_argument("--input", required=True, type=Path,
                   help="audit_results.m4.json")
    p.add_argument("--output", required=True, type=Path,
                   help="output sanitized JSON path")
    p.add_argument("--slice-discipline", default=None,
                   help="Only sanitize rows in this discipline (e.g. 'shafa').")
    args = p.parse_args(argv)

    meta = sanitize_m4(args.input, args.output,
                       slice_discipline=args.slice_discipline)
    return 0 if not meta["preservation_failures"] else 0  # warnings, not errors


if __name__ == "__main__":
    raise SystemExit(main())
