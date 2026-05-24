# M3 Test Slice Verification — Submission v24.3

## Slice 1 (5 critical M2 findings, Gemini 2.5 Flash critic, m3-v1)

**Date:** 2026-05-24
**Verifier:** Claude Code (rasterized cited pages at 200 DPI + 400 DPI for the dispute case; viewed via Read)
**Output file:** `data/projects/407-1048248/submissions/v24.3/critic_findings.slice1.tmp.json`
**Prompt:** `vision_scanner/critic/prompts/m3_v1.txt` (m3-v1)
**Code commit:** uncommitted; built on top of `5789785`

### Filter sanity check — critical findings in M2

Filter (per spec): `compliance_indicator ∈ {compliant, non_compliant}` AND `confidence == "high"` AND `extraction.value contains a digit` AND `source_pages non-empty`.

**Result: 9 of 110 M2 findings are critical** (8 compliant + 1 non_compliant). Lower than the 20-30 estimate because:
- All 6 of the `5.table` per-plot row extractions emit `requires_review` (M2 correctly defers row-vs-takanon threshold comparison to M4) → filtered out
- ~30 M2 findings are `medium` confidence → filtered out
- Many M2 findings are qualitative text ("residential use is shown throughout") with no digit → filtered out

**Implication:** the M3 critic in its current shape does NOT critique the most quantitatively-impactful M2 findings (the rights-table cells). Slice-2 / full-scale will be small (≤9 findings) unless the filter is broadened. **Flagged for Lior — should `requires_review` findings also be critiqued?** That would change M3's role from "double-check M2's verdicts" to "double-check M2's extractions regardless of verdict".

### Clauses selected for slice 1

| # | clause_id | Category | Rationale |
|---|---|---|---|
| 1 | `4.1.2.4` | building_geometry | Plan-level quantitative — 9m minimum between buildings. Pure numeric extraction from a plan dimension label. |
| 2 | `6.7.4` | building_height_safety | Plan-level quantitative — 91m max absolute height (aviation). Pure numeric extraction from an elevation drawing. |
| 3 | `4.1.2.10` | parking | Plot-1 qualitative-quantitative — "separate entrances and parking for daycare". Tests critic on a mixed text/visual claim. |
| 4 | `6.6.4` | easements | **The single `non_compliant` finding** (plot 2 → חלקה 12 underground easement) — must be critiqued. Tests critic on a "missing-feature" claim. |
| 5 | `6.1.2` | public_areas | Plan-level quantitative — 780 sq.m daycare facilities. Tests critic on aggregate area extraction from multi-page basement + functions diagram. |

Substituted `6.7.4` and `4.1.2.4` for the requested "5.table" because no 5.table finding survives the critical-filter (see Filter section above).

### Run stats

- **Calls:** 5 sequential Flash calls (one per finding)
- **Runtime:** 92 sec end-to-end including raster + 5 Flash calls + validation
- **Total attempts:** 5 (no retries on the re-run; one prior aborted run with `MAX_OUTPUT_TOKENS=4096` truncated mid-string — bumped to 16384 and the re-run succeeded)
- **Per-finding tokens:** 1.0K–1.6K prompt, 140–240 candidates each. Aggregate: prompt 6,920 + candidates 846 + thinking ~12,726 = **total 20,492 tokens**
- **Cost (Gemini 2.5 Flash pricing $0.075/M input, $0.30/M output):** 6,920 × $0.075/M + 13,572 × $0.30/M = $0.0005 + $0.0041 = **~$0.005** ($0.001/finding)
- **Snapshots:** 5 incremental saves (after each finding) — patch verified

### Automated checks (8/8 PASS)

| # | Check | Result |
|---|---|---|
| 1 | schema_valid | ✓ 5 critic_findings OK |
| 2 | clause_ids_in_vision | ✓ all 5 resolve to M2 findings |
| 3 | source_pages_in_range | ✓ all in [1, 63] |
| 4 | verdict_enum_valid | ✓ all in {agree, disagree, cannot_determine} |
| 5 | disagree_has_severity | ✓ severity set iff verdict=disagree |
| 6 | disagree_has_extraction_value | ✓ every disagree has critic_extraction_value |
| 7 | input_refs_sha256_match | ✓ vision_findings.json sha256 matches disk |
| 8 | summary_counts_consistent | ✓ critiqued=5, agree=3, disagree=2, cannot_determine=0 |

