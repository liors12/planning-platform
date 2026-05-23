# Engine output JSON — contract for Module B

Authoritative shape of the JSON returned by `GET /submissions/{id}/findings`
(which is the verbatim contents of `audit_results.json` produced by
`scripts/run_audit.py` and downstream of `compliance_engine.audit.run_full_audit`).

**Stable since v8j.** Phase 2b's Module B (the findings UI) must target this
shape. Any change to the contract requires:

1. A migration plan that includes Module B's renderer.
2. A pinned snapshot of the new shape in this doc.
3. A version bump in the top-level `audit_run_id` semantics (TBD when the
   first breaking change happens).

---

## Top-level shape

```jsonc
{
  "format":            [FormatRule, ...],           // per-rule format compliance findings
  "content":           [ContentRule, ...],          // per-תא-שטח statutory content findings
  "disciplines":       [DisciplineRule, ...],       // multi-discipline (3.1-3.10) findings
  "extraction_cache":  ExtractedSubmissionData,     // raw values the extractor pulled from the PDF
  "extracts_overlay":  { ... },                     // optional manual/Cowork overlay (may be {})
  "feedback_entries":  [FeedbackEntry, ...],        // merged discipline-manager overrides (may be [])
  "audit_run_id":      "407-1048248/v24.3"          // {project_key}/v{version}, or null in standalone runs
}
```

## Per-rule shapes

All three rule arrays (`format`, `content`, `disciplines`) share a common
field set:

```jsonc
{
  "rule_code":            "CONTENT_APARTMENT_MIX_SMALL",   // stable ID; rule renderers key off this
  "rule_name_he":         "אחוז דירות קטנות",
  "verdict":              "pass" | "pass_with_note" | "fail" | "fail_borderline"
                        | "not_submitted" | "requires_review" | "unevaluable"
                        | "not_applicable",
  "failure_mode":         "NONE" | "DOCUMENT_NOT_PROVIDED" | "POLICY_VIOLATION"
                        | "UNDERRUN" | "ENGINE_ERROR" | "AMBIGUOUS_INPUT",
  "confidence":           "HIGH" | "MEDIUM" | "LOW",
  "evidence":             { ... },     // shape varies by rule + verdict; see below
  "notes_he":             "...",       // human-facing explanation (Hebrew, may contain Markdown bits)
  "remediation_he":       "...",       // what the architect should do
  "required_artifact_he": "...",       // what document/section satisfies this rule
  "booklet_section":      "ב.2",       // citation to the requirements doc (may be empty)
  "booklet_pages":        [12, 14],    // page references in the requirements doc (may be empty)
  "severity":             "critical" | "major" | "minor" | "info"
}
```

### Content-rule extras

```jsonc
{
  ...common fields...,
  "ta_shetach_id":  "plot_1"   // optional; absent for plan-wide rules
}
```

### Discipline-rule extras (when sourced from Cowork JSON)

```jsonc
{
  ...common fields...,
  "discipline":         "shafa" | "gardens" | "infra" | "fire" | "drainage"
                      | "roofs" | "arch" | "balcony" | "laundry" | "env",
  "evidence_visual":    "תיאור ויזואלי של מה שצולם בעמוד...",
  "evidence_pages":     [25, 35, 40, 44],
  "compliance_note":    "תואם — תנועת רכבי האשפה מחוץ למגרש",
  // evidence.source == "cowork_discipline_findings_v24.3" when these are present
}
```

## rule_code invariants

`rule_code` is the **stable rule identifier** in `content_rules.json` /
`format_rules.json` and the join key used by downstream consumers
(`report_generator.py`, the frontend findings renderer, the regression
baseline). Three properties must hold:

1. **Uniqueness within a rules-config file.** Each entry in
   `content_rules.json` `.rules[]` has a distinct `rule_code`.
   Enforced by:
   ```bash
   jq '[.rules[].rule_code] | group_by(.) | map(select(length>1))' \
     content_rules.json
   ```
   must return `[]`.

2. **NOT unique within an engine output array.** Rules with
   `"scope": "per_ta_shetach"` (e.g. `CONTENT_UNIT_COUNT`,
   `CONTENT_BUILDING_AREA_MAIN`, …) emit ONE result per plot. All
   results share the same `rule_code` but carry distinct
   `ta_shetach_id` values (`"plot_1"`, `"plot_2"`, …). For a project
   with 11 plots, the `content` array can contain 11 entries that all
   say `"rule_code": "CONTENT_UNIT_COUNT"` — that is correct and not a
   bug.
   Downstream code that needs a single row identity per emitted
   result MUST compose `rule_code` with `ta_shetach_id` (with a falsy
   fallback for non-per-plot rules). The frontend does this in
   `app/frontend/src/components/FindingsView.tsx` with the React key
   ``` `${r.rule_code}::${r.ta_shetach_id ?? idx}` ```.

