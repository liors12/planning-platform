"""Unit tests for src/compliance/persistence.py.

Covers six scenarios per spec:

  1. Happy path — run produces violations, run row goes from 'running' →
     'complete', summary stats populated correctly.
  2. Multi-parcel run — violations from all parcels persist, parcel-level
     stats correct.
  3. JSON roundtrip — complex expected_value/actual_value/evidence
     survive persist + load_violations_for_run.
  4. Override flag persistence — is_override_applied=True survives the
     INTEGER column roundtrip.
  5. Failure path — uncaught exception during evaluation marks the run
     'failed' with traceback in error_message; partial violations from
     completed parcels remain in the DB.
  6. Two consecutive runs of the same project produce two distinct
     engine_run_ids with their own violation sets — no cross-contamination.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
import uuid
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from compliance import evaluator as _evaluator_mod
from compliance.persistence import (
    load_violations_for_run,
    run_compliance_evaluation,
)
from compliance.types import Confidence, FailureMode, RuleType, Verdict, Violation


# ──────────────────────────────────────────────────────────────────────
# Fixture
# ──────────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE projects (
  id TEXT PRIMARY KEY, name TEXT, plan_number TEXT NOT NULL UNIQUE,
  approval_date DATE, status TEXT, active_takanon_version_id TEXT,
  plots_json TEXT, scope_notes TEXT, appeal_days INTEGER,
  created_at TIMESTAMP);
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
CREATE TABLE engine_runs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  engine_version TEXT NOT NULL,
  submission_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('running', 'complete', 'failed')),
  triggered_by TEXT NOT NULL,
  started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP,
  summary_stats_json TEXT,
  error_message TEXT
);
CREATE TABLE violations (
  id TEXT PRIMARY KEY,
  engine_run_id TEXT NOT NULL REFERENCES engine_runs(id),
  parcel_id TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  rule_type TEXT NOT NULL,
  verdict TEXT NOT NULL CHECK (verdict IN (
    'pass', 'pass_with_note', 'fail', 'fail_borderline',
    'unevaluable', 'not_applicable', 'requires_review'
  )),
  expected_value_json TEXT,
  actual_value_json TEXT,
  evidence_json TEXT,
  notes TEXT,
  is_override_applied INTEGER NOT NULL DEFAULT 0,
  failure_mode TEXT NOT NULL DEFAULT 'none' CHECK (failure_mode IN (
    'engine_error', 'missing_data', 'ambiguous_rule',
    'extraction_failure', 'none'
  )),
  error_fingerprint TEXT,
  confidence TEXT NOT NULL DEFAULT 'high' CHECK (confidence IN (
    'high', 'medium', 'low'
  )),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _build_db_with_two_parcels():
    """Project with 2 parcels (plot_1, plot_2), 2 numeric rules per parcel
    (one passes, one fails), 1 active exception on plot_1's first rule."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(DDL)
    project_id = str(uuid.uuid4())
    takanon_id = str(uuid.uuid4())
    conn.execute("INSERT INTO projects (id, name, plan_number) "
                 "VALUES (?, ?, ?)",
                 (project_id, "test", "TEST"))
    conn.execute("INSERT INTO takanon_versions (id, project_id, "
                 "version_label, effective_date) VALUES (?, ?, ?, ?)",
                 (takanon_id, project_id, "approved_test", "2025-01-01"))

    rule_uuids = {}
    for code, threshold in [("R_PASS", 100.0), ("R_FAIL", 50.0)]:
        rid = str(uuid.uuid4())
        rule_uuids[code] = rid
        conn.execute(
            "INSERT INTO rules (id, project_id, takanon_version_id, "
            "rule_code, rule_type, plot, operator, threshold, description, "
            "is_active, raw_json) "
            "VALUES (?, ?, ?, ?, 'numeric', 'all', '<=', ?, ?, 1, ?)",
            (rid, project_id, takanon_id, code, threshold,
             f"{code} threshold {threshold}",
             json.dumps({"parameter": "value"})),
        )

    # Active exception on R_PASS for plot_1.
    conn.execute(
        "INSERT INTO project_rule_exceptions (id, project_id, rule_id, "
        "exception_type, notes, created_by) "
        "VALUES (?, ?, ?, 'global_waiver', 'test exception', 'eng-test')",
        (str(uuid.uuid4()), project_id, rule_uuids["R_PASS"]),
    )
    conn.commit()

    project_data = {
        "_schema_version": "3.0.0",
        "design_plan": {"id": "test"},
        "linked_statutory_plans": [{
            "plan_number": "TEST",
            "version_label": "approved_test",
            "coverage_type": "primary",
        }],
        "project": {
            "meta": {"plan_number": "TEST"},
            "parcels": [
                {"parcel_id": "plot_1", "governing_takanon_id": "TEST"},
                {"parcel_id": "plot_2", "governing_takanon_id": "TEST"},
            ],
        },
    }
    extracted_data = {
        "parcels": {
            "plot_1": {"numeric_values": {"value": 60}},
            "plot_2": {"numeric_values": {"value": 60}},
        }
    }
    return conn, project_id, project_data, extracted_data


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────

