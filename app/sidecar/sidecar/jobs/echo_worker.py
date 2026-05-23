"""Phase 1 demo worker — echoes its input payload, with metadata.

The point of this worker is not its functionality; it's to lock down the
ADR-001 § Implication 1 contract on day one. Every future worker
(`scripts/run_audit.py`, `scripts/dwg_parse.py`, future LLM extractor) follows
the same pattern this script demonstrates:

  1. Receive `--job-dir DIR` on the command line.
  2. Read `DIR/job_input.json`.
  3. Do the work (here: trivially).
  4. Write `DIR/job_output.json` on success OR `DIR/error.json` on failure.
  5. Exit 0 on success, non-zero on failure.

This script is intentionally importable as a `python -m sidecar.jobs.echo_worker`
target so the dispatch helper doesn't have to know an absolute path.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 1 echo worker (ADR-001 demo).")
    parser.add_argument("--job-dir", required=True, type=Path,
                        help="per-invocation job temp dir; contains job_input.json")
    args = parser.parse_args(argv)

    job_dir: Path = args.job_dir
    input_path = job_dir / "job_input.json"
    output_path = job_dir / "job_output.json"
    error_path = job_dir / "error.json"

    try:
        if not input_path.exists():
            raise FileNotFoundError(f"missing input file: {input_path}")
        payload = json.loads(input_path.read_text(encoding="utf-8"))

        # The "work": echo the payload + add some proof-of-isolation metadata
        # so the caller can verify it ran in a separate process.
        response = {
            "echo": payload,
            "worker_info": {
                "pid": os.getpid(),
                "ppid": os.getppid(),
                "python": sys.executable,
                "python_version": sys.version.split()[0],
                "platform": platform.platform(),
                "executed_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        output_path.write_text(
            json.dumps(response, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 0
    except Exception as exc:
        # The contract: write error.json on failure so the sidecar can surface
        # a structured error to the UI instead of guessing from stderr.
        error_path.write_text(
            json.dumps({
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "executed_at": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"echo_worker failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
