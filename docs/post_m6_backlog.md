# Post-M6 Backlog

Insights from external AI consultations (5 engines) + new findings during M6 polish work.

These items are NOT in scope for M6. They represent direction for M7 and beyond.

---

## M7 — Discipline appendix audit (new scope dimension, surfaced after M6 work)

**The requirement (verbatim from Lior, 2026-05-24):**

The platform currently audits the architect's תוכנית עיצוב against the תב"ע תקנון. A new scope dimension is needed: audit the architect's **discipline-specific appendices (1:250)** against the **תב"ע נספחים (1:500)**.

Seven disciplines requiring this paired-appendix review:

1. אדריכלות
2. תנועה
3. פיזי — כבישים ופיתוח
4. גינון ועצים
5. ניקוז
6. אשפה
7. בנייה ציבורית

Each architect-submitted discipline appendix (1:250) must be compared to the corresponding תב"ע appendix (1:500). The תב"ע נספחים are not yet in the system — Lior will upload them as part of M7 kickoff.

### Open clarifying questions (must resolve before M7 design)

1. Format of תב"ע nspachim (vector PDF / DWG / DXF / raster PDF / KML / SHP)?
2. Are architect's discipline appendices separate files, or embedded in the 63-page תוכנית עיצוב we already audit?
3. Comparison semantics — geometric overlay, feature presence, or organized side-by-side presentation?
4. Per-discipline deliverable — visual overlay, list of discrepancies, or pass/fail verdict?
5. Is discipline review gated on automatic comparison, or independent?
6. בנייה ציבורית on the new list but not in the M6 signature page (10 disciplines). Add as 11th? Different sign workflow?

### Likely architecture (subject to answers above)

- New ingest pipeline for both architect's discipline appendices and תב"ע nspachim
- If both vector: Shapely-based geometric comparison (preferred path per consultation insights)
- If mixed: hybrid — vectorize the raster ones, then geometric ops
- New section in the audit report: section 3 already organized by discipline, could host per-pair comparison summaries
- Each discipline gets a sub-report; chief engineer + discipline reviewers each see relevant slice
- Effort estimate: 3-5 weeks depending on format answers

### Dependencies

- This is the highest-priority M7 candidate. Conflicts with other backlog items (consultation insights below) only on engineering capacity.
- DWG path (ODA File Converter, see backlog below) is a prerequisite if the תב"ע nspachim are in DWG. Build that first.

---

## Phase 6.D Tier 2 — Pending Lior reference values

The five deferred format-check automations. Each can move from `manual_review` to a deterministic handler once the listed reference value is supplied.

### 1. FORMAT_HEADER_COLOR_CYAN
Currently `manual_review`. Could become `pixel_color_sample` on heading-text spans.