class HappyPath(unittest.TestCase):

    def test_run_lifecycle_running_to_complete_with_summary_stats(self):
        conn, pid, proj, extracted = _build_db_with_two_parcels()
        run_id = run_compliance_evaluation(
            project_id=pid, project_data=proj, extracted_data=extracted,
            db_conn=conn, engine_version="1.0.0",
            submission_version="sub-001", triggered_by="test-user",
        )

        # Run row goes from 'running' to 'complete'; completed_at populated.
        row = conn.execute(
            "SELECT status, error_message, summary_stats_json, "
            "completed_at, project_id, engine_version, "
            "submission_version, triggered_by FROM engine_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        (status, err, stats_json, completed_at, project_id_col,
         eng_ver, sub_ver, triggered_by) = row
        self.assertEqual(status, "complete")
        self.assertIsNone(err)
        self.assertIsNotNone(completed_at)
        self.assertEqual(project_id_col, pid)
        self.assertEqual(eng_ver, "1.0.0")
        self.assertEqual(sub_ver, "sub-001")
        self.assertEqual(triggered_by, "test-user")

        # Summary stats — all 7 verdict keys present, zero-filled where
        # nothing fired.
        stats = json.loads(stats_json)
        self.assertEqual(stats["parcels_evaluated"], 2)
        # 2 parcels × 2 rules = 4 violations total. Both parcels pass R_PASS
        # (60 ≤ 100) and fail R_FAIL (60 > 50).
        self.assertEqual(stats["total_violations"], 4)
        self.assertEqual(set(stats["by_verdict"].keys()),
                         {v.value for v in Verdict})
        self.assertEqual(stats["by_verdict"]["pass"], 2)
        self.assertEqual(stats["by_verdict"]["fail"], 2)
        self.assertEqual(stats["by_verdict"]["pass_with_note"], 0)
        self.assertEqual(stats["parcels_with_failures"], 2)


class MultiParcel(unittest.TestCase):

    def test_violations_persist_for_every_parcel_and_per_parcel_stats_correct(self):
        conn, pid, proj, extracted = _build_db_with_two_parcels()
        run_id = run_compliance_evaluation(
            project_id=pid, project_data=proj, extracted_data=extracted,
            db_conn=conn, engine_version="1.0.0",
            submission_version="sub-001",
        )

        rows = conn.execute(
            "SELECT parcel_id, rule_id, verdict FROM violations "
            "WHERE engine_run_id = ? ORDER BY parcel_id, rule_id",
            (run_id,),
        ).fetchall()
        self.assertEqual(len(rows), 4)
        self.assertEqual({r[0] for r in rows}, {"plot_1", "plot_2"})

        stats = json.loads(conn.execute(
            "SELECT summary_stats_json FROM engine_runs WHERE id = ?",
            (run_id,),
        ).fetchone()[0])
        self.assertEqual(set(stats["by_parcel"].keys()),
                         {"plot_1", "plot_2"})
        for parcel_id, parcel_stats in stats["by_parcel"].items():
            self.assertEqual(parcel_stats["pass"], 1)
            self.assertEqual(parcel_stats["fail"], 1)
            # All 7 verdict keys zero-filled.
            self.assertEqual(set(parcel_stats.keys()),
                             {v.value for v in Verdict})


