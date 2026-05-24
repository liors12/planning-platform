# PDF Design + Coverage Report — v24.3

**Date:** 2026-05-24
**Investigator:** Claude Code
**Reference PDF (v6):** `/Users/liorlevin/Downloads/v6_design_reference.pdf` (55 KB, 6 pages, dated 2026-05-17 08:35)
**New PDF:** `/Users/liorlevin/Desktop/planning-platform/audit_outputs/407-1048248/v24.3/audit_report_24.3.pdf` (272 KB, 35 pages, generated 2026-05-24 06:52)
**Engine output:** `/Users/liorlevin/Desktop/planning-platform/audit_outputs/407-1048248/v24.3/audit_results.json` — **byte-identical to baseline** `tests/regression/v8j_baseline_v24.3.json` (sha `8c5627f9…2fef8`). Any divergence is in the PDF generator, not the engine.

---

# Part A — Design comparison

## A1. RTL alignment focus check

**RTL is NOT regressed.** Hebrew body text, headers, table cells, and footers read right-to-left correctly across all sampled pages. Inspection of `compliance_engine/report_generator.py`:
- `html { direction: rtl; }` (line 91)
- `body { direction: rtl; ... }` (line 93)
- `table { direction: rtl; ... }` (line 392)
- `<html lang="he" dir="rtl">` (line 571)

The "not right-aligned" complaint is driven by a **specific layout choice on the cover page**: `.cover .data-block .label { min-width: 36mm; display: inline-block; }` (line 213-218) forces labels into a fixed-width column, pushing values far to the left and creating a visual "spread" that reads as misaligned. Body content is fine.

Rasters viewed: `/tmp/pdf_compare/{v6_ref,new}_p{01,02,03,05,06,29,35}.png` (150 DPI).

## A2. Git archaeology for the historical RTL fix

- **Only commit touching `compliance_engine/`:** `f50765e` ("Phase 1 + 2a + 2b baseline (2026-05-19, pre-versioning)") — a single bulk commit. No incremental history of an RTL "fix" to recover from.
- **`compliance_engine/report_generator.py:3`** says CSS was "**lifted verbatim from `v6_design_reference (2).html`**" — that's the **2nd iteration** of the v6 design (file dated 2026-05-17 13:49, dark-green cover). Lior's reference PDF is from the **1st iteration** (file dated 2026-05-17 08:35, white cover). The code matches a different snapshot than the comparison target.
- **Dead code paths:** `compliance_engine/templates/audit_report.css` and `compliance_engine/templates/audit_report.html.jinja` exist but are never imported. The generator builds HTML by string concatenation in `_render_*` functions and uses inline `_CSS` (line 80). The templates directory is leftover scaffolding.

## A3. 9-checkpoint design comparison

| # | Checkpoint | v6 reference | New PDF | Verdict |
|---|---|---|---|---|
| 1 | Cover — NZC branding, plan #/version, draft watermark | **White** background, **centered** title, eyebrow "המינהלת להתחדשות עירונית — עיריית נס ציונה", subtitle "מתחם הטייסים-ההסתדרות", inline-text watermark | **Dark green** full-bleed, title mid-right, eyebrow **clipped behind absolute-positioned logo**, watermark as **pill button**, NZC label split across two lines | ✗ **REGRESSED** (visual theme + clipping) |
| 2 | TOC structure | Compact 1-page table, number column "1./2./3./4." styled as bullets, page #'s on left | Wide spaced rows with dotted separators, numbers inline with title, spans 2 pages | ⚠ **DIFFERENT** (denser spacing) |
| 3 | 4-section structure (Urban / Content / Multidisciplinary / Summary) | Sec 1 (p5), 2 (p3), 3 (p4), 4 (p5) | Sec 1 (p4), 2 (p5), 3 (p18), 4 (p29) | ✓ **MATCHES** |
| 4 | Appendix A — Format issues | Dedicated divider page "נספח א" (letter-spaced characters) + intro line; format issues follow | **No divider page**. Format issues appear as numbered "סעיף 6.10 (4 ליקויים)" sections embedded in body | ✗ **REGRESSED** (missing divider) |
| 5 | Verdict counts at section openers | 5 cards consistently (תקינים / ליקויים / דורשים בירור / לא ניתנים / לא רלוונטיים) | 5 on §2 (15/27/11/0/26), **4** on §3 (9/8/16/0 — missing "לא רלוונטיים"), **3** on §4 (24/35/27) | ⚠ **INCONSISTENT** |
| 6 | Per-תא-שטח tables — נושא בדיקה / ממצא / בהגשה / בתב"ע / הערה | Columns: נושא בדיקה / ממצא / **בהגשה** / בתב"ע / הערה | Columns: נושא בדיקה / ממצא / **בתוכנית עיצוב** / בתב"ע / הערה | ⚠ **DIFFERENT** (col-3 label changed) |
| 7 | Action items numbered list in summary | Numbered 1./2./3. with bold lead-in + cross-plot grouping | Numbered 1-5 with bold lead + cross-plot grouping ("**שטח עיקרי (מ"ר) — תא שטח 1, 2, ...**") | ✓ **MATCHES** |
| 8 | Footer pagination + "מינהלת התחדשות עירונית נס ציונה — סקירת תוכנית עיצוב N/M" | "6 / 2 ... · עמ' 2" | "35 / 2 ..." (**dropped "· עמ' N" suffix**) | ⚠ **DIFFERENT** |
| 9 | Brand color NZC green (`#005030`) | Used as accent for titles, borders, badges on **white** background | Same hex tokens applied; cover uses `#005030` as **full background** (white text on green) | ⚠ **DIFFERENT** (tokens same, application changed) |
| — | RTL alignment | ✓ R→L throughout | ✓ R→L throughout | ✓ **NOT REGRESSED** |

