"""
Determinism contract tests for compliance_engine.format_rules_checker.

These tests enforce the non-negotiables from SKILL.md:
  1. Same PDF + same rules file -> byte-identical verdict set, every run.
  2. manual_review rules ALWAYS return verdict='requires_review' regardless of input.
  3. Zero Anthropic API calls in the format rules path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz  # PyMuPDF
import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from compliance_engine.format_rules_checker import check_submission_format  # noqa: E402

RULES_PATH = PROJECT_ROOT / "submission_format_rules.json"


@pytest.fixture(scope="session")
def rules_data() -> dict:
    with RULES_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def sample_pdf(tmp_path_factory) -> Path:
    """A small A3-landscape PDF with Hebrew-ish text, footer, table-like header, and an image.

    Deterministic — same content emitted across runs.
    """
    pdf_path = tmp_path_factory.mktemp("format_rules_fixtures") / "sample_submission.pdf"

    a3_landscape = fitz.paper_rect("a3-l")  # 1190 x 841 pt
    doc = fitz.open()

    # Page 1 — cover page
    cover = doc.new_page(width=a3_landscape.width, height=a3_landscape.height)
    cover.insert_text(
        (60, 80),
        "חוברת הנחיות בינוי ופיתוח\nתוכנית עיצוב\n407-0977595\nגרסה 1.0\nינואר 2026",
        fontsize=20,
    )
    cover.insert_text(
        (60, 300),
        "שפ\"ע   תנועה   גנים ונוף   אדריכלות   תאגיד   יו\"ר\nחתימה   תאריך",
        fontsize=14,
    )
    # Aerial image placeholder — rectangle filled with a 1-pixel image to satisfy image_detection
    img_rect = fitz.Rect(60, 400, 1130, 800)
    cover.insert_image(img_rect, stream=_one_pixel_png())

    # Page 2 — team / TOC / chapter content
    p2 = doc.new_page(width=a3_landscape.width, height=a3_landscape.height)
    p2.insert_text(
        (60, 60),
        "צוות הפרויקט\nאדריכל   נגישות   מים   ביוב   תנועה   ניקוז   מדידות   סביבה   "
        "קונסטרוקטור   חשמל   תאורה   הידרולוג   נוף   אגרונום",
        fontsize=14,
    )
    p2.insert_text((60, 200), "תוכן עניינים\n1.1 פרק ראשון\n1.2 פרק שני\n2.1 פרק שלישי\n2.2 פרק רביעי\n3.1 פרק חמישי", fontsize=14)
    p2.insert_text((60, 400), "מקרא\n1:250 — קנה מידה תכנוני", fontsize=14)
    p2.insert_text((60, a3_landscape.height - 40), "תוכנית עיצוב הטייסים | 2 |", fontsize=10)

    # Pages 3..8 — chapter content with the strings each rule looks for
    chapter_blocks = [
        "טיפולוגיות בינוי\nטיפולוגיה A\n1:250",
        "טיפולוגיה B\nטיפולוגיה C\n1:250",
        "מעטפת\nחזיתות\nפתחים\nחומריות\n1:250",
        "פיתוח\nפרוגרמות\nממשקים\nעיצוב סביבה\nגינון\n1:250",
        "הנחיות סביבתיות\nתכנון אנרגטי\nסביבתי\n1:250",
        "הנחיות תשתיות\nתנועה וחניה\nתאורה\nתקשורת\nחתימת רפרנט\n1:250",
    ]
    for i, body in enumerate(chapter_blocks, start=3):
        page = doc.new_page(width=a3_landscape.width, height=a3_landscape.height)
        page.insert_text((60, 60), body, fontsize=14)
        page.insert_text((60, a3_landscape.height - 40), f"תוכנית עיצוב הטייסים | {i} |", fontsize=10)

    doc.save(str(pdf_path), deflate=True)
    doc.close()
    return pdf_path


def _one_pixel_png() -> bytes:
    """Return raw bytes of a 1x1 white PNG."""
    return bytes.fromhex(
        "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
        "0000000D49444154789C636060606000000005000186A0314D0000000049454E44AE426082"
    )


# -------------------------------------------------------------------------
# 1) Same PDF -> byte-identical verdict set
# -------------------------------------------------------------------------

def test_same_pdf_same_verdicts(sample_pdf):
    result_1 = check_submission_format(sample_pdf, rules_path=RULES_PATH)
    result_2 = check_submission_format(sample_pdf, rules_path=RULES_PATH)
    assert result_1 == result_2

    # Stronger: serialized representations are byte-identical too.
    blob_1 = json.dumps(result_1, sort_keys=True, ensure_ascii=False)
    blob_2 = json.dumps(result_2, sort_keys=True, ensure_ascii=False)
    assert blob_1 == blob_2


# -------------------------------------------------------------------------
# 2) Manual-review rules ALWAYS return requires_review
# -------------------------------------------------------------------------

def test_manual_review_always_returns_requires_review(sample_pdf, rules_data):
    results = check_submission_format(sample_pdf, rules_path=RULES_PATH)
    manual_review_codes = {
        r["rule_code"] for r in rules_data["rules"] if r["check_method"] == "manual_review"
    }
    assert manual_review_codes, "rules file should contain at least one manual_review rule"

    by_code = {r["rule_code"]: r for r in results}
    for code in manual_review_codes:
        assert code in by_code, f"missing result for manual-review rule {code}"
        assert by_code[code]["verdict"] == "requires_review"
        assert by_code[code]["confidence"] == "HIGH"
        assert by_code[code]["failure_mode"] == "NONE"
        assert "review_instructions_he" in by_code[code]


# -------------------------------------------------------------------------
# 3) No Anthropic API calls anywhere in the format rules path
# -------------------------------------------------------------------------

def test_no_anthropic_calls_in_format_checker(sample_pdf, monkeypatch):
    call_count = {"count": 0}

    def _fail(*_args, **_kwargs):
        call_count["count"] += 1
        raise RuntimeError("Format rules path must not call Anthropic API")

    try:
        import anthropic  # noqa: F401
    except ImportError:
        # If the SDK isn't installed in this env, the path obviously can't call it.
        results = check_submission_format(sample_pdf, rules_path=RULES_PATH)
        assert results, "checker should still produce results"
        return

    monkeypatch.setattr("anthropic.Anthropic", _fail)
    results = check_submission_format(sample_pdf, rules_path=RULES_PATH)

    assert call_count["count"] == 0
    assert results, "checker should still produce results"


# -------------------------------------------------------------------------
# Bonus: project_overrides skip rules deterministically
# -------------------------------------------------------------------------

def test_project_overrides_skip_rules(sample_pdf):
    base = check_submission_format(sample_pdf, rules_path=RULES_PATH)
    base_codes = {r["rule_code"] for r in base}
    skip = next(iter(base_codes))

    filtered = check_submission_format(sample_pdf, rules_path=RULES_PATH, project_overrides=[skip])
    filtered_codes = {r["rule_code"] for r in filtered}

    assert skip not in filtered_codes
    assert filtered_codes == base_codes - {skip}
