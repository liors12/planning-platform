# M0: Clause Inventory Specification — Plan 407-1048248

**Status:** approved by Lior 2026-05-23. v1.
**Owner:** vision_scanner package.

## Purpose

Build `canonical_clauses.json` listing every identifiable clause in the approved takanon. Feeds Phase 3 vision pipeline (completeness verification) and gap analysis (which clauses the 146 existing engine rules already cover).

## Scope

**In:**
- All clauses in `data/projects/407-1048248/source-documents/takanon.pdf` (20 pages, leishur canonical, file sha256 starts `17ccdf1448ef8de1*`, text_sha256 prefix `c5310165*` (computed by the M0 extractor with `<<PAGE N>>` markers; locked at first run))
- Section headers WITHOUT operative content ARE included as clauses (with `is_normative=false`, `is_quantitative=false`). Reason: child clauses' `parent_id` must reference an existing clause; skipping headers breaks the hierarchy
- §5 building rights table as ONE structured clause with nested rows + footnotes

**Out (for M0):**
- `tashrit_proposed.pdf` (spatial — DWG path unresolved)
- `decisions/decisions.pdf` (committee decisions, not regulatory)
- Mapping inventory clauses to existing engine rules (separate post-M0 pass)

## Output

**Path:** `data/projects/407-1048248/canonical_clauses.json`

**Gitignore exception:** add line `!data/projects/*/canonical_clauses.json` to `.gitignore` AFTER the existing `data/` ignore line, so this specific filename pattern is tracked despite `data/` being ignored.

**Top-level schema:**
```json
{
  "plan_id": "407-1048248",
  "source_doc": "takanon.pdf",
  "source_doc_sha256": "<sha256 of takanon.pdf bytes>",
  "source_doc_text_sha256": "<sha256 of extracted text>",
  "extracted_at": "<ISO-8601 UTC>",
  "extractor": "gemini-2.5-pro",
  "extractor_version": "m0-v1",
  "page_count": 20,
  "clauses": [/* ... */]
}
```

**Default clause schema:**
```json
{
  "clause_id": "4.1.2.א.4",
  "parent_id": "4.1.2.א",
  "section_title_chain": ["יעודי קרקע ושימושים", "מגורים ד'", "הוראות", "בינוי ו/או פיתוח"],
  "clause_text": "מרחק מינימלי בין מבנים לא יפחת מ-9 מ' כולל מרפסות.",
  "page": 13,
  "category": "building_geometry",
  "is_quantitative": true,
  "is_normative": true
}
```

**§5 table — special structured clause shape:**
```json
{
  "clause_id": "5.table",
  "parent_id": "5",
  "section_title_chain": ["טבלת זכויות והוראות בניה - מצב מוצע"],
  "clause_text": "Building rights table — see structured_values",
  "page": 16,
  "category": "building_rights",
  "is_quantitative": true,
  "is_normative": true,
  "structured_values": [
    {
      "ta_shetach": 1,
      "use": "מגורים",
      "plot_area_m2": 5197,
      "primary_area_m2": 20616,
      "service_area_above_m2": 9278,
      "service_area_below_m2": 17660,
      "total_built_m2": 47554,
      "units": 232,
      "max_height_m": 49,
      "floors_above": 14,
      "floors_below": 4,
      "setbacks": "per tashrit",
      "balcony_area_m2": 2784,
      "cell_footnote_refs": [1, 2]
    }
  ],
  "general_footnotes": [
    {"id": "5.note.א", "text": "..."},
    {"id": "5.note.ב", "text": "..."},
    {"id": "5.note.ג", "text": "..."},
    {"id": "5.note.ד", "text": "..."}
  ],
  "cell_footnotes": [
    {"id": 1, "text": "..."},
    {"id": 2, "text": "..."},
    {"id": 3, "text": "..."},
    {"id": 4, "text": "..."}
  ]
}
```

## Categories (controlled vocabulary — exactly 15 values)

`identification`, `objectives`, `land_use_zoning`, `building_geometry`, `building_rights`, `building_use`, `parking`, `infrastructure`, `stormwater`, `tree_preservation`, `unification_subdivision`, `public_areas`, `easements`, `building_height_safety`, `phasing`, `procedural`

## Extraction approach

**Stack:** PyMuPDF text extraction → Gemini 2.5 Pro single call with `response_schema` constraint.

**Pipeline:**
1. `fitz.open(takanon.pdf)` → extract text per page
2. Concatenate with `<<PAGE N>>` markers between pages
3. Compute file sha256 + text sha256 for the metadata block
4. Single Gemini Pro call with `response_schema=ClausesSchema` (Pydantic → schema)
5. JSON-schema validate the response
6. Run automated validation (§Validation below)
7. Write to JSON file
8. Append run record to `data/projects/407-1048248/canonical_clauses.run_log.jsonl`

**API key rotation (`vision_scanner/config.py`):**
Read these env vars in order, filter non-empty, rotate on 429:
1. `GEMINI_API_KEY` (primary)
2. `GEMINI_API_KEY_BACKUP_1`
3. `GEMINI_API_KEY_BACKUP_2`
4. `GEMINI_API_KEY_BACKUP_3`

