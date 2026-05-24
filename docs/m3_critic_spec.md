# M3: Critic Specification — Submission v24.3

**Status:** v1 draft, 2026-05-24. Awaiting slice-1 verification before scaling.
**Owner:** `vision_scanner.critic` package.
**Dependencies:** M0 locked at `08f2a1a` (177 clauses), M1 locked at `48d4661` (63 manifests), M2 locked at `0ede9da` (110 vision findings).

## Purpose

Run an **independent** vision-model critic over M2's **critical** findings to catch:
- Mis-readings of values from drawings (wrong number extracted)
- Mis-classifications of compliance (compliant vs non-compliant flipped)
- Hallucinated values where the cited page actually has no such evidence

M3 produces `critic_findings.json` with an `agree`/`disagree`/`cannot_determine` verdict per critical M2 finding plus a disagreement-severity tag. Feeds M4 (compliance reasoning) by surfacing where to require extra human review.

## Scope

**In (the "critical" subset of M2 findings):**
- `compliance_indicator ∈ {compliant, non_compliant}` — verdicts that would be acted on in the report
- `confidence == "high"` — M2 was confident, so a critic disagreement is most impactful
- `extraction.value` is numeric (parseable as a number, ignoring units) — text-only extractions are out-of-scope for this critic pass
- `source_pages` non-empty — the critic needs cited evidence to evaluate

**Out (for M3):**
- M2 findings with `requires_review`, `missing`, or `deferred_to_dwg` indicators (no actionable verdict to critique)
- M2 findings with `confidence ∈ {medium, low}` (M2 already flagged uncertainty)
- Qualitative extractions (no numeric value to verify)
- Full re-extraction or alternative compliance reasoning — the critic only assesses M2's specific claim

## Output

**Path:** `data/projects/407-1048248/submissions/v24.3/critic_findings.json`

**Gitignore exception:** add `!data/projects/*/submissions/*/critic_findings.json` and `!data/projects/*/submissions/*/critic_findings.run_log.jsonl` to `.gitignore` (mirror the M2 pattern).

## Top-level schema

```json
{
  "project_id": "407-1048248",
  "submission_id": "v24.3",
  "critic_version": "m3-v1",
  "critic_model": "gemini-2.5-flash",
  "extracted_at": "<ISO-8601 UTC>",
  "input_refs": {
    "vision_findings_sha256": "<sha256 of vision_findings.json>",
    "source_pdf_sha256":      "<sha256 of v24.3.pdf>"
  },
  "critic_findings": [
    {
      "clause_id": "5.table",
      "m2_extraction_value": "232",
      "m2_compliance_indicator": "compliant",
      "m2_source_pages": [30],
      "critic_verdict": "agree",
      "critic_extraction_value": "232",
      "critic_compliance_indicator": "compliant",
      "critic_reasoning": "The ריכוז תמהיל table on page 30 shows '100% / 232' in the total row, confirming 232 units in plot 1.",
      "disagreement_severity": null
    }
  ],
  "summary": {
    "critiqued_count": 25,
    "agree_count": 22,
    "disagree_count": 2,
    "cannot_determine_count": 1,
    "critical_disagreements": ["6.7.4"],
    "agreement_rate_pct": 88.0
  }
}
```

## Pydantic schema

```python
class CriticFinding(BaseModel):
    clause_id: str                            # echo of M2's clause_id
    m2_extraction_value: str                  # echo of M2's value (for traceability)
    m2_compliance_indicator: Literal["compliant", "non_compliant"]
    m2_source_pages: List[int]                # the cited pages the critic looked at
    critic_verdict: Literal["agree", "disagree", "cannot_determine"]
    critic_extraction_value: Optional[str]    # critic's independent reading; required if disagree
    critic_compliance_indicator: Optional[Literal["compliant", "non_compliant", "requires_review"]]
    critic_reasoning: str                     # 2-4 sentences citing what's on the page
    disagreement_severity: Optional[Literal["minor", "major", "critical"]]

class CriticSummary(BaseModel):
    critiqued_count: int
    agree_count: int
    disagree_count: int
    cannot_determine_count: int
    critical_disagreements: List[str]         # clause_ids where severity == "critical"
    agreement_rate_pct: float

class CriticFindings(BaseModel):
    project_id: str
    submission_id: str
    critic_version: str = "m3-v1"
    critic_model: str = "gemini-2.5-flash"
    extracted_at: str
    input_refs: Dict[str, str]
    critic_findings: List[CriticFinding]
    summary: CriticSummary
```

## Architecture

**One Flash call per finding.** Flash is fast (~1-3 sec/call) and cheap (~$0.001-0.002 per call); per-finding isolation is feasible and gives the critic a tight, constrained context.

