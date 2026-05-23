"""Unit tests for src/compliance/evaluator.py and the per-type evaluators.

Layered coverage:

  - Per-evaluator type behaviour (one fixture per RuleType).
  - All 7 verdict states (one assertion path per verdict).
  - Override-flag propagation from the resolver into Violation rows.
  - Exception safety — an evaluator that raises produces UNEVALUABLE
    with the exception message in `notes`, and the run continues.
  - Dispatch coverage — every RuleType has a registered evaluator.

Tests use an in-memory SQLite DB built by the same DDL as the resolver
tests, plus a tiny project_data dict and a synthetic extracted_data
dict. The resolver itself is exercised end-to-end (no monkey-patching)
so this file also validates the resolver→evaluator integration.
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
import uuid
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from compliance.evaluator import EVALUATORS, evaluate_parcel
from compliance.evaluators import (
    document_presence as _doc,
    geometric as _geo,
    numeric as _num,
    procedural as _proc,
    qualitative as _qual,
)
from compliance.types import Confidence, FailureMode, Rule, RuleType, Verdict, Violation


# ──────────────────────────────────────────────────────────────────────
# Fixture builder
# ──────────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE projects (
  id TEXT PRIMARY KEY, name TEXT, plan_number TEXT NOT NULL UNIQUE,
  approval_date DATE, status TEXT, active_takanon_version_id TEXT,
  plots_json TEXT, scope_notes TEXT, appeal_days INTEGER, created_at TIMESTAMP);
CREATE TABLE takanon_versions (
  id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id),
  version_label TEXT NOT NULL, effective_date DATE, pdf_path TEXT,
  status TEXT, confirmed_by TEXT, confirmed_at TIMESTAMP);
CREATE TABLE rules (
  id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id),
  takanon_version_id TEXT REFERENCES takanon_versions(id),
  rule_code TEXT NOT NULL, rule_type TEXT NOT NULL, section TEXT,
  plot TEXT, operator TEXT, threshold REAL, threshold_text TEXT,
  unit TEXT, source_quote TEXT, source_page INTEGER, description TEXT,
  severity_if_violated TEXT, extraction_confidence REAL,
  review_status TEXT, confirmed_by TEXT, confirmed_at TIMESTAMP,
  is_active INTEGER DEFAULT 1, raw_json TEXT);
CREATE TABLE project_rule_exceptions (
  id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id),
  rule_id TEXT REFERENCES rules(id), plot TEXT, exception_type TEXT,
  notes TEXT, created_by TEXT, co_confirmed_by TEXT,
  valid_from_engine_version TEXT, expires_at TIMESTAMP, created_at TIMESTAMP);
"""


