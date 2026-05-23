"""Tests for the compliance-opinion PDF generator.

Strategy: mostly assert against the rendered HTML (Jinja2 → string), not
the PDF binary. Hebrew substring assertions on HTML are far more reliable
than parsing PDF text streams. One smoke test does run the full Chrome
pipeline (skipped when Chrome isn't available) to catch packaging /
template / CSS errors that only show up in the real backend.

Covered:
  1. Smoke: full PDF generation succeeds, file is non-empty.
  2. Content: key Hebrew strings appear (verdict translations, parcel IDs,
     "טיוטה" watermark, override badge text).
  3. All 7 verdict states render with their Hebrew translation.
  4. Override badge appears iff is_override_applied=True (and only there).
  5. Multi-parcel run produces one section per parcel in deterministic
     order.
  6. Empty run still produces a valid HTML document with the executive
     summary noting zero findings.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pdf.generator import generate_compliance_opinion, render_html  # noqa: E402
from pdf.verdict_translations import (  # noqa: E402
    OVERRIDE_BADGE_HEBREW,
    VERDICT_HEBREW,
)
from compliance.types import Verdict  # noqa: E402

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from fixtures.synthetic_run import (  # noqa: E402
    build_empty_run,
    build_run_with_engine_errors,
    build_run_with_only_missing_data,
    build_synthetic_run,
)


def _chrome_available() -> bool:
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    ]
    if any(Path(p).exists() for p in candidates):
        return True
    return any(shutil.which(c) for c in ("google-chrome", "chromium", "chrome"))


class HtmlContent(unittest.TestCase):
    """All HTML-substring assertions live here — fastest tier of tests."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.conn, cls.run_id = build_synthetic_run()
        cls.html = render_html(cls.run_id, cls.conn)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_title_and_draft_notice_present(self) -> None:
        self.assertIn("חוות דעת מהנדס הוועדה המקומית", self.html)
        self.assertIn("טיוטה לעיון המהנדס", self.html)

    def test_draft_watermark_present(self) -> None:
        # Watermark element should be in the rendered HTML, with the word
        # "טיוטה" wrapped in the dedicated CSS class.
        self.assertRegex(
            self.html,
            r'class="draft-watermark"[^>]*>\s*טיוטה\s*</div>',
        )

    def test_project_metadata_rendered(self) -> None:
        # Design plan name + revision from the fixture's raw_json.
        self.assertIn("תכנית עיצוב הטייסים", self.html)
        self.assertIn("23.3", self.html)
        # Both linked statutory plans, including in the plan-list element.
        self.assertIn("407-0977595", self.html)
        self.assertIn("407-1048248", self.html)

    def test_engine_run_metadata_rendered(self) -> None:
        self.assertIn("0.3.0", self.html)              # engine_version
        self.assertIn("submission-23.3", self.html)    # submission_version

    def test_executive_summary_total_count_matches_fixture(self) -> None:
        # Fixture inserts exactly 20 violations.
        self.assertRegex(self.html, r'class="totals-row"[\s\S]{0,400}>\s*20\s*<')

    def test_one_section_per_parcel_in_order(self) -> None:
        # The fixture inserts תא שטח 101, 102, 103 in that order.
        positions = {
            pid: self.html.find(f"תא שטח {pid}") for pid in ("101", "102", "103")
        }
        for pid, idx in positions.items():
            self.assertGreater(idx, -1, f"missing parcel section for {pid}")
        self.assertLess(positions["101"], positions["102"])
        self.assertLess(positions["102"], positions["103"])

    def test_governing_takanon_appears_in_parcel_meta(self) -> None:
        # The fixture wires תא שטח 101's rules to plan 407-0977595.
        self.assertRegex(self.html, r'תא שטח 101[\s\S]+?407-0977595')

    def test_hebrew_text_with_mixed_ltr_renders_correctly(self) -> None:
        """Hebrew strings mixed with LTR fragments must not be reversed.

        Regression for the .vp-value bug where `direction: ltr;
        unicode-bidi: bidi-override` flipped every Hebrew character in
        the expected/actual cells. Fix: drop the bidi-override and wrap
        each value in <bdi> so the BiDi algorithm sees an isolated
        context for the value, regardless of the surrounding labels."""
        # Forward strings should be present; their reversed counterparts
        # (what the bug produced) must NOT appear anywhere in the HTML.
        self.assertIn("קומות", self.html)
        self.assertNotIn("תומוק", self.html)

        self.assertIn("נספח הידרולוגי", self.html)
        self.assertNotIn("חפסנ יגולורדיה", self.html)
        self.assertNotIn("יגולורדיה", self.html)

        # The literal "כן" boolean rendering — must not appear as "ןכ".
        # We can't simply assertNotIn("ןכ") because the substring "ןכ"
        # could legitimately appear inside a longer Hebrew word; instead
        # check it doesn't appear inside the .vp-value isolation context.
        self.assertNotRegex(self.html, r'<bdi class="vp-value">ןכ</bdi>')

    def test_value_cells_use_bdi_isolation(self) -> None:
        """Every expected/actual value cell must be wrapped in <bdi> with
        the .vp-value class — that's the structural guarantee that mixed
        Hebrew+LTR content renders correctly."""
        self.assertRegex(self.html, r'<bdi class="vp-value">[^<]*נדרש?</bdi>|<bdi class="vp-value">[^<]+</bdi>')
        # And no raw <span class="vp-value"> survives — the old bug.
        self.assertNotIn('<span class="vp-value">', self.html)


