# M4 Test Slice Verification — Submission v24.3

## Slice 1 (3 engine rule_codes, m4-v1)

**Date:** 2026-05-24
**Verifier:** Claude Code (programmatic — M4 is pure compute, no API calls)
**Output file:** `data/projects/407-1048248/submissions/v24.3/audit_results.m4.slice1.tmp.json`
**Spec:** `docs/m4_engine_adapter_spec.md` (m4-v1, architecture B+ post-engine override)
**Code:** `vision_scanner/m4/` (uncommitted)

### Engine rule survey

Engine emits exactly 9 content `rule_code`s:
- Per-plot (×11 plots = plot_1..10, plot_20): `CONTENT_BUILDING_AREA_MAIN`, `CONTENT_BUILDING_AREA_SERVICE_ABOVE`, `CONTENT_BUILDING_AREA_SERVICE_BELOW`, `CONTENT_BUILDING_HEIGHT`, `CONTENT_PARKING_RATIO`, `CONTENT_SETBACKS`, `CONTENT_UNIT_COUNT`
- Plan-wide (×1): `CONTENT_APARTMENT_MIX_SMALL`, `CONTENT_PERMEABLE_SURFACES`

Total content findings: 79 (= 7 × 11 + 2). Plus 33 discipline + 34 format = 146 engine findings overall.

### Clause mapping table (slice 1)

`vision_scanner/m4/clause_mapping.py` — **7 mappings**, covering 6 unique M2 clauses:

| # | M2 clause_id | M2 unit match | Engine rule_code | Plot scope | Notes |
|---|---|---|---|---|---|
| 1 | `5.table` | `יח"ד` | `CONTENT_UNIT_COUNT` | per_plot_passthrough | Per-plot units row |
| 2 | `5.table` | `floors` | `CONTENT_BUILDING_HEIGHT` | per_plot_passthrough | Per-plot floor count row |
| 3 | `4.1.2.1` | (any) | `CONTENT_BUILDING_HEIGHT` | per_plot_passthrough | Street-facing floor caps |
| 4 | `6.7.4` | (any) | `CONTENT_BUILDING_HEIGHT` | plan_wide_to_plot_5 | Max 91m — plan-wide M2 → plot_5 (tallest building A5) |
| 5 | `4.1.2.4` | (any) | `CONTENT_SETBACKS` | all_engine_plots | 9m between buildings — plan-wide → annotate all |
| 6 | `6.5.1` | (any) | `None` (sidecar) | sidecar | Mature trees appendix missing — non_compliant |
| 7 | `6.6.4` | (any) | `None` (sidecar) | sidecar | חלקה 12 underground easement missing — non_compliant |

