"""Compliance engine — shared types.

Rule taxonomy is the same 5-type set documented in CONTEXT.md and SKILL.md:
numeric, geometric, document_presence, procedural, qualitative. The Rule
dataclass below is the runtime shape that the rule resolver returns; rule
storage in the SQLite `rules` table uses string columns (rule_type, raw_json)
which are converted to this shape on the way out.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RuleType(str, Enum):
    """The 5 rule types from the v2 taxonomy. Stored on `rules.rule_type`
    as a string; this enum is the canonical Python form."""

    NUMERIC = "numeric"
    GEOMETRIC = "geometric"
    DOCUMENT_PRESENCE = "document_presence"
    PROCEDURAL = "procedural"
    QUALITATIVE = "qualitative"

    @classmethod
    def from_str(cls, s: str) -> "RuleType":
        try:
            return cls(s)
        except ValueError as e:
            raise ValueError(
                f"unknown rule_type {s!r}; expected one of "
                f"{[t.value for t in cls]}"
            ) from e


@dataclass
class Rule:
    """A single compliance rule resolved for one parcel.

    Returned by `resolve_rules_for_parcel`. Carries everything an evaluator
    needs to run the check, plus the override audit trail.

    Attributes:
        rule_id: Stable rule identifier (the `rule_code` column from the
            `rules` table — e.g. "UNITS_MAX_PLOT_1"). Stable across engine
            versions and submissions; safe to use as a join key.
        rule_type: One of the 5 taxonomy values. Drives which evaluator
            runs (numeric/geometric/document_presence/procedural/qualitative).
        source_takanon_id: The plan_number string of the statutory plan this
            rule comes from (e.g. "407-0977595"). Carried into evidence
            bundles so the future חוות דעת cites the correct authority.
        parameters: Rule-specific config. After overrides are applied, this
            holds the effective parameters the evaluator should use.
        is_overridden: True if a `project_rule_exceptions` row matched this
            (project_id, rule_id) and modified the parameters or notes.
        override_reason: When `is_overridden=True`, the `notes` field from
            the matching exception row; None otherwise.
        original_parameters: When `is_overridden=True`, the parameters as
            they came from the rules table (pre-override). Preserved for
            audit. None when there was no override.
        plot: Per-plot scope tag from the rule definition (e.g. "plot_1",
            "all"); useful when one rule_code has plot-specific variants.
    """

    rule_id: str
    rule_type: RuleType
    source_takanon_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    is_overridden: bool = False
    override_reason: str | None = None
    original_parameters: dict[str, Any] | None = None
    plot: str | None = None

    def with_override(
        self,
        new_parameters: dict[str, Any],
        reason: str,
    ) -> "Rule":
        """Return a copy of this Rule with override applied. Preserves
        the pre-override parameters in `original_parameters` for audit."""
        return Rule(
            rule_id=self.rule_id,
            rule_type=self.rule_type,
            source_takanon_id=self.source_takanon_id,
            parameters=copy.deepcopy(new_parameters),
            is_overridden=True,
            override_reason=reason,
            original_parameters=(
                self.original_parameters
                if self.original_parameters is not None
                else copy.deepcopy(self.parameters)
            ),
            plot=self.plot,
        )


class FailureMode(str, Enum):
    """Cause classification for UNEVALUABLE verdicts.

    The ``verdict`` axis answers *what* happened (pass / fail / unevaluable
    / …); ``failure_mode`` is an orthogonal axis that answers *why* — and
    only carries signal when ``verdict == UNEVALUABLE``. For every other
    verdict the field stays ``NONE``.

    This split exists because, in production, an engineer looking at 30
    UNEVALUABLE rows needs to tell three very different stories apart:

      ENGINE_ERROR        the evaluator raised an exception. The system
                          (not the architect) is the problem; this is a
                          ticket for the engine team.
      MISSING_DATA        the rule asked for a field the extractor did
                          not produce. The architect's submission is
                          incomplete OR the extractor missed something —
                          either way it's a real submission gap.
      AMBIGUOUS_RULE      the rule's own definition is unclear or
                          unparseable; the rule itself needs editing
                          before it can be evaluated.
      EXTRACTION_FAILURE  a value WAS produced but the extractor flagged
                          it as unreliable; the engineer should re-check
                          the source rather than trust the verdict.
      NONE                default. The verdict is not UNEVALUABLE so the
                          field is meaningless and explicitly set to NONE
                          to make that explicit at the type level.

    Stored on ``violations.failure_mode`` as a string with a CHECK
    constraint enumerating these values.
    """

    ENGINE_ERROR = "engine_error"
    MISSING_DATA = "missing_data"
    AMBIGUOUS_RULE = "ambiguous_rule"
    EXTRACTION_FAILURE = "extraction_failure"
    NONE = "none"

    @classmethod
    def from_str(cls, s: str) -> "FailureMode":
        try:
            return cls(s)
        except ValueError as e:
            raise ValueError(
                f"unknown failure_mode {s!r}; expected one of "
                f"{[m.value for m in cls]}"
            ) from e


class Confidence(str, Enum):
    """How reliable is this verdict? Orthogonal to ``verdict`` itself.

    A pass with LOW confidence is genuinely different from a pass with
    HIGH confidence — the engineer must know whether to trust it before
    signing. Three levels are intentional: more granularity (e.g. a 0–1
    float) buys nothing here and is harder to reason about during review.

    Values:
      HIGH    — deterministic check on clean data, or explicit rule
                match with no interpretation. All current evaluators
                (numeric/geometric stub/document_presence/procedural)
                return HIGH because they're deterministic by
                construction.
      MEDIUM  — deterministic but with assumptions, or a model-
                recommended verdict with strong, citable evidence.
                Reserved for the future Claude integration when it
                returns structured reasoning that the engineer can
                trace.
      LOW     — qualitative model judgment without explicit rule
                grounding, or an extracted value of uncertain quality.
                The qualitative evaluator emits LOW today by default,
                upgrading to MEDIUM only when the future Claude path
                provides explicit reasoning.

    Stored on ``violations.confidence`` as a string with a CHECK
    constraint enumerating these values.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @classmethod
    def from_str(cls, s: str) -> "Confidence":
        try:
            return cls(s)
        except ValueError as e:
            raise ValueError(
                f"unknown confidence {s!r}; expected one of "
                f"{[c.value for c in cls]}"
            ) from e