3. **Reserved separator: `::` must not appear inside `rule_code`.**
   This is the invariant the frontend's composite React key relies on.
   Currently every rule_code matches `^[A-Z][A-Z0-9_]*$`, so the
   invariant holds trivially. If a future rule introduces a non-
   matching character, audit every composite-key usage (start with
   `grep -rn '\${.*rule_code.*}::' app/frontend/`) and pick a new
   separator that's still impossible inside `rule_code`.

## Verdict semantics for the UI

The Hebrew display label that Module B should show, and the badge color group:

| `verdict` | Hebrew | Badge |
|---|---|---|
| `pass` | תקין | green |
| `pass_with_note` | תקין בהערה | green-with-note |
| `fail` | נדרש תיקון | red |
| `fail_borderline` | נדרש תיקון | red (alt shade) |
| `not_submitted` | לא הוגש | red |
| `requires_review` | דורש בירור | amber |
| `unevaluable` | לא ניתן לבדיקה | gray |
| `not_applicable` | לא רלוונטי | gray (hidden by default) |

These are codified in `compliance_engine/report_generator.py`'s
`VERDICT_TO_VCLASS_AND_LABEL` mapping. Module B should reuse the same mapping
function/table — recommend extracting it to a shared module accessible from
both engine and sidecar in Phase 2b.

## What Module B does NOT need to handle

- **PDF page navigation:** the embedded pdf.js viewer (a separate Phase 2b
  deliverable) handles `evidence_pages` clicks. Module B just needs to emit
  the page numbers as clickable links.
- **Manager overrides:** the `feedback_entries` array carries the result of
  the discipline-manager overlay AFTER the engine merges them. Module B
  displays the post-merge state; the override UI itself is Phase 3 (Module D).
- **Provenance audit trail:** the `extraction_cache` field carries the raw
  extraction (what the LLM/vision pass pulled from the PDF). A small
  "show provenance" disclosure in Module B is sufficient — full audit
  visualization is later.

## Empty-fields convention

- Lists default to `[]`, never null.
- Dict fields default to `{}`.
- Optional string fields are `""` (empty string), not `null` — keeps the
  renderer's `_esc(value)` calls safe.

## Example fragment (v24.3 audit_results.json, abbreviated)

```jsonc
{
  "format": [
    {
      "rule_code": "FORMAT_FONT_EMBEDDING",
      "rule_name_he": "הטמעת גופנים",
      "verdict": "pass",
      "failure_mode": "NONE",
      "confidence": "HIGH",
      "evidence": { "embedded_fonts": ["Heebo", "Arial"], "..." },
      "severity": "minor",
      ...
    }
  ],
  "content": [
    {
      "rule_code": "CONTENT_APARTMENT_MIX_SMALL",
      "rule_name_he": "אחוז דירות קטנות",
      "ta_shetach_id": null,
      "verdict": "requires_review",
      "failure_mode": "AMBIGUOUS_INPUT",
      "notes_he": "גבול תחתון: לפי הקריאה המחמירה של התב\"ע (≤75 מ\"ר), מאומתות לכל הפחות 17 דירות קטנות = 2.43%...",
      "evidence": { "strict_count_lower_bound": 17, "total_units": 700,
                    "ambiguous_plots": ["1", "3"], "architect_count": 147,
                    "architect_pct": 21.0 },
      "severity": "critical",
      ...
    }
  ],
  "disciplines": [
    {
      "rule_code": "DISC_SHAFA_NO_TRUCK_ENTRY",
      "rule_name_he": "ללא כניסת משאיות אשפה לתחום המגרש",
      "discipline": "shafa",
      "verdict": "pass",
      "evidence_visual": "החצים הירוקים המקווקווים (תנועת רכבי אשפה לפי הלגנדה)...",
      "evidence_pages": [25, 35, 40, 44],
      "compliance_note": "תואם — תנועת רכבי האשפה מחוץ למגרש",
      "evidence": { "source": "cowork_discipline_findings_v24.3", ... },
      ...
    }
  ],
  "extraction_cache": { /* ExtractedSubmissionData dataclass dict */ },
  "extracts_overlay": { /* contents of extracts.json next to the PDF, if present */ },
  "feedback_entries": [],
  "audit_run_id": "407-1048248/v24.3"
}
```

## Verdict counts for the v24.3 pilot (regression baseline)

The smoke test that verifies end-to-end engine integration through the
sidecar (Phase 2a) compares its findings JSON against these v8j numbers:

```
format:       11 fail + 9 pass + 5 pass_with_note + 8 requires_review + 1 unevaluable
content:      15 pass + 27 not_submitted + 11 requires_review + 26 not_applicable  (79 total)
disciplines:   9 pass + 8 fail + 16 requires_review                                 (33 total)
```

Any drift from these numbers — when running the same v24.3 PDF + extracts.json
+ discipline_findings.json — is a regression to investigate before Module B
work continues.