**Critical: each critic call is fed a MINIMAL context — only:**
- The clause text (verbatim from M0)
- The M2 extracted value + compliance indicator (so the critic knows what to verify)
- The rasterized PNG of EACH cited source page (one PNG per page in `m2_source_pages`)

**NOT fed to the critic:**
- M2's `compliance_reasoning` (the explanation Pro wrote justifying its verdict)
- M2's `extraction.raw_text_match`
- M2's `evidence_bboxes` (the critic does its own visual scanning)
- M2's `confidence`
- M2's `ta_shetach_*` mappings
- Any other M2 finding

**Why the redaction matters:** if the critic sees Pro's reasoning, it'll tend to echo it back instead of independently looking at the page. Removing the reasoning forces the critic to reason from page evidence alone — making disagreements meaningful and agreements substantive.

**Per-finding context size:** 1-5 pages × ~1.5K tokens per image + clause text + claim ≈ 5-15K tokens. Well within Flash's 1M context.

**Disagreement severity ladder:**
- **minor** — value differs by ≤5% (rounding, unit conversion, reading precision)
- **major** — value differs by >5% OR the extracted value is sound but the compliance verdict is wrong
- **critical** — critic finds the value isn't on the cited page at all (potential hallucination) OR the verdict flips (compliant → non_compliant)

**API key rotation:** same as M0/M1/M2 — `GeminiKeyRotator`.
**Model:** `gemini-2.5-flash` (free tier acceptable; we expect ≤30 critical findings).
**Temperature:** 0.0.
**Max output tokens:** 4096 per critic call (response is small JSON).

**JSON parse retry:** mirror M2's `MAX_JSON_RETRY=2` pattern.

