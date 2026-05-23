"""SHA-keyed extraction cache.

Determinism contract: extraction runs at most once per (pdf_sha, extraction
target). Subsequent runs read cached values. Manual overrides are honored
(comparison re-runs against the override value).

The cache is a plain JSON file. On a cache hit we return the same dict the
extractor returned the first time, so downstream code is fully deterministic.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


CACHE_SCHEMA_VERSION = "1.0.0"


def pdf_sha256(pdf_path: Path) -> str:
    """SHA-256 of the PDF file bytes."""
    h = hashlib.sha256()
    with Path(pdf_path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class CacheRecord:
    pdf_sha256: str
    extraction_target: str
    extraction_data: dict
    extraction_metadata: dict  # source pages, confidence, manual overrides, etc.


def load_cache(cache_path: Path) -> dict:
    if not Path(cache_path).exists():
        return {"_schema_version": CACHE_SCHEMA_VERSION, "entries": {}}
    try:
        data = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"_schema_version": CACHE_SCHEMA_VERSION, "entries": {}}
    if "entries" not in data:
        data["entries"] = {}
    return data


def save_cache(cache_path: Path, cache: dict) -> None:
    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    Path(cache_path).write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def cache_key(pdf_sha: str, extraction_target: str) -> str:
    return f"{pdf_sha}:{extraction_target}"


def get_or_extract(
    pdf_path: Path,
    extraction_target: str,
    cache_path: Path,
    extractor: Callable[[], dict],
) -> dict:
    """Look up an extraction in the cache, or run the extractor and store it.

    Returns the extraction dict (the same shape the extractor produced).
    If a cache entry has a manual override (manually_overridden=True) the
    cached `extraction_data` already reflects the override — we just return it.
    """
    sha = pdf_sha256(pdf_path)
    cache = load_cache(cache_path)
    key = cache_key(sha, extraction_target)
    if key in cache["entries"]:
        return cache["entries"][key]["extraction_data"]

    data = extractor()
    cache["entries"][key] = {
        "pdf_sha256": sha,
        "extraction_target": extraction_target,
        "extraction_data": data,
        "extraction_metadata": {
            "manually_overridden": False,
        },
    }
    save_cache(cache_path, cache)
    return data


def apply_override(
    cache_path: Path,
    pdf_sha: str,
    extraction_target: str,
    new_value: Any,
    note: str = "",
) -> None:
    """Mark a cached extraction entry as manually overridden.

    Replaces the `extraction_data` with `new_value` and sets the metadata flag
    so subsequent runs treat it as authoritative.
    """
    cache = load_cache(cache_path)
    key = cache_key(pdf_sha, extraction_target)
    if key not in cache["entries"]:
        raise KeyError(f"no cache entry for {key}")
    cache["entries"][key]["extraction_data"] = new_value
    meta = cache["entries"][key].setdefault("extraction_metadata", {})
    meta["manually_overridden"] = True
    if note:
        meta["override_note"] = note
    save_cache(cache_path, cache)
