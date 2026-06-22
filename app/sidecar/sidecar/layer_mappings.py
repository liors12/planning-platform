"""Layer mapping endpoints — DXF layer → semantic role per project.

  GET    /projects/{project_id}/layer-mappings          — list all mappings
  POST   /projects/{project_id}/layer-mappings/discover — scan DXF + seed rows
  PATCH  /projects/{project_id}/layer-mappings/{layer}  — update role (Ellen confirms)

Layer roles follow the national רישוי זמין (RZ) spec from מינהל התכנון:
  RZ_AREA     → AREA_ZONES      (area polygons with USAGE_TYPE attribute)
  RZ_FLOOR    → FLOOR_DEFINITION
  RZ_FRAME    → PRINT_FRAME
  RZ_LANCOVER → BUILDING_COVERAGE  (note: single V, not LANDCOVER)
  RZ_ANCHOR   → GEOGRAPHIC_ANCHOR

Usage type codes (from USAGE_TYPE block attribute on RZ_AREA_SYM):
  1=residential, 33=parking, 10=public buildings, 30=balcony, etc.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .config import Config
from .models import LayerMapping, Project, Submission

router = APIRouter(prefix="/projects", tags=["layer-mappings"])

# ─────────────────────────────────────────────────────────────────────────────
# Role constants
# ─────────────────────────────────────────────────────────────────────────────

VALID_ROLES = {
    # National standard (רישוי זמין) roles
    "AREA_ZONES",           # RZ_AREA — polygons tagged with USAGE_TYPE
    "FLOOR_DEFINITION",     # RZ_FLOOR
    "PRINT_FRAME",          # RZ_FRAME
    "BUILDING_COVERAGE",    # RZ_LANCOVER — ground coverage (תכסית)
    "GEOGRAPHIC_ANCHOR",    # RZ_ANCHOR
    # Geometric roles (used by compliance checks)
    "PLOT_BOUNDARY",
    "BUILDING_FOOTPRINT",
    "SETBACK_FRONT",
    "SETBACK_SIDE",
    "SETBACK_REAR",
    "PUBLIC_SPACE",
    "PARKING",
    "OTHER",
    "UNKNOWN",
}


# ─────────────────────────────────────────────────────────────────────────────
# Heuristics — four tiers
# ─────────────────────────────────────────────────────────────────────────────

# Tier 1 — National RZ_ standard (HIGH confidence).
# Exact uppercase layer names from מינהל התכנון official guide.
_TIER1_RZ: dict[str, str] = {
    # Core RZ layers (confirmed from official spec)
    "RZ_AREA":      "AREA_ZONES",        # area polygons, USAGE_TYPE attribute
    "RZ_FLOOR":     "FLOOR_DEFINITION",  # floor definition
    "RZ_FRAME":     "PRINT_FRAME",       # print frame
    "RZ_LANCOVER":  "BUILDING_COVERAGE", # ground coverage/תכסית (single V)
    "RZ_ANCHOR":    "GEOGRAPHIC_ANCHOR", # geographic anchor point
    # Additional RZ geometry layers (setbacks, plot, public space, parking)
    "RZ_BOUNDARY":      "PLOT_BOUNDARY",
    "RZ_FOOTPRINT":     "BUILDING_FOOTPRINT",
    "RZ_SETBACK_F":     "SETBACK_FRONT",
    "RZ_SETBACK_FRONT": "SETBACK_FRONT",
    "RZ_SETBACK_S":     "SETBACK_SIDE",
    "RZ_SETBACK_SIDE":  "SETBACK_SIDE",
    "RZ_SETBACK_R":     "SETBACK_REAR",
    "RZ_SETBACK_REAR":  "SETBACK_REAR",
    "RZ_SETBACK":       "SETBACK_FRONT",  # generic → treat as front
    "RZ_PUBLIC":        "PUBLIC_SPACE",
    "RZ_GREEN":         "PUBLIC_SPACE",
    "RZ_PARKING":       "PARKING",
    "RZ_PARK":          "PARKING",
}

# Tier 2 — Tel Aviv municipal variant (MEDIUM confidence).
# muni_* layer names and block names from רישוי עסקים spec.
_TIER2_MUNI: dict[str, str] = {
    "muni_area":  "AREA_ZONES",
    "area_muni":  "AREA_ZONES",
    "muni_floor": "FLOOR_DEFINITION",
    "floor_muni": "FLOOR_DEFINITION",
    "muni_plot":  "PRINT_FRAME",
    "plot_muni":  "PRINT_FRAME",
}

# Tier 3 — firm-specific exact names (HIGH confidence for known firms).
_TIER3_EXACT: dict[str, str] = {
    "pgvul1":    "PLOT_BOUNDARY",
    "pcell":     "PLOT_BOUNDARY",
    "pvul":      "PLOT_BOUNDARY",
    "scellno":   "OTHER",
    "boundary":  "PLOT_BOUNDARY",
    "plot":      "PLOT_BOUNDARY",
    "footprint": "BUILDING_FOOTPRINT",
    "building":  "BUILDING_FOOTPRINT",
    "setback":   "SETBACK_FRONT",
    "parking":   "PARKING",
    "parkings":  "PARKING",
}

# Tier 4 — substring / keyword heuristics (LOW confidence).
_TIER4_PATTERNS: list[tuple[str, str]] = [
    (r"גבול\s*מגרש|גבמגרש|gvul|pvul",           "PLOT_BOUNDARY"),
    (r"תכסית|תכס|buildingfoot|bldg_foot",         "BUILDING_FOOTPRINT"),
    (r"קו\s*בנין\s*קד|setback.{0,4}front|חזית",  "SETBACK_FRONT"),
    (r"קו\s*בנין\s*צד|setback.{0,4}side|צד",     "SETBACK_SIDE"),
    (r"קו\s*בנין\s*אחו|setback.{0,4}rear|אחור",  "SETBACK_REAR"),
    (r"קו\s*בנין|קובנ|setback|kav.?binyan",       "SETBACK_FRONT"),
    (r'שצ"פ|שצפ|public.?space|green.?area|ירוק', "PUBLIC_SPACE"),
    (r"חנייה|חניה|parking|חנ",                    "PARKING"),
    (r"שטח|area|zone",                             "AREA_ZONES"),
    (r"floor|קומה|קומות|manzor",                  "FLOOR_DEFINITION"),
]


def _classify_layer(name: str) -> tuple[str, str]:
    """Return (role, confidence) for a layer name using four-tier heuristics."""
    low = name.lower().strip()
    up = name.upper().strip()

    # Tier 1 — RZ_ national standard (exact match, case-insensitive upper)
    if up in _TIER1_RZ:
        return _TIER1_RZ[up], "HIGH"

    # Also match RZ_ prefix with suffix variations not in the explicit list
    if up.startswith("RZ_"):
        for key, role in _TIER1_RZ.items():
            if up.startswith(key):
                return role, "HIGH"

    # Tier 2 — muni_ municipal variant (exact match, case-insensitive lower)
    if low in _TIER2_MUNI:
        return _TIER2_MUNI[low], "MEDIUM"

    # Tier 3 — firm-specific exact names (case-insensitive lower)
    if low in _TIER3_EXACT:
        return _TIER3_EXACT[low], "HIGH"

    # Tier 4 — keyword/regex patterns (LOW confidence)
    for pattern, role in _TIER4_PATTERNS:
        if re.search(pattern, name, re.IGNORECASE):
            return role, "LOW"

    return "UNKNOWN", "LOW"


def discover_layers_from_dxf(dxf_path: Path) -> list[str]:
    """Return the set of layer names present in the DXF file."""
    try:
        import ezdxf
        doc = ezdxf.readfile(str(dxf_path))
        return [layer.dxf.name for layer in doc.layers]
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic I/O
# ─────────────────────────────────────────────────────────────────────────────

class LayerMappingOut(BaseModel):
    id: int
    project_id: int
    layer_name: str
    role: str
    confidence: str
    confirmed: bool
    updated_at: str


class LayerMappingPatch(BaseModel):
    role: str
    confirmed: bool = True


# ─────────────────────────────────────────────────────────────────────────────
# Router factory
# ─────────────────────────────────────────────────────────────────────────────

def make_router(get_engine, cfg: Config):
    def _session() -> Session:
        return Session(get_engine())

    def _latest_cad_path(sess: Session, project_id: int) -> Path | None:
        """Find the most recently uploaded DXF file for this project."""
        rows = (
            sess.query(Submission)
            .filter(
                Submission.project_id == project_id,
                Submission.dwg_path.isnot(None),
            )
            .order_by(Submission.uploaded_at.desc())
            .limit(10)
            .all()
        )
        for row in rows:
            p = Path(row.dwg_path)
            if p.exists() and p.suffix.lower() == ".dxf":
                return p
        return None

    def _seed_mappings(sess: Session, project_id: int, dxf_path: Path) -> list[LayerMapping]:
        """Populate layer_mappings for project from DXF, skipping existing rows."""
        layer_names = discover_layers_from_dxf(dxf_path)
        seeded: list[LayerMapping] = []
        for name in layer_names:
            existing = (
                sess.query(LayerMapping)
                .filter_by(project_id=project_id, layer_name=name)
                .first()
            )
            if existing:
                continue
            role, confidence = _classify_layer(name)
            m = LayerMapping(
                project_id=project_id,
                layer_name=name,
                role=role,
                confidence=confidence,
                confirmed=False,
            )
            sess.add(m)
            seeded.append(m)
        return seeded

    # ── GET /projects/{project_id}/layer-mappings ──────────────────────────

    @router.get("/{project_id}/layer-mappings", response_model=list[LayerMappingOut])
    def list_layer_mappings(project_id: int) -> list[LayerMappingOut]:
        with _session() as sess:
            if sess.get(Project, project_id) is None:
                raise HTTPException(404, f"project {project_id} not found")

            rows = (
                sess.query(LayerMapping)
                .filter_by(project_id=project_id)
                .order_by(LayerMapping.layer_name)
                .all()
            )

            # Auto-discover if no rows yet and a DXF is available
            if not rows:
                dxf_path = _latest_cad_path(sess, project_id)
                if dxf_path:
                    _seed_mappings(sess, project_id, dxf_path)
                    sess.commit()
                    rows = (
                        sess.query(LayerMapping)
                        .filter_by(project_id=project_id)
                        .order_by(LayerMapping.layer_name)
                        .all()
                    )

            return [LayerMappingOut(**m.to_dict()) for m in rows]

    # ── POST /projects/{project_id}/layer-mappings/discover ───────────────

    @router.post("/{project_id}/layer-mappings/discover",
                 response_model=list[LayerMappingOut], status_code=201)
    def discover_layer_mappings(project_id: int) -> list[LayerMappingOut]:
        """Force a re-scan of the latest DXF and add any new layers."""
        with _session() as sess:
            if sess.get(Project, project_id) is None:
                raise HTTPException(404, f"project {project_id} not found")

            dxf_path = _latest_cad_path(sess, project_id)
            if dxf_path is None:
                raise HTTPException(
                    422, "אין קובץ DXF שהועלה לפרויקט זה — העלי קובץ DXF תחילה"
                )

            _seed_mappings(sess, project_id, dxf_path)
            sess.commit()

            rows = (
                sess.query(LayerMapping)
                .filter_by(project_id=project_id)
                .order_by(LayerMapping.layer_name)
                .all()
            )
            return [LayerMappingOut(**m.to_dict()) for m in rows]

    # ── PATCH /projects/{project_id}/layer-mappings/{layer_name} ──────────

    @router.patch("/{project_id}/layer-mappings/{layer_name}",
                  response_model=LayerMappingOut)
    def update_layer_mapping(
        project_id: int,
        layer_name: str,
        body: LayerMappingPatch,
    ) -> LayerMappingOut:
        if body.role not in VALID_ROLES:
            raise HTTPException(
                422,
                f"תפקיד לא חוקי: {body.role!r}. תפקידים תקפים: {sorted(VALID_ROLES)}"
            )
        with _session() as sess:
            if sess.get(Project, project_id) is None:
                raise HTTPException(404, f"project {project_id} not found")

            row = (
                sess.query(LayerMapping)
                .filter_by(project_id=project_id, layer_name=layer_name)
                .first()
            )
            if row is None:
                raise HTTPException(404, f"שכבה {layer_name!r} לא נמצאה בפרויקט זה")

            row.role = body.role
            row.confirmed = body.confirmed
            row.confidence = "MANUAL"
            row.updated_at = datetime.now(timezone.utc)
            sess.commit()
            sess.refresh(row)
            return LayerMappingOut(**row.to_dict())

    return router