**Extraction prompt:**
```
You are extracting clauses from an Israeli urban planning regulation
document (תקנון של תב"ע) in Hebrew.

The document is divided into numbered sections (1, 2, 3...), subsections
(1.1, 4.1.2...), lettered subsections (א, ב, ג), and numbered points.

For EVERY identifiable clause, emit one JSON object per the schema.

CRITICAL RULES:
1. Preserve Hebrew text faithfully — no translation, no paraphrasing,
   no summarization. clause_text is verbatim from the source.
2. clause_id reflects hierarchy: "4.1.2.א.4" means section 4 → 4.1 →
   4.1.2 → letter א → item 4
3. category MUST be from this exact list (15 values):
   [identification, objectives, land_use_zoning, building_geometry,
    building_rights, building_use, parking, infrastructure, stormwater,
    tree_preservation, unification_subdivision, public_areas, easements,
    building_height_safety, phasing, procedural]
4. is_quantitative=true ONLY when clause text contains a checkable
   number/threshold (e.g., "9 מטרים", "75%", "5 קומות"). false for
   text-only or descriptive content.
5. is_normative=true when the clause imposes a requirement
   (allow/forbid/must/shall). false for identification, description,
   or pure section headers without operative content.
6. Section headers WITHOUT operative content ARE clauses with both
   is_normative=false and is_quantitative=false. They are needed so
   child clauses' parent_id references resolve.
7. For the §5 building rights table (around page 16): emit ONE clause
   with clause_id="5.table" containing nested structured_values array
   + general_footnotes (lettered notes א-ד) + cell_footnotes (numbered 1-4).
8. page is 1-indexed from <<PAGE N>> markers.
9. parent_id is the immediate parent (e.g. parent of "4.1.2.א.4"
   is "4.1.2.א", parent of "4.1.2.א" is "4.1.2"). null for top-level
   (sections 1-7).

OUTPUT: {clauses: [...]}
```

## Validation

**Automated (extractor fails non-zero exit if ANY fail):**

1. JSON output validates against the Pydantic schema
2. Every `clause_text` is non-empty (after `.strip()`)
3. Every `clause_id` is unique within the inventory
4. Every `parent_id` is either `null` OR references an existing `clause_id` in the inventory
5. Every `page` is in `[1, page_count]`
6. Every `category` is in the 15-value controlled vocabulary
7. `5.table` clause exists; `structured_values` has ≥ 5 rows (plots 1-5, possibly plot 9); `general_footnotes` has ≥ 4 entries (notes א-ד)
8. Total clause count is in `[70, 200]` — tightened from initial [50, 300] per Lior's review

**Manual (Lior performs after automated checks pass):**

Extractor prints to stdout in this exact order:
1. 10 randomly-sampled clauses (full record)
2. ALL of §5 (the `5.table` clause in pretty-printed JSON)
3. ALL clauses of §6 (sections 6.1 through 6.7, full records)

Leishur version: §6 has 7 subsections (deposit version had 9; restructured per public objections).

Lior eyeballs faithfulness against the PDF. Estimated time: 45 minutes. If any clause shows translation/paraphrase/hallucination → file an issue, iterate prompt, re-run.

## Re-run policy

- Extractor is mostly-idempotent (small LLM variance is acceptable)
- Re-run triggers:
  - Takanon PDF changes (sha256 mismatch with metadata block)
  - Schema or controlled vocabulary changes
  - Prompt improvements (logged in run_log)
  - Validation tightening
- Each run appends one JSON line to `canonical_clauses.run_log.jsonl` with: `{ts, model, source_sha256, validation_result, clause_count, prompt_version}`

## Acceptance criteria for M0

1. `canonical_clauses.json` exists at the spec'd path with valid JSON
2. All 8 automated validation checks pass (exit 0)
3. Lior manual spot-check on 10 random + ALL of §5 + ALL of §6 (≈45 min review) → all faithful, no translation, no hallucination
4. `source_doc_sha256` in the JSON matches the canonical leishur file hash
5. Committed to `phase-3-vision` branch with commit message: `feat(m0): clause inventory for plan 407-1048248`

## Files this milestone creates

| Path | Purpose |
|---|---|
| `docs/m0_clause_inventory_spec.md` | This spec |
| `vision_scanner/__init__.py` | Package init |
| `vision_scanner/config.py` | Env reader + key rotation |
| `vision_scanner/clause_inventory/__init__.py` | Subpackage init |
| `vision_scanner/clause_inventory/schema.py` | Pydantic models |
| `vision_scanner/clause_inventory/extract.py` | Main extractor |
| `vision_scanner/clause_inventory/validate.py` | 8 automated checks |
| `vision_scanner/clause_inventory/run.py` | CLI entry point |
| `data/projects/407-1048248/canonical_clauses.json` | OUTPUT (after Lior approval) |
| `data/projects/407-1048248/canonical_clauses.run_log.jsonl` | Run history |
| `.gitignore` patch | Add `!data/projects/*/canonical_clauses.json` |

## Out of scope

- Mapping inventory clauses to engine rules → post-M0
- Extracting from tashrit (DWG) → blocked on libredwg path
- Extracting from decisions.pdf → not regulatory, low priority
- Multi-project generalization → the code IS project-keyed, but only run against 407-1048248 in M0
