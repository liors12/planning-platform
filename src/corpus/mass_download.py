"""
Mass-download orchestrator for Tel Aviv subcommittee protocol PDFs.

Reads `data/corpus/manifest/tel-aviv-protocols.yaml`, downloads every
`status: candidate` protocol PDF, runs the extractor on each, and writes
the manifest back with updated statuses.

Guardrails:
  - 2 second sleep between HTTP requests
  - interim report every 10 successful downloads
  - auto-stop on 3+ extraction_failed
  - auto-stop on 5+ 404 (not_found)
  - skips PDFs that already exist
  - skips IDs already marked in_corpus / not_found / extraction_failed

Usage:
    python3 src/corpus/mass_download.py
    python3 src/corpus/mass_download.py --limit 5    (cap at N candidates)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import traceback
import urllib.parse
from datetime import datetime
from pathlib import Path

import requests
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "data" / "corpus" / "manifest" / "tel-aviv-protocols.yaml"
EXTRACT_CLI = REPO_ROOT / "src" / "corpus" / "extract_protocol.py"

SLEEP_SECONDS = 2.0
INTERIM_EVERY = 10
STOP_ON_EXTRACTION_FAIL = 3
STOP_ON_404 = 5
HTTP_TIMEOUT = 60
DT_WARN_SECONDS = 30  # warn if a single download takes longer than this


# ──────────────────────────────────────────────────────────────────────
# Manifest IO — preserves comments and ordering by editing in place.
# ──────────────────────────────────────────────────────────────────────

def load_manifest() -> dict:
    with open(MANIFEST, encoding="utf-8") as f:
        return yaml.safe_load(f)


def update_protocol_status(protocol_id: str, new_status: str,
                           extra: dict | None = None) -> None:
    """Patch a single protocol's `status` (and optional extra fields) in place,
    preserving comments and surrounding YAML structure. Edits the file by line
    rewriting, not by re-emitting the full document."""
    text = MANIFEST.read_text(encoding="utf-8")
    lines = text.splitlines()

    out = []
    i = 0
    matched = False
    while i < len(lines):
        line = lines[i]
        # Detect the start of the protocol block matching this id
        if not matched and re.search(rf'id:\s*"{re.escape(protocol_id)}"', line):
            matched = True
            # Two cases:
            #  (a) inline form: `- { id: "...", year: ..., status: ... }`
            #  (b) block form spanning multiple lines
            if line.lstrip().startswith("-") and line.rstrip().endswith("}"):
                # Inline: rewrite the status field in-line
                new_line = re.sub(r'status:\s*\w+',
                                  f'status: {new_status}', line)
                if extra:
                    # Inject extra fields before the closing brace
                    extras = ", ".join(f'{k}: {yaml_scalar(v)}'
                                        for k, v in extra.items())
                    new_line = re.sub(r'\s*\}\s*$',
                                       f', {extras} }}', new_line)
                out.append(new_line)
            else:
                # Block: rewrite this line + look ahead for the status line
                out.append(line)
                j = i + 1
                while j < len(lines) and (lines[j].startswith("    ")
                                          or lines[j].startswith("      ")
                                          or lines[j].strip().startswith("notes:")
                                          or re.match(r"^\s+\w+:", lines[j])):
                    if "status:" in lines[j]:
                        lines[j] = re.sub(r'status:\s*\w+',
                                          f'status: {new_status}', lines[j])
                    j += 1
                # Continue copying through end of block
                for k in range(i + 1, j):
                    out.append(lines[k])
                # If extra fields requested, inject indented after status
                if extra:
                    indent = "    "
                    for k, v in extra.items():
                        out.append(f"{indent}{k}: {yaml_scalar(v)}")
                i = j - 1
        else:
            out.append(line)
        i += 1

    if not matched:
        raise KeyError(f"protocol id {protocol_id!r} not found in manifest")

    MANIFEST.write_text("\n".join(out) + ("\n" if text.endswith("\n") else ""),
                        encoding="utf-8")


def yaml_scalar(v) -> str:
    """Render a Python value as a YAML scalar (single-line)."""
    if isinstance(v, str):
        # Quote if contains special chars
        if any(c in v for c in ":#{}[],&*!|>'\"%@`") or v.lstrip() != v:
            return '"' + v.replace('"', '\\"') + '"'
        return v
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    return json.dumps(v, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────────────
# HTTP download
# ──────────────────────────────────────────────────────────────────────

def build_url(source: str, url_pattern: str, protocol_id: str) -> str:
    filename = url_pattern.format(ID=protocol_id)
    return source + "/" + urllib.parse.quote(filename)


def download_pdf(url: str, dest: Path) -> tuple[str, float]:
    """Return (status, elapsed_seconds) where status in {ok, not_found, error}.
    On `ok` the file is saved at `dest`."""
    t0 = time.monotonic()
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT,
                         headers={"User-Agent": "nzc-research/1.0"})
        elapsed = time.monotonic() - t0
        if r.status_code == 404:
            return "not_found", elapsed
        if not r.ok:
            return f"error_http_{r.status_code}", elapsed
        # Sanity: PDFs start with %PDF
        if not r.content.startswith(b"%PDF"):
            return "error_not_pdf", elapsed
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return "ok", elapsed
    except Exception as e:
        return f"error_exception:{type(e).__name__}", time.monotonic() - t0


# ──────────────────────────────────────────────────────────────────────
# Extraction
# ──────────────────────────────────────────────────────────────────────

def run_extractor(pdf_path: Path) -> tuple[bool, str]:
    """Run the extractor CLI as a subprocess, return (success, output_or_error)."""
    env = {"PYTHONPATH": str(REPO_ROOT / "src")}
    try:
        result = subprocess.run(
            [sys.executable, str(EXTRACT_CLI), str(pdf_path)],
            capture_output=True, text=True, timeout=180,
            env={**__import__("os").environ, **env},
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout)[:500]
        return True, result.stdout
    except subprocess.TimeoutExpired:
        return False, "extractor timed out (>180s)"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ──────────────────────────────────────────────────────────────────────
# Interim reports
# ──────────────────────────────────────────────────────────────────────

def interim_report(downloaded: int, missed_404: int, ext_failed: int,
                   results: list[dict]) -> None:
    print()
    print("─" * 72)
    print(f"INTERIM REPORT — after {downloaded + missed_404 + ext_failed} attempts")
    print("─" * 72)
    print(f"  downloaded + extracted: {downloaded}")
    print(f"  404 (not_found):        {missed_404}")
    print(f"  extraction_failed:      {ext_failed}")

    # Acceptance gate over current corpus
    extracted_dir = REPO_ROOT / "data" / "corpus" / "extracted"
    files = sorted(extracted_dir.glob("tlv-*-findings.json"))
    by_protocol = []
    flagged_low = []
    flagged_high_unknown = []
    for fp in files:
        d = json.loads(fp.read_text(encoding="utf-8"))
        if str(d.get("extracted_by", "")).startswith("manual-"):
            continue
        cs = d.get("cases", [])
        if not cs:
            continue
        complete = sum(1 for c in cs
                       if c["verdict"] != "unknown"
                       and len(c.get("findings", [])) >= 1
                       and c.get("gush") and c.get("address"))
        verdict_set = sum(1 for c in cs
                          if c["verdict"] != "unknown"
                          and c.get("gush") and c.get("address"))
        unknown = sum(1 for c in cs if c["verdict"] == "unknown")
        pct_complete = complete / len(cs)
        pct_unknown = unknown / len(cs)
        by_protocol.append({
            "id": d["protocol_id"],
            "cases": len(cs),
            "verdict_set": verdict_set / len(cs),
            "strict_complete": pct_complete,
            "unknown_pct": pct_unknown,
        })
        if pct_complete < 0.50:
            flagged_low.append((d["protocol_id"], pct_complete))
        if pct_unknown > 0.20:
            flagged_high_unknown.append((d["protocol_id"], pct_unknown))

    if by_protocol:
        avg_vs = sum(p["verdict_set"] for p in by_protocol) / len(by_protocol)
        print(f"\n  corpus protocols: {len(by_protocol)}, "
              f"mean verdict-set: {100*avg_vs:.0f}%")

    if flagged_low:
        print("\n  ⚠ FLAG — strictly-complete < 50%:")
        for pid, pct in flagged_low:
            print(f"    {pid}: {100*pct:.0f}%")
    if flagged_high_unknown:
        print("\n  ⚠ FLAG — unknown-verdict ratio > 20%:")
        for pid, pct in flagged_high_unknown:
            print(f"    {pid}: {100*pct:.0f}%")

    print("─" * 72)


# ──────────────────────────────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Cap on candidates to attempt")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest = load_manifest()
    source = manifest["source"]
    url_pattern = manifest["url_pattern"]
    fixture_dir = REPO_ROOT / manifest["fixture_dir"]
    candidates = [p for p in manifest["protocols"] if p["status"] == "candidate"]
    if args.limit:
        candidates = candidates[: args.limit]

    print(f"Mass download orchestrator")
    print(f"  manifest:       {MANIFEST}")
    print(f"  candidates:     {len(candidates)}")
    print(f"  fixture_dir:    {fixture_dir}")
    print(f"  sleep between:  {SLEEP_SECONDS}s")
    print(f"  auto-stop:      ≥{STOP_ON_EXTRACTION_FAIL} extraction_failed OR ≥{STOP_ON_404} 404")
    print()

    if args.dry_run:
        for c in candidates:
            url = build_url(source, url_pattern, c["id"])
            print(f"  would fetch: {c['id']} → {url}")
        return 0

    downloaded = 0
    missed_404 = 0
    ext_failed = 0
    results: list[dict] = []

    for idx, c in enumerate(candidates, 1):
        pid = c["id"]
        pdf_path = fixture_dir / f"tlv-{pid}.pdf"
        url = build_url(source, url_pattern, pid)

        print(f"[{idx}/{len(candidates)}] {pid} … ", end="", flush=True)

        if pdf_path.exists():
            print("PDF already on disk, skipping download")
            # Still ensure extraction was run (idempotent)
            ok, out = run_extractor(pdf_path)
            if ok:
                update_protocol_status(pid, "in_corpus")
                downloaded += 1
            else:
                update_protocol_status(pid, "extraction_failed",
                                       {"extraction_error": out[:140]})
                ext_failed += 1
            continue

        status, elapsed = download_pdf(url, pdf_path)
        if status == "not_found":
            print(f"404 ({elapsed:.1f}s)")
            update_protocol_status(pid, "not_found")
            missed_404 += 1
            time.sleep(SLEEP_SECONDS)
            if missed_404 >= STOP_ON_404:
                print(f"\n⚠ AUTO-STOP: {missed_404} consecutive 404s — possible URL pattern change")
                break
            continue
        elif status != "ok":
            print(f"error: {status} ({elapsed:.1f}s)")
            update_protocol_status(pid, "extraction_failed",
                                   {"download_error": status})
            ext_failed += 1
            time.sleep(SLEEP_SECONDS)
            if ext_failed >= STOP_ON_EXTRACTION_FAIL:
                print(f"\n⚠ AUTO-STOP: {ext_failed} download/extraction failures")
                break
            continue

        size_kb = pdf_path.stat().st_size / 1024
        dt_warn = " ⚠SLOW" if elapsed > DT_WARN_SECONDS else ""
        print(f"downloaded ({size_kb:.0f} KB, {elapsed:.1f}s{dt_warn})", end="", flush=True)

        # Extract
        update_protocol_status(pid, "downloaded")
        ok, out = run_extractor(pdf_path)
        if not ok:
            print(" → extraction FAILED")
            update_protocol_status(pid, "extraction_failed",
                                   {"extraction_error": out[:140]})
            ext_failed += 1
            time.sleep(SLEEP_SECONDS)
            if ext_failed >= STOP_ON_EXTRACTION_FAIL:
                print(f"\n⚠ AUTO-STOP: {ext_failed} extraction failures — possible format change")
                break
            continue

        print(" → extracted")
        update_protocol_status(pid, "in_corpus")
        downloaded += 1

        # Interim report every N successful downloads
        if downloaded > 0 and downloaded % INTERIM_EVERY == 0:
            interim_report(downloaded, missed_404, ext_failed, results)

        time.sleep(SLEEP_SECONDS)

    # Final summary
    print()
    print("=" * 72)
    print("MASS DOWNLOAD COMPLETE")
    print("=" * 72)
    print(f"  attempted:               {downloaded + missed_404 + ext_failed}")
    print(f"  downloaded + extracted:  {downloaded}")
    print(f"  404 (not_found):         {missed_404}")
    print(f"  extraction_failed:       {ext_failed}")
    print(f"  remaining candidates:    {len(candidates) - (downloaded + missed_404 + ext_failed)}")

    interim_report(downloaded, missed_404, ext_failed, results)

    return 0


if __name__ == "__main__":
    sys.exit(main())
