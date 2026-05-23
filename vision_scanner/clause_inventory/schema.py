"""Pydantic models for clause inventory.

These mirror the JSON schema in docs/m0_clause_inventory_spec.md. The
top-level ClausesResponse is passed to Gemini as `response_schema` so the
model is constrained to emit valid clause records.

Gemini's structured-output mode supports an OpenAPI 3.0 subset; we keep
the models flat (no unions, no oneOf). Fields that only apply to the §5
building-rights table (structured_values, general_footnotes, cell_footnotes)
are Optional on the base Clause shape.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Category(str, Enum):
    identification = "identification"
    objectives = "objectives"
    land_use_zoning = "land_use_zoning"
    building_geometry = "building_geometry"
    building_rights = "building_rights"
    building_use = "building_use"
    parking = "parking"
    infrastructure = "infrastructure"
    stormwater = "stormwater"
    tree_preservation = "tree_preservation"
    unification_subdivision = "unification_subdivision"
    public_areas = "public_areas"
    easements = "easements"
    building_height_safety = "building_height_safety"
    phasing = "phasing"
    procedural = "procedural"


ALLOWED_CATEGORIES = {c.value for c in Category}


class StructuredRow(BaseModel):
    """One row of the §5 building rights table (one ta_shetach / plot)."""

    ta_shetach: Optional[int] = None
    use: Optional[str] = None
    plot_area_m2: Optional[float] = None
    primary_area_m2: Optional[float] = None
    service_area_above_m2: Optional[float] = None
    service_area_below_m2: Optional[float] = None
    total_built_m2: Optional[float] = None
    units: Optional[int] = None
    max_height_m: Optional[float] = None
    floors_above: Optional[int] = None
    floors_below: Optional[int] = None
    setbacks: Optional[str] = None
    balcony_area_m2: Optional[float] = None
    cell_footnote_refs: List[int] = Field(default_factory=list)


class GeneralFootnote(BaseModel):
    id: str
    text: str


class CellFootnote(BaseModel):
    id: int
    text: str


class Clause(BaseModel):
    clause_id: str
    parent_id: Optional[str] = None
    section_title_chain: List[str] = Field(default_factory=list)
    clause_text: str
    page: int
    category: Category
    is_quantitative: bool
    is_normative: bool
    structured_values: Optional[List[StructuredRow]] = None
    general_footnotes: Optional[List[GeneralFootnote]] = None
    cell_footnotes: Optional[List[CellFootnote]] = None


class ClausesResponse(BaseModel):
    """Top-level schema Gemini emits. Wrapped in {clauses: [...]} so the
    response is an object (Gemini structured output requires a top-level
    object, not a bare array)."""

    clauses: List[Clause]
