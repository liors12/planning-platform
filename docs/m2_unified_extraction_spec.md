# M2: Unified Extraction Specification — Submission v24.3

**Status:** v1 draft, 2026-05-24. Awaiting slice-1 verification before scaling.
**Owner:** `vision_scanner.unified_extraction` package.
**Dependencies:** M0 locked at commit `08f2a1a` (177 clauses), M1 locked at commit `48d4661` (63 manifests).

## Purpose

For every normative clause in the takanon (M0), extract the corresponding values/evidence from the architect submission (v24.3) into a single structured `vision_findings.json`. This is the **bridge** between "what the regulation says" and "what the submission shows" — feeds M4 (compliance reasoning). It does NOT pass/fail; it surfaces grounded extractions with confidence and compliance hints.

## Scope

**In:**
- Every **normative** clause from M0 (`is_normative=true`): 93 of 177.
- All 63 pages of `projects/407-1048248/submissions/v24.3/v24.3.pdf` as visual context.
- Auto-reconciliation of three plot numbering schemes encountered in M1:
  - Takanon plot designations: 1-10 (residential, public, road), 20 (path)
  - Design-doc cadastral labels: "ת.ש 52", "ת.ש 64", etc. (parallel architect numbering)
  - שצ"פ structure labels: "מתחם 1/2/3" (sub-zones of public open space)
- One `Finding` per clause × plot scope when the clause is per-plot; one `Finding` per clause when plan-level.

**Out (for M2):**
- Compliance pass/fail verdicts — that's M4 (the `compliance_indicator` field is a HINT for M4, not a verdict).
- Format-rule checks (cover/TOC/font/etc.) — handled by the existing compliance engine.
- Discipline-specific findings (shafa, gardens, drainage, etc.) — those stay in the compliance engine for now; M4 may unify later.
- Non-normative clauses (descriptive, identification, pure headers).

## Output

**Path:** `data/projects/407-1048248/submissions/v24.3/vision_findings.json`

**Gitignore exception:** add `!data/projects/*/submissions/*/vision_findings.json` to `.gitignore` (mirrors the M1 pattern). Other files in `submissions/` stay ignored.

## Top-level schema

```json
{
  "project_id": "407-1048248",
  "submission_id": "v24.3",
  "extractor_version": "m2-v1",
  "extracted_at": "<ISO-8601 UTC>",
  "model": "gemini-2.5-pro",
  "input_refs": {
    "canonical_clauses_sha256": "<sha256 of canonical_clauses.json>",
    "page_manifests_sha256":    "<sha256 of page_manifests.json>",
    "source_pdf_sha256":        "<sha256 of v24.3.pdf>"
  },
  "plot_reconciliation": {
    "method": "auto",
    "mappings": [
      {
        "submission_label": "ת.ש 52",
        "takanon_plot": "6",
        "confidence": "medium",
        "evidence_pages": [8, 14],
        "rationale": "ת.ש 52 appears with תכנון רב-תחומי label on the page-8 summary…"
      }
    ],
    "unreconciled_submission_labels": ["מתחם 2"],
    "unreconciled_takanon_plots": ["9"]
  },
  "findings": [
    {
      "clause_id": "4.1.2.1",
      "clause_text_excerpt": "תתאפשר הקמת מספר מבנים במגרש. הבינוי לאורך רחוב הטייסים לא יעלה על 9 קומות + סה\"כ קומה טכנית. הבינוי לאורך רחובות ההסתדרות וששת הימים לא יעל…",
      "extraction": {
        "value": "10 floors",
        "unit": "floors",
        "raw_text_match": "ק. 09 (top floor index → 10 floors total above ground)"
      },
      "source_pages": [60, 61],
      "evidence_bboxes": [
        {"page": 60, "bbox": [120.5, 410.0, 780.0, 720.0], "tag": "primary"},
        {"page": 61, "bbox": [180.0, 440.0, 720.0, 800.0], "tag": "supporting"}
      ],
      "confidence": "high",
      "compliance_indicator": "requires_review",
      "compliance_reasoning": "Page 60 shows top floor index ק.09 = 10 floors above ground for plot 3 building A3, exceeding the 9-floor limit by one floor. Cite-check needed for actual plot 3 location relative to Tayasim St.",
      "ta_shetach_takanon": "3",
      "ta_shetach_submission": "ת.ש 3"
    }
  ],
  "validation_summary": {
    "schema_valid": true,
    "clause_ids_resolve_count": 5,
    "source_pages_in_range_count": 5,
    "bboxes_in_page_dims_count": 8,
    "confidence_enum_valid_count": 5,
    "compliance_enum_valid_count": 5,
    "plot_reconciliation_consistent": true
  }
}
```

