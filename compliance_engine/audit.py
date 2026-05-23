"""
Top-level audit entry point: format + content + disciplines, with feedback merge.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .content_compliance_checker import run_content_compliance
from .discipline_policy_checker import run_discipline_checks
from .feedback_store import ensure_db_initialized, get_feedback_for_audit, merge_with_feedback
from .format_rules_checker import check_submission_format
from .submission_data_extractor import extract as extract_submission_data
from .submission_extracts import load_extracts


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_full_audit(
    pdf_path: Path,
    project_schema: dict,
    *,
    content_rules_path: Path | None = None,
    discipline_rules_path: Path | None = None,
    extraction_cache_path: Path | None = None,
    audit_outputs_root: Path | None = None,
    project_key: str | None = None,
    submission_version: str | None = None,
    audit_run_id: str | None = None,
    feedback_db_path: Path | None = None,
    allow_llm: bool | None = None,
) -> dict:
    pdf_path = Path(pdf_path)
    if content_rules_path is None:
        content_rules_path = PROJECT_ROOT / "content_rules.json"
    if discipline_rules_path is None:
        discipline_rules_path = PROJECT_ROOT / "discipline_rules.json"
    if extraction_cache_path is None:
        if audit_outputs_root and project_key and submission_version:
            extraction_cache_path = (
                Path(audit_outputs_root) / project_key / f"v{submission_version}" / "extraction_cache.json"
            )
        else:
            extraction_cache_path = pdf_path.parent / "extraction_cache.json"
    if audit_run_id is None and project_key and submission_version:
        audit_run_id = f"{project_key}/v{submission_version}"

    # --- format ---
    format_overrides = (
        project_schema.get("project", {}).get("meta", {}).get("format_rule_overrides")
        if "project" in project_schema
        else project_schema.get("meta", {}).get("format_rule_overrides")
    ) or []
    format_results = check_submission_format(pdf_path, project_overrides=format_overrides)

    # --- content ---
    content_rules = json.loads(Path(content_rules_path).read_text(encoding="utf-8"))["rules"]
    extracted = extract_submission_data(
        pdf_path, project_schema,
        cache_path=extraction_cache_path,
        use_cache=True,
        allow_llm=allow_llm,
    )
    # Overlay hand-extracted values (extracts.json next to the PDF) on top of the
    # automated extractor's results. v8a-2's vision-LLM extractor will eventually
    # replace this manual step.
    extracts_overlay = load_extracts(pdf_path.parent)
    content_results = run_content_compliance(
        extracted, project_schema, content_rules, extracts=extracts_overlay,
    )

    # --- disciplines ---
    discipline_results = run_discipline_checks(
        pdf_path,
        rules_path=discipline_rules_path,
        submission_dir=pdf_path.parent,
    )

    # --- feedback merge (if DB available + audit_run_id known) ---
    feedback_entries: list[dict] = []
    if audit_run_id:
        ensure_db_initialized(feedback_db_path)
        feedback_entries = get_feedback_for_audit(audit_run_id, db_path=feedback_db_path)
        if feedback_entries:
            content_results = merge_with_feedback(content_results, audit_run_id, db_path=feedback_db_path)
            discipline_results = merge_with_feedback(discipline_results, audit_run_id, db_path=feedback_db_path)

    return {
        "format": format_results,
        "content": content_results,
        "disciplines": discipline_results,
        "extraction_cache": asdict(extracted),
        "extracts_overlay": extracts_overlay,
        "feedback_entries": feedback_entries,
        "audit_run_id": audit_run_id,
    }
