---
name: design-plan-structure
description: |
  Reference for the structure, content, and visual conventions of an Israeli תכנית עיצוב
  (urban design plan) document. Use whenever generating, parsing, or validating תכנית עיצוב
  documents — including drafting new ones from project parameters, checking submitted plans
  for required sections, or building UI for design-plan composition. Triggers on mentions of
  תכנית עיצוב, design plan, tichnit itzuv, Kika Braz Architects format, or per-תא-שטח
  structure (פיתוח / אשפה / פונקציות / מעונות יום / מרתף / קומה טיפוסית / חזיתות / חתכים).

confidence: low-to-medium — derived from a single reference document (Kika Braz Architects,
  Hetzeisim, March 2026). Patterns that recur across multiple תאי שטח within that document
  are flagged "structural"; patterns observed only once are flagged "tentative". Update as
  more reference documents become available.

reference_document: data/projects/407-0977595/source-documents/תכנית_עיצוב_הטייסים_23_3.pdf
last_updated: 2026-04-30
---

# תכנית עיצוב — Document Structure Reference

## Purpose of this skill

This skill is **descriptive**, not generative. It documents what a real תכנית עיצוב looks
like, so that:

1. **Document generators** producing תכנית עיצוב drafts know what sections to populate, in
   what order, with what content types.
2. **Compliance engines** validating submitted תכניות עיצוב know what to expect and where
   to look for specific data.
3. **UI designers** building the project-configuration form (where Ellen fills in
   per-project parameters) know which fields are real inputs vs. derived outputs.

The current confidence level is **low-to-medium**. The structure described here is based on
a single reference document — תכנית עיצוב הטייסים by Kika Braz Architects (March 2026,
revision 23.3). When more reference plans become available — from Ellen, from the authority
archive, or from other Ness Ziona urban renewal plans — this skill should be updated.
Patterns observed multiple times in the reference document (e.g., the per-תא-שטח sequence
that repeats 5 times) are noted as **structural**; patterns observed only once are
**tentative**.

---

## 1. Physical document specs

