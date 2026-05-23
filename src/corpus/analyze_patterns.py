#!/usr/bin/env python3
"""
Corpus pattern analyzer.

Reads findings JSON files in corpus/extracted/ and surfaces:
- Verdict distribution
- Reason class distribution (observed empirically)
- Rule topic distribution
- Comparison: observed reason classes vs. the proposed 8-class enum
- Cases where observed class doesn't fit any proposed class
"""

from pathlib import Path
import json
from collections import Counter, defaultdict

# The 8-class enum proposed before we had real data
PROPOSED_REASON_CLASSES = {
    "source_missing",
    "source_conflict",
    "parser_low_confidence",
    "rule_not_modeled",
    "ambiguous_applicability",
    "manual_override",
    "geometry_tolerance",
    "human_judgment_required",
}

# Mapping from observed → proposed (where one exists)
OBSERVED_TO_PROPOSED = {
    "source_missing_or_incomplete": "source_missing",
    "qualitative_judgment": "human_judgment_required",
    # The two below have no clean mapping — they're new categories
    "numeric_rule_violation": None,  # not a "reason for uncertainty" — it's a hard fail
    "non_conformance_with_plan": None,  # also a hard fail, against a higher plan
}


def load_all_findings(base_path: Path) -> list[dict]:
    """Load every *-findings.json file in `base_path` and merge their cases.

    Skip files whose top-level `extracted_by` starts with "manual-" so a
    gold-standard archive sitting in the same directory does not double-count
    cases that also have an automated extraction (with "-auto-findings.json"
    in the filename).
    """
    cases = []
    for p in sorted(base_path.glob("*-findings.json")):
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if str(data.get("extracted_by", "")).startswith("manual-"):
            continue
        for case in data.get("cases", []):
            case["_protocol"] = data["protocol_id"]
            case["_municipality"] = data["municipality"]
            case["_source_file"] = p.name
            cases.append(case)
    return cases


def analyze(cases: list[dict]) -> dict:
    verdict_counts = Counter()
    reason_class_counts = Counter()
    rule_topic_counts = Counter()
    needs_classification_count = 0
    subtype_counts: Counter[str] = Counter()
    total_findings_with_text = 0
    findings_by_class: dict[str, list[dict]] = defaultdict(list)

    for case in cases:
        verdict_counts[case.get("verdict", "unknown")] += 1
        for finding in case.get("findings", []):
            total_findings_with_text += 1
            rc = finding.get("reason_class")
            if rc:
                reason_class_counts[rc] += 1
                findings_by_class[rc].append(
                    {
                        "case_id": case["case_id"],
                        "address": case["address"],
                        "text": finding.get("text", ""),
                        "rule_topic": finding.get("rule_topic"),
                    }
                )
            if finding.get("needs_classification"):
                needs_classification_count += 1
            sub = finding.get("finding_subtype")
            if sub:
                subtype_counts[sub] += 1
            rt = finding.get("rule_topic")
            if rt:
                rule_topic_counts[rt] += 1

    # Which observed classes don't map to a proposed class?
    proposal_gaps = []
    for observed_class in reason_class_counts:
        mapped = OBSERVED_TO_PROPOSED.get(observed_class, "UNMAPPED")
        if mapped is None or mapped == "UNMAPPED":
            proposal_gaps.append(
                {
                    "observed_class": observed_class,
                    "proposed_mapping": mapped,
                    "count": reason_class_counts[observed_class],
                    "samples": findings_by_class[observed_class][:3],
                }
            )

    # Which proposed classes have no observed examples yet?
    observed_mapped_set = {
        OBSERVED_TO_PROPOSED[c]
        for c in reason_class_counts
        if OBSERVED_TO_PROPOSED.get(c) is not None
    }
    unobserved_proposed = PROPOSED_REASON_CLASSES - observed_mapped_set

    return {
        "summary": {
            "cases_analyzed": len(cases),
            "total_findings": total_findings_with_text,
            "findings_with_reason_class": sum(reason_class_counts.values()),
            "needs_classification": needs_classification_count,
        },
        "verdict_distribution": dict(verdict_counts.most_common()),
        "observed_reason_classes": dict(reason_class_counts.most_common()),
        "finding_subtypes": dict(subtype_counts.most_common()),
        "rule_topics": dict(rule_topic_counts.most_common()),
        "proposal_gaps": proposal_gaps,
        "proposed_classes_with_no_evidence": sorted(unobserved_proposed),
    }


def render_report(analysis: dict) -> str:
    lines = []
    a = analysis
    lines.append("# Corpus pattern analysis — first run\n")
    lines.append(f"Cases analyzed: **{a['summary']['cases_analyzed']}**  ")
    lines.append(f"Total findings: **{a['summary']['total_findings']}**  ")
    lines.append(f"Findings with reason_class: **{a['summary']['findings_with_reason_class']}**  ")
    lines.append(f"Findings flagged needs_classification: **{a['summary']['needs_classification']}**\n")
    if a.get("finding_subtypes"):
        lines.append("## Finding subtypes\n")
        for k, v in a["finding_subtypes"].items():
            lines.append(f"- `{k}`: {v}")
        lines.append("")

    lines.append("## Verdict distribution\n")
    for k, v in a["verdict_distribution"].items():
        lines.append(f"- `{k}`: {v}")
    lines.append("")

    lines.append("## Observed reason classes (empirical)\n")
    for k, v in a["observed_reason_classes"].items():
        lines.append(f"- `{k}`: {v}")
    lines.append("")

    lines.append("## Rule topics (empirical)\n")
    for k, v in a["rule_topics"].items():
        lines.append(f"- `{k}`: {v}")
    lines.append("")

    lines.append("## Proposal gaps — observed classes that don't fit the 8-class enum\n")
    if not a["proposal_gaps"]:
        lines.append("_(none)_\n")
    else:
        for gap in a["proposal_gaps"]:
            lines.append(
                f"### `{gap['observed_class']}` "
                f"(observed {gap['count']}× — proposed mapping: `{gap['proposed_mapping']}`)\n"
            )
            for s in gap["samples"]:
                lines.append(f"- *{s['address']}* — {s['text']}")
            lines.append("")

    lines.append("## Proposed classes with no evidence in corpus yet\n")
    if not a["proposed_classes_with_no_evidence"]:
        lines.append("_(all proposed classes have observed examples)_\n")
    else:
        for c in a["proposed_classes_with_no_evidence"]:
            lines.append(f"- `{c}` — proposed but not observed (yet)")
        lines.append(
            "\n_Note: absence here may mean these classes are real but rare, "
            "or that the proposed taxonomy doesn't match how engineers actually reason._\n"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    # Resolve paths relative to the project root (parent of `src/`).
    repo_root = Path(__file__).resolve().parents[2]
    base = repo_root / "data" / "corpus" / "extracted"
    cases = load_all_findings(base)
    analysis = analyze(cases)
    report = render_report(analysis)
    out = repo_root / "data" / "corpus" / "index" / "pattern-analysis.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n[saved → {out}]")
