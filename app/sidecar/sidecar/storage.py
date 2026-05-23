"""File storage helpers — Phase 2a Module A.

Storage layout under PLATFORM_DATA_DIR (default `~/.platform/`):

  projects/
    {project_id}/
      submissions/
        {version_string}/
          {original_pdf_filename}.pdf
          {original_dwg_filename}.dwg   (optional)
          findings.json                  (engine output, after Run Engine)

`{version_string}` is user-controlled free text, NOT auto-versioned. It's
stored verbatim in the DB and also used as the directory name; we validate
that it's a safe filesystem fragment (no path separators or hidden-file
leading dot) at the API layer.

Project IDs are the integer DB row IDs, not tava_numbers — guarantees
filesystem-safe paths and decouples physical storage from business
identifiers (a project's tava_number could change over its lifetime; its
storage location shouldn't).
"""
from __future__ import annotations

import re
from pathlib import Path

from .config import Config


# Allowed in version_string: letters, digits, dot, hyphen, underscore.
# Prevents path traversal, hidden-dir leading dot, awkward whitespace.
_SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class StorageError(ValueError):
    """Raised for caller-side input problems (unsafe version string etc.)."""


def project_dir(cfg: Config, project_id: int) -> Path:
    """Return `~/.platform/projects/{project_id}/`. Created if absent."""
    p = cfg.data_dir / "projects" / str(int(project_id))
    p.mkdir(parents=True, exist_ok=True)
    return p


def submission_dir(cfg: Config, project_id: int, version_string: str) -> Path:
    """Return `~/.platform/projects/{project_id}/submissions/{version}/`.

    Raises StorageError if version_string is not a filesystem-safe fragment.
    """
    if not _SAFE_VERSION_RE.match(version_string):
        raise StorageError(
            f"version_string {version_string!r} contains characters outside "
            "[A-Za-z0-9._-] or doesn't start with an alphanumeric. "
            "Reject and ask user to re-enter."
        )
    p = project_dir(cfg, project_id) / "submissions" / version_string
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


def findings_path(cfg: Config, project_id: int, version_string: str) -> Path:
    """Canonical path for the engine output JSON for a given submission."""
    return submission_dir(cfg, project_id, version_string) / "findings.json"
