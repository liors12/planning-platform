# Planning Compliance Platform — Architecture Context
**For Claude Code. Read this before writing any code.**
Last updated: March 2026

---

## What This System Does

Two things:
1. **Checks submitted תכניות בינוי ופיתוח** (architect-submitted PDFs + DWGs) against approved תב"ע rules
2. **Generates draft חוות דעת מהנדס הוועדה המקומית** — the official compliance opinion Ellen signs

Every AI output is a draft. A licensed professional reviews and signs before any document is used.

---

## Critical Architecture Principles

### 1. Everything is project-keyed
No rules are hard-coded. Every rule, plot, extract, and violation belongs to a `project_id`. The pilot is plan 407-0977595 (מתחם הטייסים). Future plans load the same way — no code changes.

### 2. Two-axis versioning
Two independent things can change between runs:
- `submission_version` — the architect submitted corrected files (new PDF, new DWG)
- `engine_version` — the compliance engine was improved (same files, better analysis)

Every compliance run is identified by `(submission_id, engine_version)`. This is stored in the `engine_runs` table. Violations link to `engine_run_id`, not just `submission_id`.

### 3. Files are immutable once uploaded
When an architect submits files, they go to storage and never change. Re-runs use the same file keys. A new submission_version means new files.

### 4. Rules engine is deterministic for 80% of checks
Quantitative, geometric, document_presence, and procedural rules are pure Python — no AI. Claude API is only called for qualitative RAG checks and stormwater extraction.

### 5. Evidence-first
Every extracted value carries a unified evidence bundle. Every violation links to an extract with evidence. This is the legal defense in appeal proceedings.

---

## Rule Taxonomy (5 types — use these exactly)

| type | examples | engine | evidence |
|---|---|---|---|
| `numeric` | max 235 units, max height 50m, min setback 9m | Python comparison | extracted_value, page, cell_text |
| `geometric` | setback ≥9m between buildings, top-floor setback ≥3m | Shapely .distance() | nearest_points, polygon coords |
| `document_presence` | רת"א approval, tree survey, asbestos survey | EXISTS check in submissions | document type, filename |
| `procedural` | scale 1:250 required, demolition sequence marked | metadata check | page metadata, title block text |
| `qualitative` | architectural character, landscape quality | Claude RAG | retrieved תקנון chunk, confidence |

---

## Violation Statuses (7 states — not binary pass/fail)

**Canonical enum (post 2026-05-01 harmonization).** The earlier 7-state list
(`pass`, `fail`, `low_confidence`, `needs_clarification`, `input_missing`,
`cannot_determine`, `suppressed_by_override`) is **retired** — it conflated
verdict state, extraction confidence, and override status into a single
field. The new design separates these cleanly:

- **Verdict** describes only the outcome of the rule check itself.
- **Extraction confidence** is a per-extract numeric value on the
  `extracts` table — nothing to do with verdict.
- **Override status** is tracked as the boolean `is_override_applied`
  column on `violations` (and as `is_overridden` on the in-memory `Rule`
  + `Violation` dataclasses). Not a verdict state.

The `Verdict` enum lives in `src/compliance/types.py` and is the single
source of truth for both the in-memory dataclass (`Violation.verdict`)
and the persisted column (`violations.verdict`, with a CHECK constraint
that lists exactly these seven strings):

```python
class Verdict(str, Enum):
    PASS              = "pass"              # rule satisfied, hard match
    PASS_WITH_NOTE    = "pass_with_note"    # satisfied but reviewer should see context
                                            # (e.g. value within tolerance band of threshold)
    FAIL              = "fail"              # rule violated, clear case
    FAIL_BORDERLINE   = "fail_borderline"   # violated but within typical tolerance —
                                            # flag for reviewer rather than reject outright
    UNEVALUABLE       = "unevaluable"       # extracted data missing or extraction failed
    NOT_APPLICABLE    = "not_applicable"    # rule's applies_when condition not met
                                            # for this parcel
    REQUIRES_REVIEW   = "requires_review"   # qualitative rule — surfaces the question
                                            # to the human; no automated verdict
```

Override semantics: a Violation with `is_override_applied=True` means the
resolver applied a `project_rule_exceptions` row before evaluation; the
verdict still describes the *evaluated* outcome under the overridden
parameters. There is no separate "suppressed_by_override" verdict —
override status is one bit, the verdict is another.

---

## Unified Evidence Bundle (JSONB — attach to every extract)

```json
{
  "source_file": "תכנית_עיצוב_הטייסים.pdf",
  "page": 29,
  "region": "upper_box",
  "bbox": [120.5, 340.2, 480.8, 520.1],
  "excerpt": "232 חניות דיירים",
  "method": "pdfplumber",
  "confidence": 0.97,
  "reviewed_by": null
}
```

`bbox` coordinates are in PDF points (pt). Store them — they enable visual highlight in the review UI later.

---

## Database Schema (SQLite for local, PostgreSQL for server)

