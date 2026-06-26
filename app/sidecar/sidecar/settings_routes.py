"""Settings endpoints — GET/PUT /settings.

GET /settings  → {anthropic_api_key_set, gemini_api_key_set, gemini_backup_count}
                 (never echoes key values)
PUT /settings  → stores keys in DB, injects into os.environ, returns same shape

Gemini key rotation: vision_scanner.config reads GEMINI_API_KEY +
GEMINI_API_KEY_BACKUP_1/2/3 from os.environ in priority order. Storing up to
4 keys here gives the sidecar automatic fallback on quota errors.

The DB is plaintext sqlite3 (no SQLCipher on Windows); only boolean presence
is exposed via the API.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .models import Settings

_ANTHROPIC_KEY_NAME = "anthropic_api_key"

# Gemini key DB names → env var names (same order as vision_scanner.config)
_GEMINI_KEY_MAP: list[tuple[str, str]] = [
    ("gemini_api_key",          "GEMINI_API_KEY"),
    ("gemini_api_key_backup_1", "GEMINI_API_KEY_BACKUP_1"),
    ("gemini_api_key_backup_2", "GEMINI_API_KEY_BACKUP_2"),
    ("gemini_api_key_backup_3", "GEMINI_API_KEY_BACKUP_3"),
]


class SettingsOut(BaseModel):
    anthropic_api_key_set: bool
    gemini_api_key_set: bool
    gemini_backup_count: int  # number of backup slots that are filled (0–3)


class SettingsPutPayload(BaseModel):
    anthropic_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_api_key_backup_1: Optional[str] = None
    gemini_api_key_backup_2: Optional[str] = None
    gemini_api_key_backup_3: Optional[str] = None


def _read_out(sess: Session) -> SettingsOut:
    anthropic_row = sess.get(Settings, _ANTHROPIC_KEY_NAME)
    gemini_primary = sess.get(Settings, "gemini_api_key")
    backup_count = sum(
        1
        for db_name, _ in _GEMINI_KEY_MAP[1:]
        if (r := sess.get(Settings, db_name)) is not None and bool(r.value)
    )
    return SettingsOut(
        anthropic_api_key_set=anthropic_row is not None and bool(anthropic_row.value),
        gemini_api_key_set=gemini_primary is not None and bool(gemini_primary.value),
        gemini_backup_count=backup_count,
    )


def _upsert(sess: Session, db_name: str, value: str) -> None:
    row = sess.get(Settings, db_name)
    if row is None:
        sess.add(Settings(key=db_name, value=value))
    else:
        row.value = value


def _inject_env(env_var: str, value: str) -> None:
    if value:
        os.environ[env_var] = value
    elif env_var in os.environ:
        del os.environ[env_var]


def make_router(get_engine: Callable[[], Engine]) -> APIRouter:
    router = APIRouter()

    @router.get("/settings", response_model=SettingsOut)
    def get_settings() -> SettingsOut:
        with Session(get_engine()) as sess:
            return _read_out(sess)

    @router.put("/settings", response_model=SettingsOut)
    def put_settings(body: SettingsPutPayload) -> SettingsOut:
        with Session(get_engine()) as sess:
            if body.anthropic_api_key is not None:
                key = body.anthropic_api_key.strip()
                _upsert(sess, _ANTHROPIC_KEY_NAME, key)
                _inject_env("ANTHROPIC_API_KEY", key)

            gemini_values = [
                body.gemini_api_key,
                body.gemini_api_key_backup_1,
                body.gemini_api_key_backup_2,
                body.gemini_api_key_backup_3,
            ]
            for (db_name, env_var), raw in zip(_GEMINI_KEY_MAP, gemini_values):
                if raw is not None:
                    value = raw.strip()
                    _upsert(sess, db_name, value)
                    _inject_env(env_var, value)

            sess.commit()
            return _read_out(sess)

    return router


def load_settings(engine: Engine) -> None:
    """Inject all persisted API keys into os.environ at sidecar startup.

    Called once from main.py before the first request is served, so every
    subsequent import of os.environ (including vision_scanner.config's
    load_gemini_keys()) already sees the persisted values.
    """
    with Session(engine) as sess:
        anthropic_row = sess.get(Settings, _ANTHROPIC_KEY_NAME)
        if anthropic_row is not None and anthropic_row.value:
            os.environ["ANTHROPIC_API_KEY"] = anthropic_row.value

        for db_name, env_var in _GEMINI_KEY_MAP:
            row = sess.get(Settings, db_name)
            if row is not None and row.value:
                os.environ[env_var] = row.value
