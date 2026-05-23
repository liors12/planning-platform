-- Feedback workflow tables (SQLite). See compliance_engine/feedback_store.py.

CREATE TABLE IF NOT EXISTS discipline_managers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    discipline_code     TEXT NOT NULL UNIQUE,
    discipline_name_he  TEXT NOT NULL,
    manager_name        TEXT,
    manager_email       TEXT,
    manager_phone       TEXT,
    active              INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS feedback_requests (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_run_id        TEXT NOT NULL,
    discipline_code     TEXT NOT NULL,
    manager_id          INTEGER REFERENCES discipline_managers(id),
    status              TEXT NOT NULL DEFAULT 'pending',  -- pending / received / integrated
    sent_at             TEXT,
    received_at         TEXT,
    integrated_at       TEXT,
    notes               TEXT,
    UNIQUE(audit_run_id, discipline_code)
);

CREATE TABLE IF NOT EXISTS feedback_entries (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_request_id      INTEGER REFERENCES feedback_requests(id),
    rule_code                TEXT,           -- nullable: feedback on a rule or general
    verdict_override         TEXT,           -- nullable
    feedback_text_he         TEXT NOT NULL,
    supplementary_pages_csv  TEXT,           -- comma-separated page numbers
    created_at               TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by               TEXT,
    approved_for_inclusion   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS report_versions (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_run_id             TEXT NOT NULL,
    version_number           INTEGER NOT NULL,
    pdf_path                 TEXT NOT NULL,
    generated_at             TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    feedback_snapshot_count  INTEGER,
    is_final                 INTEGER NOT NULL DEFAULT 0,
    UNIQUE(audit_run_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_feedback_requests_audit ON feedback_requests(audit_run_id);
CREATE INDEX IF NOT EXISTS idx_feedback_entries_request ON feedback_entries(feedback_request_id);
CREATE INDEX IF NOT EXISTS idx_report_versions_audit ON report_versions(audit_run_id);