### Critic verdict distribution

- **agree:** 3 (60%)
- **disagree:** 2 (40%)
  - 1 × major (refines value/scope)
  - **1 × critical (verdict-flip claim)**
- **cannot_determine:** 0

### Self-verification of each critic call

For each I rasterized the cited `m2_source_pages` at 200 DPI to `/tmp/m3_verify_slice1/` (page 58 also at 400 DPI + cropped zoom for the high-stakes dispute) and viewed each.

| # | clause | M2 verdict | Critic verdict | Self-verify of CRITIC | Notes |
|---|---|---|---|---|---|
| 1 | 4.1.2.10 / plot 1 | compliant | **agree, compliant** | ✓ correct | Page 29 basement clearly shows גן ילדים with a distinct entrance separate from residential A1/B1/C1/D1 lobbies. Critic's reasoning cites the page directly. |
| 2 | 4.1.2.4 | compliant, "9" m | **agree, "9.00" m compliant** | ✓ correct | Page 24 site plan plot 1 has "900" labels (= 9.00 m) between buildings. Critic refines string format but value matches. |
| 3 | 6.1.2 | compliant, "780 sq.m daycare + clubs in other plots" | **disagree / major, "780 sq.m daycare + 180 sq.m clubs IN plot 1" compliant** | ✓ critic is MORE PRECISE | Page 26 (functions diagram plot 1) shows מועדון דיירים in buildings A and B of plot 1 with areas. M2's "other plots" wording was loose; critic correctly refines. Same verdict, sharper extraction. |
| 4 | 6.6.4 / plot 2 | **non_compliant**, "no underground passage" | **agree, non_compliant** | ✓ correct | Page 37 basement plot 2 is a self-contained footprint; no tunnel/ramp toward חלקה 12. Critic's reasoning matches what I verified in M2 Round 4. |
| 5 | 6.7.4 | compliant, **"89.80" m** | **disagree / critical, "91.80" m, non_compliant** | ✗ **CRITIC WRONG** | Page 58 at 400 DPI clearly shows "**A5 +42.30 / +89.80**" for plot 5's tallest building — same value M2 extracted. **No "91.80" appears anywhere on page 58.** Critic hallucinated 2 extra meters. M2's compliant verdict (89.80 < 91 m limit) stands. |

**Aggregate critic accuracy: 4 / 5 (80%).**

- 3 agreements where the critic correctly confirmed M2's claim
- 1 disagree/major where the critic was MORE precise than M2 (helpful refinement)
- 1 disagree/critical where the critic hallucinated a different value (critic should be ignored)

### Independence check (no leaked M2 reasoning)

Reviewed each critic_reasoning for phrases that would indicate the critic saw M2's reasoning:
- ✓ No "Pro said" / "the M2 reasoning" / "they claimed" / "according to the source" leaks
- One minor reference in finding #3 ("the claimed extraction incorrectly states...") — this is acceptable because the critic IS supposed to know the claimed value and can comment on its phrasing; it doesn't reveal M2's full reasoning
- Critic uses its own page-reasoning ("the upper basement plan on page 29..."), Hebrew-label citations ("שטח מעונות יום קרקע — 280 מ'ר"), and self-contained logic

**Independence verdict: PASS.** No reasoning leakage. The 91.80 hallucination is NOT caused by independence breach — it's a Flash visual misreading.

### Issues to address before slice 2

1. **Filter scope is too narrow.** Only 9 critical findings selected. The most quantitatively impactful claims (5.table rows) are all `requires_review` and thus excluded. Two options:
   - (a) Broaden filter to include `requires_review` with numeric value when source_pages are populated (would add ~10 5.table findings to the critique pool, raising total critical to ~19)
   - (b) Keep filter as-is and ship M3 as "verdict-double-check only" rather than "extraction-double-check". M4 handles 5.table thresholds.
   - **Recommend (a)** — Flash is cheap ($0.001/finding) and the 5.table rows are exactly where row-level mis-reads have the highest stakes.
