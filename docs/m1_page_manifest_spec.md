# M1: Per-Page Vision Manifest Specification — Submission v24.3

**Status:** approved by Lior 2026-05-23. v1.
**Owner:** vision_scanner.page_manifest package.
**Dependencies:** M0 locked at commit `08f2a1a`.

## Purpose

For each page of the architect submission, produce a structured manifest of what's on the page. Feeds M2 (unified extraction). NOT a compliance check — a "what's here?" pass to route M2's attention.

## Scope

**In:**
- Every page of `projects/407-1048248/submissions/v24.3/v24.3.pdf` (63 pages)
- Visual identification: page type, plot references, labels, dimensions, tables, diagrams, quality flags
- Output structured to feed M2

**Out (for M1):**
- Compliance checking — that's M4
- Clause-ID matching per page — that's M2
- Mapping submission to canonical_clauses.json — that's M2
- Numeric value extraction beyond visible dimensions — that's M2

## Output

**Path:** `data/projects/407-1048248/submissions/v24.3/page_manifests.json`

**Gitignore exception:** add `!data/projects/*/submissions/*/page_manifests.json` to `.gitignore`. Other files in `submissions/` stay ignored.

## Top-level schema

```json
{
  "plan_id": "407-1048248",
  "submission_id": "v24.3",
  "source_pdf": "v24.3.pdf",
  "source_pdf_sha256": "<sha256>",
  "extracted_at": "<ISO-8601 UTC>",
  "extractor": "gemini-2.5-flash",
  "extractor_version": "m1-v1",
  "page_count": 63,
  "page_numbers_processed": [1, 5, 15, 30, 45],
  "manifests": [/* PageManifest items */]
}
```

## PageManifest schema

```json
{
  "page_number": 12,
  "page_type": "site_plan_per_ta_shetach",
  "ta_shetach_refs": [1],
  "visible_text_labels": ["מגרש 1", "פיתוח", "כניסה ראשית"],
  "visible_dimensions": [
    {"value": 9, "unit": "m", "context": "min distance between buildings"},
    {"value": 49, "unit": "m", "context": "building height"}
  ],
  "tables_present": [
    {"title": "טבלת חניות", "estimated_rows": 5}
  ],
  "diagrams_present": [
    {"type": "site_plan", "description": "Top-down view of plot 1"}
  ],
  "page_quality": "ok"
}
```

## Controlled vocabulary

**page_type (15 values):**
`cover`, `table_of_contents`, `summary`, `site_plan_per_ta_shetach`, `waste_diagram`, `functions_diagram`, `daycare`, `basement_with_parking_table`, `typical_floor`, `cross_section`, `elevation`, `public_open_space`, `rendering`, `legend_or_key`, `other`

**page_quality (5 values):**
`ok`, `illegible`, `incomplete`, `draft`, `blank`

## Extraction pipeline

1. PyMuPDF rasterize each requested page at 300 DPI → in-memory PNG bytes
2. Send PNG to Gemini Flash with text prompt + `response_schema=PageManifest`
3. Validate response against Pydantic schema
4. Aggregate into top-level structure
5. Write JSON, append to run_log

**API key rotation:** same as M0 — read `GEMINI_API_KEY*`, filter non-empty, rotate on 429.
**Model:** `gemini-2.5-flash` (free tier).

## Extraction prompt

