"""Eight automated checks on a canonical_clauses document.

Each check returns a (name, passed, detail) tuple. The runner aggregates
results and exits non-zero if any check fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from .schema import ALLOWED_CATEGORIES, ClausesResponse

MIN_CLAUSES = 70
MAX_CLAUSES = 200
MIN_TABLE_ROWS = 5
MIN_GENERAL_FOOTNOTES = 4


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def _check_schema(document: Dict[str, Any]) -> CheckResult:
    try:
        ClausesResponse.model_validate({"clauses": document.get("clauses", [])})
    except Exception as exc:  # noqa: BLE001
        return CheckResult("1. schema_valid", False, f"Pydantic validation failed: {exc}")
    return CheckResult("1. schema_valid", True, "OK")


def _check_clause_text_non_empty(document: Dict[str, Any]) -> CheckResult:
    bad: List[str] = []
    for clause in document.get("clauses", []):
        text = clause.get("clause_text", "")
        if not isinstance(text, str) or not text.strip():
            bad.append(clause.get("clause_id", "<missing>"))
    if bad:
        return CheckResult(
            "2. clause_text_non_empty",
            False,
            f"{len(bad)} clauses have empty clause_text: {bad[:5]}",
        )
    return CheckResult("2. clause_text_non_empty", True, "all non-empty")


def _check_unique_clause_ids(document: Dict[str, Any]) -> CheckResult:
    seen: Dict[str, int] = {}
    for clause in document.get("clauses", []):
        cid = clause.get("clause_id")
        seen[cid] = seen.get(cid, 0) + 1
    duplicates = {cid: n for cid, n in seen.items() if n > 1}
    if duplicates:
        return CheckResult(
            "3. unique_clause_ids", False, f"duplicate clause_ids: {duplicates}"
        )
    return CheckResult("3. unique_clause_ids", True, f"{len(seen)} unique ids")


def _check_parent_ids_resolve(document: Dict[str, Any]) -> CheckResult:
    ids = {c.get("clause_id") for c in document.get("clauses", [])}
    bad: List[Tuple[str, str]] = []
    for clause in document.get("clauses", []):
        parent = clause.get("parent_id")
        if parent is None:
            continue
        if parent not in ids:
            bad.append((clause.get("clause_id"), parent))
    if bad:
        return CheckResult(
            "4. parent_ids_resolve",
            False,
            f"{len(bad)} dangling parent_ids: {bad[:5]}",
        )
    return CheckResult("4. parent_ids_resolve", True, "all parent_ids resolve")


def _check_pages_in_range(document: Dict[str, Any]) -> CheckResult:
    page_count = document.get("page_count")
    if not isinstance(page_count, int) or page_count <= 0:
        return CheckResult(
            "5. pages_in_range", False, f"invalid page_count: {page_count!r}"
        )
    bad: List[Tuple[str, Any]] = []
    for clause in document.get("clauses", []):
        page = clause.get("page")
        if not isinstance(page, int) or page < 1 or page > page_count:
            bad.append((clause.get("clause_id"), page))
    if bad:
        return CheckResult(
            "5. pages_in_range",
            False,
            f"{len(bad)} clauses have out-of-range page: {bad[:5]}",
        )
    return CheckResult("5. pages_in_range", True, f"all in [1, {page_count}]")


def _check_categories(document: Dict[str, Any]) -> CheckResult:
    bad: List[Tuple[str, Any]] = []
    for clause in document.get("clauses", []):
        cat = clause.get("category")
        if cat not in ALLOWED_CATEGORIES:
            bad.append((clause.get("clause_id"), cat))
    if bad:
        return CheckResult(
            "6. categories_in_vocab",
            False,
            f"{len(bad)} clauses with unknown category: {bad[:5]}",
        )
    return CheckResult("6. categories_in_vocab", True, "all in 15-value vocab")


def _check_section_5_table(document: Dict[str, Any]) -> CheckResult:
    table = next(
        (c for c in document.get("clauses", []) if c.get("clause_id") == "5.table"),
        None,
    )
    if table is None:
        return CheckResult("7. section_5_table", False, "no clause with clause_id='5.table'")
    rows = table.get("structured_values") or []
    notes = table.get("general_footnotes") or []
    problems: List[str] = []
    if len(rows) < MIN_TABLE_ROWS:
        problems.append(f"structured_values has {len(rows)} rows, need ≥ {MIN_TABLE_ROWS}")
    if len(notes) < MIN_GENERAL_FOOTNOTES:
        problems.append(
            f"general_footnotes has {len(notes)} entries, need ≥ {MIN_GENERAL_FOOTNOTES}"
        )
    if problems:
        return CheckResult("7. section_5_table", False, "; ".join(problems))
    return CheckResult(
        "7. section_5_table",
        True,
        f"{len(rows)} rows, {len(notes)} general_footnotes",
    )


def _check_clause_count(document: Dict[str, Any]) -> CheckResult:
    n = len(document.get("clauses", []))
    if n < MIN_CLAUSES or n > MAX_CLAUSES:
        return CheckResult(
            "8. clause_count_bounds",
            False,
            f"{n} clauses outside [{MIN_CLAUSES}, {MAX_CLAUSES}]",
        )
    return CheckResult("8. clause_count_bounds", True, f"{n} clauses in bounds")


def run_all(document: Dict[str, Any]) -> List[CheckResult]:
    return [
        _check_schema(document),
        _check_clause_text_non_empty(document),
        _check_unique_clause_ids(document),
        _check_parent_ids_resolve(document),
        _check_pages_in_range(document),
        _check_categories(document),
        _check_section_5_table(document),
        _check_clause_count(document),
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
