"""Pydantic models for per-page vision manifests.

These mirror the JSON schema in docs/m1_page_manifest_spec.md. PageManifest
is passed to Gemini Flash as `response_schema` so the model is constrained
to emit valid records. We keep the models flat (no unions / oneOf) so the
Gemini schema converter from clause_inventory.extract can reuse the same
cleaning pass.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class PageType(str, Enum):
    cover = "cover"
    table_of_contents = "table_of_contents"
    summary = "summary"
    site_plan_per_ta_shetach = "site_plan_per_ta_shetach"
    waste_diagram = "waste_diagram"
    functions_diagram = "functions_diagram"
    daycare = "daycare"
    basement_with_parking_table = "basement_with_parking_table"
    typical_floor = "typical_floor"
    cross_section = "cross_section"
    elevation = "elevation"
    public_open_space = "public_open_space"
    rendering = "rendering"
    legend_or_key = "legend_or_key"
    other = "other"


class PageQuality(str, Enum):
    ok = "ok"
    illegible = "illegible"
    incomplete = "incomplete"
    draft = "draft"
    blank = "blank"


ALLOWED_PAGE_TYPES = {p.value for p in PageType}
ALLOWED_PAGE_QUALITIES = {q.value for q in PageQuality}


class Dimension(BaseModel):
    value: float
    unit: str  # "m", "m²", "cm"
    context: str  # 1-3 word descriptor


class TableMarker(BaseModel):
    title: str
    estimated_rows: int


class DiagramMarker(BaseModel):
    type: str  # site_plan / floor_plan / section / elevation / diagram
    description: str  # 1-2 sentences


class PageManifest(BaseModel):
    page_number: int
    page_type: PageType
    ta_shetach_refs: List[int] = Field(default_factory=list)
    visible_text_labels: List[str] = Field(default_factory=list)
    visible_dimensions: List[Dimension] = Field(default_factory=list)
    tables_present: List[TableMarker] = Field(default_factory=list)
    diagrams_present: List[DiagramMarker] = Field(default_factory=list)
    page_quality: PageQuality


class PageManifestResponse(BaseModel):
    """Top-level schema Gemini emits per page. Wrapping a single PageManifest
    in an object satisfies Gemini's structured-output requirement (object,
    not bare scalar / array)."""

    manifest: PageManifest