2. **MAX_OUTPUT_TOKENS = 4096 was too small.** Bumped to 16384 in slice-1 mid-run. Should be the default for m3-v1 going forward (already applied).
3. **Critic can make critical-severity hallucinations.** Finding #5 (6.7.4) flipped compliant → non_compliant on a misread value. This means M3's verdicts must be presented to human reviewers as DISAGREEMENT FLAGS — not as authoritative overrides of M2. M4 should treat `critic_verdict == disagree` as "require human review of this row", not as "non_compliant".

### Stop here

Per the spec, do NOT proceed to slice 2 without explicit go. Issues #1 (filter scope) and #3 (interpretation policy) are non-blocking for slice-1 sign-off but should be addressed before broader rollout.

### Files state (uncommitted)

- `docs/m3_critic_spec.md`
- `vision_scanner/critic/{__init__,schema,filter,extract,validate,run}.py`
- `vision_scanner/critic/prompts/m3_v1.txt`
- `data/projects/407-1048248/submissions/v24.3/critic_findings.slice1.tmp.json` (5 findings, ~7 KB)
- `data/projects/407-1048248/submissions/v24.3/critic_findings.run_log.jsonl` (2 entries — failed first run + successful re-run)
- `data/projects/407-1048248/submissions/v24.3/m3_test_slice_verification.md` (this file)

---

## Slice 1.5 + Round 2 (m3-v2, full critical set)

**Date:** 2026-05-24
**Output files:**
- `critic_findings.slice1_5.tmp.json` — 5-finding re-run of slice 1 with m3-v2
- `critic_findings.tmp.json` — full 19-finding critique with m3-v2

### 3 fixes applied in m3-v2

