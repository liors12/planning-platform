#!/usr/bin/env python3
"""Create a synthetic RZ_ test DXF and verify extract_geometry() output."""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import ezdxf

OUTPUT = Path(__file__).parent / "fixtures" / "test_rz.dxf"

X_OFF = 180000.0
Y_OFF = 660000.0


def xy(x, y):
    return (x + X_OFF, y + Y_OFF)


def rect_verts(x1, y1, x2, y2):
    return [xy(x1, y1), xy(x2, y1), xy(x2, y2), xy(x1, y2)]


def add_closed_lwpoly(msp, verts, layer):
    e = msp.add_lwpolyline(verts, dxfattribs={"layer": layer})
    e.close(True)
    return e


def add_block(doc, name, attdefs):
    """Create block definition with ATTDEFs."""
    blk = doc.blocks.new(name)
    for i, (tag, default) in enumerate(attdefs):
        blk.add_attdef(tag=tag, insert=(0, -i * 20), text=default,
                       dxfattribs={"height": 5})
    return blk


def add_insert(msp, block_name, pt, attrib_values, layer="0"):
    """Add INSERT with ATTRIBs auto-created from block ATTDEFs."""
    ref = msp.add_blockref(block_name, pt, dxfattribs={"layer": layer})
    ref.add_auto_attribs(attrib_values)
    return ref


# ── Build DXF ────────────────────────────────────────────────────────────────

doc = ezdxf.new(dxfversion="R2010")
msp = doc.modelspace()

# Layers
for name, color in [
    ("RZ_AREA", 1),
    ("RZ_FLOOR", 3),
    ("RZ_FRAME", 5),
    ("RZ_LANCOVER", 4),
    ("RZ_ANCHOR", 6),
]:
    doc.layers.new(name, dxfattribs={"color": color})

# Block definitions
add_block(doc, "RZ_FRAME_SYM", [("SHEET_NO", "1")])
add_block(doc, "RZ_FLOOR_SYM", [
    ("BUILDING_NO", "1"),
    ("FLOOR", "קומת קרקע"),
    ("IS_UNDERGROUND", "0"),
    ("LEVEL_ELEVATION", "+0.00"),
])
add_block(doc, "RZ_AREA_SYM", [("USAGE_TYPE", "1")])

# ── Geometry ─────────────────────────────────────────────────────────────────

# 1. RZ_FRAME rectangle (print frame)
add_closed_lwpoly(msp, rect_verts(0, 0, 5000, 4000), "RZ_FRAME")

# 2. RZ_FRAME_SYM INSERT
add_insert(msp, "RZ_FRAME_SYM", xy(0, 0), {"SHEET_NO": "1"}, layer="RZ_FRAME")

# 3. Two RZ_FLOOR rectangles
add_closed_lwpoly(msp, rect_verts(100, 100, 2400, 1900), "RZ_FLOOR")
add_closed_lwpoly(msp, rect_verts(2600, 100, 4900, 1900), "RZ_FLOOR")

# 4. Two RZ_FLOOR_SYM INSERTs (block name triggers floor-def extraction)
add_insert(msp, "RZ_FLOOR_SYM", xy(100, 100), {
    "BUILDING_NO": "1",
    "FLOOR": "קומת קרקע",
    "IS_UNDERGROUND": "0",
    "LEVEL_ELEVATION": "+0.00",
}, layer="RZ_FLOOR")

add_insert(msp, "RZ_FLOOR_SYM", xy(2600, 100), {
    "BUILDING_NO": "1",
    "FLOOR": "קומה א",
    "IS_UNDERGROUND": "0",
    "LEVEL_ELEVATION": "+3.00",
}, layer="RZ_FLOOR")

# 5. Six RZ_AREA polygons (closed LWPOLYLINEs)
AREAS = [
    # name, x1, y1, x2, y2, cx, cy, usage_type
    ("Room1",   200,  200, 1100,  900,  650,  550, "1"),
    ("Room2",  1200,  200, 2300,  900, 1750,  550, "1"),
    ("Mamad",   200, 1000,  600, 1400,  400, 1200, "101"),
    ("Parking",1200, 1000, 2300, 1800, 1750, 1400, "33"),
    ("Lobby",   700, 1000, 1100, 1800,  900, 1400, "105"),
    ("Balcony",2300,  200, 2400,  600, 2350,  400, "30"),
]