class JsonRoundtrip(unittest.TestCase):

    def test_complex_expected_actual_evidence_survive_persist_load(self):
        """expected_value, actual_value, evidence are polymorphic. Hand-craft
        a Violation with nested dicts, lists, Hebrew, floats; persist via
        run_compliance_evaluation; reload via load_violations_for_run; verify
        equality."""
        conn, pid, proj, extracted = _build_db_with_two_parcels()

        # Inject a complex expected/actual/evidence by monkeypatching the
        # numeric evaluator just for this test.
        complex_expected = {
            "operator": "<=", "threshold": 100,
            "context_he": "מקסימום יחידות דיור",
            "tags": ["primary-rule", "v3"],
        }
        complex_evidence = {
            "source_file": "תקנון.pdf",
            "page": 8,
            "bbox": [120.5, 340.2, 480.8, 520.1],
            "excerpt": "מספר יחידות הדיור המרבי",
            "confidence": 0.97,
            "nested": {"reviewed_by": None, "tags": ["a", "b"]},
        }

        original = _evaluator_mod.EVALUATORS[RuleType.NUMERIC]
        def _custom(rule, extracted_data, parcel_id, engine_run_id):
            v = original(rule, extracted_data, parcel_id, engine_run_id)
            v.expected_value = complex_expected
            v.actual_value = {"value": 60.0, "unit": "יח״ד"}
            v.evidence = complex_evidence
            return v

        _evaluator_mod.EVALUATORS[RuleType.NUMERIC] = _custom
        try:
            run_id = run_compliance_evaluation(
                project_id=pid, project_data=proj, extracted_data=extracted,
                db_conn=conn, engine_version="1.0.0",
                submission_version="sub-001",
            )
        finally:
            _evaluator_mod.EVALUATORS[RuleType.NUMERIC] = original

        loaded = load_violations_for_run(run_id, conn)
        self.assertGreater(len(loaded), 0)
        for v in loaded:
            self.assertEqual(v.expected_value, complex_expected)
            self.assertEqual(v.actual_value, {"value": 60.0, "unit": "יח״ד"})
            self.assertEqual(v.evidence, complex_evidence)
            # Type fields are reconstructed as enums, not strings.
            self.assertIsInstance(v.rule_type, RuleType)
            self.assertIsInstance(v.verdict, Verdict)


class OverrideFlagPersistence(unittest.TestCase):

    def test_is_override_applied_survives_integer_column_roundtrip(self):
        conn, pid, proj, extracted = _build_db_with_two_parcels()
        run_id = run_compliance_evaluation(
            project_id=pid, project_data=proj, extracted_data=extracted,
            db_conn=conn, engine_version="1.0.0",
            submission_version="sub-001",
        )

        # The fixture put an exception on R_PASS, so R_PASS rows for both
        # parcels should have is_override_applied=1; R_FAIL rows = 0.
        raw = conn.execute(
            "SELECT rule_id, parcel_id, is_override_applied "
            "FROM violations WHERE engine_run_id = ?",
            (run_id,),
        ).fetchall()
        for rule_id, parcel_id, flag in raw:
            self.assertIn(flag, (0, 1),
                          "is_override_applied stored as INTEGER 0/1")
            if rule_id == "R_PASS":
                self.assertEqual(flag, 1, f"R_PASS on {parcel_id} should be overridden")
            else:
                self.assertEqual(flag, 0, f"R_FAIL on {parcel_id} should not be overridden")

        # And via the load function — flag comes back as bool.
        loaded = load_violations_for_run(run_id, conn)
        for v in loaded:
            self.assertIsInstance(v.is_override_applied, bool)
            if v.rule_id == "R_PASS":
                self.assertTrue(v.is_override_applied)
            else:
                self.assertFalse(v.is_override_applied)


