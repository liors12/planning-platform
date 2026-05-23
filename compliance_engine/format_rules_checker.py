"""
Submission format rules checker.

Determinism contract: same PDF + same rules file -> byte-identical verdict set.
No LLM calls anywhere in this module. All checks are pure Python over PDF bytes.
Manual-review rules deterministically return verdict="requires_review".
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

import fitz  # PyMuPDF
import pdfplumber


HEBREW_RE = re.compile(r"[֐-׿]")

VERDICT_PASS = "pass"
VERDICT_PASS_WITH_NOTE = "pass_with_note"
VERDICT_FAIL = "fail"
VERDICT_FAIL_BORDERLINE = "fail_borderline"
VERDICT_UNEVALUABLE = "unevaluable"
VERDICT_REQUIRES_REVIEW = "requires_review"

FAILURE_NONE = "NONE"
FAILURE_EXTRACTION = "EXTRACTION_FAILURE"
FAILURE_ENGINE = "ENGINE_ERROR"


def check_submission_format(
    pdf_path: Path,
    rules_path: Path = Path("submission_format_rules.json"),
    project_overrides: list[str] | None = None,
) -> list[dict]:
    """
    Run all format rules from rules_path against pdf_path.

    Returns list of dicts: rule_code, verdict, failure_mode, confidence, evidence, notes_he.
    project_overrides: list of rule_codes to skip (returns no result for them).
    Results are sorted by rule_code so the output is deterministic across runs.
    """
    pdf_path = Path(pdf_path)
    rules_path = Path(rules_path)
    overrides = set(project_overrides or [])

    with rules_path.open("r", encoding="utf-8") as f:
        rules_data = json.load(f)

    extraction = _extract_pdf_once(pdf_path)

    results: list[dict] = []
    for rule in rules_data["rules"]:
        rule_code = rule["rule_code"]
        if rule_code in overrides:
            continue

        check_method = rule["check_method"]
        handler = _HANDLERS.get(check_method)
        if handler is None:
            results.append(_engine_error(rule, f"unknown check_method: {check_method}"))
            continue

        try:
            results.append(handler(extraction, rule))
        except Exception as exc:  # noqa: BLE001
            results.append(_engine_error(rule, f"{type(exc).__name__}: {exc}"))

    results.sort(key=lambda r: r["rule_code"])
    return results


# ---------------------------------------------------------------------------
# PDF extraction (run once per file; deterministic given the same input bytes)
# ---------------------------------------------------------------------------

def _extract_pdf_once(pdf_path: Path) -> dict:
    """Pull all data we need from the PDF in a single pass.

    Returned dict shape:
      {
        "pdf_path": Path,
        "page_count": int,
        "pages": [
          {"index": 0, "page_number": 1, "width_pt": float, "height_pt": float,
           "fonts": [str], "text": str, "images": [{"area_ratio": float, ...}],
           "footer_text": str, "tables": [[[cell, ...], ...], ...]},
          ...
        ],
      }
    """
    pages: list[dict] = []

    doc = fitz.open(str(pdf_path))
    try:
        for i, page in enumerate(doc):
            rect = page.rect
            width_pt = float(rect.width)
            height_pt = float(rect.height)
            page_area = width_pt * height_pt if width_pt and height_pt else 0.0

            try:
                fonts = sorted({f[3] for f in page.get_fonts(full=True) if len(f) >= 4 and f[3]})
            except Exception:
                fonts = []

            try:
                images_raw = page.get_images(full=True)
            except Exception:
                images_raw = []
            image_entries: list[dict] = []
            for img in images_raw:
                xref = img[0]
                try:
                    bboxes = page.get_image_rects(xref)
                except Exception:
                    bboxes = []
                for bbox in bboxes:
                    img_area = float(bbox.width) * float(bbox.height)
                    ratio = (img_area / page_area) if page_area else 0.0
                    image_entries.append({"area_ratio": ratio})

            try:
                text = page.get_text("text") or ""
            except Exception:
                text = ""

            footer_text = _slice_footer_text(page, height_pt)

            pages.append({
                "index": i,
                "page_number": i + 1,
                "width_pt": width_pt,
                "height_pt": height_pt,
                "fonts": fonts,
                "text": text,
                "images": image_entries,
                "footer_text": footer_text,
                "tables": [],  # filled by pdfplumber pass below
            })
    finally:
        doc.close()

    # Tables via pdfplumber (deterministic given pinned library version)
    try:
        with pdfplumber.open(str(pdf_path)) as pp:
            for i, p in enumerate(pp.pages):
                if i >= len(pages):
                    break
                try:
                    tables = p.extract_tables() or []
                except Exception:
                    tables = []
                pages[i]["tables"] = tables
    except Exception:
        pass

    return {"pdf_path": pdf_path, "page_count": len(pages), "pages": pages}


def _slice_footer_text(page: "fitz.Page", height_pt: float) -> str:
    """Return text whose vertical center is in the bottom 10% of the page."""
    if not height_pt:
        return ""
    cutoff = height_pt * 0.9
    try:
        blocks = page.get_text("blocks") or []
    except Exception:
        return ""
    parts: list[str] = []
    for block in blocks:
        if len(block) < 5:
            continue
        y0, y1 = float(block[1]), float(block[3])
        if (y0 + y1) / 2.0 >= cutoff:
            text = block[4]
            if isinstance(text, str) and text.strip():
                parts.append(text)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------

def _resolve_pages(extraction: dict, scope: str | None) -> list[dict]:
    pages = extraction["pages"]
    if not scope or scope == "all_pages":
        return pages
    if scope == "page_1_only":
        return pages[:1]
    if scope == "all_pages_except_cover":
        return pages[1:]
    if scope == "all_pages_with_text":
        return [p for p in pages if p["text"].strip()]
    if scope == "all_text_in_document":
        return pages
    if scope == "pages_1_to_5":
        return pages[:5]
    if scope == "team_page":
        for p in pages[:5]:
            if "צוות הפרויקט" in p["text"]:
                return [p]
        return []
    return pages


# ---------------------------------------------------------------------------
# Result builders
# ---------------------------------------------------------------------------

def _result(
    rule: dict,
    verdict: str,
    *,
    check_method: str,
    extracted_values: dict | None = None,
    pages_checked: list[int] | None = None,
    failure_mode: str = FAILURE_NONE,
) -> dict:
    return {
        "rule_code": rule["rule_code"],
        "rule_name_he": rule.get("rule_name_he", "") or "",
        "verdict": verdict,
        "failure_mode": failure_mode,
        "confidence": "HIGH",
        "evidence": {
            "check_method": check_method,
            "extracted_values": extracted_values or {},
            "pages_checked": pages_checked or [],
        },
        "notes_he": rule.get("description_he", ""),
    }


def _engine_error(rule: dict, message: str) -> dict:
    return {
        "rule_code": rule["rule_code"],
        "rule_name_he": rule.get("rule_name_he", "") or "",
        "verdict": VERDICT_UNEVALUABLE,
        "failure_mode": FAILURE_ENGINE,
        "confidence": "HIGH",
        "evidence": {
            "check_method": rule.get("check_method", "unknown"),
            "extracted_values": {"error": message},
            "pages_checked": [],
        },
        "notes_he": rule.get("description_he", ""),
    }


# ---------------------------------------------------------------------------
# 7 check-method handlers — exactly the set listed in submission_format_rules.json
# ---------------------------------------------------------------------------

def check_pdf_metadata(extraction: dict, rule: dict) -> dict:
    """Page size and font-name checks driven by check_spec.

    Page-size mode requires target_width_pt and target_height_pt; font mode
    requires allowed_fonts.
    """
    spec = rule["check_spec"]
    pages = _resolve_pages(extraction, spec.get("scope"))
    if not pages:
        return _result(
            rule,
            VERDICT_UNEVALUABLE,
            check_method="pdf_metadata",
            failure_mode=FAILURE_EXTRACTION,
            extracted_values={"reason": "no pages in scope"},
        )

    if "target_width_pt" in spec and "target_height_pt" in spec:
        target_w = float(spec["target_width_pt"])
        target_h = float(spec["target_height_pt"])
        tol = float(spec.get("tolerance_pt", 0))
        bad: list[dict] = []
        for p in pages:
            if abs(p["width_pt"] - target_w) > tol or abs(p["height_pt"] - target_h) > tol:
                bad.append({
                    "page_number": p["page_number"],
                    "width_pt": round(p["width_pt"], 2),
                    "height_pt": round(p["height_pt"], 2),
                })
        verdict = rule.get("verdict_on_pass", VERDICT_PASS) if not bad else rule.get("verdict_on_fail", VERDICT_FAIL)
        return _result(
            rule,
            verdict,
            check_method="pdf_metadata",
            extracted_values={
                "target_width_pt": target_w,
                "target_height_pt": target_h,
                "tolerance_pt": tol,
                "non_conforming_pages": bad,
            },
            pages_checked=[p["page_number"] for p in pages],
        )

    if "allowed_fonts" in spec:
        allowed = [a.lower() for a in spec["allowed_fonts"]]
        observed: set[str] = set()
        for p in pages:
            observed.update(p["fonts"])

        if not observed:
            return _result(
                rule,
                rule.get("verdict_when_indeterminate", VERDICT_REQUIRES_REVIEW),
                check_method="pdf_metadata",
                extracted_values={"reason": "no embedded font names extractable"},
                pages_checked=[p["page_number"] for p in pages],
            )

        unrecognized = sorted(
            font for font in observed
            if not any(allow in font.lower() for allow in allowed)
        )
        if not unrecognized:
            verdict = rule.get("verdict_on_pass", VERDICT_PASS)
        else:
            verdict = rule.get("verdict_on_fail", VERDICT_PASS_WITH_NOTE)
        return _result(
            rule,
            verdict,
            check_method="pdf_metadata",
            extracted_values={
                "fonts_observed": sorted(observed),
                "unrecognized_fonts": unrecognized,
            },
            pages_checked=[p["page_number"] for p in pages],
        )

    return _engine_error(rule, "pdf_metadata: spec missing both target_*_pt and allowed_fonts")


def check_text_extraction(extraction: dict, rule: dict) -> dict:
    """Text presence checks. Honors scope and several logic variants used in the rules file."""
    spec = rule["check_spec"]
    pages = _resolve_pages(extraction, spec.get("scope"))
    if not pages:
        return _result(
            rule,
            VERDICT_UNEVALUABLE,
            check_method="text_extraction",
            failure_mode=FAILURE_EXTRACTION,
            extracted_values={"reason": "no pages in scope"},
        )
    pages_checked = [p["page_number"] for p in pages]

    # RTL / Hebrew block ratio. Honors optional block_filter + threshold.
    test_str = spec.get("test", "")
    if test_str.startswith("extracted_text_starts_with_hebrew") or test_str.startswith("filtered_blocks_starting_with_hebrew"):
        block_filter = spec.get("block_filter") or {}
        min_chars = int(block_filter.get("min_length_chars", 0))
        require_hebrew_letter = bool(block_filter.get("must_contain_hebrew_letter", False))
        threshold = float(spec.get("threshold", 0.80))

        eligible = 0
        hebrew_blocks = 0
        for p in pages:
            for line in p["text"].splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if min_chars and len(stripped) < min_chars:
                    continue
                if require_hebrew_letter and not HEBREW_RE.search(stripped):
                    continue
                eligible += 1
                head = next((ch for ch in stripped if ch.isalpha()), "")
                if head and HEBREW_RE.match(head):
                    hebrew_blocks += 1

        ratio = (hebrew_blocks / eligible) if eligible else 0.0
        if eligible == 0:
            verdict = VERDICT_UNEVALUABLE
            failure = FAILURE_EXTRACTION
        elif ratio >= threshold:
            verdict = rule.get("verdict_on_pass", VERDICT_PASS)
            failure = FAILURE_NONE
        else:
            verdict = rule.get("verdict_on_fail", VERDICT_FAIL)
            failure = FAILURE_NONE
        return _result(
            rule,
            verdict,
            check_method="text_extraction",
            extracted_values={
                "hebrew_block_ratio": round(ratio, 3),
                "blocks_examined": eligible,
                "threshold": threshold,
                "block_filter": block_filter,
            },
            pages_checked=pages_checked,
            failure_mode=failure,
        )

    # Disciplines list (count distinct matches across the team page)
    if "required_disciplines" in spec:
        required = list(spec["required_disciplines"])
        minimum = int(spec.get("minimum_matches", len(required)))
        text_blob = "\n".join(p["text"] for p in pages)
        matched = [d for d in required if d in text_blob]
        if len(matched) >= minimum:
            verdict = rule.get("verdict_on_pass", VERDICT_PASS)
        else:
            verdict = rule.get("verdict_on_fail", VERDICT_FAIL)
        return _result(
            rule,
            verdict,
            check_method="text_extraction",
            extracted_values={
                "disciplines_found": matched,
                "minimum_required": minimum,
                "found_count": len(matched),
            },
            pages_checked=pages_checked,
        )

    # Distinct-terms-per-page (table-keyword detection without table_detection)
    if "required_terms" in spec and "minimum_distinct_terms_on_same_page" in spec:
        terms = list(spec["required_terms"])
        minimum = int(spec["minimum_distinct_terms_on_same_page"])
        best_page = None
        best_terms: list[str] = []
        per_page_hits: dict[int, list[str]] = {}
        for p in pages:
            page_text = p["text"]
            found = [t for t in terms if t in page_text]
            if found:
                per_page_hits[p["page_number"]] = found
            if len(found) > len(best_terms):
                best_page = p["page_number"]
                best_terms = found
            if len(found) >= minimum:
                return _result(
                    rule,
                    rule.get("verdict_on_pass", VERDICT_PASS),
                    check_method="text_extraction",
                    extracted_values={
                        "matched_page": p["page_number"],
                        "matched_terms": found,
                        "minimum_required": minimum,
                    },
                    pages_checked=pages_checked,
                )
        return _result(
            rule,
            rule.get("verdict_on_fail", VERDICT_REQUIRES_REVIEW),
            check_method="text_extraction",
            extracted_values={
                "best_page": best_page,
                "best_terms_found": best_terms,
                "minimum_required": minimum,
                "per_page_hits": per_page_hits,
            },
            pages_checked=pages_checked,
        )

    # Cover signature table — both required_terms and additional_required_terms must be present
    if "required_terms" in spec and "additional_required_terms" in spec:
        text_blob = "\n".join(p["text"] for p in pages)
        all_terms = list(spec["required_terms"]) + list(spec["additional_required_terms"])
        missing = [t for t in all_terms if t not in text_blob]
        if not missing:
            verdict = rule.get("verdict_on_pass", VERDICT_PASS)
        else:
            verdict = rule.get("verdict_on_fail", VERDICT_FAIL)
        return _result(
            rule,
            verdict,
            check_method="text_extraction",
            extracted_values={"missing_terms": missing, "all_required_terms": all_terms},
            pages_checked=pages_checked,
        )

    # Project name appears on every page — derive a stable banner/footer token
    # from page 1 (any pipe-delimited or sentence-like segment) and verify it
    # appears on every other page. Deterministic given the same PDF.
    if spec.get("required_text", "").startswith("project_name_from_cover_page"):
        all_pages = extraction["pages"]
        if not all_pages:
            return _result(
                rule,
                VERDICT_UNEVALUABLE,
                check_method="text_extraction",
                failure_mode=FAILURE_EXTRACTION,
                extracted_values={"reason": "PDF has no pages"},
            )
        # Source pool: page 1 footer band (bottom 10%) + page 1 top band (top 10%)
        # — covers both bottom-footer designs and top-banner designs.
        cover_text_pool = all_pages[0]["footer_text"] + "\n" + all_pages[0]["text"]
        candidate_tokens = [
            t.strip() for t in re.split(r"[|·•\n\r\t]", cover_text_pool)
            if t.strip()
        ]
        candidate_tokens = [
            t for t in candidate_tokens
            if not re.fullmatch(r"\|?\s*\d+\s*\|?", t) and not t.isdigit() and len(t) >= 4
        ]
        if not candidate_tokens:
            return _result(
                rule,
                VERDICT_UNEVALUABLE,
                check_method="text_extraction",
                failure_mode=FAILURE_EXTRACTION,
                extracted_values={"reason": "no project-name token derivable from cover page text"},
                pages_checked=[1],
            )
        # The "project name token" is the candidate that appears on the most
        # other pages. Ties broken by length, then by sort order.
        check_pages = pages  # already scoped to all_pages_except_cover
        best_token = ""
        best_pages_with: list[int] = []
        for token in sorted(set(candidate_tokens), key=lambda t: (-len(t), t)):
            pages_with = [p["page_number"] for p in check_pages if token in p["text"]]
            if len(pages_with) > len(best_pages_with):
                best_token = token
                best_pages_with = pages_with
        if not best_token:
            return _result(
                rule,
                rule.get("verdict_on_fail", VERDICT_PASS_WITH_NOTE),
                check_method="text_extraction",
                extracted_values={
                    "candidates_examined": len(set(candidate_tokens)),
                    "missing_in_pages": [p["page_number"] for p in check_pages],
                },
                pages_checked=pages_checked,
            )
        missing_pages = [p["page_number"] for p in check_pages if p["page_number"] not in best_pages_with]
        if not missing_pages:
            verdict = rule.get("verdict_on_pass", VERDICT_PASS)
        else:
            verdict = rule.get("verdict_on_fail", VERDICT_PASS_WITH_NOTE)
        return _result(
            rule,
            verdict,
            check_method="text_extraction",
            extracted_values={
                "project_token": best_token,
                "pages_with_token": len(best_pages_with),
                "missing_in_pages": missing_pages,
            },
            pages_checked=pages_checked,
        )

    # Generic required_text_patterns flow
    patterns = list(spec.get("required_text_patterns", []))
    if not patterns:
        return _engine_error(rule, "text_extraction: spec has no required_text_patterns / disciplines / terms")

    logic = spec.get("logic", "at_least_one_match")
    minimum_matches = int(spec.get("minimum_matches", 0))
    minimum_distinct_pages = int(spec.get("minimum_matches_in_distinct_pages", 0))

    # Per-page hit map
    matches: dict[str, list[int]] = {pat: [] for pat in patterns}
    for p in pages:
        for pat in patterns:
            if pat in p["text"]:
                matches[pat].append(p["page_number"])

    total_hits = sum(len(v) for v in matches.values())
    distinct_hit_pages = sorted({pg for pgs in matches.values() for pg in pgs})

    passed: bool
    if minimum_distinct_pages:
        passed = len(distinct_hit_pages) >= minimum_distinct_pages
    elif minimum_matches:
        passed = total_hits >= minimum_matches
    elif logic in ("at_least_one_match", "at_least_one_page_contains_pattern"):
        passed = total_hits > 0
    elif logic == "all_terms_must_appear_in_page_1_text":
        passed = all(matches[pat] for pat in patterns)
    else:
        passed = total_hits > 0

    verdict = rule.get("verdict_on_pass", VERDICT_PASS) if passed else rule.get("verdict_on_fail", VERDICT_FAIL)
    return _result(
        rule,
        verdict,
        check_method="text_extraction",
        extracted_values={
            "matches_per_pattern": {k: v for k, v in matches.items()},
            "total_hits": total_hits,
            "distinct_hit_pages": distinct_hit_pages,
        },
        pages_checked=pages_checked,
    )


def check_regex_pattern(extraction: dict, rule: dict) -> dict:
    spec = rule["check_spec"]
    pages = _resolve_pages(extraction, spec.get("scope"))
    if not pages:
        return _result(
            rule,
            VERDICT_UNEVALUABLE,
            check_method="regex_pattern",
            failure_mode=FAILURE_EXTRACTION,
            extracted_values={"reason": "no pages in scope"},
        )
    pages_checked = [p["page_number"] for p in pages]

    raw_patterns: list[str] = []
    if "regex_pattern" in spec:
        raw_patterns.append(spec["regex_pattern"])
    if "regex_patterns" in spec:
        raw_patterns.extend(spec["regex_patterns"])
    if not raw_patterns:
        return _engine_error(rule, "regex_pattern: spec has no regex_pattern(s)")

    compiled = [re.compile(p) for p in raw_patterns]

    # Footer-region scoping (only certain rules ask for this)
    use_footer = bool(spec.get("footer_region"))

    per_pattern_pages: dict[str, list[int]] = {p: [] for p in raw_patterns}
    sample_matches: dict[str, str] = {}
    for p in pages:
        haystack = p["footer_text"] if use_footer else p["text"]
        for src, rx in zip(raw_patterns, compiled):
            m = rx.search(haystack)
            if m:
                per_pattern_pages[src].append(p["page_number"])
                sample_matches.setdefault(src, m.group(0))

    total_hits = sum(len(v) for v in per_pattern_pages.values())
    distinct_hit_pages = sorted({pg for pgs in per_pattern_pages.values() for pg in pgs})

    minimum_matches = int(spec.get("minimum_matches", 0))
    minimum_distinct_pages = int(spec.get("minimum_matches_in_distinct_pages", 0))
    logic = spec.get("logic", "at_least_one_pattern_matches")

    if minimum_distinct_pages:
        passed = len(distinct_hit_pages) >= minimum_distinct_pages
    elif minimum_matches:
        passed = total_hits >= minimum_matches
    elif logic == "at_least_one_pattern_matches":
        passed = any(per_pattern_pages[p] for p in raw_patterns)
    else:
        passed = total_hits > 0

    verdict = rule.get("verdict_on_pass", VERDICT_PASS) if passed else rule.get("verdict_on_fail", VERDICT_FAIL)
    return _result(
        rule,
        verdict,
        check_method="regex_pattern",
        extracted_values={
            "pattern_hit_pages": per_pattern_pages,
            "sample_matches": sample_matches,
            "total_hits": total_hits,
            "distinct_hit_pages": distinct_hit_pages,
            "footer_scoped": use_footer,
        },
        pages_checked=pages_checked,
    )


def check_table_detection(extraction: dict, rule: dict) -> dict:
    """Look for a table whose headers (top row) match enough required headers, case-insensitive."""
    spec = rule["check_spec"]
    pages = _resolve_pages(extraction, spec.get("scope"))
    if not pages:
        return _result(
            rule,
            VERDICT_UNEVALUABLE,
            check_method="table_detection",
            failure_mode=FAILURE_EXTRACTION,
            extracted_values={"reason": "no pages in scope"},
        )
    pages_checked = [p["page_number"] for p in pages]

    required_headers = [h.lower() for h in spec.get("required_table_headers", [])]
    minimum = int(spec.get("minimum_matching_headers", len(required_headers)))

    best_match: dict[str, Any] = {"matches": 0, "page": None, "headers": []}
    for p in pages:
        for table in p["tables"]:
            if not table:
                continue
            # Examine first non-empty row as the header row
            header_row = None
            for row in table:
                if row and any(cell and cell.strip() for cell in row if isinstance(cell, str)):
                    header_row = row
                    break
            if header_row is None:
                continue
            normalized = [
                (cell or "").strip().lower() for cell in header_row if isinstance(cell, str)
            ]
            matches = [
                h for h in required_headers
                if any(h in cell for cell in normalized)
            ]
            if len(matches) > best_match["matches"]:
                best_match = {
                    "matches": len(matches),
                    "page": p["page_number"],
                    "headers": [c for c in header_row if isinstance(c, str)],
                    "matched_headers": matches,
                }
            if len(matches) >= minimum:
                return _result(
                    rule,
                    rule.get("verdict_on_pass", VERDICT_PASS),
                    check_method="table_detection",
                    extracted_values={
                        "matched_table_page": p["page_number"],
                        "matched_headers": matches,
                        "header_row": [c for c in header_row if isinstance(c, str)],
                        "minimum_required": minimum,
                    },
                    pages_checked=pages_checked,
                )

    return _result(
        rule,
        rule.get("verdict_on_fail", VERDICT_FAIL),
        check_method="table_detection",
        extracted_values={
            "best_match": best_match,
            "minimum_required": minimum,
            "required_headers": required_headers,
        },
        pages_checked=pages_checked,
    )


def check_pdf_image_detection(extraction: dict, rule: dict) -> dict:
    """Image presence + minimum-size check using image bbox area / page area."""
    spec = rule["check_spec"]
    pages = _resolve_pages(extraction, spec.get("scope"))
    if not pages:
        return _result(
            rule,
            VERDICT_UNEVALUABLE,
            check_method="pdf_image_detection",
            failure_mode=FAILURE_EXTRACTION,
            extracted_values={"reason": "no pages in scope"},
        )
    pages_checked = [p["page_number"] for p in pages]

    min_pct = float(spec.get("minimum_image_area_percent_of_page", 0)) / 100.0

    # Variant A: minimum_image_count on the in-scope pages
    if "minimum_image_count" in spec:
        min_count = int(spec["minimum_image_count"])
        large_count = 0
        for p in pages:
            for img in p["images"]:
                if img["area_ratio"] >= min_pct:
                    large_count += 1
        if large_count >= min_count:
            verdict = rule.get("verdict_on_pass", VERDICT_PASS)
        else:
            verdict = rule.get("verdict_on_fail", VERDICT_FAIL)
        return _result(
            rule,
            verdict,
            check_method="pdf_image_detection",
            extracted_values={
                "large_image_count": large_count,
                "minimum_required": min_count,
                "minimum_area_ratio": min_pct,
            },
            pages_checked=pages_checked,
        )

    # Variant B: minimum_large_images_total across the document, excluding cover
    if "minimum_large_images_total" in spec:
        min_total = int(spec["minimum_large_images_total"])
        large = 0
        for p in pages:
            if p["page_number"] == 1:
                continue
            for img in p["images"]:
                if img["area_ratio"] >= min_pct:
                    large += 1
        if large >= min_total:
            verdict = rule.get("verdict_on_pass", VERDICT_PASS)
        else:
            verdict = rule.get("verdict_on_fail", VERDICT_PASS_WITH_NOTE)
        return _result(
            rule,
            verdict,
            check_method="pdf_image_detection",
            extracted_values={
                "large_images_excluding_cover": large,
                "minimum_required": min_total,
                "minimum_area_ratio": min_pct,
            },
            pages_checked=pages_checked,
        )

    return _engine_error(rule, "pdf_image_detection: spec missing minimum_image_count or minimum_large_images_total")


def check_page_structure_analysis(extraction: dict, rule: dict) -> dict:
    """Two structural variants used by the rule set: footer-region presence and chapter-divider detection."""
    spec = rule["check_spec"]
    pages = _resolve_pages(extraction, spec.get("scope"))
    if not pages:
        return _result(
            rule,
            VERDICT_UNEVALUABLE,
            check_method="page_structure_analysis",
            failure_mode=FAILURE_EXTRACTION,
            extracted_values={"reason": "no pages in scope"},
        )
    pages_checked = [p["page_number"] for p in pages]

    # Footer-region presence (FORMAT_FOOTER_PRESENT_ALL_PAGES)
    if spec.get("footer_region") and spec.get("test", "").startswith("footer region contains text"):
        empty_pages = [p["page_number"] for p in pages if not p["footer_text"].strip()]
        if not empty_pages:
            verdict = rule.get("verdict_on_pass", VERDICT_PASS)
        else:
            verdict = rule.get("verdict_on_fail", VERDICT_FAIL)
        return _result(
            rule,
            verdict,
            check_method="page_structure_analysis",
            extracted_values={"pages_missing_footer": empty_pages},
            pages_checked=pages_checked,
        )

    # Chapter dividers (FORMAT_CHAPTER_DIVIDER_PAGES) — pass-with-note bias per spec
    if "expected_chapter_names" in spec:
        chapter_names = list(spec["expected_chapter_names"])
        full_text = "\n".join(p["text"] for p in pages)

        divider_pages_per_chapter: dict[str, list[int]] = {}
        chapters_present_anywhere: list[str] = []
        for chapter in chapter_names:
            divider_hits: list[int] = []
            present_anywhere = chapter in full_text
            if present_anywhere:
                chapters_present_anywhere.append(chapter)
            for p in pages:
                word_count = len(p["text"].split())
                if word_count < 50 and chapter in p["text"]:
                    divider_hits.append(p["page_number"])
            divider_pages_per_chapter[chapter] = divider_hits

        # Logic: for each required chapter, divider page exists OR chapter appears as a major heading.
        unmet = [c for c in chapter_names if not divider_pages_per_chapter[c] and c not in chapters_present_anywhere]
        if not unmet:
            verdict = rule.get("verdict_on_pass", VERDICT_PASS)
        else:
            verdict = rule.get("verdict_on_fail", VERDICT_PASS_WITH_NOTE)
        return _result(
            rule,
            verdict,
            check_method="page_structure_analysis",
            extracted_values={
                "divider_pages_per_chapter": divider_pages_per_chapter,
                "chapters_present_anywhere": chapters_present_anywhere,
                "chapters_missing": unmet,
            },
            pages_checked=pages_checked,
        )

    return _engine_error(rule, "page_structure_analysis: unknown spec variant")


def check_manual_review(extraction: dict, rule: dict) -> dict:
    """Always returns 'requires_review'. Never inspects the PDF — the determinism contract forbids it."""
    instructions = rule.get("check_spec", {}).get("review_instructions_he", "")
    return {
        "rule_code": rule["rule_code"],
        "rule_name_he": rule.get("rule_name_he", "") or "",
        "verdict": VERDICT_REQUIRES_REVIEW,
        "failure_mode": FAILURE_NONE,
        "confidence": "HIGH",
        "evidence": {
            "check_method": "manual_review",
            "extracted_values": {},
            "pages_checked": [],
        },
        "notes_he": rule.get("description_he", ""),
        "review_instructions_he": instructions,
    }


_HANDLERS: dict[str, Callable[[dict, dict], dict]] = {
    "pdf_metadata": check_pdf_metadata,
    "text_extraction": check_text_extraction,
    "regex_pattern": check_regex_pattern,
    "table_detection": check_table_detection,
    "pdf_image_detection": check_pdf_image_detection,
    "page_structure_analysis": check_page_structure_analysis,
    "manual_review": check_manual_review,
}
