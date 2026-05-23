"""CLI: extract a Tel Aviv subcommittee protocol PDF into findings JSON.

Usage:
    python3 src/corpus/extract_protocol.py <pdf_path>
    python3 src/corpus/extract_protocol.py <pdf_path> --out <findings.json> --report <report.md>

Defaults:
    out    = data/corpus/extracted/<protocol_id>-findings.json
    report = data/corpus/extracted/<protocol_id>-extraction-report.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

# Self-bootstrap sys.path so the `corpus.extractors.*` imports below resolve
# regardless of how the script was invoked. This is required because the
# repo path contains colons (e.g. ":planning-platform:"), which Python's
# PYTHONPATH parser treats as path separators — so passing PYTHONPATH from
# a parent process (e.g. mass_download.py) silently shreds it. Inserting
# the absolute "src" dir directly into sys.path here is the robust fix.
_SRC_DIR = str(Path(__file__).resolve().parents[1])
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from corpus.extractors.pdf_to_text import extract_text
from corpus.extractors.case_splitter import split_cases
from corpus.extractors.case_parser import parse_case


PROTOCOL_ID_RE = re.compile(r"(\d-\d{2}-\d{4})")
SESSION_DATE_RE = re.compile(r"תאריך\s*[:.]?\s*(\d{1,2}/\d{1,2}/\d{4})")


def derive_protocol_id(pdf_path: Path, full_text: str) -> str:
    """Try filename first, then text body."""
    m = PROTOCOL_ID_RE.search(pdf_path.stem)
    if m:
        return m.group(1)
    m = PROTOCOL_ID_RE.search(full_text[:5000])
    if m:
        return m.group(1)
    return "unknown"


def derive_session_date(full_text: str) -> str | None:
    m = SESSION_DATE_RE.search(full_text[:3000])
    if not m:
        return None
    d = m.group(1)
    parts = d.split("/")
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
    return None


def render_extraction_report(payload: dict, low_conf_cases: list[dict]) -> str:
    cases = payload["cases"]
    verdicts = Counter(c["verdict"] for c in cases)
    confs = [c["extraction_confidence"] for c in cases]
    avg_conf = sum(confs) / len(confs) if confs else 0.0

    lines = [
        f"# Extraction report — {payload['protocol_id']}",
        "",
        f"- Source PDF: `{payload['source_pdf']}`",
        f"- Session date: {payload.get('session_date') or '?'}",
        f"- Generated: {date.today().isoformat()}",
        f"- Cases extracted: **{len(cases)}**",
        f"- Average extraction confidence: **{avg_conf:.2f}**",
        "",
        "## Verdict distribution",
        "",
    ]
    for v, n in verdicts.most_common():
        lines.append(f"- `{v}`: {n}")
    lines.append("")

    # Findings tally
    rc_counts: Counter[str] = Counter()
    for c in cases:
        for f in c.get("findings", []):
            rc = f.get("reason_class") or "(unclassified)"
            rc_counts[rc] += 1
    lines.append("## Reason-class distribution")
    lines.append("")
    for rc, n in rc_counts.most_common():
        lines.append(f"- `{rc}`: {n}")
    lines.append("")

    # Low-confidence cases
    lines.append("## Cases with confidence < 0.70 (manual review recommended)")
    lines.append("")
    if not low_conf_cases:
        lines.append("_None._")
    else:
        for c in low_conf_cases:
            warns = "; ".join(c.get("extraction_warnings") or []) or "—"
            lines.append(
                f"- **{c['case_id']}** ({c.get('address') or '?'}): "
                f"verdict=`{c['verdict']}`, conf={c['extraction_confidence']:.2f}, "
                f"warnings: {warns}"
            )
    lines.append("")

    # All warnings summary
    all_warnings: Counter[str] = Counter()
    for c in cases:
        for w in c.get("extraction_warnings", []):
            all_warnings[w] += 1
    if all_warnings:
        lines.append("## Warnings (all cases)")
        lines.append("")
        for w, n in all_warnings.most_common():
            lines.append(f"- ({n}×) {w}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a TLV protocol PDF to findings JSON")
    parser.add_argument("pdf", help="Path to protocol PDF")
    parser.add_argument("--out", help="Override output JSON path")
    parser.add_argument("--report", help="Override extraction report path")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    full_text, _pages = extract_text(pdf_path)
    protocol_id = derive_protocol_id(pdf_path, full_text)
    session_date = derive_session_date(full_text)

    blocks = split_cases(full_text)
    if not blocks:
        print(f"ERROR: no cases detected in {pdf_path}", file=sys.stderr)
        return 2

    cases = []
    for blk in blocks:
        case_dict, conf, warns = parse_case(blk)
        cases.append(case_dict)

    payload = {
        "protocol_id": protocol_id,
        "municipality": "tel-aviv",
        "session_date": session_date,
        "extracted_by": "automated-extractor-v1",
        "extracted_at": date.today().isoformat(),
        "source_pdf": str(pdf_path.relative_to(repo_root)) if str(pdf_path).startswith(str(repo_root)) else str(pdf_path),
        "cases_total_in_protocol": len(cases),
        "cases_extracted_here": len(cases),
        "extraction_note": (
            "Automated extraction via deterministic regex anchors on the standard "
            "Tel Aviv subcommittee protocol format. See "
            "src/corpus/extractors/."
        ),
        "cases": cases,
    }

    # If a manual gold-standard already exists for this protocol, write the
    # automated output to a sibling path so we don't clobber it.
    gold_path = repo_root / "data" / "corpus" / "gold-standard" / f"tlv-{protocol_id}-findings.json"
    default_name = (
        f"tlv-{protocol_id}-auto-findings.json"
        if gold_path.exists()
        else f"tlv-{protocol_id}-findings.json"
    )
    out_path = Path(args.out) if args.out else (
        repo_root / "data" / "corpus" / "extracted" / default_name
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    low_conf = sorted(
        [c for c in cases if c["extraction_confidence"] < 0.70],
        key=lambda c: c["extraction_confidence"],
    )
    report_path = Path(args.report) if args.report else (
        repo_root / "data" / "corpus" / "extracted" / f"tlv-{protocol_id}-extraction-report.md"
    )
    report_path.write_text(render_extraction_report(payload, low_conf), encoding="utf-8")

    print(f"protocol: {protocol_id}")
    print(f"cases:    {len(cases)}")
    print(f"avg conf: {sum(c['extraction_confidence'] for c in cases) / len(cases):.2f}")
    print(f"json:     {out_path}")
    print(f"report:   {report_path}")
    return 0


if __name__ == "__main__":
    # Allow `python3 src/corpus/extract_protocol.py ...` to import via package path
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "src"))
    sys.exit(main())