class Verdict(str, Enum):
    """The 7 verdict states the evaluator may return per (parcel, rule).

    Canonical for both the in-memory dataclass and the persisted
    `violations.verdict` column. The persistence-layer DDL has a CHECK
    constraint that lists exactly these strings — adding a new member
    here without updating the CHECK constraint will cause INSERTs to
    fail. See CONTEXT.md → "Violation Statuses" for the rationale and
    the override/confidence separation.
    """

    PASS = "pass"
    PASS_WITH_NOTE = "pass_with_note"
    FAIL = "fail"
    FAIL_BORDERLINE = "fail_borderline"
    UNEVALUABLE = "unevaluable"
    NOT_APPLICABLE = "not_applicable"
    REQUIRES_REVIEW = "requires_review"

    @classmethod
    def from_str(cls, s: str) -> "Verdict":
        try:
            return cls(s)
        except ValueError as e:
            raise ValueError(
                f"unknown verdict {s!r}; expected one of "
                f"{[v.value for v in cls]}"
            ) from e


@dataclass
class Violation:
    """One evaluation result per (parcel, rule).

    The name "Violation" is historical — these rows live in the
    `violations` table — but the dataclass represents *every* outcome,
    including passes. A Violation with `verdict=Verdict.PASS` means
    "this rule was checked against this parcel and the parcel met it."

    Attributes:
        violation_id: Auto-generated UUID. Primary key in the persisted
            row. Created at construction time so callers can refer to
            it before persistence.
        engine_run_id: Foreign key to the engine_runs table. Set by the
            caller (the orchestration layer that triggered evaluation).
        parcel_id: The תא שטח identifier this verdict applies to.
        rule_id: The rule_code from the resolved Rule.
        rule_type: Which evaluator produced this verdict (numeric /
            geometric / document_presence / procedural / qualitative).
        verdict: One of the 7 Verdict states.
        expected_value: What the rule required (threshold, document
            name, expected scale, etc.). Type varies by rule type.
        actual_value: What the extractor produced. None when the field
            was missing from extracted_data (typically yields
            UNEVALUABLE).
        evidence: Per-rule evidence bundle — bbox, page numbers, source
            file, excerpts. Free-form dict; the unified evidence bundle
            schema documented in CONTEXT.md is the target shape.
        notes: Optional free-form explanation. Required for UNEVALUABLE
            (extractor failure reason) and REQUIRES_REVIEW (the question
            the human reviewer must answer); optional otherwise.
        is_override_applied: Mirror of the resolved Rule's `is_overridden`
            flag — propagated so the persistence layer can flag the row
            without re-querying the rule.
        failure_mode: The cause classification when verdict==UNEVALUABLE.
            Defaults to FailureMode.NONE for every other verdict; should
            be set to one of ENGINE_ERROR / MISSING_DATA / AMBIGUOUS_RULE
            / EXTRACTION_FAILURE when verdict is UNEVALUABLE. The
            evaluator dispatcher's try/except wrapper sets ENGINE_ERROR
            on uncaught exceptions; individual evaluators set the rest.
        error_fingerprint: Short stable hash used to cluster violations
            that share the same root cause (e.g. all 30 rows that hit
            the same KeyError in the numeric evaluator). The PDF
            generator uses this to collapse a swarm of identical errors
            into a single incident at the run level. None when there is
            nothing to cluster on (e.g. successful verdicts, or
            uniquely-noted unevaluable rows). The
            ``compute_error_fingerprint`` helper produces a 16-char
            sha256 prefix from a stable string.
        confidence: How reliable is this verdict? Orthogonal to verdict
            and failure_mode. Defaults to HIGH because every current
            evaluator is deterministic. The qualitative evaluator
            overrides to LOW; future Claude integration will set MEDIUM
            when its structured reasoning is strong enough. The PDF
            generator surfaces a small badge next to the verdict pill
            when this is not HIGH.
    """

    engine_run_id: str
    parcel_id: str
    rule_id: str
    rule_type: RuleType
    verdict: Verdict
    expected_value: Any = None
    actual_value: Any = None
    evidence: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None
    is_override_applied: bool = False
    failure_mode: FailureMode = FailureMode.NONE
    error_fingerprint: str | None = None
    confidence: Confidence = Confidence.HIGH
    violation_id: str = field(default_factory=lambda: str(__import__("uuid").uuid4()))


def compute_error_fingerprint(seed: str) -> str:
    """Stable 16-char sha256 prefix used to cluster identical failures.

    Callers pass any deterministic string (e.g. ``"engine_error:KeyError:'x'"``
    or ``"numeric:missing:height_m"``); rows that produce the same seed
    will share a fingerprint and the PDF generator will fold them into a
    single incident row. 16 hex chars (64 bits) is plenty for collision
    avoidance across a single engine run; using more would just add visual
    noise in the document without buying us anything.
    """
    import hashlib
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
