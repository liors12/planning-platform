"""Render a sample חוות דעת PDF + intermediate HTML for Ellen's review.

Builds the in-memory synthetic DB via tests/fixtures/synthetic_run.py and
runs the real PDF generator against it. Produces:

  /tmp/draft_chavat_daat_sample.pdf
  /tmp/draft_chavat_daat_sample.html

Run:
  python3 scripts/generate_sample_pdf.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures.synthetic_run import build_run_with_engine_errors  # noqa: E402
from pdf.generator import generate_compliance_opinion, render_html  # noqa: E402


PDF_OUT = Path("/tmp/draft_chavat_daat_sample.pdf")
HTML_OUT = Path("/tmp/draft_chavat_daat_sample.html")


def main() -> int:
    # Use the engine-errors variant so the system-health warning fires,
    # the cluster banner folds the swarm of identical errors on
    # תא שטח 102, and the inline failure-mode pills surface on the
    # singleton engine-error rows on the other parcels. This is the
    # most format-stressing fixture; a happy-path version still
    # available via build_synthetic_run() if Ellen wants both.
    conn, engine_run_id = build_run_with_engine_errors()
    try:
        html = render_html(engine_run_id, conn)
        HTML_OUT.write_text(html, encoding="utf-8")

        generate_compliance_opinion(
            engine_run_id=engine_run_id,
            db_conn=conn,
            output_path=PDF_OUT,
        )
    finally:
        conn.close()

    pdf_size = PDF_OUT.stat().st_size
    html_size = HTML_OUT.stat().st_size
    print(f"HTML: {HTML_OUT}  ({html_size:,} bytes)")
    print(f"PDF:  {PDF_OUT}  ({pdf_size:,} bytes)")
    print(f"engine_run_id: {engine_run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
