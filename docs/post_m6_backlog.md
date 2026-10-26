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

--------------------------------------------------------------------------

B-17: title and body carry the same content (guidelines screen)
PRIORITY: MEDIUM. v0.2.3. A DISPLAY change, not a content change - see why below.

Found by rendering the guidelines screen for the first time (v0.2.2 pre-merge
visual check). Three symptoms, ONE root cause: a row whose body restates its
title, which a BEFORE/AFTER table cannot show because the table never puts the
two side by side under each other.

  A. חלק ז - 25 consecutive rows where the body adds three words and nothing
     else:
        title  תוכן עניינים מפורט     body  החוברת תכלול תוכן עניינים מפורט.
        title  הקדמה וחזון            body  החוברת תכלול הקדמה וחזון.
        title  חתכים אורכי + רוחבי    body  החוברת תכלול חתכים אורכי + רוחבי.
     The six per-plot rows are the exception - they add real information
     ("...עבור תא שטח 1 את ששת העמודים הנדרשים").

  B. The same requirement appears TWICE inside one discipline card: the
     substantive row and its חלק ז checklist echo. In אדריכלות וחזיתות:
     נספח חומריות, מסתורי כביסה, פתחי ממ"ד, חזיתות, תכנית גג. Not new in
     v0.2.2 - checklist rows always folded into disciplines - but while they
     were "☐" stubs they read as a different KIND of thing.

  C. Two titles in חלק א are full sentences with trailing periods, where every
     neighbour is a noun phrase, and their bodies restate them:
        הקבצים הבאים יצורפו להגשה. ללא קבצי CAD ההגשה לא תתקבל.
        גודל קובץ. כל קובץ DWG/DXF מקסימום 200 MB.

WHY THE OBVIOUS FIX IS NOT AVAILABLE. C cannot be fixed by editing the titles:
those ARE the docx titles. Authority text is not ours to rewrite - that is the
line this whole release has been drawn against. The same applies to A: the
checklist item text is the authority's.

So the only remedy available for all three is DISPLAY-LEVEL: suppress or
collapse a body that restates its title (exact match after normalisation, or
title-is-a-prefix-of-body). That is a UI change in Guidelines.tsx and the PDF
builders, not a seed change, and it needs a rule careful enough not to hide a
body that adds a threshold or a condition.

NOTE ON PROVENANCE: A was CREATED by a correct fix in v0.2.2. The checklist
template's trailing sentence "בקבלת ההגשה נבדק שהפריט קיים ותואם לנדרש" was cut
because it was a claim about this software published as municipal guidance, and
false as written. Cutting it was right. The residue - a body that now adds
nothing - is the cost of that cut, and it is cheaper than shipping a false
claim. Do not "restore" the sentence to fix the echo.

--------------------------------------------------------------------------

B-18: font staging in the packaged build is UNVERIFIED
PRIORITY: MEDIUM. Not a known break - an untested link, which is the same shape
as the WebView2 download bug and the report_chrome.css staging gap.

All three PDFs embed Heebo from assets/fonts/, staged into the PyInstaller
bundle by backend.spec (`("../../assets/fonts", "assets/fonts")`) and resolved
via report_chrome.resolve_font_dir(). Nothing verifies the fonts actually land
in the packaged artifact.

WHY THE EXISTING PROBE CANNOT CATCH IT. build-windows.yml's report-chrome probe
asserts (1) 200 + %PDF, (2) size > 50 KB, (3) the body contains "/Image".
None of the three fires on missing fonts:

  * the render still SUCCEEDS - WeasyPrint falls back to a system face rather
    than raising, so 200 + %PDF still passes;
  * the size assertion is backwards here. MEASURED: with assets/fonts absent
    the PDF gets LARGER, not smaller - 193 KB against 179 KB with the fonts
    present - because the fallback face subsets differently. A "> 50 KB" floor
    can never catch it, and a ceiling would be worse;
  * "/FontFile" and "Heebo" do NOT appear in the raw bytes in either case,
    because font descriptors and embedded programs sit inside compressed
    streams. Verified on both renders. So no cheap byte-level assertion in
    PowerShell distinguishes them.

