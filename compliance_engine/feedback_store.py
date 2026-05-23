"""SQLite-backed feedback store for discipline-manager comments.

Tables (see migrations/0001_feedback_tables.sql):
  - discipline_managers       — master list of 10 disciplines + contact info
  - feedback_requests         — one per (audit_run, discipline) — tracks status
  - feedback_entries          — actual comments, optionally tied to a rule_code
  - report_versions           — versioned PDF outputs (v1 = pre-feedback, v2+ = with feedback)

The DB lives at <project_root>/data/feedback.sqlite by default. Manage via
ensure_db_initialized() — that's the entry point UIs/scripts should call.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "data" / "feedback.sqlite"
MIGRATION_SQL = ROOT / "migrations" / "0001_feedback_tables.sql"

SEED_DISCIPLINES: list[tuple[str, str, str]] = [
    # (discipline_code, discipline_name_he, manager_name_he)
    ("shafa",    "שפ\"ע — אשפה ופינוי פסולת",       "אגף שפ\"ע"),
    ("gardens",  "גנים ונוף",                        "אגף גנים ונוף"),
    ("infra",    "תשתיות",                           "אגף בינוי פיתוח ותשתיות (אברהם הורן)"),
    ("fire",     "רחבות כיבוי אש",                    "תאגיד מים וביוב"),
    ("drainage", "ניקוז וחלחול",                     "תאגיד / הידרולוגיה (לביא נטיף)"),
    ("roofs",    "גגות וגינון על גג",                 "אגף אדריכלות"),
    ("arch",     "אדריכלות וחזיתות",                  "אדריכלית העיר (סמדר ירון)"),
    ("balcony",  "מרפסות",                           "אגף אדריכלות"),
    ("laundry",  "מסתורי כביסה",                     "אגף אדריכלות"),
    ("env",      "הנחיות סביבתיות",                   "יחידה סביבתית (לשם שפר איכות סביבה)"),
]


# ---------------------------------------------------------------------------
# DB lifecycle
# ---------------------------------------------------------------------------

@contextmanager
def connect(db_path: Path | None = None):
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_db_initialized(db_path: Path | None = None) -> Path:
    """Apply schema and seed discipline_managers. Idempotent."""
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    schema_sql = MIGRATION_SQL.read_text(encoding="utf-8")
    with connect(db_path) as conn:
        conn.executescript(schema_sql)
        seeded = conn.execute("SELECT COUNT(*) AS c FROM discipline_managers").fetchone()["c"]
        if seeded == 0:
            conn.executemany(
                "INSERT INTO discipline_managers (discipline_code, discipline_name_he, manager_name) VALUES (?, ?, ?)",
                SEED_DISCIPLINES,
            )
    return db_path


# ---------------------------------------------------------------------------
# Feedback queries
# ---------------------------------------------------------------------------

def list_disciplines(db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM discipline_managers WHERE active = 1 ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_feedback_request(
    audit_run_id: str,
    discipline_code: str,
    *,
    status: str = "pending",
    manager_id: int | None = None,
    db_path: Path | None = None,
) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO feedback_requests (audit_run_id, discipline_code, manager_id, status)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(audit_run_id, discipline_code) DO UPDATE SET status = excluded.status""",
            (audit_run_id, discipline_code, manager_id, status),
        )
        row = conn.execute(
            "SELECT id FROM feedback_requests WHERE audit_run_id = ? AND discipline_code = ?",
            (audit_run_id, discipline_code),
        ).fetchone()
        return int(row["id"])


def add_feedback_entry(
    audit_run_id: str,
    discipline_code: str,
    feedback_text_he: str,
    *,
    rule_code: str | None = None,
    verdict_override: str | None = None,
    supplementary_pages: Iterable[int] | None = None,
    created_by: str | None = None,
    db_path: Path | None = None,
) -> int:
    req_id = upsert_feedback_request(audit_run_id, discipline_code, status="received", db_path=db_path)
    pages_csv = ",".join(str(p) for p in (supplementary_pages or []))
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO feedback_entries
                 (feedback_request_id, rule_code, verdict_override, feedback_text_he,
                  supplementary_pages_csv, created_by)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (req_id, rule_code, verdict_override, feedback_text_he, pages_csv, created_by),
        )
        return int(cur.lastrowid)