def _build_minimal_db():
    """Build an in-memory DB with one project + one takanon. Rules are
    inserted by individual tests via the helper below."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(DDL)
    project_id = str(uuid.uuid4())
    takanon_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO projects (id, name, plan_number) VALUES (?, ?, ?)",
        (project_id, "test-dp", "TEST-PLAN"),
    )
    conn.execute(
        "INSERT INTO takanon_versions (id, project_id, version_label, "
        "effective_date) VALUES (?, ?, ?, ?)",
        (takanon_id, project_id, "approved_test", "2025-01-01"),
    )
    conn.commit()
    return conn, project_id, takanon_id


def _insert_rule(conn, project_id, takanon_id, *, code, rtype,
                 operator=None, threshold=None, threshold_text=None,
                 description=None, parameter=None, raw_extra=None):
    rid = str(uuid.uuid4())
    raw = {"rule_code": code, "rule_type": rtype}
    if parameter is not None:
        raw["parameter"] = parameter
    if raw_extra:
        raw.update(raw_extra)
    import json as _json
    conn.execute(
        "INSERT INTO rules (id, project_id, takanon_version_id, rule_code, "
        "rule_type, plot, operator, threshold, threshold_text, description, "
        "severity_if_violated, is_active, raw_json) "
        "VALUES (?, ?, ?, ?, ?, 'all', ?, ?, ?, ?, 'major', 1, ?)",
        (rid, project_id, takanon_id, code, rtype, operator, threshold,
         threshold_text, description, _json.dumps(raw, ensure_ascii=False)),
    )
    conn.commit()
    return rid


def _project_data():
    """A minimal project_data dict that points all parcels at the test plan."""
    return {
        "_schema_version": "3.0.0",
        "design_plan": {"id": "test-dp"},
        "linked_statutory_plans": [{
            "plan_number": "TEST-PLAN",
            "version_label": "approved_test",
            "coverage_type": "primary",
        }],
        "project": {
            "meta": {"plan_number": "TEST-PLAN"},
            "parcels": [
                {"parcel_id": "plot_1", "governing_takanon_id": "TEST-PLAN"},
                {"parcel_id": "plot_2", "governing_takanon_id": "TEST-PLAN"},
            ],
        },
    }


# ──────────────────────────────────────────────────────────────────────
# Tests — every RuleType produces a Violation through evaluate_parcel()
# ──────────────────────────────────────────────────────────────────────

class EvaluatorTypeCoverage(unittest.TestCase):
    """One test per RuleType — the most important property."""

    def test_numeric_pass(self):
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="N_OK", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="value")
        extracted = {"parcels": {"plot_1": {"numeric_values": {"value": 50}}}}
        violations = evaluate_parcel("plot_1", _project_data(), extracted,
                                     conn, "run-1")
        self.assertEqual(len(violations), 1)
        v = violations[0]
        self.assertEqual(v.rule_type, RuleType.NUMERIC)
        self.assertEqual(v.verdict, Verdict.PASS)
        self.assertEqual(v.actual_value, 50)
        self.assertEqual(v.expected_value, "<= 100.0")

    def test_geometric_returns_unevaluable_stub(self):
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="G_STUB", rtype="geometric",
                     description="setback ≥ 9m")
        extracted = {"parcels": {"plot_1": {}}}
        violations = evaluate_parcel("plot_1", _project_data(), extracted,
                                     conn, "run-1")
        self.assertEqual(len(violations), 1)
        v = violations[0]
        self.assertEqual(v.rule_type, RuleType.GEOMETRIC)
        self.assertEqual(v.verdict, Verdict.UNEVALUABLE)
        self.assertIn("DWG parsing pending", v.notes)

    def test_document_presence_pass(self):
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="DOC_PRESENT", rtype="document_presence",
                     parameter="חתכים")
        extracted = {"parcels": {"plot_1": {
            "documents_present": {"חתכים": True}}}}
        violations = evaluate_parcel("plot_1", _project_data(), extracted,
                                     conn, "run-1")
        self.assertEqual(violations[0].verdict, Verdict.PASS)
        self.assertEqual(violations[0].rule_type, RuleType.DOCUMENT_PRESENCE)

    def test_document_presence_fail(self):
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="DOC_MISSING", rtype="document_presence",
                     parameter="רת\"א")
        extracted = {"parcels": {"plot_1": {
            "documents_present": {"רת\"א": False}}}}
        violations = evaluate_parcel("plot_1", _project_data(), extracted,
                                     conn, "run-1")
        self.assertEqual(violations[0].verdict, Verdict.FAIL)
        self.assertIn("absent", violations[0].notes)

    def test_procedural_text_equality(self):
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="SCALE_RULE", rtype="procedural",
                     operator="=", threshold_text="1:250",
                     parameter="plan_scale")
        # Wrong scale → FAIL
        extracted = {"parcels": {"plot_1": {
            "procedural_flags": {"plan_scale": "1:500"}}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.rule_type, RuleType.PROCEDURAL)
        self.assertEqual(v.verdict, Verdict.FAIL)
        # Right scale → PASS
        extracted["parcels"]["plot_1"]["procedural_flags"]["plan_scale"] = "1:250"
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.PASS)

    def test_qualitative_returns_requires_review_with_notes(self):
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="Q_DESIGN", rtype="qualitative",
                     description="architectural character",
                     raw_extra={"check_note": "evaluate against תקנון §6.2",
                                 "source_quote": "ייבחן…",
                                 "source_section": "6.2"})
        extracted = {"parcels": {"plot_1": {}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.rule_type, RuleType.QUALITATIVE)
        self.assertEqual(v.verdict, Verdict.REQUIRES_REVIEW)
        self.assertIn("requires human judgment", v.notes)
        self.assertIn("§6.2", v.notes)


# ──────────────────────────────────────────────────────────────────────
# Tests — all 7 Verdict states reachable through evaluate_parcel()
# ──────────────────────────────────────────────────────────────────────

class VerdictStateCoverage(unittest.TestCase):
    """Exercise each of the 7 Verdict states from the new enum."""

    def setUp(self):
        self.conn, self.pid, self.tid = _build_minimal_db()
        self.proj = _project_data()

    def test_pass_state(self):
        _insert_rule(self.conn, self.pid, self.tid, code="P", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="x")
        extracted = {"parcels": {"plot_1": {"numeric_values": {"x": 50}}}}
        v = evaluate_parcel("plot_1", self.proj, extracted, self.conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.PASS)

    def test_pass_with_note_state(self):
        # 99 against `<= 100` with default 2% tolerance → PASS_WITH_NOTE.
        _insert_rule(self.conn, self.pid, self.tid, code="PWN", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="x")
        extracted = {"parcels": {"plot_1": {"numeric_values": {"x": 99}}}}
        v = evaluate_parcel("plot_1", self.proj, extracted, self.conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.PASS_WITH_NOTE)
        self.assertIn("within", v.notes)

    def test_fail_state(self):
        # 200 against `<= 100`, well outside tolerance → FAIL.
        _insert_rule(self.conn, self.pid, self.tid, code="F", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="x")
        extracted = {"parcels": {"plot_1": {"numeric_values": {"x": 200}}}}
        v = evaluate_parcel("plot_1", self.proj, extracted, self.conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.FAIL)
        self.assertIsNone(v.notes)

    def test_fail_borderline_state(self):
        # 101 against `<= 100` with default 2% tolerance → FAIL_BORDERLINE.
        _insert_rule(self.conn, self.pid, self.tid, code="FB", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="x")
        extracted = {"parcels": {"plot_1": {"numeric_values": {"x": 101}}}}
        v = evaluate_parcel("plot_1", self.proj, extracted, self.conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.FAIL_BORDERLINE)
        self.assertIn("within", v.notes)

    def test_unevaluable_state_via_missing_data(self):
        _insert_rule(self.conn, self.pid, self.tid, code="U", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="x")
        # Extractor produced nothing for x.
        extracted = {"parcels": {"plot_1": {"numeric_values": {}}}}
        v = evaluate_parcel("plot_1", self.proj, extracted, self.conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.UNEVALUABLE)
        self.assertIn("no extracted numeric value", v.notes)

    def test_not_applicable_state(self):
        # Extractor flags this rule as not applicable to the parcel.
        _insert_rule(self.conn, self.pid, self.tid, code="NA", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="x")
        extracted = {"parcels": {"plot_1": {
            "numeric_values": {"x": 999},  # would FAIL if checked
            "not_applicable_rules": ["NA"],
        }}}
        v = evaluate_parcel("plot_1", self.proj, extracted, self.conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.NOT_APPLICABLE)
        self.assertIn("does not apply", v.notes)

    def test_requires_review_state(self):
        _insert_rule(self.conn, self.pid, self.tid, code="QR", rtype="qualitative",
                     description="architectural character")
        extracted = {"parcels": {"plot_1": {}}}
        v = evaluate_parcel("plot_1", self.proj, extracted, self.conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.REQUIRES_REVIEW)


# ──────────────────────────────────────────────────────────────────────
# Tests — override propagation, exception safety, dispatch coverage
# ──────────────────────────────────────────────────────────────────────

class CrossCutting(unittest.TestCase):

    def test_override_flag_propagates_to_violation(self):
        conn, pid, tid = _build_minimal_db()
        rid = _insert_rule(conn, pid, tid, code="OVR_TEST", rtype="numeric",
                           operator="<=", threshold=100.0, parameter="x")
        # Add an active exception on this rule.
        conn.execute(
            "INSERT INTO project_rule_exceptions (id, project_id, rule_id, "
            "exception_type, notes, created_by) "
            "VALUES (?, ?, ?, 'global_waiver', "
            "'engineer-approved waiver for test', 'engineer-test')",
            (str(uuid.uuid4()), pid, rid),
        )
        conn.commit()

        extracted = {"parcels": {"plot_1": {"numeric_values": {"x": 50}}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted,
                            conn, "run-1")[0]
        self.assertTrue(v.is_override_applied,
                        "Violation must reflect the resolved Rule's override flag")

    def test_evaluator_exception_yields_unevaluable_and_continues(self):
        """Inject a faulty evaluator into the dispatch table for one
        rule_type, run a parcel with TWO rules (one faulty, one OK), and
        verify the run produces 2 Violations: UNEVALUABLE for the faulty
        type with the exception message in `notes`, and PASS for the OK one."""
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="WILL_RAISE", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="x")
        _insert_rule(conn, pid, tid, code="WILL_PASS", rtype="document_presence",
                     parameter="חתכים")
        extracted = {"parcels": {"plot_1": {
            "numeric_values": {"x": 50},
            "documents_present": {"חתכים": True},
        }}}

        # Monkeypatch numeric evaluator to raise; restore after.
        original = EVALUATORS[RuleType.NUMERIC]
        def _boom(rule, extracted_data, parcel_id, engine_run_id):
            raise RuntimeError("synthetic test failure: boom")
        EVALUATORS[RuleType.NUMERIC] = _boom
        try:
            violations = evaluate_parcel("plot_1", _project_data(), extracted,
                                         conn, "run-1")
        finally:
            EVALUATORS[RuleType.NUMERIC] = original

        self.assertEqual(len(violations), 2,
                         "run must continue past the failing evaluator")
        by_code = {v.rule_id: v for v in violations}
        # The numeric rule got UNEVALUABLE with the exception in notes.
        self.assertEqual(by_code["WILL_RAISE"].verdict, Verdict.UNEVALUABLE)
        self.assertIn("RuntimeError", by_code["WILL_RAISE"].notes)
        self.assertIn("boom", by_code["WILL_RAISE"].notes)
        # The other rule still passed normally.
        self.assertEqual(by_code["WILL_PASS"].verdict, Verdict.PASS)

    def test_dispatch_table_covers_every_rule_type(self):
        """Every RuleType has a registered evaluator. The import-time
        guard inside evaluator.py enforces this; this test makes the
        invariant explicit so future RuleType additions don't slip past."""
        for rt in RuleType:
            self.assertIn(rt, EVALUATORS,
                          f"no evaluator registered for RuleType.{rt.name}")
            self.assertTrue(callable(EVALUATORS[rt]),
                             f"evaluator for {rt.name} is not callable")


