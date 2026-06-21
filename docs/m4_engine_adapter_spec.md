# M4: Engine Adapter Specification — Submission v24.3

**Status:** v1 draft, 2026-05-24. Awaiting slice-1 verification before scaling.
**Owner:** `vision_scanner.m4` package.
**Dependencies:** M0 locked at `08f2a1a` (177 clauses), M1 locked at `48d4661` (63 manifests), M2 locked at `0ede9da` (110 vision findings), M3 locked at `207daef` (19 critic verdicts).

## Purpose

Bridge M2's per-clause vision evidence + M3's critic verdicts into the existing compliance engine's per-rule output, without modifying the engine itself. M4 produces an enriched audit-results file that the PDF generator can consume to show vision-grounded verdicts, page citations, and critic-disagreement escalations alongside the engine's deterministic rule output.

Specifically addresses:
- **Task #32** (engine emits "תקין" with reasoning that admits incomplete verification) — M4 surfaces M2's evidence so the verdict + reasoning are co-evaluated.
- **Task #33** (engine has zero "fail" verdicts in section 2) — M4 maps M2's `non_compliant` to a `fail` verdict for the relevant rule × plot rows.

## Architecture — B+ (post-engine override)

Decided 2026-05-24 in the M4 discovery report. Out of architectures A (overlay-replacement), B (sidecar enrichment), C (hybrid overlay fill), the chosen design is **B+ — post-engine override**:

1. **Engine runs UNCHANGED** with the existing curated `extracts.json`. The `audit_results.json` (engine output) sha256 stays byte-identical to baseline (`8c5627f9…`).
2. **M4 reads** engine's `audit_results.json` + M2's `vision_findings.json` + M3's `critic_findings.json`.
3. **For each engine finding** (rule_code × ta_shetach_id): look up matching M2 finding(s) via the clause-mapping table; if any matching critic verdict is `disagree`, escalate to `requires_review`; else if matching high-confidence M2 finding(s) exist, override the verdict per the translator table.
4. **M4 writes** `audit_results.m4.json` — a new file alongside (not replacing) the engine output. PDF generator patch in phase 2 reads `.m4.json` if present, falls back to `audit_results.json` otherwise.
5. **Engine baseline preserved.** All regression checks against `tests/regression/v8j_baseline_v24.3.json` continue to pass.

### Why B+ over A / B / C

- **A (overwrite extracts.json):** would break Lior-curated overrides (e.g. plot_1 `height_m: 45.45` with detailed `_note_height` explaining v6 reference discrepancy). Lost human judgment.
- **B (pure sidecar, no engine output mutation):** PDF generator would need bigger changes to merge two parallel data structures.
- **C (hybrid overlay fill):** still touches the engine output's value space — risks subtle behavioral changes per rule.
- **B+ (chosen):** modifications happen AFTER the engine produces its verdicts. The engine output is untouched (sha-identical) — M4 produces a separate enriched-verdict file with explicit `m4_override_applied=true` markers. PDF generator can pick whichever file is present.

## Output

