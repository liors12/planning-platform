"""Geometry extraction from DXF submission files.

Reads a DXF file, applies the project's layer mapping (layer_name → semantic
role), and returns typed Shapely polygons and lines per role. This is the data
layer for the CAD compliance checks in compliance_engine/cad_compliance_checker.py.

Supported entity types:
  LWPOLYLINE, POLYLINE → Polygon (closed) or LineString (open)
  LINE                 → LineString
  CIRCLE               → approximated Polygon

INSERT entities (blocks) are NOT exploded — only direct modelspace entities
are processed. Architecturally, the DXF submitted for compliance review should
be a flat drawing; if blocks appear, they're silently skipped (logged at DEBUG).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────

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
    unmapped_layers: list[str] = field(default_factory=list)
    # Total entity counts per layer for diagnostics
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


def _is_closed(entity) -> bool:
    """True if the entity forms a closed loop."""
    try:
        et = entity.dxftype()
        if et == "LWPOLYLINE":
            return bool(entity.closed)
        if et == "POLYLINE":
            return bool(entity.is_closed)
        return False
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Largest-polygon selector — when a layer has multiple closed polylines,
# pick the one with the largest area (the enclosing boundary).
# ─────────────────────────────────────────────────────────────────────────────

def _largest(polygons: list) -> object | None:
    if not polygons:
        return None
    return max(polygons, key=lambda p: p.area)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def extract_geometry(
    dxf_path: Path,
    layer_mapping: dict[str, str],
) -> DXFGeometry:
    """Extract geometry from a DXF submission file using the project's layer mapping.

    Args:
        dxf_path:      Path to the DXF file.
        layer_mapping: Dict mapping layer_name → semantic_role (e.g. "PLOT_BOUNDARY").

    Returns:
        DXFGeometry dataclass with per-role Shapely geometries.

    Raises:
        ImportError: if ezdxf or shapely is not installed.
        IOError:     if the DXF cannot be read.
    """
    import ezdxf

    result = DXFGeometry()
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    # Accumulators per role (we may see multiple polygons per layer)
    boundary_polys: list = []
    footprint_polys: list = []
    setback_front: list = []
    setback_side: list = []
    setback_rear: list = []
    public_polys: list = []
    parking_polys: list = []
    seen_unmapped: set[str] = set()

    for entity in msp:
        et = entity.dxftype()
        layer_name = getattr(entity.dxf, "layer", "0")
        role = layer_mapping.get(layer_name, "UNKNOWN")

        # Track entity counts for diagnostics
        result.entity_counts[layer_name] = result.entity_counts.get(layer_name, 0) + 1

        if role in ("UNKNOWN", "OTHER"):
            seen_unmapped.add(layer_name)
            continue

        if et in ("LWPOLYLINE", "POLYLINE"):
            verts = _entity_to_verts(entity)
            if verts is None:
                continue
            closed = _is_closed(entity)
            if closed or (len(verts) >= 3 and role in (
                "PLOT_BOUNDARY", "BUILDING_FOOTPRINT", "PUBLIC_SPACE", "PARKING"
            )):
                poly = _to_polygon(verts)
                if poly:
                    if role == "PLOT_BOUNDARY":
                        boundary_polys.append(poly)
                    elif role == "BUILDING_FOOTPRINT":
                        footprint_polys.append(poly)
                    elif role == "PUBLIC_SPACE":
                        public_polys.append(poly)
                    elif role == "PARKING":
                        parking_polys.append(poly)
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
                elif role == "PLOT_BOUNDARY":
                    pass  # single lines don't form a boundary polygon
                elif role == "BUILDING_FOOTPRINT":
                    pass

        elif et == "CIRCLE":
            poly = _circle_to_polygon(entity)
            if poly:
                if role == "PARKING":
                    parking_polys.append(poly)
                elif role == "PUBLIC_SPACE":
                    public_polys.append(poly)

        else:
            log.debug("Skipping entity type %s on layer %s (role=%s)", et, layer_name, role)

    # Pick the largest boundary/footprint polygon when multiple are present
    result.plot_boundary = _largest(boundary_polys)
    result.building_footprint = _largest(footprint_polys)
    result.setback_front_lines = setback_front
    result.setback_side_lines = setback_side
    result.setback_rear_lines = setback_rear
    result.public_space_polygons = public_polys
    result.parking_polygons = parking_polys
    result.unmapped_layers = sorted(seen_unmapped)

    log.info(
        "extract_geometry: boundary=%s footprint=%s public=%d parking=%d unmapped=%d",
        result.plot_boundary_area_sqm,
        result.building_footprint_area_sqm,
        len(public_polys),
        len(parking_polys),
        len(seen_unmapped),
    )
    return result
