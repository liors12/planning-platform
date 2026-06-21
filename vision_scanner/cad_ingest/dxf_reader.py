"""ezdxf + shapely extraction of plot polygons from תב"ע tashrit DXFs.

Critical design choice (per Phase 7.1 spec, Q1 = polygon):
  The CAD INSERT block's `AREA` ATTRIB is treated as METADATA ONLY — not
  authoritative. Smoke-test investigation found 2 plots (9, 20) with
  copy-pasted AREA values and 1 plot (10) with a stale AREA. The polygon's
  geometric area (`shapely.Polygon.area`) is authoritative everywhere.

  When polygon area and AREA ATTRIB differ by >5%, we emit a structured
  discrepancy record (saved by the caller to
  data/projects/<plan>/cad_attribute_discrepancies.json). This is internal
  data-quality monitoring — never surfaced in the architect-facing PDF.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ezdxf
from shapely.geometry import Point, Polygon


# Discrepancy threshold — any AREA-attribute vs polygon-area mismatch above this
# magnitude triggers a structured log entry.
DISCREPANCY_THRESHOLD_PCT = 5.0


def _classify_discrepancy(pct: float, plot_id: int, attr_area: float,
                          all_attr_areas: Dict[int, float]) -> Tuple[str, str]:
    """Heuristic classifier for the discrepancy log.

    ATTRIBUTE_CORRUPTED → AREA value matches another plot's AREA (copy-paste).
    ATTRIBUTE_STALE     → AREA differs from geometry but not a copy of any other.
    """
    duplicates = [
        pid for pid, a in all_attr_areas.items()
        if pid != plot_id and abs(a - attr_area) < 0.01
    ]
    if duplicates:
        return (
            "ATTRIBUTE_CORRUPTED",
            f"AREA attribute matches plot {duplicates[0]}'s value — "
            f"suspected copy-paste bug in source CAD"
        )
    return (
        "ATTRIBUTE_STALE",
        "AREA attribute appears stale (likely pre-revision)"
    )


def _polyline_to_shapely(entity) -> Optional[Polygon]:
    """Convert an LWPOLYLINE (or POLYLINE) entity to a shapely Polygon."""
    try:
        if entity.dxftype() == "LWPOLYLINE":
            verts = [(v[0], v[1]) for v in entity.vertices()]
        else:
            verts = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
    except Exception:
        return None
    if len(verts) < 3:
        return None
    try:
        poly = Polygon(verts)
        if not poly.is_valid:
            # Try buffer(0) repair (handles self-intersecting trivially)
            poly = poly.buffer(0)
        if poly.is_empty or poly.area <= 0:
            return None
        return poly
    except Exception:
        return None


def read_plot_polygons(
    dxf_path: Path,
    *,
    block_name: str = "cellno",
    polygon_layer: str = "pcell",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Extract plot polygons from a תב"ע tashrit DXF.

    Returns (plots, discrepancies):
      plots: [{ "cellno": int, "code": str, "area_attr_m2": float,
                "area_m2": float (polygon-derived, AUTHORITATIVE),
                "polygon": shapely.Polygon, "polygon_wkt": str,
                "insert_point": (x, y) }, ...]
      discrepancies: [{ "plot_id": int, "polygon_area_m2": float,
                        "attribute_area_m2": float, "discrepancy_percent": float,
                        "verdict": "ATTRIBUTE_CORRUPTED" | "ATTRIBUTE_STALE",
                        "notes": str }, ...]
    """
    dxf_path = Path(dxf_path)
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    # 1. Collect candidate polygons on the target layer
    candidate_polygons: List[Tuple[int, Polygon]] = []
    for idx, e in enumerate(msp):
        if e.dxftype() == "LWPOLYLINE" and e.closed and e.dxf.layer == polygon_layer:
            poly = _polyline_to_shapely(e)
            if poly is not None:
                candidate_polygons.append((idx, poly))

    # 2. Collect INSERT records pointing at the target block
    insert_records = []
    for idx, e in enumerate(msp):
        if e.dxftype() == "INSERT" and e.dxf.name == block_name:
            attrs = {a.dxf.tag: a.dxf.text for a in e.attribs}
            try:
                cellno = int(attrs.get("CELLNO", "-1"))
            except ValueError:
                continue
            try:
                attr_area = float(attrs.get("AREA", "0"))
            except ValueError:
                attr_area = 0.0
            insert_records.append({
                "idx": idx,
                "cellno": cellno,
                "code": str(attrs.get("CODE", "")).strip(),
                "area_attr_m2": attr_area,
                "insert_point": (e.dxf.insert.x, e.dxf.insert.y),
            })

    # 3. Match each INSERT to its polygon (contains → fallback nearest centroid)
    used_polygon_indices = set()
    plots: List[Dict[str, Any]] = []
    for rec in insert_records:
        pt = Point(rec["insert_point"])
        matched_idx = None
        matched_poly = None
        # First pass: polygon that geometrically contains the insert point
        for idx, poly in candidate_polygons:
            if idx in used_polygon_indices:
                continue
            if poly.contains(pt):
                matched_idx = idx
                matched_poly = poly
                break
        # Fallback: nearest polygon by centroid distance
        if matched_poly is None:
            best = None
            best_d = float("inf")
            for idx, poly in candidate_polygons:
                if idx in used_polygon_indices:
                    continue
                d = pt.distance(poly.centroid)
                if d < best_d:
                    best_d = d
                    best = (idx, poly)
            if best is not None:
                matched_idx, matched_poly = best
        if matched_poly is None:
            # No polygon at all — skip; will be flagged downstream as orphan
            continue
        used_polygon_indices.add(matched_idx)
        plots.append({
            "cellno": rec["cellno"],
            "code": rec["code"],
            "area_attr_m2": round(rec["area_attr_m2"], 2),
            "area_m2": round(matched_poly.area, 2),
            "polygon": matched_poly,
            "polygon_wkt": matched_poly.wkt,
            "insert_point": (
                round(rec["insert_point"][0], 2),
                round(rec["insert_point"][1], 2),
            ),
        })

    # 4. Compute discrepancies (>5% delta between polygon and ATTRIB)
    plots.sort(key=lambda p: p["cellno"])
    all_attr_areas = {p["cellno"]: p["area_attr_m2"] for p in plots}
    discrepancies: List[Dict[str, Any]] = []
    for p in plots:
        attr = p["area_attr_m2"]
        geom = p["area_m2"]
        if attr <= 0:
            continue
        pct = round(100.0 * (attr - geom) / geom, 1) if geom > 0 else float("inf")
        if abs(pct) > DISCREPANCY_THRESHOLD_PCT:
            verdict, notes = _classify_discrepancy(pct, p["cellno"], attr, all_attr_areas)
            discrepancies.append({
                "plot_id": p["cellno"],
                "polygon_area_m2": geom,
                "attribute_area_m2": attr,
                "discrepancy_percent": pct,
                "verdict": verdict,
                "notes": notes,
            })

    return plots, discrepancies


def read_blue_line_polygon(
    dxf_path: Path,
    *,
    primary_layer: str = "pgvul1",
) -> Optional[Polygon]:
    """Extract the תב"ע boundary polygon (קו כחול) from the boundary DXF.

    Returns the polygon on `primary_layer`. If multiple closed polylines exist
    on that layer, returns the one with the largest area.
    """
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()
    candidates = []
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.closed and e.dxf.layer == primary_layer:
            poly = _polyline_to_shapely(e)
            if poly is not None:
                candidates.append(poly)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.area)
