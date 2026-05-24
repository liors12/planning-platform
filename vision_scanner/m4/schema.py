"""Pydantic models for M4 engine adapter output."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    pass_ = "pass"
    fail = "fail"
    not_submitted = "not_submitted"
    not_applicable = "not_applicable"
    requires_review = "requires_review"
    pass_with_note = "pass_with_note"
    unevaluable = "unevaluable"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class OverrideSource(str, Enum):
    m2_finding = "m2_finding"
    m3_critic_disagreement = "m3_critic_disagreement"
    hedged_reasoning_escalation = "hedged_reasoning_escalation"


class CriticVerdict(str, Enum):
    agree = "agree"
    disagree = "disagree"
    cannot_determine = "cannot_determine"


ALLOWED_VERDICTS = {v.value for v in Verdict}
ALLOWED_CONFIDENCES = {c.value for c in Confidence}


class M4Finding(BaseModel):
    # Engine-original fields (preserved verbatim on passthrough)
    rule_code: str
    rule_name_he: str
    ta_shetach_id: Optional[str] = None
    verdict: Verdict
    confidence: Confidence
    failure_mode: str
    evidence: Dict[str, Any] = Field(default_factory=dict)
    notes_he: str = ""
    remediation_he: str = ""

    # M4 additions
    m4_override_applied: bool = False
    m4_override_source: Optional[OverrideSource] = None
    m4_m2_clause_ids: List[str] = Field(default_factory=list)
    m4_m3_critic_verdict: Optional[CriticVerdict] = None
    m4_evidence_pages: List[int] = Field(default_factory=list)
    m4_evidence_bboxes: List[Dict[str, Any]] = Field(default_factory=list)


class M4Summary(BaseModel):
    total_engine_findings: int
    overridden_count: int
    by_override_source: Dict[str, int] = Field(default_factory=dict)
    verdict_distribution_before: Dict[str, int] = Field(default_factory=dict)
    verdict_distribution_after: Dict[str, int] = Field(default_factory=dict)
    new_fail_verdicts: List[str] = Field(default_factory=list)
    critic_disagreements_applied: List[str] = Field(default_factory=list)


class M4AuditResults(BaseModel):
    audit_run_id: Optional[str] = None
    m4_version: str = "m4-v1"
    m4_input_refs: Dict[str, str] = Field(default_factory=dict)
    content: List[M4Finding] = Field(default_factory=list)
    disciplines: List[M4Finding] = Field(default_factory=list)
    format: List[M4Finding] = Field(default_factory=list)
    extraction_cache: Dict[str, Any] = Field(default_factory=dict)
    extracts_overlay: Dict[str, Any] = Field(default_factory=dict)
    feedback_entries: List[Any] = Field(default_factory=list)
    m4_summary: M4Summary
