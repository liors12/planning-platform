"""Synthetic fixture for the compliance-opinion PDF generator.

Builds an in-memory SQLite DB with:
  - 2 statutory plans (each is a `projects` row + a `takanon_versions` row)
  - 1 design-plan project (the row whose engine_run we render)
  - project_takanon_links wiring the design plan to both statutory plans
  - rules covering the rule_codes referenced by synthetic violations
  - 1 engine_runs row (status='complete')
  - ~20 violations spanning all 7 verdict states across 3 parcels

One violation has is_override_applied=True. One violation has complex
evidence (bbox coords, page numbers). One violation has Hebrew notes.

Why a hand-built fixture rather than running the persistence layer:
the PDF generator should be testable without depending on the full
evaluator → persistence pipeline. Insert violations directly so we
can shape the verdict distribution per test.

Public:
  build_synthetic_run() -> (db_conn, engine_run_id)
  build_empty_run()     -> (db_conn, engine_run_id)
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from compliance.types import RuleType, Verdict  # noqa: E402


def _make_schema(conn: sqlite3.Connection) -> None:
    """Apply the slice of DDL we need for PDF-generator tests. Pulled from
    src/load_project.py rather than imported as a module to keep this
    fixture standalone (the loader does additional work on import that we
    don't want during a test setUp)."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS projects (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      plan_number TEXT NOT NULL UNIQUE,
      approval_date DATE,
      status TEXT DEFAULT 'onboarding',
      active_takanon_version_id TEXT,
      plots_json TEXT,
      scope_notes TEXT,
      appeal_days INTEGER DEFAULT 30,
      raw_json TEXT,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS takanon_versions (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL REFERENCES projects(id),
      version_label TEXT NOT NULL,
      effective_date DATE NOT NULL,
      pdf_path TEXT,
      status TEXT DEFAULT 'draft',
      confirmed_by TEXT,
      confirmed_at TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS engine_runs (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL REFERENCES projects(id),
      engine_version TEXT NOT NULL,
      submission_version TEXT NOT NULL,
      status TEXT NOT NULL CHECK (status IN ('running','complete','failed')),
      triggered_by TEXT NOT NULL,
      started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      completed_at TIMESTAMP,
      summary_stats_json TEXT,
      error_message TEXT
    );

    CREATE TABLE IF NOT EXISTS rules (
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

    CREATE TABLE IF NOT EXISTS project_takanon_links (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL REFERENCES projects(id),
      takanon_id TEXT NOT NULL REFERENCES takanon_versions(id),
      coverage_type TEXT NOT NULL CHECK (coverage_type IN ('primary','partial','adjacent_reference')),
      coverage_notes TEXT,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS violations (
      id TEXT PRIMARY KEY,
      engine_run_id TEXT NOT NULL REFERENCES engine_runs(id),
      parcel_id TEXT NOT NULL,
      rule_id TEXT NOT NULL,
      rule_type TEXT NOT NULL,
      verdict TEXT NOT NULL CHECK (verdict IN (
        'pass','pass_with_note','fail','fail_borderline',
        'unevaluable','not_applicable','requires_review'
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
    """)


def _insert_project(
    conn: sqlite3.Connection, *,
    project_id: str, name: str, plan_number: str,
    raw_json: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO projects (id, name, plan_number, raw_json) VALUES (?, ?, ?, ?)",
        (project_id, name, plan_number,
         json.dumps(raw_json, ensure_ascii=False) if raw_json else None),
    )


def _insert_takanon(
    conn: sqlite3.Connection, *,
    takanon_id: str, project_id: str, version_label: str,
) -> None:
    conn.execute(
        """INSERT INTO takanon_versions
             (id, project_id, version_label, effective_date, status)
           VALUES (?, ?, ?, '2024-01-01', 'active')""",
        (takanon_id, project_id, version_label),
    )


def _insert_rule(
    conn: sqlite3.Connection, *,
    rule_id_uuid: str, project_id: str, takanon_version_id: str,
    rule_code: str, rule_type: RuleType,
) -> None:
    conn.execute(
        """INSERT INTO rules
             (id, project_id, takanon_version_id, rule_code, rule_type)
           VALUES (?, ?, ?, ?, ?)""",
        (rule_id_uuid, project_id, takanon_version_id, rule_code, rule_type.value),
    )


def _insert_violation(
    conn: sqlite3.Connection, *,
    engine_run_id: str, parcel_id: str, rule_id: str, rule_type: RuleType,
    verdict: Verdict,
    expected_value: Any = None,
    actual_value: Any = None,
    evidence: dict | None = None,
    notes: str | None = None,
    is_override_applied: bool = False,
    failure_mode: str = "none",
    error_fingerprint: str | None = None,
    confidence: str = "high",
) -> None:
    conn.execute(
        """INSERT INTO violations
             (id, engine_run_id, parcel_id, rule_id, rule_type, verdict,
              expected_value_json, actual_value_json, evidence_json,
              notes, is_override_applied, failure_mode, error_fingerprint,
              confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4()),
            engine_run_id, parcel_id, rule_id, rule_type.value, verdict.value,
            json.dumps(expected_value, ensure_ascii=False) if expected_value is not None else None,
            json.dumps(actual_value, ensure_ascii=False) if actual_value is not None else None,
            json.dumps(evidence, ensure_ascii=False) if evidence else None,
            notes,
            1 if is_override_applied else 0,
            failure_mode,
            error_fingerprint,
            confidence,
        ),
    )


# ──────────────────────────────────────────────────────────────────────
# Public builders
# ──────────────────────────────────────────────────────────────────────

# Rule codes used by the synthetic run. Three per parcel × three parcels,
# plus extras to cover all 7 verdict states. Stable across builds so tests
# can assert on specific codes.
_R_HEIGHT  = "HEIGHT_MAX"
_R_SETBACK = "SETBACK_FRONT"
_R_UNITS   = "UNITS_MAX_PLOT"
_R_FAR     = "FAR_RATIO"
_R_PARKING = "PARKING_RATIO"
_R_FACADE  = "FACADE_MATERIALS"
_R_DOC1    = "DOC_HYDROLOGY"
_R_DOC2    = "DOC_LANDSCAPE"
_R_PROC    = "PROC_PUBLIC_NOTICE"


def build_synthetic_run() -> tuple[sqlite3.Connection, str]:
    """Build a populated DB and return (conn, engine_run_id).

    Verdict distribution (20 rows total across 3 parcels):
      - PASS: 6
      - PASS_WITH_NOTE: 2
      - FAIL: 4
      - FAIL_BORDERLINE: 2
      - UNEVALUABLE: 2
      - NOT_APPLICABLE: 2
      - REQUIRES_REVIEW: 2

    One FAIL violation is_override_applied=True.
    One violation has bbox+page evidence.
    One violation has Hebrew text in notes.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    _make_schema(conn)

    # Statutory plans (each is also a `projects` row).
    sp1_id = str(uuid.uuid4())
    sp2_id = str(uuid.uuid4())
    _insert_project(conn, project_id=sp1_id, name="הטייסים", plan_number="407-0977595")
    _insert_project(conn, project_id=sp2_id, name="צפון נס ציונה", plan_number="407-1048248")

    tk1_id = str(uuid.uuid4())
    tk2_id = str(uuid.uuid4())
    _insert_takanon(conn, takanon_id=tk1_id, project_id=sp1_id, version_label="approved-2024-01")
    _insert_takanon(conn, takanon_id=tk2_id, project_id=sp2_id, version_label="approved-2023-09")

    # Design plan project.
    dp_id = str(uuid.uuid4())
    raw_json = {
        "design_plan": {"name": "תכנית עיצוב הטייסים", "revision": "23.3"},
        "linked_statutory_plans": [
            {"plan_number": "407-0977595", "coverage_type": "primary"},
            {"plan_number": "407-1048248", "coverage_type": "partial"},
        ],
    }
    _insert_project(conn, project_id=dp_id, name="תכנית עיצוב הטייסים",
                    plan_number="DP-407-0977595-23.3", raw_json=raw_json)

    conn.execute(
        """INSERT INTO project_takanon_links (id, project_id, takanon_id, coverage_type)
           VALUES (?, ?, ?, ?), (?, ?, ?, ?)""",
        (str(uuid.uuid4()), dp_id, tk1_id, "primary",
         str(uuid.uuid4()), dp_id, tk2_id, "partial"),
    )

    # Rules — `rule_id` in the violations table is the rule_code (per the
    # persistence layer's convention), so we just need rule_code rows here.
    rules_spec = [
        (_R_HEIGHT,  RuleType.NUMERIC,           tk1_id),
        (_R_SETBACK, RuleType.GEOMETRIC,         tk1_id),
        (_R_UNITS,   RuleType.NUMERIC,           tk1_id),
        (_R_FAR,     RuleType.NUMERIC,           tk1_id),
        (_R_PARKING, RuleType.NUMERIC,           tk2_id),
        (_R_FACADE,  RuleType.QUALITATIVE,       tk1_id),
        (_R_DOC1,    RuleType.DOCUMENT_PRESENCE, tk1_id),
        (_R_DOC2,    RuleType.DOCUMENT_PRESENCE, tk2_id),
        (_R_PROC,    RuleType.PROCEDURAL,        tk1_id),
    ]
    for code, rtype, tk in rules_spec:
        _insert_rule(conn, rule_id_uuid=str(uuid.uuid4()),
                     project_id=dp_id, takanon_version_id=tk,
                     rule_code=code, rule_type=rtype)

    # Engine run.
    engine_run_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO engine_runs
             (id, project_id, engine_version, submission_version, status,
              triggered_by, started_at, completed_at, summary_stats_json)
           VALUES (?, ?, ?, ?, 'complete', 'manual',
                   '2026-05-02 09:15:00', '2026-05-02 09:15:08',
                   '{"total_violations": 20}')""",
        (engine_run_id, dp_id, "0.3.0", "submission-23.3"),
    )

    # Violations — 20 rows covering all 7 verdicts across 3 parcels.
    # parcel_1 — mostly clean
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 101",
                      rule_id=_R_HEIGHT, rule_type=RuleType.NUMERIC,
                      verdict=Verdict.PASS,
                      expected_value={"operator": "<=", "threshold": 24.0, "unit": "m"},
                      actual_value=22.5)
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 101",
                      rule_id=_R_UNITS, rule_type=RuleType.NUMERIC,
                      verdict=Verdict.PASS,
                      expected_value={"operator": "<=", "threshold": 12, "unit": "units"},
                      actual_value=10)
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 101",
                      rule_id=_R_PARKING, rule_type=RuleType.NUMERIC,
                      verdict=Verdict.PASS_WITH_NOTE,
                      expected_value={"operator": ">=", "threshold": 1.0, "unit": "spaces/unit"},
                      actual_value=1.0,
                      notes="חניה במינימום הנדרש; מומלץ להוסיף עמדת טעינה לרכב חשמלי.")
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 101",
                      rule_id=_R_DOC1, rule_type=RuleType.DOCUMENT_PRESENCE,
                      verdict=Verdict.PASS,
                      expected_value={"document": "נספח הידרולוגי"},
                      actual_value=True)
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 101",
                      rule_id=_R_FACADE, rule_type=RuleType.QUALITATIVE,
                      verdict=Verdict.REQUIRES_REVIEW,
                      notes="האם הכרכוב התואם לטיפוס המבנה הקיים בסביבה? (סעיף 5.3)",
                      confidence="low")
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 101",
                      rule_id=_R_PROC, rule_type=RuleType.PROCEDURAL,
                      verdict=Verdict.NOT_APPLICABLE,
                      notes="לא רלוונטי לתא שטח זה — אין שטחים ציבוריים.")

    # parcel_2 — failures + override + complex evidence
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 102",
                      rule_id=_R_HEIGHT, rule_type=RuleType.NUMERIC,
                      verdict=Verdict.FAIL,
                      expected_value="עד 6 קומות",
                      actual_value="8 קומות",
                      evidence={
                          "source_file": "design-plan.pdf",
                          "page": 12,
                          "bbox": [120, 480, 360, 510],
                          "excerpt": "גובה מבנה — 8 קומות עפ\"י תכנית קומה 7",
                      },
                      notes="המידות בתשריט אינן תואמות את המופיע בתקנון, נדרש תיקון לפני אישור.")
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 102",
                      rule_id=_R_UNITS, rule_type=RuleType.NUMERIC,
                      verdict=Verdict.FAIL,
                      expected_value={"operator": "<=", "threshold": 12, "unit": "units"},
                      actual_value=14,
                      is_override_applied=True,
                      confidence="low",
                      notes="הוחלפה החלטה הנדסית — מאושרות 14 יח״ד בכפוף להיקף שטחים ציבוריים.")
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 102",
                      rule_id=_R_SETBACK, rule_type=RuleType.GEOMETRIC,
                      verdict=Verdict.FAIL_BORDERLINE,
                      expected_value={"operator": ">=", "threshold": 5.0, "unit": "m"},
                      actual_value=4.85,
                      notes="חריגה בסף סטייה מקובל (3% מתחת לדרישה).")
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 102",
                      rule_id=_R_FAR, rule_type=RuleType.NUMERIC,
                      verdict=Verdict.FAIL,
                      expected_value={"operator": "<=", "threshold": 2.5, "unit": "ratio"},
                      actual_value=2.78,
                      notes="חריגה ב-FAR.")
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 102",
                      rule_id=_R_PARKING, rule_type=RuleType.NUMERIC,
                      verdict=Verdict.UNEVALUABLE,
                      notes="לא נמצא בנספח החניה ספירת מקומות מפורטת.")
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 102",
                      rule_id=_R_DOC2, rule_type=RuleType.DOCUMENT_PRESENCE,
                      verdict=Verdict.PASS,
                      expected_value={"document": "נספח נוף"},
                      actual_value=True)
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 102",
                      rule_id=_R_FACADE, rule_type=RuleType.QUALITATIVE,
                      verdict=Verdict.PASS_WITH_NOTE,
                      notes="חיפוי אבן תואם להנחיות המרחב הציבורי.",
                      confidence="medium")
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 102",
                      rule_id=_R_PROC, rule_type=RuleType.PROCEDURAL,
                      verdict=Verdict.NOT_APPLICABLE)

    # parcel_3 — borderline + review-heavy
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 103",
                      rule_id=_R_HEIGHT, rule_type=RuleType.NUMERIC,
                      verdict=Verdict.PASS,
                      expected_value={"operator": "<=", "threshold": 24.0, "unit": "m"},
                      actual_value=23.0)
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 103",
                      rule_id=_R_UNITS, rule_type=RuleType.NUMERIC,
                      verdict=Verdict.PASS,
                      expected_value={"operator": "<=", "threshold": 12, "unit": "units"},
                      actual_value=11)
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 103",
                      rule_id=_R_SETBACK, rule_type=RuleType.GEOMETRIC,
                      verdict=Verdict.FAIL_BORDERLINE,
                      expected_value={"operator": ">=", "threshold": 5.0, "unit": "m"},
                      actual_value=4.92,
                      notes="חריגה זניחה — בסף הסטייה.")
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 103",
                      rule_id=_R_DOC1, rule_type=RuleType.DOCUMENT_PRESENCE,
                      verdict=Verdict.UNEVALUABLE,
                      notes="הנספח קיים אך לא ניתן לקרוא את גוף המסמך (קובץ פגום).")
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 103",
                      rule_id=_R_FACADE, rule_type=RuleType.QUALITATIVE,
                      verdict=Verdict.REQUIRES_REVIEW,
                      notes="התאמת חזית לרחוב — נדרשת בחינת מהנדס לאור הנחיית המרחב.",
                      confidence="low")
    _insert_violation(conn, engine_run_id=engine_run_id, parcel_id="תא שטח 103",
                      rule_id=_R_PROC, rule_type=RuleType.PROCEDURAL,
                      verdict=Verdict.PASS)

    conn.commit()
    return conn, engine_run_id


