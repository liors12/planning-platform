"""Settings endpoints — GET/PUT /settings.

GET /settings  → {anthropic_api_key_set: bool}  (never echoes the key value)
PUT /settings  → stores key in DB, injects into os.environ, returns same shape

The DB is plaintext sqlite3 (no SQLCipher on Windows); the API honest-labels
this in comments and the frontend. Only boolean presence is exposed.
"""
from __future__ import annotations

import os
from typing import Callable

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .models import Settings

_ANTHROPIC_KEY_NAME = "anthropic_api_key"


class SettingsOut(BaseModel):
    anthropic_api_key_set: bool


class SettingsPutPayload(BaseModel):
    anthropic_api_key: str


def make_router(get_engine: Callable[[], Engine]) -> APIRouter:
    router = APIRouter()

    @router.get("/settings", response_model=SettingsOut)
    def get_settings() -> SettingsOut:
        with Session(get_engine()) as sess:
            row = sess.get(Settings, _ANTHROPIC_KEY_NAME)
            return SettingsOut(anthropic_api_key_set=row is not None and bool(row.value))

    @router.put("/settings", response_model=SettingsOut)
    def put_settings(body: SettingsPutPayload) -> SettingsOut:
        key = body.anthropic_api_key.strip()
        with Session(get_engine()) as sess:
            row = sess.get(Settings, _ANTHROPIC_KEY_NAME)
            if row is None:
                row = Settings(key=_ANTHROPIC_KEY_NAME, value=key)
                sess.add(row)
            else:
                row.value = key
            sess.commit()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
        elif "ANTHROPIC_API_KEY" in os.environ:
            del os.environ["ANTHROPIC_API_KEY"]
        return SettingsOut(anthropic_api_key_set=bool(key))

    return router


def load_settings(engine: Engine) -> None:
    """Inject persisted ANTHROPIC_API_KEY into os.environ at sidecar startup."""
    with Session(engine) as sess:
        row = sess.get(Settings, _ANTHROPIC_KEY_NAME)
        if row is not None and row.value:
            os.environ["ANTHROPIC_API_KEY"] = row.value