1. **Fix A — Filter broadened.** `is_critical()` now adds a 5.table exception: any 5.table clause with a digit + source_pages passes regardless of `requires_review` indicator. This brings the rights-table per-plot row extractions into critique scope (M2 emits `requires_review` for table rows so M4 can do the row-vs-takanon threshold check; the row's NUMERIC VALUE is still worth Flash-critiquing). Critical-set grew **9 → 19** (8 compliant + 1 non_compliant + 10 × 5.table rows).
2. **Fix B — DPI bump + exact-citation + critical re-examination.** Raster DPI 200 → **300** so small floor-ladder labels are clearer. Prompt now requires exact-text citation (quoted Hebrew/English with surrounding context) when `verdict=disagree`. Prompt also requires a literal `'I re-examined the page at [region]'` phrase when `severity=critical`, else the severity must be downgraded. Prompt versioned m3-v2.
3. **Fix C — Disagreement-handling policy.** Appended to `docs/m3_critic_spec.md` (new section "Disagreement handling policy for M4") and recorded as `Task #34` in `docs/known_issues.md`. M4 escalates `disagree` findings to `requires_review` in the engine, never auto-flips M2's verdict. Rationale: m3-v1 slice 1 verified that critics can produce critical-severity hallucinations.

Also **schema patched** mid-run: `M2ComplianceIndicator` enum extended to include `requires_review` (required because the broadened Fix-A filter now includes 5.table findings with that indicator). The Pro response itself was already valid; only the on-disk schema needed updating.

### Slice 1.5 re-run (same 5 clauses as slice 1)

- **Runtime:** 99s for 5 Flash calls
- **Cost:** prompt 8,950 + candidates 916 + ~8K thinking = ~$0.005
- **Verdict distribution:** 4 agree (was 3 in slice 1), 1 disagree/critical, 0 cannot_determine
- **All 8 checks PASS**
- Finding #3 (6.1.2 daycare) flipped from slice-1's "disagree/major" to slice-1.5's "agree" — the previous "M2 says clubs in other plots, critic says clubs in plot 1" refinement was apparently too nitpicky on re-read.
- **Finding #5 (6.7.4) STILL disagree/critical** — but with proper exact-citation: critic claims "+42.30 // +91.80" at level 13 of the elevation ladder. **Verified at 500 DPI**: the floor-13 elevation marker DOES read +91.80 on page 58's right-side ladder. So this is NOT a hallucination — it's an interpretive disagreement (M2 read A5's actual roof label `+42.30/+89.80`; critic read the floor-13 envelope marker on the master ladder). Per the new Fix C policy, M4 escalates to `requires_review`.

### Round 2 full-critical run (19 findings, m3-v2)

- **Runtime:** 429s (~7 min)
- **Cost:** prompt 33,334 + candidates 3,674 + thinking ~43,041 = total 80,049 tokens → $0.0025 + $0.0140 = **~$0.017** for all 19
- **Verdict distribution:** **13 agree (68.4%) / 5 disagree / 1 cannot_determine**
  - of the 5 disagrees: 1 critical (6.7.4 interpretive), 4 major
- **All 8 automated checks PASS** (after schema patch)
- **0 critical-severity hallucinations** — the lone critical disagreement (6.7.4) is the legitimate interpretive case verified above

### Per-finding overview (all 19)

| # | clause | M2 value | Verdict | Critic value | Sev |
|---|---|---|---|---|---|
| 1 | 4.1.2.10 | "Separate entrances..." | agree | confirmed | — |
| 2 | 4.1.2.13 | 5.35 | **disagree** | **4.50** | major |
| 3 | 4.1.2.13 | 4.1 | **disagree** | **4.50** | major |
| 4 | 4.1.2.4 | 9 | agree | 9 | — |
| 5 | 4.1.2.9 | "Daycare centers..." | agree | confirmed | — |
| 6 | 4.1.2.א.3 | "shared basement" | **disagree** | **"separate basements"** | major |
| 7 | 5.table plot 1 | 232 | **disagree** | 232 (value ok, semantic concern) | major |
| 8 | 5.table plot 1 | 10-14 | agree | 10-14 | — |
| 9-13, 15-16 | 5.table plots 2-5 | various | all agree | values match | — |
| 14 | 5.table plot 4 (9-13 floors) | 9-13 | **cannot_determine** | (overly literal — strict reading of "table") | — |
| 17 | 6.1.2 | "780 sq.m daycare..." | agree | 780 sq.m confirmed | — |
| 18 | 6.6.4 / plot 2 | "no underground passage" non_compliant | agree | confirmed | — |
| 19 | 6.7.4 | 89.80 | **disagree** | **91.80** | critical |

### Self-verification of 8 random + the 1 critical (sample seed 42, forced-include disagrees)

| Sample | clause | Critic verdict | Self-verify | Critic correct? |
|---|---|---|---|---|
| 1 | 4.1.2.10 (daycare entrance) | agree | ✓ page 29 shows separate entrance | ✓ correct |
| 2 | 4.1.2.13 (5.35 → 4.50) | disagree/major | ✓ **page 61 ladder shows floor 01 at +4.50, floor 00 at +0.00 → lobby = 4.50m; M2's 5.35 = wrong baseline (used +45.45 = B1's TOP, not ground)** | ✓ **CRITIC CAUGHT M2 ERROR** |
| 3 | 4.1.2.13 (4.1 → 4.50) | disagree/major | ✓ same ladder, M2's 4.1 also wrong | ✓ **CRITIC CAUGHT M2 ERROR** |
| 4 | 4.1.2.4 (9m) | agree | ✓ page 24 "900" labels verified | ✓ correct |
| 6 | 4.1.2.א.3 (basement) | disagree/major | ✓ **page 37 hi-res clearly shows plot 2 basement and plot 4 basement as separate enclosed footprints; M2's "shared" is wrong** | ✓ **CRITIC CAUGHT M2 ERROR** |
| 7 | 5.table 232 units | disagree/major | ⚠ value (232) matches reality; critic's semantic concern is fair but pedantic — the rights table DOES have a "units" column | ⚠ critic raises valid concern, M2 not wrong |
| 8 | 5.table 10-14 floors | agree | ✓ page 61+62 elevation ladders span 00-14 | ✓ correct |
| 14 | 5.table 9-13 floors plot 4 | cannot_determine | ⚠ critic is too strict — elevations DO show floor counts which is what was extracted | ⚠ overly literal but conservative |
| 19 | **6.7.4 (89.80 vs 91.80)** | disagree/critical | ✓ **page 58 right-ladder at 500 DPI shows "13 → +42.30 // +91.80"** AND base label shows "A5 +42.30 / +89.80" — **both numbers are on the page**. M2 read A5's actual roof; critic read the regulatory floor-13 envelope. Legitimate interpretive disagreement. | ⚠ legitimate, handled by Fix C escalation |

