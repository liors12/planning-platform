# Phase 4 — Geometry Compliance Engine
## Detailed specification for Claude Code

**Status:** BLOCKED until Phases 1–3 are validated. Do not start until Phase 3 produces a חוות דעת that Ellen confirms.

**Estimated time:** 5–7 days

**Goal:** Add geometric compliance checks to the engine — building setbacks, top-floor setbacks, balcony distances, plot boundary validation, and cross-format consistency checking.

---

## 1. Three Input Formats — Priority Order

The system reads three different geometric formats. Each has a different role and priority:

```
┌─────────────────────────────────────────────────────────────┐
│  PRIORITY 1 (HIGHEST):  SHP from ממ"ג                       │
│  ─────────────────────────────────────────────────────────  │
│  • Source: מנהל התכנון (national planning registry)         │
│  • Authority: This is the legally registered version       │
│  • Use for:                                                 │
│    - Parcel boundaries (תאי שטח)                            │
│    - Land use codes (MAVAT_CODE → residential, public, etc) │
│    - Plan boundary (קו כחול)                                │
│    - Official areas (LEGAL_AREA per parcel)                 │
│    - Building lines if present (קווי בניין)                 │
│  • Library: pyshp (with encoding='cp1255' for Hebrew)        │
│  • Coordinate system: ITM (Israeli Transverse Mercator)     │
│                                                             │
│  PRIORITY 2:  DWG from architect                            │
│  ─────────────────────────────────────────────────────────  │
│  • Source: The submitting architect                         │
│  • Authority: Construction-level detail                     │
│  • Use for (only what SHP doesn't provide):                 │
│    - Building envelopes (footprint + balconies)             │
│    - Top-floor setbacks                                     │
│    - Detailed building lines                                │
│    - Basement layout polygons                               │
│  • Library: ezdxf (after AC1018 → DXF conversion)           │
│  • Per-firm layer mapping required                          │
│                                                             │
│  PRIORITY 3:  PDF tables (already from Phase 1)             │
│  ─────────────────────────────────────────────────────────  │
│  • Source: The architect's submitted plan                   │
│  • Authority: What the architect CLAIMS                     │
│  • Use for:                                                 │
│    - Cross-reference validation                             │
│    - Stated values to compare against measured              │
│  • Already extracted in Phase 1                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. SHP Reader — Build This First

### 2.1 Why SHP first

The SHP package is the **most reliable** format. Real-world test on plan 407-1048248:
- 11 parcels extracted in 30 seconds
- Each with parcel number, land use code, exact area
- No ambiguity, no per-firm configuration needed
- Same structure for every plan from MAVAT

DWG is harder, less reliable, and requires per-firm configuration. PDF is for human review.

### 2.2 The MVT Shapefile Package

Every MAVAT plan comes with a ZIP containing 9 shapefile layers:

| Layer | Type | What's in it | Priority |
|---|---|---|---|
| `MVT_PLAN_NUM` | POINT | Parcel numbers + land use codes + areas | **CRITICAL** |
| `MVT_PLAN` | POLYGON | Plan polygons | High |
| `MVT_GVUL` | POLYLINE | Building lines (קווי בניין) | **CRITICAL** for setbacks |
| `MVT_ARC` | ARC | Curved boundaries | Medium |
| `MVT_LABEL` | POINT | Text labels | Low |
| `MVT_POL` | POLYGON | Other polygons | Medium |
| `MVT_ROZETA` | POLYGON | Compass roses (visual only) | Skip |
| `MVT_PRINT_FRAME` | POLYGON | Print frame (visual only) | Skip |
| `MVT_SYMBOL` | POINT | Symbols (visual only) | Skip |

### 2.3 MAVAT Code Reference (land use codes)

Build a lookup dictionary:

```python
MAVAT_CODES = {
    140: ("מבנים ומוסדות ציבור", "Public Buildings"),
    220: ("מסחר ושירותים", "Commercial"),
    230: ("מגורים ומסחר", "Mixed Use Residential/Commercial"),
    340: ("דרך מוצעת", "Proposed Road"),
    400: ("שביל", "Pedestrian Path"),
    670: ("מגורים ד'", "Residential D"),
    830: ("שצ\"פ", "Public Open Space"),
    860: ("שטח לאיחוד וחלוקה", "Reorganization Area"),
    # extend as new plans are loaded
}
```

When an unknown code is encountered, log it and flag for human review. Do not assume.

### 2.4 Code structure

```python
# src/parsers/shp_reader.py

import shapefile
from shapely.geometry import Polygon, Point
from pyproj import Transformer

ITM_TO_WGS84 = Transformer.from_crs("EPSG:2039", "EPSG:4326", always_xy=True)