CONSEQUENCE IF IT REGRESSES: every PDF the municipality sends out renders
Hebrew in a fallback face - wrong typography, and on a Windows host without a
good Hebrew font, potentially unreadable text or tofu. Dev mode would look
perfect throughout, because it reads assets/fonts/ from the source tree.

WHAT A REAL CHECK NEEDS - one of:
  a. a PDF library in the CI job (pypdf / pikepdf) to decompress the font
     descriptors and assert an embedded FontFile2 whose BaseFont name contains
     "Heebo". This is the direct assertion and the one to prefer;
  b. rasterise page 1 and compare against a committed reference image, which
     also covers layout regressions but is brittle across renderer versions;
  c. cheapest partial: assert the staged bundle CONTAINS
     assets/fonts/Heebo-Regular.ttf before the smoke test runs. That proves
     staging, not embedding - the same distinction as the CSS, where boot
     proves resolution but not use.

(c) is a one-line file-existence check and would have caught a dropped datas
entry; (a) is what actually proves the glyphs in the shipped PDF come from
Heebo. Prefer (a), fall back to (c).

--------------------------------------------------------------------------

B-19: 4 of the 9 verdicts print in English  - SHIPPED DEFECT, HIGH
SHIPPED IN: v0.2.0 (attachments) through v0.2.2. Not fixed.

The engine can emit nine verdicts: pass, fail, pass_with_note, fail_borderline,
not_submitted, requires_review, manual_review, unevaluable, not_applicable.
Each surface maps them to Hebrew with a `.get(v, v)`-style fallback, so an
unmapped verdict prints its raw English key to the reader. Found while
rendering a real דו"ח התייחסות for the conference deck: "pass_with_note"
appeared in the table Ellen sends to architects.

Sweep of every verdict/status label map (2026-10-19):

  surface                      file                                  covers  missing
  דו"ח התייחסות PDF            app/sidecar/sidecar/attachments.py     5/9    pass_with_note, fail_borderline, unevaluable, not_applicable   LIVE
  attachments review screen    app/frontend/.../AttachmentsTab.tsx    5/9    the same four                                              LIVE
  main report + Excel export   compliance_engine/constants.py         8/9    manual_review                                              LATENT
  findings screen              app/frontend/.../FindingsView.tsx      9/9    -

LATENT means no current path emits that status into those outputs:
manual_review appears in the engine only as a check TYPE, never as a finding
STATUS. It becomes live the day it does.

Fix needs: Hebrew labels for the four (wording for Lior's approval - the
existing five set the register), and a gate that derives the verdict list
from the engine and fails if any label map misses one. Same defect class as
the CAPS_UNDERSCORE tech-ID leak, in a different surface.

--------------------------------------------------------------------------

B-20: a merge to main published a release nobody approved - SHIPPED PROCESS DEFECT
2026-07-27. FIXED ON BRANCH fix/release-safety (548642e), not yet in main.

Pushing the v0.2.2 merge to main ran build-windows.yml's release job, gated
on `github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/')`.
It created tag v0.2.1-20260727-b744fd3, published it as Latest (not draft,
not prerelease, although the step was named "pre-release") with
Planning.Platform_0.2.1_x64-setup.exe - labelled 0.2.1 because the version was
never bumped, containing 0.2.2 code - and its "Delete previous build
releases" step deleted the real v0.2.1 release and, with --cleanup-tag, the
tags of every earlier build. 0 downloads. The approval had said "no tag, no
release, no installer"; the report back said none had been made, because
nobody checked what a push to main triggers.

State now: the release was converted to a DRAFT on 2026-10-19 (asset and tag
kept). /releases/latest therefore returns 404 - the link Ellen uses is dead
until a new release is published.

Fix on the branch: releases only on a version tag, only as draft, tag must
match tauri.conf.json, delete step removed; tests/test_release_safety.py
gates every workflow file (red against the July workflows: 3 failures).

--------------------------------------------------------------------------

FACT (recorded 2026-10-19, not a backlog item): data dir == install dir

On Windows the sidecar's data dir and the NSIS install dir are the SAME
folder, %LOCALAPPDATA%\Planning Platform:
  - data:    app/sidecar/sidecar/config.py, _default_data_dir()
  - install: app/tauri/tauri.conf.json, nsis.installMode = "currentUser"
