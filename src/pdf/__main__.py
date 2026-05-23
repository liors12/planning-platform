"""CLI for ad-hoc PDF generation during development.

Usage:
    python -m src.pdf --engine-run-id <UUID> --db <path> --output /tmp/draft.pdf

Pass --html-only to write the intermediate HTML instead of invoking Chrome
— useful when iterating on the template/CSS without paying the Chrome
startup cost on every change.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path
_SRC = _Path(__file__).resolve().parents[1]
if str(_SRC) not in _sys.path:
    _sys.path.insert(0, str(_SRC))

from pdf.generator import generate_compliance_opinion, render_html  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.pdf",
        description="Generate a draft חוות דעת PDF from a completed engine run.",
    )
    parser.add_argument("--engine-run-id", required=True,
                        help="UUID of the engine_runs row to render.")
    parser.add_argument("--db", required=True,
                        help="Path to the SQLite database.")
    parser.add_argument("--output", required=True,
                        help="Output PDF path.")
    parser.add_argument("--html-only", action="store_true",
                        help="Write HTML to --output instead of running Chrome.")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        if args.html_only:
            html = render_html(args.engine_run_id, conn)
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html, encoding="utf-8")
            print(f"HTML written: {out}")
        else:
            out = generate_compliance_opinion(
                engine_run_id=args.engine_run_id,
                db_conn=conn,
                output_path=Path(args.output),
            )
            print(f"PDF written: {out}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