def read_mmg_package(zip_path: str, project_id: str) -> dict:
    """
    Extract structured data from a MAVAT shapefile package.
    Returns dict with parcels, building_lines, plan_boundary.
    All geometries in ITM coordinates. WGS84 conversion done on read for display.
    """
    # Extract ZIP to temp folder
    # Read MVT_PLAN_NUM for parcel data
    # Read MVT_GVUL for building lines
    # Read MVT_PLAN for plan polygons
    # Match by spatial join (point-in-polygon for parcel labels)
    # Return structured result
    pass

def read_parcels(shp_path: str) -> list[dict]:
    """Read MVT_PLAN_NUM with cp1255 encoding."""
    sf = shapefile.Reader(shp_path, encoding='cp1255')
    parcels = []
    for rec, shape in zip(sf.records(), sf.shapes()):
        rec_dict = dict(zip([f[0] for f in sf.fields[1:]], list(rec)))
        parcels.append({
            'parcel_id': rec_dict['NUM'],
            'mavat_code': rec_dict['MAVAT_CODE'],
            'land_use_he': MAVAT_CODES.get(rec_dict['MAVAT_CODE'], (None, None))[0],
            'land_use_en': MAVAT_CODES.get(rec_dict['MAVAT_CODE'], (None, None))[1],
            'legal_area_sqm': rec_dict['LEGAL_AREA'],
            'point_itm': shape.points[0] if shape.points else None,
        })
    return parcels
```

### 2.5 Definition of done for SHP reader

Run on the test file `407-1048248_קבצי_התכנית__SHP__1.zip` and produce:
- 11 parcels with correct numbers (1-10, 20)
- Correct land use mapping (Public Buildings × 5, Residential D × 3, Public Open Space, etc.)
- Total area matches sum of LEGAL_AREA values within 0.01% tolerance

---

## 3. DWG Reader — Build Second

### 3.1 The conversion problem

DWG files from MAVAT and architects are typically **AC1018** (AutoCAD 2004 format). 

- `ezdxf` reads DXF only, not DWG
- GDAL's libopencad supports only AC1015 (older format)
- Best option: **libredwg** (open source, command-line)
- Alternative: **ODA File Converter** (free for non-commercial use)

### 3.2 Conversion pipeline

```python
# src/parsers/dwg_reader.py

import subprocess
import ezdxf
from pathlib import Path

