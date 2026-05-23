"""Hebrew translations for the 7-state Verdict enum.

Used by the compliance-opinion PDF generator to render verdicts in prose
that an Israeli planning engineer would actually write. These strings are
**starting drafts** — Ellen (NZC authority director) will refine the
wording. Keeping all translations in one module so a single edit propagates
through the whole document.

Conventions:
  - The "תואם / אינו תואם" axis mirrors the standard Hebrew planning-review
    register; the borderline modifier reads as a qualifier on the failure
    rather than a separate verdict in prose.
  - "מצריך בחינת מהנדס" calls out the human-loop step explicitly — the
    engineer reviewing the draft sees exactly which rows demand their
    judgment before they sign.
  - "לא ניתן לבדיקה" is preferred over a literal "לא ניתן להעריך" because
    the planning context is one of *checking against rules*, not abstract
    evaluation.
"""

from __future__ import annotations

from compliance.types import Confidence, FailureMode, Verdict


VERDICT_HEBREW: dict[Verdict, str] = {
    Verdict.PASS:            "תואם",
    Verdict.PASS_WITH_NOTE:  "תואם — לידיעה",
    Verdict.FAIL:            "אינו תואם",
    Verdict.FAIL_BORDERLINE: "אינו תואם — בסף הסטייה המקובלת",
    Verdict.UNEVALUABLE:     "לא ניתן לבדיקה",
    Verdict.NOT_APPLICABLE:  "לא רלוונטי",
    Verdict.REQUIRES_REVIEW: "מצריך בחינת מהנדס",
}


VERDICT_CSS_CLASS: dict[Verdict, str] = {
    Verdict.PASS:            "v-pass",
    Verdict.PASS_WITH_NOTE:  "v-pass-note",
    Verdict.FAIL:            "v-fail",
    Verdict.FAIL_BORDERLINE: "v-fail-borderline",
    Verdict.UNEVALUABLE:     "v-unevaluable",
    Verdict.NOT_APPLICABLE:  "v-not-applicable",
    Verdict.REQUIRES_REVIEW: "v-requires-review",
}


OVERRIDE_BADGE_HEBREW = "הוחלפה החלטה הנדסית"


# Hebrew labels for failure_mode. Shown inline next to the UNEVALUABLE
# pill in the findings table so the engineer immediately distinguishes
# "missing data in submission" from "internal engine error" — two very
# different escalation paths.
FAILURE_MODE_HEBREW: dict[FailureMode, str] = {
    FailureMode.ENGINE_ERROR:       "שגיאת מערכת",
    FailureMode.MISSING_DATA:       "מידע חסר בהגשה",
    FailureMode.AMBIGUOUS_RULE:     "כלל לא ברור — נדרשת הבהרה",
    FailureMode.EXTRACTION_FAILURE: "כשל בחילוץ הנתון",
    FailureMode.NONE:               "",
}


def translate(verdict: Verdict) -> str:
    return VERDICT_HEBREW[verdict]


def css_class(verdict: Verdict) -> str:
    return VERDICT_CSS_CLASS[verdict]


def failure_mode_label(failure_mode: FailureMode) -> str:
    return FAILURE_MODE_HEBREW[failure_mode]


# Hebrew labels for the confidence axis. Shown as a small badge next to
# the verdict pill ONLY when confidence is not HIGH — high-confidence
# rows display nothing (otherwise every row gets cluttered).
CONFIDENCE_HEBREW: dict[Confidence, str] = {
    Confidence.HIGH:   "ודאות גבוהה",
    Confidence.MEDIUM: "ודאות בינונית",
    Confidence.LOW:    "ודאות נמוכה",
}


CONFIDENCE_CSS_CLASS: dict[Confidence, str] = {
    Confidence.HIGH:   "conf-high",
    Confidence.MEDIUM: "conf-medium",
    Confidence.LOW:    "conf-low",
}


def confidence_label(confidence: Confidence) -> str:
    return CONFIDENCE_HEBREW[confidence]


def confidence_css_class(confidence: Confidence) -> str:
    return CONFIDENCE_CSS_CLASS[confidence]
