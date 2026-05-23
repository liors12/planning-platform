"""Seven automated checks on a page_manifests document.

Each check returns a (name, passed, detail) tuple. The runner aggregates
results and exits non-zero if any check fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

from .schema import (
    ALLOWED_PAGE_QUALITIES,
    ALLOWED_PAGE_TYPES,
    PageManifestResponse,
)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def _check_schema(document: Dict[str, Any]) -> CheckResult:
    bad: List[Tuple[int, str]] = []
    for m in document.get("manifests", []):
        try:
            PageManifestResponse.model_validate({"manifest": m})
        except Exception as exc:  # noqa: BLE001
            bad.append((m.get("page_number"), str(exc)[:120]))
    if bad:
        return CheckResult(
            "1. schema_valid",
            False,
            f"{len(bad)} manifests failed schema validation: {bad[:3]}",
        )
    return CheckResult("1. schema_valid", True, f"{len(document.get('manifests', []))} manifests OK")


def _check_every_requested_page_present(
    document: Dict[str, Any], requested: Sequence[int]
) -> CheckResult:
    have = {m.get("page_number") for m in document.get("manifests", [])}
    missing = [p for p in requested if p not in have]
    if missing:
        return CheckResult(
            "2. requested_pages_present",
            False,
            f"{len(missing)} requested pages missing: {missing[:5]}",
        )
    return CheckResult(
        "2. requested_pages_present", True, f"all {len(requested)} requested pages present"
    )


def _check_no_duplicate_pages(document: Dict[str, Any]) -> CheckResult:
    seen: Dict[int, int] = {}
    for m in document.get("manifests", []):
        p = m.get("page_number")
        seen[p] = seen.get(p, 0) + 1
    duplicates = {p: n for p, n in seen.items() if n > 1}
    if duplicates:
        return CheckResult(
            "3. no_duplicate_pages", False, f"duplicate page_numbers: {duplicates}"
        )
    return CheckResult("3. no_duplicate_pages", True, f"{len(seen)} unique page_numbers")


def _check_pages_in_range(document: Dict[str, Any]) -> CheckResult:
    page_count = document.get("page_count")
    if not isinstance(page_count, int) or page_count <= 0:
        return CheckResult(
            "4. pages_in_range", False, f"invalid page_count: {page_count!r}"
        )
    bad: List[Any] = []
    for m in document.get("manifests", []):
        p = m.get("page_number")
        if not isinstance(p, int) or p < 1 or p > page_count:
            bad.append(p)
    if bad:
        return CheckResult(
            "4. pages_in_range",
            False,
            f"{len(bad)} manifests have out-of-range page_number: {bad[:5]}",
        )
    return CheckResult("4. pages_in_range", True, f"all in [1, {page_count}]")


def _check_page_types(document: Dict[str, Any]) -> CheckResult:
    bad: List[Tuple[Any, Any]] = []
    for m in document.get("manifests", []):
        pt = m.get("page_type")
        if pt not in ALLOWED_PAGE_TYPES:
            bad.append((m.get("page_number"), pt))
    if bad:
        return CheckResult(
            "5. page_types_in_vocab",
            False,
            f"{len(bad)} manifests with unknown page_type: {bad[:5]}",
        )
    return CheckResult("5. page_types_in_vocab", True, "all in 15-value vocab")


def _check_page_qualities(document: Dict[str, Any]) -> CheckResult:
    bad: List[Tuple[Any, Any]] = []
    for m in document.get("manifests", []):
        pq = m.get("page_quality")
        if pq not in ALLOWED_PAGE_QUALITIES:
            bad.append((m.get("page_number"), pq))
    if bad:
        return CheckResult(
            "6. page_qualities_in_vocab",
            False,
            f"{len(bad)} manifests with unknown page_quality: {bad[:5]}",
        )
    return CheckResult("6. page_qualities_in_vocab", True, "all in 5-value vocab")


def _check_text_labels_non_empty_unless_blank(document: Dict[str, Any]) -> CheckResult:
    bad: List[Any] = []
    for m in document.get("manifests", []):
        labels = m.get("visible_text_labels") or []
        quality = m.get("page_quality")
        if not labels and quality != "blank":
            bad.append(m.get("page_number"))
    if bad:
        return CheckResult(
            "7. text_labels_non_empty_unless_blank",
            False,
            f"{len(bad)} non-blank manifests have empty visible_text_labels: {bad[:5]}",
        )
    return CheckResult(
        "7. text_labels_non_empty_unless_blank",
        True,
        "all non-blank manifests have ≥1 label",
    )


def run_all(document: Dict[str, Any], requested_pages: Sequence[int]) -> List[CheckResult]:
    return [
        _check_schema(document),
        _check_every_requested_page_present(document, requested_pages),
        _check_no_duplicate_pages(document),
        _check_pages_in_range(document),
        _check_page_types(document),
        _check_page_qualities(document),
        _check_text_labels_non_empty_unless_blank(document),
    ]


def summarize(results: List[CheckResult]) -> Tuple[bool, str]:
    lines: List[str] = []
    all_ok = True
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        if not r.passed:
            all_ok = False
        lines.append(f"  [{status}] {r.name} — {r.detail}")
    return all_ok, "\n".join(lines)
