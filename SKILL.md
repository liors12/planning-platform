---
name: planning-compliance-platform
description: Municipal planning compliance platform for Ness Ziona Urban Renewal Authority. Use when working on תכנית עיצוב documents, תב"ע compliance checking, building rights analysis, DWG/KML/SHP parsing for Israeli urban renewal plans, or any task related to Ellen's planning platform. Triggers on mentions of תב"ע, תכנית עיצוב, תא שטח, compliance engine, building rights, plan 407, Ness Ziona planning, urban renewal, פינוי-בינוי, הנחיות מרחביות, or municipal planning.
---

# Municipal Planning Compliance Platform

Platform for Ness Ziona Urban Renewal Authority (מינהלת התחדשות עירונית נס ציונה). Ellen is the authority director and primary client.

## System Overview

The platform does TWO things:
1. **Checks submitted plans** — architect submits תכנית עיצוב (PDF/DWG), system validates against תב"ע rules
2. **Generates תכנית עיצוב documents** — 60+ page design plan from structured parameters

## CRITICAL: Multi-Project Architecture

This is NOT a single-plan tool. Every rule, schema, and check is **project-keyed**. Plan 407-0977595 (מתחם הטייסים) is just the pilot. The system handles ANY Ness Ziona urban renewal plan loaded into it.

- Each project has its own תקנון, rules, plots, and submissions
- No rules are hard-coded — everything is project-keyed
- ~1 submission checked per 2 months; same files can be re-run with new engine versions

## Domain Knowledge

### Key Hebrew Terms (no English equivalent)

