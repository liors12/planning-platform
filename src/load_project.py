"""
Phase 0 — Project Loader

Loads a project schema JSON into the planning compliance SQLite database.

Usage:
    python src/load_project.py --schema project-schema-407-0977595-v2.json
    python src/load_project.py --schema <path> --db <path>
"""

import argparse
import json
import re
import sqlite3
import sys
import uuid
from pathlib import Path


SCHEMA_DDL = """
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
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_projects_plan_number ON projects(plan_number);

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

CREATE TABLE IF NOT EXISTS submissions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  version INTEGER NOT NULL,
  submitted_at TIMESTAMP,
  submitted_by TEXT,
  status TEXT DEFAULT 'pending',
  documents_json TEXT
);

-- Replaced 2026-05-01 (compliance persistence layer).
-- The previous shape keyed engine_runs off (submission_id, takanon_version_id)
-- and tracked sign-off state. The new shape keys off project_id directly and
-- tracks the run lifecycle (running → complete/failed) plus summary stats.
-- Submission tracking moves into submission_version (a string version label)
-- on the run row itself; the older `submissions` table is left in place for
-- file-storage tracking but is no longer FK'd from engine_runs.
CREATE TABLE IF NOT EXISTS engine_runs (
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
CREATE INDEX IF NOT EXISTS idx_engine_runs_project
  ON engine_runs(project_id, started_at DESC);

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

CREATE TABLE IF NOT EXISTS project_rule_exceptions (
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

-- Many-to-many link between a design plan (project) and the statutory plans
-- (takanon_versions) that govern its parcels. A תכנית עיצוב frequently spans
-- the boundary of multiple תב"עות; each תא שטח is tagged with its governing
-- takanon via parcels[].governing_takanon_id in the project schema JSON.
--
--   coverage_type:
--     primary             - the design plan's main governing plan
--     partial             - covers some תאי שטח only
--     adjacent_reference  - needed for context but doesn't govern any תא שטח
CREATE TABLE IF NOT EXISTS project_takanon_links (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  takanon_id TEXT NOT NULL REFERENCES takanon_versions(id),
  coverage_type TEXT NOT NULL CHECK (coverage_type IN ('primary', 'partial', 'adjacent_reference')),
  coverage_notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_takanon_links
  ON project_takanon_links(project_id, takanon_id);
CREATE INDEX IF NOT EXISTS idx_project_takanon_links_project
  ON project_takanon_links(project_id);

CREATE TABLE IF NOT EXISTS extracts (
  id TEXT PRIMARY KEY,
  engine_run_id TEXT NOT NULL REFERENCES engine_runs(id),
  rule_code TEXT NOT NULL,
  plot TEXT,
  extracted_value REAL,
  extracted_text TEXT,
  unit TEXT,
  evidence_json TEXT NOT NULL,
  confidence REAL NOT NULL,
  review_required INTEGER DEFAULT 0,
  review_reason TEXT
);

-- Replaced 2026-05-01 (compliance persistence layer).
-- The previous shape modeled violations as a workflow-tracking row with
-- severity/status/resolution_type/override fields. The new shape stores
-- the full evaluation result (one row per (parcel, rule) including passes)
-- with verdict CHECK constraint matching the new Verdict enum, polymorphic
-- expected/actual values stored as JSON, and a flat is_override_applied
-- bool for fast filtering. Override/sign-off bookkeeping moves to a
-- separate workflow layer (see Open Tasks).
CREATE TABLE IF NOT EXISTS violations (
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
  -- Failure-mode metadata: meaningful only when verdict='unevaluable'
  -- (else 'none'). The PDF generator clusters by error_fingerprint to
  -- collapse identical incidents. See docs/architecture/failure-modes
  -- (or CONTEXT.md → "Failure Mode Distinction") for the rationale.
  failure_mode TEXT NOT NULL DEFAULT 'none' CHECK (failure_mode IN (
    'engine_error', 'missing_data', 'ambiguous_rule',
    'extraction_failure', 'none'
  )),
  error_fingerprint TEXT,
  -- Reliability axis, orthogonal to verdict and failure_mode. All
  -- deterministic evaluators emit 'high'; the qualitative evaluator
  -- emits 'low' by default. See CONTEXT.md → "Confidence as an
  -- Orthogonal Axis" for the rationale.
  confidence TEXT NOT NULL DEFAULT 'high' CHECK (confidence IN (
    'high', 'medium', 'low'
  )),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_violations_run
  ON violations(engine_run_id);
CREATE INDEX IF NOT EXISTS idx_violations_run_verdict
  ON violations(engine_run_id, verdict);
CREATE INDEX IF NOT EXISTS idx_violations_run_parcel
  ON violations(engine_run_id, parcel_id);

CREATE TABLE IF NOT EXISTS generated_outputs (
  id TEXT PRIMARY KEY,
  engine_run_id TEXT NOT NULL REFERENCES engine_runs(id),
  output_type TEXT,
  file_path TEXT,
  generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  signed_by TEXT,
  signed_at TIMESTAMP,
  is_final INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dwg_layer_configs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  firm_name TEXT NOT NULL,
  layer_name TEXT NOT NULL,
  category TEXT NOT NULL,
  match_confidence REAL,
  confirmed_by TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rules_project ON rules(project_id);
CREATE INDEX IF NOT EXISTS idx_rules_takanon ON rules(takanon_version_id);
CREATE INDEX IF NOT EXISTS idx_rules_code ON rules(rule_code);
CREATE UNIQUE INDEX IF NOT EXISTS uq_rules_project_takanon_code
  ON rules(project_id, takanon_version_id, rule_code);
CREATE UNIQUE INDEX IF NOT EXISTS uq_takanon_project_label
  ON takanon_versions(project_id, version_label);
CREATE INDEX IF NOT EXISTS idx_extracts_run ON extracts(engine_run_id);
CREATE INDEX IF NOT EXISTS idx_violations_run ON violations(engine_run_id);
"""