class VerdictTranslations(unittest.TestCase):
    """Each of the 7 verdicts must render with its Hebrew translation
    somewhere in the document. The fixture is built to include all 7."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.conn, cls.run_id = build_synthetic_run()
        cls.html = render_html(cls.run_id, cls.conn)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_all_seven_verdicts_render_in_hebrew(self) -> None:
        for verdict, hebrew in VERDICT_HEBREW.items():
            with self.subTest(verdict=verdict):
                self.assertIn(
                    hebrew, self.html,
                    f"missing Hebrew translation for {verdict.value}: {hebrew!r}",
                )


class OverrideBadge(unittest.TestCase):
    """Override badge text must appear exactly once (the fixture has one
    is_override_applied=True row), inside an .override-badge element."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.conn, cls.run_id = build_synthetic_run()
        cls.html = render_html(cls.run_id, cls.conn)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_override_badge_renders_when_flag_true(self) -> None:
        # The badge text must be inside the .override-badge element. The
        # same Hebrew string also appears in our notes-text (the fixture
        # echoes it for human-readability), so we anchor on the CSS class.
        match = re.search(
            r'<div class="override-badge"[^>]*>\s*([^<]+?)\s*</div>',
            self.html,
        )
        self.assertIsNotNone(match, "no .override-badge element rendered")
        self.assertEqual(match.group(1).strip(), OVERRIDE_BADGE_HEBREW)

    def test_override_badge_count_matches_flag_count(self) -> None:
        badge_count = len(re.findall(
            r'<div class="override-badge"', self.html,
        ))
        self.assertEqual(badge_count, 1, "fixture expects exactly 1 override badge")