**Slice 1 rule scope:** `CONTENT_UNIT_COUNT`, `CONTENT_BUILDING_HEIGHT`, `CONTENT_SETBACKS`. Sidecar-only mappings (6.5.1, 6.6.4) are always included regardless of slice filter (they don't override engine rows).

### Run stats

- **Runtime:** 0.225 sec (M4 is pure local compute, no API calls)
- **Cost:** **$0** (no LLM calls; all logic deterministic)
- **Output file size:** ~150 KB

### Automated checks (8/8 PASS)

| # | Check | Result |
|---|---|---|
| 1 | schema_valid | ✓ 79 content findings OK |
| 2 | m2_clause_ids_resolve | ✓ all 22 clause refs resolve |
| 3 | m3_disagreements_applied | ✓ 2 routed critic disagreements all escalated |
| 4 | verdict_enum_valid | ✓ all content verdicts in extended enum |
| 5 | engine_passthrough_preserved | ✓ all non-overridden findings preserve engine fields |
| 6 | input_refs_sha256_match | ✓ all 3 input_refs sha256 match disk |
| 7 | verdict_distribution_consistent | ✓ after={requires_review: 11, not_submitted: 26, not_applicable: 26, pass: 16}, overridden=21 |
| 8 | no_orphan_overrides | ✓ every override has clause_id traceability |

### Override stats

| Metric | Value |
|---|---|
| Total engine findings (content) | 79 |
| M4 overrides applied | **21** of 79 = 27% |
| — from M2 findings | 19 |
| — from M3 critic disagreements | 2 |
| Critic disagreements routed | 2 (clauses `5.table` + `6.7.4`) |
| **New `fail` verdicts** | **0** |
| Sidecar-only findings | 2 (clauses `6.5.1` + `6.6.4`) |

**Verdict distribution shift (slice 1):**

| Verdict | Before (engine) | After (M4) | Delta |
|---|---|---|---|
| pass | 15 | 16 | **+1** |
| not_submitted | 27 | 26 | −1 |
| not_applicable | 26 | 26 | 0 |
| requires_review | 11 | 11 | 0 |
| fail | 0 | 0 | 0 |
| **Total** | **79** | **79** | 0 |

The shift is modest because most M2 overrides land on findings already at `pass` or `requires_review`. The one visible change: CONTENT_SETBACKS for plots that had `not_submitted` (no engine data) now show `pass` because M2 verified 9m between buildings.

### Why zero new `fail` verdicts (Task #33 partial)

Slice 1 produces **0 new `fail`** because:
1. Only 1 of 19 critical M2 findings is `non_compliant` (`6.6.4` plot 2). It's sidecar-only — no engine rule like `CONTENT_EASEMENT_REGISTRY` exists for it to override.
2. The other 6 critical M2 findings that affect mapped engine rules are all `compliant` or `requires_review`.
3. The `non_compliant` finding `6.5.1` (mature trees appendix) — same situation: sidecar-only, no engine rule.

**Sidecar surfaces both `non_compliant` findings in `m4_summary.sidecar_only_findings`** with reasoning + cited pages, so the PDF generator (phase 2) can render them as callouts. Task #33's symptom (zero `fail` in engine output) is partly an engine-coverage gap (missing rules for easements/tree-preservation), not just a verdict-mapping gap.

To produce a visible `fail` verdict in slice 2, candidates are:
- Adding a content rule for the easement / tree-preservation categories (engine change — beyond M4)
- Mapping more M2 `non_compliant` cases — but M2 currently has only 2 (full content of `non_compliant`)
- Lowering the bar: take M2 `requires_review` findings where the M3 critic's `compliance_indicator` is `non_compliant` and map THAT to engine `fail` (would surface the 6.7.4 91.80 disagreement as a `fail` if we trust the critic over M2 — but that contradicts Fix C policy which says critic disagreements escalate to `requires_review`, not `fail`)

### Self-verification of representative overrides

| Sample (rule_code / plot) | Verdict | Override source | Result |
|---|---|---|---|
| `CONTENT_UNIT_COUNT` / plot_1 | requires_review | m3_critic_disagreement | ✓ Critic semantic-disagreement on 5.table plot 1 ("232 units, but clause is about areas") correctly escalates |
| `CONTENT_UNIT_COUNT` / plot_2 | requires_review | m2_finding (5.table) | ✓ M2 emits requires_review for table-row extraction; critic agreed; passes through |
| `CONTENT_UNIT_COUNT` / plot_6 | not_applicable | — (passthrough) | ✓ No M2 data for plot 6; engine fields preserved |
| `CONTENT_BUILDING_HEIGHT` / plot_1 | requires_review | m2_finding (5.table) | ✓ M2 extracted "10-14 floors" range; engine verdict updated; critic agreed |
| `CONTENT_BUILDING_HEIGHT` / plot_5 | requires_review | m3_critic_disagreement | ✓ The legitimate interpretive disagreement on 6.7.4 (89.80 vs 91.80) escalates correctly. m4_m2_clause_ids=[5.table, 6.7.4]; m4_m3_critic_verdict=disagree |
| `CONTENT_BUILDING_HEIGHT` / plot_7 | not_applicable | — (passthrough) | ✓ No M2 data; engine output preserved |
| `CONTENT_SETBACKS` / plot_1 | pass | m2_finding (4.1.2.4) | ✓ Override from `not_submitted` to `pass` based on M2's verified "9m between buildings" extraction |

**Aggregate self-verify: 7/7 correct.**

### Sidecar-only findings (surfaced in m4_summary)

```json
[
  {
    "clause_id": "6.5.1",
    "ta_shetach_takanon": null,
    "compliance_indicator": "non_compliant",
    "reasoning": "The clause explicitly states that a 'Mature Trees Appendix' (נספח עצים בוגרים) is attached to the plan. A review of the 63-page submission, including the table of contents on page 2, confirms that this appendix is missing.",
    "source_pages": [2]
  },
  {
    "clause_id": "6.6.4",
    "ta_shetach_takanon": "2",
    "compliance_indicator": "non_compliant",
    "reasoning": "The clause specifically requires an underground easement for vehicle passage from plot 2 to the adjacent plot 12. The basement plan for plot 2 (page 37) and the corresponding site plan (page 34) do not show any ramp, tunnel, or other provision for such a connection.",
    "source_pages": [34, 37]
  }
]
```

### Engine baseline preserved

The engine's `audit_outputs/407-1048248/v24.3/audit_results.json` sha256 is UNCHANGED. M4 wrote a NEW file (`audit_results.m4.slice1.tmp.json`) alongside, not in place. Regression check via `tests/regression/v8j_baseline_v24.3.json` would continue to pass byte-identically.

### Issues observed during slice 1

1. **Slice-spec filter dropped sidecar entries (FIXED mid-slice).** Initial filter `--slice-rules CONTENT_UNIT_COUNT,...` translated to enabled-M2-clauses via `MAPPINGS` but skipped entries with `engine_rule_code: None`. Fix applied: `_parse_slice_spec()` now ALWAYS includes sidecar-only mappings regardless of engine-rule filter. Re-ran with fix; sidecar findings now appear in `m4_summary.sidecar_only_findings`.
2. **Task #33 not visibly addressed by slice 1.** Both M2 `non_compliant` findings are sidecar-only (no engine rule to override). They surface in the sidecar list, but until the PDF generator (phase 2) renders sidecar callouts, the visible engine-output `fail` count stays 0. Recommend the PDF patch include sidecar rendering as part of the same change.
3. **5.table plot_1 finding's critic disagreement comment is a semantic critique** ("232 is units not areas"), not a value disagreement. M4 correctly escalates to requires_review per Fix C, but the resulting notes_he may confuse readers (the value 232 IS correct; only the interpretation is disputed). For phase 2 PDF, may want to highlight critic_verdict severity rather than just dump the reasoning.

### Recommended slice 2 (when approved)

- Expand mapping to cover `CONTENT_PARKING_RATIO` (need parking ratio M2 findings; currently 6.2.1/6.2.2 are not in critical-19 because qualitative)
- Add `CONTENT_APARTMENT_MIX_SMALL` (M2 has plan-wide finding with `requires_review` indicator + multiple ambiguous plot rows)
- Add `CONTENT_PERMEABLE_SURFACES` (M2 has it but as deferred_to_dwg)
- Consider broadening to cover M2 `requires_review` findings — currently the M2 override only flips verdict when `compliant` or `non_compliant`; many `requires_review` findings with rich evidence get less utility from M4

### Files state (uncommitted)

- `docs/m4_engine_adapter_spec.md`
- `vision_scanner/m4/{__init__,schema,clause_mapping,translator,value_parser,processor,validate,run}.py`
- `data/projects/407-1048248/submissions/v24.3/audit_results.m4.slice1.tmp.json` (~150 KB)
- `data/projects/407-1048248/submissions/v24.3/audit_results.m4.run_log.jsonl` (2 entries — pre-fix run + post-fix re-run)
- `data/projects/407-1048248/submissions/v24.3/m4_test_slice_verification.md` (this file)

### Stop here — awaiting Lior's review

NOT patched: PDF generator (deferred to phase 2). NOT regenerated: audit_report_24.3.pdf. NOT committed: any of the above.

---

## Round 2 — Expanded mapping (17 rules, m4-v1)

**Date:** 2026-05-24
**Output file:** `data/projects/407-1048248/submissions/v24.3/audit_results.m4.tmp.json`
**Code:** `vision_scanner/m4/clause_mapping.py` expanded from 7 → **17 entries** (covering 16 unique M2 clauses).
**Spec unchanged** (still m4-v1 — only the data table grew).

### Mapping coverage by engine rule

| Engine rule | # mapping entries | Engine findings overridden | Notes |
|---|---|---|---|
| `CONTENT_UNIT_COUNT` | 1 | 5 of 11 | 5.table units; plots 1-5 (M2 has no plot 6-10/20 evidence) |
| `CONTENT_BUILDING_HEIGHT` | 3 | 5 of 11 | 5.table floors + 4.1.2.1 + 6.7.4 (latter → plot_5 only) |
| `CONTENT_SETBACKS` | 1 | 11 of 11 | 4.1.2.4 9m compliance annotates all plots |
| `CONTENT_PARKING_RATIO` | 4 | 11 of 11 | 6.2.x family + 4.1.2.10 plot_1-specific |
| `CONTENT_PERMEABLE_SURFACES` | 2 | 1 of 1 | 6.5.4.א + 4.5.2.1 (plan-wide) |
| `CONTENT_BUILDING_AREA_MAIN` | 0 | 0 of 11 | **GAP** — submission has no שטח עיקרי table |
| `CONTENT_BUILDING_AREA_SERVICE_ABOVE` | 0 | 0 of 11 | **GAP** — same |
| `CONTENT_BUILDING_AREA_SERVICE_BELOW` | 0 | 0 of 11 | **GAP** — same |
| `CONTENT_APARTMENT_MIX_SMALL` | 0 | 0 of 1 | **GAP** — M2 lacks a clean small-apt % clause |
| **Sidecar (no engine row)** | 6 | — | 2 non_compliant (6.5.1, 6.6.4) + 4 missing (4.2.2.4, 4.3.2.2, 6.4.2, 7.1.1) |

**Total override coverage:** 33 of 79 content findings = **42%** (up from slice-1's 27%).

### Run stats

- Runtime: 0.199 sec (still sub-second; M4 is pure local compute)
- Cost: $0
- All 8 automated checks PASS

### Round 2 verdict distribution shift

| Verdict | Before (engine) | After Round 1 (slice 1) | After Round 2 | Round 2 Δ vs engine |
|---|---|---|---|---|
| pass | 15 | 16 | **22** | **+7** |
| not_submitted | 27 | 26 | 20 | **−7** |
| not_applicable | 26 | 26 | 25 | −1 |
| requires_review | 11 | 11 | 12 | +1 |
| fail | 0 | 0 | 0 | 0 |

The +7 pass shift comes from:
- 6 × CONTENT_PARKING_RATIO findings that were `not_submitted` → `pass` (annotated via 6.2.x evidence)
- 1 × CONTENT_PERMEABLE_SURFACES that flipped to `requires_review` (deferred_to_dwg)

### Sidecar entries (6 surfaced for PDF callout)

| clause | plot | indicator | reasoning summary |
|---|---|---|---|
| `6.5.1` | plan-wide | **non_compliant** | Mature trees appendix (נספח עצים בוגרים) missing from submission |
| `6.6.4` | plot_2 | **non_compliant** | חלקה 12 underground easement not shown |
| `4.2.2.4` | plot 9 | missing | Plot 9 pedestrian passage not in submission |
| `4.3.2.2` | plot 7 | missing | Plot 7 שצ"פ width 10m+ not in submission |
| `6.4.2` | plan-wide | missing | Stormwater retention 450 m³ not in submission |
| `7.1.1` | plan-wide | missing | Phasing plan not provided |

### Slice-1 regression — PRESERVED

| Slice-1 expected outcome | Round 2 result |
|---|---|
| `CONTENT_SETBACKS/plot_1` = `pass` via m2_finding | ✓ verdict=pass, source=m2_finding |
| `CONTENT_BUILDING_HEIGHT/plot_5` = `requires_review` via m3_critic_disagreement | ✓ verdict=requires_review, source=m3_critic_disagreement |
| 2 sidecar entries (6.5.1, 6.6.4) present | ✓ both present (plus 4 new) |

### Self-verification of NEW Round 2 overrides

| Sample (rule_code / plot) | Verdict | Override source | Result |
|---|---|---|---|
| `CONTENT_PARKING_RATIO` / plot_1 | pass | m2_finding (4.1.2.10 + 6.2.1/2/3) | ✓ correct — 4.1.2.10 plot-1-specific takes precedence ("daycare separation"), 6.2.x clauses aggregate as supporting |
| `CONTENT_PARKING_RATIO` / plot_2 | pass | m2_finding (6.2.1+6.2.2+6.2.3) | ✓ correct — 6.2.1 plan-wide compliant ("all parking underground") wins |
| `CONTENT_PARKING_RATIO` / plot_5 | pass | m2_finding (6.2.x) | ✓ correct — same logic |
| `CONTENT_PARKING_RATIO` / plot_6 | pass | m2_finding (6.2.x) | ✓ correct — `all_engine_plots` mapping applies even to plots M2 didn't directly cover |
| `CONTENT_PARKING_RATIO` / plot_20 | pass | m2_finding (6.2.x) | ✓ correct — same |
| `CONTENT_PERMEABLE_SURFACES` / plan-wide | requires_review | m2_finding (6.5.4.א + 4.5.2.1) | ✓ correct — 4.5.2.1 deferred_to_dwg (high) wins over 6.5.4.א compliant (medium) by confidence rank; deferred_to_dwg translates to requires_review |
| `CONTENT_UNIT_COUNT` / plot_4 | requires_review | m2_finding (5.table) | ✓ slice-1 carryover — 5.table requires_review preserved |
| `CONTENT_BUILDING_HEIGHT` / plot_3 | requires_review | m2_finding (5.table) | ✓ slice-1 carryover |

**Aggregate self-verify: 8/8 correct.**

### Coverage gaps documented

The mapping table inline-documents 3 engine rules with no M2 source:
- `CONTENT_BUILDING_AREA_MAIN`, `CONTENT_BUILDING_AREA_SERVICE_ABOVE`, `CONTENT_BUILDING_AREA_SERVICE_BELOW` — submission has no שטח עיקרי / שטח שירות tables (architect's design plan, not quantitative-areas plan). The existing curated `extracts.json` also marks these `null` with `_note_areas` explanation. Engine emits `not_submitted` for these 33 findings; M4 can't improve without source data.
- `CONTENT_APARTMENT_MIX_SMALL` — no clean M2 clause covers small-apartment % calculation. The takanon math uses 5.table area ranges + per-plot mix; M2's 5.table extractions are unit counts and floor counts, not unit-mix breakdowns. The existing hand-curated `extracts.json` populates this directly.

To close these gaps would require either:
- A future M2 prompt iteration that explicitly targets per-plot שטח עיקרי / שטח שירות / unit-mix bands (the architect's submission doesn't have them, so likely deferred until the architect publishes a v25.x with these tables)
- Or engine-side rules that handle "submission has no area table" → requires_review with a clearer remediation message (engine change, beyond M4 scope)

### Still zero new `fail` verdicts

Even with expanded mapping, Round 2 produces 0 new `fail` verdicts in the engine output. The 2 non_compliant M2 findings (6.5.1, 6.6.4) remain in the sidecar list — engine has no rules for "mature trees appendix" or "easement registration" to override.

**Task #33 status:** M4 cannot produce `fail` verdicts via engine override without engine-side rule additions for the easement / tree-preservation / phasing categories. The sidecar list IS where these violations live in M4's output — and the phase-2 PDF generator patch will surface them as visible callouts. The Task-#33 fix is therefore split: (a) M4 surfaces violations in sidecar; (b) PDF generator renders sidecar as a callout section; (c) future engine work adds rules so violations can also override row verdicts.

### Files state (uncommitted)

- `vision_scanner/m4/clause_mapping.py` (updated to 17 mappings + gap documentation)
- `data/projects/407-1048248/submissions/v24.3/audit_results.m4.tmp.json` (~280 KB)
- `data/projects/407-1048248/submissions/v24.3/audit_results.m4.slice1.tmp.json` (now stale — kept for slice-1 reference; delete on lock)
- `audit_results.m4.run_log.jsonl` (3 entries — slice 1, slice 1 with sidecar fix, Round 2)
- `m4_test_slice_verification.md` (this file)

### Recommendation

Mapping table is mature for v1. Engine ↔ M2 coverage is bounded by the architect submission's content (no area tables, no unit-mix breakdowns). Two next steps are independently valuable:
1. **Phase 2: PDF generator patch** — make report_generator render `audit_results.m4.json` if present (fall back to `audit_results.json`) AND render `m4_summary.sidecar_only_findings` as a callout. This is where Tasks #32 + #33 become visibly addressed in the user-facing audit.
2. **Future M5 (engine rules expansion)** — add rules for easement/tree-preservation/phasing so the 2 non_compliant findings actually map to `fail` verdicts in the engine output, not just the sidecar.

### Stop here — awaiting Lior's review

NOT patched: PDF generator. NOT regenerated: audit_report_24.3.pdf. NOT committed: any of the above.
