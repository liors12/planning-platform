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
