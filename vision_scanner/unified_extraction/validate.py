"""Seven automated checks on a vision_findings document.

Mirrors the M1 pattern. Each check returns a CheckResult; the runner
aggregates and exits non-zero on any failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .schema import (
    ALLOWED_BBOX_TAGS,
    ALLOWED_COMPLIANCE,
    ALLOWED_CONFIDENCES,
    VisionFindings,
)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def _check_schema(document: Dict[str, Any]) -> CheckResult:
    try:
        VisionFindings.model_validate(document)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "1. schema_valid", False, f"Pydantic validation failed: {str(exc)[:200]}"
        )
    n = len(document.get("findings", []))
    return CheckResult("1. schema_valid", True, f"{n} findings OK")


def _check_clause_ids_resolve(
    document: Dict[str, Any], known_clause_ids: set
) -> CheckResult:
    bad: List[str] = []
    for f in document.get("findings", []):
        cid = f.get("clause_id")
        if cid not in known_clause_ids:
            bad.append(str(cid))
    if bad:
        return CheckResult(
            "2. clause_ids_resolve",
            False,
            f"{len(bad)} findings reference unknown clause_id: {bad[:5]}",
        )
    return CheckResult(
        "2. clause_ids_resolve",
        True,
        f"all {len(document.get('findings', []))} clause_ids resolve",
    )


def _check_source_pages_in_range(document: Dict[str, Any], page_count: int) -> CheckResult:
    bad: List[Tuple[str, int]] = []
    for f in document.get("findings", []):
        for p in f.get("source_pages", []) or []:
            if not isinstance(p, int) or p < 1 or p > page_count:
                bad.append((f.get("clause_id"), p))
    if bad:
        return CheckResult(
            "3. source_pages_in_range",
            False,
            f"{len(bad)} out-of-range source_pages (e.g. {bad[:3]})",
        )
    return CheckResult(
        "3. source_pages_in_range", True, f"all source_pages in [1, {page_count}]"
    )


def _check_bboxes_in_range(
    document: Dict[str, Any], page_count: int, page_dims: Dict[int, Tuple[int, int]]
) -> CheckResult:
    """Each bbox.page must be in [1, page_count]; bbox coords must be within page dims.

    page_dims maps page_number → (width_px, height_px) at the raster DPI used.
    If page_dims is empty (caller couldn't supply), we only check page in [1, page_count]
    and that bbox has 4 finite values.
    """
    bad: List[Tuple[str, int, str]] = []
    for f in document.get("findings", []):
        for b in f.get("evidence_bboxes", []) or []:
            page = b.get("page")
            bbox = b.get("bbox", []) or []
            if not isinstance(page, int) or page < 1 or page > page_count:
                bad.append((f.get("clause_id"), page, "page out of range"))
                continue
            if len(bbox) != 4 or any(not isinstance(v, (int, float)) for v in bbox):
                bad.append((f.get("clause_id"), page, f"bbox shape {bbox}"))
                continue
            if page_dims and page in page_dims:
                w, h = page_dims[page]
                x1, y1, x2, y2 = bbox
                if x1 < 0 or y1 < 0 or x2 > w or y2 > h or x1 >= x2 or y1 >= y2:
                    bad.append((f.get("clause_id"), page,
                                f"bbox {bbox} outside [{w}x{h}]"))
    if bad:
        return CheckResult(
            "4. bboxes_in_page_dims",
            False,
            f"{len(bad)} bboxes failed (e.g. {bad[:3]})",
        )
    n = sum(len(f.get("evidence_bboxes", []) or []) for f in document.get("findings", []))
    return CheckResult("4. bboxes_in_page_dims", True, f"all {n} bboxes OK")


def _check_confidence_enum(document: Dict[str, Any]) -> CheckResult:
    bad: List[Tuple[str, Any]] = []
    for f in document.get("findings", []):
        c = f.get("confidence")
        if c not in ALLOWED_CONFIDENCES:
            bad.append((f.get("clause_id"), c))
    if bad:
        return CheckResult(
            "5. confidence_enum_valid",
            False,
            f"{len(bad)} findings with bad confidence: {bad[:5]}",
        )
    return CheckResult("5. confidence_enum_valid", True, "all in {high, medium, low}")


def _check_compliance_enum(document: Dict[str, Any]) -> CheckResult:
    bad: List[Tuple[str, Any]] = []
    for f in document.get("findings", []):
        c = f.get("compliance_indicator")
        if c not in ALLOWED_COMPLIANCE:
            bad.append((f.get("clause_id"), c))
    if bad:
        return CheckResult(
            "6. compliance_enum_valid",
            False,
            f"{len(bad)} findings with bad compliance_indicator: {bad[:5]}",
        )
    return CheckResult(
        "6. compliance_enum_valid",
        True,
        "all in {compliant, non_compliant, requires_review, missing, deferred_to_dwg}",
    )


_TAKANON_PLOTS = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "20"}


def _parse_compound_plot_label(submission_label: str) -> List[str]:
    """Split a compound submission label like "תא שטח 2+4" into ["תא שטח 2", "תא שטח 4"].

    Handles separators `+`, `,`, `;`, `ו-` (Hebrew "and").
    Returns the original label as a single-element list if no compound split applies.
    """
    if not submission_label or not isinstance(submission_label, str):
        return [submission_label] if submission_label else []
    # Extract leading prefix (e.g. "תא שטח", "מגרש") and the trailing digit/separator block
    import re
    m = re.match(r"^\s*(תא\s*שטח|מגרש[֐-׿\s]*?)\s*([0-9+,;\s\-ו]+)\s*$", submission_label)
    if not m:
        return [submission_label]
    prefix = m.group(1).strip()
    numpart = m.group(2)
    # Split on +, comma, semicolon, "ו-" (Hebrew "and-"), or whitespace runs containing them
    pieces = re.split(r"[+,;\s]+|ו-", numpart)
    nums = [p.strip() for p in pieces if p.strip() and p.strip().isdigit()]
    if len(nums) <= 1:
        return [submission_label]
    return [f"{prefix} {n}" for n in nums]


def _is_self_evident_takanon_label(submission_label: str) -> bool:
    """Submission labels that ARE the takanon plot themselves don't need explicit mapping.

    A literal "תא שטח N" or "מגרש N" where N ∈ {1..10, 20} maps to itself. Pro
    legitimately treats these as self-evident and doesn't emit a redundant
    mappings entry; the validator should not flag them.

    Also accepts:
      • trailing descriptors (e.g. "מגרש מסחרי 20" still resolves to 20)
      • compound labels (e.g. "תא שטח 2+4" — each component must individually
        be a self-evident takanon plot)
    """
    if not submission_label:
        return False
    # Compound-label handling — every component must self-resolve.
    components = _parse_compound_plot_label(submission_label)
    if len(components) > 1:
        return all(_is_self_evident_takanon_label(c) for c in components)
    # Single-label check
    tokens = submission_label.strip().split()
    if not any(tok in {"תא", "מגרש"} or tok.startswith("מגרש") for tok in tokens):
        return False
    for tok in tokens:
        stripped = tok.lstrip("שטח").strip()
        if stripped in _TAKANON_PLOTS:
            return True
        if tok.isdigit() and tok in _TAKANON_PLOTS:
            return True
    return False


def _check_plot_reconciliation_consistent(document: Dict[str, Any]) -> CheckResult:
    """Every ta_shetach_submission referenced by a Finding must be accounted for:
    either (a) listed in plot_reconciliation.mappings, (b) listed in
    plot_reconciliation.unreconciled_submission_labels, or (c) a self-evident
    takanon label like "תא שטח 3" / "מגרש 20" that needs no reconciliation."""
    pr = document.get("plot_reconciliation", {}) or {}
    mapped = {m.get("submission_label") for m in pr.get("mappings", []) or []}
    unreconciled = set(pr.get("unreconciled_submission_labels", []) or [])
    known = mapped | unreconciled

    bad: List[Tuple[str, str]] = []
    self_evident_count = 0
    for f in document.get("findings", []):
        sub = f.get("ta_shetach_submission")
        if sub is None or sub == "":
            continue
        if sub in known:
            continue
        if _is_self_evident_takanon_label(sub):
            self_evident_count += 1
            continue
        bad.append((f.get("clause_id"), sub))
    if bad:
        return CheckResult(
            "7. plot_reconciliation_consistent",
            False,
            f"{len(bad)} findings cite unmapped/unreconciled ta_shetach_submission: {bad[:5]}",
        )
    return CheckResult(
        "7. plot_reconciliation_consistent",
        True,
        f"{len(mapped)} mappings + {len(unreconciled)} unreconciled + "
        f"{self_evident_count} self-evident takanon labels cover all citations",
    )


def _check_all_requested_clauses_present(
    document: Dict[str, Any], requested_clause_ids: Optional[Sequence[str]]
) -> CheckResult:
    """Every clause_id in the run's request set must appear in ≥1 finding.

    Skipped (PASS with note) if no `requested_clause_ids` provided — the caller
    didn't specify which clauses to track. When provided, this is the guard
    against Pro silently dropping clauses (m2-v3 regression caught in Round 3).
    """
    if requested_clause_ids is None:
        return CheckResult(
            "8. all_requested_clauses_present",
            True,
            "skipped — no requested_clause_ids provided to validator",
        )
    requested = set(requested_clause_ids)
    seen = {f.get("clause_id") for f in document.get("findings", [])}
    dropped = sorted(requested - seen)
    if dropped:
        # Truncate display if very many
        display = dropped[:15]
        more = f" (and {len(dropped) - 15} more)" if len(dropped) > 15 else ""
        return CheckResult(
            "8. all_requested_clauses_present",
            False,
            f"{len(dropped)} of {len(requested)} requested clauses produced ZERO findings: "
            f"{display}{more}",
        )
    return CheckResult(
        "8. all_requested_clauses_present",
        True,
        f"all {len(requested)} requested clauses have ≥1 finding",
    )


def run_all(
    document: Dict[str, Any],
    known_clause_ids: set,
    page_count: int = 63,
    page_dims: Dict[int, Tuple[int, int]] = None,
    requested_clause_ids: Optional[Sequence[str]] = None,
) -> List[CheckResult]:
    page_dims = page_dims or {}
    return [
        _check_schema(document),
        _check_clause_ids_resolve(document, known_clause_ids),
        _check_source_pages_in_range(document, page_count),
        _check_bboxes_in_range(document, page_count, page_dims),
        _check_confidence_enum(document),
        _check_compliance_enum(document),
        _check_plot_reconciliation_consistent(document),
        _check_all_requested_clauses_present(document, requested_clause_ids),
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
