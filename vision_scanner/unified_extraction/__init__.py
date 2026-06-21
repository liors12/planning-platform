"""Unified per-clause extraction (M2).

For every normative clause in the takanon (M0), extract corresponding
evidence from the architect submission (v24.3) into a structured
vision_findings.json. Single Gemini 2.5 Pro call using 1M context with
all 63 page images + clause texts + M1 manifests.
"""