def convert_dwg_to_dxf(dwg_path: Path, output_dir: Path) -> Path:
    """Convert AC1018 DWG to DXF using libredwg."""
    dxf_path = output_dir / dwg_path.with_suffix('.dxf').name
    result = subprocess.run([
        'dwg2dxf', 
        '--version', '2018',  # output format
        str(dwg_path),
        str(dxf_path)
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        raise ConversionError(f"DWG conversion failed: {result.stderr}")
    return dxf_path

def read_dxf_layers(dxf_path: Path) -> dict:
    """Read all layers from DXF, group entities by layer name."""
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()
    
    layers = {}
    for entity in msp:
        layer_name = entity.dxf.layer
        if layer_name not in layers:
            layers[layer_name] = []
        layers[layer_name].append(entity)
    return layers
```

### 3.3 Per-firm layer configuration

DWG layer names vary by architect firm. Build a configuration table:

```python
# src/parsers/dwg_layer_configs.py

LAYER_CONFIGS = {
    'kika_braz': {
        'building_footprint': ['A-WALL-EXT', 'A-WALL-EXTERIOR', 'BLDG_FOOTPRINT'],
        'balcony': ['A-BALC', 'BALCONIES'],
        'plot_boundary': ['L-PROP', 'PROPERTY-LINE'],
        'building_line': ['קו-בניין', 'BUILDING-LINE'],
        'top_floor': ['A-FLOR-TOPF', 'TOP-FLOOR'],
    },
    # When a new firm submits, add their layer mapping here
    # Or: build interactive UI for admin to map layers per submission
}
```

When an unknown firm submits, the system should:
1. Extract all unique layer names
2. Use Claude API to suggest mapping (which layer is the building footprint?)
3. Present suggestions to admin for confirmation
4. Store confirmed mapping in `dwg_layer_configs` DB table

### 3.4 Geometry construction

```python
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid

def build_envelope(footprint_polys: list, balcony_polys: list) -> Polygon:
    """
    Build building envelope = footprint ∪ balconies.
    Always make_valid + buffer(0) before union to handle messy geometries.
    """
    all_geoms = []
    for poly in footprint_polys + balcony_polys:
        valid_poly = make_valid(poly).buffer(0)
        if not valid_poly.is_empty:
            all_geoms.append(valid_poly)
    
    if not all_geoms:
        raise GeometryError("No valid geometries to union")
    
    return unary_union(all_geoms)
```

---

## 4. Compliance Checks

### 4.1 Setback between buildings

```python
def check_setback_between_buildings(
    building_a: Polygon,
    building_b: Polygon,
    rule: dict
) -> dict:
    """
    Rule SETBACK_MIN_BETWEEN_BUILDINGS: ≥9m between any two buildings.
    Uses Shapely .distance() and nearest_points() for evidence.
    """
    from shapely.ops import nearest_points
    
    measured_distance = building_a.distance(building_b)
    nearest_a, nearest_b = nearest_points(building_a, building_b)
    
    return {
        'rule_code': 'SETBACK_MIN_BETWEEN_BUILDINGS',
        'measured_value_m': round(measured_distance, 3),
        'required_value_m': rule['threshold'],
        'verdict': 'pass' if measured_distance >= rule['threshold'] else 'fail',
        'evidence': {
            'method': 'shapely_distance',
            'nearest_point_a_itm': list(nearest_a.coords)[0],
            'nearest_point_b_itm': list(nearest_b.coords)[0],
            'building_a_layer': 'A-WALL-EXT',  # from layer config
            'building_b_layer': 'A-WALL-EXT',
        }
    }
```

### 4.2 Top-floor setback from שצ"פ

```python
def check_top_floor_setback_from_shatzap(
    top_floor: Polygon,    # from DWG
    shatzap_boundary: Polygon,  # from SHP MVT_PLAN_NUM (mavat_code=830)
    rule: dict
) -> dict:
    """Rule TOPFLOOR_SETBACK_SHATZAP: top floor ≥3m from שצ"פ boundary."""
    measured = top_floor.distance(shatzap_boundary.boundary)
    return {
        'rule_code': 'TOPFLOOR_SETBACK_SHATZAP',
        'measured_value_m': round(measured, 3),
        'required_value_m': rule['threshold'],
        'verdict': 'pass' if measured >= rule['threshold'] else 'fail',
        'evidence': {
            'method': 'shapely_distance',
            'top_floor_source': 'DWG layer A-FLOR-TOPF',
            'shatzap_source': 'SHP MVT_PLAN_NUM, mavat_code=830',
        }
    }
```

### 4.3 Building footprint within plot boundary

```python
def check_building_within_plot(
    building: Polygon,    # DWG
    plot: Polygon,        # SHP (authoritative)
    tolerance_m: float = 0.05
) -> dict:
    """Building must be entirely within plot boundary (small tolerance for rounding)."""
    plot_buffered = plot.buffer(tolerance_m)
    is_within = plot_buffered.contains(building)
    
    if not is_within:
        # Find which parts protrude
        protrusion = building.difference(plot)
        return {
            'verdict': 'fail',
            'protrusion_area_sqm': round(protrusion.area, 3),
            'evidence': {
                'method': 'shapely_difference',
                'protrusion_polygon_itm': list(protrusion.exterior.coords) if not protrusion.is_empty else None,
            }
        }
    return {'verdict': 'pass'}
```

---

## 5. Cross-Reference Validation (CRITICAL)

This is the unique value of having three formats. Compare:

| Source | Says |
|---|---|
| PDF (architect's claim) | "232 residential units, plot 1 area = 6,762 m²" |
| DWG (architect's drawing) | Counted blocks: 234 units, measured plot = 6,758 m² |
| SHP (registry) | Official: 235 max units, LEGAL_AREA = 6,762 m² |

```python
def cross_reference_check(
    pdf_extract: dict,
    dwg_measurements: dict,
    shp_data: dict,
    tolerance_pct: float = 0.5
) -> list[dict]:
    """
    Compare values across all three sources. Flag discrepancies.
    """
    violations = []
    
    # Parcel count check
    if pdf_extract.get('parcel_count') != len(shp_data['parcels']):
        violations.append({
            'rule_code': 'PARCEL_COUNT_MISMATCH',
            'verdict': 'fail',
            'severity': 'critical',
            'pdf_value': pdf_extract['parcel_count'],
            'shp_value': len(shp_data['parcels']),
            'evidence': {
                'method': 'cross_reference',
                'sources': ['PDF table', 'SHP MVT_PLAN_NUM'],
            }
        })
    
    # Plot area check (per parcel)
    for shp_parcel in shp_data['parcels']:
        pdf_area = pdf_extract.get('plot_areas', {}).get(shp_parcel['parcel_id'])
        if pdf_area is None:
            continue
        
        shp_area = shp_parcel['legal_area_sqm']
        diff_pct = abs(pdf_area - shp_area) / shp_area * 100
        
        if diff_pct > tolerance_pct:
            violations.append({
                'rule_code': f'AREA_MISMATCH_PLOT_{shp_parcel["parcel_id"]}',
                'verdict': 'cross_reference_conflict',
                'severity': 'major',
                'pdf_value_sqm': pdf_area,
                'shp_value_sqm': shp_area,
                'difference_pct': round(diff_pct, 2),
            })
    
    return violations
```

---

## 6. Pre-flight Validation

Before running compliance checks, validate the geometries are processable:

```python
def preflight_geometry_check(geoms: list[Polygon]) -> list[dict]:
    """Check for common DWG geometry problems before analysis."""
    issues = []
    for i, geom in enumerate(geoms):
        if not geom.is_valid:
            issues.append({
                'index': i,
                'issue': 'invalid_geometry',
                'reason': geom.is_valid_reason if hasattr(geom, 'is_valid_reason') else 'unknown',
            })
        if hasattr(geom, 'is_closed') and not geom.is_closed:
            issues.append({
                'index': i,
                'issue': 'open_polyline',
                'gap_m': geom.boundary.length - geom.length,
            })
    return issues
```

If pre-flight fails, return `geometry_error` verdict — do NOT compute distances on invalid geometry.

---

## 7. Dependencies to Add

```bash
pip install pyshp pyproj shapely geopandas rasterio ezdxf
```

For DWG conversion (one-time setup):
```bash
# macOS
brew install libredwg

# Or use ODA File Converter:
# Download from https://www.opendesign.com/guestfiles/oda_file_converter
```

---

## 8. Definition of Done for Phase 4

The phase is complete when:

1. ✅ SHP reader extracts all 11 parcels from `407-1048248_קבצי_התכנית__SHP__1.zip` with correct mavat codes and areas
2. ✅ DWG reader converts AC1018 → DXF and reads layers from `407-1048248_קו_כחול.dwg` and `407-1048248_תאי_שטח.dwg`
3. ✅ Per-firm layer config table populated for Kika Braz Architects
4. ✅ Geometry compliance check on Kika Braz reference submission detects:
   - Building 1C top-floor setback violation: 2.85m measured, 3.0m required
   - Western building line not marked (WESTERN_LINE_PLOT_1)
5. ✅ Cross-reference validation flags PDF/SHP/DWG discrepancies as `cross_reference_conflict`
6. ✅ All geometric extracts stored with full evidence bundle (nearest_points, source layer, method)
7. ✅ Phase 4 results integrated into the חוות דעת PDF generated in Phase 3

---

## 9. Files to Create

```
src/
├── parsers/
│   ├── shp_reader.py          ← Build first
│   ├── dwg_reader.py          ← Build second
│   ├── dwg_layer_configs.py   ← Per-firm mappings
│   └── geometry_validator.py  ← Pre-flight checks
├── compliance/
│   ├── geometry_checks.py     ← Setback rules
│   └── cross_reference.py     ← PDF/DWG/SHP consistency
└── utils/
    ├── coordinate_systems.py  ← ITM ↔ WGS84
    └── mavat_codes.py         ← Land use code lookup

data/projects/407-0977595/
├── ממ"ג.zip                   ← SHP package
├── submissions/
│   └── submission_v1/
│       ├── תכנית_עיצוב.pdf    ← already in Phase 1
│       ├── תכנית_עיצוב.dwg    ← needed for Phase 4
│       └── ממ"ג.zip            ← optional (architect may include)
```

---

## 10. Open Questions Before Starting

1. **Where does the project's primary SHP come from?** From מנהל התכנון (loaded once at project onboarding), not from each submission. The submission may include its own DWG, but the SHP is the project's authoritative reference.

2. **What if architect's DWG and project's SHP disagree on parcel boundaries?** SHP wins. Flag as `boundary_conflict` violation.

3. **What about plans where MAVAT_CODE is unknown?** Log it, flag for admin review, do not block the engine. Add to MAVAT_CODES dict after confirmation.

4. **What if the architect doesn't submit a DWG at all?** All numeric and document_presence checks still work from PDF (Phase 1-2). Geometric checks return `input_missing` verdict. The חוות דעת will note that DWG was not submitted.

---

## 11. Why This Order Matters

**Build SHP first** because:
- It's structured data — no parsing ambiguity
- It's the authoritative reference — if anything wins, SHP wins
- Real-world test on 407-1048248 worked in 30 seconds, no configuration needed
- Once SHP is working, you have ground truth to validate DWG against

**Build DWG second** because:
- It's complex (per-firm config, AC1018 conversion, layer mapping)
- It's only needed for details the SHP doesn't have
- Easier to debug when you have SHP as a reference

**PDF cross-reference last** because:
- The Phase 1 parser already extracts these values
- Just compare three sets of numbers — straightforward logic
- This is where the real legal value emerges: "the architect's PDF claims X, but SHP shows Y, and DWG measures Z"
