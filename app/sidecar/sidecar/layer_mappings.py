"""Layer mapping endpoints — DXF layer → semantic role per project.

  GET    /projects/{project_id}/layer-mappings          — list all mappings
  POST   /projects/{project_id}/layer-mappings/discover — scan DXF + seed rows
  PATCH  /projects/{project_id}/layer-mappings/{layer}  — update role (Ellen confirms)
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
# Heuristics
# ─────────────────────────────────────────────────────────────────────────────

# Tier 1 — exact layer name → role (firm-specific known names from existing DXFs)
_EXACT: dict[str, str] = {
    # Ness Ziona firm defaults (observed in existing project DXFs)
    "pgvul1": "PLOT_BOUNDARY",
    "pcell": "PLOT_BOUNDARY",
    "pvul": "PLOT_BOUNDARY",
    "scellno": "OTHER",
    # Common generic names
    "boundary": "PLOT_BOUNDARY",
    "plot": "PLOT_BOUNDARY",
    "footprint": "BUILDING_FOOTPRINT",
    "building": "BUILDING_FOOTPRINT",
    "setback": "SETBACK_FRONT",
    "parking": "PARKING",
    "parkings": "PARKING",
}

# Tier 2 — RZ_ (Rishui Zamin / rezoning approval) standard prefixes from gov.il spec.
# Present in formal submission DXFs; may be absent in early-stage files.
_RZ_PREFIX: dict[str, str] = {
    "RZ_BOUNDARY":      "PLOT_BOUNDARY",
    "RZ_AREA":          "PLOT_BOUNDARY",
    "RZ_FOOTPRINT":     "BUILDING_FOOTPRINT",
    "RZ_LANDCOVER":     "BUILDING_FOOTPRINT",
    "RZ_SETBACK_F":     "SETBACK_FRONT",
    "RZ_SETBACK_FRONT": "SETBACK_FRONT",
    "RZ_SETBACK_S":     "SETBACK_SIDE",
    "RZ_SETBACK_SIDE":  "SETBACK_SIDE",
    "RZ_SETBACK_R":     "SETBACK_REAR",
    "RZ_SETBACK_REAR":  "SETBACK_REAR",
    "RZ_SETBACK":       "SETBACK_FRONT",   # generic setback → treat as front
    "RZ_PUBLIC":        "PUBLIC_SPACE",
    "RZ_GREEN":         "PUBLIC_SPACE",
    "RZ_PARKING":       "PARKING",
    "RZ_PARK":          "PARKING",
}

# Tier 3 — substring / keyword heuristics (Hebrew and English)
_PATTERNS: list[tuple[str, str]] = [
    (r"גבול\s*מגרש|גבמגרש|gvul|pvul",           "PLOT_BOUNDARY"),
    (r"תכסית|תכס|buildingfoot|bldg_foot",         "BUILDING_FOOTPRINT"),
    (r"קו\s*בנין\s*קד|setback.{0,4}front|חזית",  "SETBACK_FRONT"),
    (r"קו\s*בנין\s*צד|setback.{0,4}side|צד",     "SETBACK_SIDE"),
    (r"קו\s*בנין\s*אחו|setback.{0,4}rear|אחור",  "SETBACK_REAR"),
    (r"קו\s*בנין|קובנ|setback",                   "SETBACK_FRONT"),
    (r'שצ"פ|שצפ|public.?space|green.?area|ירוק', "PUBLIC_SPACE"),
    (r"חנייה|חניה|parking|חנ",                    "PARKING"),
]


def _classify_layer(name: str) -> tuple[str, str]:
    """Return (role, confidence) for a layer name using three-tier heuristics."""
    low = name.lower().strip()
    up = name.upper().strip()

    # Tier 1 — exact match (case-insensitive)
    if low in _EXACT:
        return _EXACT[low], "AUTO"

    # Tier 2 — RZ_ prefix (case-insensitive on the full name)
    if up in _RZ_PREFIX:
        return _RZ_PREFIX[up], "AUTO"

    # Also match RZ_ prefix with suffix variations not listed explicitly
    if up.startswith("RZ_"):
        for key, role in _RZ_PREFIX.items():
            if up.startswith(key):
                return role, "HEURISTIC"

    # Tier 3 — pattern matching
    for pattern, role in _PATTERNS:
        if re.search(pattern, name, re.IGNORECASE):
            return role, "HEURISTIC"

    return "UNKNOWN", "HEURISTIC"


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
