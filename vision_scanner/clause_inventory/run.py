"""CLI entry point for clause inventory extraction.

Usage:
    python -m vision_scanner.clause_inventory.run \
        --project-id 407-1048248 \
        --source-pdf data/projects/407-1048248/source-documents/takanon.pdf \
        --output data/projects/407-1048248/canonical_clauses.tmp.json \
        --print-samples
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .extract import EXTRACTOR_VERSION, MODEL_NAME, PROMPT_VERSION, extract_clauses
from .postprocess import apply_postprocess
from .validate import run_all, summarize


def _print_samples(document: Dict[str, Any], seed: int = 42) -> None:
    clauses: List[Dict[str, Any]] = document.get("clauses", [])
    non_table = [c for c in clauses if c.get("clause_id") != "5.table"]
    rng = random.Random(seed)
    sample = rng.sample(non_table, k=min(10, len(non_table)))

    print("\n" + "=" * 72)
    print("MANUAL SPOT-CHECK SAMPLES (Lior — eyeball against the PDF)")
    print("=" * 72)

    print("\n--- (1/3) 10 RANDOM CLAUSES ---\n")
    for i, clause in enumerate(sample, 1):
        print(f"[random {i}/{len(sample)}]")
        print(json.dumps(clause, ensure_ascii=False, indent=2))
        print()

    print("\n--- (2/3) §5 BUILDING RIGHTS TABLE (full) ---\n")
    table = next((c for c in clauses if c.get("clause_id") == "5.table"), None)
    if table is None:
        print("(no 5.table clause found)")
    else:
        print(json.dumps(table, ensure_ascii=False, indent=2))

    print("\n--- (3/3) ALL CLAUSES OF §6 ---\n")
    section_6 = [
        c for c in clauses
        if c.get("clause_id") == "6" or (c.get("clause_id", "").startswith("6."))
    ]
    section_6.sort(key=lambda c: c.get("clause_id", ""))
    if not section_6:
        print("(no §6 clauses found)")
    else:
        for i, clause in enumerate(section_6, 1):
            print(f"[§6 {i}/{len(section_6)}]")
            print(json.dumps(clause, ensure_ascii=False, indent=2))
            print()


def _append_run_log(log_path: Path, record: Dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract canonical clause inventory from a takanon PDF.")
    parser.add_argument("--project-id", required=True, help="Plan id, e.g. 407-1048248")
    parser.add_argument("--source-pdf", type=Path, default=None, help="Path to takanon PDF (omit when --postprocess-only is set)")
    parser.add_argument("--output", required=True, type=Path, help="Output JSON path")
    parser.add_argument(
        "--print-samples",
        action="store_true",
        help="Print 10 random + §5 + §6 to stdout for manual spot-check",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=None,
        help="Run-log JSONL path (defaults to <output dir>/canonical_clauses.run_log.jsonl)",
    )
    parser.add_argument(
        "--postprocess-only",
        type=Path,
        default=None,
        help="Skip the Gemini call: load this JSON, run postprocess + validation, "
             "write to --output, print samples. No API call.",
    )
    args = parser.parse_args(argv)

    if args.postprocess_only is not None:
        if not args.postprocess_only.exists():
            print(f"ERROR: --postprocess-only path not found: {args.postprocess_only}", file=sys.stderr)
            return 2
        print(f"Postprocess-only: loading {args.postprocess_only}...")
        document = json.loads(args.postprocess_only.read_text(encoding="utf-8"))
        clauses_before = len(document.get("clauses", []))
        document = apply_postprocess(document)
        clauses_after = len(document.get("clauses", []))
        print(f"  clauses before: {clauses_before}")
        print(f"  clauses after:  {clauses_after}")
        usage_metadata = None
        file_sha = document.get("source_doc_sha256", "")
        text_sha = document.get("source_doc_text_sha256", "")
        key_attempts = 0
        validation_label_extra = "postprocess"
    else:
        if args.source_pdf is None:
            print("ERROR: --source-pdf is required unless --postprocess-only is set.", file=sys.stderr)
            return 2
        if not args.source_pdf.exists():
            print(f"ERROR: source pdf not found: {args.source_pdf}", file=sys.stderr)
            return 2

        print(f"Extracting clauses from {args.source_pdf} (plan={args.project_id})...")
        result = extract_clauses(args.source_pdf, args.project_id)
        document = apply_postprocess(result.document)
        print(f"  source_doc_sha256: {result.file_sha256}")
        print(f"  source_doc_text_sha256: {result.text_sha256}")
        print(f"  page_count: {result.page_count}")
        print(f"  clauses returned: {len(document['clauses'])}")
        if result.usage_metadata:
            print(f"  gemini usage: {result.usage_metadata}")
        print(f"  key rotation attempts: {result.key_attempts}")
        usage_metadata = result.usage_metadata
        file_sha = result.file_sha256
        text_sha = result.text_sha256
        key_attempts = result.key_attempts
        validation_label_extra = "extract"

    print("\nRunning 8 automated checks...")
    checks = run_all(document)
    all_ok, summary = summarize(checks)
    print(summary)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nWrote: {args.output}")

    log_path = args.log_path or (args.output.parent / "canonical_clauses.run_log.jsonl")
    _append_run_log(
        log_path,
        {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model": MODEL_NAME,
            "extractor_version": EXTRACTOR_VERSION,
            "prompt_version": PROMPT_VERSION,
            "phase": validation_label_extra,
            "source_sha256": file_sha,
            "source_text_sha256": text_sha,
            "clause_count": len(document["clauses"]),
            "validation_result": "pass" if all_ok else "fail",
            "key_attempts": key_attempts,
            "usage_metadata": usage_metadata,
            "output_path": str(args.output),
        },
    )
    print(f"Logged run to: {log_path}")

    if args.print_samples:
        _print_samples(document)

    if not all_ok:
        print("\nVALIDATION FAILED — see [FAIL] lines above.", file=sys.stderr)
        return 1
    print("\nAll 8 automated checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
