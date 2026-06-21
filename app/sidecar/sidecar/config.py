"""Sidecar runtime config — paths, ports, env-driven knobs.

All paths live under the user's app data dir so the same install supports
multiple OS users on Windows. Platform-conventional defaults:

  Windows:        %LOCALAPPDATA%\\Planning Platform\\   (under AppData\\Local)
  macOS / Linux:  ~/.platform/                          (dotfile under $HOME)

Env knobs:
  PLATFORM_DATA_DIR        — overrides the data dir entirely (tests / CI)
  PLATFORM_BIND_HOST       — must remain 127.0.0.1; loudly rejected otherwise
  PLATFORM_BIND_PORT       — sidecar listen port (default 17321)
  PLATFORM_MAX_CONCURRENT_JOBS  — concurrency cap per ADR-001 § Implication 2
  PLATFORM_DB_KEY          — SQLCipher key (DEV ONLY; v1 derives from PIN)
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


VERSION = "0.1.0"

# Sidecar binds 127.0.0.1 ONLY (spec § 8 + ADR-001). 0.0.0.0 would expose the
# API to the LAN; anything other than 127.0.0.1 is a configuration mistake.
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}

# DEV-ONLY default. Production derives a key from Ellen's app PIN at startup
# (spec § 8). This default must never reach a shipped installer.
_DEV_DB_KEY = "phase1-dev-key-DO-NOT-SHIP"


@dataclass(frozen=True)
class Config:
    data_dir: Path
    db_path: Path
    jobs_dir: Path
    bind_host: str
    bind_port: int
    max_concurrent_jobs: int
    db_key: str
    sidecar_python: str  # the interpreter spawn() uses for workers


def _default_data_dir() -> Path:
    """Return the OS-conventional user-data dir for this app.

    Windows: %LOCALAPPDATA%\\Planning Platform (typically
    C:\\Users\\<user>\\AppData\\Local\\Planning Platform). Falls back to
    %USERPROFILE%\\.platform if LOCALAPPDATA is somehow unset (shouldn't
    happen on Win10+, but defensive).

    macOS / Linux: ~/.platform (preserves the existing dev convention so
    nobody's local data moves under their feet).
    """
    if sys.platform == "win32":
        appdata = os.environ.get("LOCALAPPDATA")
        if appdata:
            return Path(appdata) / "Planning Platform"
        # Defensive fallback — should never trigger on Win10+
        return Path.home() / ".platform"
    return Path.home() / ".platform"


def load() -> Config:
    data_dir = Path(os.environ.get("PLATFORM_DATA_DIR") or _default_data_dir())
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "jobs").mkdir(parents=True, exist_ok=True)

    host = os.environ.get("PLATFORM_BIND_HOST", "127.0.0.1")
    if host not in _ALLOWED_HOSTS:
        raise RuntimeError(
            f"PLATFORM_BIND_HOST={host!r} is not localhost-only. "
            f"Allowed: {sorted(_ALLOWED_HOSTS)}. See spec § 8 + ADR-001."
        )

    return Config(
        data_dir=data_dir,
        db_path=data_dir / "platform.db",
        jobs_dir=data_dir / "jobs",
        bind_host=host,
        bind_port=int(os.environ.get("PLATFORM_BIND_PORT", "17321")),
        max_concurrent_jobs=int(os.environ.get("PLATFORM_MAX_CONCURRENT_JOBS", "1")),
        db_key=os.environ.get("PLATFORM_DB_KEY", _DEV_DB_KEY),
        sidecar_python=os.environ.get("PLATFORM_PYTHON", "/opt/homebrew/bin/python3.13"),
    )
