"""
Render a Markdown analysis report as a Hebrew-RTL PDF via headless Chrome.

Why Chrome (not WeasyPrint): macOS WeasyPrint needs `brew install pango`
system-level. Chrome ships with the same browser engine that renders RTL
Hebrew text on every Israeli site — no extra deps, no font drama.

Usage:
    python3 src/render_report_pdf.py reports/407-0977595/tashrit-analysis-2026-04-30.md
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown


CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]


# Page-level CSS:
#  - dir="rtl" on <html>; per-block `unicode-bidi: plaintext` lets each
#    paragraph pick LTR/RTL by its own first strong character (so an
#    English-heavy paragraph still flows left-to-right inside an RTL page).
#  - Arial Unicode MS is shipped with macOS and covers Hebrew + Latin cleanly.
#    Heebo is a dedicated Hebrew sans (loaded via Google Fonts as fallback).
#  - Tables stay LTR for readability of code identifiers and numbers.
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;600;700&display=swap');

@page {
  size: A4;
  margin: 18mm 16mm 20mm 16mm;
  @bottom-center {
    content: counter(page) " / " counter(pages);
    font-family: 'Heebo', 'Arial Unicode MS', sans-serif;
    font-size: 9pt;
    color: #888;
  }
}

html { direction: rtl; }

body {
  font-family: 'Heebo', 'Arial Unicode MS', 'Arial Hebrew', sans-serif;
  font-size: 11pt;
  line-height: 1.6;
  color: #1a1a1a;
  unicode-bidi: plaintext;
}

p, li, dd, dt, blockquote, td, th {
  unicode-bidi: plaintext;
}

h1 {
  color: #005030;          /* brand primary */
  border-bottom: 3px solid #007840;
  padding-bottom: 8pt;
  font-size: 22pt;
  font-weight: 700;
  margin-top: 0;
  page-break-after: avoid;
}

h2 {
  color: #005030;
  font-size: 16pt;
  font-weight: 700;
  margin-top: 22pt;
  margin-bottom: 8pt;
  border-right: 4px solid #007840;
  padding-right: 10pt;
  page-break-after: avoid;
}

h3 {
  color: #2a2a2a;
  font-size: 13pt;
  font-weight: 600;
  margin-top: 14pt;
  margin-bottom: 6pt;
  page-break-after: avoid;
}

p { margin: 6pt 0; }

ul, ol {
  /* RTL bullets: pad on the right side */
  padding-right: 22pt;
  padding-left: 0;
  margin: 4pt 0;
}

li { margin: 2pt 0; }

strong { color: #005030; font-weight: 600; }

code, kbd, samp, pre {
  font-family: 'SF Mono', 'Menlo', 'Consolas', monospace;
  font-size: 9.5pt;
  /* Identifiers always read left-to-right */
  direction: ltr;
  unicode-bidi: bidi-override;
}

p > code, li > code, td > code, th > code {
  background: #f3f4f1;
  padding: 1px 5px;
  border-radius: 3px;
  border: 1px solid #e2e5dd;
  white-space: nowrap;
}

pre {
  background: #f8f8f6;
  border: 1px solid #e2e5dd;
  border-right: 4px solid #007840;
  padding: 10pt;
  border-radius: 4px;
  overflow-x: auto;
  page-break-inside: avoid;
}

table {
  /* Tables read LTR — easier for numbers, code, file paths */
  direction: ltr;
  border-collapse: collapse;
  width: 100%;
  margin: 10pt 0;
  font-size: 10pt;
  page-break-inside: avoid;
}

table, th, td { border: 1px solid #d6d8d2; }

th {
  background: #005030;
  color: #fff;
  font-weight: 600;
  text-align: left;
  padding: 6pt 8pt;
}

td {
  padding: 5pt 8pt;
  vertical-align: top;
}

tbody tr:nth-child(even) { background: #f8f8f6; }

blockquote {
  border-right: 4px solid #007840;
  background: #f3f4f1;
  margin: 12pt 0;
  padding: 8pt 14pt;
  color: #2a2a2a;
  page-break-inside: avoid;
}

hr {
  border: 0;
  border-top: 1px solid #e2e5dd;
  margin: 18pt 0;
}

/* Verdict lines pop */
p strong:first-child:not(:only-child) {
  /* "Verdict: …" — already styled by <strong> */
}

/* ✓ ⚠ ✗ symbols a tad bigger */
.report-meta {
  background: #f3f4f1;
  padding: 10pt 14pt;
  border-radius: 4px;
  margin-bottom: 18pt;
  font-size: 10pt;
  border-right: 4px solid #007840;
}
"""


HTML_TEMPLATE = """<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
{css}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def find_chrome() -> str | None:
    for p in CHROME_PATHS:
        if Path(p).exists():
            return p
    for cmd in ("google-chrome", "chromium", "chrome"):
        which = shutil.which(cmd)
        if which:
            return which
    return None


def md_to_html(md_text: str) -> str:
    return markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
    )


def render_pdf(md_path: Path, out_path: Path) -> None:
    chrome = find_chrome()
    if not chrome:
        raise SystemExit("ERROR: no Chrome/Chromium found in /Applications or PATH")

    md_text = md_path.read_text(encoding="utf-8")
    body_html = md_to_html(md_text)
    title = md_path.stem
    full = HTML_TEMPLATE.format(title=title, css=CSS, body=body_html)

    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "report.html"
        html_path.write_text(full, encoding="utf-8")

        # Headless Chrome → PDF. --no-pdf-header-footer keeps pages clean.
        # --virtual-time-budget gives Google Fonts time to load.
        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            "--virtual-time-budget=4000",
            f"--print-to-pdf={out_path}",
            html_path.as_uri(),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not out_path.exists():
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            raise SystemExit(f"chrome --print-to-pdf failed (exit {result.returncode})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a Markdown report to a Hebrew-RTL PDF")
    parser.add_argument("md", help="Path to the Markdown report")
    parser.add_argument("--out", help="Output PDF path (default: alongside the .md)")
    args = parser.parse_args()

    md_path = Path(args.md).resolve()
    if not md_path.exists():
        print(f"ERROR: not found: {md_path}", file=sys.stderr)
        return 1

    out_path = Path(args.out).resolve() if args.out else md_path.with_suffix(".pdf")
    render_pdf(md_path, out_path)
    print(f"PDF written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