**Critic correctness on examined 9 findings: 5 strong-correct + 2 semantic-concerns + 1 overly-literal + 1 interpretive-disagreement = 5 unambiguous wins, 4 nuanced.**

**The 3 cases where the critic caught real M2 errors (#2, #3, #6) are the strongest justification for shipping M3.** Without the critic, M2's 4.1.2.13 lobby-height extractions would have stood at incorrect values (5.35 and 4.1) and 4.1.2.א.3 would have falsely claimed a shared basement. All three errors landed inside `compliant` findings, so M2's verdicts happened to be right by coincidence (4.50 is still ≥4.5m; separate basement is still permitted by the permissive clause) — but the underlying extraction was wrong. M3 surfaces these for human review.

### Independence check (no leaked M2 reasoning)

Reviewed reasoning across all 19 findings:
- ✓ Critic uses page numbers + direct Hebrew citations (`"מרתף עליון"`, `"כניסה לגן ילדים"`, `"+45.45 // +85.45"`)
- ✓ No phrases like "the other model said" / "Pro extracted" / "M2 claimed"
- ✓ Reasoning is self-contained — independent of M2's logic
- One minor: finding #7's reasoning ("the extracted value does not align with the type of information the clause describes") gently critiques M2's extraction choice. Acceptable — it's a substantive observation about scope, not a leak of M2's reasoning text.

### Cost & throughput

- **Cost per critique:** ~$0.001/finding
- **Cost per project (110 M2 findings → 19 critical):** ~$0.017
- **Runtime per critique:** ~22.5s/finding avg
- **Runtime per project:** ~7 min for the full critical set
- **Total M2+M3 cost on v24.3:** $1.22 (M2) + $0.017 (M3) = **$1.24**

### Remaining concerns

1. **Critic over-strict on table-context (#14).** When M2 extracts floor counts from elevation pages for a 5.table row, the critic strictly reads the clause as "must be a table" and emits cannot_determine. Acceptable conservative posture but suggests prompt refinement for m3-v3 if needed (e.g., "the cited pages are sufficient evidence regardless of whether they're the literal takanon table").
2. **Critic semantic-scope concern on #7 (232 units vs "building areas").** The 5.table clause text spans multiple columns; the critic is right that "units" ≠ "building area" but M2's extraction is on the units column which IS part of the table. Worth flagging for M4's row-level reasoning.
3. **6.7.4 (#19) interpretive disagreement persists.** Fix C handles it — escalate to requires_review. Engineer decides whether the floor-13 envelope at +91.80 or A5's actual roof at +89.80 is the right value for the clause.

### Aggregate verdict

**APPROVE M3 for lock.**
- All 8 automated checks PASS
- 0 critical-severity hallucinations after Fix B (the one critical disagreement is now well-cited and verifiable)
- Critic caught 3 real M2 errors (4.1.2.13 × 2 + 4.1.2.א.3) — direct value justification for the M3 layer
- Disagreement-handling policy (Fix C) provides the safety net for the remaining interpretive disagreements
- Cost is negligible ($0.017 for full project)

---

## Methodology Lessons Learned

### Self-verify zoom can miss interpretive disagreements

During slice 1 self-verify, finding #5 (clause 6.7.4) was incorrectly flagged as a critic hallucination ("91.80m vs M2's 89.80m"). Self-verify zoomed on A5's roof label (+89.80) and concluded the critic invented +91.80.

Slice 1.5 with Fix B (exact-citation requirement) forced the critic to cite "13 → +42.30 // +91.80" — which prompted re-verification at 500 DPI of the page's master floor ladder on the right side. The marker IS there. Both numbers (89.80 and 91.80) appear on page 58 in different roles: 89.80 is A5's actual roof, 91.80 is the floor-13 envelope marker.

**Lesson:** when self-verifying disagreements, scan the entire cited page region (not just the immediate bbox around the disputed value). Interpretive disagreements — where both readings are factually on the page but reference different elements — are not catchable by bbox-local zoom alone.

**Downstream consequence:** Fix C (escalate critical disagreements to requires_review rather than auto-flipping) is the correct policy because neither M2 nor the critic should be trusted to adjudicate interpretive ambiguity. Surface to human.