class ReviewSection(unittest.TestCase):
    """The review-rollup table at the end aggregates requires_review and
    unevaluable verdicts. Every such violation should appear there."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.conn, cls.run_id = build_synthetic_run()
        cls.html = render_html(cls.run_id, cls.conn)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_review_section_present(self) -> None:
        self.assertIn("סוגיות הדורשות בחינת מהנדס", self.html)

    def test_review_section_includes_review_and_unevaluable_rows(self) -> None:
        # Slice from the review-section heading onward and assert on it.
        idx = self.html.find('class="review-section"')
        self.assertGreater(idx, -1)
        review_html = self.html[idx:]
        self.assertIn(VERDICT_HEBREW[Verdict.REQUIRES_REVIEW], review_html)
        self.assertIn(VERDICT_HEBREW[Verdict.UNEVALUABLE], review_html)


class EmptyRun(unittest.TestCase):
    """A run with zero violations must still produce a valid document with
    the exec summary noting zero findings — same template path."""

    def test_zero_violations_renders_clean_summary(self) -> None:
        conn, run_id = build_empty_run()
        try:
            html = render_html(run_id, conn)
        finally:
            conn.close()

        self.assertIn("חוות דעת מהנדס הוועדה המקומית", html)
        self.assertIn("לא נמצאו ממצאים", html)
        # No per-parcel sections, no review section.
        self.assertNotIn('class="parcel-section"', html)
        self.assertNotIn('class="review-section"', html)
        # Totals row should report 0.
        self.assertRegex(html, r'class="totals-row"[\s\S]{0,400}>\s*0\s*<')


@unittest.skipUnless(_chrome_available(), "headless Chrome not available")
class PdfSmoke(unittest.TestCase):
    """Run the full Chrome pipeline once to catch packaging issues that
    don't show up in HTML-only tests (CSS @page directives, font fallback,
    template paths). Skipped if no Chrome on PATH."""

    def test_generates_non_empty_pdf(self) -> None:
        conn, run_id = build_synthetic_run()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "draft.pdf"
                result = generate_compliance_opinion(run_id, conn, out)
                self.assertTrue(result.exists())
                self.assertGreater(result.stat().st_size, 1000,
                                   "PDF unexpectedly small (<1KB)")
                # Sanity: the file should start with %PDF-.
                with open(result, "rb") as f:
                    self.assertEqual(f.read(5), b"%PDF-")
        finally:
            conn.close()


class SystemHealthWarning(unittest.TestCase):
    """Engine errors at the run level surface a system-health warning;
    missing-data-only runs do NOT."""

    def test_warning_appears_when_engine_errors_present(self) -> None:
        conn, run_id = build_run_with_engine_errors()
        try:
            html = render_html(run_id, conn)
        finally:
            conn.close()
        self.assertIn('class="system-health-warning"', html)
        self.assertIn("אזהרת מערכת", html)
        self.assertIn("שגיאות עיבוד פנימיות", html)

    def test_engine_error_paragraph_absent_when_only_missing_data(self) -> None:
        """The engine-error paragraph stays out of the warning when no
        ENGINE_ERROR rows exist. The warning *banner* may still render
        because the underlying synthetic_run fixture seeds
        low-confidence qualitative rows, which is its own escalation
        signal — but the engine-error paragraph specifically must be
        absent."""
        conn, run_id = build_run_with_only_missing_data()
        try:
            html = render_html(run_id, conn)
        finally:
            conn.close()
        self.assertNotIn("שגיאות עיבוד פנימיות", html)

    def test_engine_error_paragraph_absent_when_synthetic_run_has_no_engine_errors(self) -> None:
        """The basic synthetic_run has UNEVALUABLE rows but none with
        ENGINE_ERROR. The engine-error paragraph must NOT render. The
        warning banner itself may render because the fixture also has
        low-confidence rows (qualitative REQUIRES_REVIEW), so we only
        assert on the engine-error paragraph text."""
        conn, run_id = build_synthetic_run()
        try:
            html = render_html(run_id, conn)
        finally:
            conn.close()
        self.assertNotIn("שגיאות עיבוד פנימיות", html)


class ClusterFolding(unittest.TestCase):
    """3+ violations sharing an error_fingerprint collapse into a
    cluster banner; <3 render normally."""

    def test_cluster_banner_renders_for_3_plus_shared_fingerprint(self) -> None:
        conn, run_id = build_run_with_engine_errors()
        try:
            html = render_html(run_id, conn)
        finally:
            conn.close()
        self.assertIn('class="cluster-row', html)
        self.assertIn("כללים נכשלו עם אותה שגיאה", html)
        # The fixture puts three errors on תא שטח 102 with the shared
        # fingerprint, so those three rule_ids appear inside the banner
        # under that parcel.
        for rule_id in ("ENG_ERR_SETBACK", "ENG_ERR_FAR", "ENG_ERR_PARKING"):
            self.assertIn(rule_id, html)

    def test_no_cluster_banner_when_fingerprints_distinct(self) -> None:
        conn, run_id = build_run_with_only_missing_data()
        try:
            html = render_html(run_id, conn)
        finally:
            conn.close()
        # Each missing-data row has its own fingerprint → no banner.
        self.assertNotIn('class="cluster-row', html)


class FailureModeInlineLabel(unittest.TestCase):
    """The Hebrew failure-mode label appears inline next to the
    UNEVALUABLE pill so the engineer immediately tells the cause."""

    def test_missing_data_label_renders_inline(self) -> None:
        conn, run_id = build_run_with_only_missing_data()
        try:
            html = render_html(run_id, conn)
        finally:
            conn.close()
        self.assertIn("מידע חסר בהגשה", html)
        self.assertIn('class="failure-mode-pill', html)

    def test_engine_error_label_renders_inline_when_not_clustered(self) -> None:
        # When 3+ engine errors share a fingerprint they're clustered,
        # not rendered as individual rows. To test the inline pill we
        # need a single-instance engine_error. Build a minimal fixture.
        conn, run_id = build_synthetic_run()
        try:
            # Insert a unique engine_error row that won't cluster.
            import json as _json
            import uuid as _uuid
            conn.execute(
                """INSERT INTO violations
                     (id, engine_run_id, parcel_id, rule_id, rule_type,
                      verdict, expected_value_json, actual_value_json,
                      evidence_json, notes, is_override_applied,
                      failure_mode, error_fingerprint)
                   VALUES (?, ?, 'תא שטח 101', 'SOLO_ENG_ERR', 'numeric',
                           'unevaluable', null, null, null,
                           'evaluator raised KeyError: solo', 0,
                           'engine_error', 'unique-fp-solo')""",
                (str(_uuid.uuid4()), run_id),
            )
            conn.commit()
            html = render_html(run_id, conn)
        finally:
            conn.close()
        self.assertIn("שגיאת מערכת", html)
        self.assertIn('failure-mode-engine_error', html)


class ConfidenceBadge(unittest.TestCase):
    """Confidence badge rules:
       - HIGH-confidence rows show no badge (would clutter every row)
       - MEDIUM and LOW rows show their Hebrew label inside a
         .confidence-badge element next to the verdict pill
       - The low-confidence summary line in the system-health area
         appears iff at least one LOW row exists
       - A LOW + override row also surfaces a worklist flag
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.conn, cls.run_id = build_synthetic_run()
        cls.html = render_html(cls.run_id, cls.conn)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_low_confidence_badge_renders(self) -> None:
        # Fixture's qualitative REQUIRES_REVIEW rows are tagged LOW.
        self.assertIn('class="confidence-badge conf-low"', self.html)
        self.assertIn("ודאות נמוכה", self.html)

    def test_medium_confidence_badge_renders(self) -> None:
        # Fixture has one PASS_WITH_NOTE qualitative row tagged MEDIUM.
        self.assertIn('class="confidence-badge conf-medium"', self.html)
        self.assertIn("ודאות בינונית", self.html)

    def test_high_confidence_rows_have_no_badge_text(self) -> None:
        # The Hebrew "ודאות גבוהה" text must NOT appear anywhere in the
        # rendered document — high confidence is the silent default.
        self.assertNotIn("ודאות גבוהה", self.html)
        self.assertNotIn('class="confidence-badge conf-high"', self.html)

    def test_low_confidence_summary_line_appears(self) -> None:
        self.assertIn("מומלץ לבחון אותם אישית", self.html)
        self.assertIn('class="shw-body shw-low-conf"', self.html)

    def test_low_confidence_override_surfaces_worklist_flag(self) -> None:
        # The fixture's overridden units-cap row on תא שטח 102 is tagged
        # confidence=low, so the worklist flag should appear.
        self.assertIn('class="worklist-flag"', self.html)
        self.assertIn("עקיפה בוודאות נמוכה", self.html)


class ConfidenceBadgeAbsentWhenAllHigh(unittest.TestCase):
    """When every row is HIGH-confidence, NO badge and NO low-conf
    summary line render. The empty-run fixture is all-HIGH (zero rows
    is technically all-HIGH)."""

    def test_empty_run_has_no_low_confidence_summary(self) -> None:
        conn, run_id = build_empty_run()
        try:
            html = render_html(run_id, conn)
        finally:
            conn.close()
        self.assertNotIn("מומלץ לבחון אותם אישית", html)
        self.assertNotIn('class="confidence-badge', html)


if __name__ == "__main__":
    unittest.main()