```sql
-- Root anchor. Everything joins through project_id.
CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  plan_number TEXT NOT NULL,
  approval_date DATE,
  status TEXT DEFAULT 'onboarding',
  active_takanon_version_id TEXT,
  plots_json TEXT,           -- JSON array of plot definitions
  scope_notes TEXT,          -- northern site exclusion language etc
  appeal_days INTEGER DEFAULT 30,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- When תקנון changes (amendment), create new version. Old submissions stay linked to old version.
CREATE TABLE takanon_versions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  version_label TEXT NOT NULL,   -- 'approved_2024-01-23'
  effective_date DATE NOT NULL,
  pdf_path TEXT,
  status TEXT DEFAULT 'draft',   -- draft|confirmed|superseded
  confirmed_by TEXT,
  confirmed_at TIMESTAMP
);

-- One row per architect file submission.
CREATE TABLE submissions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  version INTEGER NOT NULL,      -- increments per resubmission
  submitted_at TIMESTAMP,
  submitted_by TEXT,
  status TEXT DEFAULT 'pending', -- pending|processing|review|done
  documents_json TEXT            -- [{id, type, path, scale, pages}]
);

-- One row per compliance pipeline run. Key table for two-axis versioning.
CREATE TABLE engine_runs (
  id TEXT PRIMARY KEY,
  submission_id TEXT NOT NULL REFERENCES submissions(id),
  takanon_version_id TEXT NOT NULL REFERENCES takanon_versions(id),
  engine_version TEXT NOT NULL,  -- semver: '1.0.0'
  triggered_by TEXT,             -- 'auto'|'admin_rerun'|'resubmission'
  triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP,
  status TEXT DEFAULT 'queued',  -- queued|running|complete|failed|signed
  signed_by TEXT,
  signed_at TIMESTAMP
);

-- Compliance rules. Loaded from project-schema.json at onboarding.
CREATE TABLE rules (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  takanon_version_id TEXT NOT NULL REFERENCES takanon_versions(id),
  rule_code TEXT NOT NULL,       -- stable: 'HEIGHT_MAX_PLOT_1'
  rule_type TEXT NOT NULL,       -- numeric|geometric|document_presence|procedural|qualitative
  section TEXT,
  plot TEXT,                     -- 'plot_1'|'all'|NULL
  operator TEXT,                 -- '<=','>=','=','EXISTS','REGEX'
  threshold REAL,
  unit TEXT,
  source_quote TEXT,
  source_page INTEGER,
  extraction_confidence REAL,
  review_status TEXT DEFAULT 'pending',  -- pending|confirmed|disputed
  confirmed_by TEXT,
  confirmed_at TIMESTAMP,
  is_active INTEGER DEFAULT 1
);

-- Project-level rule overrides. Persists across engine runs.
-- Prevents engineer from confirming the same exception every single run.
CREATE TABLE project_rule_exceptions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  rule_id TEXT NOT NULL REFERENCES rules(id),
  plot TEXT,                     -- NULL = applies to all plots
  exception_type TEXT,           -- 'global_waiver'|'interpretation_change'|'measurement_method'
  notes TEXT NOT NULL,
  created_by TEXT NOT NULL,
  co_confirmed_by TEXT,          -- dual sign-off required
  valid_from_engine_version TEXT,
  expires_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Every value extracted from PDF or DWG.
CREATE TABLE extracts (
  id TEXT PRIMARY KEY,
  engine_run_id TEXT NOT NULL REFERENCES engine_runs(id),
  rule_code TEXT NOT NULL,
  plot TEXT,
  extracted_value REAL,
  extracted_text TEXT,
  unit TEXT,
  evidence_json TEXT NOT NULL,   -- unified evidence bundle (see above)
  confidence REAL NOT NULL,
  review_required INTEGER DEFAULT 0,
  review_reason TEXT
);

-- One row per compliance failure per engine run.
CREATE TABLE violations (
  id TEXT PRIMARY KEY,
  engine_run_id TEXT NOT NULL REFERENCES engine_runs(id),
  rule_id TEXT NOT NULL REFERENCES rules(id),
  extract_id TEXT REFERENCES extracts(id),
  severity TEXT NOT NULL,        -- critical|major|minor|info
  status TEXT DEFAULT 'open',    -- open|fixed|waived|suppressed_by_override|cannot_determine
  resolution_type TEXT,          -- fixed_by_architect|waived_by_engineer|deferred_to_permit
  verdict TEXT NOT NULL,         -- see 7 verdict states above
  submitted_value TEXT,
  required_value TEXT,
  correction_instruction TEXT,
  reference_pages TEXT,          -- JSON array of page numbers
  override_id TEXT REFERENCES project_rule_exceptions(id),
  human_override_by TEXT,
  human_override_at TIMESTAMP,
  human_override_reason TEXT
);

-- Generated חוות דעת PDFs.
CREATE TABLE generated_outputs (
  id TEXT PRIMARY KEY,
  engine_run_id TEXT NOT NULL REFERENCES engine_runs(id),
  output_type TEXT,              -- 'chavat_daat'|'violations_summary'|'diff_report'
  file_path TEXT,
  generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  signed_by TEXT,
  signed_at TIMESTAMP,
  is_final INTEGER DEFAULT 0
);

-- DWG layer mapping per (project, firm).
CREATE TABLE dwg_layer_configs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  firm_name TEXT NOT NULL,
  layer_name TEXT NOT NULL,
  category TEXT NOT NULL,        -- building_footprint|balcony|plot_boundary|public_open_space|road|annotation|unknown
  match_confidence REAL,
  confirmed_by TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Diff Engine Logic

```python
def diff_engine_runs(violations_old: list, violations_new: list) -> dict:
    codes_old = {v['rule_code'] for v in violations_old}
    codes_new = {v['rule_code'] for v in violations_new}
    return {
        'fixed':          [v for v in violations_old if v['rule_code'] not in codes_new],
        'still_open':     [v for v in violations_new if v['rule_code'] in codes_old],
        'newly_detected': [v for v in violations_new if v['rule_code'] not in codes_old],
    }
