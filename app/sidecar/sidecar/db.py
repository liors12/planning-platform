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
    # check_same_thread=False (F-3): SQLAlchemy's pool hands each connection
    # to one thread at a time, but POOL TEARDOWN may close it from a
    # different thread (uvicorn/queue-worker thread pools) - sqlcipher3's
    # same-thread guard turned every such close into a noisy
    # ProgrammingError in the logs during engine runs. Cross-thread CLOSE of
    # an idle connection is safe; concurrent USE is still prevented by the
    # pool's checkout discipline.
    conn = _sqlite_backend.connect(str(db_path), isolation_level=None,
                                   check_same_thread=False)
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
    from sqlalchemy.pool import QueuePool
    engine = create_engine(
        "sqlite://",
        creator=lambda: _connect(db_path, key),
        # We manage pragmas ourselves on each connection; turn off SQLAlchemy's
        # default opinionated isolation handling.
        connect_args={},
        # The "sqlite://" URL looks in-memory to SQLAlchemy, which defaults
        # to SingletonThreadPool - ONE shared connection. Combined with
        # check_same_thread=False (the F-3 fix) that let uvicorn/queue
        # threads share and close each other's connection ("Cannot operate
        # on a closed database" storms on the stdlib-sqlite3 backend).
        # A real pool gives every checkout its own connection.
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
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

    # Addendum-8 migration - merge the legacy "הערות אדריכלית העיר"
    # discipline into "אדריכלות וחזיתות" (same discipline in Ellen's
    # practice). Idempotent: after the first pass no rows carry a legacy
    # key. Alias map lives with the canonical list.
    from .disciplines import LEGACY_DISCIPLINE_ALIASES
    with engine.begin() as conn:
        dc_exists = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='discipline_comments'"
        )).fetchone()
        if dc_exists:
            for old_key, new_key in LEGACY_DISCIPLINE_ALIASES.items():
                res = conn.execute(text(
                    "UPDATE discipline_comments SET discipline_key = :new "
                    "WHERE discipline_key = :old"
                ), {"new": new_key, "old": old_key})
                if res.rowcount:
                    log.info("migration: remapped %d discipline_comments rows %s -> %s",
                             res.rowcount, old_key, new_key)

    # Full-seed migration - document-structure columns on guidelines.
    with engine.begin() as conn:
        g_exists = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='guidelines'"
        )).fetchone()
        if g_exists:
            g_cols = {c[1] for c in conn.execute(text("PRAGMA table_info(guidelines)")).fetchall()}
            for col, decl in (("section_key", "TEXT"), ("section_title", "TEXT"),
                              ("sort_order", "INTEGER"),
                              ("discipline_key", "TEXT"),   # v0.2.0
                              ("origin", "TEXT")):          # v0.2.0 (מינהלת additions)
                if col not in g_cols:
                    conn.execute(text(f"ALTER TABLE guidelines ADD COLUMN {col} {decl}"))
                    log.info("migration: added %s to guidelines", col)

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


def _seed_json_path() -> Path:
    """Locate seed/guidelines_seed.json, PyInstaller-aware."""
    import sys as _sys
    if getattr(_sys, "frozen", False):
        meipass = getattr(_sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "seed" / "guidelines_seed.json"
    return Path(__file__).resolve().parent.parent / "seed" / "guidelines_seed.json"


def seed_guidelines(engine: Engine) -> None:
    """Seed the FULL municipal guidelines document (guidelines_seed.json).

    Collision policy (append-only, user edits sacred):
      * A row whose check_key matches an existing ACTIVE row ADOPTS that row:
        the existing row gets the document's section placement; its title/body
        are updated to the document text ONLY if it is an untouched seed row
        (version 1, edited_by='seed') - user-edited rows keep their text,
        values, version and history.
      * Legacy ACTIVE rows with no section placement and no match in the
        document (old demo rows) are deactivated (superseded; history kept).
      * Every document row not already present (identity: section_key +
        sort_order) is inserted as version 1.
    Fresh DBs take the same path - everything simply gets inserted.
    """
    import json as _json
    from sqlalchemy.orm import Session

    from .models import Guideline

    seed_path = _seed_json_path()
    if not seed_path.exists():
        log.warning("guidelines seed JSON missing at %s - skipping seed", seed_path)
        return
    data = _json.loads(seed_path.read_text(encoding="utf-8"))
    doc_rows = data["guidelines"]

    with Session(engine) as sess:
        existing = sess.query(Guideline).all()
        active_by_key = {g.check_key: g for g in existing if g.is_active and g.check_key}
        placed = {(g.section_key, g.sort_order) for g in existing if g.section_key}

        inserted = adopted = superseded = 0
        consumed_ids: set[int] = set()

        for row in doc_rows:
            key = row.get("check_key")
            if key and key in active_by_key:
                g = active_by_key[key]
                g.section_key = row["section_key"]
                g.section_title = row["section_title"]
                g.sort_order = row["sort_order"]
                g.discipline_key = row.get("discipline_key")
                if g.origin is None:
                    g.origin = row.get("origin")
                if g.version == 1 and (g.edited_by or "seed") == "seed":
                    g.title = row["title"]
                    g.body_text = row["body_text"]
                    g.unit = row.get("unit")
                    g.check_value = row.get("check_value")
                consumed_ids.add(g.id)
                adopted += 1
                continue
            if (row["section_key"], row["sort_order"]) in placed:
                continue
            sess.add(Guideline(
                discipline=row["section_title"],
                title=row["title"],
                body_text=row["body_text"],
                guideline_type=row["guideline_type"],
                check_key=row.get("check_key"),
                check_value=row.get("check_value"),
                unit=row.get("unit"),
                version=1,
                is_active=1,
                edited_by="seed",
                section_key=row["section_key"],
                section_title=row["section_title"],
                sort_order=row["sort_order"],
                discipline_key=row.get("discipline_key"),
                origin=row.get("origin"),
            ))
            inserted += 1

        # Deactivate leftover demo rows: active, unplaced, unconsumed.
        for g in existing:
            if g.is_active and not g.section_key and g.id not in consumed_ids:
                g.is_active = 0
                superseded += 1

        # v0.2.0 backfills on existing installs:
        # 1. חלק ח removed - deactivate its rows (never delete; user edits
        #    stay in history).
        # 2. discipline_key: match placed rows to the seed by
        #    (section_key, sort_order); anything still NULL → general.
        part_h_removed = 0
        by_place = {(r["section_key"], r["sort_order"]): r for r in doc_rows}
        backfilled = 0
        for g in existing:
            if g.is_active and g.section_key == "part_h":
                g.is_active = 0
                part_h_removed += 1
                continue
            if g.is_active and g.discipline_key is None:
                src = by_place.get((g.section_key, g.sort_order))
                g.discipline_key = (src or {}).get("discipline_key") or "general"
                backfilled += 1

        sess.commit()
        if inserted or adopted or superseded or part_h_removed or backfilled:
            log.info("guidelines seed: %d inserted, %d adopted, %d superseded, "
                     "%d part_h deactivated, %d discipline backfilled",
                     inserted, adopted, superseded, part_h_removed, backfilled)
