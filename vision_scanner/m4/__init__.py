"""M4 engine adapter — post-engine override layer.

Reads engine's audit_results.json + M2's vision_findings.json + M3's
critic_findings.json, and emits an enriched audit_results.m4.json with
per-rule × plot overrides driven by M2 vision evidence and M3 critic
disagreement escalation.

Engine output stays byte-identical to baseline. The PDF generator (phase 2)
reads .m4.json if present, falls back to engine output otherwise.
"""
