"""Unit tests for src/compliance/rule_resolver.py.

Uses an in-memory SQLite DB with a minimal handcrafted fixture: one project,
two statutory plans (X primary, Y partial), an `adjacent_reference` plan A
with no parcels, ~5 rules per plan, and one project_rule_exception.
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
import uuid
import warnings
from pathlib import Path

# Ensure src/ is importable regardless of cwd or PYTHONPATH (the repo path
# contains colons that break the standard PYTHONPATH mechanism).
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from compliance.rule_resolver import resolve_rules_for_parcel
from compliance.types import Rule, RuleType


# ──────────────────────────────────────────────────────────────────────
# Fixture: a minimal in-memory DB matching the production DDL shape
# ──────────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  plan_number TEXT NOT NULL UNIQUE,
  approval_date DATE,
  status TEXT,
  active_takanon_version_id TEXT,
  plots_json TEXT,
  scope_notes TEXT,
  appeal_days INTEGER DEFAULT 30,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE takanon_versions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  version_label TEXT NOT NULL,
  effective_date DATE NOT NULL,
  pdf_path TEXT,
  status TEXT,
  confirmed_by TEXT,
  confirmed_at TIMESTAMP
);
CREATE UNIQUE INDEX uq_takanon_project_label
  ON takanon_versions(project_id, version_label);
CREATE TABLE rules (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  takanon_version_id TEXT NOT NULL REFERENCES takanon_versions(id),
  rule_code TEXT NOT NULL,
  rule_type TEXT NOT NULL,
  section TEXT,
  plot TEXT,
  operator TEXT,
  threshold REAL,
  threshold_text TEXT,
  unit TEXT,
  source_quote TEXT,
  source_page INTEGER,
  description TEXT,
  severity_if_violated TEXT,
  extraction_confidence REAL,
  review_status TEXT DEFAULT 'pending',
  confirmed_by TEXT,
  confirmed_at TIMESTAMP,
  is_active INTEGER DEFAULT 1,
  raw_json TEXT
);
CREATE TABLE project_rule_exceptions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  rule_id TEXT NOT NULL REFERENCES rules(id),
  plot TEXT,
  exception_type TEXT,
  notes TEXT NOT NULL,
  created_by TEXT NOT NULL,
  co_confirmed_by TEXT,
  valid_from_engine_version TEXT,
  expires_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE project_takanon_links (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  takanon_id TEXT NOT NULL REFERENCES takanon_versions(id),
  coverage_type TEXT NOT NULL CHECK (coverage_type IN ('primary', 'partial', 'adjacent_reference')),
  coverage_notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _build_fixture():
    """Return (conn, project_data, ids) with a populated in-memory DB.

    Layout:
      project    "test-design-plan" (plan_number "X-001-PRIMARY")
      takanon X  version_label "approved_X" — primary, 5 numeric rules
      takanon Y  version_label "approved_Y" — partial, 5 rules (mixed types)
      takanon A  version_label "approved_A" — adjacent_reference, 3 rules
                 (these MUST NOT contribute to any parcel's resolution)
      parcels    plot_1 → X (primary)
                 plot_2 → Y (partial)
                 plot_3 → no governing_takanon_id (skipped by resolver)
                 plot_4 → A (adjacent_reference — should warn + return [])
      exception  on rule X.RX_03 — overrides threshold from 100 → 80
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript(DDL)
    conn.execute("PRAGMA foreign_keys = ON")

    project_id = str(uuid.uuid4())
    takanon_x_id = str(uuid.uuid4())
    takanon_y_id = str(uuid.uuid4())
    takanon_a_id = str(uuid.uuid4())

    conn.execute(
        "INSERT INTO projects (id, name, plan_number, approval_date, status) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, "test-design-plan", "X-001-PRIMARY", "2025-01-01", "approved"),
    )
    conn.execute(
        "INSERT INTO takanon_versions (id, project_id, version_label, effective_date, status) "
        "VALUES (?, ?, ?, ?, 'confirmed')",
        (takanon_x_id, project_id, "approved_X", "2025-01-01"),
    )
    conn.execute(
        "INSERT INTO takanon_versions (id, project_id, version_label, effective_date, status) "
        "VALUES (?, ?, ?, ?, 'confirmed')",
        (takanon_y_id, project_id, "approved_Y", "2025-02-01"),
    )
    conn.execute(
        "INSERT INTO takanon_versions (id, project_id, version_label, effective_date, status) "
        "VALUES (?, ?, ?, ?, 'confirmed')",
        (takanon_a_id, project_id, "approved_A", "2025-03-01"),
    )
    conn.execute(
        "INSERT INTO project_takanon_links (id, project_id, takanon_id, coverage_type) "
        "VALUES (?, ?, ?, 'primary')",
        (str(uuid.uuid4()), project_id, takanon_x_id),
    )
    conn.execute(
        "INSERT INTO project_takanon_links (id, project_id, takanon_id, coverage_type) "
        "VALUES (?, ?, ?, 'partial')",
        (str(uuid.uuid4()), project_id, takanon_y_id),
    )
    conn.execute(
        "INSERT INTO project_takanon_links (id, project_id, takanon_id, coverage_type) "
        "VALUES (?, ?, ?, 'adjacent_reference')",
        (str(uuid.uuid4()), project_id, takanon_a_id),
    )

    # Plan X — 5 numeric rules
    rule_x_uuids = {}
    for i in range(1, 6):
        rid = str(uuid.uuid4())
        code = f"RX_0{i}"
        rule_x_uuids[code] = rid
        conn.execute(
            "INSERT INTO rules (id, project_id, takanon_version_id, rule_code, "
            "rule_type, plot, operator, threshold, unit, description, "
            "severity_if_violated, is_active) "
            "VALUES (?, ?, ?, ?, 'numeric', 'all', '<=', ?, 'units', ?, 'major', 1)",
            (rid, project_id, takanon_x_id, code, 100.0 * i,
             f"X rule {i}"),
        )

    # Plan Y — 5 mixed-type rules
    for i in range(1, 6):
        rid = str(uuid.uuid4())
        rule_type = ["numeric", "geometric", "document_presence",
                     "procedural", "qualitative"][i - 1]
        conn.execute(
            "INSERT INTO rules (id, project_id, takanon_version_id, rule_code, "
            "rule_type, plot, operator, threshold, description, "
            "severity_if_violated, is_active) "
            "VALUES (?, ?, ?, ?, ?, 'all', '>=', ?, ?, 'minor', 1)",
            (rid, project_id, takanon_y_id, f"RY_0{i}", rule_type,
             50.0 * i, f"Y rule {i}"),
        )

    # Plan A (adjacent_reference) — 3 rules. The resolver must NOT return
    # these for any parcel (adjacent_reference plans don't contribute rules).
    for i in range(1, 4):
        rid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO rules (id, project_id, takanon_version_id, rule_code, "
            "rule_type, plot, operator, threshold, description, "
            "severity_if_violated, is_active) "
            "VALUES (?, ?, ?, ?, 'numeric', 'all', '<=', ?, ?, 'info', 1)",
            (rid, project_id, takanon_a_id, f"RA_0{i}", 999.0 * i,
             f"A rule {i} (must not appear)"),
        )

    # One exception: override RX_03 threshold (100*3=300) — engineer waived
    # to a tighter limit for some good reason.
    conn.execute(
        "INSERT INTO project_rule_exceptions (id, project_id, rule_id, "
        "exception_type, notes, created_by) "
        "VALUES (?, ?, ?, 'measurement_method', "
        "?, 'engineer-test')",
        (str(uuid.uuid4()), project_id, rule_x_uuids["RX_03"],
         "Tightened threshold to 80 per Ellen's 2025 review of plan_X."),
    )

    conn.commit()

    # The project_data dict that mirrors what we'd parse from the JSON.
    project_data = {
        "_schema_version": "3.0.0",
        "design_plan": {"id": "test-dp", "name": "Test Design Plan"},
        "linked_statutory_plans": [
            {"plan_number": "X-001-PRIMARY",
             "version_label": "approved_X",
             "coverage_type": "primary"},
            {"plan_number": "Y-002-PARTIAL",
             "version_label": "approved_Y",
             "coverage_type": "partial"},
            {"plan_number": "A-003-CONTEXT",
             "version_label": "approved_A",
             "coverage_type": "adjacent_reference"},
        ],
        "project": {
            "meta": {"plan_number": "X-001-PRIMARY"},
            "parcels": [
                {"parcel_id": "plot_1", "governing_takanon_id": "X-001-PRIMARY"},
                {"parcel_id": "plot_2", "governing_takanon_id": "Y-002-PARTIAL"},
                {"parcel_id": "plot_3"},  # no governing_takanon_id
                {"parcel_id": "plot_4", "governing_takanon_id": "A-003-CONTEXT"},
            ],
        },
    }

    return conn, project_data, {
        "project_id": project_id,
        "takanon_x_id": takanon_x_id,
        "takanon_y_id": takanon_y_id,
        "takanon_a_id": takanon_a_id,
        "rule_x_uuids": rule_x_uuids,
    }


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────

class ResolverTests(unittest.TestCase):

    def setUp(self):
        self.conn, self.project_data, self.ids = _build_fixture()

    def tearDown(self):
        self.conn.close()

    # ── Test 1 ──
    def test_single_plan_no_overrides_returns_full_rule_set(self):
        """plot_2 is governed by Y; Y has 5 rules, no overrides on Y."""
        rules = resolve_rules_for_parcel("plot_2", self.project_data, self.conn)
        self.assertEqual(len(rules), 5,
                          "Y has 5 rules — resolver must return all 5")
        codes = [r.rule_id for r in rules]
        self.assertEqual(codes, [f"RY_0{i}" for i in range(1, 6)],
                          "rules must come back in rule_code order")
        # All Y rules are tagged with Y's plan_number.
        for r in rules:
            self.assertEqual(r.source_takanon_id, "Y-002-PARTIAL")
            self.assertFalse(r.is_overridden)
            self.assertIsNone(r.override_reason)
            self.assertIsNone(r.original_parameters)
        # Rule types should reflect the mix Y was seeded with.
        type_set = {r.rule_type for r in rules}
        self.assertEqual(type_set, set(RuleType))

    # ── Test 2 ──
    def test_two_parcels_different_plans_get_different_rules(self):
        """plot_1 → X's rules only; plot_2 → Y's rules only. No cross-leak."""
        rules_1 = resolve_rules_for_parcel("plot_1", self.project_data, self.conn)
        rules_2 = resolve_rules_for_parcel("plot_2", self.project_data, self.conn)

        codes_1 = {r.rule_id for r in rules_1}
        codes_2 = {r.rule_id for r in rules_2}

        # X rules and Y rules have disjoint code prefixes.
        self.assertTrue(all(c.startswith("RX_") for c in codes_1))
        self.assertTrue(all(c.startswith("RY_") for c in codes_2))
        self.assertEqual(codes_1 & codes_2, set(),
                          "no rule should appear in both parcels' rule sets")

        # Source plan tagging is correct.
        self.assertEqual({r.source_takanon_id for r in rules_1},
                         {"X-001-PRIMARY"})
        self.assertEqual({r.source_takanon_id for r in rules_2},
                         {"Y-002-PARTIAL"})

    # ── Test 3 ──
    def test_active_exception_marks_rule_as_overridden(self):
        """plot_1 is governed by X; X.RX_03 has an active exception. The
        returned RX_03 must be `is_overridden=True` with the exception's
        notes preserved as `override_reason`, and `original_parameters` must
        retain the pre-override threshold."""
        rules = resolve_rules_for_parcel("plot_1", self.project_data, self.conn)
        by_code = {r.rule_id: r for r in rules}

        # All X rules present.
        self.assertEqual(set(by_code), {f"RX_0{i}" for i in range(1, 6)})

        # RX_03 is overridden — others are not.
        for code, r in by_code.items():
            if code == "RX_03":
                self.assertTrue(r.is_overridden,
                                f"{code} should be overridden")
                self.assertIsNotNone(r.override_reason)
                self.assertIn("Ellen's 2025 review", r.override_reason)
                self.assertIsNotNone(r.original_parameters)
                # The original threshold was 100*3 = 300.
                self.assertEqual(r.original_parameters["threshold"], 300.0)
                # Override metadata bubbles into the live parameters.
                self.assertEqual(r.parameters["_override_type"],
                                 "measurement_method")
            else:
                self.assertFalse(r.is_overridden,
                                 f"{code} should NOT be overridden")
                self.assertIsNone(r.override_reason)
                self.assertIsNone(r.original_parameters)

    # ── Test 4 ──
    def test_adjacent_reference_plan_does_not_contribute_rules(self):
        """plot_4 points at A (adjacent_reference). Resolver returns [] and
        emits a warning. Plan A's rules MUST NOT leak into any other parcel
        either — verify by re-checking plot_1 and plot_2 don't contain any
        RA_ codes."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            rules_4 = resolve_rules_for_parcel(
                "plot_4", self.project_data, self.conn,
            )

        self.assertEqual(rules_4, [],
                         "adjacent_reference governing plan must yield "
                         "an empty rule set")
        self.assertTrue(any("adjacent_reference" in str(w.message)
                            for w in caught),
                        "expected a warning about adjacent_reference")

        # Plan A's rules must not appear under any other parcel either.
        for parcel_id in ("plot_1", "plot_2"):
            rules = resolve_rules_for_parcel(
                parcel_id, self.project_data, self.conn,
            )
            self.assertFalse(any(r.rule_id.startswith("RA_") for r in rules),
                             f"plan A rules leaked into {parcel_id}")

    # ── Bonus: parcel without governing_takanon_id returns [] ──
    def test_parcel_without_governing_takanon_returns_empty(self):
        rules = resolve_rules_for_parcel("plot_3", self.project_data, self.conn)
        self.assertEqual(rules, [])


if __name__ == "__main__":
    unittest.main()