## Pydantic schema

```python
class ExtractionValue(BaseModel):
    value: str                   # value as a string (preserves "10 floors", "450 m³", "compliant")
    unit: Optional[str]          # e.g. "floors", "m³", "m", "%"; None for qualitative
    raw_text_match: str          # snippet from the page that justifies the extraction

class EvidenceBbox(BaseModel):
    page: int                    # 1-indexed page number in 1..63
    bbox: List[float]            # [x1, y1, x2, y2] in PDF coords or rasterized px (consistent within doc)
    tag: Literal["primary", "supporting"]

class Finding(BaseModel):
    clause_id: str               # must resolve to a clause_id in canonical_clauses.json
    clause_text_excerpt: str     # first ~200 chars of clause text, for reviewer cross-reference
    extraction: ExtractionValue
    source_pages: List[int]      # 1-indexed pages cited
    evidence_bboxes: List[EvidenceBbox]
    confidence: Literal["high", "medium", "low"]
    compliance_indicator: Literal["compliant", "non_compliant", "requires_review", "missing", "deferred_to_dwg"]
    compliance_reasoning: str    # 1-3 sentences explaining the indicator
    ta_shetach_takanon: Optional[str]    # e.g. "3" — null for plan-level clauses
    ta_shetach_submission: Optional[str] # e.g. "ת.ש 3" — preserves submission label

class PlotMapping(BaseModel):
    submission_label: str        # verbatim as printed: "ת.ש 52", "מתחם 1", etc.
    takanon_plot: Optional[str]  # "1"–"10", "20", or None if unmappable
    confidence: Literal["high", "medium", "low"]
    evidence_pages: List[int]
    rationale: str               # how the model arrived at the mapping

class PlotReconciliation(BaseModel):
    method: Literal["auto"]
    mappings: List[PlotMapping]
    unreconciled_submission_labels: List[str]   # labels seen but not mapped
    unreconciled_takanon_plots: List[str]       # takanon plots not referenced anywhere

class VisionFindings(BaseModel):
    project_id: str
    submission_id: str
    extractor_version: str = "m2-v1"
    extracted_at: str
    model: str = "gemini-2.5-pro"
    input_refs: Dict[str, str]
    plot_reconciliation: PlotReconciliation
    findings: List[Finding]
    validation_summary: Dict[str, Any]
```

## Architecture