```
You are analyzing a single page from an Israeli urban planning design document (תכנית עיצוב) in Hebrew.

This document type follows a standard structure where each plot (תא שטח) has up to 6 page types repeating: site plan (פיתוח), waste diagram (דיאגרמת אשפה), functions diagram (דיאגרמת פונקציות), daycare (מעונות יום), basement+parking table (מרתף), typical floor (קומה טיפוסית). Plus document-level pages: cover, summary, cross-sections (חתכים), elevations (חזיתות), public open space (שצ"פ), renderings (הדמיות).

Analyze the page image and produce a structured manifest:

1. page_type — pick ONE from this exact list (15 values):
   cover, table_of_contents, summary, site_plan_per_ta_shetach, waste_diagram, functions_diagram, daycare, basement_with_parking_table, typical_floor, cross_section, elevation, public_open_space, rendering, legend_or_key, other.

2. ta_shetach_refs — array of plot numbers (1-9) this page references. Look for labels like "מגרש X", "תא שטח X", or "תא X". Empty array if no specific plot reference.

3. visible_text_labels — 5-15 prominent Hebrew labels (titles, callouts, area names, key terms). Not every word; just the important ones a reader would notice first.

4. visible_dimensions — array of measurements with units. Each: {value: number, unit: string ("m", "m²", "cm"), context: 1-3 words}.

5. tables_present — array of tables on the page: {title: string, estimated_rows: integer}.

6. diagrams_present — array of drawings: {type: string (site_plan/floor_plan/section/elevation/diagram), description: 1-2 sentence}.

7. page_quality — one of: ok, illegible, incomplete, draft, blank.

RULES:
- Preserve Hebrew text — no translation
- Numbers are numeric values, not text
- Do not hallucinate — describe only what you see
- When ambiguous: prefer "other" + low-detail over confident guesses
- page_quality="draft" only if a visible "DRAFT/טיוטה" marker is present
```

## Test slice (per iteration principle)

**First run: pages 1, 13, 26, 39, 52 only.** These are evenly spread across 63 pages and likely hit diverse content (cover, mid-doc plot pages, end-of-doc renderings/elevations).

Validation steps:
1. Generate manifests for the 5 pages only
2. Write to `data/projects/407-1048248/submissions/v24.3/page_manifests.tmp.json` (NOT .json)
3. Print each manifest to stdout (pretty-printed JSON)
4. Stop for Lior validation
5. Lior approves OR points out issues
6. If issues: iterate prompt, re-run 5 pages
7. If approved: scale to all 63 (run --pages all)

## Validation

**Automated (extractor fails non-zero exit on any fail):**

1. JSON validates against the Pydantic schema
2. Every requested page has a manifest
3. No duplicate page_numbers in manifests
4. Every page_number is in [1, page_count]
5. Every page_type is in the 15-value vocabulary
6. Every page_quality is in the 5-value vocabulary
7. visible_text_labels has ≥ 1 entry unless page_quality is "blank"

**Manual (Lior, 5 pages = ~5 min):**
- Open the 5 PDF pages side-by-side with their manifests
- Verify page_type matches reality
- Verify ta_shetach_refs is correct
- Spot-check visible_dimensions against the page
- Approve or flag issues

## CLI

`vision_scanner/page_manifest/run.py`:

```
--project-id PLAN_ID         (required)
--submission-id SUB_ID       (required, e.g. v24.3)
--source-pdf PATH            (required)
--output PATH                (required)
--pages SPEC                 (optional: "1,13,26,39,52" or "all", default "all")
--print-samples              (prints manifests to stdout)
```

## Files this milestone creates

| Path | Purpose |
|---|---|
| `docs/m1_page_manifest_spec.md` | This spec |
| `vision_scanner/page_manifest/__init__.py` | Subpackage |
| `vision_scanner/page_manifest/schema.py` | Pydantic models |
| `vision_scanner/page_manifest/extract.py` | Main extractor |
| `vision_scanner/page_manifest/validate.py` | Automated checks |
| `vision_scanner/page_manifest/run.py` | CLI entry point |
| `data/projects/407-1048248/submissions/v24.3/page_manifests.json` | Output (after full run + lock) |
| `data/projects/407-1048248/submissions/v24.3/page_manifests.run_log.jsonl` | Run history |
| `.gitignore` patch | `!data/projects/*/submissions/*/page_manifests.json` |

## Acceptance criteria for M1

1. All 63 pages have manifests in the final JSON (after scale step)
2. All 7 automated validation checks pass
3. Lior approved the 5-page test slice
4. Source PDF sha256 in metadata matches `v24.3.pdf` on disk
5. Committed to `phase-3-vision`
