"""Geometry extraction from DXF submission files.

Reads a DXF file, applies the project's layer mapping (layer_name → semantic
role), and returns typed Shapely polygons and lines per role. This is the data
layer for the CAD compliance checks in compliance_engine/cad_compliance_checker.py.

Supported entity types:
  LWPOLYLINE, POLYLINE → Polygon (closed/nearly-closed) or LineString (open)
  LINE                 → LineString
  CIRCLE               → approximated Polygon
  INSERT               → block reference; attributes extracted for AREA_ZONES
                         (USAGE_TYPE, AREA, ASSET from RZ_AREA_SYM / area_muni)

INSERT entities in AREA_ZONES layers carry a USAGE_TYPE block attribute:
  33 = parking → contributes to parking_polygons (via point-in-polygon)
  Other codes are collected in area_zones for future use.

Coordinate validation: warns if coordinates fall outside Israel ITM
(EPSG:2039) bounds (X ~100 000–300 000, Y ~400 000–900 000).

Unclosed polyline healing: if first and last vertices are ≤1mm apart, the
polyline is treated as closed so polygon extraction succeeds.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Israel ITM (EPSG:2039) approximate bounding box
_ITM_X_MIN, _ITM_X_MAX = 100_000, 300_000
_ITM_Y_MIN, _ITM_Y_MAX = 400_000, 900_000

# USAGE_TYPE code for parking in national RZ spec
_USAGE_PARKING = 33

# Block names that carry USAGE_TYPE attributes (national + Tel Aviv variants)
_AREA_BLOCK_NAMES = frozenset({"RZ_AREA_SYM", "area_muni"})

# Roles that contribute to AREA_ZONES polygon collection
_AREA_ZONE_ROLES = frozenset({"AREA_ZONES"})

# BUILDING_COVERAGE is treated as BUILDING_FOOTPRINT for geometric checks
_BUILDING_ROLES = frozenset({"BUILDING_FOOTPRINT", "BUILDING_COVERAGE"})


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AreaZone:
    """One AREA_ZONES polygon with its attribute data."""
    polygon: object              # shapely.Polygon
    usage_type: int | None = None
    usage_type_old: int | None = None
    area_sqm: float | None = None
    asset_count: int | None = None


@dataclass
class DXFGeometry:
    """Geometry extracted from a submission DXF, keyed by semantic role."""
    plot_boundary: Optional[object] = None          # shapely.Polygon
    building_footprint: Optional[object] = None     # shapely.Polygon
    setback_front_lines: list = field(default_factory=list)   # list[LineString]
    setback_side_lines: list = field(default_factory=list)
    setback_rear_lines: list = field(default_factory=list)
    public_space_polygons: list = field(default_factory=list)  # list[Polygon]
    parking_polygons: list = field(default_factory=list)       # list[Polygon]
    area_zones: list = field(default_factory=list)             # list[AreaZone]
    unmapped_layers: list[str] = field(default_factory=list)
    entity_counts: dict[str, int] = field(default_factory=dict)

    @property
    def has_plot_boundary(self) -> bool:
        return self.plot_boundary is not None

    @property
    def has_building_footprint(self) -> bool:
        return self.building_footprint is not None

    @property
    def building_footprint_area_sqm(self) -> float | None:
        if self.building_footprint is None:
            return None
        return float(self.building_footprint.area)

    @property
    def plot_boundary_area_sqm(self) -> float | None:
        if self.plot_boundary is None:
            return None
        return float(self.plot_boundary.area)


# ─────────────────────────────────────────────────────────────────────────────
# Coordinate validation
# ─────────────────────────────────────────────────────────────────────────────

def _check_itm_bounds(sample_points: list[tuple[float, float]]) -> None:
    """Log a warning if the majority of sample points are outside Israel ITM."""
    if not sample_points:
        return
    outside = sum(
        1 for x, y in sample_points
        if not (_ITM_X_MIN <= x <= _ITM_X_MAX and _ITM_Y_MIN <= y <= _ITM_Y_MAX)
    )
    ratio = outside / len(sample_points)
    if ratio > 0.5:
        log.warning(
            "DXF coordinates appear to be outside Israel ITM bounds "
            "(%d/%d sample points out of range). Geometric checks may be unreliable.",
            outside, len(sample_points),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Shapely helpers
# ─────────────────────────────────────────────────────────────────────────────

def _to_polygon(verts: list[tuple[float, float]]) -> object | None:
    """Convert a vertex list to a Shapely Polygon. Returns None if degenerate."""
    try:
        from shapely.geometry import Polygon
        if len(verts) < 3:
            return None
        poly = Polygon(verts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area <= 0:
            return None
        return poly
    except Exception as exc:
        log.debug("_to_polygon: %s", exc)
        return None


def _to_linestring(verts: list[tuple[float, float]]) -> object | None:
    try:
        from shapely.geometry import LineString
        if len(verts) < 2:
            return None
        return LineString(verts)
    except Exception as exc:
        log.debug("_to_linestring: %s", exc)
        return None


def _line_to_linestring(entity) -> object | None:
    try:
        from shapely.geometry import LineString
        s = entity.dxf.start
        e = entity.dxf.end
        return LineString([(s.x, s.y), (e.x, e.y)])
    except Exception as exc:
        log.debug("_line_to_linestring: %s", exc)
        return None


def _circle_to_polygon(entity, segments: int = 64) -> object | None:
    try:
        import math
        from shapely.geometry import Polygon
        cx = entity.dxf.center.x
        cy = entity.dxf.center.y
        r = entity.dxf.radius
        verts = [
            (cx + r * math.cos(2 * math.pi * i / segments),
             cy + r * math.sin(2 * math.pi * i / segments))
            for i in range(segments)
        ]
        return _to_polygon(verts)
    except Exception as exc:
        log.debug("_circle_to_polygon: %s", exc)
        return None


def _entity_to_verts(entity) -> list[tuple[float, float]] | None:
    """Extract vertex list from LWPOLYLINE or POLYLINE."""
    try:
        et = entity.dxftype()
        if et == "LWPOLYLINE":
            return [(v[0], v[1]) for v in entity.vertices()]
        elif et == "POLYLINE":
            return [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        return None
    except Exception as exc:
        log.debug("_entity_to_verts(%s): %s", entity.dxftype(), exc)
        return None


def _is_closed_or_healable(entity, verts: list[tuple[float, float]]) -> bool:
    """True if the entity forms a closed loop, or first/last vertices are ≤1mm apart."""
    try:
        et = entity.dxftype()
        if et == "LWPOLYLINE" and bool(entity.closed):
            return True
        if et == "POLYLINE" and bool(entity.is_closed):
            return True
    except Exception:
        pass
    if len(verts) >= 3:
        dx = verts[-1][0] - verts[0][0]
        dy = verts[-1][1] - verts[0][1]
        if (dx * dx + dy * dy) <= 1e-6:  # 1mm² threshold (ITM units = meters)
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Largest-polygon selector
# ─────────────────────────────────────────────────────────────────────────────

def _largest(polygons: list) -> object | None:
    if not polygons:
        return None
    return max(polygons, key=lambda p: p.area)


# ─────────────────────────────────────────────────────────────────────────────
# Block attribute extraction
# ─────────────────────────────────────────────────────────────────────────────

def _attrib_int(attribs: dict[str, str], key: str) -> int | None:
    val = attribs.get(key, "").strip()
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _attrib_float(attribs: dict[str, str], key: str) -> float | None:
    val = attribs.get(key, "").strip()
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _extract_block_attribs(entity) -> dict[str, str]:
    """Extract tag→value dict from an INSERT entity's ATTRIB children."""
    result: dict[str, str] = {}
    try:
        for attrib in entity.attribs:
            tag = attrib.dxf.tag.upper().strip()
            value = attrib.dxf.text.strip()
            result[tag] = value
    except Exception as exc:
        log.debug("_extract_block_attribs: %s", exc)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def extract_geometry(
    dxf_path: Path,
    layer_mapping: dict[str, str],
) -> DXFGeometry:
    """Extract geometry from a DXF submission file using the project's layer mapping.

    Two-pass algorithm:
    1. Collect all AREA_ZONES polygons and all other geometry by role.
    2. Process INSERT (block) entities with AREA_ZONE block names:
       extract USAGE_TYPE attribute and use point-in-polygon to assign
       attributes to the enclosing polygon.

    Args:
        dxf_path:      Path to the DXF file.
        layer_mapping: Dict mapping layer_name → semantic_role.

    Returns:
        DXFGeometry dataclass with per-role Shapely geometries.
    """
    import ezdxf

    result = DXFGeometry()
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    # Accumulators per role
    boundary_polys: list = []
    footprint_polys: list = []
    setback_front: list = []
    setback_side: list = []
    setback_rear: list = []
    public_polys: list = []
    parking_polys: list = []
    area_zone_polys: list = []    # raw polygons before attribute binding
    seen_unmapped: set[str] = set()
    sample_points: list[tuple[float, float]] = []

    # Deferred INSERT processing (need polygons first for point-in-polygon)
    deferred_inserts: list = []

    for entity in msp:
        et = entity.dxftype()
        layer_name = getattr(entity.dxf, "layer", "0")
        role = layer_mapping.get(layer_name, "UNKNOWN")

        result.entity_counts[layer_name] = result.entity_counts.get(layer_name, 0) + 1

        if et == "INSERT":
            block_name = getattr(entity.dxf, "name", "").upper()
            # Collect area-zone block inserts for pass 2
            if block_name in {b.upper() for b in _AREA_BLOCK_NAMES} or role in _AREA_ZONE_ROLES:
                deferred_inserts.append(entity)
            else:
                log.debug("Skipping INSERT block %s on layer %s", block_name, layer_name)
            continue

        if role in ("UNKNOWN", "OTHER"):
            seen_unmapped.add(layer_name)
            continue

        if et in ("LWPOLYLINE", "POLYLINE"):
            verts = _entity_to_verts(entity)
            if verts is None:
                continue

            # Collect sample points for ITM bounds check (first vertex only)
            if verts and len(sample_points) < 200:
                sample_points.append(verts[0])

            closed = _is_closed_or_healable(entity, verts)
            polygon_roles = _BUILDING_ROLES | _AREA_ZONE_ROLES | {"PLOT_BOUNDARY", "PUBLIC_SPACE", "PARKING"}

            if closed or (len(verts) >= 3 and role in polygon_roles):
                poly = _to_polygon(verts)
                if poly:
                    if role == "PLOT_BOUNDARY":
                        boundary_polys.append(poly)
                    elif role in _BUILDING_ROLES:
                        footprint_polys.append(poly)
                    elif role == "PUBLIC_SPACE":
                        public_polys.append(poly)
                    elif role == "PARKING":
                        parking_polys.append(poly)
                    elif role in _AREA_ZONE_ROLES:
                        area_zone_polys.append(poly)
                    continue

            # Open polyline → treat as setback line
            ls = _to_linestring(verts)
            if ls:
                if role == "SETBACK_FRONT":
                    setback_front.append(ls)
                elif role == "SETBACK_SIDE":
                    setback_side.append(ls)
                elif role == "SETBACK_REAR":
                    setback_rear.append(ls)

        elif et == "LINE":
            ls = _line_to_linestring(entity)
            if ls:
                if role == "SETBACK_FRONT":
                    setback_front.append(ls)
                elif role == "SETBACK_SIDE":
                    setback_side.append(ls)
                elif role == "SETBACK_REAR":
                    setback_rear.append(ls)

        elif et == "CIRCLE":
            poly = _circle_to_polygon(entity)
            if poly:
                if role == "PARKING":
                    parking_polys.append(poly)
                elif role == "PUBLIC_SPACE":
                    public_polys.append(poly)
                elif role in _AREA_ZONE_ROLES:
                    area_zone_polys.append(poly)

        else:
            log.debug("Skipping entity type %s on layer %s (role=%s)", et, layer_name, role)

    # Coordinate validation
    _check_itm_bounds(sample_points)

    # ── Pass 2: bind INSERT block attributes to AREA_ZONES polygons ───────
    # For each INSERT from an area-zone block, extract USAGE_TYPE and find
    # which polygon contains the insert's insertion point.
    area_zones: list[AreaZone] = [AreaZone(polygon=p) for p in area_zone_polys]

    for entity in deferred_inserts:
        try:
            from shapely.geometry import Point
            ins = entity.dxf.insert
            pt = Point(ins.x, ins.y)
            attribs = _extract_block_attribs(entity)
            usage_type = _attrib_int(attribs, "USAGE_TYPE")
            usage_type_old = _attrib_int(attribs, "USAGE_TYPE_OLD")
            area_sqm = _attrib_float(attribs, "AREA")
            asset_count = _attrib_int(attribs, "ASSET")

            matched = False
            for az in area_zones:
                try:
                    if az.polygon.contains(pt):
                        az.usage_type = usage_type
                        az.usage_type_old = usage_type_old
                        az.area_sqm = area_sqm
                        az.asset_count = asset_count
                        matched = True
                        break
                except Exception:
                    continue

            if not matched and usage_type is not None:
                # No enclosing polygon found — insert likely represents a standalone zone
                log.debug(
                    "INSERT block at (%.1f, %.1f) USAGE_TYPE=%s has no enclosing polygon",
                    ins.x, ins.y, usage_type,
                )
                # Still capture it as an unlocated zone for diagnostics
                area_zones.append(AreaZone(
                    polygon=pt.buffer(1.0),  # 1m stub polygon
                    usage_type=usage_type,
                    usage_type_old=usage_type_old,
                    area_sqm=area_sqm,
                    asset_count=asset_count,
                ))
        except Exception as exc:
            log.debug("Failed to process INSERT block: %s", exc)

    # ── Derive parking from AREA_ZONES with USAGE_TYPE=33 ─────────────────
    for az in area_zones:
        if az.usage_type == _USAGE_PARKING:
            parking_polys.append(az.polygon)

    # ── Assemble result ────────────────────────────────────────────────────
    result.plot_boundary = _largest(boundary_polys)
    result.building_footprint = _largest(footprint_polys)
    result.setback_front_lines = setback_front
    result.setback_side_lines = setback_side
    result.setback_rear_lines = setback_rear
    result.public_space_polygons = public_polys
    result.parking_polygons = parking_polys
    result.area_zones = area_zones
    result.unmapped_layers = sorted(seen_unmapped)

    log.info(
        "extract_geometry: boundary=%s footprint=%s public=%d parking=%d "
        "area_zones=%d (parking_from_uz=%d) unmapped=%d",
        result.plot_boundary_area_sqm,
        result.building_footprint_area_sqm,
        len(public_polys),
        len(parking_polys),
        len(area_zones),
        sum(1 for az in area_zones if az.usage_type == _USAGE_PARKING),
        len(seen_unmapped),
    )
    return result
