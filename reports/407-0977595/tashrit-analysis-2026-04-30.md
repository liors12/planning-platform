# תשריט analysis report — 407-0977595
*התחדשות עירונית במתחם הטייסים, נס ציונה*

**Generated:** 2026-04-30  
**Source:** `/Users/liorlevin/Desktop/:planning-platform:/data/projects/407-0977595/source-documents/tashrit`  
**File-set sha256:** `0cdfcd356af482fdfee1bf9b965abe9a90dd064a09c381ee2ee8ca861b448a84`  
**Generator:** `src/tashrit_analysis.py` (deterministic — geopandas / shapely / pyproj / rasterio)

---

## 1. Per-parcel geometry consistency

**Source:** `migrashim.shp` (6 polygons)

CRS missing in `.prj` (no projection file). Coordinates fall in the Israeli ITM range — assumed `EPSG:2039` for area calculations.

### Roster cross-check

| set | members |
|---|---|
| `migrashim.shp` (תשריט reality) | 1, 2, 4, 5, 6, 10 |
| `schema.parcels[]` (defined) | 1, 2, 4, 5, 6, 10 |
| `schema.meta.scope_in` | 1, 2, 4, 5, 6, 10 |
| `schema.meta.scope_out` | — |

### Per-parcel area

| migrash | computed (m²) | dbf Shape_Area | schema plot_area_sqm | Δ% vs schema | verdict |
|---|---|---|---|---|---|
| 1 | 6,761.57 | 0.00 *(empty)* | 6,762.00 | -0.01% | ✓ area match |
| 2 | 4,256.23 | 0.00 *(empty)* | 4,260.00 | -0.09% | ✓ area match |
| 4 | 2,830.97 | 0.00 *(empty)* | 2,830.97 | -0.00% | ✓ area match |
| 5 | 402.77 | 0.00 *(empty)* | 402.77 | +0.00% | ✓ area match |
| 6 | 2,119.13 | 0.00 *(empty)* | 2,117.00 | +0.10% | ✓ area match |
| 10 | 207.38 | 0.00 *(empty)* | 207.38 | -0.00% | ✓ area match |

**Findings:**

- All `Shape_Area` values in `migrashim.dbf` are `0.0` — the field is present but unpopulated by MAVAT for this plan. Cross-check (a) `dbf Shape_Area` is therefore unavailable; we rely on (b) computed-vs-schema.

**Verdict:** ✓ consistent — every declared parcel area within ±1% of schema; roster consistent.

---

## 2. Topological coverage

**Sum of parcel polygon areas:** 16,578.06 m²

**Schema declares:**
- `meta.total_site_area_dunam`: 16.58 dunam → 16,580.00 m²
- `meta.total_site_area_sqm`: 16580.2 m²

**Parcel sum vs dunam-derived total:** Δ -0.01%

**Plan envelope** (from `kavim kchulim.shp`): 16,580.20 m²
**Parcel union area:** 16,578.04 m²
**Gaps within envelope:** 2.25 m²
**Pairwise parcel overlaps:** 0.00 m²

**Largest gap polygons (top 5):**
- gap #1: area 1.59 m², centroid ITM (180744.0, 649108.4)
- gap #2: area 0.62 m², centroid ITM (180767.3, 649111.8)
- gap #3: area 0.00 m², centroid ITM (180841.2, 649134.4)
- gap #4: area 0.00 m², centroid ITM (180841.6, 649133.7)
- gap #5: area 0.00 m², centroid ITM (180840.7, 649135.1)

**Findings:**

- 2.25 m² of gap area inside the plan envelope. Likely roads / שצ"פ / unassigned strip — if expected, document; if not, the parcel boundaries don't tile the plan.

**Verdict:** ⚠ warning — 2.25 m² of gaps inside the envelope (likely roads / open space).

---

## 3. Land-use designation cross-check

**Note on ymishnep.shp:** the file is **62 Point features**, not polygons, with attributes `Id, ISHUV, TOCHNIT, NUM, KOD, NAME`. `KOD` values seen in this dataset are `'29'` and `'31'` — these are MAVAT code-list IDs for annotation/symbol categories, not land-use YEUD codes. The expected sub-יעוד polygons are not present in this layer.

**Authoritative land-use per parcel** lives in `migrashim.shp.YEUD` (one code per parcel), not in `ymishnep.shp`. Reading from there:

| migrash | YEUD code | decoded (lookup) | schema land_use | verdict |
|---|---|---|---|---|
| 1 | 73 | מגורים ד' | מגורים ד' | ✓ match (exact) |
| 10 | 423 | שביל | שביל | ✓ match (exact) |
| 2 | 73 | מגורים ד' | מגורים ד' | ✓ match (exact) |
| 4 | 882 | שטח ציבורי פתוח (וריאנט) | שצ"פ | ✓ match (exact) |
| 5 | 882 | שטח ציבורי פתוח (וריאנט) | שצ"פ | ✓ match (exact) |
| 6 | 676 | מבנים ומוסדות ציבור (וריאנט) | מבנים ומוסדות ציבור | ✓ match (exact) |

**ymishnep.shp contents:** 62 Point features. `KOD` distribution: `29`×36, `31`×26.

**Findings:**