**Aggregate Part A:** 1 ✓ RTL + 2 ✓ matches + 5 ⚠ different + 2 ✗ regressed.

---

# Part B — Coverage check

## B1. Per-תא-שטח coverage

**Plots in submission (M1):** `{1, 2, 3, 4, 5, 20, 52, 54, 64}` (9 unique plot refs across 63 manifests)
**Plots checked in audit content findings:** `{plot_1, plot_2, …, plot_10, plot_20}` (11 plot buckets)
**Plots in disciplines findings:** none — disciplines are global, not per-plot.

| Plot | In submission (M1)? | In audit findings? | Status |
|---|---|---|---|
| 1 | ✓ | ✓ (7 findings) | ✓ COVERED |
| 2 | ✓ | ✓ (7 findings) | ✓ COVERED |
| 3 | ✓ | ✓ (7 findings) | ✓ COVERED |
| 4 | ✓ | ✓ (7 findings) | ✓ COVERED |
| 5 | ✓ | ✓ (7 findings) | ✓ COVERED |
| 6 | ✗ | ✓ (7 findings) | ⚠ PHANTOM (audited though not in submission) |
| 7 | ✗ | ✓ (7 findings) | ⚠ PHANTOM |
| 8 | ✗ | ✓ (7 findings) | ⚠ PHANTOM |
| 9 | ✗ | ✓ (7 findings) | ⚠ PHANTOM |
| 10 | ✗ | ✓ (7 findings) | ⚠ PHANTOM |
| 20 | ✓ | ✓ (7 findings) | ✓ COVERED |
| 52 | ✓ | ✗ | ⚠ GAP (design-doc parallel numbering, Task #27) |
| 54 | ✓ | ✗ | ⚠ GAP (design-doc parallel numbering, Task #27) |
| 64 | ✓ | ✗ | ⚠ GAP (design-doc parallel numbering, Task #27) |

**Interpretation:**
- The audit is anchored on the **takanon's plot scheme** (plots 1–10 + 20), generating findings for every plot defined there, even when v24.3 submission only covers 5 of them.
- Plots 6–10 are **"phantom" plot findings** — `not_submitted` verdicts for plots that the submission deliberately omits. This is actually the correct behavior (the takanon defines them; the submission should eventually cover them; calling out the gap is useful).
- Plots 52/54/64 (design-doc's parallel numbering, surfaced by M1) are NOT mapped to takanon plots — known Task #27 reconciliation backlog for M2.

## B2. Clause coverage

**M0 normative clauses:** 93 of 177 total (53%), in 13 categories. 32 of the 93 are quantitative.

**Audit content rules applied:** 9 unique `rule_code` values across 79 content findings:
| Rule code | Category it addresses |
|---|---|
| CONTENT_UNIT_COUNT | building_rights / building_use |
| CONTENT_BUILDING_AREA_MAIN | building_rights |
| CONTENT_BUILDING_AREA_SERVICE_ABOVE | building_rights |
| CONTENT_BUILDING_AREA_SERVICE_BELOW | building_rights |
| CONTENT_BUILDING_HEIGHT | building_geometry, building_height_safety |
| CONTENT_SETBACKS | building_geometry |
| CONTENT_PARKING_RATIO | parking |
| CONTENT_APARTMENT_MIX_SMALL | building_use |
| CONTENT_PERMEABLE_SURFACES | stormwater |

**Audit format rules applied:** 34 unique `FORMAT_*` codes covering the entire `procedural` category (cover, TOC, footer, fonts, page size, RTL declaration, required chapters, signature blocks, etc.).

**Audit discipline rules applied:** 33 findings across 10 disciplines (see B3).

**Coverage by clause category (structural — no clause_id refs in audit output, so this is category-level):**

| Category | M0 normative clauses | Addressed by audit? | Notes |
|---|---|---|---|
| infrastructure | 15 | ⚠ partial | Disciplines `infra` (3 findings), `drainage` (4) — but no `CONTENT_INFRA_*` rules. Category covered through discipline layer only. |
| procedural | 13 | ✓ full | 34 FORMAT_* rules thoroughly cover this. |
| building_use | 12 | ⚠ partial | Only `CONTENT_APARTMENT_MIX_SMALL` + `CONTENT_UNIT_COUNT` — 2 rules for 12 clauses. |
| building_geometry | 11 | ⚠ partial | `CONTENT_BUILDING_HEIGHT` + `CONTENT_SETBACKS` — 2 rules for 11 clauses. |
| stormwater | 11 | ⚠ partial | `CONTENT_PERMEABLE_SURFACES` + discipline `drainage` (4 findings). |
| easements | 8 | ✗ none | No dedicated rule, no discipline coverage. **GAP**. |
| tree_preservation | 7 | ⚠ partial | Possibly covered via `gardens` discipline (3 findings) but no explicit tree rule. |
| building_height_safety | 5 | ⚠ partial | `CONTENT_BUILDING_HEIGHT` overlaps; fire safety via `fire` discipline (3 findings). |
| parking | 4 | ✓ adequate | `CONTENT_PARKING_RATIO` directly addresses. |
| phasing | 3 | ✗ none | No rule, no discipline coverage. **GAP**. |
| public_areas | 2 | ⚠ partial | `gardens` discipline (3 findings) tangentially. |
| building_rights | 1 | ✓ adequate | 3 BUILDING_AREA_* rules + UNIT_COUNT. |
| identification | 1 | ✓ adequate | FORMAT_COVER_PLAN_NUMBER / FORMAT_VERSION_NOTATION. |

**Coverage summary:**
- ✓ **Fully or adequately covered (4 categories, 19 clauses):** procedural, parking, building_rights, identification
- ⚠ **Partially covered (7 categories, 69 clauses):** infrastructure, building_use, building_geometry, stormwater, tree_preservation, building_height_safety, public_areas
- ✗ **Not covered at all (2 categories, 11 clauses):** easements, phasing
- **Structural coverage:** 11/13 categories = **85%** by category breadth. **Rule density** is shallow: 9 content + 10 disciplines = 19 distinct rule types for 93 normative clauses (~20% if you treated each clause as needing its own rule).

## B3. Per-discipline coverage (10 disciplines)

Verified `compliance_engine/report_generator.py:45-56` (`DISCIPLINE_NAME_HE`) and TOC output in `new_p02.png`:

| # | discipline code | Hebrew section title | Findings | TOC position |
|---|---|---|---|---|
| 1 | shafa | שפ"ע — אשפה ופינוי פסולת | 4 | 3.1 |
| 2 | gardens | גנים ונוף | 3 | 3.2 |
| 3 | infra | תשתיות | 3 | 3.3 |
| 4 | fire | רחבות כיבוי אש | 3 | 3.4 |
| 5 | drainage | ניקוז וחלחול | 4 | 3.5 |
| 6 | roofs | גגות וגינון על גג | 3 | 3.6 |
| 7 | arch | אדריכלות וחזיתות | 5 | 3.7 |
| 8 | balcony | מרפסות | 2 | 3.8 |
| 9 | laundry | מסתורי כביסה | 2 | 3.9 |
| 10 | env | הנחיות סביבתיות | 4 | 3.10 |

**✓ All 10 disciplines present in both code, audit findings, and rendered TOC.**

## B4. Sample-based submission coverage (5 random M1 manifests)

Random sample (seed 101), one per page-type bucket:

| M1 page | page_type | ta_shetach_refs | Relevant audit findings | Verdict |
|---|---|---|---|---|
| 11 | site_plan_per_ta_shetach | [3, 5] | 14 content findings for plots 3+5 (incl. 2 SETBACKS for plot 3 and 5); discipline `gardens` (3 findings) globally applies | ✓ COVERED |
| 42 | basement_with_parking_table | [3] | 7 content findings for plot 3 incl. `CONTENT_PARKING_RATIO` ("תקן חניה") | ✓ COVERED |
| 17 | public_open_space | [3] | 7 content findings for plot 3; 7 discipline findings (gardens 3 + drainage 4) directly relevant to שצ"פ design | ✓ COVERED |
| 25 | waste_diagram | [1] | 7 content findings for plot 1; 4 `shafa` discipline findings ("חדרי פסולת קומתיים", "רחבת גזם ייעודית", "ללא כניסת משאיות אשפה", "מערכת איסוף אשפה פניאומטית") | ✓ COVERED |
| 23 | cross_section | [1] | 7 content findings for plot 1 incl. `CONTENT_BUILDING_HEIGHT` ("גובה הבניין") | ✓ COVERED |

**Sample verdict: 5/5 covered.** Every random manifest had at least one targeted finding in the report. No "submission content with zero report coverage" was found in this sample.

---

# Combined verdict

| Axis | Verdict |
|---|---|
| **Design fidelity to v6 reference** | ✗ **REGRESSED** — 2 outright regressions (cover theme, missing Appendix A divider) + 5 differences (TOC spacing, verdict-card inconsistency, column label "בהגשה" → "בתוכנית עיצוב", footer "עמ'" prefix dropped, brand-color application). RTL is intact. |
| **Coverage adequacy** | ⚠ **ADEQUATE with documented gaps** — All in-submission plots (1-5, 20) covered with 7 findings each; all 10 disciplines present; per-plot sample 5/5 covered. Gaps: (a) 2 of 13 normative-clause categories have zero rules (easements, phasing); (b) plots 52/54/64 from M1 design-doc numbering not mapped to takanon plots (Task #27 known caveat); (c) phantom-plot findings for 6-10 are correct behavior (takanon-defined) but worth understanding. |
| **Combined** | ⚠ **NEEDS FIXES (design)** but coverage is shippable. Design issues are visible to every reader on page 1; coverage gaps are second-order and already on the M2 backlog. |

---

# Proposed fixes (NOT applied — awaiting Lior's go)

All fixes are in `compliance_engine/report_generator.py` (engine untouched, baseline stays byte-identical).

### Design fixes

**Fix A — Restore minimalist white cover** (highest user-visible priority)
- File: `compliance_engine/report_generator.py:160-235`
- Remove `background: #005030` from `.cover` (line 162) → white background
- Recolor `.cover` text from white to NZC green for title + dark gray for body
- Remove `min-width: 36mm` from `.cover .data-block .label` (line 216) → labels cluster with values, no extreme spread
- Reposition `.cover .logo` from absolute-top-right (line 170-176) to inline above title to avoid clipping the eyebrow text
- Drop title `42pt` → ~`30pt` (line 194) and center it
- Replace green-pill watermark with inline text "טיוטה לסקירה — לא לחתימה" matching v6

**Fix B — Add Appendix A divider page**
- File: `compliance_engine/report_generator.py:566` (already calls `_render_appendix_divider()`)
- Verify the function emits the letter-spaced "נ ס פ ח א" + intro per v6_p06 (currently produces empty/no output that's why we don't see it)
- The CSS `@page appendix-divider` (line 128) already exists — confirm `.appendix-divider` class is applied

**Fix C — Verdict-card consistency**
- `_render_section_3` and `_render_section_4` use different card sets vs `_render_section_2`. Standardize to 5 cards (תקינים / ליקויים / דורשים בירור / לא ניתנים / לא רלוונטיים) and pass `0` when bucket doesn't apply.

**Fix D — Restore "עמ'" prefix in footer**
- `@page` `@bottom-left` declaration (~lines 95-122). Change `counter(page) " / " counter(pages)` to add "· עמ' " marker matching v6.

**Fix E — Column label "בהגשה" vs "בתוכנית עיצוב"**
- Currently "בתוכנית עיצוב" in `_content_table_html` (~line 858). Confirm with Lior which terminology is preferred.

**Fix F — Clean up dead template files (follow-up)**
- Delete unused `compliance_engine/templates/audit_report.css` and `audit_report.html.jinja`, OR refactor inline `_CSS` + `_render_*` back into those files so future CSS edits live in a `.css` file instead of a Python string.

### Coverage fixes (M2-scope, not blocking ship)

**Fix G — Map M1 design-doc plot numbers to takanon plot scheme (Task #27)**
- M1 surfaces plots `52, 54, 64` from the design doc; takanon uses `1-10`. Add a project-level `plot_number_aliases` mapping (e.g., `{52: 4, 54: 5, 64: 6}`) so M2's reconciliation can link findings across both schemes. Until then, audit silently skips these.

**Fix H — Add content rules for `easements` and `phasing` categories (2 categories, 11 clauses)**
- Backfill rule codes like `CONTENT_EASEMENTS_PUBLIC`, `CONTENT_PHASING_SEQUENCE`. Discipline layer doesn't cover these.

**Fix I — Expose phantom-plot findings explicitly**
- Plots 6-10 currently produce findings with `verdict: not_submitted` but the report renders them as if they were submitted. Consider an explicit "תא שטח X — לא נכלל בהגשה" indicator at the section opener for clarity.

---

**Awaiting Lior's go before touching `report_generator.py`.**
