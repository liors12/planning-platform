# Submission Coverage Report — v24.3

**Date:** 2026-05-24
**Investigator:** Claude Code
**Submission:** `projects/407-1048248/submissions/v24.3/v24.3.pdf` (63 pages)
**Engine output:** `audit_outputs/407-1048248/v24.3/audit_results.json` (79 content + 33 disciplines + 34 format findings = 146 total)
**M1 manifests:** `data/projects/407-1048248/submissions/v24.3/page_manifests.json`
**Generated review PDF:** `audit_outputs/407-1048248/v24.3/audit_report_24.3.pdf`

## Question answered

For every page in the architect's submission (v24.3), does the review actually check what's on it? Three buckets: FULL (every meaningful element addressed), PARTIAL (some elements addressed, others listed in the "Unaddressed elements" column), UNADDRESSED (nothing on this page referenced by any finding).

## Summary

| Status | Page count | % of submission |
|--------|------------|-----------------|
| **FULL coverage** | 54 | 54/63 = **85.7%** |
| **PARTIAL coverage** | 8 | 8/63 = **12.7%** |
| **UNADDRESSED** | 1 | 1/63 = **1.6%** |

**Headline:** 85.7% of submitted pages are fully addressed. Of the remaining 14.3% (9 pages), almost all fall into 3 known buckets: daycare (no rule type exists), unmapped design-doc plot numbers (Task #27), and ad-hoc comparative/structural tables that no rule template targets.

## Per-page coverage table (all 63 pages)

| Page | page_type | ta_shetach | Coverage | Unaddressed elements |
|------|-----------|------------|----------|----------------------|
| 1 | rendering | — | **FULL** | — |
| 2 | table_of_contents | 2, 4, 3, 5, 1 | **PARTIAL** | table "תוכן עניינים" — no dedicated rule check |
| 3 | rendering | — | **FULL** | — |
| 4 | rendering | — | **FULL** | — |
| 5 | rendering | — | **FULL** | — |
| 6 | site_plan_per_ta_shetach | — | **PARTIAL** | table "מצב מאושר" — no dedicated rule check; table "נושא" — no dedicated rule check |
| 7 | summary | — | **FULL** | — |
| 8 | summary | 52, 64, 20 | **PARTIAL** | unmapped plots [52, 64] (Task #27) |
| 9 | site_plan_per_ta_shetach | 1, 2, 3, 4, 5 | **FULL** | — |
| 10 | site_plan_per_ta_shetach | 1, 2, 3, 4, 5 | **FULL** | — |
| 11 | site_plan_per_ta_shetach | 3, 5 | **FULL** | — |
| 12 | other | — | **UNADDRESSED** | "other"-type page; no canonical rule maps to it |
| 13 | public_open_space | 52, 54 | **PARTIAL** | unmapped plots [52, 54] (Task #27) |
| 14 | site_plan_per_ta_shetach | 52, 54 | **PARTIAL** | unmapped plots [52, 54] (Task #27) |
| 15 | public_open_space | — | **FULL** | — |
| 16 | public_open_space | 5 | **FULL** | — |
| 17 | public_open_space | 3 | **FULL** | — |
| 18 | public_open_space | 5 | **FULL** | — |
| 19 | public_open_space | 5 | **FULL** | — |
| 20 | cross_section | 2, 4 | **FULL** | — |
| 21 | cross_section | 1, 2 | **FULL** | — |
| 22 | cross_section | 5, 3 | **FULL** | — |
| 23 | cross_section | 1 | **FULL** | — |
| 24 | site_plan_per_ta_shetach | 1 | **FULL** | — |
| 25 | waste_diagram | 1 | **FULL** | — |
| 26 | functions_diagram | 1 | **FULL** | — |
| 27 | daycare | 1 | **PARTIAL** | no daycare-specific rule exists in engine |
| 28 | daycare | 1 | **PARTIAL** | no daycare-specific rule exists in engine |
| 29 | basement_with_parking_table | 1 | **FULL** | — |
| 30 | typical_floor | 1 | **FULL** | — |
| 31 | rendering | 1 | **FULL** | — |
| 32 | rendering | 1 | **FULL** | — |
| 33 | rendering | 1 | **FULL** | — |
| 34 | site_plan_per_ta_shetach | 2, 4 | **FULL** | — |
| 35 | waste_diagram | 2, 4 | **FULL** | — |
| 36 | functions_diagram | 2, 4 | **FULL** | — |
| 37 | basement_with_parking_table | 2, 4 | **FULL** | — |
| 38 | typical_floor | 2, 4 | **FULL** | — |
| 39 | site_plan_per_ta_shetach | 3, 5 | **FULL** | — |
| 40 | waste_diagram | 3 | **FULL** | — |
| 41 | functions_diagram | 3 | **FULL** | — |
| 42 | basement_with_parking_table | 3 | **PARTIAL** | table "מרתף טיפוסי" — no dedicated rule check |
| 43 | typical_floor | 3 | **FULL** | — |
| 44 | waste_diagram | 5 | **FULL** | — |
| 45 | functions_diagram | 5 | **FULL** | — |
| 46 | basement_with_parking_table | 5 | **FULL** | — |
| 47 | typical_floor | 5 | **FULL** | — |
| 48 | cross_section | 1, 2, 3 | **FULL** | — |
| 49 | cross_section | 1, 4, 5, 3 | **FULL** | — |
| 50 | cross_section | 3, 5 | **FULL** | — |
| 51 | cross_section | 1, 3, 4 | **FULL** | — |
| 52 | elevation | 3, 2, 1 | **FULL** | — |
| 53 | elevation | 1, 2, 3 | **FULL** | — |
| 54 | elevation | 5, 4 | **FULL** | — |
| 55 | elevation | 4, 5 | **FULL** | — |
| 56 | elevation | 2, 4 | **FULL** | — |
| 57 | elevation | 4, 2 | **FULL** | — |
| 58 | elevation | 3, 5 | **FULL** | — |
| 59 | elevation | 5 | **FULL** | — |
| 60 | elevation | 3 | **FULL** | — |
| 61 | elevation | 1 | **FULL** | — |
| 62 | elevation | 1 | **FULL** | — |
| 63 | rendering | — | **FULL** | — |


## Aggregate gap summary

What categories of submission content are systematically missed across the report:

### 1. Daycare design (2 pages, plot 1)
- **Pages affected:** 27, 28
- **What's submitted:** detailed daycare floor plans, area breakdowns (280 m² ground floor, 195 m² courtyards, 500 m² floor 1)
- **What's checked:** nothing. The engine has zero rules for daycare-specific compliance (size requirements, accessibility, outdoor space ratios, etc.) and there's no `daycare` discipline.
- **Status:** **NEW GAP** (not in existing backlog)
- **Severity for Ellen:** moderate — a planning reviewer would expect daycare yards / room counts / accessibility paths to be checked, especially given Israeli planning code requirements (תקנות מעונות יום).

### 2. Unmapped plot numbers from design doc (3 pages)
- **Pages affected:** 8, 13, 14
- **Plot refs unmapped:** 52, 54, 64 (the design doc's parallel numbering scheme — likely commercial / public-amenity zones with separate cadastral numbering)
- **What's checked:** the takanon-plot subset (20) is checked for page 8; plots 52/54/64 are completely skipped because no mapping table exists.
- **Status:** **KNOWN — Task #27** (M2 reconciliation)
- **Severity for Ellen:** high — these are the מבני ציבור + מסחר zones; their entire compliance check is currently empty.

### 3. Phasing / "other" structural pages (1 page)
- **Pages affected:** 12 (שצ"פ phasing diagram with מתחם 1/2/3 → שלב א/ב/ג labels)
- **What's checked:** nothing. The page is a phasing/staging diagram and the engine has no rules for phasing constraints (sequencing, prerequisite infrastructure, etc.).
- **Status:** **KNOWN — Task #29** (phasing category has 0 rules)
- **Severity for Ellen:** low to moderate — phasing affects construction order and infrastructure coordination, not architectural compliance per se.

### 4. Ad-hoc tables in submission with no matching rule template
- **Pages affected:** 2 (תוכן עניינים table), 6 (מצב מאושר / נושא comparison tables), 42 (מרתף טיפוסי table — basement-level summary, distinct from the parking-ratio table the engine does check)
- **What's checked:** the engine checks parking-ratio tables (page 46 etc.) and mix tables (page 30 etc.), but freestanding comparison/summary tables aren't templated.
- **Status:** **NEW GAP** (low priority — these tables are structural / navigation, not normative)
- **Severity for Ellen:** low.

### 5. Easements (NOT directly visible in submission but flagged in M0)
- **Pages affected:** 0 in submission (no easement diagrams in v24.3)
- **What's missed:** the takanon has 8 normative easement clauses, none checked by any rule.
- **Status:** **KNOWN — Task #28**
- **Severity for Ellen:** depends — if v24.3 doesn't address easements explicitly, this is "scope-gap" not "review-gap." Worth a heads-up.

## Per-discipline gap check (10 disciplines)

| # | Discipline | Findings | Page types it should cover | Pages potentially missed |
|---|---|---|---|---|
| 1 | shafa (אשפה) | 4 | waste_diagram | ✓ All 4 waste_diagram pages (25, 35, 40, 44) addressed |
| 2 | gardens (גנים ונוף) | 3 | public_open_space, site_plan | ✓ Covered globally; rules apply across all site/POS pages |
| 3 | infra (תשתיות) | 3 | functions_diagram, basement | ⚠ functions diagrams (26, 36, 41, 45) — infra mentioned globally but not page-specific |
| 4 | fire (רחבות כיבוי אש) | 3 | site_plan, functions_diagram | ✓ Globally applied |
| 5 | drainage (ניקוז) | 4 | public_open_space, site_plan, cross_section | ✓ Globally applied |
| 6 | roofs (גגות) | 3 | typical_floor, elevation | ⚠ Globally applied; no per-plot roof check |
| 7 | arch (אדריכלות) | 5 | elevation, rendering, typical_floor | ✓ Covered (includes materials annex finding) |
| 8 | balcony (מרפסות) | 2 | typical_floor, elevation | ✓ Globally applied; only 2 findings for 11 elevation + 4 typical_floor pages — **rule density LOW** |
| 9 | laundry (מסתורי כביסה) | 2 | elevation | ✓ Globally applied; LOW rule density |
| 10 | env (סביבתי) | 4 | summary | ✓ Globally applied (acoustic / hydrological annexes flagged as missing) |

**Discipline-level summary:** all 10 disciplines have at least 2 findings each (33 total). The disciplines are applied **globally** (not per-plot), so a single discipline finding effectively covers all pages that touch that domain. Coverage is broad but shallow — `balcony` and `laundry` have only 2 findings each, which Ellen may flag as "too thin for a 5-plot, 700-unit submission."

## Methodology notes

- A page is **FULL** if (a) for every plot ref on the page, the expected per-plot CONTENT rules are present in the audit, AND (b) the expected disciplines for that page_type have at least one finding, AND (c) the plan-level rules that apply (e.g., `CONTENT_APARTMENT_MIX_SMALL`, `CONTENT_PERMEABLE_SURFACES`) are in the audit.
- A page is **PARTIAL** if some expectations are met but at least one is missing or one of: unmapped plot refs, untemplated table, no daycare-rule-type-exists.
- A page is **UNADDRESSED** if no expected rule/discipline applies to its page_type at all (the "other" bucket).
- Plan-level rules (`CONTENT_APARTMENT_MIX_SMALL` and `CONTENT_PERMEABLE_SURFACES` have `ta_shetach_id=null`) are counted ONCE for the whole submission, not per-plot — matching how the engine actually applies them.
- Renderings count as FULL via FORMAT_RENDERINGS_PRESENT + arch discipline. Strictly visual content has no per-page numeric to check.

## Recommendations for what to tell Ellen (in order of importance)

1. **Daycare not reviewed.** Pages 27-28 detail מעונות יום and the engine doesn't check them. If Ellen cares about daycare compliance (areas, outdoor space, etc.), call this out explicitly in the cover note.
2. **Public/commercial zones (plots 52/54/64) not reviewed.** Pages 8, 13, 14 — these are the מבני ציבור + מסחר; current engine plot scheme doesn't reach them. Task #27 fixes this in M2.
3. **Discipline rule density is thin for some domains.** Only 2 findings each for `balcony` and `laundry` across 4-11 relevant pages. Ellen may expect more granularity.
4. **Phasing not reviewed.** Page 12 (שצ"פ phasing) has zero compliance check. Task #29.
5. **Easements not in scope of current rule set.** 8 normative takanon clauses unchecked. Task #28 — likely not visible to Ellen since v24.3 doesn't have easement diagrams, but worth a footnote.

**Overall:** 85.7% page-level coverage is reasonable for a v1 review pass. The 14.3% gap is concentrated in known-issue buckets, not silent failures.