class FailurePath(unittest.TestCase):

    def test_uncaught_exception_marks_run_failed_partial_violations_remain(self):
        """Patch evaluate_parcel to raise on the SECOND parcel only. The
        first parcel's violations should commit; the run row should be
        marked 'failed' with traceback in error_message; the exception
        re-raises to the caller."""
        conn, pid, proj, extracted = _build_db_with_two_parcels()

        from compliance import persistence as _persist_mod
        original_eval = _persist_mod.evaluate_parcel
        call_log = []
        def _flaky(parcel_id, **kwargs):
            call_log.append(parcel_id)
            if parcel_id == "plot_2":
                raise RuntimeError("synthetic failure on plot_2")
            return original_eval(parcel_id=parcel_id, **kwargs)

        _persist_mod.evaluate_parcel = _flaky
        try:
            with self.assertRaises(RuntimeError) as cm:
                run_compliance_evaluation(
                    project_id=pid, project_data=proj, extracted_data=extracted,
                    db_conn=conn, engine_version="1.0.0",
                    submission_version="sub-001",
                )
            self.assertIn("plot_2", str(cm.exception))
        finally:
            _persist_mod.evaluate_parcel = original_eval

        # Exactly one engine_runs row, status='failed', traceback in error_message.
        rows = conn.execute(
            "SELECT id, status, error_message, summary_stats_json, "
            "completed_at FROM engine_runs"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        run_id, status, err, stats, completed_at = rows[0]
        self.assertEqual(status, "failed")
        self.assertIsNotNone(err)
        self.assertIn("RuntimeError", err)
        self.assertIn("plot_2", err)
        self.assertIsNone(stats,
                          "summary_stats_json must NOT be populated on failure")
        self.assertIsNotNone(completed_at,
                              "completed_at is set even on failure (timestamp of giving up)")

        # Partial violations from plot_1 remain.
        partial = conn.execute(
            "SELECT parcel_id FROM violations WHERE engine_run_id = ?",
            (run_id,),
        ).fetchall()
        self.assertGreater(len(partial), 0,
                            "plot_1's violations must persist even though plot_2 crashed")
        self.assertEqual({r[0] for r in partial}, {"plot_1"})


class TwoConsecutiveRuns(unittest.TestCase):

    def test_two_runs_distinct_ids_no_cross_contamination(self):
        conn, pid, proj, extracted = _build_db_with_two_parcels()

        run_id_1 = run_compliance_evaluation(
            project_id=pid, project_data=proj, extracted_data=extracted,
            db_conn=conn, engine_version="1.0.0",
            submission_version="sub-001",
        )
        run_id_2 = run_compliance_evaluation(
            project_id=pid, project_data=proj, extracted_data=extracted,
            db_conn=conn, engine_version="1.0.1",
            submission_version="sub-002",
        )

        self.assertNotEqual(run_id_1, run_id_2,
                            "two consecutive runs must produce distinct UUIDs")

        # Each run has its own engine_runs row, both 'complete'.
        rows = conn.execute(
            "SELECT id, status, engine_version, submission_version "
            "FROM engine_runs ORDER BY started_at"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r[1] for r in rows}, {"complete"})
        self.assertEqual({r[2] for r in rows}, {"1.0.0", "1.0.1"})

        # Violations are partitioned by engine_run_id.
        v1 = load_violations_for_run(run_id_1, conn)
        v2 = load_violations_for_run(run_id_2, conn)
        self.assertEqual(len(v1), 4)
        self.assertEqual(len(v2), 4)
        for v in v1:
            self.assertEqual(v.engine_run_id, run_id_1)
        for v in v2:
            self.assertEqual(v.engine_run_id, run_id_2)
        # No violation_id collisions across runs.
        self.assertTrue({v.violation_id for v in v1}.isdisjoint(
                         {v.violation_id for v in v2}))