**Path:** `data/projects/407-1048248/submissions/v24.3/audit_results.m4.json` (NEW file, alongside the engine's `audit_outputs/.../audit_results.json` which stays unchanged).

**Gitignore exception:** add `!data/projects/*/submissions/*/audit_results.m4.json` and the run-log to `.gitignore` at lock-time.

## Top-level schema

```json
{
  "audit_run_id": "407-1048248/v24.3",
  "m4_version": "m4-v1",
  "m4_input_refs": {
    "engine_audit_results_sha256": "<sha256>",
    "vision_findings_sha256": "<sha256>",
    "critic_findings_sha256": "<sha256>"
  },

  "content": [<M4Finding>, ...],         // engine.content with M4 overrides applied
  "disciplines": [<M4Finding>, ...],     // passthrough in m4-v1 (untouched)
  "format": [<M4Finding>, ...],          // passthrough in m4-v1 (untouched)

  // Passthrough from engine output (unchanged):
  "extraction_cache": {...},
  "extracts_overlay": {...},
  "feedback_entries": [...],

  "m4_summary": {<M4Summary>}
}
```

## Pydantic schema

```python
class M4Finding(BaseModel):
    # All original fields from engine finding (preserved verbatim)
    rule_code: str
    rule_name_he: str
    ta_shetach_id: Optional[str]
    verdict: Literal["pass", "fail", "not_submitted", "not_applicable",
                     "requires_review", "pass_with_note", "unevaluable"]
    # NOTE: "fail" appears in content-scope findings ONLY when M4 overrides
    # from M2 non_compliant — engine itself never emits "fail" for content.
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    # NOTE: "MEDIUM" / "LOW" appear ONLY when M4 overrides from M2.
    failure_mode: str
    evidence: Dict[str, Any]
    notes_he: str
    remediation_he: str

    # M4 additions:
    m4_override_applied: bool
    m4_override_source: Optional[Literal["m2_finding", "m3_critic_disagreement"]]
    m4_m2_clause_ids: List[str] = []      # which M2 findings informed this verdict
    m4_m3_critic_verdict: Optional[Literal["agree", "disagree", "cannot_determine"]] = None
    m4_evidence_pages: List[int] = []     # aggregated from M2 source_pages
    m4_evidence_bboxes: List[Dict[str, Any]] = []  # M2 bboxes, for PDF rendering


class M4Summary(BaseModel):
    total_engine_findings: int
    overridden_count: int
    by_override_source: Dict[str, int]                  # {"m2_finding": N, "m3_critic_disagreement": M}
    verdict_distribution_before: Dict[str, int]         # engine output
    verdict_distribution_after: Dict[str, int]          # after M4
    new_fail_verdicts: List[str]                        # rule_code:plot pairs newly fail
    critic_disagreements_applied: List[str]             # m2 clause_ids triggering escalation


class M4AuditResults(BaseModel):
    audit_run_id: str
    m4_version: str = "m4-v1"
    m4_input_refs: Dict[str, str]
    content: List[M4Finding]
    disciplines: List[M4Finding]                        # passthrough
    format: List[M4Finding]                             # passthrough
    extraction_cache: Dict[str, Any]                    # passthrough
    extracts_overlay: Dict[str, Any]                    # passthrough
    feedback_entries: List[Any]                         # passthrough
    m4_summary: M4Summary
```

## Override logic (pseudocode)

```python
def process_finding(finding, m2_index, critic_index, mapping):
    # mapping: clause_id → (rule_code, ta_shetach_id_pattern)
    key = (finding["rule_code"], finding.get("ta_shetach_id"))
    m2_matches = lookup_m2_findings(mapping, key, m2_index)

    if not m2_matches:
        # No M4 coverage — pass through unchanged with override_applied=False
        return passthrough(finding)

    # Find M3 critic verdicts attached to any of these M2 findings
    critic_matches = [critic_index.get(m2["clause_id"]) for m2 in m2_matches
                      if m2["clause_id"] in critic_index]
    critic_matches = [c for c in critic_matches if c is not None]

    # Critic disagreement takes precedence — escalate to requires_review
    disagree_critics = [c for c in critic_matches if c["critic_verdict"] == "disagree"]
    if disagree_critics:
        return apply_critic_escalation(finding, m2_matches, disagree_critics)

    # No critic disagreement — apply M2 override
    high_conf_m2 = [m for m in m2_matches if m["confidence"] == "high"]
    if not high_conf_m2:
        # M2 has only medium/low confidence — annotate but don't override
        return apply_m2_annotation_only(finding, m2_matches)

    best_m2 = pick_best(high_conf_m2)
    return apply_m2_override(finding, best_m2, m2_matches, critic_matches)


def apply_m2_override(finding, best_m2, all_m2, critic_matches):
    new_verdict = m2_indicator_to_engine_verdict(best_m2["compliance_indicator"])
    new_confidence = m2_confidence_to_engine(best_m2["confidence"])
    new_notes = (finding["notes_he"] or "") + "\n\n[Vision evidence]: " + best_m2["compliance_reasoning"]

    return {
        **finding,
        "verdict": new_verdict,
        "confidence": new_confidence,
        "notes_he": new_notes,
        "m4_override_applied": True,
        "m4_override_source": "m2_finding",
        "m4_m2_clause_ids": [m["clause_id"] for m in all_m2],
        "m4_m3_critic_verdict": (critic_matches[0]["critic_verdict"] if critic_matches else None),
        "m4_evidence_pages": sorted({p for m in all_m2 for p in (m.get("source_pages") or [])}),
        "m4_evidence_bboxes": [b for m in all_m2 for b in (m.get("evidence_bboxes") or [])],
    }
```

## Translator tables

**M2 `compliance_indicator` → engine `verdict`:**

| M2 indicator | engine verdict |
|---|---|
| `compliant` | `pass` |
| `non_compliant` | `fail` |  ← **new for content scope; visibly addresses Task #33** |
| `requires_review` | `requires_review` |
| `missing` | `not_submitted` |
| `deferred_to_dwg` | `requires_review` |

**M2 `confidence` → engine `confidence`:**

| M2 confidence | engine confidence |
|---|---|
| `high` | `HIGH` |
| `medium` | `MEDIUM` ← **new value** |
| `low` | `LOW` ← **new value** |

## Clause-mapping (initial slice-1 subset)

Hand-curated `vision_scanner/m4/clause_mapping.py` maps `(clause_id, plot)` pairs to `(engine_rule_code, ta_shetach_id)` pairs. Slice 1 covers:

| M2 clause_id | M2 value type | Engine rule_code | Plot scope | Priority |
|---|---|---|---|---|
| `5.table` (plot N, units numeric) | int | `CONTENT_UNIT_COUNT` | per-plot | HIGH |
| `5.table` (plot N, height/floors range) | range str | `CONTENT_BUILDING_HEIGHT` | per-plot | HIGH |
| `4.1.2.1` | floor-count numeric | `CONTENT_BUILDING_HEIGHT` | per-plot | HIGH |
| `4.1.2.4` | dimension numeric (m) | (no direct engine rule — note-only) | per-plot | MED |
| `6.5.1` non_compliant | "missing appendix" | (no rule — surface via m4_critical_findings sidecar) | plan-wide | HIGH (Task #33) |
| `6.6.4` non_compliant | "no underground passage" | (no rule — surface via sidecar) | plot_2 | HIGH (Task #33) |
| `6.7.4` (with critic disagreement) | absolute height | `CONTENT_BUILDING_HEIGHT` | plan-wide | HIGH (M3 escalation test) |

**Note:** 6.5.1 and 6.6.4 are critical non_compliant findings that don't have a direct engine rule to override. M4 v1 surfaces them via the `m4_summary.new_fail_verdicts` list (which the PDF generator will render as a callout in phase 2). They don't appear as engine rule rows because the engine has no `CONTENT_TREE_PRESERVATION_APPENDIX` or `CONTENT_EASEMENT_REGISTRY` rule.

## Validation (8 automated checks)

1. **schema_valid** — output validates against `M4AuditResults` Pydantic model
2. **m4_clause_ids_resolve** — every `m4_m2_clause_ids` entry exists in `vision_findings.json`
3. **m3_disagreements_applied** — every `critic_findings.json` `disagree` verdict whose M2 clause maps to an engine rule produces a corresponding `m4_override_source="m3_critic_disagreement"` in M4 output
4. **verdict_enum_valid** — all verdicts in the extended enum
5. **engine_passthrough_preserved** — for non-overridden findings, every original field is byte-identical to engine input
6. **input_refs_sha256_match** — `m4_input_refs` sha256s match the on-disk input files
7. **verdict_distribution_consistent** — `m4_summary.verdict_distribution_after` matches actual count of finding verdicts
8. **no_orphan_overrides** — no finding has `m4_override_applied=true` with empty `m4_m2_clause_ids`

## Test slice methodology

**Slice 1** — 5-10 highest-impact rule mappings (this round). Must include both M2 `non_compliant` findings (Task #33) and at least one M3-disagreement case.

**Slice 2** — Expand to ~15-20 mappings after slice 1 sign-off.

**Full** — All available rule mappings (~25-30 expected). Then PDF generator patch (separate phase 2).

**STOP conditions:**
- Any automated validation check fails
- Self-verify finds >20% of overrides incorrect
- Override produces a verdict change that contradicts the M2 compliance_reasoning
- Critic disagreement escalation doesn't surface in the M4 output

## CLI

`vision_scanner/m4/run.py`:

```
--project-id PLAN_ID                 (required)
--submission-id SUB_ID               (required)
--engine-results PATH                (required; path to engine's audit_results.json)
--vision-findings PATH               (required; M2 output)
--critic-findings PATH               (required; M3 output)
--output PATH                        (required; .m4.json target)
--slice-rules SPEC                   (optional: comma-separated rule_codes or "all")
--print-samples                      (prints overridden findings to stdout)
```

## Files this milestone creates

| Path | Purpose |
|---|---|
| `docs/m4_engine_adapter_spec.md` | This spec |
| `vision_scanner/m4/__init__.py` | Subpackage |
| `vision_scanner/m4/schema.py` | Pydantic models |
| `vision_scanner/m4/clause_mapping.py` | Hand-curated clause↔rule mapping |
| `vision_scanner/m4/value_parser.py` | Parse M2 value strings to typed numerics |
| `vision_scanner/m4/translator.py` | Indicator/confidence translation tables |
| `vision_scanner/m4/processor.py` | Core override loop |
| `vision_scanner/m4/validate.py` | 8 automated checks |
| `vision_scanner/m4/run.py` | CLI entry point |
| `data/projects/407-1048248/submissions/v24.3/audit_results.m4.json` | Output (after full run + lock) |
| `data/projects/407-1048248/submissions/v24.3/audit_results.m4.run_log.jsonl` | Run history |
| `data/projects/407-1048248/submissions/v24.3/m4_test_slice_verification.md` | Per-slice audit |

## Acceptance criteria for M4 v1

1. Engine output sha256 unchanged (regression baseline preserved)
2. All 8 automated checks pass
3. Slice-by-slice approval (5-10 → 15-20 → full)
4. At least one finding visibly transitions `requires_review` → `fail` (Task #33 demonstrably addressed)
5. M3 critic disagreements that map to engine rules visibly escalate to `requires_review` with reasoning attached
6. Original engine fields preserved on every non-overridden finding (no silent mutations)
7. Committed to `phase-3-vision`

## NOT in M4 v1 scope (deferred to phase 2)

- PDF generator patch to read `.m4.json` — separate phase, separate audit
- Discipline-scope overrides — disciplines stay passthrough in v1
- Format-scope overrides — format stays passthrough in v1
- 5.table threshold comparison (M2 emits values; rights-table threshold comparison is done by the engine separately — M4 doesn't re-evaluate)
- Auto-discovery of new rule mappings from M2 findings (mapping table stays hand-curated for v1)