def build_run_with_engine_errors() -> tuple[sqlite3.Connection, str]:
    """Variant of build_synthetic_run() that injects a swarm of identical
    engine errors. Three violations on three different parcels share the
    same error_fingerprint so the cluster banner fires; failure_mode is
    ENGINE_ERROR so the system-health warning also fires.

    Used by the PDF tests + the sample-PDF script."""
    conn, engine_run_id = build_synthetic_run()

    # Same exception-style fingerprint repeated across 3 parcels: the
    # PDF generator should fold them into a single cluster banner AND
    # surface the system-health warning.
    fp = "deadbeefcafe1234"
    sample_note = (
        "evaluator raised KeyError: 'numeric_values'\n"
        "  File \"src/compliance/evaluators/numeric.py\", line 47\n"
        "    actual = numeric_values[field_name]"
    )
    # Five same-fingerprint rows distributed so:
    #   - run-level count is 5 (well over the cluster threshold of 3)
    #   - תא שטח 102 has 3 of them, so the per-parcel cluster banner fires
    #     for that parcel
    #   - the other two parcels have one each, which renders as a normal
    #     single row (with the inline failure-mode pill)
    for parcel_id, rule_code in [
        ("תא שטח 101", "ENG_ERR_HEIGHT"),
        ("תא שטח 102", "ENG_ERR_SETBACK"),
        ("תא שטח 102", "ENG_ERR_FAR"),
        ("תא שטח 102", "ENG_ERR_PARKING"),
        ("תא שטח 103", "ENG_ERR_UNITS"),
    ]:
        _insert_violation(
            conn, engine_run_id=engine_run_id, parcel_id=parcel_id,
            rule_id=rule_code, rule_type=RuleType.NUMERIC,
            verdict=Verdict.UNEVALUABLE,
            failure_mode="engine_error",
            error_fingerprint=fp,
            notes=sample_note,
        )
    conn.commit()
    return conn, engine_run_id