for name, x1, y1, x2, y2, cx, cy, utype in AREAS:
    add_closed_lwpoly(msp, rect_verts(x1, y1, x2, y2), "RZ_AREA")
    add_insert(msp, "RZ_AREA_SYM", xy(cx, cy), {"USAGE_TYPE": utype}, layer="RZ_AREA")

# 6. RZ_LANCOVER polygon (covers floor 1 area)
add_closed_lwpoly(msp, rect_verts(100, 100, 2400, 1900), "RZ_LANCOVER")

# 7. RZ_ANCHOR entity (just a point to register the layer)
msp.add_point(xy(250, 250), dxfattribs={"layer": "RZ_ANCHOR"})

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
doc.saveas(str(OUTPUT))
print(f"✓ Saved {OUTPUT}")

# ── Verify with extract_geometry() ───────────────────────────────────────────

from vision_scanner.cad_ingest.dxf_geometry import extract_geometry

LAYER_MAPPING = {
    "RZ_AREA":    "AREA_ZONES",
    "RZ_FLOOR":   "OTHER",
    "RZ_FRAME":   "PLOT_BOUNDARY",
    "RZ_LANCOVER":"BUILDING_FOOTPRINT",
    "RZ_ANCHOR":  "UNKNOWN",
}

result = extract_geometry(OUTPUT, LAYER_MAPPING)

print()
print("═" * 50)
print("extract_geometry() results")
print("═" * 50)

# 1. Layers found in entity_counts
found_layers = set(result.entity_counts.keys())
expected_layers = {"RZ_AREA", "RZ_FLOOR", "RZ_FRAME", "RZ_LANCOVER", "RZ_ANCHOR"}
layers_ok = expected_layers.issubset(found_layers)
print(f"[{'✅' if layers_ok else '❌'}] 5 layers found: {sorted(found_layers)}")

# 2. Area zones
zone_count = len(result.area_zones)
zones_ok = zone_count == 6
usage_types = [az.usage_type for az in result.area_zones]
print(f"[{'✅' if zones_ok else '❌'}] area_zones count: {zone_count} (expected 6)")
print(f"      USAGE_TYPEs: {sorted(usage_types)}")

usage_types_ok = sorted(usage_types) == sorted([1, 1, 101, 33, 105, 30])
print(f"[{'✅' if usage_types_ok else '❌'}] USAGE_TYPE values correct: {sorted(usage_types)}")

# 3. Floor definitions
floor_count = len(result.floor_definitions)
floors_ok = floor_count == 2
print(f"[{'✅' if floors_ok else '❌'}] floor_definitions count: {floor_count} (expected 2)")
for fd in result.floor_definitions:
    print(f"      building_no={fd.building_no}, floor={fd.floor}, "
          f"is_underground={fd.is_underground}, level_elevation={fd.level_elevation}")

# 4. Parking polygons
parking_count = len(result.parking_polygons)
parking_ok = parking_count == 1
print(f"[{'✅' if parking_ok else '❌'}] parking_polygons count: {parking_count} (expected 1)")

# 5. Building footprint from RZ_LANCOVER
footprint_ok = result.building_footprint is not None
area = result.building_footprint_area_sqm if footprint_ok else None
print(f"[{'✅' if footprint_ok else '❌'}] building_footprint present: {footprint_ok} "
      f"(area={area:.1f} m²)" if footprint_ok else f"[{'✅' if footprint_ok else '❌'}] building_footprint present: {footprint_ok}")

# Summary
all_ok = layers_ok and zones_ok and usage_types_ok and floors_ok and parking_ok and footprint_ok
print()
print("═" * 50)
print(f"RESULT: {'ALL CHECKS PASSED ✅' if all_ok else 'SOME CHECKS FAILED ❌'}")
print("═" * 50)
sys.exit(0 if all_ok else 1)