platform.db therefore lives inside the directory the installer rewrites.
No release separated them - not v0.2.2, not any other. No document in the
repo claims otherwise; the claim existed only in a prompt. Over-installs have
kept data so far only because the NSIS uninstaller removes just the files it
installed - an implementation detail, not a guarantee. See the data-dir
proposal (2026-10-19 report) before relying on auto-uninstall.

--------------------------------------------------------------------------

B-21: every Python dependency is floor-only; PyMuPDF 2.0 already broke the packaged engine
FOUND 2026-10-19. PyMuPDF capped on branch fix/release-safety (ad2b4cf).
CLOSED 2026-10-19 on fix/release-safety (fabb5fc): exact pins + per-platform
uv locks, CI installs only from them, actions/Rust/tauri tools pinned, monthly
Dependabot PRs merged by a person, gate tests/test_dependency_lock.py.

app/sidecar/requirements.txt pins nothing: every entry is `>=X` or bare.
On 2026-10-19 the runner resolved `PyMuPDF>=1.24` to PyMuPDF 2.0, whose
`import fitz` activates a `pymupdf.layout` package that loads ONNX data
files PyInstaller does not collect. In the packaged app the import raises:
the end-to-end smoke test failed 3 of 43 checks, including "engine job
completed (run_full_audit loaded in bundle)" - i.e. a build made from main
today cannot run an audit. Dev mode and pytest are unaffected, so nothing
local would have shown it.

Still floor-only (same exposure): fastapi, uvicorn, sqlalchemy, pydantic,
python-multipart, openpyxl, ezdxf, shapely, pdfplumber, google-generativeai,
and `pip install pyinstaller` in build-windows.yml.

Fix needs: a lock file (pip-compile) or upper caps, regenerated deliberately;
and the build should install from it, so a release is reproducible. Until
then any rebuild of an old commit is NOT the build that shipped.

--------------------------------------------------------------------------

DECISIONS (Lior, 2026-10-19) - recorded so they are not reopened

D-1: Auto-uninstall before install - NOT NEEDED. CLOSED.
Install-over is proven to keep the data: the 0.2.1 -> 0.2.2 upgrade probe
(ui-smoke.yml, job upgrade-probe) kept the sentinel project in runs
39303871011 and 39304639970, and its sabotage run 39303884369 went red.
Auto-uninstall would run the OLD uninstaller over the folder that holds
platform.db (data dir == install dir, see the FACT above) for no
demonstrated benefit. Do not reopen without a failure install-over cannot fix,
and never before the data dir has moved out (D-2).