**Incremental save:** after every critic call, atomically write the partial `critic_findings.json` (mirrors M2's `on_batch_complete` pattern).

## Critical-finding filter

```python
def is_critical(m2_finding: dict) -> bool:
    if m2_finding.get("compliance_indicator") not in ("compliant", "non_compliant"):
        return False
    if m2_finding.get("confidence") != "high":
        return False
    if not m2_finding.get("source_pages"):
        return False
    extraction = m2_finding.get("extraction") or {}
    val = extraction.get("value") or ""
    # Numeric: contains at least one digit AND can be normalized to a number after
    # stripping units / commas / "≈" etc. Conservative — text-only "compliant"
    # claims (e.g. "Daycare centers are present") are excluded.
    import re
    digits = re.search(r"[-+]?\d", val)
    return bool(digits)
```

Expected count from current `vision_findings.json` (110 findings): ~20-30 critical findings.

## Critic prompt (m3_v1.txt)

```
You are an independent vision-based compliance critic for an Israeli architectural
submission (תכנית עיצוב) in Hebrew. Another vision model has extracted a finding from
the submission and assigned a compliance verdict. Your job is to verify INDEPENDENTLY.

YOU DO NOT SEE THE OTHER MODEL'S REASONING. You only see:
  • The takanon clause text (Hebrew)
  • The value the other model extracted (as a string)
  • The compliance verdict it assigned (compliant / non_compliant)
  • The cited source page image(s)

YOUR TASK:
  1. Look at the cited page image(s) yourself. Find the relevant location.
  2. Read the value from the page. Is it the same as the claimed extracted value?
     • Same number → agree
     • Different number → disagree (state YOUR reading + severity)
     • Page doesn't show this number anywhere → disagree (severity="critical": potential hallucination)
     • Page is illegible / not clear enough → cannot_determine
  3. Reason about the compliance verdict from the clause + value. Does the verdict logic hold?
     • If value satisfies threshold → "compliant"
     • If value violates threshold → "non_compliant"
     • If interpretation is ambiguous → "requires_review"

OUTPUT JSON:
{
  "verdict": "agree" | "disagree" | "cannot_determine",
  "extraction_value": "<your reading from the page>" | null,
  "compliance_indicator": "compliant" | "non_compliant" | "requires_review" | null,
  "reasoning": "<2-4 sentences explaining what YOU see on the page. Do NOT speculate about why the other model said what it said.>",
  "disagreement_severity": "minor" | "major" | "critical" | null
}

DISAGREEMENT SEVERITY:
  • minor    — value differs by ≤5% (rounding, reading precision)
  • major    — value differs by >5%, OR verdict is wrong even if value is right
  • critical — value is not on the cited page at all, OR verdict flips (compliant ↔ non_compliant)

BE STRICT. Agree only if you can independently confirm BOTH the value AND the verdict.
Use cannot_determine when the cited page genuinely doesn't carry enough evidence.
```

## Test slice methodology

**Slice 1 — 5 critical findings.** Diverse-by-category to exercise:
- Building-geometry/height (per-plot numeric from elevation drawings)
- A row from 5.table (per-plot rights-table extraction)
- Parking (basement-page extraction)
- A non_compliant finding (we have only 2 in M2 — critic this one)
- One other category (e.g., POS, stormwater, easement)

**Slice 2 — 15 critical findings** after slice-1 sign-off.

**Full scale — all critical findings** (~20-30) after slice-2 sign-off.

**STOP conditions between slices:**
- Any automated validation check fails
- Independence violation observed (critic mentions "Pro said" / "the M2 reasoning" / similar)
- Critic agreement rate <50% or >95% (suspicious — either echoing or hallucinating)
- Sample self-verify finds >20% of critic verdicts incorrect

## Validation

**Automated:**
1. JSON validates against the Pydantic `CriticFindings` schema
2. Every `critic_finding.clause_id` resolves to a clause_id in `vision_findings.json`
3. Every `m2_source_pages` entry is in `[1, 63]`
4. `critic_verdict` enum valid
5. `disagreement_severity` is set whenever `critic_verdict == "disagree"` (and is null otherwise)
6. `critic_extraction_value` is set whenever `critic_verdict == "disagree"`
7. Input refs sha256 matches the on-disk `vision_findings.json`
8. `summary.critiqued_count` equals `len(critic_findings)`; agree/disagree/cannot_determine counts sum to `critiqued_count`

**Manual (Claude Code self-verify, per slice):**
- For each critic finding: rasterize the cited `m2_source_pages` at 200 DPI; view; check both M2's claim and the critic's claim against the page; verify the critic's reasoning doesn't reference M2's reasoning (independence guard)

## CLI

`vision_scanner/critic/run.py`:

```
--project-id PLAN_ID         (required)
--submission-id SUB_ID       (required, e.g. v24.3)
--source-pdf PATH            (required)
--findings-from PATH         (required, M2 output)
--output PATH                (required)
--slice-clauses SPEC         (optional: "5.1.1,6.4.2,..." or "all-critical"; default "all-critical")
--raster-dpi INT             (optional: default 200)
--print-samples              (prints each critic finding to stdout)
```

## Files this milestone creates

| Path | Purpose |
|---|---|
| `docs/m3_critic_spec.md` | This spec |
| `vision_scanner/critic/__init__.py` | Subpackage |
| `vision_scanner/critic/schema.py` | Pydantic models |
| `vision_scanner/critic/extract.py` | Per-finding Flash critic call |
| `vision_scanner/critic/filter.py` | `is_critical()` predicate |
| `vision_scanner/critic/validate.py` | 8 automated checks |
| `vision_scanner/critic/run.py` | CLI entry point |
| `vision_scanner/critic/prompts/m3_v1.txt` | Critic prompt template |
| `data/projects/407-1048248/submissions/v24.3/critic_findings.json` | Output (after full run + lock) |
| `data/projects/407-1048248/submissions/v24.3/critic_findings.run_log.jsonl` | Run history |
| `data/projects/407-1048248/submissions/v24.3/m3_test_slice_verification.md` | Per-slice audit |
| `.gitignore` patches | `!.../critic_findings.json`, `!.../critic_findings.run_log.jsonl` |

## Acceptance criteria for M3

1. Every critical finding (per the filter) has a critic verdict
2. All 8 automated validation checks pass
3. Independence guard passes — no critic reasoning references M2's reasoning
4. Slice-by-slice approval (5 → 15 → all critical)
5. Self-verify on a random sample shows ≥80% of critic verdicts are correct (i.e., when critic agrees, M2 was right; when critic disagrees, critic was right)
6. Source PDF, M2 vision_findings sha256s in `input_refs` match the on-disk files
7. Committed to `phase-3-vision`

## Disagreement handling policy for M4

M3 critic verdicts are DISAGREEMENT FLAGS for human review, NOT authoritative overrides of M2.

When M4 adapter consumes `critic_findings.json`:
- `verdict=agree` → no action; M2 finding stands as-is in engine output.
- `verdict=cannot_determine` → attach critic reasoning as a note; M2 finding stands.
- `verdict=disagree, severity=minor` → attach critic note; M2 value stands (rounding/precision deltas).
- `verdict=disagree, severity=major` → escalate to `requires_review` state in engine; both M2 and critic reasoning attached; engineer decides.
- `verdict=disagree, severity=critical` → escalate to `requires_review` state in engine; both M2 and critic reasoning attached; engineer decides. **M2's original verdict is NOT auto-flipped.**

**Rationale:** M3 slice 1 (m3-v1) verified that critics can hallucinate critical-severity flips (e.g., misreading "+89.80" as "+91.80" on plot 5 elevation page 58, flipping a correct `compliant` verdict to incorrect `non_compliant`). Auto-override would propagate critic errors into the audit PDF. The added value of M3 is surfacing disagreements for human attention, not adjudicating them.

m3-v2 adds two structural defenses against repeat hallucinations (exact-label citation requirement + critical-severity re-examination rule), but the M4-side conservative-handling policy above remains the authoritative safety net.
