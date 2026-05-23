"""Sidecar runtime config — paths, ports, env-driven knobs.

All paths live under the user's app data dir so the same install supports
multiple OS users on Windows. On dev (Mac) we default to ~/.platform/.

Env knobs:
  PLATFORM_DATA_DIR        — overrides the data dir entirely (tests / CI)
  PLATFORM_BIND_HOST       — must remain 127.0.0.1; loudly rejected otherwise
  PLATFORM_BIND_PORT       — sidecar listen port (default 17321)
  PLATFORM_MAX_CONCURRENT_JOBS  — concurrency cap per ADR-001 § Implication 2
  PLATFORM_DB_KEY          — SQLCipher key (DEV ONLY; v1 derives from PIN)
"""
from __future__ import annotations

import os
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


def load() -> Config:
    data_dir = Path(os.environ.get("PLATFORM_DATA_DIR") or (Path.home() / ".platform"))
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