# Strip line-leading `//` comments so the v2 schema parses as valid JSON.
# Only matches whitespace-prefixed `//` to end of line — safe for URLs in strings.
_LINE_COMMENT_RE = re.compile(r"^\s*//.*$", flags=re.MULTILINE)


def load_schema_file(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    cleaned = _LINE_COMMENT_RE.sub("", raw)
    return json.loads(cleaned)


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_DDL)
    conn.commit()


def insert_project(conn: sqlite3.Connection, schema: dict) -> str:
    """Idempotent on plan_number. Returns the project's UUID id."""
    proj = schema["project"]
    meta = proj["meta"]
    plan_number = meta["plan_number"]
    plots_json = json.dumps(
        [
            {k: v for k, v in p.items() if k != "geometry"}
            for p in proj.get("parcels", [])
        ],
        ensure_ascii=False,
    )
    scope_notes = meta.get("scope_out_reason")

    row = conn.execute(
        "SELECT id FROM projects WHERE plan_number = ?", (plan_number,)
    ).fetchone()
    if row:
        project_id = row[0]
        conn.execute(
            """UPDATE projects
               SET name = ?, approval_date = ?, status = ?,
                   plots_json = ?, scope_notes = ?
               WHERE id = ?""",
            (
                meta["plan_name"],
                meta.get("approval_date"),
                meta.get("status", "onboarding"),
                plots_json,
                scope_notes,
                project_id,
            ),
        )
    else:
        project_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO projects
               (id, name, plan_number, approval_date, status,
                plots_json, scope_notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id,
                meta["plan_name"],
                plan_number,
                meta.get("approval_date"),
                meta.get("status", "onboarding"),
                plots_json,
                scope_notes,
            ),
        )
    return project_id


