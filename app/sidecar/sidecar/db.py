"""SQLCipher-encrypted SQLite with WAL mode.

Uses sqlcipher3 (a fork of pysqlite3 linked against libsqlcipher) as the DB-API
driver. SQLAlchemy is wired up via a custom `creator=` so the engine reuses
the same pragmas on every new connection — necessary because SQLCipher's key
PRAGMA must run on each connection, before any other query.

Phase 1 just initializes the file with WAL + a stub `app_metadata` row so we
can prove the encrypted store is round-tripping. Real ORM models land in
Phase 2 (Module A).
"""
from __future__ import annotations

import logging
from pathlib import Path

# SQLCipher is preferred for at-rest encryption (spec § 8), but it has no
# Windows wheels on PyPI. For the pilot Windows installer we fall back to
# stdlib sqlite3 (no encryption at rest). Phase 4 — when Ellen-PIN-derived
# keys land — will require a real Windows SQLCipher story (vcpkg / bundled
# DLL). The Phase 1 dev key "phase1-dev-key-DO-NOT-SHIP" was never real
# security anyway, so for the pilot installer this is acceptable.
try:
    import sqlcipher3 as _sqlite_backend  # type: ignore[import-not-found]
    _BACKEND_NAME = "sqlcipher3"
except ImportError:  # pragma: no cover — Windows pilot fallback
    import sqlite3 as _sqlite_backend
    _BACKEND_NAME = "sqlite3 (no encryption)"

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)


def _quote_key(key: str) -> str:
    """PRAGMA key requires the value as a quoted SQL string literal.

    Single quotes inside the key are escaped per SQLite literal-string rules.
    """
    escaped = key.replace("'", "''")
    return f"'{escaped}'"


def _connect(db_path: Path, key: str):
    """Open one connection with WAL + sensible pragmas.

    With sqlcipher3: applies PRAGMA key + cipher_compatibility first.
    With stdlib sqlite3 (Windows fallback): skips encryption pragmas.
    """
    conn = _sqlite_backend.connect(str(db_path), isolation_level=None)
    cur = conn.cursor()
    if _BACKEND_NAME == "sqlcipher3":
        # Key must be the very first statement on a fresh connection.
        cur.execute(f"PRAGMA key = {_quote_key(key)};")
        # cipher_compatibility=4 matches the SQLCipher 4 default (AES-256-CBC + HMAC-SHA512).
        cur.execute("PRAGMA cipher_compatibility = 4;")
    else:
        log.warning("DB backend: %s — DB at %s will NOT be encrypted at rest",
                    _BACKEND_NAME, db_path)
    # WAL = better concurrency + crash recovery; required by spec § 5.
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("PRAGMA foreign_keys = ON;")
    cur.close()
    return conn


