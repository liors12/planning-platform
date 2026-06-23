"""Type-safety tests for sidecar.storage.findings_path.

Regression guard for the bug where project_id (int) was passed to
findings_path() instead of tava_number (str), causing:
  TypeError: expected string or bytes-like object, got 'int'
inside re.match() at _validate_tava().

Fixed in commits 8d2d853 and ee94187 across four call sites in
queue_worker.py. These tests ensure the bug fails loudly at test time
rather than silently reaching production.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the sidecar package importable without an installed package.
_SIDECAR_ROOT = Path(__file__).resolve().parents[1] / "app" / "sidecar"
if str(_SIDECAR_ROOT) not in sys.path:
    sys.path.insert(0, str(_SIDECAR_ROOT))

from sidecar.config import Config
from sidecar.storage import StorageError, findings_path


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(
        data_dir=tmp_path,
        db_path=tmp_path / "platform.db",
        jobs_dir=tmp_path / "jobs",
        bind_host="127.0.0.1",
        bind_port=17321,
        max_concurrent_jobs=1,
        db_key="test-key",
        sidecar_python=sys.executable,
    )


# ── Happy-path ──────────────────────────────────────────────────────────────

def test_findings_path_returns_correct_path(cfg: Config, tmp_path: Path) -> None:
    """findings_path with a valid tava_number string returns the expected path."""
    result = findings_path(cfg, "407-1048248", "v24.3")
    expected = tmp_path / "projects" / "407-1048248" / "submissions" / "v24.3" / "findings.json"
    assert result == expected


def test_findings_path_bare_version(cfg: Config, tmp_path: Path) -> None:
    """Version without leading 'v' is normalised to 'v<bare>'."""
    result = findings_path(cfg, "407-1048248", "24.3")
    expected = tmp_path / "projects" / "407-1048248" / "submissions" / "v24.3" / "findings.json"
    assert result == expected


# ── Type-safety: int instead of string ──────────────────────────────────────

def test_findings_path_rejects_int_tava_number(cfg: Config) -> None:
    """Passing project_id (int) instead of tava_number (str) must raise, not
    silently produce a wrong path or a TypeError deep inside re.match()."""
    with pytest.raises((TypeError, StorageError)):
        findings_path(cfg, 3, "v24.3")  # type: ignore[arg-type]


def test_findings_path_rejects_int_masquerading_as_version(cfg: Config) -> None:
    """Both positional args must be strings."""
    with pytest.raises((TypeError, StorageError)):
        findings_path(cfg, "407-1048248", 24)  # type: ignore[arg-type]


# ── Input validation: unsafe / empty strings ─────────────────────────────────

def test_findings_path_rejects_path_traversal(cfg: Config) -> None:
    with pytest.raises(StorageError):
        findings_path(cfg, "../../../etc", "v1.0")


def test_findings_path_rejects_empty_tava(cfg: Config) -> None:
    with pytest.raises(StorageError):
        findings_path(cfg, "", "v1.0")


def test_findings_path_rejects_empty_version(cfg: Config) -> None:
    with pytest.raises(StorageError):
        findings_path(cfg, "407-1048248", "")
