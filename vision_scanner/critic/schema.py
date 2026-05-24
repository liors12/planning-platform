"""Pydantic models for M3 critic.

Mirrors docs/m3_critic_spec.md. Models are flat so the Gemini schema
converter from clause_inventory.extract can reuse the same cleaning pass.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CriticVerdict(str, Enum):
    agree = "agree"
    disagree = "disagree"
    cannot_determine = "cannot_determine"


class M2ComplianceIndicator(str, Enum):
    """Allowed M2 indicators for a finding sent through the critic.

    Base filter passes only compliant/non_compliant. The m3-v2 5.table exception
    also allows requires_review (M2 emits requires_review for table rows to
    defer threshold comparison to M4 — the row's NUMERIC VALUE is still worth
    critiquing).
    """

    compliant = "compliant"
    non_compliant = "non_compliant"
    requires_review = "requires_review"


class CriticComplianceIndicator(str, Enum):
    compliant = "compliant"
    non_compliant = "non_compliant"
    requires_review = "requires_review"


class DisagreementSeverity(str, Enum):
    minor = "minor"      # value differs by ≤5% (rounding / reading precision)
    major = "major"      # value differs by >5%, OR verdict wrong though value right
    critical = "critical"  # value not on page at all, OR verdict flips


ALLOWED_CRITIC_VERDICTS = {v.value for v in CriticVerdict}
ALLOWED_M2_INDICATORS = {v.value for v in M2ComplianceIndicator}
ALLOWED_CRITIC_INDICATORS = {v.value for v in CriticComplianceIndicator}
ALLOWED_SEVERITIES = {v.value for v in DisagreementSeverity}


class CriticResponse(BaseModel):
    """Per-finding Flash response shape (what the model emits)."""

    verdict: CriticVerdict
    extraction_value: Optional[str] = None
    compliance_indicator: Optional[CriticComplianceIndicator] = None
    reasoning: str
    disagreement_severity: Optional[DisagreementSeverity] = None


class CriticFinding(BaseModel):
    """On-disk per-finding record (response + M2 context for traceability)."""

    clause_id: str
    m2_extraction_value: str
    m2_compliance_indicator: M2ComplianceIndicator
    m2_source_pages: List[int] = Field(default_factory=list)
    critic_verdict: CriticVerdict
    critic_extraction_value: Optional[str] = None
    critic_compliance_indicator: Optional[CriticComplianceIndicator] = None
    critic_reasoning: str
    disagreement_severity: Optional[DisagreementSeverity] = None


class CriticSummary(BaseModel):
    critiqued_count: int
    agree_count: int
    disagree_count: int
    cannot_determine_count: int
    critical_disagreements: List[str] = Field(default_factory=list)
    agreement_rate_pct: float


class CriticFindings(BaseModel):
    """Full on-disk document."""

    project_id: str
    submission_id: str
    critic_version: str = "m3-v2"
    critic_model: str = "gemini-2.5-flash"
    extracted_at: str
    input_refs: Dict[str, str] = Field(default_factory=dict)
    critic_findings: List[CriticFinding] = Field(default_factory=list)
    summary: CriticSummary