| Property | Value |
|---|---|
| Page size | **A3 landscape** (1190.55 × 841.89 pt) |
| Software | Adobe InDesign (the reference uses InDesign 21.2) |
| Total pages | ~63 (varies — depends on number of תאי שטח and שצ"פ complexity) |
| Output format | PDF |
| Direction | RTL (Hebrew); titles and labels right-aligned |
| Typography | Hebrew throughout; English used only for building codes (A1, B1, etc.) and software/firm names |

**Important practical implication:** תכנית עיצוב cannot be authored in Word, ReportLab, or
WeasyPrint — the layout density, multi-column structure, and integration of vector drawings
require a real DTP tool. For automated generation, the realistic path is:

- Generate **content** (per-section data) from project schema as structured input.
- Generate **drawings** (site plans, sections, elevations) as vector outputs (SVG/DXF) from
  geometry sources.
- Compose into A3 layout via InDesign template (manually or via InDesign Server scripting),
  or via a custom DTP pipeline (HTML→Chromium with print CSS isn't sufficient for the
  layout density observed; requires evaluation).

This is a **Phase 4+ problem**. For Phase 3 (חוות דעת drafts), output is plain Hebrew PDF
via the wkhtmltopdf path documented in `src/pdf/styles/README.md`.

---

## 2. Document hierarchy (TOC structure)

Observed structure of the reference document:

```
1. Cover page
2. Table of contents

3. Introduction & context
   - מיקום הפרויקט (location, single page)
   - מבט כללי (general view, 2 pages — typically renderings)
   - תב"ע summary table (statutory plan summary, 1 page)
   - תחום תוכנית (plan boundary diagram with adjacent plans, 1 page)
   - נתונים כלליים לתוכנית (general plan data + planning principles, 1 page)
   - תאי שטח (cell breakdown listing buildings per cell, 1 page)
   - תכנית פיתוח (overall development plan, 1 page at 1:1250)

4. שצ"פ section (open-space park)
   - מבנה השצ"פ (overall structure, areas, sub-zones, 1 page)
   - תכנון שלד השצ"פ (skeleton plan: paths, planting strips, 1 page)
   - חזון ערכי לפארק (values vision, 4 pages including renderings)
   - הדמיות לשצ"פ (additional renderings, 4 pages)
   - חתכים לשצ"פ (cross-sections, 1 page)

5. Per-תא-שטח sections (repeating, 1 per cell — see §3 below)

6. Whole-plan visualizations
   - חתכים (cross-sections through the whole site, 4 pages)
   - חזיתות (street elevations, 11 pages)
   - הדמיה (final 3D rendering, 1 page)
```

**Structural insight:** The reference plan covers an area larger than its constituent
statutory plans. The Hetzeisim plan covers 23.2 dunam / 700 units across **two** statutory
plans (407-0977595 = 16.5 dunam, 387 units, approved + הטייסים צפון = 6.0 dunam, 220 units,
preliminary planning). The תב"ע summary table on page 6 reflects this combined scope, not a
single plan. **A תכנית עיצוב can encompass multiple תב"עות.** This was not anticipated in
the original platform architecture and should be reconciled — see Open Tasks in CONTEXT.md.

---

## 3. Per-תא-שטח section (the repeating unit)

For each תא שטח (5 in the reference document), the following pages repeat in this order:

| Page | Section | Content type |
|---|---|---|
| 1 | פיתוח (Development) | 1:500 site plan with buildings, entrances, garden zones, fire-truck access |
| 2 | דיאגרמת אשפה (Waste diagram) | Same site plan, overlaid with waste collection rooms, compactor locations, truck routes |
| 3 | דיאגרמת פונקציות (Functions diagram) | Same site plan, overlaid with ground-floor uses (lobby, residents' club, gym, bicycle storage), with area annotations in m² |
| 4 | מעונות יום (Daycare layout) | Site plan zoom on daycare-housing building, with area numbers |
| 5 | מרתף (Basement) | Basement floor plan with parking, technical rooms (transformer, generator, meters), storage |
| 6 | קומה טיפוסית (Typical floor) | Typical floor plan + **unit mix table** (the critical Ellen-input table — see §6) |
| 7 | הדמיות (Renderings) | 3D visualizations from various angles (1-3 pages — varies) |

**Variations observed:**
- Some cells share a פיתוח page if they're geographically adjacent (e.g., the reference
  shows a combined "תכנית פיתוח תא שטח 3+5" page).
- Cells without daycare use omit the מעונות יום page.
- Number of הדמיות pages varies with cell size and number of buildings.

The total per-cell section is therefore **5–10 pages**, depending on these factors.

---

## 4. Standard color palette for plans

Observed across multiple section types (פיתוח, חתכים, פונקציות):

| Use | Color | Notes |
|---|---|---|
| מרתפים (basements) | Pink/salmon | Below-grade floors, parking levels |
| דירות גן (garden apartments) | Pale green | Ground-floor units with private outdoor space |
| לובי כניסה (entrance lobby) | Light blue/cyan | Building entry zones, common circulation |
| מגורים (residential floors) | Pale yellow | Typical above-grade residential floors |
| מעונות יום (daycare) | Pale purple/lavender | Daycare-designated floors and zones |
| Public open space (שצ"פ) | Mid-green | Parks, gardens; in renderings |
| Tree canopy | Dark green | Existing and new trees on site plans |
| Roads (asphalt) | Pale gray/yellow | Streets and access roads |
| Buildings being designed | Various accents | Each building given a unique outline color or fill |

This palette is **convention**, not arbitrary. Engineers reviewing the document expect it.
Generated documents should adopt the same conventions to feel familiar.

---

## 5. Typical labels and conventions on plans

### Building identification
Buildings are coded with a letter + cell number: `A1, B1, C1, D1` for buildings A through D
in cell 1; `A2` for the single building in cell 2; etc. In every plan, a small index map of
the entire site appears in the lower-left corner showing which buildings the current page
covers (highlighted) vs. the rest of the site (gray).

### Heights and floors
- **Floor count**: `ק+9` means ground floor + 9 = 10 floors. `ק+13` means 14 floors. The
  reference building heights range from 9–14 floors above ground.
- **Elevation reference**: `±00.00 = 40.00` means the building's relative zero (ground
  floor finished) corresponds to absolute elevation 40.00m above sea level. Buildings with
  different ±00 references appear in elevation drawings at different baseline heights.
- **Per-floor markers** (in cross-sections): two values per floor, e.g., `+32.85 / +75.85`
  — the first is height above the building's ±00, the second is absolute elevation.

### Scales
| Page type | Typical scale |
|---|---|
| Per-cell site plans (פיתוח, אשפה, פונקציות, מרתף, קומה טיפוסית) | 1:500 |
| Whole-site development plan (תכנית פיתוח כללית) | 1:1250 |
| Cross-sections (חתכים) | 1:750 |
| Elevations (חזיתות) | 1:750 |

---

## 6. The unit-mix table (the critical Ellen-input)

The most important data structure in any תכנית עיצוב from a project-configuration
perspective is the **ריכוז תמהיל דירות** table, appearing on each cell's קומה טיפוסית
page (or a separate summary page).

### Observed structure (cell 1 of Hetzeisim):

| סוג (Type) | שטח (Area, m²) | דירות תמורה (Eviction-replacement units) | דירות יזם (Developer units) | אחוז יזם (Developer %) | סה"כ יח"ד (Total) | אחוז סה"כ (Total %) |
|---|---|---|---|---|---|---|
| 2 חדרים (2 rooms) | 57–61 | 8 | 9 | 6% | 17 | 7% |
| 3 חד' קטנה (3 small) | 62–81 | 16 | 19 | 12% | 35 | 15% |
| 3 חד' גדולה (3 large) | 82–94 | 16 | 7 | 4% | 23 | 10% |
| 4 חדרים (4 rooms) | 96–109 | 32 | 23 | 14% | 55 | 24% |
| 5 חדרים (5 rooms) | 110–135 | 0 | 74 | 46% | 74 | 32% |
| 6 חדרים (6 rooms) | 136–153 | 0 | 12 | 8% | 12 | 5% |
| מיוחדות (Special) | מעל 155 | 0 | 16 | 10% | 16 | 7% |
| **סה"כ (Total)** | | **72** | **160** | **100%** | **232** | **100%** |

### Schema implication

This table is **not** a fixed template — it is the **output** of project-configuration
inputs Ellen fills in per תא שטח:

**Inputs Ellen provides (per תא שטח):**
- `total_units_target` (e.g., 232)
- `developer_unit_count` and `eviction_replacement_count` (e.g., 160 / 72; ratio set by
  project-level תמורה/יזם split)
- `unit_size_brackets` (the 7 bracket definitions: type label + area range)
- `units_by_type_and_party` (the 7×2 matrix of how many units of each type belong to each
  party)

**Outputs the system computes:**
- Percentages within each row (developer %, total %)
- Column totals
- Validation: do row-totals match the per-bracket totals? Does the sum match the
  schema-declared `total_units_target`?

Per `userMemories`: "תמורה/יזם split, parking ratios, and apartment sizes are per-project
INPUT fields Ellen fills in, not hardcoded policy." This table is the primary place those
inputs surface.

### Ranges across the reference document

The reference document shows similar tables for cells 2+4, 3, and 5. Across these cells,
the bracket *labels* (2 חדרים, 3 קטנה, 3 גדולה, etc.) are consistent, but the **area
ranges** can vary slightly (e.g., 4 חדרים might be 96–109 in one cell and 95–110 in
another). The number of brackets (7) is consistent. **Tentative**: this consistency may
hold across plans, or it may be Kika Braz's house style. Verify against more documents.

---

## 7. Standard footer / branding block

Every page (except cover and TOC) closes with a footer containing:

- **Page number** (large, leftmost)
- **Architect firm logo + name** ("KIKA BRAZ ARCHITECTS & URBAN PLANNERS" in the reference;
  rightmost-leftish)
- **Engineering consultant logos** (AURA, הנדסה — left of architect logo)
- **Municipal authority logos** ("Municipality of Ness Ziona" + "מינהלת התחדשות עירונית"
  + city seal — rightmost)
- **Title strip**: "תכנית עיצוב" (right edge)

For NZC-generated תכניות עיצוב, the architect/firm logos will vary per project; the
municipal block is consistent.

The footer is approximately the bottom 80–100 pt of every page.

---

## 8. Cover page conventions

The reference cover shows:
- **Project name** prominently: "מתחם הטייסים – נס ציונה"
- **Document type**: "תכנית עיצוב"
- A large rendering or image (labeled "הדמייה להמחשה בלבד" — "for illustration only")
- Footer block as above

No date, version, or revision number is on the cover page — only inferred from filename
("23.3" = revision 23.3) and PDF metadata. **Tentative**: a version/date block on the
cover would be a useful addition for generated documents.

---

## 9. תב"ע summary table (page 6 in reference)

A standardized summary of the statutory plan(s) the design plan implements. Observed
fields:

| Field | Example value |
|---|---|
| מצב מאושר — יח"ד (כולל במ"ר) | 700 יח"ד |
| שצ"פ (דונם) | 3.1 |
| שב"צ (דונם ובמ"ר) | 2.08 / 2,086 m² |
| שטח בנוי ציבורי (במ"ר) | 10,800 (incl. 700 m² public space within residential) |
| דרכים (דונם) | 1.5 |
| שבילים | אין / present |
| צפיפות נטו | 42.3 |
| צפיפות ברוטו | 30.1 |
| רח"ק (residential building rights coefficient) | ~4,300 |

Plus a breakdown table by יעוד:

| יעוד | שטח (m²) | אחוז |
|---|---|---|
| מגורים | 16,528 | 71.12% |
| שב"צ | 2,086 | 9% |
| שצ"פ | 3,113 | 13.4% |
| דרך | 1,512 | 6.5% |
| **סה"כ ציבורי** | 6,711 | 28.8% |
| **סה"כ** | 23,234 | 100% |

These values come directly from the statutory plan(s) and should be auto-populated from
the project schema. They do not change between revisions of the design plan unless the
underlying תב"ע is amended.

---

## 10. Cross-sections (חתכים) and elevations (חזיתות)

### Cross-sections (חתכים)

Cross-sections cut through the site along defined lines (typically labeled א-א, ב-ב,
ג-ג). Each section shows:

- Buildings as silhouettes from the cut line outward
- Floor lines drawn across each building with elevation markers at each floor
- Color-coded floor uses (per §4 palette)
- Building codes (A1, B1, etc.) at the top of each silhouette
- Land-form (existing topography line) drawn in
- Trees and vegetation in elevation
- Cell boundaries shown in dashed/colored lines

Standard scale: **1:750**. Each section runs across the full A3 landscape page.

### Elevations (חזיתות)

Street-facing facades drawn from each surrounding street. The reference shows:

- "חזית רח' ההסתדרות" (Histadrut St. facade)
- "חזית רח' הטייסים" (Pilots St. facade) — separate page
- Plus internal-street elevations

Each elevation shows building facades along the street, side by side, at scale 1:750.
Building codes labeled at each base, with floor count (`ק+9`, `ק+13`) and absolute height
(`+32.85 / +85.00`). Trees in foreground, drawn in solid green/gray.

### Implications for generation

Both חתכים and חזיתות are **vector drawings**, not text + tables. They cannot be
generated from Markdown or HTML. The realistic path for automated generation is:

1. Compute building geometry (footprint, height per floor, floor uses) from project schema
2. Render to SVG using a vector library (or DXF for AutoCAD compatibility)
3. Place into A3 InDesign template at the right scale and position

This is **out of scope for Phase 3** but should be planned for Phase 4+. For early MVPs,
these sections can be marked as "manually inserted by architect" in generated documents.

---

## 11. Boilerplate / standard text

### Cover/page-level
- "תכנית עיצוב" appears on every page (typically in the title strip)
- "מתחם {plan_name} – {city}" (e.g., "מתחם הטייסים – נס ציונה") appears as a top header
  on every page
- "הדמייה להמחשה בלבד" appears next to every rendering (means "for illustration only" — a
  legal disclaimer)

### Scale annotations
- "קנ"מ 1:500" for site plans
- "קנ"מ 1:1250" for the overall development plan
- "קנ"מ 1:750" for cross-sections and elevations

### Renderings disclaimer
Every page containing a 3D rendering should include "הדמייה להמחשה בלבד" near the
rendering. This is a legal protection against the renderings being treated as binding
representations.

---

## 12. What's NOT in a תכנית עיצוב (per §145(ז))

The official guide from מינהל התכנון (10.11.2024) is explicit that תכנית עיצוב **cannot
include** matters reserved for the statutory plan (תב"ע) under §145(ז). Specifically:

- Land-use designations (those come from תב"ע)
- Number of units (those come from תב"ע)
- Building footprint areas (those come from תב"ע)
- Maximum building heights (those come from תב"ע)
- Building lines / setbacks (those come from תב"ע)

The תכנית עיצוב **can include**:
- Building placement *within* the building lines defined by תב"ע
- Floor-by-floor uses and unit mix (within the total allowed)
- Vehicle access patterns
- Infrastructure routing
- Public-use zone layouts
- Landscape and microclimate design
- Easements and access rights
- Plantings

This is a **compliance check the platform should run** when validating a submitted
תכנית עיצוב — flag any field that asserts statutory matters as out-of-scope for the
document type.

---

## 13. Open questions (to revisit when more reference plans are available)

1. **Cover-page metadata**: Should generated cover pages include date/version/revision
   block? Reference does not, but it would aid auditability.
2. **Unit-mix bracket consistency**: Are the 7-row bracket definitions consistent across
   architects, or Kika Braz's convention? Other Ness Ziona plans by other firms would tell
   us.
3. **חזון ערכי לפארק** (4 pages of "values vision" for the park): Is this a standard
   section in every תכנית עיצוב, or specific to plans with significant שצ"פ? Would be
   absent in plans without substantial public open space.
4. **Daycare integration**: Reference shows מעונות יום integrated as ground-floor uses in
   specific buildings (e.g., C1). Is this a Ness-Ziona-specific requirement (the city
   prioritizing in-building daycare for new families) or universal?
5. **Footer logos**: Are AURA and הנדסה consultants on every project, or specific to this
   one? Generated documents should pull this from project metadata.

---

## 14. Update protocol

When a new reference תכנית עיצוב becomes available, update this skill by:

1. Comparing its structure against §2 (TOC). Note any new sections, missing sections, or
   reordering.
2. Comparing per-תא-שטח sequence against §3. Note variations.
3. Adding new color palette entries to §4 if observed.
4. Verifying the unit-mix table structure (§6) — bracket count, column structure,
   percentage handling.
5. Revising the `confidence` field in the frontmatter.
6. Listing the new reference in `reference_document` (multiple values OK).
7. Updating `last_updated`.

The goal: as the reference base grows from 1 to 5+ documents, this skill transitions from
**descriptive of one document** to **prescriptive across the genre**.
