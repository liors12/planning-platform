"""Configuration: Gemini API key rotation across primary + 3 backups.

Reads keys from env in priority order, filters empty/missing values, and
exposes a rotating iterator so the extractor can advance to the next key on
HTTP 429 / quota errors.
"""

from __future__ import annotations

import os
from typing import List, Optional

GEMINI_KEY_ENV_VARS: List[str] = [
    "GEMINI_API_KEY",
    "GEMINI_API_KEY_BACKUP_1",
    "GEMINI_API_KEY_BACKUP_2",
    "GEMINI_API_KEY_BACKUP_3",
]


def load_gemini_keys() -> List[str]:
    """Return non-empty Gemini API keys, in declared priority order."""
    keys: List[str] = []
    for var in GEMINI_KEY_ENV_VARS:
        value = os.environ.get(var, "").strip()
        if value:
            keys.append(value)
    return keys


class GeminiKeyRotator:
    """Iterates through available Gemini keys, advancing on quota errors."""

    def __init__(self, keys: Optional[List[str]] = None) -> None:
        self._keys = keys if keys is not None else load_gemini_keys()
        self._index = 0

    @property
    def has_keys(self) -> bool:
        return bool(self._keys)

    @property
    def remaining(self) -> int:
        return max(0, len(self._keys) - self._index)

    def current(self) -> str:
        if not self.has_keys:
            raise RuntimeError(
                "No Gemini API keys available. Set GEMINI_API_KEY (and optionally "
                "GEMINI_API_KEY_BACKUP_1/2/3)."
            )
        if self._index >= len(self._keys):
            raise RuntimeError("All Gemini API keys exhausted (rotation past end).")
        return self._keys[self._index]

    def rotate(self) -> Optional[str]:
        """Advance to the next key. Returns the new key, or None if exhausted."""
        self._index += 1
        if self._index >= len(self._keys):
            return None
        return self._keys[self._index]
