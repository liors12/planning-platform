"""Independent Flash critic over M2 vision findings (M3).

Runs Gemini 2.5 Flash per critical M2 finding with a constrained context
(clause text + claimed value + cited page images only, NO M2 reasoning).
Emits agree/disagree/cannot_determine verdicts that feed M4's compliance
reasoning by surfacing extractions that need extra human review.
"""
