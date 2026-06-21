"""CLI for M4 engine adapter (post-engine override → audit_results.m4.json).

Usage:
    python3 -m vision_scanner.m4.run \\
        --project-id 407-1048248 \\
        --submission-id v24.3 \\
        --engine-results audit_outputs/407-1048248/v24.3/audit_results.json \\
        --vision-findings data/projects/407-1048248/submissions/v24.3/vision_findings.json \\
        --critic-findings data/projects/407-1048248/submissions/v24.3/critic_findings.json \\
        --output data/projects/407-1048248/submissions/v24.3/audit_results.m4.slice1.tmp.json \\
        --slice-rules CONTENT_UNIT_COUNT,CONTENT_BUILDING_HEIGHT,CONTENT_SETBACKS \\
        --print-samples
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .clause_mapping import MAPPINGS, all_enabled_clauses
from .processor import M4_VERSION, build_m4_document
from .validate import run_all, summarize


def _atomic_write_json(path: Path, document: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _append_run_log(log_path: Path, record: Dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _parse_slice_spec(spec: Optional[str]) -> Optional[set]:
    """Slice spec is comma-separated engine rule_codes. Filters which mappings
    are 'enabled' for this run (anything else passes through engine output).

    Sidecar-only mappings (engine_rule_code is None — surface in m4_summary
    without overriding any engine row) are ALWAYS included regardless of the
    engine-rule filter. They're informational; they don't contend with engine
    output. This is important for slice 1: the non_compliant findings (6.5.1,
    6.6.4) are sidecar-only and would otherwise vanish from the M4 output.
    """
    if spec is None:
        return None
    s = spec.strip().lower()
    if s in ("all", "all-mappings", ""):
        return None
    rule_codes = {r.strip() for r in spec.split(",") if r.strip()}
    enabled_clauses: set = set()
    for entry in MAPPINGS:
        engine_rc = entry.get("engine_rule_code")
        if engine_rc is None:
            # Sidecar-only: always include
            enabled_clauses.add(entry["m2_clause_id"])
        elif engine_rc in rule_codes:
            enabled_clauses.add(entry["m2_clause_id"])
    return enabled_clauses


def _print_samples(document: Dict[str, Any], n: int = 8) -> None:
    print("\n" + "=" * 72)
    print(f"M4 SUMMARY")
    print("=" * 72)
    print(json.dumps(document.get("m4_summary", {}), ensure_ascii=False, indent=2))
    print()
    overrides = [f for f in document.get("content", []) if f.get("m4_override_applied")]
    print("=" * 72)
    print(f"OVERRIDDEN CONTENT FINDINGS ({len(overrides)} of {len(document.get('content', []))})")
    print("=" * 72)
    for f in overrides[:n]:
        print(f"\n--- {f.get('rule_code')} / {f.get('ta_shetach_id') or 'plan-wide'} ---")
        slim = {
            "verdict": f.get("verdict"),
            "confidence": f.get("confidence"),
            "m4_override_source": f.get("m4_override_source"),
            "m4_m2_clause_ids": f.get("m4_m2_clause_ids"),
            "m4_m3_critic_verdict": f.get("m4_m3_critic_verdict"),
            "m4_evidence_pages": f.get("m4_evidence_pages"),
            "notes_he_tail": (f.get("notes_he") or "").split("\n\n[")[-1][:280],
        }
        print(json.dumps(slim, ensure_ascii=False, indent=2))


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="M4 engine adapter — produce audit_results.m4.json with M2/M3 overrides."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--engine-results", required=True, type=Path)
    parser.add_argument("--vision-findings", required=True, type=Path)
    parser.add_argument("--critic-findings", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--slice-rules",
        default=None,
        help='Comma-separated engine rule_codes to enable (e.g. "CONTENT_UNIT_COUNT,CONTENT_BUILDING_HEIGHT"), or "all"',
    )
    parser.add_argument("--print-samples", action="store_true")
    parser.add_argument(
        "--no-translate",
        action="store_true",
        help="Skip the Flash-driven Hebrew translation pass (M5). Default: translate.",
    )
    parser.add_argument(
        "--include-cad-findings",
        action="store_true",
        help="Phase 7.1+: build the takanon CAD dataset and append CAD-derived "
             "findings (e.g. plot completeness) to m4_summary.sidecar_only_findings.",
    )
    parser.add_argument(
        "--submitted-plots",
        default="1,2,3,4,5",
        help="Comma-separated plot numbers the architect did submit. "
             "Used by the CAD plot-completeness check. Default: 1,2,3,4,5 (v24.3).",
    )
    parser.add_argument(
        "--include-chatakhim-findings",
        action="store_true",
        help="Phase 7.2+: parse M1 page_manifests on the cross-section + elevation "
             "pages to produce absolute-height ceiling + drawing-consistency findings.",
    )
    parser.add_argument(
        "--include-amenity-inventory",
        action="store_true",
        help="Phase 7.4: build the resident-amenities inventory from M1 "
             "functions_diagram pages; stash in m4_summary.amenity_inventory "
             "for rendering as §3.11.",
    )
    parser.add_argument(
        "--log-path", type=Path, default=None,
        help="Run-log JSONL (default: <output dir>/audit_results.m4.run_log.jsonl)",
    )
    args = parser.parse_args(argv)

    for p in (args.engine_results, args.vision_findings, args.critic_findings):
        if not p.exists():
            print(f"ERROR: missing input: {p}", file=sys.stderr)
            return 2

    enabled_m2_clauses = _parse_slice_spec(args.slice_rules)
    if enabled_m2_clauses is None:
        enabled_m2_clauses = all_enabled_clauses()
    print(f"M4 adapter — plan={args.project_id}, submission={args.submission_id}")
    print(f"  enabled M2 clauses (slice): {sorted(enabled_m2_clauses)}")

    engine_doc = json.loads(args.engine_results.read_text(encoding="utf-8"))
    vision_doc = json.loads(args.vision_findings.read_text(encoding="utf-8"))
    critic_doc = json.loads(args.critic_findings.read_text(encoding="utf-8"))

    cad_findings: list = []
    if args.include_cad_findings:
        from ..cad_ingest.plot_completeness import produce_plot_completeness_finding
        from ..cad_ingest.takanon_dataset import build_takanon_plot_dataset
        print("  Phase 7.1 CAD ingest — building takanon dataset...")
        dataset = build_takanon_plot_dataset(args.project_id)
        submitted = [int(s) for s in args.submitted_plots.split(",") if s.strip()]
        print(f"  submitted_plots (architect): {submitted}")
        finding = produce_plot_completeness_finding(dataset, submitted)
        cad_findings.append(finding)
        n_missing = len(finding.get("missing_plots", []))
        print(f"  CAD finding: plot_completeness → "
              f"{finding.get('compliance_indicator')} ({n_missing} missing plots)")

    chatakhim_findings: list = []
    if args.include_chatakhim_findings:
        from ..m2.parsers.chatakhim_height_parser import (
            produce_chatakhim_findings,
            PROJECT_ROOT as _CHAT_ROOT,
        )
        print("  Phase 7.2 chatakhim height parse — reading M1 manifests...")
        manifests_path = (
            _CHAT_ROOT / "data" / "projects" / args.project_id
            / "submissions" / args.submission_id / "page_manifests.json"
        )
        manifests = json.loads(manifests_path.read_text(encoding="utf-8"))
        chatakhim_findings, chat_summary = produce_chatakhim_findings(manifests)
        print(f"  buildings audited: {len(chat_summary['buildings_audited'])} "
              f"→ {chat_summary['buildings_audited']}")
        print(f"  ceiling violations (buildings): {chat_summary['ceiling_violations_buildings']}")
        print(f"  ceiling violations (plot-level): {chat_summary['ceiling_violations_plot_level']}")
        print(f"  consistency warnings: {chat_summary['consistency_warnings_buildings']}")
        print(f"  total chatakhim findings: {len(chatakhim_findings)}")

    amenity_inventory = None
    if args.include_amenity_inventory:
        from ..parsers.amenity_inventory_parser import (
            build_amenity_matrix,
            PROJECT_ROOT as _AMEN_ROOT,
        )
        print("  Phase 7.4 amenity inventory — reading M1 manifests...")
        manifests_path = (
            _AMEN_ROOT / "data" / "projects" / args.project_id
            / "submissions" / args.submission_id / "page_manifests.json"
        )
        manifests = json.loads(manifests_path.read_text(encoding="utf-8"))
        amenity_inventory = build_amenity_matrix(manifests)
        amenities_count = len(amenity_inventory.get("amenities") or [])
        gaps = amenity_inventory.get("gaps_summary") or {}
        print(f"  amenities tracked: {amenities_count}")
        print(f"  always_detected: {gaps.get('always_detected')}")
        print(f"  partial:         {gaps.get('partial')}")
        print(f"  never_detected:  {gaps.get('never_detected')}")

    document = build_m4_document(
        engine_doc, vision_doc, critic_doc,
        engine_path=args.engine_results,
        vision_path=args.vision_findings,
        critic_path=args.critic_findings,
        enabled_clause_ids=enabled_m2_clauses,
        translate_hebrew=not args.no_translate,
        cad_findings=(cad_findings + chatakhim_findings) or None,
        amenity_inventory=amenity_inventory,
    )

    known_m2_clauses = {f.get("clause_id") for f in vision_doc.get("findings", [])}

    print("\nRunning 8 automated checks...")
    checks = run_all(
        document,
        known_m2_clauses,
        engine_doc=engine_doc,
        critic_doc=critic_doc,
        engine_path=args.engine_results,
        vision_path=args.vision_findings,
        critic_path=args.critic_findings,
        enabled_m2_clauses=enabled_m2_clauses,
    )
    all_ok, summary_text = summarize(checks)
    print(summary_text)

    _atomic_write_json(args.output, document)
    print(f"\nWrote: {args.output}")

    log_path = args.log_path or (args.output.parent / "audit_results.m4.run_log.jsonl")
    _append_run_log(
        log_path,
        {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "m4_version": M4_VERSION,
            "phase": "adapter",
            "plan_id": args.project_id,
            "submission_id": args.submission_id,
            "input_refs": document.get("m4_input_refs"),
            "slice_enabled_clauses": sorted(enabled_m2_clauses),
            "summary": document.get("m4_summary"),
            "validation_result": "pass" if all_ok else "fail",
            "output_path": str(args.output),
        },
    )
    print(f"Logged run to: {log_path}")

    if args.print_samples:
        _print_samples(document)

    if not all_ok:
        print("\nVALIDATION FAILED — see [FAIL] lines above.", file=sys.stderr)
        return 1
    print(f"\nAll {len(checks)} automated checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