```

Works for both diff modes:
- Architect resubmission: same engine_version, different submission_version
- Engine improvement: same submission_version, different engine_version

---

## Tech Stack

| Component | Technology | Notes |
|---|---|---|
| Language | Python 3.11+ | |
| Web framework | FastAPI | Async, Pydantic models |
| Database | SQLite (local) | Upgrade to PostgreSQL when multi-user needed |
| PDF discovery | PyMuPDF (fitz) | Page search by keyword |
| PDF tables | pdfplumber | Primary. Camelot as narrow fallback |
| PDF OCR fallback | AWS Textract | Only if raster scan detected |
| DWG/DXF | ezdxf | Reads DXF. DWG needs conversion first |
| DWG conversion | libredwg or ODA | AC1018 → DXF |
| ממ"ג shapefiles | GeoPandas | ESRI .shp/.dbf/.shx in ITM (EPSG:2039). Authoritative parcel polygons. Phase 4. |
| ממ"ג georeferenced JPGs | rasterio | Reads .jpg + .jgw worldfile. Phase 4. |
| Geometry | Shapely + GeoPandas | setbacks, envelopes, distances |
| AI analysis | Claude API (Sonnet) | Qualitative RAG + stormwater extraction |
| Vector store | sqlite-vec or chromadb | pgvector when on PostgreSQL |
| PDF output | wkhtmltopdf + NotoSansHebrew (base64) | Hebrew RTL from HTML/CSS. See "Architectural Decisions → PDF rendering for Hebrew output". |
| Frontend | Minimal HTML/JS served by FastAPI | No React needed for MVP |
| File storage | Local filesystem | Cloudflare R2 when server-based |

---

## Architectural Decisions

### Design plan ↔ statutory plan: many-to-many

**Decision.** A single תכנית עיצוב (design plan) may be governed by multiple תב"עות (statutory plans). The data model treats this relationship as **many-to-many**, NOT 1:1. Each תא שטח (area cell) within the design plan declares which specific statutory plan governs it; the compliance engine resolves which rules apply on a per-cell basis.

**Why.** This isn't an edge case. It's how Ness Ziona urban renewal works: a developer's design proposal often spans the boundary of multiple approved statutory plans. The pilot is the canonical example — the Hetzeisim design plan (Kika Braz, revision 23.3, 23.2 dunams, 700 units) covers the boundary between two statutory plans:

- **407-0977595** — Hetzeisim, 16.5 dunams, 387 units, approved 2024-01-23 (`coverage_type: primary`)
- **407-1048248** — Hetzeisim North, 6.0 dunams, 220 units, currently staged awaiting תקנון (`coverage_type: partial`)

A 1:1 model would force us to either fragment the design plan into two project rows (loses the cross-cutting design analysis the architect actually delivered) or pick one תב"ע and ignore the other (produces compliance opinions that fail to cite the correct statutory basis for half the parcels). Neither is acceptable.

**Schema shape.**

1. **`projects` table** — one row per design plan. `plan_number` continues to hold the design plan's primary statutory plan number (the `coverage_type: primary` entry) for human-readable lookup. `id` remains a UUID.
2. **`takanon_versions` table** — one row per statutory plan version. Unchanged.
3. **`project_takanon_links` table (NEW)** — join table. Columns: `project_id` → `projects(id)`, `takanon_id` → `takanon_versions(id)`, `coverage_type` (`primary` | `partial` | `adjacent_reference`), `coverage_notes`. Unique on `(project_id, takanon_id)`.
4. **`rules` table** — already keyed by `takanon_version_id`. Unchanged.
5. **Project schema JSON** (`project-schema-*.json`) — restructured top-level: `design_plan` (id, name, architect, scope) + `linked_statutory_plans[]` (one entry per linked statutory plan, with `coverage_type` and `coverage_notes`). Each parcel in `parcels[]` carries `governing_takanon_id` (a plan_number string matching one of the `linked_statutory_plans[]` entries) so the engine knows which תב"ע's rules to evaluate against that cell.

**`coverage_type` enum.**

- `primary` — the design plan's main governing plan. Most תאי שטח are governed by this. Bookkeeping convention: `projects.plan_number` mirrors this entry.
- `partial` — covers some תאי שטח only. Their `governing_takanon_id` references this plan.
- `adjacent_reference` — needed for context (e.g., scope_out neighbors, infrastructure dependencies, §77–78 notices) but doesn't govern any תא שטח directly.

**What this enables.** The compliance engine can now resolve which statutory plan's rules apply to a given תא שטח and run the right per-cell checks. A חוות דעת for a design plan can correctly cite the statutory basis for each violation — drawing rules from 407-0977595 for the southern parcels, from 407-1048248 for the northern ones, from a third plan for any later expansion, etc.

**Implementation status (2026-05-01).** DDL added to [src/load_project.py](src/load_project.py) (`project_takanon_links` table). Pilot project schema restructured at [project-schema-407-0977595-v2.json](project-schema-407-0977595-v2.json) and mirror at [data/projects/407-0977595/project-schema.json](data/projects/407-0977595/project-schema.json). The loader's mapping logic (`insert_project`, `insert_takanon_version`, `insert_rules`) does NOT yet consume the new fields — it still ingests the existing `project` block as before. Wiring the loader to populate `project_takanon_links` and the per-parcel `governing_takanon_id` is a separate task, planned for once the schema stabilizes.

### PDF rendering for Hebrew output

**Decision.** All Hebrew PDF output will be generated via **HTML → wkhtmltopdf** with **NotoSansHebrew embedded as base64** inside the HTML's `<style>` block. The pipeline is: build HTML with `<html dir="rtl">`, inline the CSS at `src/pdf/styles/hebrew-rtl-base.css`, embed the font as a base64 `data:font/truetype;…` URL, then shell out to `wkhtmltopdf`.

**Rejected alternatives.**

- **ReportLab** — does not render Hebrew correctly. Confirmed by the battle-tested workspace skill `keyword-feasibility-report`.
- **WeasyPrint** — works but produces *visual-order* Hebrew that breaks copy-paste and search inside the resulting PDFs (per project memory from the תשריט analysis report). Selectable text comes back word-reversed.
- **Chrome headless `--print-to-pdf`** — same visual-order Hebrew problem as WeasyPrint. Already observed in this project: Hebrew renders correctly on screen but extracted text reverses multi-word phrases. Acceptable as a fallback for read-only deliverables; not acceptable for legal documents that must be searchable.

**Reference implementation.** [`keyword-feasibility-report` skill](file:///Users/liorlevin/Library/Application%20Support/Claude/local-agent-mode-sessions/skills-plugin/dbf57864-b078-4b9b-ade4-dd0387a945c1/c5f1e5d3-0167-477e-86c7-f2ed1b0fa231/skills/keyword-feasibility-report/SKILL.md) — proven Hebrew RTL PDF generation. CSS patterns, font-embedding strategy, and the `wkhtmltopdf` invocation flags are documented there. The CSS has been adapted to the NZC color palette and saved at [src/pdf/styles/hebrew-rtl-base.css](src/pdf/styles/hebrew-rtl-base.css).

**Implementation timing.** The PDF rendering module will be built when the first Hebrew PDF generation need actually arises — likely at **Phase 3** (חוות דעת draft generator). Until then, all intermediate outputs are Markdown. No `wkhtmltopdf` or `NotoSansHebrew` dependency is added to `requirements.txt` or `pyproject.toml` yet.

### Failure Mode Distinction

**Decision.** A `Violation` carries two orthogonal classification axes: **`verdict`** (what happened) and **`failure_mode`** (why it happened, only meaningful when `verdict == UNEVALUABLE`). The 7-state Verdict taxonomy stays unchanged; failure_mode is a separate enum with five values: `ENGINE_ERROR`, `MISSING_DATA`, `AMBIGUOUS_RULE`, `EXTRACTION_FAILURE`, and `NONE` (the default for every non-UNEVALUABLE verdict).

**Why.** Without the second axis, every "I can't tell" outcome — an evaluator that crashed, a submission missing a field, a rule whose definition is unclear — collapses into a single UNEVALUABLE bucket. When an engineer reviewing a real submission sees 30 UNEVALUABLE rows, they have no way to triage: are these the architect's problem (incomplete submission), the engine team's problem (bug in the evaluator), or the rules team's problem (ambiguous rule)? Each requires a different escalation path and a different conversation. Treating the cause as a first-class field forces evaluators to declare it explicitly and lets the PDF generator route the engineer's attention accordingly.

The five values:

- **`ENGINE_ERROR`** — the evaluator raised an uncaught exception. Set by the dispatcher's try/except wrapper in `evaluate_parcel`. The system, not the architect, is the problem; this is a ticket for the engine team.
- **`MISSING_DATA`** — the rule asked for a field the extracted data did not provide. Set by individual evaluators when their lookup key is absent. Either the architect's submission is incomplete OR the extractor missed the field — either way it's a real submission gap and the engineer should ask the architect or re-run extraction.
- **`AMBIGUOUS_RULE`** — the rule's own definition is unclear or unparseable (e.g. numeric rule with neither operator nor threshold; range rule missing min/max). Set by individual evaluators when the rule itself can't be interpreted. The rule needs editing before it can be evaluated.
- **`EXTRACTION_FAILURE`** — a value WAS produced but the extractor flagged it as unreliable. Reserved for the extraction layer to populate (no current evaluators emit this; the slot exists so we don't have to widen the enum later).
- **`NONE`** — default. Used for every non-UNEVALUABLE verdict to make the "this field has no signal here" state explicit at the type level (rather than nullable).

**`error_fingerprint`.** Companion field — a stable 16-char sha256 prefix used to **cluster identical failures**. The dispatcher computes it from the exception type + first 200 chars of the message; per-evaluator missing-data paths compute it from the missing field name. Two violations that hit the same `KeyError("x")` share a fingerprint; two violations that hit different exceptions don't. The persistence layer's `summary_stats_json` exposes both `by_failure_mode` (run-level breakdown by all 5 modes) and `error_fingerprint_clusters` (fingerprint → count, sorted by descending count).

**PDF generator behaviour.** When `engine_error` count > 0 at the run level, the executive summary displays a system-health warning (אזהרת מערכת) explicitly stating the run may be incomplete and that engine-team review is required before sign-off. When the same `error_fingerprint` appears ≥3 times across the run, the per-parcel findings table folds 2+ same-fingerprint rows in a single parcel into one cluster banner ("N כללים נכשלו עם אותה שגיאה") instead of repeating the same row N times. When a UNEVALUABLE row is rendered individually, its Hebrew failure-mode label appears inline next to the verdict pill so the engineer immediately distinguishes "missing data" from "system error".

**What this is NOT.** failure_mode does not change the verdict taxonomy — UNEVALUABLE remains a single verdict outcome. failure_mode does not introduce automatic recovery (engine errors still produce UNEVALUABLE, the change is only metadata). And failure_mode is meaningless for verdicts other than UNEVALUABLE; the field is explicitly NONE there to make that orthogonality enforceable at the type level.

**Implementation status (2026-05-03).** `FailureMode` enum + Violation fields in [src/compliance/types.py](src/compliance/types.py); `compute_error_fingerprint` helper in the same module. Dispatcher updated in [src/compliance/evaluator.py](src/compliance/evaluator.py) (ENGINE_ERROR + fingerprint in the try/except wrapper; AMBIGUOUS_RULE for the no-evaluator-registered defensive path). Each evaluator at [src/compliance/evaluators/](src/compliance/evaluators/) populates failure_mode on its UNEVALUABLE paths (numeric: MISSING_DATA on missing field, AMBIGUOUS_RULE on rule defects; geometric stub: MISSING_DATA with a fixed run-level fingerprint; document_presence + procedural: MISSING_DATA on missing key). DDL columns added to `violations` in [src/load_project.py](src/load_project.py) with a CHECK constraint on the 5 modes. Persistence layer write/read updated in [src/compliance/persistence.py](src/compliance/persistence.py); summary stats include `by_failure_mode` and `error_fingerprint_clusters`. PDF generator renders the system-health warning, cluster banners, and inline failure-mode pills via [src/pdf/templates/compliance_opinion.html.j2](src/pdf/templates/compliance_opinion.html.j2) and [src/pdf/templates/partials/parcel_section.html.j2](src/pdf/templates/partials/parcel_section.html.j2); Hebrew labels live in [src/pdf/verdict_translations.py](src/pdf/verdict_translations.py). Test coverage extended in [tests/test_evaluator.py](tests/test_evaluator.py), [tests/test_persistence.py](tests/test_persistence.py), and [tests/test_pdf_generator.py](tests/test_pdf_generator.py) — 61 tests across 4 suites pass.

### Confidence as an Orthogonal Axis

**Decision.** A `Violation` carries a third orthogonal classification axis alongside `verdict` and `failure_mode`: **`confidence`** — a three-level enum (`HIGH` / `MEDIUM` / `LOW`) that answers "how reliable is this verdict?" The default is `HIGH` because every current evaluator is deterministic. The qualitative evaluator emits `LOW` by default; future Claude-backed paths may upgrade specific outputs to `MEDIUM` when their structured reasoning supports it.

**Why a third axis.** The first two axes already answer two important questions:

- `verdict` — *what* happened? (the 7-state outcome)
- `failure_mode` — *if unevaluable, why?* (the 5-state cause classification)

Neither answers a third critical question the engineer asks during review: *how much should I trust this verdict?* A pass with low confidence is genuinely different from a pass with high confidence — the first warrants a manual look, the second doesn't. Without a confidence axis, every verdict reads as equally authoritative even when the underlying check was a fuzzy model judgment vs. a deterministic numeric comparison. Treating reliability as a first-class field forces evaluators to declare it explicitly and lets the PDF generator surface low-confidence rows for the engineer's attention without mis-stating the verdict itself.

**Why three values, not a 0–1 float.** A scalar would invite false precision (is 0.73 different from 0.78?) and would force every evaluator to invent a calibration scheme. Three discrete buckets — *trust by default*, *trust with a glance*, *check personally* — are easier for the engineer to act on and easier for evaluators to assign honestly.

The three values:

- **`HIGH`** — deterministic check on clean data, or explicit rule match. All current evaluators (numeric, geometric stub, document_presence, procedural) emit this. Even the "I can't evaluate" outcome from these evaluators is HIGH-confidence: we're confident the answer is "couldn't check". The dispatcher's exception path also leaves the field at HIGH because the verdict + failure_mode already carry the "we don't trust this" signal.
- **`MEDIUM`** — deterministic but with assumptions, or model-recommended verdict with strong, citable evidence. Reserved for the future Claude integration when it returns structured reasoning the engineer can trace.
- **`LOW`** — qualitative model judgment without explicit rule grounding, or extracted value of uncertain quality. The qualitative evaluator emits this today. The future extraction layer may emit it on borderline OCR or DWG parses.

**Independence from verdict.** Confidence does NOT change verdict logic. A LOW-confidence PASS is still a PASS — the engineer sees both signals and decides. A MEDIUM-confidence FAIL is still a FAIL. The rule for the engineer is "verdict tells you the outcome; confidence tells you whether to look closer."

**PDF generator behaviour.** The findings table shows a small `.confidence-badge` next to the verdict pill **only when confidence is not HIGH** — high-confidence rows display nothing so the rest of the table stays uncluttered. When the run contains any LOW-confidence rows, the system-health area gains a second paragraph: "N ממצאים סווגו בוודאות נמוכה — מומלץ לבחון אותם אישית." When a row has both `is_override_applied=True` AND `confidence=LOW`, an additional `worklist-flag` appears beneath the override badge ("לבחינת מהנדס: עקיפה בוודאות נמוכה") — a low-confidence verdict that an engineer waived earlier is a particularly weak signal and should be re-examined regardless of verdict.

**What this is NOT.** confidence does not propagate to `extracted_data` yet — that's the extraction layer's responsibility (separate task). confidence does not affect the rule resolver. confidence does not change persistence semantics for any other field; it's purely additive.

**Implementation status (2026-05-03).** `Confidence` enum + `confidence: Confidence = HIGH` field in [src/compliance/types.py](src/compliance/types.py). Qualitative evaluator at [src/compliance/evaluators/qualitative.py](src/compliance/evaluators/qualitative.py) emits LOW by default; all four deterministic evaluators inherit the HIGH default. DDL column added to `violations` in [src/load_project.py](src/load_project.py) with a CHECK constraint on the 3 values. Persistence layer reads/writes the column in [src/compliance/persistence.py](src/compliance/persistence.py); summary stats include `by_confidence` (3 keys, zero-filled). PDF generator surfaces the confidence badge, low-confidence summary line, and low-confidence-override worklist flag via the existing template + CSS files. Hebrew labels in [src/pdf/verdict_translations.py](src/pdf/verdict_translations.py). Test coverage extended in [tests/test_evaluator.py](tests/test_evaluator.py) (`ConfidenceAxis` class — 8 tests), [tests/test_persistence.py](tests/test_persistence.py) (roundtrip + summary), and [tests/test_pdf_generator.py](tests/test_pdf_generator.py) (`ConfidenceBadge` + `ConfidenceBadgeAbsentWhenAllHigh`) — 77 tests across 4 suites pass.

---

## Key Files in This Project

- `SKILL.md` — domain knowledge, Hebrew terms, document structure
- `project-template-blank.json` — blank template for new projects
- `project-schema-407-0977595.json` — pilot project full data
- `CONTEXT.md` — this file (architectural decisions)
- `CLAUDE_CODE_START.md` — what to build first

---

## Reference skills (active context for code that handles Hebrew docs)

Two reference documents must be loaded as model context for code that
generates or validates Hebrew planning documents. Neither is a runtime
dependency today — both light up at Phase 3 and beyond.

| skill | path | when to load |
|---|---|---|
| Hebrew style guide for חוות דעת | [docs/style-guide-hebrew.md](docs/style-guide-hebrew.md) | every Hebrew text-generation call in the חוות דעת draft generator (Phase 3). Sets register, fixed phrasings, term preferences. Living document — refresh when corpus grows. |
| תכנית עיצוב document structure | [docs/skills/design-plan-structure/SKILL.md](docs/skills/design-plan-structure/SKILL.md) | every code path that **produces or validates a תכנית עיצוב** (Phase 2/3 design-plan generator + future compliance check against §145(ז) limits). Documents the 14-section structure, 5×-per-תא-שטח page sequence, color system, mix-table data structure, footer/branding, and what design plans *cannot* legally include. Confidence: low-to-medium — based on a single reference document (Kika Braz תכנית עיצוב הטייסים, 63 pages, A3). See §14 of the skill for the update protocol when more reference plans arrive. |

Pair with the gold-standard examples under `data/corpus/extracted/` and
`data/corpus/gold-standard/` when prompting — the skills are the rule books;
the corpus files are worked examples.

---

## Knowledge Base / Domain References

Curated knowledge artifacts that inform compliance decisions but are NOT
used for automated enforcement. Code may parse them as advisory context,
surfacing relevant entries to a human reviewer; the reviewer adjudicates.

- [docs/ness-ziona-policy-themes.md](docs/ness-ziona-policy-themes.md) — Ness Ziona committee policy knowledge base (36 entries, 6,833 words). Two sections: local committee patterns (P-001 to P-020) and city positions at district committee hearings (P-021 to P-036). Status: `fifth_pass_draft`, not yet reviewed by Ellen. Used as advisory context in compliance engine — never for automated enforcement.

---

## What NOT to Do

- Do NOT hard-code any rules for any specific plan
- Do NOT call Claude API for numeric/geometric checks — pure Python
- Do NOT accept implicit sub-basin → statutory plot mappings in stormwater extraction
- Do NOT generate a compliance opinion for parcels covered by an adjacent plan without an explicit scope_out entry confirmed by Ellen
- Do NOT allow a rule into production without human confirmation (`review_status = 'confirmed'`)

---

## Northern Site Reference

The submitted תכנית עיצוב (Kika Braz, 23.3) covers a wider area than the pilot's statutory plan. Two MAVAT artifacts apply to the area immediately north of 407-0977595:

- **407-1048248** — *התחדשות עירונית במתחם ההסתדרות-הטייסים*. Approved 2025-08-07. The actual adjacent urban-renewal plan. Currently staged at `data/staging/407-1048248/` (תשריט only); pending תקנון to be promoted.
- **407-1109909** — *הודעה לפי סעיפים 77–78 לחוק התכנון והבנייה* for the same geography. Interim restriction notice that preceded 407-1048248. Not a separate plan and not a competing registration.

The pilot's `parcels[]` (after the 2026-04-30 schema fixes) reflects only what is actually inside the 407-0977595 תשריט: plots 1, 2, 4, 5, 6, 10. The earlier "scope_out: ['plot_3', 'plot_5']" framing was wrong (plot_3 doesn't exist in the תשריט; plot_5 is a small parcel inside the plan boundary).

---

## Open Tasks

Maintained list of known-unresolved items that any phase may pick up.

- **Review [docs/ness-ziona-policy-themes.md](docs/ness-ziona-policy-themes.md) with Ellen.** Target outcome: promote `observed_pattern` entries to `verified_policy` where she confirms; remove entries she rejects; capture her answers to "Open questions for Ellen" sections embedded in each P-NNN entry. The file is structured for focused review — each entry is independently reviewable.
- **Cross-reference plan 407-0730606 (Northeast Ness Ziona) statutory text against P-028 through P-036.** We have both the city's objections raised at district committee AND the final approved plan — that gives us a calibration case for "what city wants vs what gets approved." Useful for tuning the compliance engine's confidence calibration on city-stance vs district-outcome.
- **Acquire full text of four verified committee resolutions cited in `ness-ziona-policy-themes.md`:** resolution 202203 (17.05.2022, pool setback), the 30.11.2020 resolution (balcony 30%+6%), resolution 202508 (30.07.2025, low-rise concessions, supersedes the 2020 resolution), and plenary resolution 202101 (TMA-38 local extension). Full text strengthens the `verified_policy` entries from "cited" to "documented in repo."
- **Architectural caveat: Tel Aviv corpus is structural reference only, not policy training data.** The 20-protocol corpus under `data/corpus/extracted/` was downloaded from the Tel Aviv subcommittee. It informs three things — (1) **structural patterns** of חוות דעת documents (universal, law-driven), (2) **professional Hebrew register** for planning prose, and (3) **the taxonomy of argument *types*** (`source_missing_or_incomplete`, `numeric_rule_violation`, `non_conformance_with_plan`, `qualitative_judgment` — all universal). It does NOT inform Ness Ziona policy. **When building Phase 3 (חוות דעת generator), do NOT encode Tel Aviv-specific policy as defaults**: do not assume e.g. "הוועדה לא מאשרת X" patterns from this corpus apply in Ness Ziona without explicit Ness Ziona policy confirmation from Ellen. **`reason_class` values are universal; `rule_basis` values (תוכנית ע1, מדיניות יפו, הנחיות מרחביות תל אביב, חוות דעת צוות התכנון של מכון הרישוי, …) are NOT.** Build the Ness Ziona corpus separately as it accumulates, and when conflicts arise treat the Ness Ziona corpus as authoritative for that municipality. The `verdict_classifier` and `findings_extractor` regex patterns added to date are deliberately scoped to *universal Hebrew planning register* — verb forms ("נוגד/נוגדת"), generic regulatory citations ("בניגוד לתקנות"), structural document anchors ("ללא הצגת", "לא הוכח") — not municipality-specific phrasings.
- **Verify YEUD codes 676 and 882 against an official MAVAT symbology source.** Both are currently classified by parent category only (`tentative` confidence in `YEUD_LOOKUP` in `src/tashrit_analysis.py`). מינהל התכנון does NOT publish a machine-readable YEUD table. Source candidates: MAVAT 2024 DXF standard file, MAVAT symbology PDF, or a direct query to מינהל התכנון. Inferred meanings: 676 → public buildings variant (assigned to plot 6 = מבנים ומוסדות ציבור per תקנון); 882 → open space variant (assigned to plots 4 and 5 with שצ"פ designation per תקנון).
- **Identify the building-line layer (קו בניין).** Confirmed 2026-04-30 that `kavim kchulim.shp` is the plan boundary, not the building line. The building line still needs vector-form extraction; only known source is `407-0977595_מצב מוצע.dwg` (AC1018), which requires DWG → DXF conversion (libredwg or ODA).
- **Promote 407-1048248 from staging.** Blocked on obtaining תקנון from mavat.gov.il. See `data/staging/407-1048248/STATUS.md`.
- **`verdict_classifier`: `partial_approve` verdict type — track instances.** `partial_approve` covers two distinct patterns. **(a)** "Approve some, reject the objection on the rest" — already caught by the existing `לקבל את ההתנגדות` regex; N=3 in corpus today (case 22-0214 in 2-22-0009, case 22-1634 in 2-23-0002, case 23-0258 in 2-24-0005). **(b)** "Approve one concession, explicitly cancel others with נימוקים" — the case-19-0704 family. Currently classified as `approved` because the broader `לאשר` pattern fires first; 1 known instance (19-0704 in 2-21-0006). Still below the N≥3 threshold for a dedicated regex pattern. Track count after each mass-download batch — the (b) family in particular needs vigilance because it's misclassified as `approved` rather than surfaced as `unknown`.
- **Findings parser produces "mixed-multi-issue" single findings** (one finding text containing 5–7 distinct defects). Examples: case 21-1293/f003 (4 distinct design-guideline issues a–d), case 21-0372/f005 (5 issues comma-separated), case 20-1557/f003 (3 issues comma-separated). Current classifier can't handle these because they span multiple categories — only the first matching pattern fires, leaving the other defects unclassified inside the same string. Future work: split numbered-list / lettered-list / comma-list rejection text into separate findings before classification.
- **Finding text contamination from PDF page-break artifacts.** Some findings extend past their natural close because the rejection-list parser's end-anchor doesn't catch every variant of the closing line, so the next page's banner text leaks into the finding body. Example: case 23-1153/f001 in 2-24-0014 contains `[[PAGE_BREAK]] בקשת רישוי...` suffix from the next page. Strip page-banner text from finding bodies before classification (and ideally before storing).
- **Three candidate finding subtypes observed in sample-30 review but currently N<3 in corpus.** Promote to `reason_class` only if N≥3 each after pattern expansion. (i) `third_party_negative_review` — consultant body issues a negative opinion ("התכנית הוגשה עם חו"ד שלילית של מכון הרישוי..."); seen in 22-1264/f013. (ii) `objection_upheld` — committee accepts a third-party objection ("לקבל את טענות המתנגדים..."); seen in 21-0116/f002, 22-0207/f002. (iii) `owner_consent_missing` — statutory 75% owner consent absent ("לא התקבלה הסכמת כל בעלי הזכויות בבית המשותף..."); seen in 22-0228/f003.
- ~~**Period wedged inside Hebrew words breaks classifier keyword matching.**~~ **RESOLVED 2026-05-01.** Fixed in `pdf_to_text._patch_artifacts` with regex `[א-ת]\.[א-ת] → [א-ת][א-ת]` — strips a period sandwiched between two Hebrew letters with no whitespace on either side. Safe for legitimate Hebrew text (sentence boundaries always have whitespace; abbreviations like `ת"א` and `מ"ר` use quotes, not periods; apostrophes like `קומה א'` are a different character). Recovered exactly **1 finding** out of the 98-residual pool — meaningfully lower than the 5–15 I estimated, suggesting period-wedge artifacts co-occur with other unclassifiable issues (mixed-multi-issue findings, page-break contamination) so the period was rarely the sole blocker. Regression on 2-22-0009 vs gold held at 31/31 = 100%.
- **`verdict_classifier` pattern 4 added 2026-04-30** based on N=3 instances of "בהמשך להחלטת… לאשר" in 2021–2022 protocols (cases 19-1456, 19-0950, 20-0173). Same shape as patterns 1–3: subsequent discussion of a prior committee decision.
- **Approval pattern family: "לאשר X … בכפוף לכל דין" without "את הבקשה" anchor.** N=2 in current corpus (`21-1647` in 2-22-0002, `22-0231` in 2-22-0011). After mass download, count instances. **If N≥10**, design a 3-anchor pattern (`בכפוף לכל דין` + `ובתנאים הבאים` + conditions block exists). **If N<10**, leave as `unknown` and hand-classify in a review pass. Do NOT lower the threshold or add a 2-anchor pattern with a long span — risk of false positives on rejections that mention "לאשר" elsewhere is too high.
- ~~**Reconcile schema model: a project (תכנית עיצוב) may span multiple statutory plans.**~~ **RESOLVED 2026-05-01.** Design plan ↔ statutory plan is now explicitly modeled as **many-to-many**. Schema additions: `project_takanon_links` join table in DDL; top-level `design_plan` block + `linked_statutory_plans[]` array in the project schema JSON; `governing_takanon_id` per parcel. Pilot already updated to declare both 407-0977595 (`coverage_type: primary`) and 407-1048248 (`coverage_type: partial`, `version_label: "pending_takanon"`). See "Architectural Decisions → Design plan ↔ statutory plan: many-to-many" above. **Follow-up:** wiring the loader (`src/load_project.py`) to populate `project_takanon_links` and read `governing_takanon_id` from parcels — separate task, see new Open Task below.
- ~~**Persist violations to DB.**~~ **RESOLVED 2026-05-01.** Built [src/compliance/persistence.py](src/compliance/persistence.py). Public API: `run_compliance_evaluation(project_id, project_data, extracted_data, db_conn, engine_version, submission_version, triggered_by="manual") -> str` (returns engine_run_id) and `load_violations_for_run(engine_run_id, db_conn) -> list[Violation]`. Lifecycle: insert `engine_runs` row with `status='running'`, evaluate each parcel + per-parcel commit (so partial progress survives a later failure), compute summary stats, mark `complete` with `summary_stats_json` and `completed_at`. Failure path marks `failed` with traceback in `error_message` and re-raises. The schema mismatch between the new 7-state Verdict enum and the older list has been harmonized: the new enum is canonical — see "Violation Statuses" section above. DDL for `engine_runs` and `violations` updated in [src/load_project.py](src/load_project.py) with a CHECK constraint listing exactly the 7 verdict values (adding a new Verdict member without updating the CHECK will break INSERTs). Tests at [tests/test_persistence.py](tests/test_persistence.py) cover happy path, multi-parcel rollups, JSON polymorphic round-trip (Hebrew + nested), override flag round-trip through INTEGER column, failure-path partial-progress preservation, and two-runs no-cross-contamination — all 6 green.
- **Build the engineer override workflow.** The persistence layer reads `project_rule_exceptions` and the `is_override_applied` bit propagates correctly through `Violation` rows, but there is no application path for an engineer to actually create overrides. Need a UI/CLI that inserts rows into `project_rule_exceptions` with dual sign-off (engineer + authority) before the override takes effect at evaluation time. Until this lands, overrides can only be inserted by hand-written SQL.
- ~~**Build the PDF generator that consumes a completed engine run.**~~ **RESOLVED 2026-05-02.** Built [src/pdf/generator.py](src/pdf/generator.py) with two public surfaces: `generate_compliance_opinion(engine_run_id, db_conn, output_path) -> Path` (the full HTML→PDF path) and `render_html(engine_run_id, db_conn) -> str` (intermediate HTML, used by tests so we can assert on Hebrew substrings without parsing PDF binaries). Templates: Jinja2 under [src/pdf/templates/](src/pdf/templates/) — `compliance_opinion.html.j2` plus three partials (header, parcel section, footer). Styling: [src/pdf/styles/compliance-opinion.css](src/pdf/styles/compliance-opinion.css), self-contained — does NOT import `hebrew-rtl-base.css` because that file targets the wkhtmltopdf base64-font path; the new CSS uses Heebo + Arial Unicode MS, matching the working approach in [src/render_report_pdf.py](src/render_report_pdf.py). PDF backend: headless Chrome `--print-to-pdf` (macOS WeasyPrint needs `brew install pango`). Verdict translations live in [src/pdf/verdict_translations.py](src/pdf/verdict_translations.py) — Ellen-tunable in one place. Within each parcel, rows sort failures-first → borderline → review → unevaluable → pass-with-note → pass → not-applicable. CLI: `python -m src.pdf --engine-run-id <UUID> --db <path> --output draft.pdf` (or `--html-only` for fast template iteration). Tests at [tests/test_pdf_generator.py](tests/test_pdf_generator.py) (14 cases including a Chrome smoke test) all green; synthetic fixture at [tests/fixtures/synthetic_run.py](tests/fixtures/synthetic_run.py) covers all 7 verdict states across 3 parcels with one override-applied row, one bbox-evidence row, and Hebrew `notes` text.
- **Review the draft חוות דעת format with Ellen.** The verdict translations in [src/pdf/verdict_translations.py](src/pdf/verdict_translations.py), the section structure in [src/pdf/templates/compliance_opinion.html.j2](src/pdf/templates/compliance_opinion.html.j2), and the prose tone (executive-summary phrasing, footer disclaimer, "סוגיות הדורשות בחינת מהנדס" framing) are all starting drafts — Ellen will have professional opinions about phrasing, document conventions, and what an engineer expects to see in a חוות דעת. Capture her feedback as concrete diffs against these files. The verdict translation strings in particular are likely to shift; they are isolated to a single dict so a string-only edit propagates everywhere.
- **Populate the rules table with real rules from plan 407-0977595's תקנון.** Currently the rules table accepts inserts but no rules exist for the pilot. Synthetic test data exercised the persistence + PDF layers, but the engine cannot run a real evaluation until rule rows exist. This task is mostly judgment work — could be done collaboratively in a review session, possibly with the Claude API drafting rules from the תקנון text and a human (Ellen + engineer) verifying. Output: a population script that idempotently inserts rules with rule_code, rule_type, parameters, and source citations.
- **Build the extraction layer that reads the Kika Braz design plan PDF (63 pages)** and produces the `extracted_data` dict that the evaluator expects (per-parcel actual values keyed to rule_code, plus document-presence facts and qualitative excerpts for the qualitative/Claude evaluator). Pre-requisites: rules table populated (above), since the extractor knows what to look for from the rules. Build on the PyMuPDF + Hebrew-RTL artifact-handling work already done for the Tel Aviv corpus pipeline.
- **Implement geometric evaluator** once DWG parsing is end-to-end. Currently stubbed to `Verdict.UNEVALUABLE` with a fixed note (`"geometric evaluation not yet implemented (DWG parsing pending)"`) at [src/compliance/evaluators/geometric.py](src/compliance/evaluators/geometric.py). When DWG → DXF conversion is wired (libredwg or ODA), this evaluator should consume the parcel's geometry from `extracted_data['parcels'][parcel_id]['geometry']` and run Shapely-based checks (setbacks, footprint within boundary, balcony protrusion, etc.). Pre-requisite: the building-line layer (קו בניין) must be identified — see the Open Task above.
- **Implement Claude API integration for the qualitative evaluator.** Currently structurally returns `Verdict.REQUIRES_REVIEW` at [src/compliance/evaluators/qualitative.py](src/compliance/evaluators/qualitative.py) with a structured explanation built from the rule's `check_note` and source citation. The Phase 3+ replacement should call the Claude API with: (a) the rule definition, (b) the relevant evidence bundle from the parcel, (c) the תקנון excerpt cited by the rule. The model's structured response (verdict + reasoning + evidence references) should be surfaced to the human reviewer — the human still adjudicates, but the model produces a first-pass opinion that drafts a compliant חוות דעת sentence.
- **Wire the loader to consume the many-to-many schema additions.** `src/load_project.py` currently ingests the original `project` block only; it does NOT populate the new `project_takanon_links` table or read per-parcel `governing_takanon_id`. The DDL adds the table and the JSON declares the data, but no row is inserted yet. Update `insert_takanon_version()` (or add a sibling `insert_project_takanon_links()`) to: (1) iterate `linked_statutory_plans[]`, (2) ensure a `takanon_versions` row exists per linked plan, (3) insert idempotent rows into `project_takanon_links` keyed on `(project_id, takanon_id)`. Also propagate `parcels[].governing_takanon_id` into `plots_json` (already happens — the parcels are JSON-blobbed verbatim — but worth verifying after the loader change). Idempotency requirement holds throughout.
