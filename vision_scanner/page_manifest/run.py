"""CLI entry point for per-page vision manifest extraction (M1).

Usage:
    python -m vision_scanner.page_manifest.run \
        --project-id 407-1048248 \
        --submission-id v24.3 \
        --source-pdf projects/407-1048248/submissions/v24.3/v24.3.pdf \
        --output data/projects/407-1048248/submissions/v24.3/page_manifests.tmp.json \
        --pages "1,13,26,39,52" \
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

import fitz  # PyMuPDF

from .extract import (
    EXTRACTOR_VERSION,
    MODEL_NAME,
    PROMPT_VERSION,
    extract_manifests,
    parse_pages_spec,
)
from .validate import run_all, summarize


def _print_samples(document: Dict[str, Any]) -> None:
    manifests = document.get("manifests", [])
    print("\n" + "=" * 72)
    print(f"PAGE MANIFESTS ({len(manifests)} pages) — eyeball against the PDF")
    print("=" * 72)
    for m in manifests:
        print(f"\n--- page {m.get('page_number')} ---")
        print(json.dumps(m, ensure_ascii=False, indent=2))


def _append_run_log(log_path: Path, record: Dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _atomic_write_json(path: Path, document: Dict[str, Any]) -> None:
    """Write JSON to disk atomically (write-then-rename via os.replace).

    POSIX `os.replace` is atomic on the same filesystem, so a reader will
    never see a partial JSON file even mid-write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _load_seed_document(
    output_path: Path,
    expected_plan_id: str,
    expected_submission_id: str,
    expected_source_sha256: str,
) -> Optional[Dict[str, Any]]:
    """Load an existing output file as a seed for incremental save.

    Returns None if the file doesn't exist. Raises if metadata doesn't match
    (refuses to merge into a file extracted from a different PDF / project /
    submission to prevent silent cross-contamination).
    """
    if not output_path.exists():
        return None
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Existing output file at {output_path} is not valid JSON: {exc}. "
            f"Delete or repair it before re-running."
        ) from exc

    for field, expected, actual_key in [
        ("plan_id", expected_plan_id, "plan_id"),
        ("submission_id", expected_submission_id, "submission_id"),
        ("source_pdf_sha256", expected_source_sha256, "source_pdf_sha256"),
    ]:
        actual = data.get(actual_key)
        if actual is not None and actual != expected:
            raise RuntimeError(
                f"Existing output file at {output_path} has {field}={actual!r}, "
                f"but this run expects {expected!r}. Refusing to merge. "
                f"Delete the file or write to a different --output path."
            )
    return data


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Per-page vision manifest extractor (M1)."
    )
    parser.add_argument("--project-id", required=True, help="Plan id, e.g. 407-1048248")
    parser.add_argument("--submission-id", required=True, help="Submission id, e.g. v24.3")
    parser.add_argument("--source-pdf", required=True, type=Path, help="Path to submission PDF")
    parser.add_argument("--output", required=True, type=Path, help="Output JSON path")
    parser.add_argument(
        "--pages",
        default="all",
        help='Page spec: "all", "1,13,26,39,52", or "1-10,20" (default: all)',
    )
    parser.add_argument(
        "--print-samples",
        action="store_true",
        help="Print each manifest to stdout",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=None,
        help="Run-log JSONL path (defaults to <output dir>/page_manifests.run_log.jsonl)",
    )
    args = parser.parse_args(argv)

    if not args.source_pdf.exists():
        print(f"ERROR: source pdf not found: {args.source_pdf}", file=sys.stderr)
        return 2

    with fitz.open(args.source_pdf) as doc:
        page_count = doc.page_count
    try:
        pages_to_process = parse_pages_spec(args.pages, page_count)
    except ValueError as exc:
        print(f"ERROR: bad --pages spec: {exc}", file=sys.stderr)
        return 2

    source_sha256 = hashlib.sha256(args.source_pdf.read_bytes()).hexdigest()

    # Load existing output (if any) as a seed for incremental save. Refuses to
    # merge if metadata mismatches — protects against silently overwriting
    # manifests from a different document.
    try:
        seed = _load_seed_document(
            args.output,
            expected_plan_id=args.project_id,
            expected_submission_id=args.submission_id,
            expected_source_sha256=source_sha256,
        )
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if seed is not None:
        print(
            f"Found existing output at {args.output} with "
            f"{len(seed.get('manifests', []))} manifests — will merge "
            f"(re-extracted pages overwrite existing entries)."
        )

    print(
        f"Extracting page manifests from {args.source_pdf} "
        f"(plan={args.project_id}, submission={args.submission_id})..."
    )
    print(f"  page_count: {page_count}")
    print(f"  pages to process: {len(pages_to_process)} ({pages_to_process[:10]}{'...' if len(pages_to_process) > 10 else ''})")

    # Callback persists partial progress after every successful page so a
    # mid-run crash (quota, network, JSON-truncation) doesn't lose work.
    def on_page_complete(doc: Dict[str, Any], _just_done: int) -> None:
        _atomic_write_json(args.output, doc)

    try:
        result = extract_manifests(
            pdf_path=args.source_pdf,
            plan_id=args.project_id,
            submission_id=args.submission_id,
            pages=pages_to_process,
            seed_document=seed,
            on_page_complete=on_page_complete,
        )
    except Exception as exc:
        print(
            f"\nERROR: extraction aborted: {exc}\n"
            f"Partial progress (if any) is saved at: {args.output}",
            file=sys.stderr,
        )
        raise
    document = result.document

    print(f"  source_pdf_sha256: {result.file_sha256}")
    print(f"  manifests in file: {len(document['manifests'])}")
    print(f"  aggregate token usage (this run): {result.aggregate_usage}")
    print(f"  total key rotation attempts (this run): {result.total_key_attempts}")

    print("\nRunning 7 automated checks...")
    checks = run_all(document, pages_to_process)
    all_ok, summary = summarize(checks)
    print(summary)

    # Final save (same content as the last incremental save; ensures consistency).
    _atomic_write_json(args.output, document)
    print(f"\nWrote: {args.output}")

    log_path = args.log_path or (args.output.parent / "page_manifests.run_log.jsonl")
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
            "source_pdf_sha256": result.file_sha256,
            "page_count": page_count,
            "pages_processed": pages_to_process,
            "manifest_count": len(document["manifests"]),
            "validation_result": "pass" if all_ok else "fail",
            "key_attempts": result.total_key_attempts,
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
    print("\nAll 7 automated checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