def build_run_with_only_missing_data() -> tuple[sqlite3.Connection, str]:
    """Variant with only MISSING_DATA failures — the system-health
    warning must NOT fire (warning is gated on engine_error count)."""
    conn, engine_run_id = build_synthetic_run()
    # Three missing-data unevaluables — fingerprints differ so they don't
    # cluster either.
    for i, parcel_id in enumerate(("תא שטח 101", "תא שטח 102", "תא שטח 103")):
        _insert_violation(
            conn, engine_run_id=engine_run_id, parcel_id=parcel_id,
            rule_id=f"MISSING_DATA_RULE_{i}", rule_type=RuleType.NUMERIC,
            verdict=Verdict.UNEVALUABLE,
            failure_mode="missing_data",
            error_fingerprint=f"missing-fp-{i}",
            notes=f"no extracted numeric value for field_{i}",
        )
    conn.commit()
    return conn, engine_run_id


def build_empty_run() -> tuple[sqlite3.Connection, str]:
    """Build a DB with one project + one engine_run and zero violations.
    Used for the empty-run smoke test."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    _make_schema(conn)

    sp_id = str(uuid.uuid4())
    _insert_project(conn, project_id=sp_id, name="הטייסים", plan_number="407-0977595")
    tk_id = str(uuid.uuid4())
    _insert_takanon(conn, takanon_id=tk_id, project_id=sp_id, version_label="approved-2024-01")

    dp_id = str(uuid.uuid4())
    _insert_project(conn, project_id=dp_id, name="תכנית עיצוב ריקה",
                    plan_number="DP-EMPTY",
                    raw_json={
                        "design_plan": {"name": "תכנית עיצוב ריקה", "revision": "1.0"},
                        "linked_statutory_plans": [{"plan_number": "407-0977595"}],
                    })
    conn.execute(
        """INSERT INTO project_takanon_links (id, project_id, takanon_id, coverage_type)
           VALUES (?, ?, ?, 'primary')""",
        (str(uuid.uuid4()), dp_id, tk_id),
    )

    engine_run_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO engine_runs
             (id, project_id, engine_version, submission_version, status,
              triggered_by, started_at, completed_at, summary_stats_json)
           VALUES (?, ?, '0.3.0', 'v1', 'complete', 'manual',
                   '2026-05-02 09:00:00', '2026-05-02 09:00:01',
                   '{"total_violations": 0}')""",
        (engine_run_id, dp_id),
    )
    conn.commit()
    return conn, engine_run_id