class FailureModePersistence(unittest.TestCase):
    """failure_mode + error_fingerprint survive write+read; summary stats
    expose by_failure_mode + error_fingerprint_clusters."""

    def test_failure_mode_and_fingerprint_roundtrip(self):
        conn, pid, proj, extracted = _build_db_with_two_parcels()

        # Make the numeric evaluator emit UNEVALUABLE+ENGINE_ERROR for
        # plot_1.R_PASS so we exercise the new columns end-to-end.
        from compliance import persistence as _persist_mod  # noqa: F401
        original = _evaluator_mod.EVALUATORS[RuleType.NUMERIC]
        def _custom(rule, ed, parcel_id, run_id):
            v = original(rule, ed, parcel_id, run_id)
            if rule.rule_id == "R_PASS" and parcel_id == "plot_1":
                v.verdict = Verdict.UNEVALUABLE
                v.failure_mode = FailureMode.ENGINE_ERROR
                v.error_fingerprint = "fp-eng-err-aaa"
            return v
        _evaluator_mod.EVALUATORS[RuleType.NUMERIC] = _custom
        try:
            run_id = run_compliance_evaluation(
                project_id=pid, project_data=proj, extracted_data=extracted,
                db_conn=conn, engine_version="1.0.0",
                submission_version="sub-001",
            )
        finally:
            _evaluator_mod.EVALUATORS[RuleType.NUMERIC] = original

        loaded = load_violations_for_run(run_id, conn)
        target = next(v for v in loaded
                      if v.parcel_id == "plot_1" and v.rule_id == "R_PASS")
        self.assertEqual(target.failure_mode, FailureMode.ENGINE_ERROR)
        self.assertEqual(target.error_fingerprint, "fp-eng-err-aaa")
        # Other rows still default to NONE / null.
        for v in loaded:
            if v is target:
                continue
            self.assertEqual(v.failure_mode, FailureMode.NONE)
            self.assertIsNone(v.error_fingerprint)

    def test_confidence_roundtrip(self):
        """confidence column survives write+read; defaults to HIGH for
        deterministic evaluators and LOW for qualitative."""
        conn, pid, proj, extracted = _build_db_with_two_parcels()

        original = _evaluator_mod.EVALUATORS[RuleType.NUMERIC]
        def _custom(rule, ed, parcel_id, run_id):
            v = original(rule, ed, parcel_id, run_id)
            # Tag plot_1.R_FAIL as MEDIUM so we exercise all three values
            if rule.rule_id == "R_FAIL" and parcel_id == "plot_1":
                v.confidence = Confidence.MEDIUM
            return v
        _evaluator_mod.EVALUATORS[RuleType.NUMERIC] = _custom
        try:
            run_id = run_compliance_evaluation(
                project_id=pid, project_data=proj, extracted_data=extracted,
                db_conn=conn, engine_version="1.0.0",
                submission_version="sub-001",
            )
        finally:
            _evaluator_mod.EVALUATORS[RuleType.NUMERIC] = original

        loaded = load_violations_for_run(run_id, conn)
        target = next(v for v in loaded
                      if v.parcel_id == "plot_1" and v.rule_id == "R_FAIL")
        self.assertEqual(target.confidence, Confidence.MEDIUM)
        # Other rows default HIGH
        for v in loaded:
            if v is target:
                continue
            self.assertEqual(v.confidence, Confidence.HIGH)

    def test_summary_stats_include_by_confidence(self):
        """summary_stats_json carries a by_confidence dict with all 3
        keys zero-filled and the correct counts."""
        conn, pid, proj, extracted = _build_db_with_two_parcels()
        run_id = run_compliance_evaluation(
            project_id=pid, project_data=proj, extracted_data=extracted,
            db_conn=conn, engine_version="1.0.0",
            submission_version="sub-001",
        )
        stats_json = conn.execute(
            "SELECT summary_stats_json FROM engine_runs WHERE id = ?",
            (run_id,),
        ).fetchone()[0]
        stats = json.loads(stats_json)
        self.assertIn("by_confidence", stats)
        self.assertEqual(set(stats["by_confidence"].keys()),
                         {c.value for c in Confidence})
        # All 4 violations are deterministic numeric → all HIGH.
        self.assertEqual(stats["by_confidence"]["high"], 4)
        self.assertEqual(stats["by_confidence"]["medium"], 0)
        self.assertEqual(stats["by_confidence"]["low"], 0)

    def test_summary_stats_include_by_failure_mode_and_clusters(self):
        conn, pid, proj, extracted = _build_db_with_two_parcels()

        original = _evaluator_mod.EVALUATORS[RuleType.NUMERIC]
        def _custom(rule, ed, parcel_id, run_id):
            v = original(rule, ed, parcel_id, run_id)
            # Force both R_PASS rows (plot_1 + plot_2) into the same
            # ENGINE_ERROR cluster.
            if rule.rule_id == "R_PASS":
                v.verdict = Verdict.UNEVALUABLE
                v.failure_mode = FailureMode.ENGINE_ERROR
                v.error_fingerprint = "shared-fp-cluster"
            return v
        _evaluator_mod.EVALUATORS[RuleType.NUMERIC] = _custom
        try:
            run_id = run_compliance_evaluation(
                project_id=pid, project_data=proj, extracted_data=extracted,
                db_conn=conn, engine_version="1.0.0",
                submission_version="sub-001",
            )
        finally:
            _evaluator_mod.EVALUATORS[RuleType.NUMERIC] = original

        stats_json = conn.execute(
            "SELECT summary_stats_json FROM engine_runs WHERE id = ?",
            (run_id,),
        ).fetchone()[0]
        stats = json.loads(stats_json)

        self.assertIn("by_failure_mode", stats)
        self.assertEqual(set(stats["by_failure_mode"].keys()),
                         {m.value for m in FailureMode})
        self.assertEqual(stats["by_failure_mode"]["engine_error"], 2)
        self.assertEqual(stats["by_failure_mode"]["none"], 2)

        self.assertIn("error_fingerprint_clusters", stats)
        self.assertEqual(stats["error_fingerprint_clusters"]["shared-fp-cluster"], 2)


if __name__ == "__main__":
    unittest.main()