def get_feedback_for_audit(audit_run_id: str, db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT fe.id, fr.discipline_code, fe.rule_code, fe.verdict_override,
                      fe.feedback_text_he, fe.supplementary_pages_csv, fe.created_at,
                      fe.approved_for_inclusion, dm.discipline_name_he, dm.manager_name
                 FROM feedback_entries fe
                 JOIN feedback_requests fr ON fr.id = fe.feedback_request_id
                 LEFT JOIN discipline_managers dm ON dm.discipline_code = fr.discipline_code
                WHERE fr.audit_run_id = ?
                  AND fe.approved_for_inclusion = 1
                ORDER BY fr.discipline_code, fe.id""",
            (audit_run_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def feedback_status_summary(audit_run_id: str, db_path: Path | None = None) -> dict:
    with connect(db_path) as conn:
        by_d = conn.execute(
            """SELECT dm.discipline_code, dm.discipline_name_he,
                      COALESCE(fr.status, 'pending') AS status,
                      COUNT(fe.id) AS feedback_count
                 FROM discipline_managers dm
                 LEFT JOIN feedback_requests fr
                        ON fr.discipline_code = dm.discipline_code AND fr.audit_run_id = ?
                 LEFT JOIN feedback_entries fe
                        ON fe.feedback_request_id = fr.id AND fe.approved_for_inclusion = 1
                WHERE dm.active = 1
                GROUP BY dm.discipline_code
                ORDER BY dm.id""",
            (audit_run_id,),
        ).fetchall()
        total = conn.execute(
            """SELECT COUNT(*) AS c FROM feedback_entries fe
                 JOIN feedback_requests fr ON fr.id = fe.feedback_request_id
                WHERE fr.audit_run_id = ? AND fe.approved_for_inclusion = 1""",
            (audit_run_id,),
        ).fetchone()["c"]
    return {
        "by_discipline": [dict(r) for r in by_d],
        "total_rules_with_feedback": total,
    }


# ---------------------------------------------------------------------------
# Report versioning
# ---------------------------------------------------------------------------

def record_report_version(
    audit_run_id: str,
    pdf_path: Path,
    *,
    feedback_snapshot_count: int = 0,
    is_final: bool = False,
    db_path: Path | None = None,
) -> int:
    with connect(db_path) as conn:
        next_ver = conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 AS n FROM report_versions WHERE audit_run_id = ?",
            (audit_run_id,),
        ).fetchone()["n"]
        cur = conn.execute(
            """INSERT INTO report_versions
                 (audit_run_id, version_number, pdf_path, feedback_snapshot_count, is_final)
               VALUES (?, ?, ?, ?, ?)""",
            (audit_run_id, int(next_ver), str(pdf_path), int(feedback_snapshot_count), 1 if is_final else 0),
        )
        return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Merge feedback into automated results
# ---------------------------------------------------------------------------

def merge_with_feedback(
    automated_results: list[dict],
    audit_run_id: str,
    *,
    db_path: Path | None = None,
) -> list[dict]:
    """For each result, attach any matching discipline-manager feedback.

    Match key is (rule_code,). If feedback has a `verdict_override`, the
    result's verdict is replaced and `verdict_source` set to
    "discipline_manager".
    """
    feedback = get_feedback_for_audit(audit_run_id, db_path=db_path)
    by_rule: dict[str, dict] = {}
    general_by_discipline: dict[str, list[dict]] = {}
    for fb in feedback:
        if fb["rule_code"]:
            by_rule[fb["rule_code"]] = fb
        else:
            general_by_discipline.setdefault(fb["discipline_code"], []).append(fb)

    merged: list[dict] = []
    for r in automated_results:
        new_r = dict(r)
        rc = new_r.get("rule_code")
        if rc and rc in by_rule:
            fb = by_rule[rc]
            new_r["feedback_text_he"] = fb["feedback_text_he"]
            new_r["feedback_discipline_name_he"] = fb["discipline_name_he"]
            if fb["verdict_override"]:
                new_r["verdict"] = fb["verdict_override"]
                new_r["verdict_source"] = "discipline_manager"
        merged.append(new_r)
    return merged
