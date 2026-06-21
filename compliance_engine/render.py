"""Library-level entry points for the report-render and Excel-export
paths used by the sidecar.

History: until this module existed, both functions lived in
`scripts/run_audit.py` and the sidecar imported them with
`from scripts.run_audit import _run_render_only`. That broke under
PyInstaller — `scripts/` was never a package, was never declared in
backend.spec, and the import only "worked" in dev because of a
`sys.path.insert(...)` shim in queue_worker. The frozen Windows build
failed at first render with `ModuleNotFoundError: No module named
'scripts'`.

`compliance_engine` is already a proper package that PyInstaller
follows automatically, so the fix is simply to live here. The CLI
flags `--render-only` and `--export-excel` in scripts/run_audit.py
now re-import these functions and dispatch to them — single source of
truth, no parallel paths to drift apart.

`base_dir` is the root under which `projects/` and `<output_subdir>/`
resolve. In dev it's the repo root; under the Windows-packaged sidecar
it's `cfg.data_dir` (= %LOCALAPPDATA%\\Planning Platform\\) so reads
and writes never touch _MEIPASS.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Module-level logger so errors flow through the rotating file handler
# attached in run_sidecar.py — not just to stderr (which the Tauri
# console window swallows when it closes). Errors here are the most
# common diagnostic surface for render failures.
_log = logging.getLogger(__name__)


def run_render_only(
    project_key: str,
    submission_version: str,
    output_subdir: str,
    comments_file: Path | None = None,
    base_dir: Path | None = None,
) -> int:
    """M7.7 --render-only: skip the engine, render straight from existing
    audit_results.m4.json + project schema + submission metadata.

    Use when only the report_generator templates or m4 JSON content has
    changed and the analysis (engine compliance run, M1-M4 pipeline)
    doesn't need to re-execute.

    Phase 2b: with `comments_file`, merge discipline_comments rows into
    §3 subsections at render time. Comments live only in the platform
    DB and the snapshot file; audit_results.m4.json is never touched.
    """
    if base_dir is None:
        # Default to repo root (compliance_engine/ is two levels under it).
        base_dir = Path(__file__).resolve().parent.parent

    # Local import — defers the heavy report_generator (WeasyPrint, fonts)
    # until a render call actually arrives, keeps sidecar cold-start light.
    from compliance_engine.report_generator import generate_audit_pdf

    submission_dir = base_dir / "projects" / project_key / "submissions" / f"v{submission_version}"
    metadata_path = submission_dir / "metadata.json"
    # P2-C: tolerate a missing metadata.json instead of failing fast.
    # The render reads only submission_version + submission_date from
    # this dict, both with empty-string fallbacks (report_generator.py
    # line 1675-6). Failing the render over a missing file class of
    # bug bit Ellen on Friday — losing the file should degrade the
    # cover (blank version/date) but never crash. The warning still
    # flows to errors.log so a developer can spot the missing file.
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    else:
        msg = f"WARN: metadata not found at {metadata_path}; rendering with empty defaults"
        print(msg, file=sys.stderr)
        _log.warning(msg)
        metadata = {}

    schema_path = base_dir / "projects" / project_key / f"project-schema-{project_key}-v2.json"
    if not schema_path.exists():
        schema_path = base_dir / f"project-schema-{project_key}-v2.json"
    if not schema_path.exists():
        msg = f"ERROR: schema not found for {project_key}"
        print(msg, file=sys.stderr)
        _log.error(msg)
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
        msg = (f"ERROR: --render-only needs an existing {m4_path} "
               f"(or {sanitized_path})")
        print(msg, file=sys.stderr)
        print(f"       Run a full audit first, then iterate with --render-only.", file=sys.stderr)
        _log.error(msg)
        return 1

    project_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    results_for_pdf = json.loads(source_path.read_text(encoding="utf-8"))
    pdf_out = output_dir / f"audit_report_{submission_version}.pdf"

    discipline_comments = None
    if comments_file is not None:
        if not comments_file.exists():
            msg = f"ERROR: --comments-file not found: {comments_file}"
            print(msg, file=sys.stderr)
            _log.error(msg)
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


def run_export_excel(
    project_key: str,
    submission_version: str,
    output_subdir: str,
    base_dir: Path | None = None,
    discipline_comments: list[dict] | None = None,
) -> int:
    """Export findings to an architect-response Excel workbook.

    Uses the same source-preference rule as run_render_only: prefer the
    sanitized JSON (which the approved PDF was rendered from) and fall back
    to the raw M4 JSON. Output filename includes the version suffix so
    multiple submission versions can coexist in the same directory.
    """
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent

    from compliance_engine.excel_export import export_findings_to_excel

    output_dir = base_dir / output_subdir / project_key / f"v{submission_version}"
    sanitized_path = output_dir / "audit_results.m4.sanitized.json"
    m4_path = output_dir / "audit_results.m4.json"
    if sanitized_path.exists():
        source_path = sanitized_path
    elif m4_path.exists():
        source_path = m4_path
    else:
        msg = (f"ERROR: --export-excel needs an existing {sanitized_path} "
               f"(or {m4_path})")
        print(msg, file=sys.stderr)
        print(f"       Run a full audit first, then iterate with --export-excel.",
              file=sys.stderr)
        _log.error(msg)
        return 1

    audit_results = json.loads(source_path.read_text(encoding="utf-8"))
    xlsx_path = output_dir / f"הערות_סקירה_v{submission_version}.xlsx"

    print(f"--export-excel: using {source_path}")
    export_findings_to_excel(
        audit_results=audit_results,
        output_path=xlsx_path,
        report_version=submission_version,
        discipline_comments=discipline_comments,
    )
    print(f"Excel export: {xlsx_path}")
    return 0
