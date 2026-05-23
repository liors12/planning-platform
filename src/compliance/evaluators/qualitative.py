"""Qualitative rule evaluator.

Qualitative rules require human judgment — architectural character,
landscape quality, design integration, "appropriate to context". They
cannot be evaluated by pattern-matching against extracted_data.

For now this evaluator always returns REQUIRES_REVIEW with a structured
explanation built from the rule's `check_note` (or `description`) plus
the rule's source citation. The Phase 3+ task will swap this stub for
a Claude API call that takes the rule, the relevant evidence bundle,
and an excerpt from the תקנון, then surfaces the model's structured
opinion to the human reviewer.
"""
from __future__ import annotations

from ..types import Confidence, Rule, Verdict, Violation


def evaluate(
    rule: Rule,
    extracted_data: dict,
    parcel_id: str,
    engine_run_id: str,
) -> Violation:
    check_note = (
        rule.parameters.get("check_note")
        or rule.parameters.get("description")
        or "qualitative rule — see source quote"
    )
    source_quote = rule.parameters.get("source_quote")
    source_section = rule.parameters.get("section") or rule.parameters.get("source_section")

    notes_parts = [
        "qualitative rule — requires human judgment.",
        f"check: {check_note}",
    ]
    if source_quote:
        notes_parts.append(f"source: {source_quote}")
    if source_section:
        notes_parts.append(f"section: {source_section}")

    return Violation(
        engine_run_id=engine_run_id,
        parcel_id=parcel_id,
        rule_id=rule.rule_id,
        rule_type=rule.rule_type,
        verdict=Verdict.REQUIRES_REVIEW,
        expected_value=check_note,
        actual_value=None,
        evidence={
            "source_quote": source_quote,
            "source_section": source_section,
            "source_page": rule.parameters.get("source_page"),
        },
        notes="\n".join(notes_parts),
        is_override_applied=rule.is_overridden,
        # Qualitative judgments are LOW-confidence by default. The future
        # Claude integration may upgrade specific outputs to MEDIUM when
        # it can cite explicit reasoning anchored in the תקנון excerpt.
        confidence=Confidence.LOW,
    )