- **תב"ע** — statutory plan (legally binding zoning/building rights)
- **תקנון** — planning regulations document (part of תב"ע)
- **תכנית עיצוב / תכנית בינוי ופיתוח** — design and development plan (submitted for approval)
- **תא שטח** — planning parcel/plot within a plan
- **שצ"פ** — public open space
- **תמורה** — compensation units (for existing residents in פינוי-בינוי)
- **מרתף** — basement (parking levels)
- **קומה טיפוסית** — typical floor plan
- **חזיתות** — building elevations
- **חתכים** — cross-sections
- **הנחיות מרחביות** — spatial/design guidelines (municipal)
- **חוות דעת מהנדס העיר** — city engineer compliance opinion (the output document)
- **קו בניין** — building setback line
- **קו כחול** — plan boundary (blue line)
- **יח"ד** — housing unit
- **מפלס הכניסה הקובעת** — primary entrance level (defined as ≤1.20m above ground level — see National Regulatory Baseline)
- **קומה תחתית** — lower floor (technical term: floor whose level is below the primary entrance level)
- **שטח כולל המותר לבניה** — total area permitted for construction (legal term: עיקרי + שירות combined)

### What תכנית בינוי CAN and CANNOT include (per מינהל התכנון guide 10.11.2024)

**CANNOT include (statutory matters per §145ז):**
- Land use designations
- Number of units
- Building areas (sqm)
- Height limits
- Building lines
- Building interior design
- Restrictions beyond the statutory plan
- Duplicate approval requirements

**CAN include:**
- Building placement within plot
- Entrance levels (±0.00)
- Vehicle access points
- Infrastructure coordination
- Public uses allocation
- Landscape design
- Public space interface
- Microclimate considerations
- Easements
- Plantings

### תכנית עיצוב Document Structure (63 pages, per Kika Braz reference)

Per תא שטח, these 6 pages repeat:
1. **פיתוח** (site plan) — building footprints, setbacks, levels
2. **דיאגרמת אשפה** (waste) — same base plan + waste collection overlay
3. **דיאגרמת פונקציות** (functions) — same base plan + lobby/bike/amenity overlay
4. **מעונות יום** (daycare) — if applicable
5. **מרתף** (basement) — parking layout + data table
6. **קומה טיפוסית** (typical floor) — apartment layouts + unit mix table

Plus global sections: חתכים (cross-sections), חזיתות (elevations), שצ"פ (open space), הדמיות (renderings)

### Decision-Driven Data

Ellen decides these per project (within תב"ע constraints):
- Unit mix (תמורה/יזם split per building)
- Parking ratios (typically ~1.3:1)
- Apartment type allocation
- Public use placement

Architects provide: floor plans, apartment layouts, DWG files

## National Regulatory Baseline

**This section captures Israeli planning regulations verified against primary sources (gov.il, nevo.co.il, wikisource). Do not rely on memory or LLM training data for these facts — they are intentionally captured here because LLMs frequently err on them.** See `national_regulatory_baseline.md` for full citations and detail.

### Primary statutes and regulations

| Source | Year | Key role |
|---|---|---|
| חוק התכנון והבניה | תשכ"ה-1965 | Master statute. Defines "שטח כולל המותר לבניה" (§1), §62א local committee authority, §145(ז) statutory matters |
| תקנות חישוב שטחים | תשנ"ב-1992 | THE source for area calculations. Includes major תיקון תשפ"ה-2025 |
| תקנות בקשה להיתר | תש"ל-1970 | Defines entry level, building height categories, basic building terminology |
| תקנות הקלות | תשפ"ג-2023 | Replaced תקנות סטיה ניכרת תשס"ב-2002 — relevant for variance procedures |

### Verified definitions (use these, ignore LLM-suggested alternatives)

**מפלס הכניסה הקובעת** (entry level): primary entrance whose floor level is ≤1.20m above the planned ground level or adjacent street/sidewalk, accessed via path/stairs/bridge directly from street. If multiple entrances exist, the determining one is specified in the building permit. (Source: תקנה 1 of תקנות בקשה להיתר תש"ל-1970, also תקנה 1 of תקנות חישוב שטחים תשנ"ב-1992)

**Building height categories** (measured from entry level to the entry level of the highest occupied floor accessed via shared staircase):
- **בנין רגיל**: ≤13m
- **בנין גבוה**: >13m and ≤29m
- **בנין רב-קומות**: >29m

(Source: תקנות בקשה להיתר תש"ל-1970, definitions section)

**שטח כולל המותר לבניה** (total area permitted for construction): "סך כל השטח המותר לבניה, הכולל הן שטחים למטרות עיקריות והן שטחים למטרות שירות" (Source: §1 of חוק התכנון והבניה)

**קומה תחתית** (lower floor): floor whose level is below the entry level, regardless of whether all walls are below ground or some face open air. **NOT to be confused with "מרתף"** — מרתף is a colloquial term that maps to קומה תחתית in regulation. (Source: תקנה 1 of תקנות בקשה להיתר תש"ל-1970)

**שטח עיקרי vs שטח שירות**: Defined exclusively in **תקנה 9 of תקנות חישוב שטחים תשנ"ב-1992**. Specifically:
- תקנה 9(ב): defines "מטרות עיקריות" (residential, commercial, etc.)
- תקנה 9(ד): defines "מטרות שירות" (ממ"ד, parking, storage, technical systems, shared corridors and stairs, open columns floors)
- תקנה 9(ג): everything not in service is treated as main use

### CRITICAL: Dual-mode regulatory framework (post-Dec 3, 2023)

A major reform occurred in two stages:
1. **December 2023**: תיקון to תקנות חישוב שטחים — for plans approved after 3.12.2023, the planning institution can choose either of two modes:
   - **"תוכנית בשטח כולל"**: areas defined without distinction between עיקרי and שירות
   - **Old mode (split)**: areas defined separately for עיקרי and שירות (legacy approach)
2. **September 30, 2025** (תיקון תשפ"ה-2025): added implementation rules including the option to issue a "היתר בשטח כולל" even from a plan that defines split areas, under specified conditions

**Implications for the platform:**
- Every plan loaded into the system must have a `regulatory_mode` field: `"split"` (legacy) or `"total_area"` (post-2023 new mode)
- When plan was approved AFTER 3.12.2023, the system must check the תקנון to determine which mode it uses
- Compliance engine logic differs significantly between modes — area checks against ratios are only meaningful in split mode
- Plan 407-0977595 (Hetzeisim, approved 21.01.2024) is in **split mode** — the תקנון explicitly defines main and service areas separately. See project schema for `regulatory_mode: "split"`.

### CRITICAL: Common LLM errors to NOT replicate

These false claims appear repeatedly in AI-generated regulatory analyses. Do not use them:

1. **❌ "תיקון 117 (2017) defines 'small apartment'"** — FALSE. תיקון 117 is a temporary provision for splitting ground-floor houses (פיצול בתים צמודי קרקע). Required minimum 120m² home, new unit ≥45m². Has no general "small apartment" definition.

2. **❌ "תיקון 155 (2024) redefines 'small apartment'"** — FALSE. תיקון 155 is the renewal of תיקון 117 — also about splitting ground-floor houses, not general definitions.

3. **❌ "Section 147(י) of the Law defines 'small apartment'"** — UNVERIFIED. Section 147 deals with variances, not definitions. There is no single statutory definition of "דירה קטנה" — the threshold (75m², 80m², or other) varies by context.

4. **❌ "Court case עע"מ 2605/18 establishes height conflict resolution"** — UNVERIFIED. The case may not exist; cited by AI engines without verification.

5. **❌ "1.20m entry level definition is in some other regulation"** — The correct source is BOTH תקנה 1 of תקנות בקשה להיתר תש"ל-1970 AND תקנה 1 of תקנות חישוב שטחים תשנ"ב-1992. They contain identical definitions.

When in doubt, cite directly from `national_regulatory_baseline.md` rather than from training data.

### Authority for plan modifications (relevant to ניוד)

**Section 62א(א)(6)** of חוק התכנון והבניה: Local Committee has authority to approve a plan that "changes the distribution of building areas allowed in a single plan, without changing the total allowed building area, provided that the total allowed building area in any land-use category does not increase by more than 50%."

**Important**: This is the AUTHORITY — it does not specify HOW to measure transfers. Specific transfer rules (like "10% between plots") are defined in each תקנון individually.

## Tech Stack

| Component | Technology | Purpose |
|---|---|---|
| Geometry/compliance | Shapely + GeoPandas | Setbacks, footprints, area calculations |
| CAD generation | ezdxf | DXF output for technical drawings |
| CAD reading (DWG) | @mlightcad/libredwg-web (WASM) or ODA File Converter | DWG→DXF conversion (AC1018+) |
| Renderings | Gemini image generation | Conceptual architectural images |
| PDF parsing | PyMuPDF | Text/table extraction from submitted plans |
| Regulatory analysis | Claude API | Cross-checking plan text against תקנון |
| PDF output | WeasyPrint | HTML/CSS → PDF with RTL Hebrew |
| File upload | Uppy.js | Chunked uploads for large files (100MB+) |
| Storage | Cloudflare R2 | File storage |
| Frontend | React + Next.js | Ellen's decision UI |

## Project Data Schema

Every project loaded into the system follows this JSON structure. See `project-schema.json` for the complete schema with plan 407-0977595 as the reference instance.

### Key Schema Sections:
- `project.meta` — plan number, name, status, approval date, **regulatory_mode** (split | total_area)
- `project.parcels[]` — per-parcel building rights, geometry, constraints
- `project.compliance_rules[]` — machine-checkable rules from תקנון
- `project.global_rules` — plan-wide constraints (small apartments %, transfer rules)
- `project.stormwater` — retention requirements per parcel
- `project.geometry.boundary` — קו כחול polygon coordinates
- `project.geometry.parcels[]` — parcel boundary polygons
- `project.submissions[]` — history of submitted plans and check results

## File Format Notes

### Digital Files from מנהל התכנון (MAVAT)

Plans come with a standard digital package:
- **KML** — plan boundary + parcel polygons with land use metadata (floors, status)
- **KML for Google Earth** — simplified version for viewing
- **XLS** — building rights table (often HTML-formatted, not true Excel)
- **DWG** — CAD drawings (תשריט, existing state, proposed state). Usually AC1018 (AutoCAD 2004) format
- **SHP** — GIS shapefile with geographic data

### DWG Handling

- Files are typically AC1018 (AutoCAD 2004) binary format
- `ezdxf` only reads DXF (not DWG)
- GDAL's `libopencad` only supports AC1015 (2000)
- Best option: `@mlightcad/libredwg-web` (WASM-based, works in Node.js)
- Alternative: ODA File Converter (commercial, free for non-commercial)
- DWG files contain building setback lines (קו בניין) that are critical for compliance

### KML Parsing

- KML altitude = floors × 3m (for 3D visualization only, not authoritative)
- Authoritative floor count is in the metadata table within each Placemark
- Hebrew encoding may require cp437→windows-1255 conversion in ZIP files
- Coordinates are WGS84 (lon, lat, altitude)

## Compliance Engine Rules

Rules are extracted per-project from the תקנון. Categories:

1. **Quantitative** (auto-checkable): unit count, building area, height, floors, setbacks, parking ratio, stormwater retention, permeable surface %, small apartment %
2. **Geometric** (Shapely-checkable): building footprint within parcel, setback distances, gap between buildings, balcony protrusion limits, מרתף coverage %
3. **Regulatory text** (Claude API): narrative conditions, pre-permit requirements, aviation authority approvals, cross-references to other plans

### Rule resolution and national regulations

When a rule references a term that is defined nationally (e.g., "שטח עיקרי", "מפלס הכניסה הקובעת"), the system applies the verified national definition from this baseline. This means:

- For a plan in **split mode**: rules referencing "שטח עיקרי" use the תקנה 9(ב) definition, "שטח שירות" uses תקנה 9(ד)
- For a plan in **total_area mode**: rules referencing "שטח כולל" use the §1 statutory definition (no split required)
- For "מפלס הכניסה הקובעת" in any mode: the 1.20m threshold from תקנות בקשה להיתר applies

### Local-only rule fields

Rules that are **inherently project-specific** (no national fallback) and require Engineer (Ellen) decision:
- Distribution requirements for small apartments between parcels
- Counting rules for technical roof floors
- Specific transfer percentages and direction rules
- Building line measurement origins (from road centerline vs. plot boundary)
- Setback origin (from facade vs. balcony edge)

These are tracked in `project_rule_exceptions` table for persistent engineer overrides.

---

## Submission Format Rules — separate from content rules

The platform now distinguishes between two categories of rules:

### Category 1: Content compliance rules

These check whether the submitted plan **complies with the תב"ע**. Examples: unit count ≤ 235, setback ≥ 3.0m, small apartment ≥ 20%. These are stored per-project in `project.compliance_rules[]` and reference the specific project's תקנון.

### Category 2: Submission format rules (NEW)

These check whether the submitted document **follows the standard format** used in Ness Ziona. Examples: page size is A3 landscape, cover has 6-discipline signature table, every page has a footer with section name and page number, scale annotations exist on all plans.

These rules are **city-wide standards** (not per-project), derived from the approved Northeast Nes-Ziona booklet (plan 407-0730606, Dec 2025) which was accepted by the city management as the visual reference for all תוכנית עיצוב submissions in Ness Ziona.

The format rules live in **`submission_format_rules.json`** at the project root. Every project automatically references this file. Per-project overrides go in the project schema's `format_rule_overrides` field.

## CRITICAL: Determinism contract for format rules

The format-rules system has a strict determinism requirement that does NOT apply to content rules:

> **Every format rule must produce identical verdict for identical input PDF.** Same submission, run twice → same set of verdicts, every time. No exceptions.

This is enforced by two design rules:

1. **No LLM calls for format checks.** All deterministic format rules must be implemented in pure Python (PDF metadata, text extraction, regex, table detection, image detection). LLMs are explicitly forbidden in this path because their outputs can vary even with temperature 0.

2. **Manual review rules return a deterministic verdict.** Rules marked `check_method: "manual_review"` do NOT attempt to interpret the PDF. They deterministically return `verdict: "requires_review"` with `review_instructions_he` passed to the engineer's UI. The system never says "I think this passes" or "I think this fails" for a manual-review rule.

The contract is enforced at multiple layers:
- The JSON schema for format rules has a `deterministic: true|false` field that must match the `check_method`.
- The engine module that runs format rules has zero Anthropic API calls in its codepath.
- Same content + same engine version → byte-identical verdict set, every run.

This is what the user means by "סטנדרט קבוע — שלא פעם אחת נגיד ככה ופעם אחרת נגיד אחרת" (a constant standard — that we don't say one thing once and something else another time).

## Format rule check methods

Each rule specifies one of these check methods:

| Method | Implementation | Determinism |
|---|---|---|
| `pdf_metadata` | Read page size, fonts, image counts from PDF structure | ✓ Fully deterministic |
| `text_extraction` | Search for required text patterns in extracted text | ✓ Fully deterministic |
| `regex_pattern` | Apply regex to extracted text within scope | ✓ Fully deterministic |
| `table_detection` | Use pdfplumber to detect tables and match headers | ✓ Deterministic given same library version |
| `pdf_image_detection` | Enumerate embedded images, compute area | ✓ Fully deterministic |
| `page_structure_analysis` | Combine text density, position, footer region | ✓ Deterministic with explicit rules |
| `manual_review` | Return `requires_review` with instructions | ✓ Deterministic (always same verdict) |

## Format rule integration with existing taxonomy

Format rules use the existing verdict and failure_mode taxonomy:

- **Deterministic rule passes**: verdict=`pass`, failure_mode=NONE, confidence=HIGH
- **Deterministic rule fails**: verdict=`fail` or `fail_borderline` per rule spec, failure_mode=NONE, confidence=HIGH
- **Deterministic rule cannot extract input**: verdict=`unevaluable`, failure_mode=EXTRACTION_FAILURE, confidence=HIGH
- **Manual review rule**: verdict=`requires_review`, failure_mode=NONE, confidence=HIGH

Note: For format rules, confidence is always HIGH because the check is mechanical. Confidence below HIGH would violate the determinism contract.

## File locations (when working in this project)

- `submission_format_rules.json` — the rules data (canonical standard)
- `submission_format_baseline.md` — human-readable documentation (optional companion)
- Per-project schema can include `format_rule_overrides: [...rule_codes_to_skip]` for cases where a rule doesn't apply (e.g., commercial chapter for a residential-only plan)

## What this changes in the audit report

The compliance opinion document now includes a new section (currently Section 6 of the Hetzeisim audit) listing all format rules and verdicts. For each rule:
- Deterministic rules → definitive pass/fail/fail_borderline verdict
- Manual review rules → `requires_review` with instructions for the engineer

The audit report's verdict thus becomes fully reproducible: given the same submission and the same `submission_format_rules.json` version, the system produces the same audit, every time.

## Output Documents

The platform generates:
1. **חוות דעת מהנדס העיר** — compliance opinion with pass/fail per rule, specific objections with page references, verdict (APPROVED / CONDITIONAL / REJECTED)
2. **תכנית עיצוב** — full 60+ page design plan document

## Instructions for Claude

When working on this project:

1. Always respond in English, keeping Hebrew only for terms with no English translation
2. Everything is multi-project — never hard-code rules for a specific plan
3. The compliance engine checks submitted plans AGAINST the תב"ע, not the other way around
4. Ellen decides unit mix and allocation; the system provides the תב"ע constraints
5. Architects provide floor plans; the system places them in the document template
6. Cross-sections and elevations are programmatically generated from parameters
7. Site plans (פיתוח) are the most complex drawings — they combine footprints, landscape, dimensions, levels, parking entrances in one view
8. Waste and function diagrams reuse the same base drawing with different overlays
9. For DWG files: convert to DXF first, then parse with ezdxf
10. The KML from MAVAT is the source of truth for parcel boundaries and land use
11. **NEVER cite Israeli planning regulations from training data**. Use the National Regulatory Baseline section above or `national_regulatory_baseline.md`. LLMs (including earlier Claude versions) are systematically wrong about תיקון 117, תיקון 155, "small apartment" definitions, and section numbers — these errors are documented above.
12. **Always check `regulatory_mode`** before validating area-related rules: split mode requires separate עיקרי/שירות checks; total_area mode treats them as combined.
