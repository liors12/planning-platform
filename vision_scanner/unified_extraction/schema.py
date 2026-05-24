"""Pydantic models for M2 unified extraction.

Mirrors docs/m2_unified_extraction_spec.md. Models are flat (no unions /
oneOf) so vision_scanner.clause_inventory.extract.pydantic_to_gemini_schema
can reuse the same cleaning pass when emitting the Gemini response_schema.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class ComplianceIndicator(str, Enum):
    compliant = "compliant"
    non_compliant = "non_compliant"
    requires_review = "requires_review"
    missing = "missing"
    deferred_to_dwg = "deferred_to_dwg"


class BboxTag(str, Enum):
    primary = "primary"
    supporting = "supporting"


class PlotMappingMethod(str, Enum):
    auto = "auto"


ALLOWED_CONFIDENCES = {c.value for c in Confidence}
ALLOWED_COMPLIANCE = {c.value for c in ComplianceIndicator}
ALLOWED_BBOX_TAGS = {t.value for t in BboxTag}


class ExtractionValue(BaseModel):
    value: str  # always a string; preserves "10 floors", "450 m³", "compliant", etc.
    unit: Optional[str] = None  # e.g. "floors", "m³", "m", "%"; None for qualitative
    raw_text_match: str  # snippet from the page that justifies the extraction


class EvidenceBbox(BaseModel):
    page: int  # 1-indexed, must be in [1, 63]
    bbox: List[float]  # [x1, y1, x2, y2] in rasterized image pixel space
    tag: BboxTag


class Finding(BaseModel):
    clause_id: str  # must resolve to a clause in canonical_clauses.json
    clause_text_excerpt: str  # first ~200 chars
    extraction: ExtractionValue
    source_pages: List[int] = Field(default_factory=list)
    evidence_bboxes: List[EvidenceBbox] = Field(default_factory=list)
    confidence: Confidence
    compliance_indicator: ComplianceIndicator
    compliance_reasoning: str  # 1-3 sentences
    ta_shetach_takanon: Optional[str] = None  # "1"-"10", "20", or None for plan-level
    ta_shetach_submission: Optional[str] = None  # verbatim label "ת.ש 52" etc.


class PlotMapping(BaseModel):
    submission_label: str  # verbatim: "ת.ש 52", "מתחם 1", etc.
    takanon_plot: Optional[str] = None  # "1"-"10", "20", or None
    confidence: Confidence
    evidence_pages: List[int] = Field(default_factory=list)
    rationale: str


class PlotReconciliation(BaseModel):
    method: PlotMappingMethod = PlotMappingMethod.auto
    mappings: List[PlotMapping] = Field(default_factory=list)
    unreconciled_submission_labels: List[str] = Field(default_factory=list)
    unreconciled_takanon_plots: List[str] = Field(default_factory=list)


class VisionFindingsResponse(BaseModel):
    """Top-level schema Gemini emits.

    Wrapping in a parent object satisfies Gemini's structured-output
    requirement (object root, not bare list).
    """

    plot_reconciliation: PlotReconciliation
    findings: List[Finding] = Field(default_factory=list)


class VisionFindings(BaseModel):
    """Full on-disk document, including caller-set metadata."""

    project_id: str
    submission_id: str
    extractor_version: str = "m2-v4"
    extracted_at: str
    model: str = "gemini-2.5-pro"
    input_refs: Dict[str, str] = Field(default_factory=dict)
    plot_reconciliation: PlotReconciliation
    findings: List[Finding] = Field(default_factory=list)
    validation_summary: Dict[str, Any] = Field(default_factory=dict)