**Single Gemini 2.5 Pro call.** 1M-context window comfortably fits:
- 63 page images (rasterized at 200 DPI; estimated 1.5K-2K tokens per page after Pro's internal resize ⇒ ~100-130K image tokens)
- All N requested clause texts (~3-10K tokens for a 5-clause slice; ~50-80K for the full 93-normative run)
- M1 manifests for context (~30K tokens for all 63)
- Prompt + plot-reconciliation instructions (~5K)

**Total budget at full scale:** ~250-300K tokens input, 50-100K output. Comfortably within 1M.

**Why single-call (vs M1's per-page Flash calls):**
- The model needs cross-page context to do plot reconciliation (correlating "ת.ש 52" on page 8 with "מבני ציבור" labels on page 14).
- Many clauses require cross-page evidence (a building-height clause references both elevations AND cross-sections AND site plans).
- Pro's reasoning is better suited for multi-evidence synthesis than Flash.
- One call = one cost line item, easier to budget.

**Failure modes and mitigations:**
- **JSON truncation** (thinking tokens exhaust output): mirror M1's `MAX_JSON_RETRY=2` pattern.
- **Quota 429**: GeminiKeyRotator handles fallover to backup keys.
- **Image read failure** (rare): re-rasterize at lower DPI on retry.
- **Schema validation fails** (extra fields, missing required): treat as hard error, no auto-retry — surface the error and stop.

**Incremental save:** Pro is single-call so there's no per-clause checkpointing; on success the full JSON is written atomically (`write-then-rename`). On failure, no partial state is persisted (the call either returned a complete response or didn't).

**API key rotation:** same as M0/M1 — read `GEMINI_API_KEY*`, filter non-empty, rotate on 429.
**Model:** `gemini-2.5-pro` (paid tier required for 1M context + reasonable speed).
**Temperature:** 0.0 (deterministic for reproducibility).
**Max output tokens:** 65536 (full slice could emit 100+ findings each ~500 tokens; thinking budget consumes additional).

## Plot reconciliation (Step 0 in prompt)

Before extracting per-clause findings, the prompt instructs Pro to:
1. Scan all 63 page manifests for plot labels.
2. Distinguish the three numbering schemes by spelling:
   - Takanon scheme: bare integers 1-10 or 20 paired with "תא שטח" / "מגרש" prefix in the takanon (M0's clause text references)
   - Design-doc scheme: integers ≥30 paired with "ת.ש" / "ת.ש." / "ת״ש" abbreviation prefix
   - שצ"פ structure: "מתחם N" labels (sub-zones of שצ"פ, not plots per se)
3. Use page-level co-occurrence + label context to map design-doc labels onto takanon plots when possible (e.g., a "ת.ש 52" page that talks about "מבני ציבור + מסחר" likely maps to whichever takanon plot is designated for public buildings).
4. Mark any label it cannot confidently map as `unreconciled_submission_labels`.
5. Mark any takanon plot with no submission evidence as `unreconciled_takanon_plots`.

The plot reconciliation table is emitted FIRST in the response, then findings reference it via `ta_shetach_takanon` and `ta_shetach_submission`.

## Confidence calibration

Every `Finding.confidence` is one of `high` / `medium` / `low`:
- **high** — value is explicitly printed on a single page with unambiguous units and clear plot scope.
- **medium** — value is derived from multi-page synthesis (e.g., reading floor count off a section drawing's floor ladder), or scope is inferred from context rather than stated.
- **low** — extraction relies on visual estimation, drawing interpretation, or partial labels. Caller (M4) should treat low-confidence findings as `requires_review` regardless of the `compliance_indicator`.

Downstream (M4) decides thresholds — M2 simply tags.

## Extraction prompt

(Full prompt is in `vision_scanner/unified_extraction/prompts/m2_v1.txt`. Key structure:)

```
You are extracting compliance evidence from an Israeli urban planning design submission
(תכנית עיצוב) against the project's binding regulation (תקנון של תב"ע).

INPUTS:
- Takanon clauses to extract evidence for: <JSON of N clause objects>
- M1 page manifests (what's on each page): <JSON of 63 manifests>
- Page images: <inline PNGs, pages 1-63>

STEP 0 — PLOT RECONCILIATION
  Build the PlotMapping table per the spec. Three numbering schemes coexist:
  • Takanon: 1–10, 20 (integers, "תא שטח N" or "מגרש N")
  • Design-doc cadastral: "ת.ש 52", "ת.ש 64", etc. (≥30 with abbreviation prefix)
  • שצ"פ structure: "מתחם 1/2/3"

STEP 1 — PER-CLAUSE EXTRACTION
  For each clause:
    1. If the clause is per-plot (text mentions "תא שטח" or has plot-specific table rows),
       emit one Finding per applicable plot scope.
    2. If the clause is plan-level (applies to the whole project), emit a single Finding
       with ta_shetach_takanon=null.
    3. Cite the SPECIFIC source_pages where evidence is visible. Use the M1 manifests to
       locate candidate pages quickly, then verify by inspecting the image.
    4. evidence_bboxes — at least one "primary" bbox per finding (where the value is
       most clearly visible). bbox coords are in the rasterized image's pixel space.
    5. compliance_indicator — your best HINT for M4:
       • "compliant"          — value satisfies the clause
       • "non_compliant"      — value violates the clause
       • "requires_review"    — borderline / multi-interpretation / human judgment needed
       • "missing"            — submission has no evidence on this clause
       • "deferred_to_dwg"    — value depends on a DWG-only artifact (e.g., precise setback
                                 measurements that PDF doesn't show)
    6. confidence — high/medium/low per the spec.
    7. raw_text_match — the SHORT snippet from the page that justified the extraction.

RULES:
  • Preserve Hebrew labels verbatim — no translation in ta_shetach_submission.
  • If a clause is plan-level but has per-plot evidence, prefer one finding with the
    aggregated value rather than 10 per-plot duplicates.
  • Do not invent values. If you cannot find evidence, set compliance_indicator="missing"
    with confidence="high" (you are confident there's no evidence) and an empty source_pages list.
  • If reconciliation gives a confident plot mapping, use the takanon plot number in
    ta_shetach_takanon AND the verbatim submission label in ta_shetach_submission.
```

## Test slice methodology

**Slice 1 — 5 clauses.** First-pass check that:
- The prompt produces well-formed JSON
- Plot reconciliation actually fires
- Compliance indicators are calibrated reasonably
- Bbox coordinates are usable
- Confidence labels distinguish high/medium/low cases

Selection criteria for the 5 clauses: each must exercise a distinct extraction failure mode (numeric building-rights, parking ratio, qualitative architectural, stormwater calc, declarative POS). See `m2_test_slice_verification.md` for actual selections.

**Slice 2 — 15 clauses.** After slice-1 sign-off. Adds: edge cases, multi-plot clauses, clauses spanning multiple page types.

**Full run — ~93 clauses.** After slice-2 sign-off. Single Pro call.

**STOP conditions between slices:**
- Any automated validation check fails
- Self-verify finds >20% of findings incorrect
- Plot reconciliation rate <60%
- Confidence calibration is inverted (low-confidence findings are correct, high-confidence are wrong)

## Validation

**Automated (extractor fails non-zero exit on any fail):**

1. JSON validates against the Pydantic `VisionFindings` schema
2. Every `Finding.clause_id` resolves to a `clause_id` in `canonical_clauses.json`
3. Every `Finding.source_pages` entry is in `[1, 63]`
4. Every `EvidenceBbox.page` is in `[1, 63]` and bbox coords are within the rasterized page dimensions
5. Every `Finding.confidence` is in `{high, medium, low}`
6. Every `Finding.compliance_indicator` is in `{compliant, non_compliant, requires_review, missing, deferred_to_dwg}`
7. `plot_reconciliation` is consistent: every `ta_shetach_submission` referenced by a Finding appears in either `mappings` or `unreconciled_submission_labels`

**Manual (Claude Code self-verify, per slice):**
- For each Finding: rasterize the cited `source_pages` at 200 DPI
- View each PNG with Claude's vision
- Confirm the extracted `value` is actually visible at the `bbox`
- Confirm `compliance_indicator` is consistent with the value + clause
- Confirm `confidence` is calibrated correctly

## CLI

`vision_scanner/unified_extraction/run.py`:

```
--project-id PLAN_ID         (required)
--submission-id SUB_ID       (required, e.g. v24.3)
--source-pdf PATH            (required)
--canonical-clauses PATH     (required, M0 output)
--page-manifests PATH        (required, M1 output)
--output PATH                (required)
--clauses SPEC               (optional: "5.1.1,6.4.2,..." or "all-normative"; default "all-normative")
--raster-dpi INT             (optional: default 200)
--print-samples              (prints first 3 findings to stdout)
```

## Files this milestone creates

| Path | Purpose |
|---|---|
| `docs/m2_unified_extraction_spec.md` | This spec |
| `vision_scanner/unified_extraction/__init__.py` | Subpackage |
| `vision_scanner/unified_extraction/schema.py` | Pydantic models |
| `vision_scanner/unified_extraction/extract.py` | Pro 1M-context extraction |
| `vision_scanner/unified_extraction/validate.py` | 7 automated checks |
| `vision_scanner/unified_extraction/run.py` | CLI entry point |
| `vision_scanner/unified_extraction/prompts/m2_v1.txt` | Prompt template |
| `data/projects/407-1048248/submissions/v24.3/vision_findings.json` | Output (after full run + lock) |
| `data/projects/407-1048248/submissions/v24.3/vision_findings.run_log.jsonl` | Run history |
| `data/projects/407-1048248/submissions/v24.3/m2_test_slice_verification.md` | Per-slice audit |
| `.gitignore` patch | `!data/projects/*/submissions/*/vision_findings.json` |

## Acceptance criteria for M2

1. All 93 normative clauses have ≥1 Finding (per-plot or plan-level as appropriate)
2. All 7 automated validation checks pass
3. Plot reconciliation rate ≥80% (at most 20% of submission labels unmapped)
4. Self-verify on a 10-clause random sample shows ≥80% correct
5. Lior approved each slice (5 → 15 → 93)
6. Source PDF, M0, and M1 sha256s in `input_refs` match the on-disk files
7. Committed to `phase-3-vision`
