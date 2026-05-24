"""CLI entry point for M2 unified extraction.

Usage:
    python -m vision_scanner.unified_extraction.run \\
        --project-id 407-1048248 \\
        --submission-id v24.3 \\
        --source-pdf projects/407-1048248/submissions/v24.3/v24.3.pdf \\
        --canonical-clauses data/projects/407-1048248/canonical_clauses.json \\
        --page-manifests data/projects/407-1048248/submissions/v24.3/page_manifests.json \\
        --output data/projects/407-1048248/submissions/v24.3/vision_findings.slice1.tmp.json \\
        --clauses "4.1.2.1,6.2.2,4.1.2.11,6.4.2,6.5.4.א" \\
        --print-samples
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .extract import (
    DEFAULT_RASTER_DPI,
    EXTRACTOR_VERSION,
    MODEL_NAME,
    PROMPT_VERSION,
    build_document,
    extract,
)
from .validate import run_all, summarize


def _print_samples(document: Dict[str, Any], n: int = 3) -> None:
    findings = document.get("findings", [])
    print("\n" + "=" * 72)
    print(f"FIRST {min(n, len(findings))} FINDINGS (of {len(findings)}) — eyeball against the PDF")
    print("=" * 72)
    for f in findings[:n]:
        print(f"\n--- clause {f.get('clause_id')} (ta_shetach_takanon={f.get('ta_shetach_takanon')}) ---")
        print(json.dumps(f, ensure_ascii=False, indent=2))
    print("\n" + "=" * 72)
    print("PLOT RECONCILIATION")
    print("=" * 72)
    print(json.dumps(document.get("plot_reconciliation", {}), ensure_ascii=False, indent=2))


def _append_run_log(log_path: Path, record: Dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _atomic_write_json(path: Path, document: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _parse_clauses_spec(spec: Optional[str]) -> Optional[List[str]]:
    if spec is None:
        return None
    s = spec.strip().lower()
    if s in ("all", "all-normative", ""):
        return None
    return [c.strip() for c in spec.split(",") if c.strip()]


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unified extraction: 63 page images + N clauses → Pro → VisionFindings (M2)."
    )
    parser.add_argument("--project-id", required=True, help="Plan id, e.g. 407-1048248")
    parser.add_argument("--submission-id", required=True, help="Submission id, e.g. v24.3")
    parser.add_argument("--source-pdf", required=True, type=Path, help="Path to submission PDF")
    parser.add_argument("--canonical-clauses", required=True, type=Path, help="Path to M0 canonical_clauses.json")
    parser.add_argument("--page-manifests", required=True, type=Path, help="Path to M1 page_manifests.json")
    parser.add_argument("--output", required=True, type=Path, help="Output JSON path")
    parser.add_argument(
        "--clauses",
        default=None,
        help='Clause-id spec: "5.1.1,6.4.2,6.5.4.א" or "all-normative" (default: all-normative)',
    )
    parser.add_argument(
        "--raster-dpi",
        type=int,
        default=DEFAULT_RASTER_DPI,
        help=f"DPI for page rasterization (default: {DEFAULT_RASTER_DPI})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Clauses per Pro call. 100 (default) = single-call when ≤100 clauses. "
             "Set lower (e.g. 20) for batched runs that fight Pro's silent-drop "
             "behavior on long clause lists.",
    )
    parser.add_argument(
        "--print-samples", action="store_true", help="Print first 3 findings + plot reconciliation"
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=None,
        help="Run-log JSONL path (default: <output dir>/vision_findings.run_log.jsonl)",
    )
    args = parser.parse_args(argv)

    for p in (args.source_pdf, args.canonical_clauses, args.page_manifests):
        if not p.exists():
            print(f"ERROR: missing input file: {p}", file=sys.stderr)
            return 2

    clause_ids = _parse_clauses_spec(args.clauses)
    print(
        f"Extracting per-clause findings from {args.source_pdf} "
        f"(plan={args.project_id}, submission={args.submission_id})..."
    )
    if clause_ids:
        print(f"  clauses spec: {len(clause_ids)} specified — {clause_ids}")
    else:
        print(f"  clauses spec: all-normative")
    print(f"  raster DPI: {args.raster_dpi}")

    # Incremental save: after each batch, build a partial document and atomic-write
    # it to the output path. A crash on a later batch preserves completed work
    # so a restart can be cheaper (or partial output is still usable).
    def _on_batch_complete(partial_merged: Dict[str, Any], idx: int, total: int) -> None:
        from .extract import build_document, ExtractionResult, CallUsage
        partial_result = ExtractionResult(
            response_data=partial_merged,
            usage=CallUsage(),  # aggregate usage is unknown mid-run
            attempts=0,
            pdf_sha256="",
            canonical_clauses_sha256="",
            page_manifests_sha256="",
        )
        partial_doc = build_document(
            project_id=args.project_id,
            submission_id=args.submission_id,
            result=partial_result,
            validation_summary={
                "incremental": f"batch {idx}/{total} complete (mid-run snapshot)"
            },
        )
        _atomic_write_json(args.output, partial_doc)
        print(
            f"[m2] saved incremental snapshot after batch {idx}/{total}: "
            f"{len(partial_merged.get('findings', []))} findings → {args.output}",
            flush=True,
        )

    try:
        result = extract(
            pdf_path=args.source_pdf,
            canonical_clauses_path=args.canonical_clauses,
            page_manifests_path=args.page_manifests,
            clause_ids=clause_ids,
            raster_dpi=args.raster_dpi,
            batch_size=args.batch_size,
            on_batch_complete=_on_batch_complete,
        )
    except Exception as exc:
        print(
            f"\nERROR: extraction aborted: {exc}\n"
            f"Partial progress (if any) saved at: {args.output}",
            file=sys.stderr,
        )
        raise

    # Build the on-disk document
    document = build_document(
        project_id=args.project_id,
        submission_id=args.submission_id,
        result=result,
        validation_summary={},  # filled in after validation below
    )

    # Validation needs the set of known clause_ids from the canonical_clauses doc
    cc_doc = json.loads(args.canonical_clauses.read_text(encoding="utf-8"))
    known_clause_ids = {c.get("clause_id") for c in cc_doc.get("clauses", [])}
    page_count = 63
    try:
        import fitz
        with fitz.open(args.source_pdf) as doc:
            page_count = doc.page_count
    except Exception:
        pass

    # For check #8 (every requested clause present), we need the exact requested set.
    # If the user passed --clauses, that's clause_ids. If they used all-normative, we
    # derive the request set from cc_doc.
    if clause_ids is not None:
        request_set = list(clause_ids)
    else:
        request_set = [
            c.get("clause_id")
            for c in cc_doc.get("clauses", [])
            if c.get("is_normative")
        ]

    print("\nRunning 8 automated checks...")
    checks = run_all(
        document,
        known_clause_ids,
        page_count=page_count,
        requested_clause_ids=request_set,
    )
    all_ok, summary = summarize(checks)
    print(summary)
    document["validation_summary"] = {
        c.name: {"passed": c.passed, "detail": c.detail} for c in checks
    }

    _atomic_write_json(args.output, document)
    print(f"\nWrote: {args.output}")

    if result.usage:
        u = result.usage
        print(f"  usage: prompt={u.prompt_token_count}, "
              f"candidates={u.candidates_token_count}, total={u.total_token_count}")
    print(f"  attempts: {result.attempts}")

    log_path = args.log_path or (args.output.parent / "vision_findings.run_log.jsonl")
    _append_run_log(
        log_path,
        {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model": MODEL_NAME,
            "extractor_version": EXTRACTOR_VERSION,
            "prompt_version": PROMPT_VERSION,
            "phase": "extract",
            "plan_id": args.project_id,
            "submission_id": args.submission_id,
            "source_pdf_sha256": result.pdf_sha256,
            "canonical_clauses_sha256": result.canonical_clauses_sha256,
            "page_manifests_sha256": result.page_manifests_sha256,
            "raster_dpi": args.raster_dpi,
            "clause_ids_requested": clause_ids,
            "findings_count": len(document["findings"]),
            "plot_mappings_count": len(
                document["plot_reconciliation"].get("mappings", [])
            ),
            "validation_result": "pass" if all_ok else "fail",
            "attempts": result.attempts,
            "usage": (
                {
                    "prompt_token_count": result.usage.prompt_token_count,
                    "candidates_token_count": result.usage.candidates_token_count,
                    "total_token_count": result.usage.total_token_count,
                }
                if result.usage
                else None
            ),
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
