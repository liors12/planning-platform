"""File storage helpers — Phase 2a Module A.

Storage layout under PLATFORM_DATA_DIR (Windows: %LOCALAPPDATA%\\Planning
Platform\\; macOS/Linux: `~/.platform/`):

  projects/
    {tava_number}/
      submissions/
        v{bare_version}/
          {original_pdf_filename}.pdf
          {original_dwg_filename}.dwg   (optional)
          findings.json                 (engine output, after Run Engine)

Keying decisions:

- **Directory key = `tava_number`** (e.g. `407-1048248`), not the DB row id.
  Phase 2a's int-id scheme aimed to decouple physical storage from business
  identifiers, but it left the upload tree disconnected from the engine
  tree (which has always been keyed by tava). Unifying on tava collapses
  two filesystem schemes into one — the queue worker, the seed bundle,
  and `_run_render_only` all see the same paths.
- **Version segment = `v{bare}`** to match the engine's longstanding
  `audit_outputs/<tava>/v<bare>/` convention. If the user types "v24.3"
  in the UI we still produce `v24.3` (we strip a leading 'v' before
  prefixing).
- **DB `Submission.version_string`** keeps the literal user input so old
  rows continue to round-trip unchanged.
"""
from __future__ import annotations

import re
from pathlib import Path

from .config import Config


# Allowed in tava_number / version_string: letters, digits, dot, hyphen,
# underscore. Prevents path traversal, hidden-dir leading dot, awkward
# whitespace. Tava numbers look like "407-1048248" — covered.
_SAFE_FRAGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class StorageError(ValueError):
    """Raised for caller-side input problems (unsafe version string etc.)."""


def _validate_tava(tava_number: str) -> None:
    if not _SAFE_FRAGMENT_RE.match(tava_number):
        raise StorageError(
            f"tava_number {tava_number!r} contains characters outside "
            "[A-Za-z0-9._-] or doesn't start with an alphanumeric."
        )


def _canonical_version_segment(version_string: str) -> str:
    """Map a user-entered version into the `v<bare>` directory form.

    "v24.3" → "v24.3"; "24.3" → "v24.3". Raises StorageError on unsafe
    fragments so callers can return 422 before the upload starts streaming.
    """
    if not _SAFE_FRAGMENT_RE.match(version_string):
        raise StorageError(
            f"version_string {version_string!r} contains characters outside "
            "[A-Za-z0-9._-] or doesn't start with an alphanumeric. "
            "Reject and ask user to re-enter."
        )
    bare = version_string[1:] if version_string.startswith("v") else version_string
    if not bare or not _SAFE_FRAGMENT_RE.match(bare):
        # e.g. "v" alone, or "v.foo"
        raise StorageError(
            f"version_string {version_string!r} is empty or unsafe after "
            "stripping the leading 'v'."
        )
    return f"v{bare}"


def project_dir(cfg: Config, tava_number: str) -> Path:
    """Return `<data_dir>/projects/{tava_number}/`. Created if absent."""
    _validate_tava(tava_number)
    p = cfg.data_dir / "projects" / tava_number
    p.mkdir(parents=True, exist_ok=True)
    return p


def submission_dir(cfg: Config, tava_number: str, version_string: str) -> Path:
    """Return `<data_dir>/projects/{tava}/submissions/v{bare}/`.

    Raises StorageError if either fragment is unsafe.
    """
    version_seg = _canonical_version_segment(version_string)
    p = project_dir(cfg, tava_number) / "submissions" / version_seg
    p.mkdir(parents=True, exist_ok=True)
    return p


def sanitize_upload_filename(filename: str) -> str:
    """Reduce a user-uploaded filename to a safe leaf name.

    Strips any path components, normalizes Unicode (Hebrew filenames are fine
    on APFS/NTFS), and rejects hidden-file leading dots. Length cap at 200
    chars to avoid edge cases on Windows.
    """
    # Take only the basename — strips directory traversal attempts.
    leaf = Path(filename).name
    if not leaf or leaf in (".", ".."):
        raise StorageError(f"upload filename {filename!r} resolves to empty leaf")
    if leaf.startswith("."):
        raise StorageError(f"upload filename {filename!r} starts with a dot")
    if len(leaf) > 200:
        # Preserve extension if reasonable.
        suffix = Path(leaf).suffix[:16]
        leaf = leaf[: 200 - len(suffix)] + suffix
    return leaf


def findings_path(cfg: Config, tava_number: str, version_string: str) -> Path:
    """Canonical path for the engine output JSON for a given submission."""
    return submission_dir(cfg, tava_number, version_string) / "findings.json"