**Needed:**
- Exact turquoise/cyan hex from חוברת ההנחיות (candidates: `#0099CC`, `#00BFFF`, `#26A0DA`, the exact value from the source PDF's color profile).
- ΔE tolerance — suggest `ΔE76 ≤ 10` so anti-aliased edges don't trigger false fails. If Lior prefers stricter visual control, `ΔE ≤ 5`.

**Implementation sketch:** extract text spans via PyMuPDF on TOC / chapter-divider / section-num spans, rasterize glyph bboxes, sample pixel color, compute ΔE distance from the reference. Pass if every heading sampled is within tolerance.

### 2. FORMAT_TOC_THREE_COLUMNS
Currently `manual_review`. Could become `column_count_analysis` on the TOC page.

**Needed:**
- Strict 3 columns (PASS only at exactly 3) or tolerance window (`2 ≤ N ≤ 4`)?
- Whether to count empty/orphan columns (e.g., last column with 2 entries) as a full column.

**Implementation sketch:** detect TOC page via the existing text-extraction check, cluster text-block x-coordinates into N groups (k-means with k=1..5, pick best silhouette), compare to threshold.

### 3. FORMAT_PARKING_TABLE
Currently `text_extraction` returning `requires_review`. Could tighten to deterministic structural check.

**Needed:**
- Exact column-header strings the table must contain (suggested: `["פרטיות", "אופנועים", "נגישות", "אופניים"]`). Order matters? Subset OK?
- Whether to require one row per תא שטח, or allow plan-wide totals.
- Per-plot row count: minimum required?

**Implementation sketch:** pdfplumber tables on basement_with_parking_table pages (already typed by M1), match column headers against the spec, verify row count.

### 4. FORMAT_TYPICAL_FLOOR_MIX_TABLE
Currently `text_extraction` returning `requires_review`. Same pattern as parking-table.

**Needed:**
- Apartment-size bucket boundaries to verify against (canonical clause 5.table suggests: `≤55 / 56-75 / 76-99 / ≥100` m²). Confirm these labels match the spec.
- Whether תמורה/יזם split must appear as a separate column.
- Acceptable tolerance if architect uses `≤50` instead of `≤55` etc.

**Implementation sketch:** pdfplumber tables across all pages, find the one matching expected headers + bucket boundaries, count rows per plot, verify sum-to-total.

### 5. FORMAT_NORTH_ARROW
Currently `manual_review`. Hardest of the 5 to automate.

**Needed:**
- Reference north-arrow PNG/SVG (template image). Without this, keep as `manual_review`.
- Pages it must appear on: all plan pages, or only site_plan_per_ta_shetach?

**Implementation sketch (if reference provided):** template matching via OpenCV on rasterized plan pages. Fallback: keep as `manual_review` (no false-positive risk).

---

## Strategic insights from consultation

### 1. Procedural data submission mandate (highest ROI)

The single most impactful direction: shift from "AI extracts structured data from PDFs" to "architect submits structured data alongside the PDF."

Realistic asks for the architect:
- **Excel area schedule per plot** — columns: plot_id, primary_m2, service_above_m2, service_below_m2, total_m2, source_page
- **CSV apartment schedule** — columns: unit_id, type (3-room / 4-room / etc.), sqm, floor, plot, building_letter
- **Declared easement table** — 8 easement types from takanon, with: easement_id, type, from_plot, to_plot, dimension, source_page
- **Phasing matrix** — CSV with phases × elements (units, parking, public space, infrastructure)
- **Daycare compliance data sheet** — fillable PDF or Excel: internal_area, outdoor_area, distance_to_residential_entry, parking_bays, separate_access_yes_no

Eliminates AI fragility on 4 of the 6 currently-uncovered categories (areas, apartments, easements, phasing).

Engagement path: Ellen negotiates the format mandate with the architect community. This is a procedural change, not a tech project.

### 2. DWG parsing via ODA File Converter

Replace the libredwg-web WASM candidate with:

```
AC1018 DWG (architect's CAD)
  → subprocess: ODA File Converter
  → R2018 DXF
  → Python: ezdxf parses DXF
  → Shapely / GeoPandas: geometric checks
```

Why this beats libredwg-web:
- ODA File Converter is industry-standard, free, headless, stable
- No WASM/JS bridge — pure Python pipeline
- ezdxf is native Python with active maintenance
- Avoids GDAL/OGR's AutoCAD format incompatibility

Unlocks:
- Easement geometry verification (8 takanon clauses)
- Setback / קווי בניין verification (currently DWG-deferred)
- Plot completeness via Shapely set-difference (catches missing plots 6-10, 20)
- Basement / underground polygon checks
- Area cross-verification against architect's Excel schedule

Estimated effort: 2 weeks integration + testing.

### 3. Verdict adjudication refinement

Current Bug A guard (M2 + M3 suppression on unambiguous numeric pass) was validated by 4 of 5 external consultations. Going further:

- **Classify M2 finding type**: value-disagreement vs provenance-concern vs anomaly. Currently treated as one binary "disagree" signal.
- **M3 role refinement**: from "binary disagree/agree" to "confidence delta" + "anomaly flag." M3 should never override deterministic verdicts.
- **Cross-document consistency layer**: same value should appear in N places (floor plan + area table + apartment schedule). Currently each validated in isolation.

### 4. PDF report length

External consultations were unanimous that 46 pages is too long. Long-term direction:

- 2-3 page executive summary as the PDF deliverable
- Full details in interactive Next.js UI with filter / drill-down
- Sidecar evidence accordion per clause

Defer until Ellen reports on current format usability. Don't redesign prematurely.

---

## New audit dimensions

Gaps surfaced by consultations + during M5/M6 review.

### Cross-section (חתכים) audit
Pages 48-51, 60 contain absolute elevation (above sea level), basement depth, podium transitions, garden apartments, retaining walls. Currently only height extracted from elevations. M2 scope expansion needed.

### Basement / parking infrastructure
Transformer rooms, generator separation, parking turning radii, daycare storage. Some are deterministic geometric (once DWG works); some need new takanon rule encoding.

### Resident amenities
Bike rooms, resident clubs, lobbies, gym, stroller rooms. Function diagrams on pages 26, 36, 41, 45 currently unaudited. Add rule encoding for required amenity types + minimum areas.

### Green axis continuity (public plots)
Plots 6-10 and 20 contain public open space connecting the new towers to the broader urban fabric. Current audit notes their absence but doesn't verify the topological continuity once they're added. Requires DWG.

### Existing-building integration
Southern elevations show "בניין קיים". No review of interface distances, shadow analysis, overlooking. Add as new audit category.

### Waste collection logistics
Vehicle turning radii, access paths for waste trucks, dumpster location vs entrance. Some visually auditable (turning radii arcs), some require explicit declaration.

### Ground-reference inconsistency between drawings

Phase 7.2 verification surfaced a new finding category that wasn't in the original consultation list: the architect's drawings sometimes use different absolute ground references for the same building. Examples from v24.3:

- Building A2: ground at 44.50 m (p53 elevation) vs 42.00 m (p57 elevation) — 2.50 m delta
- Building B4: ground at 47.75 m (p49 cross-section) vs 49.10 m (p57 elevation) — 1.35 m delta

Both drawings independently show consistent above-ground heights for these buildings (A2: 32.85 m on both pages; B4: 42.30 m on the elevation). The inconsistency is in the absolute baseline (sea-level reference), not the building geometry.

This matters because: absolute-elevation ceiling checks (§6.7's 91 m limit) depend on which ground reference is used. If the architect drew the same building once with ground at 44.50 m and once at 42.00 m, the absolute top differs by 2.50 m even though the building is the same.

For Phase 7.3+: add a "ground reference consistency" check per building, separate from "top elevation consistency." Flag any building where ground references differ by >0.5 m across drawings.

### Phase 7.3+ — chatakhim parser sophistication

The Phase 7.2 verification revealed that M1's "absolute top" context label is too coarse — it conflates three distinct value categories:

- **TRUE_BUILDING_TOP**: full-facade roof from elevation drawing (authoritative)
- **INTERMEDIATE_LEVEL**: cross-section cut top, podium roof, mechanical floor, lower wing roof
- **STATUTORY_LIMIT_ANNOTATION**: architect-drawn envelope line showing legal max (not built)
- **UNCERTAIN**: insufficient context to classify

The 7.3 parser should add `value_type` and `source_view` fields per extracted record. Rules:
- Prefer elevation-page values over cross-section values for ceiling and consistency checks
- Detect paired relative-absolute labels (e.g., "32.85 m" + "77.35 m" on same context) → treat lower as relative
- Detect floor-ladder pages → top-of-ladder is INTERMEDIATE_LEVEL, not building top
- Track ground reference per page → enables the ground-consistency finding above

Phase 7.2 shipped a defensive filter (drop consistency findings when contributing values are all elevation with consistent relative heights; drop when contributing values mix cross-section and elevation sources) as a surgical workaround. The full parser refactor is 7.3+ work.

---

## Tech debt

### M3 critic methodology
Current Flash prompt produces too-aggressive disagreements (Bug A surfaced this). Refactor to:
- Confidence delta output (not binary)
- Anomaly flag (categorical: provenance / value / completeness / other)
- Never flip verdicts; only annotate

### M4 logic accumulating ad-hoc patches
Currently has: Bug A guard, Bug B guard, M5 hedged-pass guard, cadastral-only softening. Each is a special case. Refactor into:
- Rule-type classifier (numeric-LTE / presence / geometric / qualitative)
- Uniform conflict resolver applied per type
- Sidecar spawn policy decoupled from verdict logic

### M1 manifest coverage flags
Currently classifies pages by type. Add "content_audited" / "content_unaudited" per page so the section 5 coverage table reflects real audit depth, not just page-type bucketing.

---

## Items considered but NOT adopting

### GeoPackage / IFC / BIM submission formats
Industry not ready in Israel. Architects deliver DWG + PDF. Excel area tables are realistic; structured CAD/BIM is a paradigm shift. Park indefinitely.

### Docker containerization
Single-machine, low-throughput deployment. Adds complexity without removing it. Use existing local Python environment with virtualenv.

### Critic-overrides-deterministic-pass
One consultation recommended this. Disagreed in current architecture — most consultations + Lior's instinct support deterministic supremacy with sidecar surfacing for critic concerns.

### Long M3 chains / multi-step critic debate
Compute cost without clear quality gain. M3 stays single-pass Flash.

---

## Workflow / process items

### Ellen feedback loop
After Ellen reviews the M6 PDF, capture her notes systematically:
- What did she trust without verification?
- What did she manually re-verify?
- What surprised her positively?
- What surprised her negatively?
- What did she add to her own חוות דעת that we missed?

This feedback drives M7 priorities better than further AI consultation.

### Architect feedback loop
After Kika Braz receives the formal חוות דעת with this report attached:
- Which action items did they implement?
- Which did they push back on?
- What did they request as procedural clarification?

This validates whether the architect-facing voice is working.

### Submission re-run cycle
v24.4 will eventually arrive. M6 pipeline should produce a comparable report. Diff against v24.3 should highlight what changed — both architect-side fixes and engine-side improvements. Build a "version diff" view as an M7 priority.

---

## CAD source data quality issues (for future authority outreach)

During Phase 7.1 implementation, the following data quality issues were found in the takanon-side CAD source files (`407-1048248_תאי שטח.dwg`):

- **Plot 9 AREA ATTRIB = 2086.27** but polygon area = 1194.77 (consistent with takanon schema). Identical to plot 20's AREA value — suspected copy-paste bug.
- **Plot 20 AREA ATTRIB = 2086.27** but polygon area = 86.35 (consistent with takanon schema). Same copy-paste pattern.
- **Plot 10 AREA ATTRIB = 1512.50** but polygon area = 1655.01 (consistent with takanon schema). Likely pre-revision stale attribute.

These do not affect the audit pipeline (we use polygon-derived geometry as authoritative). They are worth flagging to the planning authority's CAD team for source data correction in their next tashrit revision cycle. See `data/projects/407-1048248/cad_attribute_discrepancies.json` for the full structured log.

---

## v0.2.2 deferred items

### B-11: calibrate the attachment presence-detection match threshold

`_marker_found` in `app/sidecar/sidecar/attachments.py` currently declares an
item "present" if ANY single content word from the guideline title appears in
the attachment's text. On a text-bearing PDF that is too loose: a submission
mentioning "תכנית" anywhere satisfies every guideline whose title starts with
"תכנית", so real omissions get downgraded from "לא הוגש" to "נדרשת בדיקה".

Deliberately NOT tuned in v0.2.2 - the architecture (structural check_mode +
no-text-layer suppression) is settled, and the match rule is calibration on
top of it. Tuning it well needs a corpus of real submissions, ideally with
Ellen labelling a sample of items as present/absent so precision and recall
can be measured rather than guessed.

Direction when picked up: require a proportion of the title's content words
rather than one, weight rarer words higher, and consider matching against
drawing-label text specifically rather than the whole page text. Note that
loosening errs toward "נדרשת בדיקה" (safe) and tightening errs toward
"לא הוגש" (accusatory), so calibration should be biased toward the former.

### B-12: image-coverage page classification for attachment presence detection

DEFERRED from v0.2.2, not rejected. v0.2.2 ships the all-or-nothing rule:
if ANY page falls below MIN_TEXT_CHARS_PER_PAGE (250), presence detection is
suppressed and no finding may say "לא הוגש". That is never wrong - it costs
manual checks and nothing else - but on a booklet-shaped attachment it makes
"לא הוגש" unreachable.

Measured on the real 63-page תכנית עיצוב (24.3): 40 readable pages, 23 below
the bar, ratio 63%. Detection suppressed. Notably NO page has zero text - the
23 sub-threshold pages carry 33-217 chars each, i.e. renderings with a caption
or title block. A "zero text" rule would catch none of them.

Proposed direction: classify sub-threshold pages by raster coverage, excluding
legitimately image-only pages from the denominator, so a rendering does not
count as an unreadable sheet. THE PROPOSAL AS DRAFTED DOES NOT WORK - measured
below.

Full per-page data for the 23 sub-threshold pages (page, chars, raster
coverage as a fraction of page area, embedded image count), with the
classification a 0.35 coverage bar would give:

    page  chars  img_cover  imgs   class(>=0.35)
       1     56      0.803     7   IMAGE-ONLY
       3     77      0.525     7   IMAGE-ONLY
       4     56      0.686     7   IMAGE-ONLY
       5     56      0.649     7   IMAGE-ONLY
       9    182      0.367     7   IMAGE-ONLY
      10     62      0.336     8   UNREADABLE   <-- misses by 0.014
      11     44      0.462     8   IMAGE-ONLY
      16     53      0.488     9   IMAGE-ONLY
      17     53      0.488     9   IMAGE-ONLY
      18     44      0.489     9   IMAGE-ONLY
      19     53      0.489     9   IMAGE-ONLY
      20     86      0.588    11   IMAGE-ONLY
      21     98      0.604    13   IMAGE-ONLY
      22    149      0.557    12   IMAGE-ONLY
      23     93      0.420    11   IMAGE-ONLY
      24    175      0.413     9   IMAGE-ONLY
      31     91      0.491     9   IMAGE-ONLY
      32    101      0.491     9   IMAGE-ONLY
      33    139      0.492     9   IMAGE-ONLY
      34    159      0.368     9   IMAGE-ONLY
      39    217      0.542     9   IMAGE-ONLY
      46    197      0.092     8   UNREADABLE   <-- genuinely low coverage
      63     33      0.756     7   IMAGE-ONLY

UNREADABLE under the proposed rule: 2 (pages 10 and 46). Detection would
STILL be suppressed on the real booklet, so the proposal does not solve the
problem it was designed for.

Open questions to settle before implementing:

  1. Page 10 fails at 0.336 against a 0.35 bar - a 1.4% margin deciding
     whether an entire document gets detection. Not a rule; a coin toss.
  2. Page 46 (197 chars, 0.092 coverage, 8 images) does not fit either
     category: too much text for a rendering, too little raster for a photo
     page, too little text to read. Suspected THIRD page class - possibly a
     diagram/vector figure with a caption. The two-way image-vs-vector split
     may not describe the real page population at all. Characterise the
     classes from real files before choosing any threshold.
  3. Every constant in this area so far (200 doc-wide, then 250/page + 0.5
     ratio, then 0.35 coverage) was calibrated on self-authored fixtures or a
     single file and broke on first contact with real data. Do not pick the
     next number from one file either.

Also recorded: an earlier report of this analysis claimed the 23 pages were
"all >= 0.37x coverage -> 0 unreadable" while simultaneously quoting page 46
at 0.09x. That was a sampling error (13 of 23 pages measured, conclusion
generalised from the sample). The table above is the complete measurement and
supersedes it.

Needed to proceed: the פיתוח וכבישים and מבני ציבור attachments, plus any
further real נספחים, to characterise page classes across more than one file.

### B-13: check_key needles and thresholds are bound by Hebrew prose, not structure

PRIORITY: LOWERED (was near-term). B-13 hardens the BINDING side of a mechanism
whose INPUT side is empty - see B-14: no measure_key is populated for any of the
7 keys, so every numeric check returns "נדרשת בדיקה" regardless of how robustly
the key is bound. Fixing the binding changes nothing Ellen sees until measured
values exist. Still correct and still worth doing; no longer urgent.

Two coupled defects, same root cause as the v0.2.2 classifier bug: machine
behaviour derived from editable Hebrew text instead of structural identity.

(a) CHECK_MAP NEEDLES ARE LITERAL STRINGS.
scripts/extract_guidelines_docx.py attaches the 7 engine check_keys by
searching each row's raw text for a hard-coded Hebrew substring. Audited
against the CURRENT (post-v0.2.2-readability) row text, 3 of 7 needles no
longer appear anywhere in their row:

    check_key                      needle                        matches now?
    glass_railing_min_height_cm    "גובה מעקה 105"                NO  (dead)
    laundry_screen_width_m         "מידות 1.8×1.5"                NO  (dead)
    path_main_min_m                "שביל הולכי רגל 3 מ"           NO  (dead)
    glazing_reflectivity_max_pct   "רפלקטיביות זיגוג מקסימלית 70%" yes
    laundry_screen_height_m        "מסתורי כביסה - מידות וחומר"    yes
    gas_tank_setback_min_m         "צובר גז"                      yes
    path_secondary_min_m           "☐ שצ”פ"                       NO - absent from
                                     BOTH pre- and post-v0.2.2 text; the v0.2.1
                                     checklist sweep already stripped the ☐ glyph

Bindings survive today ONLY because attachment runs before the content
sweeps in main(). Reverse those steps and 3-4 keys vanish silently - no
error, no failing test, just guidelines that stop being checkable. An
ordering comment is the only thing protecting this.

PROPOSED (not implemented): key needles structurally, as
(section_key, sort_order), exactly like CHECK_MODE_OVERRIDES. sort_order is
derived from docx document order, is stable under any rewording, and is
already the placement key used by the seed adoption logic. The Hebrew
substring would drop to a human-readable comment. Editing a guideline's
wording could then never break its numeric check. Requires a re-extraction
to confirm the (section, sort_order) pairs, and a gate asserting all 7 keys
attach.

(b) THRESHOLDS ARE DUPLICATED IN PROSE.
5 of the 7 checkable rows state the threshold in BOTH check_value and the
body text:

    part_b/50   path_main_min_m               3.0    "3 מ' לשביל הולכי רגל"
    part_c/61   gas_tank_setback_min_m        2.0    "2 מ' לפחות"
    part_c/63   laundry_screen_width_m        1.8    "1.8 על 1.5 מ'"
    part_d/73   glass_railing_min_height_cm   105.0  "105 ס\"מ"
    part_d/76   glazing_reflectivity_max_pct  70.0   "70%"

The other 2 (part_d/74 laundry height, part_g/126 path secondary) carry the
value only in check_value - they are "partner" keys riding on a row whose
prose names a different number, which is its own inconsistency.

When Ellen edits a threshold in the guidelines screen, check_value changes
and the prose does not. The row then displays one number and enforces
another, with nothing flagging the divergence. Needs either a render-time
substitution (body text references the field rather than repeating it) or a
gate that fails when check_value and the number in prose disagree.


### B-14: the 7 numeric guideline checks have no input (product finding)

NOT A CODE DEFECT. The checks are bound, they execute, and they read the
threshold live from the guideline row so Ellen's edits take effect. What is
missing is the measured value to compare against.

Every numeric check reads extracts["plan_wide"][measure_key]. In the pilot's
audit_outputs/407-1048248/v24.3/extracts.json, NONE of the 7 measure_keys is
present:

    check_key                        measure_key                  present?
    gas_tank_setback_min_m           gas_tank_setback_m           NO
    glass_railing_min_height_cm      glass_railing_height_cm      NO
    glazing_reflectivity_max_pct     glazing_reflectivity_pct     NO
    laundry_screen_height_m          laundry_screen_height_m      NO
    laundry_screen_width_m           laundry_screen_width_m       NO
    path_main_min_m                  path_main_width_m            NO
    path_secondary_min_m             path_secondary_width_m       NO

    PRESENT: 0 of 7

plan_wide currently holds a disjoint set serving other checks:
infiltration_area_percent, infiltration_area_total_sqm, small_apartments_count,
small_apartments_percent_calculated, stormwater_retention_cubic_m,
total_units_proposed.

CONSEQUENCE IN THE SHIPPED BUILD: all 7 numeric guideline checks return
"נדרשת בדיקה" with the threshold cited. Verified by direct invocation of
run_guideline_checks - with a measured value supplied the check correctly
returns fail (2.0 < 2.5) or pass (3.0 >= 2.5); with none it returns
requires_review citing "הסף הנדרש הוא 2.5 מ' לפחות".

The behaviour is HONEST and the citation is useful to Ellen - it tells her the
current threshold and that she must verify it herself. The gap is that nothing
feeds it, so these are guided manual checks, not automated verdicts. Worth
knowing when weighing further investment in the binding machinery (B-13).

extracts.json is hand-maintained today. No extraction pipeline is proposed here
- this entry records the finding only.

--------------------------------------------------------------------------

B-15: guideline voice unification - the 43 templated rows
PRIORITY: LOW. Do NOT re-open on style grounds alone; see the reasoning below.

v0.2.2's readability pass rewrote 92 of the 160 seeded guideline rows into the
authority's voice. The remaining 68 were initially described as "raw rows in a
second voice". That framing was wrong; the real breakdown is:

  27  untouched, חלק ז checklist-template voice
  16  untouched, DUPLICATE_BODY_REWRITES (v0.2.1, per-row hand-written)
  25  untouched, genuinely raw
      of which  6  had the body-echoes-title defect  -> FIXED in v0.2.2
               19  were already clean prose in the authority's own voice
                   (the waste-room rows part_c/142-157, the מינהלת additions
                    part_b/144 and 158-160). Nothing to unify.

So the open item is 43 rows in a uniform machine voice - not 68 raw ones.

WHY THIS IS DEFERRED, AND WHY IT IS NOT SIMPLY "STYLE DEBT":

  * חלק ז IS A CHECKLIST. The authority wrote it as ☐ lines to be scanned, not
    read. A terse uniform voice there is arguably CORRECT rather than a defect;
    turning "☐ נספח אקוסטי" into flowing prose would plausibly make it worse to
    use. Anyone re-opening this must argue that point first, not assume it.
  * The 16 duplicate-body rewrites are 16 separate editorial judgements keyed by
    title, not one template. Reviewing them is 16 readings, not one.
  * NO TOOLING SAFETY NET. Both available sweeps CONFIRM lists but cannot
    ORIGINATE them: the docx-vs-seed sweep compares FACTS (identifiers, numbers,
    units, standards) and would stay at 0 through a rewrite that destroyed the
    meaning of every row; the jargon/tech-ID gates match shapes. Any rewrite here
    needs a full manual reading of each row against the docx.
  * Cost is therefore roughly half a day of authoring plus a full review round at
    the density of the 92-row pass - spent on rows that are currently readable
    and factually intact (sweep: 0 facts lost).

WHAT WAS DONE IN v0.2.2 INSTEAD (cheap, bounded, and correctness-driven):
  * the 6 echo rows rewritten (part_a/17,18,25,26 and part_f/93,95);
  * "המפורטים להלן" removed from the CAD duplicate-body rewrite, matching the
    ruling already applied to part_a/19, part_b/39 and part_c/52;
  * the checklist template's trailing sentence
    "בקבלת ההגשה נבדק שהפריט קיים ותואם לנדרש" CUT - it was a claim about this
    software published as municipal guidance, and false as written (nothing
    performs a conformance check at intake; see the 0-of-7 measure_key entry
    above);
  * CHECKLIST_FRAMES + CHECKLIST_EXCEPTIONS added because the single formula
    produced category errors on 22 of the 35 rows (see below).

STILL OPEN FOR A RULING (raised, not decided): three classes flagged inside the
16 duplicate-body rewrites - added clauses (#2, #3, #10, borderline #15),
softened modality (#5, #6, #16, mild #14). These were authored in v0.2.1 and
have never been reviewed row by row.

--------------------------------------------------------------------------

SHIPPED DEFECT CLASS: the checklist template asserted the opposite of חלק א
SHIPPED IN: v0.2.1.  FIXED IN: v0.2.2.  Logged as a shipped defect, not as a
v0.2.2 finding - Ellen read these rows in a released build.

v0.2.1 expanded all 35 חלק ז checklist stubs with ONE formula:
    "החוברת תכלול {item}. בקבלת ההגשה נבדק שהפריט קיים ותואם לנדרש."

The formula assumed every checklist item is a component CONTAINED IN the
booklet. Most are not, and 22 of the 35 read wrongly as a result:

  7 rows CONTRADICTED חלק א. "החוברת תכלול נספח אקוסטי - PDF נפרד" told the
    architect the annexes go inside the booklet. חלק א says the opposite, in
    the authority's own words: "לא יוטמעו בתוך החוברת הראשית". Two sections of
    the same document, shipped saying opposite things.
  8 rows were category errors: "החוברת תכלול שצ”פ", "החוברת תכלול צובר גז".
    A booklet does not contain a gas tank.
  6 per-plot rows carried two facts in one slot and read as fragments.
  1 row was self-referential: "החוברת תכלול חוברת תכנית עיצוב".

Additionally, the trailing sentence "בקבלת ההגשה נבדק שהפריט קיים ותואם
לנדרש" was a claim about THIS SOFTWARE published as municipal guidance, and
false as written - nothing performs a conformance check at intake (see the
0-of-7 measure_key entry). It appeared on all 35 rows.

WHY NOTHING CAUGHT IT: every gate is a shape or fact check. The docx-vs-seed
sweep compares FACTS and stayed at 0 throughout - no identifier, number, unit
or standard was lost. The sentence was well-formed Hebrew containing every
fact from the source line. Only reading it against חלק א catches it.

LESSON: a template applied uniformly to authority content asserts a
RELATIONSHIP the source may not state ("the booklet contains X"). Before
templating N rows, check that the frame's implicit claim is true for all N -
it was true for 13 of 35 here.

FIX: CHECKLIST_FRAMES (three verb frames: תוגש / יצורף / החוברת תציג) plus
CHECKLIST_EXCEPTIONS for the six per-plot rows, keyed by the docx item text,
with a FATAL if any key stops matching a row.

--------------------------------------------------------------------------

OPEN QUESTIONS FOR ELLEN (guideline wording; do not resolve unilaterally)

Q1  part_d/78 solar panels. The docx says only "בפריסה מותאמת" and never
    says adapted to WHAT. v0.2.1 resolved it as "לצורת הגג ולמערכות שעליו";
    that was an invention and has been reverted to the source's ambiguity.
    Ellen should say what the layout must be adapted to.

Q2  part_e/85 unit-mix table. The docx line is an orphan fragment - the row's
    TITLE and BODY are both "ולא טבלה מצרפת לפי בנדים של חדרים בלבד." v0.2.1
    added a positive requirement ("יש להציג את הנתונים פר-יחידת דיור") which
    the row does not carry; it is supported by the subsection heading ה.1 and
    by the חלק ז checklist row 128 ("פר-יחידה, לא לפי בנד"), but NOT by this
    row. Reverted to the prohibition alone. Ellen should confirm whether the
    positive requirement belongs in this row.

Q3  appendix_a/139 statutory name. The docx says "תקנון תכנון ובנייה"; the
    statutory instrument is "תקנות התכנון והבנייה". Kept as the source wrote
    it. Ellen to confirm whether the source is simply wrong.

--------------------------------------------------------------------------

B-16: the DXF layer classifier does not know the layer names we publish
PRIORITY: HIGH for correctness of expectations; the feature still works,
because Ellen confirms every mapping by hand. Investigated in v0.2.2, NOT fixed.

חלק א rows 20-24 tell the architect, in the authority's own words, which layer
names to use - and offer a Hebrew alternative for each:

  א/20  0_LOTS        or  תא_שטח_X
  א/21  0_SETBACK     or  קו_בניין
  א/22  0_BOUNDARY    or  קו_מגרש
  א/23  0_BLDG        or  בניין_X
  א/24  0_OPEN_SPACE  or  שצ"פ

MODULE AND LOGIC: app/sidecar/sidecar/layer_mappings.py, _classify_layer(name).
Four tiers, first match wins:
  Tier 1  _TIER1_RZ      exact, case-insensitive UPPER, plus an "RZ_" prefix
                         fallback. National רישוי זמין names only. HIGH.
  Tier 2  _TIER2_MUNI    exact, case-insensitive lower. Tel Aviv muni_* names.
  Tier 3  _TIER3_EXACT   exact, case-insensitive lower. Firm-specific names.
  Tier 4  _TIER4_PATTERNS  re.search, IGNORECASE, substring/keyword. LOW.

NONE of the five published names appears anywhere in the classifier. Verified by
running _classify_layer on all ten published forms:

  0_LOTS         -> UNKNOWN                     תא_שטח_5  -> AREA_ZONES    LOW
  0_SETBACK      -> SETBACK_FRONT  LOW          קו_בניין  -> UNKNOWN
  0_BOUNDARY     -> UNKNOWN                     קו_מגרש   -> UNKNOWN
  0_BLDG         -> UNKNOWN                     בניין_3   -> UNKNOWN
  0_OPEN_SPACE   -> UNKNOWN                     שצ"פ      -> PUBLIC_SPACE  LOW
  (contrast) RZ_BOUNDARY -> PLOT_BOUNDARY  HIGH

7 of 10 are UNKNOWN. The 3 that hit are Tier-4 substring accidents at LOW
confidence, and one of them is WRONG: 0_SETBACK matches the generic "setback"
keyword whose rule maps to SETBACK_FRONT, so a generic building-line layer is
classified as the FRONT setback specifically.

Three sharp details behind the misses:
  * SPELLING. The Tier-4 rule is "קו\\s*בנין" - בנין with one yud. The guideline
    says קו_בניין with two. "קו בנין" matches; "קו_בניין" does not. The
    underscore also defeats "\\s*", which matches whitespace, not underscores.
  * QUOTE FORM. The Tier-4 rule is 'שצ"פ' with a STRAIGHT quote. The seed and
    the docx use the gershayim שצ”פ. Verified: שצ"פ -> PUBLIC_SPACE,
    שצ”פ -> UNKNOWN. A layer named exactly as the guideline prints it misses.
  * CASE. Tier 1 upper-cases before matching, so case is not the issue for the
    0_* names - they are simply absent from every tier.

GATE: none. No test in tests/ references layer_mappings or _classify_layer.
Nothing ties the classifier's expected names to the guideline text, so the two
can drift apart silently - and already have: v0.2.2 restored 0_LOTS, 0_SETBACK,
0_BOUNDARY, 0_BLDG and 0_OPEN_SPACE to the guidelines Ellen publishes without
anything noticing the parser had never heard of them.

WHY THIS IS NOT A LIVE BREAKAGE: layer mapping is confirm-by-hand. discover
seeds rows with a guessed role and confidence, and Ellen PATCHes each one. An
UNKNOWN guess costs her a manual selection; it does not produce a wrong verdict
on its own. The exception is 0_SETBACK, which guesses SETBACK_FRONT at LOW
confidence - a wrong guess is worse than UNKNOWN if it is accepted unread.

NOT FIXED IN v0.2.2 - reported only, per instruction. A fix would be: add the
five names plus their Hebrew alternatives to a tier, normalise gershayim and
underscore/spelling variants, map 0_SETBACK to a generic setback role rather
than FRONT, and add a gate that reads the layer names OUT of the seeded
guideline text so the two cannot diverge again.

B-16 ADDENDUM (v0.2.2 ruling: stays deferred, do not fix in this release)

FIRST PIECE WHEN B-16 IS WORKED: 0_SETBACK -> SETBACK_FRONT. A wrong
LOW-confidence guess is worse than UNKNOWN, because Ellen may accept it unread;
UNKNOWN forces her to choose. Fix that mapping before adding any names.

THE PATTERN - THIS IS THE THIRD INSTANCE. Three separate subsystems key off
Hebrew strings, and in none of them does anything tie the code's expected text
to the guideline text Ellen actually publishes:

  1. CHECK_MAP needles (scripts/extract_guidelines_docx.py) - each of the 7
     engine check_keys binds to a row by grepping a hard-coded Hebrew
     substring. A rewording erases the binding. Caught only after the fact, by
     an extractor FATAL and later tests/test_check_key_attachment.py. See B-13.
  2. The check_mode classifier - originally proposed to read Hebrew prose;
     rebuilt in v0.2.2 to key on (section_key, sort_order) precisely because
     prose is not a stable key. tests/test_check_mode_structural.py holds that.
  3. The DXF layer classifier (this item) - Tier 4 matches Hebrew layer names
     by regex, and no test references it at all.

The sharpest illustration is the gershayim mismatch: the Tier-4 rule spells
שצ"פ with a STRAIGHT quote, while the docx and the seed use שצ”פ. A layer named
EXACTLY as the guideline prints it does not match. Same class as the one-yud
קו_בנין vs the published קו_בניין.

The general lesson, worth applying before adding a fourth: Hebrew-string keys
between two artifacts need either a shared constant or a gate that reads the
strings OUT of the published text. Everything else drifts silently, and the
drift is invisible to fact-level sweeps because no fact was lost.