D-2: Move the data dir out of the install dir - BACKLOG, HIGH (raised
2026-10-26 from LOW, Lior). Not built in 0.2.4.
Evidence, Windows 11 VM, 2026-10-26: the installer's own default for an
existing install is "Uninstall before installing" - the old uninstaller runs
over the folder that holds platform.db on every upgrade, whatever D-1 decided
about building it ourselves. Its page shows "Uninstalling from:
C:\Users\<user>\AppData\Local\Planning Platform" and one checkbox, "Delete the
application data", UNCHECKED by default. Left unchecked (0.2.1 -> 0.2.2 ->
0.2.3) the data survived: platform.db 4 KB, platform.db-wal 2,527 KB,
attachments/1/1/, projects/407-1048248, jobs, logs, exports. One tick of that
box by Ellen removes her database. Screenshots:
~/planning-platform-fixtures/screens/v0.2.3/0-data-dir-*.png and
2-023-installer-4-uninstall-options.png (on Lior's Mac).
Proposal as reported 2026-10-19 (section 6), nothing built:
  - new default data folder outside %LOCALAPPDATA%\Planning Platform
  - migration on the new version's first launch: copy with SQLite's backup
    API (never a file copy - it must capture the WAL), into a temp folder,
    verify file counts + PRAGMA integrity_check, then rename into place;
    leave the old folder untouched for a few versions
  - absolute file paths stored in the database (each submission's PDF path)
    must be rewritten - the riskiest part
  - a CI test for the migration, built like the upgrade probe
Failure modes as Ellen would see them:
  copy interrupted            nothing, if it falls back to the old folder
  paths not rewritten         projects listed, PDFs and reports missing
  downgrade then upgrade      recent work "disappears" (two folders drift)
  disk full (~100 MB/PDF)     an error at launch
  app open during the copy    a db missing recent changes, or no start

D-3: B-14 - NO BUILD. DEFERRED until Ellen approves draft 4.1.
Draft "19.10.26 טיוטא#4.1" drops 6 of the 7 numeric thresholds (only
"צובר גז" remains, without its 2 m), so building inputs for them now builds
for rules that are about to disappear.
STANDING REASON automatic extraction (option C) is rejected: on page 13 of
the real submission (תכנית_עיצוב_הטייסים_24.3.pdf, sha 92205abf...) the image
reads 3 m for the pedestrian path and 2.5 m for the bike path - a pass - and
the TEXT LAYER SWAPS THEM. An extractor would have FAILED a compliant plan.
That is the only real measurement available, and it inverts. Options A
(Ellen enters the values) and B (architect data sheet) remain open for
whatever thresholds 4.1 keeps.

D-3 REOPENED 2026-10-20 (Lior) on vision-spike evidence. Read-only spikes,
gemini-2.5-flash through the vision_verify path, one call per question,
3 runs each; ground truth read from the images by hand first:
  round 1, sheet 12753.1/3: Q1-Q4 correct 3/3; Q5 "total car spaces"
    answered 70 - the supply table, read correctly - the question was
    ambiguous (Lior's ruling: his question, not the model).
  round 2, 8 more sheets (TRP TS01-05, 12753.1/1, 12753.1/5, development
    plan), Q5 naming the table, Q6 waste-truck maneuver added: 109/144 runs
    correct. Per question: table present 24/24, basement plan + levels
    20/24, guest ratio 19/24, maneuver 19/24, total 17/24, residential ratio
    10/24 (reads the 1:1 bicycle column). Best sheet TS02 18/18, worst TS01
    6/18 (the largest image, JPEG re-encoded to fit the 20 MB inline cap).
    Development plan Q6: "yes" 3/3 quoting a label ("כביש גישה נגיש למשאית
    אשפה") not found on the sheet - a fabricated citation. ~$0.0019/call.
  API reports ~450 prompt tokens per call regardless of sheet size, so the
  model works from a heavily downscaled image; accuracy falls with sheet size.
  Raw results: ~/Downloads/golden-review/vision-round2-results.json.

D-4: The draft release v0.2.1-20260727-b744fd3 STAYS DRAFT until the
attachment-mapping fix (v0.2.3 section 1) ships. /releases/latest returns
404 until then.


--------------------------------------------------------------------------

B-22: flaky viewport test - the comments form is "not rendered" at 1024x700
FOUND 2026-10-19 on main after the fix/release-safety merge. NOT FIXED.

Test:   tests/ui-dev/tests/01-layer2-viewports.spec.ts:28
        "layout 1024x700: home / overview / submissions / findings / cad /
        guidelines / settings", assertion at line 64:
        "comments form clipped controls: form not rendered"
Runs:   QA Suite 39312456426 (main, 9975d2e) attempt 1 FAILED,
        attempt 2 (rerun of the failed job, same commit) PASSED.
        The identical tree passed on fix/release-safety in 39309715615.
Evidence: docs/evidence/B-22-comments-1024x700-failed.jpeg - the last
        screencast frame of the failed attempt (artifact qa-suite-traces
        12216956740, expires with the run's retention).

What the frame shows: the הערות רפרנטים tab rendered its "לא זמין" card
(run the check before entering reviewer comments) instead of the form. So
the form was legitimately absent at that instant - the assertion is not
reading a clipped layout, it is reading a project with no completed check.

Not the cause: parallel tests - playwright.config.ts has workers: 1.
Two hypotheses, neither verified:
  1. ordering/state - an earlier spec leaves project 1 without a completed
     check when this one reaches the tab;
  2. loading race - the tab shows "לא זמין" before its status request
     returns, and page.evaluate runs right after click() with no wait.

Why it matters: a test that fails without a code change is a test nobody
will trust when it fails for real. Fix needs the cause first (the trace in
the artifact has the network log), then a wait on the real condition - not
a retry and not a sleep.

--------------------------------------------------------------------------

B-23: every attachment report ran 25 unrelated general checks, on every type - SHIPPED DEFECT, HIGH
SHIPPED IN: v0.2.1 (2200184) through v0.2.2 (main 9975d2e). FIXED ON
feat/v0.2.3 (ea33905 + the include follow-up), not yet in main.

Since v0.2.1, attachment_check_mapping.json marked the whole כללי section
'חלק א - פורמט קבצים' always-on for EVERY attachment type, matched by its
Hebrew title. Its 25 rows are booklet rules (page size, fonts, file name),
the booklet's required-files list (CAD, development plan, basement plan,
sections), CAD-file rules (DWG/DXF/XREF/layers/coordinates) and other
annexes (hydrology, green building, environment). None is a property of a
single sheet.

  v0.2.1  the rows answered "נדרשת בדיקה" - wrong scope, but silent.
  v0.2.2  status semantics let a presence check say "לא הוגש"; the same rows
          now told architects they had omitted work a traffic sheet never
          contains. Found by Ellen on sheet 12753.1/3: 44 checks, 31 "לא הוגש".

Measured on the real file through the API: v0.2.1 and main run the SAME 44
checks in the same order; only the verdicts differ. No Hebrew key broke
between the versions - the mapping was too wide from the day it shipped.

Per type, checks before -> after the fix: traffic 44->17, waste 43->18,
landscape 34->7, infrastructure 32->6, roads 38->11, drainage 34->9,
architecture 60->26, environment 32->4, tenant services 28->3, public
buildings 36->11, general 84->25.

Fix: scope keyed on section_key/sort_order (structural), part_a and part_g
never on an attachment, cross-discipline rows only by explicit mapping.
Gate: tests/test_attachment_scope.py. Ellen approves the per-type lists:
~/Downloads/מיפוי_בדיקות_לפי_נספח.xlsx (2026-10-20). Open decision for her:
"שירותים לדיירים" has no guideline at all - delete the type or say what
belongs to it.

--------------------------------------------------------------------------

B-24: discipline rows inside part_a run on no attachment - LOW
DECIDED 2026-10-20 (Lior): part_a is booklet-only for every discipline.

Consequence: the discipline-tagged rows of part_a - e.g. נספח אקוסטי
(sec-3-8, part_a#31), שכבת קווי בניין (sec-3-3, part_a#21), נספח חומריות,
רשימת צמחייה, פוליגונים סגורים - now run on no attachment. They still run
in the main audit. Reopen when an attachment type exists that matches one
(e.g. an acoustic annex, or a CAD file as an attachment): add the row to
that type with include_guidelines, by (section_key, sort_order).

Note, same family: "דיאגרמת פונקציות" (part_b#42) is still TAGGED תנועה in
the guidelines database, which is where the main report files it. For
attachments it is excluded from traffic and included in architecture
(include_guidelines). Retagging the row itself changes the main report and
is a guidelines-content decision, not done.

--------------------------------------------------------------------------

B-25: a garbled text layer produced "לא הוגש" for items drawn on the sheet - SHIPPED DEFECT, HIGH
SHIPPED IN: v0.2.2 (status semantics) - before that the same miss said
"נדרשת בדיקה". FIXED ON feat/v0.2.3 (6ebfee4), not yet in main.

Ellen's traffic sheet 12753.1/3 (md5 ff37760e): the basement plan and the
parking table are on the sheet, both reported "לא הוגש". The sheet's labels
and tables are vector paths; its text layer is 518 characters of garbled
labels (reversed, ם mapped to ח). The 250-character page bar measured
quantity, not readability, so detection ran on text that cannot match.
Fix: a per-page readability test (well-formed Hebrew + known-word ratio,
thresholds measured on 14 real PDFs); a garbled page counts as unreadable
and the report leads with "לא ניתן לקרוא את הטקסט בקובץ".
Blind spot (measured, in the test): a light substitution of a few letters in
otherwise-correct text stays inside the readable range.

FOR B-14 (recorded 2026-10-20, read off the image - the text layer has none):
the sheet carries a "מאזן חניה" (underlined title) made of two tables -
"דרישת חניה", the requirement for ALL plots, and "היצע חניה", the supply in
THIS plot's four basements (front 15+16+16+15 = 62, rear 0+3+3+2 = 8,
total 70). Corrected 2026-10-20: first recorded as one "דרישת חניה" table.
The requirement table, per plot 01-05:
  units:          05: 196, 04: 98, 03: 130, 02: 44, 01: 232 (+4 kindergarten classes)
  ratios:         residents 1.3:1, guests 0.1:1 per unit, motorcycles 1:10, bikes 1:1
  grand total:    1009 private cars, 70 motorcycles, 700 bikes
  basis printed:  "בהתאם לתקנות התכנון והבנייה, 2016 - אזור ג'" - NOT the
                  guideline's "תקן חניה לאומי 3.1 (ינואר 2023)"
Two observations for Ellen, not adjudicated: the guest ratio printed is
0.1:1 per unit, where the מינהלת addition asks for 30% of the residential
standard; and the sheet cites the 2016 regulations, not standard 3.1.
Can any path today feed these numbers to a check? NO. The table area has an
empty text layer; only OCR/vision could read it - option C, rejected (D-3).
Vision spike 2026-10-20 (read-only, gemini-2.5-flash via the vision_verify
path, 5 questions x 3 runs): basement plan + levels 1-4, the table, 1.3:1
and 0.1:1 all correct 3/3; "total car spaces" answered 70 - the supply
table, read correctly - not the requirement total 1009, 3/3. ~$0.001/call.

--------------------------------------------------------------------------

B-26: the PUBLIC repository holds client and authority material - HIGH, DECISION PENDING
RECORDED 2026-10-20. Ruling (Lior): stays public for now, pending Ellen's answer.

The public repo contains the real audit report sent to the architect, the
real submission extracts, the municipality guidelines, and TLV protocols with
applicant names. Ellen to be asked. Purge plan (4b) and the synthetic-pilot
prerequisite are recorded below so the decision can be taken and executed.

Repo: liors12/planning-platform, PUBLIC, 0 forks, 0 stars, no Pages. Anything
already cloned or archived cannot be recalled.

1. IN THE TREE TODAY (417 tracked files)
 A. From the real submission (אאורה / KIKA BRAZ design plan v24.3):
    data/projects/407-1048248/submissions/v24.3/ (19 files, ~1.3 MB) -
      vision findings, page manifests, inventories, audit results + run logs,
      verification reports, all extracted from the real plan
    audit_outputs/407-1048248/v24.3/audit_results.m4.json (329 KB)
    app/sidecar/seed/audit_outputs/.../audit_results.m4.sanitized.json
      (346 KB) - SHIPPED IN THE APP as the pilot project's data
    projects/407-1048248/submissions/v24.3/extracts.json, discipline_findings.json (40 KB)
    templates/v24_3_discipline_feedback_*.docx (4 x ~224 KB) - feedback
      forms for this submission; fields blank, project/tava/version filled
 B. Statutory plan (public on Mavat):
    data/projects/407-1048248/takanon_cad/*.dwg (blue line, plots; 170 KB)
    project-schema-*.json (3), canonical_clauses.json, takanon_cad_dataset.json
    reports/407-0977595/tashrit-analysis-2026-04-30.pdf/.md (our analysis)
 C. Authority and third-party documents:
    docs/הנחיות_עיצוב_נס_ציונה_לגוגל_דוקס.docx (240 KB) + guidelines_seed.json
      (98 KB) - the municipality's guidelines, full text
    compliance_engine/reference_docs/*.pdf (17.3 MB + 1 MB) - Tel Aviv
      municipality public guides
    src/corpus/fixtures/tlv-*.pdf (20 files, ~65 MB) - Tel Aviv local
      committee decision protocols; published, but they name applicants
 Not found: no real email or meeting notes; no email address or phone number
 in any text file. Ellen is named in 75 files. docs/evidence/B-22-*.jpeg is
 a screenshot of the test app (synthetic data).

2. IN HISTORY, deleted from the tree (on every branch, main included)
    audit_outputs/407-1048248/v24.3/audit_report_24.3.pdf (305 KB) + .html
      (93 KB) - THE REAL REPORT on the real submission
    an older audit_results.m4.sanitized.json (331 KB)
    tests/ui-dev/.qa-ui-data/ - a test database (platform.db-wal 2.5 MB) and
      job outputs of runs on the pilot
    plus everything in section 1.

3. WHAT GOING PRIVATE COSTS
    Actions, last 30 days: 293 Windows + 48 Linux minutes = 634 of 2,000
    billable (Windows x2). A July-like month (44 builds, 44 UI smokes, 46 QA
    runs) is ~2,300 - over quota; with the default $0 spending limit CI stops
    for the rest of the month. (The PR-triggered Windows build was removed
    2026-10-20, 4b202ed.) Options: Pro (3,000 min).
    ELLEN'S DOWNLOAD LINK BREAKS: she installs from the GitHub release asset;
    a private repo needs a GitHub account with access. Options: a
    collaborator account for her, or distribute the installer elsewhere.
    Dependabot keeps working (ensure the dependency graph is on). Free secret
    scanning / push protection is lost. Branch protection, rulesets, Pages:
    not used today.

4a. MAKE PRIVATE: `gh repo edit --visibility private
    --accept-visibility-change-consequences`, after Ellen's download and the
    minutes question are solved. Reversible.

4b. PURGE FROM HISTORY (irreversible), on a copy:
    1. freeze pushes; `git clone --mirror` to a private backup
    2. `git filter-repo --invert-paths --paths-from-file purge.txt` with the
       approved path list
    3. force-push every branch and tag; delete branches no longer needed
    4. contact GitHub Support: old commits stay reachable by SHA and through
       refs/pull/* until they purge them - only they can
    5. every working copy re-clones
    Breaks: every commit SHA (backlog/commit references), the July 27 draft
    release and every tag, open Dependabot PRs #1-#40 (close; they reopen),
    ci/baseline-0.2.1 (the probe artifact is stored by run id - unaffected).
    PREREQUISITE: purging app/sidecar/seed/audit_outputs removes the app's
    pilot project - the findings tab, the main report and dozens of tests
    depend on it. A SYNTHETIC replacement pilot must be built first.

--------------------------------------------------------------------------

B-27: v0.2.3 was PUBLISHED as a full release, not left as a draft - HIGH, PROCESS
RECORDED 2026-10-26.

Procedure (548642e, tests/test_release_safety.py): CI creates releases as
DRAFT only; a person checks the asset and presses Publish. v0.2.3 was created
as a draft by build-windows.yml on the tag (run 39382289819, 2026-10-20
06:45Z) and published 2026-10-24 13:24:57Z, marked Latest, before any
install test on Windows. That build does not start on a Windows without the
VC++ redistributable (B-28).

Who/what: a Claude Code session on Lior's Mac, in ~/Desktop/planning-platform
(session 2a485c34), ran `gh release edit v0.2.3 --draft=false --latest` at
13:24:56Z, seven seconds after a message in that session asked it to
("Publish the v0.2.3 draft release now (gh release edit --draft=false)").
GitHub's event log shows the publish under github-actions[bot], the release's
author - no workflow ran on 2026-10-23..25. CI was not involved and the
workflow gate held; the gap is that a session with `gh` auth can publish
without the Windows install test having run.

Open: whether to require the VM install test before any publish, and how to
enforce it (a checklist line in qa/RELEASE_QA_SKILL.md, or a repo rule that
no agent session publishes).

--------------------------------------------------------------------------

B-28: planning-platform.exe needs the VC++ redistributable - FIXED ON BRANCH
FOUND 2026-10-26 (Windows 11 VM). Branch fix/static-vcruntime, 0.2.4.

0.2.2 and 0.2.3 install, then fail on launch: "VCRUNTIME140.dll was not
found", then VCRUNTIME140_1.dll. The exe imports both; tauri-build 2.6.2 links
the runtime statically only when STATIC_VCRUNTIME is exactly "true", and
nothing set it. The installer ships no vc_redist (the DLLs under
binaries/sidecar/_internal are PyInstaller's and not on the exe's search
path). The July 0.2.1 installer's exe imports neither DLL - it did not need
the runtime; see the 0.2.4 report for what changed between July and October.
Fix: STATIC_VCRUNTIME "true" in build-windows.yml (job env) and
app/tauri/.cargo/config.toml, rerun-if-env-changed in build.rs, and a CI gate
(scripts/pe_imports.py --forbid-vcruntime) on the built exe before any
release step. tests/test_static_vcruntime.py.
