"""CLI entry point for M3 critic.

Usage:
    python -m vision_scanner.critic.run \\
        --project-id 407-1048248 \\
        --submission-id v24.3 \\
        --source-pdf projects/407-1048248/submissions/v24.3/v24.3.pdf \\
        --canonical-clauses data/projects/407-1048248/canonical_clauses.json \\
        --findings-from data/projects/407-1048248/submissions/v24.3/vision_findings.json \\
        --output data/projects/407-1048248/submissions/v24.3/critic_findings.slice1.tmp.json \\
        --slice-clauses "5.table,4.1.2.4,6.7.4,6.5.1,6.6.4" \\
        --print-samples
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .extract import (
    CRITIC_VERSION,
    DEFAULT_RASTER_DPI,
    MODEL_NAME,
    PROMPT_VERSION,
    build_document,
    critique_many,
)
from .filter import is_critical
from .validate import run_all, summarize


def _print_samples(document: Dict[str, Any], n: int = 5) -> None:
    findings = document.get("critic_findings", [])
    print("\n" + "=" * 72)
    print(f"FIRST {min(n, len(findings))} CRITIC FINDINGS (of {len(findings)})")
    print("=" * 72)
    for f in findings[:n]:
        print(f"\n--- clause {f.get('clause_id')} ---")
        print(json.dumps(f, ensure_ascii=False, indent=2))
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(json.dumps(document.get("summary", {}), ensure_ascii=False, indent=2))


def _append_run_log(log_path: Path, record: Dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _atomic_write_json(path: Path, document: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _parse_slice_spec(spec: Optional[str]) -> Optional[List[str]]:
    if spec is None:
        return None
    s = spec.strip().lower()
    if s in ("all", "all-critical", ""):
        return None
    return [c.strip() for c in spec.split(",") if c.strip()]


def _select_target_findings(
    vision_doc: Dict[str, Any], slice_clause_ids: Optional[List[str]]
) -> List[Dict[str, Any]]:
    """Return M2 findings to critique:
       - if slice_clause_ids given → all findings matching any of those clause_ids
         (NOT just critical — the user is explicitly choosing them)
       - else → all critical findings
    """
    all_findings = vision_doc.get("findings", []) or []
    if slice_clause_ids:
        wanted = set(slice_clause_ids)
        return [f for f in all_findings if f.get("clause_id") in wanted]
    return [f for f in all_findings if is_critical(f)]


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="M3 critic: independent Flash critique of M2 vision findings."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--source-pdf", required=True, type=Path)
    parser.add_argument("--canonical-clauses", required=True, type=Path,
                        help="M0 canonical_clauses.json (needed for clause text)")
    parser.add_argument("--findings-from", required=True, type=Path,
                        help="M2 vision_findings.json")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--slice-clauses",
        default=None,
        help='Comma-separated clause_ids to critique, or "all-critical" (default).',
    )
    parser.add_argument(
        "--raster-dpi", type=int, default=DEFAULT_RASTER_DPI,
        help=f"DPI for page rasterization (default: {DEFAULT_RASTER_DPI})",
    )
    parser.add_argument("--print-samples", action="store_true")
    parser.add_argument(
        "--log-path", type=Path, default=None,
        help="Run-log JSONL (default: <output dir>/critic_findings.run_log.jsonl)",
    )
    args = parser.parse_args(argv)

    for p in (args.source_pdf, args.canonical_clauses, args.findings_from):
        if not p.exists():
            print(f"ERROR: missing input file: {p}", file=sys.stderr)
            return 2

    vision_doc = json.loads(args.findings_from.read_text(encoding="utf-8"))
    slice_ids = _parse_slice_spec(args.slice_clauses)
    target_findings = _select_target_findings(vision_doc, slice_ids)

    if not target_findings:
        print(
            "ERROR: no M2 findings selected. "
            "Check --slice-clauses or run with --slice-clauses all-critical.",
            file=sys.stderr,
        )
        return 2

    print(
        f"M3 critic on {args.findings_from.name} "
        f"(plan={args.project_id}, submission={args.submission_id})..."
    )
    print(f"  slice spec: {slice_ids or 'all-critical'}")
    print(f"  selected: {len(target_findings)} M2 findings to critique")
    print(f"  raster DPI: {args.raster_dpi}")

    # Incremental save after every critic call
    def _on_finding_complete(
        partial_findings: List[Dict[str, Any]], idx: int, total: int
    ) -> None:
        from .extract import _build_summary, _sha256_path
        partial_doc = {
            "project_id": args.project_id,
            "submission_id": args.submission_id,
            "critic_version": CRITIC_VERSION,
            "critic_model": MODEL_NAME,
            "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "input_refs": {
                "vision_findings_sha256": _sha256_path(args.findings_from),
                "source_pdf_sha256": _sha256_path(args.source_pdf),
                "canonical_clauses_sha256": _sha256_path(args.canonical_clauses),
            },
            "critic_findings": partial_findings,
            "summary": _build_summary(partial_findings),
        }
        _atomic_write_json(args.output, partial_doc)
        print(
            f"[m3] saved incremental snapshot after finding {idx}/{total}: "
            f"{len(partial_findings)} critic_findings → {args.output}",
            flush=True,
        )

    try:
        result = critique_many(
            pdf_path=args.source_pdf,
            canonical_clauses_path=args.canonical_clauses,
            vision_findings_path=args.findings_from,
            target_findings=target_findings,
            raster_dpi=args.raster_dpi,
            on_finding_complete=_on_finding_complete,
        )
    except Exception as exc:
        print(
            f"\nERROR: M3 critic aborted: {exc}\n"
            f"Partial progress (if any) saved at: {args.output}",
            file=sys.stderr,
        )
        raise

    document = build_document(
        project_id=args.project_id,
        submission_id=args.submission_id,
        result=result,
    )

    # Validation needs the set of M2 clause_ids
    known_clause_ids = {f.get("clause_id") for f in vision_doc.get("findings", [])}

    print("\nRunning 8 automated checks...")
    checks = run_all(
        document,
        known_clause_ids,
        page_count=63,
        vision_findings_path=args.findings_from,
    )
    all_ok, summary_text = summarize(checks)
    print(summary_text)

    _atomic_write_json(args.output, document)
    print(f"\nWrote: {args.output}")

    if result.aggregate_usage:
        u = result.aggregate_usage
        print(f"  aggregate usage: prompt={u['prompt_token_count']}, "
              f"candidates={u['candidates_token_count']}, total={u['total_token_count']}")
    print(f"  total attempts: {result.total_attempts}")

    log_path = args.log_path or (args.output.parent / "critic_findings.run_log.jsonl")
    _append_run_log(
        log_path,
        {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model": MODEL_NAME,
            "critic_version": CRITIC_VERSION,
            "prompt_version": PROMPT_VERSION,
            "phase": "critic",
            "plan_id": args.project_id,
            "submission_id": args.submission_id,
            "vision_findings_sha256": result.vision_findings_sha256,
            "source_pdf_sha256": result.pdf_sha256,
            "canonical_clauses_sha256": result.canonical_clauses_sha256,
            "raster_dpi": args.raster_dpi,
            "slice_spec": slice_ids,
            "critiqued_count": result.summary["critiqued_count"],
            "agree_count": result.summary["agree_count"],
            "disagree_count": result.summary["disagree_count"],
            "cannot_determine_count": result.summary["cannot_determine_count"],
            "agreement_rate_pct": result.summary["agreement_rate_pct"],
            "critical_disagreements": result.summary["critical_disagreements"],
            "validation_result": "pass" if all_ok else "fail",
            "total_attempts": result.total_attempts,
            "aggregate_usage": result.aggregate_usage,
            "output_path": str(args.output),
        },
    )
    print(f"Logged run to: {log_path}")

    if args.print_samples:
        _print_samples(document)

    if not all_ok:
        print("\nVALIDATION FAILED — see [FAIL] lines above.", file=sys.stderr)
        return 1
    print(f"\nAll {len(checks)} automated checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