# ──────────────────────────────────────────────────────────────────────
# Tests — failure_mode + error_fingerprint
# ──────────────────────────────────────────────────────────────────────

class FailureModeCoverage(unittest.TestCase):
    """Every UNEVALUABLE path sets a non-NONE failure_mode + a
    deterministic error_fingerprint. Identical failures share a
    fingerprint; distinct failures don't."""

    def test_numeric_missing_data_sets_missing_data_mode(self):
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="N_MISS", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="height")
        extracted = {"parcels": {"plot_1": {"numeric_values": {}}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.UNEVALUABLE)
        self.assertEqual(v.failure_mode, FailureMode.MISSING_DATA)
        self.assertIsNotNone(v.error_fingerprint)
        self.assertEqual(len(v.error_fingerprint), 16)

    def test_geometric_stub_sets_missing_data_mode(self):
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="G_STUB_FM", rtype="geometric")
        extracted = {"parcels": {"plot_1": {}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.UNEVALUABLE)
        self.assertEqual(v.failure_mode, FailureMode.MISSING_DATA)
        self.assertEqual(v.error_fingerprint, _geo.GEOMETRIC_STUB_FINGERPRINT)

    def test_document_presence_missing_key_sets_missing_data_mode(self):
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="DOC_MISS", rtype="document_presence",
                     parameter="פרוגרמה")
        # Note: documents_present dict is present but the specific key isn't
        extracted = {"parcels": {"plot_1": {"documents_present": {}}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.UNEVALUABLE)
        self.assertEqual(v.failure_mode, FailureMode.MISSING_DATA)
        self.assertIsNotNone(v.error_fingerprint)

    def test_procedural_missing_key_sets_missing_data_mode(self):
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="PROC_MISS", rtype="procedural",
                     parameter="some_flag")
        extracted = {"parcels": {"plot_1": {"procedural_flags": {}}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.UNEVALUABLE)
        self.assertEqual(v.failure_mode, FailureMode.MISSING_DATA)
        self.assertIsNotNone(v.error_fingerprint)

    def test_evaluator_exception_sets_engine_error_mode_with_fingerprint(self):
        """An evaluator that raises produces UNEVALUABLE with
        failure_mode=ENGINE_ERROR and a non-null fingerprint."""
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="BOOM", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="x")
        extracted = {"parcels": {"plot_1": {"numeric_values": {"x": 50}}}}

        original = EVALUATORS[RuleType.NUMERIC]
        def _boom(rule, ed, pid_, run_id):
            raise KeyError("x")
        EVALUATORS[RuleType.NUMERIC] = _boom
        try:
            v = evaluate_parcel("plot_1", _project_data(), extracted,
                                conn, "run")[0]
        finally:
            EVALUATORS[RuleType.NUMERIC] = original

        self.assertEqual(v.verdict, Verdict.UNEVALUABLE)
        self.assertEqual(v.failure_mode, FailureMode.ENGINE_ERROR)
        self.assertIsNotNone(v.error_fingerprint)
        self.assertEqual(len(v.error_fingerprint), 16)

    def test_two_violations_with_same_exception_share_fingerprint(self):
        """Two evaluator-raised KeyError('x') must produce the same
        error_fingerprint so the PDF generator can cluster them."""
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="BOOM_A", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="x")
        _insert_rule(conn, pid, tid, code="BOOM_B", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="y")
        extracted = {"parcels": {
            "plot_1": {"numeric_values": {"x": 50, "y": 60}},
            "plot_2": {"numeric_values": {"x": 50, "y": 60}},
        }}

        original = EVALUATORS[RuleType.NUMERIC]
        def _boom(rule, ed, pid_, run_id):
            raise KeyError("missing-key-shared")
        EVALUATORS[RuleType.NUMERIC] = _boom
        try:
            vs1 = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")
            vs2 = evaluate_parcel("plot_2", _project_data(), extracted, conn, "r")
        finally:
            EVALUATORS[RuleType.NUMERIC] = original

        all_vs = vs1 + vs2
        self.assertGreaterEqual(len(all_vs), 2)
        fingerprints = {v.error_fingerprint for v in all_vs}
        self.assertEqual(len(fingerprints), 1,
                         f"expected 1 shared fingerprint; got {fingerprints}")

    def test_two_violations_with_different_exceptions_have_different_fingerprints(self):
        """KeyError('a') and ValueError('b') must produce distinct
        fingerprints — otherwise the PDF generator would mis-cluster."""
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="DIFF_A", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="x")
        _insert_rule(conn, pid, tid, code="DIFF_B", rtype="document_presence",
                     parameter="some_doc")
        extracted = {"parcels": {"plot_1": {
            "numeric_values": {"x": 50},
            "documents_present": {"some_doc": True},
        }}}

        # Two distinct exceptions, dispatched per rule_type.
        orig_num = EVALUATORS[RuleType.NUMERIC]
        orig_doc = EVALUATORS[RuleType.DOCUMENT_PRESENCE]
        def _key_err(rule, ed, pid_, run_id):
            raise KeyError("x missing")
        def _val_err(rule, ed, pid_, run_id):
            raise ValueError("invalid doc state")
        EVALUATORS[RuleType.NUMERIC] = _key_err
        EVALUATORS[RuleType.DOCUMENT_PRESENCE] = _val_err
        try:
            vs = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")
        finally:
            EVALUATORS[RuleType.NUMERIC] = orig_num
            EVALUATORS[RuleType.DOCUMENT_PRESENCE] = orig_doc

        fps = [v.error_fingerprint for v in vs]
        self.assertEqual(len(set(fps)), 2,
                         f"expected 2 distinct fingerprints; got {fps}")

    def test_qualitative_returns_requires_review_with_failure_mode_none(self):
        """Qualitative path returns REQUIRES_REVIEW (not UNEVALUABLE) so
        failure_mode must remain NONE."""
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="Q_FM", rtype="qualitative",
                     description="check character")
        extracted = {"parcels": {"plot_1": {}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.REQUIRES_REVIEW)
        self.assertEqual(v.failure_mode, FailureMode.NONE)
        self.assertIsNone(v.error_fingerprint)

    def test_pass_verdict_keeps_failure_mode_none(self):
        """Non-UNEVALUABLE verdicts must always have failure_mode=NONE."""
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="P_FM", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="x")
        extracted = {"parcels": {"plot_1": {"numeric_values": {"x": 50}}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.PASS)
        self.assertEqual(v.failure_mode, FailureMode.NONE)
        self.assertIsNone(v.error_fingerprint)


# ──────────────────────────────────────────────────────────────────────
# Tests — confidence axis
# ──────────────────────────────────────────────────────────────────────

class ConfidenceAxis(unittest.TestCase):
    """All deterministic evaluators emit Confidence.HIGH; qualitative
    emits Confidence.LOW. Confidence is independent of verdict."""

    def test_numeric_pass_is_high_confidence(self):
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="N_HC", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="x")
        extracted = {"parcels": {"plot_1": {"numeric_values": {"x": 50}}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.PASS)
        self.assertEqual(v.confidence, Confidence.HIGH)

    def test_numeric_fail_is_high_confidence(self):
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="N_HC2", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="x")
        extracted = {"parcels": {"plot_1": {"numeric_values": {"x": 200}}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.FAIL)
        self.assertEqual(v.confidence, Confidence.HIGH)

    def test_numeric_unevaluable_is_high_confidence(self):
        # "I'm confident I can't evaluate this" — HIGH stays HIGH.
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="N_HC3", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="x")
        extracted = {"parcels": {"plot_1": {"numeric_values": {}}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.UNEVALUABLE)
        self.assertEqual(v.confidence, Confidence.HIGH)

    def test_geometric_stub_is_high_confidence(self):
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="G_HC", rtype="geometric")
        extracted = {"parcels": {"plot_1": {}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.confidence, Confidence.HIGH)

    def test_document_presence_is_high_confidence(self):
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="DOC_HC", rtype="document_presence",
                     parameter="חתכים")
        extracted = {"parcels": {"plot_1": {
            "documents_present": {"חתכים": True}}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.confidence, Confidence.HIGH)

    def test_procedural_is_high_confidence(self):
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="PROC_HC", rtype="procedural",
                     operator="=", threshold_text="1:250", parameter="scale")
        extracted = {"parcels": {"plot_1": {
            "procedural_flags": {"scale": "1:250"}}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.confidence, Confidence.HIGH)

    def test_qualitative_is_low_confidence(self):
        """Qualitative judgments default to LOW until the future Claude
        integration provides explicit reasoning to upgrade them."""
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="Q_LC", rtype="qualitative",
                     description="character check")
        extracted = {"parcels": {"plot_1": {}}}
        v = evaluate_parcel("plot_1", _project_data(), extracted, conn, "r")[0]
        self.assertEqual(v.verdict, Verdict.REQUIRES_REVIEW)
        self.assertEqual(v.confidence, Confidence.LOW)

    def test_engine_error_keeps_default_confidence(self):
        """An exception-induced UNEVALUABLE doesn't get to assert
        anything about reliability — the dispatcher leaves confidence at
        the dataclass default (HIGH). The verdict + failure_mode already
        carry the 'we don't trust this' signal."""
        conn, pid, tid = _build_minimal_db()
        _insert_rule(conn, pid, tid, code="EE_CONF", rtype="numeric",
                     operator="<=", threshold=100.0, parameter="x")
        extracted = {"parcels": {"plot_1": {"numeric_values": {"x": 50}}}}
        original = EVALUATORS[RuleType.NUMERIC]
        def _boom(rule, ed, pid_, run_id):
            raise RuntimeError("boom-conf")
        EVALUATORS[RuleType.NUMERIC] = _boom
        try:
            v = evaluate_parcel("plot_1", _project_data(), extracted,
                                conn, "r")[0]
        finally:
            EVALUATORS[RuleType.NUMERIC] = original
        self.assertEqual(v.verdict, Verdict.UNEVALUABLE)
        self.assertEqual(v.failure_mode, FailureMode.ENGINE_ERROR)
        self.assertEqual(v.confidence, Confidence.HIGH)


if __name__ == "__main__":
    unittest.main()