- Tentative YEUD codes in use (resolved via parent-category inference, not official MAVAT source): 676, 882. See `CONTEXT.md` Open Tasks.
- `ymishnep.shp` does NOT contain land-use polygons for this plan — it carries 62 annotation points with KOD `'29' / '31'`. Land-use polygons are folded into `migrashim.shp.YEUD` (one code per parcel), with no separate sub-יעוד polygon layer in this תשריט.

**Verdict:** ⚠ warning — land-use codes match where decodable, but unknown YEUD codes need confirmation.

---

## 4. kavim kchulim.shp identity

CRS missing in `.prj` (no projection file). Coordinates fall in the Israeli ITM range — assumed `EPSG:2039` for area calculations.

**Geometry type(s):** `Polygon`
**Feature count:** 1
**Total length:** 577.90 m  (perimeter if polygon)
**Total area:** 16,580.20 m²

**Attribute fields:**

| # | field | values (first row) |
|---|---|---|
| 0 | ISHUV | np.int64(7200) |
| 1 | TOCHNIT | '407-0977595' |
| 2 | MIGRASH | np.int64(6) |
| 3 | MISHNE | np.int64(16) |

**Sample WKT of first 3 features:**

- feature 0 (Polygon): `POLYGON ((180847.2305517476 649169.4630667679, 180847.40205175616 649169.4608667679, 180847.57835176494 649169.4647667687, 180847.75065177307 649169.474466769, 180847.9238517806 649169.4904667698, 180848.0991517892 649169.5128667708, 180848…`

**Spatial relationship to parcels:** parcels' union area ∩ kavim kchulim = 16,577.95 m² (100.0% of kavim kchulim)

**Interpretation:** the polygon is a single closed shape that *contains* the parcel union (≥80% coverage), with the same `TOCHNIT` ID (`407-0977595`) as the plan. This is the **plan boundary (קו כחול)**, not the building line (קו בניין). Building setback lines (קו בניין) live one level below — they're the offset edges *inside* each parcel, not the plan envelope.

**Findings:**

- `kavim kchulim.shp` is the plan boundary (קו כחול), confirmed by the single-polygon geometry containing all parcel polygons.

**Verdict:** ✓ consistent — kavim kchulim.shp identified as the plan boundary.

---

## 5. Raster georeferencing consistency

| raster | pixels (W×H) | pixel m (x / y) | bbox min ITM | bbox max ITM | real size (m) |
|---|---|---|---|---|---|
| 4053239_58_1.jpg | 10629×10038 | 0.0212 / -0.0212 | (180683.1, 648994.2) | (180908.3, 649207.3) | 225.2 × 213.1 m |
| 4053239_58_2.jpg | 10629×10038 | 0.0212 / -0.0212 | (180683.2, 648994.2) | (180908.4, 649207.3) | 225.3 × 213.1 m |
| 4053239_M.jpg | 7004×4951 | 0.0424 / -0.0424 | (180679.8, 648993.4) | (180976.9, 649203.3) | 297.1 × 210.0 m |

**Pairwise overlap check:**

All pairs overlap with the smaller raster ≥50% covered. ✓

**Resolution sanity:**

- `4053239_58_1.jpg`: 2.12 cm/px (close-up)
- `4053239_58_2.jpg`: 2.12 cm/px (close-up)
- `4053239_M.jpg`: 4.24 cm/px (wide view)

**Upper-left corner spread:** Δeast = 3.31 m, Δnorth = 3.99 m (tolerance ±5 m)

**Verdict:** ✓ consistent — all 3 rasters overlap, resolutions stack as expected (_M coarse, _58 fine).

---

## Summary findings (ranked by severity)

- ⚠ **2. Topological coverage** — 2.25 m² of gap area inside the plan envelope. Likely roads / שצ"פ / unassigned strip — if expected, document; if not, the parcel boundaries don't tile the plan.
- ⚠ **3. Land-use designation cross-check** — Tentative YEUD codes in use (resolved via parent-category inference, not official MAVAT source): 676, 882. See `CONTEXT.md` Open Tasks.
- ⚠ **3. Land-use designation cross-check** — `ymishnep.shp` does NOT contain land-use polygons for this plan — it carries 62 annotation points with KOD `'29' / '31'`. Land-use polygons are folded into `migrashim.shp.YEUD` (one code per parcel), with no separate sub-יעוד polygon layer in this תשריט.
- ✓ **1. Per-parcel geometry consistency** — All `Shape_Area` values in `migrashim.dbf` are `0.0` — the field is present but unpopulated by MAVAT for this plan. Cross-check (a) `dbf Shape_Area` is therefore unavailable; we rely on (b) computed-vs-schema.
- ✓ **4. kavim kchulim.shp identity** — `kavim kchulim.shp` is the plan boundary (קו כחול), confirmed by the single-polygon geometry containing all parcel polygons.

## Action items

- **4. kavim kchulim.shp identity**: Update `digital_files.tashrit.todo_building_line_layer` in the schema to record this conclusion: kavim kchulim = plan boundary, NOT the building line. Building-line layer remains unidentified — DWG layer extraction (`407-0977595_מצב מוצע.dwg`) is still the only known source for קו בניין.

> No schema fixes have been auto-applied. Review and decide before changing anything.