def build_engine(db_path: Path, key: str) -> Engine:
    """Build a SQLAlchemy Engine bound to an encrypted SQLite at `db_path`."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        "sqlite://",
        creator=lambda: _connect(db_path, key),
        # We manage pragmas ourselves on each connection; turn off SQLAlchemy's
        # default opinionated isolation handling.
        connect_args={},
        future=True,
    )
    return engine


def initialize(engine: Engine) -> dict:
    """Run minimal first-boot setup.

    Creates the `app_metadata` table (singleton row), the `audit_log` skeleton
    (spec § 6), and the ORM-managed tables (`projects` etc.). Returns a status
    dict for the /health endpoint.
    """
    from .config import VERSION
    from .models import Base

    # ORM tables come up via metadata.create_all — Phase 2 introduces Alembic
    # once the schema starts evolving.
    Base.metadata.create_all(engine)

    # ─── Phase 2a polish — items 1: tava_number unique among active projects.
    #
    # Cleanup pass (idempotent): if multiple non-archived rows share the same
    # tava_number, keep the OLDEST and delete the rest. CASCADE drops their
    # submissions + jobs.
    #
    # Then a partial UNIQUE INDEX enforces the constraint going forward.
    # Archived projects are deliberately excluded — re-using a tava after
    # archiving the previous occupant is legitimate.
    with engine.begin() as conn:
        # Delete duplicate active rows, keeping the oldest per tava_number.
        deleted = conn.execute(text(
            """
            DELETE FROM projects
             WHERE id IN (
                 SELECT p1.id
                   FROM projects p1
                  WHERE p1.status != 'archived'
                    AND EXISTS (
                        SELECT 1 FROM projects p2
                         WHERE p2.tava_number = p1.tava_number
                           AND p2.status != 'archived'
                           AND p2.created_at < p1.created_at
                    )
             )
            """
        )).rowcount
        if deleted:
            log.warning("dedupe migration: deleted %d duplicate active projects "
                        "(kept oldest per tava_number)", deleted)
        # Partial unique index. The expression matches the constraint we want
        # to enforce: tava_number unique only when status != 'archived'.
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_active_tava "
            "ON projects (tava_number) WHERE status != 'archived'"
        ))

    # C1 migration — add workflow_stage to submissions for existing DBs.
    # SQLite doesn't support ADD COLUMN IF NOT EXISTS, so we probe first.
    with engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(submissions)")).fetchall()
        if "workflow_stage" not in {c[1] for c in cols}:
            conn.execute(text(
                "ALTER TABLE submissions ADD COLUMN "
                "workflow_stage TEXT NOT NULL DEFAULT 'draft'"
            ))
            log.info("migration: added workflow_stage column to submissions")

    # A1 migration — submission_attachments table (handled by create_all for
    # fresh installs; for existing DBs create_all is idempotent via IF NOT EXISTS).
    # No ALTER TABLE needed: create_all only creates missing tables.

    # re-audit prerequisites migration — add pdf_hash / cad_hash / source_submission_id.
    with engine.begin() as conn:
        cols = {c[1] for c in conn.execute(text("PRAGMA table_info(submissions)")).fetchall()}
        for col in ("pdf_hash", "cad_hash", "source_submission_id"):
            if col not in cols:
                conn.execute(text(f"ALTER TABLE submissions ADD COLUMN {col} TEXT"))
                log.info("migration: added %s column to submissions", col)

    # B3 migration — add topic_he/finding_status/description to response_rows
    # for existing DBs that were created under the B2 schema.
    with engine.begin() as conn:
        rr_exists = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='response_rows'"
        )).fetchone()
        if rr_exists:
            rr_cols = {c[1] for c in conn.execute(
                text("PRAGMA table_info(response_rows)")).fetchall()}
            for col in ("topic_he", "finding_status", "description"):
                if col not in rr_cols:
                    conn.execute(text(f"ALTER TABLE response_rows ADD COLUMN {col} TEXT"))
                    log.info("migration: added %s to response_rows", col)

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS app_metadata (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                schema_version TEXT NOT NULL,
                sidecar_version TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_started_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT (datetime('now')),
                actor TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT
            )
        """))
        # Singleton upsert: insert on first boot, update on subsequent boots.
        existing = conn.execute(text("SELECT id FROM app_metadata WHERE id = 1")).first()
        if existing is None:
            conn.execute(text("""
                INSERT INTO app_metadata (id, schema_version, sidecar_version)
                VALUES (1, '0.1.0', :v)
            """), {"v": VERSION})
            conn.execute(text("""
                INSERT INTO audit_log (actor, event_type, payload_json)
                VALUES ('sidecar', 'db_initialized', :p)
            """), {"p": '{"schema_version":"0.1.0"}'})
        else:
            conn.execute(text("""
                UPDATE app_metadata
                   SET last_started_at = datetime('now'),
                       sidecar_version = :v
                 WHERE id = 1
            """), {"v": VERSION})

        # Verify journal mode actually took (WAL might not stick on some FS).
        journal_mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        # PRAGMA cipher_version is SQLCipher-only. Under stdlib sqlite3
        # (Windows pilot fallback) the statement parses cleanly but returns
        # zero rows — and .scalar() on a row-less result raises
        # ResourceClosedError. Gate the probe on the backend we detected at
        # import time so the encrypted-on-Mac signal stays visible without
        # crashing the unencrypted-on-Windows boot.
        if _BACKEND_NAME.startswith("sqlcipher"):
            cipher_version = conn.execute(text("PRAGMA cipher_version")).scalar()
        else:
            cipher_version = None
        # Raw SQLite library version (distinct from SQLCipher's cipher_version
        # and from our app schema_version). Phase 1 § React-UI deliverable.
        sqlite_version = conn.execute(text("SELECT sqlite_version()")).scalar()

    return {
        "journal_mode": journal_mode,
        "cipher_version": cipher_version,
        "sqlite_version": sqlite_version,
    }
