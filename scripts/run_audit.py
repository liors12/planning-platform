#!/opt/homebrew/bin/python3.13
"""Run a full audit (format + content + disciplines) for a submission.

This script has two invocation forms:

  1. **Canonical — `--job-dir` contract** (ADR-001 § Implication 1):

         python3.13 scripts/run_audit.py --job-dir DIR

     where `DIR/job_input.json` contains:
         {
           "pdf_path":                  "absolute path",
           "schema_path":               "absolute path",
           "project_key":               "407-1048248",
           "submission_version":        "24.3",
           "extracts_path":             "absolute path (optional)",
           "discipline_findings_path":  "absolute path (optional)",
           "audit_outputs_root":        "absolute path (optional)"
         }

     On success: writes `DIR/job_output.json` (the full audit_results dict).
     On failure: writes `DIR/error.json` + exits non-zero.

  2. **Backward-compat — positional CLI** (preserved for v8j manual runs):

         python3.13 scripts/run_audit.py PROJECT_KEY SUBMISSION_VERSION [--no-pdf]
         python3.13 scripts/run_audit.py 407-1048248 24.3

     Reconstructs job_input.json internally from the repo's
     `projects/{project_key}/submissions/v{version}/metadata.json` layout,
     calls the canonical form, then ALSO writes
     `audit_outputs/{project_key}/v{version}/audit_results.json` and the
     Hebrew PDF report (unless `--no-pdf`).

The Homebrew Python is required because WeasyPrint needs Pango/Cairo from
/opt/homebrew/lib (system Python on macOS doesn't see them).

See:
  - docs/architecture/ADR-001-subprocess-isolation.md
  - docs/architecture/job_types.md (run_audit row)
  - docs/phase_2b_commitments.md (ticket #1 — this migration)
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from compliance_engine.audit import run_full_audit  # noqa: E402
from compliance_engine.report_generator import generate_audit_pdf  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Canonical: --job-dir contract
# ─────────────────────────────────────────────────────────────────────────────

def _run_with_job_dir(job_dir: Path) -> int:
    """Execute the audit per ADR-001 § Implication 1.

    Reads `job_dir/job_input.json`, runs the audit, writes
    `job_dir/job_output.json` on success or `job_dir/error.json` on failure.
    """
    input_path = job_dir / "job_input.json"
    output_path = job_dir / "job_output.json"
    error_path = job_dir / "error.json"

    try:
        if not input_path.exists():
            raise FileNotFoundError(f"missing input file: {input_path}")
        payload = json.loads(input_path.read_text(encoding="utf-8"))

        pdf_path = _required_path(payload, "pdf_path")
        schema_path = _required_path(payload, "schema_path")
        project_key = payload.get("project_key")
        submission_version = payload.get("submission_version")
        if not project_key or not submission_version:
            raise ValueError("job_input.json must include project_key + submission_version")

        extracts_path = _optional_path(payload, "extracts_path")
        discipline_findings_path = _optional_path(payload, "discipline_findings_path")
        audit_outputs_root = _optional_path(payload, "audit_outputs_root")
        feedback_db_path = _optional_path(payload, "feedback_db_path")

        project_schema = json.loads(schema_path.read_text(encoding="utf-8"))

        # `run_full_audit` resolves extracts.json + discipline_findings.json
        # from `pdf_path.parent`. Stage them next to the PDF if the caller
        # supplied explicit paths from somewhere else; otherwise rely on the
        # default lookup.
        _maybe_stage_overlay(pdf_path.parent, "extracts.json", extracts_path)
        _maybe_stage_overlay(pdf_path.parent, "discipline_findings.json",
                             discipline_findings_path)

        results = run_full_audit(
            pdf_path,
            project_schema,
            audit_outputs_root=audit_outputs_root,
            project_key=project_key,
            submission_version=submission_version,
            feedback_db_path=feedback_db_path,
        )

        # Serialize with the same conventions as the v8j-era output:
        # ensure_ascii=False (Hebrew stays as Hebrew, not \uXXXX),
        # indent=2 (human-readable diffs), sort_keys=True (stable byte order).
        output_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return 0
    except Exception as exc:
        error_path.write_text(
            json.dumps({
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "traceback": traceback.format_exc(),
                "executed_at": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"run_audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


def _required_path(payload: dict, key: str) -> Path:
    raw = payload.get(key)
    if not raw:
        raise ValueError(f"job_input.json missing required key {key!r}")
    p = Path(raw)
    if not p.exists():
        raise FileNotFoundError(f"{key} does not exist on disk: {p}")
    return p


def _optional_path(payload: dict, key: str) -> Path | None:
    raw = payload.get(key)
    return Path(raw) if raw else None


def _maybe_stage_overlay(submission_dir: Path, leaf: str, source: Path | None) -> None:
    """If the caller supplied an explicit overlay path, stage it next to the
    PDF where `run_full_audit` expects to find it. No-op if `source` is None
    or already at the canonical location."""
    if source is None:
        return
    target = submission_dir / leaf
    try:
        if source.resolve() == target.resolve():
            return  # already in place
    except FileNotFoundError:
        pass
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())


# ─────────────────────────────────────────────────────────────────────────────
# Backward-compat: positional CLI wrapper
# ─────────────────────────────────────────────────────────────────────────────

def _run_legacy_positional(project_key: str, submission_version: str,
                            output_subdir: str, generate_pdf: bool) -> int:
    """Old v8j CLI form. Reconstructs job_input.json from the repo layout and
    delegates to the canonical `--job-dir` form, then copies the output back
    to the legacy `audit_outputs/{key}/v{version}/audit_results.json` location
    (and optionally renders the Hebrew PDF report).
    """
    submission_dir = ROOT / "projects" / project_key / "submissions" / f"v{submission_version}"
    metadata_path = submission_dir / "metadata.json"
    if not metadata_path.exists():
        print(f"ERROR: metadata not found at {metadata_path}", file=sys.stderr)
        return 1
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    pdf_path = submission_dir / metadata["file_name"]
    if not pdf_path.exists():
        print(f"ERROR: PDF not found at {pdf_path}", file=sys.stderr)
        return 1

    schema_path = ROOT / "projects" / project_key / f"project-schema-{project_key}-v2.json"
    if not schema_path.exists():
        # Fallback to repo-root copy used during early bring-up.
        schema_path = ROOT / f"project-schema-{project_key}-v2.json"
    if not schema_path.exists():
        print(f"ERROR: schema not found for {project_key}", file=sys.stderr)
        return 1

    output_dir = ROOT / output_subdir / project_key / f"v{submission_version}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Stage a temp job-dir as a sibling of the output dir.
    import tempfile, shutil
    with tempfile.TemporaryDirectory(prefix=f"run_audit_{project_key}_") as tmp:
        job_dir = Path(tmp)
        (job_dir / "job_input.json").write_text(
            json.dumps({
                "pdf_path": str(pdf_path),
                "schema_path": str(schema_path),
                "project_key": project_key,
                "submission_version": submission_version,
                "audit_outputs_root": str(ROOT / output_subdir),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"Running full audit on {pdf_path}")
        rc = _run_with_job_dir(job_dir)
        if rc != 0:
            err_path = job_dir / "error.json"
            if err_path.exists():
                print(err_path.read_text(encoding="utf-8"), file=sys.stderr)
            return rc

        job_output = job_dir / "job_output.json"
        legacy_json = output_dir / "audit_results.json"
        shutil.copyfile(job_output, legacy_json)
        print(f"JSON results: {legacy_json}")

        results = json.loads(job_output.read_text(encoding="utf-8"))

    # ── Per-section verdict summary (v8j console output, byte-stable) ──
    _print_verdict_summary("Format", results.get("format", []))
    _print_verdict_summary(f"Content rules summary ({len(results.get('content', []))} total)",
                           results.get("content", []), include_total=False)
    _print_verdict_summary(f"Discipline rules summary ({len(results.get('disciplines', []))} total)",
                           results.get("disciplines", []), include_total=False)

    eq = (results.get("extraction_cache") or {}).get("extraction_quality") or {}
    print(f"\nExtraction quality: llm_available={eq.get('llm_available')}, "
          f"llm_used={eq.get('llm_used')}, "
          f"fields_extracted={eq.get('fields_extracted_count')}")
    fb = results.get("feedback_entries", [])
    if fb:
        print(f"Feedback entries merged: {len(fb)}")

    if generate_pdf:
        project_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        pdf_out = output_dir / f"audit_report_{submission_version}.pdf"
        # M4: if an M4-enriched audit_results.m4.json exists alongside the
        # engine output, prefer it for PDF rendering. The .m4 file extends the
        # engine schema with override + sidecar info; report_generator falls
        # back to engine behavior when M4-specific keys are absent.
        m4_path = output_dir / "audit_results.m4.json"
        if m4_path.exists():
            print(f"M4 enriched results detected at {m4_path} — using for PDF render")
            results_for_pdf = json.loads(m4_path.read_text(encoding="utf-8"))
        else:
            results_for_pdf = results
        generate_audit_pdf(
            audit_results=results_for_pdf,
            project_schema=project_schema,
            submission_metadata=metadata,
            output_path=pdf_out,
        )
        print(f"PDF report: {pdf_out}")

    return 0


def _print_verdict_summary(label: str, rules: list[dict], include_total: bool = True) -> None:
    by_verdict: dict[str, int] = {}
    for r in rules:
        by_verdict[r["verdict"]] = by_verdict.get(r["verdict"], 0) + 1
    if include_total:
        print(f"\n{label} rules summary:")
    else:
        print(f"\n{label}:")
    for verdict, count in sorted(by_verdict.items()):
        print(f"  {verdict}: {count}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI dispatch
# ─────────────────────────────────────────────────────────────────────────────

def _run_from_html(html_path: Path, output_pdf: Path | None) -> int:
    """M7.7 --from-html: skip everything; pipe `html_path` straight to WeasyPrint.

    Cheapest possible loop for HTML-editing iteration. Embeds the report
    generator's CSS so the dumped HTML is self-rendering. Output defaults
    to the same stem as the input.
    """
    from compliance_engine.report_generator import _CSS, FONT_DIR
    from weasyprint import HTML, CSS as WeasyCSS
    from weasyprint.text.fonts import FontConfiguration

    html_path = Path(html_path)
    if not html_path.exists():
        print(f"ERROR: HTML not found at {html_path}", file=sys.stderr)
        return 1
    if output_pdf is None:
        output_pdf = html_path.with_suffix(".pdf")
    else:
        output_pdf = Path(output_pdf)
        output_pdf.parent.mkdir(parents=True, exist_ok=True)

    html_str = html_path.read_text(encoding="utf-8")
    font_config = FontConfiguration()
    base = str(FONT_DIR) + "/"
    HTML(string=html_str, base_url=base).write_pdf(
        str(output_pdf),
        stylesheets=[WeasyCSS(string=_CSS, base_url=base, font_config=font_config)],
        font_config=font_config,
    )
    print(f"PDF rendered: {output_pdf}")
    return 0


def _run_render_only(project_key: str, submission_version: str,
                     output_subdir: str,
                     comments_file: Path | None = None,
                     base_dir: Path = ROOT) -> int:
    """M7.7 --render-only: skip the engine, render straight from existing
    audit_results.m4.json + project schema + submission metadata.

    Use when only the report_generator templates or m4 JSON content has
    changed and the analysis (engine compliance run, M1-M4 pipeline)
    doesn't need to re-execute.

    Phase 2b: with --comments-file PATH, merge discipline_comments rows
    into §3 subsections at render time. Comments live only in the platform
    DB and the snapshot file; audit_results.m4.json is never touched.

    `base_dir` is the root under which `projects/` and `<output_subdir>/`
    live. Defaults to ROOT for backward-compat with the dev repo + the
    macOS subprocess path. The Windows in-process render branch (see
    queue_worker._process_render_pdf) passes `cfg.data_dir` so user data
    resolves under %LOCALAPPDATA%\\Planning Platform\\ instead of inside
    the PyInstaller bundle.
    """
    from compliance_engine.report_generator import generate_audit_pdf

    submission_dir = base_dir / "projects" / project_key / "submissions" / f"v{submission_version}"
    metadata_path = submission_dir / "metadata.json"
    if not metadata_path.exists():
        print(f"ERROR: metadata not found at {metadata_path}", file=sys.stderr)
        return 1
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    schema_path = base_dir / "projects" / project_key / f"project-schema-{project_key}-v2.json"
    if not schema_path.exists():
        schema_path = base_dir / f"project-schema-{project_key}-v2.json"
    if not schema_path.exists():
        print(f"ERROR: schema not found for {project_key}", file=sys.stderr)
        return 1

    output_dir = base_dir / output_subdir / project_key / f"v{submission_version}"
    m4_path = output_dir / "audit_results.m4.json"
    # Prefer the post-M4 sanitized JSON when present — it carries the same
    # rows/verdicts as m4.json but with auditor-voice scrubbed out of §3
    # discipline cells (see vision_scanner/m4/sanitizer_hebrew.py).
    sanitized_path = output_dir / "audit_results.m4.sanitized.json"
    if sanitized_path.exists():
        source_path = sanitized_path
    elif m4_path.exists():
        source_path = m4_path
    else:
        print(f"ERROR: --render-only needs an existing {m4_path} "
              f"(or {sanitized_path})", file=sys.stderr)
        print(f"       Run a full audit first, then iterate with --render-only.", file=sys.stderr)
        return 1

    project_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    results_for_pdf = json.loads(source_path.read_text(encoding="utf-8"))
    pdf_out = output_dir / f"audit_report_{submission_version}.pdf"

    discipline_comments = None
    if comments_file is not None:
        if not comments_file.exists():
            print(f"ERROR: --comments-file not found: {comments_file}", file=sys.stderr)
            return 1
        discipline_comments = json.loads(comments_file.read_text(encoding="utf-8"))
        print(f"--render-only: merging {len(discipline_comments)} comment(s) from {comments_file}")

    print(f"--render-only: using {source_path}")
    generate_audit_pdf(
        audit_results=results_for_pdf,
        project_schema=project_schema,
        submission_metadata=metadata,
        output_path=pdf_out,
        discipline_comments=discipline_comments,
    )
    print(f"PDF report: {pdf_out}")
    return 0


def _run_export_excel(project_key: str, submission_version: str,
                      output_subdir: str,
                      base_dir: Path = ROOT) -> int:
    """Export findings to an architect-response Excel workbook.

    Uses the same source-preference rule as --render-only: prefer the
    sanitized JSON (which the approved PDF was rendered from) and fall back
    to the raw M4 JSON. Output filename includes the version suffix so
    multiple submission versions can coexist in the same directory.

    `base_dir` mirrors _run_render_only — pass cfg.data_dir for the
    Windows-packaged sidecar so reads/writes land in
    %LOCALAPPDATA%\\Planning Platform\\ instead of _MEIPASS.
    """
    from compliance_engine.excel_export import export_findings_to_excel

    output_dir = base_dir / output_subdir / project_key / f"v{submission_version}"
    sanitized_path = output_dir / "audit_results.m4.sanitized.json"
    m4_path = output_dir / "audit_results.m4.json"
    if sanitized_path.exists():
        source_path = sanitized_path
    elif m4_path.exists():
        source_path = m4_path
    else:
        print(f"ERROR: --export-excel needs an existing {sanitized_path} "
              f"(or {m4_path})", file=sys.stderr)
        print(f"       Run a full audit first, then iterate with --export-excel.",
              file=sys.stderr)
        return 1

    audit_results = json.loads(source_path.read_text(encoding="utf-8"))
    xlsx_path = output_dir / f"הערות_סקירה_v{submission_version}.xlsx"

    print(f"--export-excel: using {source_path}")
    export_findings_to_excel(
        audit_results=audit_results,
        output_path=xlsx_path,
        report_version=submission_version,
    )
    print(f"Excel export: {xlsx_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a full compliance audit on a submission.",
        epilog="Either --job-dir DIR or positional PROJECT_KEY + SUBMISSION_VERSION required. "
               "Use --from-html for a WeasyPrint-only pass; --render-only to skip the engine.",
    )
    parser.add_argument("project_key", nargs="?",
                        help="(legacy) e.g., 407-1048248")
    parser.add_argument("submission_version", nargs="?",
                        help="(legacy) e.g., 24.3 (no 'v' prefix)")
    parser.add_argument("--job-dir", type=Path, default=None,
                        help="ADR-001 contract: read job_input.json here + "
                             "write job_output.json (preferred form).")
    parser.add_argument("--output-dir", default="audit_outputs",
                        help="(legacy) override the audit_outputs root.")
    parser.add_argument("--no-pdf", action="store_true",
                        help="(legacy) skip PDF report generation.")
    parser.add_argument("--from-html", type=Path, default=None,
                        help="M7.7: render PDF directly from this HTML file. "
                             "Skips ALL analysis — no engine, no pipeline. "
                             "Pairs with the HTML dump that report_generator "
                             "writes alongside every PDF.")
    parser.add_argument("--from-html-output", type=Path, default=None,
                        help="With --from-html: output PDF path. "
                             "Default: same stem as input HTML.")
    parser.add_argument("--render-only", action="store_true",
                        help="M7.7: skip the engine + analysis; render PDF "
                             "from the existing audit_results.m4.json. "
                             "Requires a prior full run for this submission.")
    parser.add_argument("--export-excel", action="store_true",
                        help="Skip PDF rendering; instead export the "
                             "audit_results.m4.sanitized.json (preferred) "
                             "or audit_results.m4.json (fallback) as a "
                             "single-sheet RTL Excel workbook for the "
                             "architect-response workflow. Requires a prior "
                             "full run for this submission.")
    parser.add_argument("--comments-file", type=Path, default=None,
                        help="Phase 2b: with --render-only, merge "
                             "discipline_comments JSON rows into §3 at render "
                             "time. Each entry: {discipline_key, status, "
                             "topic_he, action_he}. Does NOT modify "
                             "audit_results.m4.json.")
    args = parser.parse_args(argv)

    # M7.7: --from-html is the lightest path — pure WeasyPrint pass, no
    # project schema, no submission metadata.
    if args.from_html is not None:
        return _run_from_html(args.from_html, args.from_html_output)

    if args.job_dir is not None:
        return _run_with_job_dir(args.job_dir)

    if not args.project_key or not args.submission_version:
        parser.error(
            "either --job-dir DIR or positional PROJECT_KEY SUBMISSION_VERSION required"
        )

    # M7.7: --render-only skips the engine + pipeline; re-renders only.
    if args.render_only:
        return _run_render_only(
            project_key=args.project_key,
            submission_version=args.submission_version,
            output_subdir=args.output_dir,
            comments_file=args.comments_file,
        )

    # Architect-response workflow: skip PDF, emit XLSX from the same
    # sanitized JSON the render path reads.
    if args.export_excel:
        return _run_export_excel(
            project_key=args.project_key,
            submission_version=args.submission_version,
            output_subdir=args.output_dir,
        )

    return _run_legacy_positional(
        project_key=args.project_key,
        submission_version=args.submission_version,
        output_subdir=args.output_dir,
        generate_pdf=not args.no_pdf,
    )


if __name__ == "__main__":
    raise SystemExit(main())