def insert_takanon_version(
    conn: sqlite3.Connection, project_id: str, schema: dict
) -> str:
    """Idempotent on (project_id, version_label). Returns the takanon_version UUID."""
    meta = schema["project"]["meta"]
    version_label = f"approved_{meta['approval_date']}"
    # Prefer the local mirrored PDF (digital_files.takanon_pdf.path) so the
    # engine can resolve evidence pages without an HTTP fetch. Fall back to
    # the upstream URL in meta.takkanon_source if no local copy is registered.
    digital_files = schema["project"].get("digital_files", {}) or {}
    takanon_local = (digital_files.get("takanon_pdf") or {}).get("path")
    pdf_path = takanon_local or meta.get("takkanon_source")

    row = conn.execute(
        "SELECT id FROM takanon_versions WHERE project_id = ? AND version_label = ?",
        (project_id, version_label),
    ).fetchone()
    if row:
        version_id = row[0]
        conn.execute(
            """UPDATE takanon_versions
               SET effective_date = ?, pdf_path = ?, status = 'confirmed'
               WHERE id = ?""",
            (meta["approval_date"], pdf_path, version_id),
        )
    else:
        version_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO takanon_versions
               (id, project_id, version_label, effective_date, pdf_path, status)
               VALUES (?, ?, ?, ?, ?, 'confirmed')""",
            (version_id, project_id, version_label, meta["approval_date"], pdf_path),
        )

    conn.execute(
        "UPDATE projects SET active_takanon_version_id = ? WHERE id = ?",
        (version_id, project_id),
    )
    return version_id


def insert_rules(
    conn: sqlite3.Connection,
    project_id: str,
    takanon_version_id: str,
    schema: dict,
) -> int:
    """Idempotent on (project_id, takanon_version_id, rule_code)."""
    rules = schema["project"].get("compliance_rules", [])
    count = 0
    for r in rules:
        threshold = r.get("threshold")
        if isinstance(threshold, bool):
            # bool is a subclass of int — coerce to 1.0/0.0 explicitly
            threshold_real = float(int(threshold))
            threshold_text = None
        elif isinstance(threshold, (int, float)):
            threshold_real = float(threshold)
            threshold_text = None
        elif threshold is None:
            threshold_real = None
            threshold_text = None
        else:
            threshold_real = None
            threshold_text = str(threshold)

        existing = conn.execute(
            """SELECT id FROM rules
               WHERE project_id = ? AND takanon_version_id = ? AND rule_code = ?""",
            (project_id, takanon_version_id, r["rule_code"]),
        ).fetchone()

        if existing:
            rule_id = existing[0]
            conn.execute(
                """UPDATE rules
                   SET rule_type = ?, section = ?, plot = ?, operator = ?,
                       threshold = ?, threshold_text = ?, unit = ?,
                       source_quote = ?, source_page = ?, description = ?,
                       severity_if_violated = ?, review_status = ?,
                       is_active = 1, raw_json = ?
                   WHERE id = ?""",
                (
                    r["rule_type"],
                    r.get("source_section"),
                    r.get("parcel_id"),
                    r.get("operator"),
                    threshold_real,
                    threshold_text,
                    r.get("unit"),
                    r.get("source_quote"),
                    r.get("source_page"),
                    r.get("description"),
                    r.get("severity_if_violated"),
                    r.get("review_status", "pending"),
                    json.dumps(r, ensure_ascii=False),
                    rule_id,
                ),
            )
        else:
            rule_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO rules
                   (id, project_id, takanon_version_id, rule_code, rule_type,
                    section, plot, operator, threshold, threshold_text, unit,
                    source_quote, source_page, description, severity_if_violated,
                    review_status, is_active, raw_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    rule_id,
                    project_id,
                    takanon_version_id,
                    r["rule_code"],
                    r["rule_type"],
                    r.get("source_section"),
                    r.get("parcel_id"),
                    r.get("operator"),
                    threshold_real,
                    threshold_text,
                    r.get("unit"),
                    r.get("source_quote"),
                    r.get("source_page"),
                    r.get("description"),
                    r.get("severity_if_violated"),
                    r.get("review_status", "pending"),
                    json.dumps(r, ensure_ascii=False),
                ),
            )
        count += 1
    return count


def main() -> int:
    here = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Load project schema into SQLite")
    parser.add_argument(
        "--schema",
        required=True,
        help="Path to project-schema JSON (relative paths resolve from project root)",
    )
    parser.add_argument(
        "--db",
        default=str(here / "data" / "planning.db"),
        help="Path to SQLite database file (default: data/planning.db)",
    )
    args = parser.parse_args()

    schema_path = Path(args.schema)
    if not schema_path.is_absolute():
        # Try as-is first, then relative to project root.
        if not schema_path.exists():
            schema_path = here / args.schema

    if not schema_path.exists():
        print(f"ERROR: schema file not found: {schema_path}", file=sys.stderr)
        return 1

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    schema = load_schema_file(schema_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        init_db(conn)
        project_id = insert_project(conn, schema)
        takanon_version_id = insert_takanon_version(conn, project_id, schema)
        rule_count = insert_rules(conn, project_id, takanon_version_id, schema)
        conn.commit()
    finally:
        conn.close()

    plot_count = len(schema["project"].get("parcels", []))
    plan_number = schema["project"]["meta"]["plan_number"]
    print(
        f"Loaded project {plan_number}: {plot_count} plots, {rule_count} rules"
    )
    print(f"  project_id (UUID): {project_id}")
    print(f"  takanon_version_id: {takanon_version_id}")
    print(f"  database: {db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
