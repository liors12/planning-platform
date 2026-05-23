"""Compliance-opinion PDF generator.

Loads a completed engine run from SQLite, renders a Jinja2 template into a
Hebrew-RTL HTML document, then converts that HTML to PDF via headless
Chrome (same approach as `src/render_report_pdf.py` — macOS WeasyPrint
needs `brew install pango` which we sidestep by using the browser engine
that ships on every developer's machine).

Public surface:
  - generate_compliance_opinion(engine_run_id, db_conn, output_path) -> Path
  - render_html(engine_run_id, db_conn) -> str   (intermediate HTML, used
    by tests so we can assert on substrings without parsing PDF binaries)

Pipeline:
  1. Fetch the engine_runs row + project metadata + linked plans.
  2. Load all violations via load_violations_for_run().
  3. Group by parcel; build per-parcel summary counters.
  4. Build executive-summary verdict counts (all 7, zero-filled).
  5. Build the "requires_review" rollup (review + unevaluable verdicts).
  6. Render Jinja2 template with the data + injected CSS.
  7. (PDF path only) Run headless Chrome --print-to-pdf.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sqlite3
import sys
import tempfile
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from compliance.persistence import load_violations_for_run
from compliance.types import Confidence, FailureMode, RuleType, Verdict, Violation
from pdf.verdict_translations import (
    FAILURE_MODE_HEBREW,
    OVERRIDE_BADGE_HEBREW,
    VERDICT_HEBREW,
    confidence_css_class,
    confidence_label,
    css_class,
    failure_mode_label,
    translate,
)


_PDF_DIR = Path(__file__).resolve().parent
_TEMPLATE_DIR = _PDF_DIR / "templates"
_CSS_PATH = _PDF_DIR / "styles" / "compliance-opinion.css"


# Hebrew labels for the 5 rule types, used in the per-parcel findings table.
RULE_TYPE_HEBREW: dict[RuleType, str] = {
    RuleType.NUMERIC:           "כמותי",
    RuleType.GEOMETRIC:         "גיאומטרי",
    RuleType.DOCUMENT_PRESENCE: "נספח",
    RuleType.PROCEDURAL:        "פרוצדורלי",
    RuleType.QUALITATIVE:       "איכותני",
}


CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def generate_compliance_opinion(
    engine_run_id: str,
    db_conn: sqlite3.Connection,
    output_path: Path,
) -> Path:
    """Render the draft חוות דעת PDF for `engine_run_id` and write to disk.

    Returns the resolved output path. Raises if Chrome is not found or if
    the engine run row does not exist.
    """
    html = render_html(engine_run_id, db_conn)
    output_path = Path(output_path).resolve()
    _html_to_pdf(html, output_path)
    return output_path


def render_html(engine_run_id: str, db_conn: sqlite3.Connection) -> str:
    """Render the document to an HTML string. Useful for testing without
    invoking the PDF engine, and for debugging the layout in a browser."""
    run = _load_run_row(db_conn, engine_run_id)
    project = _load_project_context(db_conn, run["project_id"])
    violations = load_violations_for_run(engine_run_id, db_conn)
    rule_sources = _load_rule_source_map(db_conn, run["project_id"])

    cluster_fingerprints = _compute_cluster_fingerprints(violations)
    parcel_blocks = _build_parcel_blocks(violations, rule_sources,
                                         cluster_fingerprints)
    summary = _build_summary(violations, parcels_count=len(parcel_blocks),
                             plan_count=len(project["linked_statutory_plans"]))
    review_items = _build_review_items(violations, rule_sources)

    css = _CSS_PATH.read_text(encoding="utf-8")

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tmpl = env.get_template("compliance_opinion.html.j2")

    return tmpl.render(
        css=css,
        project=project,
        run={
            "started_at":   _format_dt(run["started_at"]),
            "engine_version":     run["engine_version"],
            "submission_version": run["submission_version"],
            "generated_at": _format_dt(datetime.utcnow().isoformat(sep=" ", timespec="seconds")),
        },
        summary=summary,
        parcels=parcel_blocks,
        review_items=review_items,
        override_badge_text=OVERRIDE_BADGE_HEBREW,
    )


# ──────────────────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────────────────

def _load_run_row(db_conn: sqlite3.Connection, engine_run_id: str) -> dict[str, Any]:
    cur = db_conn.execute(
        """SELECT id, project_id, engine_version, submission_version,
                  status, triggered_by, started_at, completed_at,
                  summary_stats_json
           FROM engine_runs WHERE id = ?""",
        (engine_run_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"engine_run not found: {engine_run_id}")
    keys = ["id", "project_id", "engine_version", "submission_version",
            "status", "triggered_by", "started_at", "completed_at",
            "summary_stats_json"]
    return dict(zip(keys, row))


def _load_project_context(db_conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    """Returns the small projection the template needs:
       design_plan_name, revision, linked_statutory_plans (list of plan_number strings)."""
    cur = db_conn.execute(
        "SELECT name, raw_json FROM projects WHERE id = ?", (project_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"project not found: {project_id}")
    name, raw_json = row
    revision = None
    linked: list[str] = []
    if raw_json:
        try:
            data = json.loads(raw_json)
            design = data.get("design_plan") or {}
            revision = design.get("revision")
            linked = [
                lp.get("plan_number") for lp in (data.get("linked_statutory_plans") or [])
                if lp.get("plan_number")
            ]
        except (json.JSONDecodeError, AttributeError):
            pass

    if not linked:
        # Fallback: each statutory plan is itself a `projects` row; the
        # takanon_version → project chain gives us the plan_number.
        cur = db_conn.execute(
            """SELECT p.plan_number
               FROM project_takanon_links ptl
               JOIN takanon_versions tv ON tv.id = ptl.takanon_id
               JOIN projects p ON p.id = tv.project_id
               WHERE ptl.project_id = ?
               ORDER BY ptl.coverage_type, p.plan_number""",
            (project_id,),
        )
        linked = [r[0] for r in cur if r[0]]

    return {
        "design_plan_name": name or "—",
        "revision": revision,
        "linked_statutory_plans": linked or ["—"],
    }


def _load_rule_source_map(db_conn: sqlite3.Connection, project_id: str) -> dict[str, str]:
    """Map rule_code → plan_number of the source statutory plan. Used to
    cite the right תב"ע next to each finding."""
    cur = db_conn.execute(
        """SELECT r.rule_code, p.plan_number
           FROM rules r
           JOIN takanon_versions tv ON tv.id = r.takanon_version_id
           JOIN projects p ON p.id = tv.project_id
           WHERE r.project_id = ?""",
        (project_id,),
    )
    return {code: plan for code, plan in cur if code}


# ──────────────────────────────────────────────────────────────────────
# View-model builders
# ──────────────────────────────────────────────────────────────────────

_FAILURE_VERDICTS = {Verdict.FAIL, Verdict.FAIL_BORDERLINE}
_REVIEW_VERDICTS = {Verdict.REQUIRES_REVIEW, Verdict.UNEVALUABLE}

# Cluster threshold: when ≥3 violations share the same error_fingerprint
# we collapse them into a single incident row inside the per-parcel table
# instead of repeating the same row N times. Below the threshold the rows
# render normally — there's no value in collapsing 2 of anything.
_CLUSTER_MIN_COUNT = 3


def _build_parcel_blocks(
    violations: list[Violation],
    rule_sources: dict[str, str],
    cluster_fingerprints: set[str],
) -> list[dict[str, Any]]:
    """Group violations by parcel_id (preserving first-seen order, which
    matches the (parcel_id, rule_id) ordering load_violations_for_run uses).
    Within each parcel, sort failures first → borderline → review →
    unevaluable → pass-with-note → pass → not_applicable, so the engineer
    sees the rows that need attention at the top.

    `cluster_fingerprints` is the set of error_fingerprint values that
    appear ≥_CLUSTER_MIN_COUNT times across the run. Rows whose
    fingerprint is in that set are folded into a single ``cluster``
    pseudo-row per (parcel, fingerprint), instead of repeating the same
    row N times.
    """
    grouped: "OrderedDict[str, list[Violation]]" = OrderedDict()
    for v in violations:
        grouped.setdefault(v.parcel_id, []).append(v)

    blocks: list[dict[str, Any]] = []
    for parcel_id, items in grouped.items():
        items_sorted = sorted(items, key=_violation_sort_key)
        failure_count = sum(1 for v in items_sorted if v.verdict in _FAILURE_VERDICTS)
        review_count = sum(1 for v in items_sorted if v.verdict in _REVIEW_VERDICTS)

        rendered_rows = _fold_cluster_rows(
            items_sorted, rule_sources, cluster_fingerprints)

        blocks.append({
            "parcel_id": parcel_id,
            "governing_takanon_id": _governing_for_parcel(items_sorted, rule_sources),
            "failure_count": failure_count,
            "review_count": review_count,
            "violations": rendered_rows,
        })
    return blocks


def _fold_cluster_rows(
    parcel_violations: list[Violation],
    rule_sources: dict[str, str],
    cluster_fingerprints: set[str],
) -> list[dict[str, Any]]:
    """Walk a parcel's sorted violations and emit either:
      - a normal violation view (most rows), or
      - a single 'cluster' pseudo-row when 2+ violations in this parcel
        share an error_fingerprint that hit the run-level cluster
        threshold. The cluster row carries an ``is_cluster=True`` flag
        and the count + sample of folded rule_ids so the template can
        render a collapsed banner instead of N identical rows.
    """
    # Bucket per-parcel violations by clusterable fingerprint.
    by_fp: "OrderedDict[str, list[Violation]]" = OrderedDict()
    standalone: list[Violation] = []
    for v in parcel_violations:
        fp = v.error_fingerprint
        if fp and fp in cluster_fingerprints:
            by_fp.setdefault(fp, []).append(v)
        else:
            standalone.append(v)

    out: list[dict[str, Any]] = []
    # Render cluster banners first (they're always UNEVALUABLE incidents
    # and the engineer should see them before the row-by-row content).
    for fp, group in by_fp.items():
        if len(group) >= 2:
            sample = group[0]
            out.append({
                "is_cluster": True,
                "cluster_count": len(group),
                "error_fingerprint": fp,
                "failure_mode": sample.failure_mode.value,
                "failure_mode_label": failure_mode_label(sample.failure_mode),
                "verdict_he": translate(sample.verdict),
                "css_class": css_class(sample.verdict),
                "rule_ids": [v.rule_id for v in group],
                "sample_notes": sample.notes,
            })
        else:
            # Single violation that happens to share a run-wide cluster
            # fingerprint — render normally rather than as a banner.
            out.append({"is_cluster": False, **_violation_to_view(group[0], rule_sources)})

    for v in standalone:
        out.append({"is_cluster": False, **_violation_to_view(v, rule_sources)})

    return out


_VERDICT_ORDER = {
    Verdict.FAIL:            0,
    Verdict.FAIL_BORDERLINE: 1,
    Verdict.REQUIRES_REVIEW: 2,
    Verdict.UNEVALUABLE:     3,
    Verdict.PASS_WITH_NOTE:  4,
    Verdict.PASS:            5,
    Verdict.NOT_APPLICABLE:  6,
}


def _violation_sort_key(v: Violation) -> tuple[int, str]:
    return (_VERDICT_ORDER.get(v.verdict, 99), v.rule_id)


def _governing_for_parcel(
    parcel_violations: list[Violation],
    rule_sources: dict[str, str],
) -> str | None:
    """Best-effort: take the first known source plan for the parcel's
    rules. Real governing-plan resolution lives elsewhere; this is just
    for the per-section header."""
    for v in parcel_violations:
        plan = rule_sources.get(v.rule_id)
        if plan:
            return plan
    return None


def _violation_to_view(v: Violation, rule_sources: dict[str, str]) -> dict[str, Any]:
    # failure_mode label is shown inline next to the UNEVALUABLE pill —
    # only meaningful for that verdict, suppressed elsewhere.
    fm_label = (
        failure_mode_label(v.failure_mode)
        if v.verdict == Verdict.UNEVALUABLE and v.failure_mode != FailureMode.NONE
        else ""
    )
    # Confidence badge: shown only when NOT HIGH so high-confidence rows
    # stay uncluttered (every row would otherwise carry the same badge
    # and the signal would disappear).
    conf_label = (
        confidence_label(v.confidence)
        if v.confidence != Confidence.HIGH else ""
    )
    return {
        "rule_id": v.rule_id,
        "rule_type_he": RULE_TYPE_HEBREW.get(v.rule_type, v.rule_type.value),
        "verdict_he": translate(v.verdict),
        "css_class": css_class(v.verdict),
        "source_takanon_id": rule_sources.get(v.rule_id),
        "expected_value": v.expected_value,
        "actual_value": v.actual_value,
        "expected_display": _format_value(v.expected_value),
        "actual_display": _format_value(v.actual_value),
        "notes": v.notes,
        "is_override_applied": v.is_override_applied,
        "failure_mode": v.failure_mode.value,
        "failure_mode_label": fm_label,
        "error_fingerprint": v.error_fingerprint,
        "confidence": v.confidence.value,
        "confidence_label": conf_label,
        "confidence_css_class": confidence_css_class(v.confidence),
        # Low-confidence override = the engineer's worklist flag. A
        # low-confidence verdict that an engineer waived earlier is a
        # particularly weak signal: we shouldn't trust the verdict AND
        # the waiver may have been made on shaky ground.
        "is_low_confidence_override": (
            v.is_override_applied and v.confidence == Confidence.LOW
        ),
    }


def _build_summary(
    violations: list[Violation],
    parcels_count: int,
    plan_count: int,
) -> dict[str, Any]:
    counts: Counter[Verdict] = Counter({v: 0 for v in Verdict})
    for v in violations:
        counts[v.verdict] += 1

    # Display order matches the engineer's mental priority:
    # failures first, then borderline failures, then human-loop verdicts,
    # then passes, then non-applicables.
    display_order = [
        Verdict.FAIL,
        Verdict.FAIL_BORDERLINE,
        Verdict.REQUIRES_REVIEW,
        Verdict.UNEVALUABLE,
        Verdict.PASS,
        Verdict.PASS_WITH_NOTE,
        Verdict.NOT_APPLICABLE,
    ]

    rows = [{
        "label":     VERDICT_HEBREW[v],
        "css_class": css_class(v),
        "count":     counts[v],
    } for v in display_order]

    failures_total = sum(counts[v] for v in _FAILURE_VERDICTS)
    review_total = sum(counts[v] for v in _REVIEW_VERDICTS)

    # System-health: count engine-error rows. Non-zero count drives the
    # warning banner in the template — a sign that the run cannot be
    # trusted as complete without engine-team review.
    engine_error_count = sum(
        1 for v in violations if v.failure_mode == FailureMode.ENGINE_ERROR)

    by_failure_mode = Counter({m.value: 0 for m in FailureMode})
    by_confidence = Counter({c.value: 0 for c in Confidence})
    for v in violations:
        by_failure_mode[v.failure_mode.value] += 1
        by_confidence[v.confidence.value] += 1

    low_confidence_count = by_confidence[Confidence.LOW.value]

    return {
        "total_violations": sum(counts.values()),
        "parcels_evaluated": parcels_count,
        "plan_count": plan_count,
        "failures_total": failures_total,
        "review_total": review_total,
        "verdict_rows": rows,
        "engine_error_count": engine_error_count,
        "by_failure_mode": dict(by_failure_mode),
        "by_confidence": dict(by_confidence),
        "low_confidence_count": low_confidence_count,
    }


def _compute_cluster_fingerprints(violations: list[Violation]) -> set[str]:
    """Return the set of error_fingerprint values that appear
    ≥_CLUSTER_MIN_COUNT times across the whole run. The PDF generator
    folds these into incident banners; rare fingerprints render as
    normal rows."""
    fp_counts: Counter[str] = Counter()
    for v in violations:
        if v.error_fingerprint:
            fp_counts[v.error_fingerprint] += 1
    return {fp for fp, c in fp_counts.items() if c >= _CLUSTER_MIN_COUNT}


def _build_review_items(
    violations: list[Violation],
    rule_sources: dict[str, str],
) -> list[dict[str, Any]]:
    return [
        {
            "parcel_id": v.parcel_id,
            "rule_id": v.rule_id,
            "source_takanon_id": rule_sources.get(v.rule_id),
            "verdict_he": translate(v.verdict),
            "css_class": css_class(v.verdict),
            "notes": v.notes,
        }
        for v in violations if v.verdict in _REVIEW_VERDICTS
    ]


# ──────────────────────────────────────────────────────────────────────
# Display helpers
# ──────────────────────────────────────────────────────────────────────

def _format_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "כן" if value else "לא"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    if isinstance(value, dict):
        # Compact one-line repr suitable for a table cell.
        return ", ".join(f"{k}: {_format_value(val)}" for k, val in value.items())
    if isinstance(value, (list, tuple)):
        return ", ".join(_format_value(x) for x in value)
    return str(value)


def _format_dt(value: Any) -> str:
    if value is None:
        return "—"
    return str(value)


# ──────────────────────────────────────────────────────────────────────
# Chrome PDF backend
# ──────────────────────────────────────────────────────────────────────

def _find_chrome() -> str | None:
    for p in CHROME_PATHS:
        if Path(p).exists():
            return p
    for cmd in ("google-chrome", "chromium", "chrome"):
        which = shutil.which(cmd)
        if which:
            return which
    return None


def _html_to_pdf(html: str, output_path: Path) -> None:
    chrome = _find_chrome()
    if not chrome:
        raise RuntimeError(
            "no Chrome/Chromium found in /Applications or PATH; "
            "install Chrome or set CHROME_PATH"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "opinion.html"
        html_path.write_text(html, encoding="utf-8")
        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            "--virtual-time-budget=4000",
            f"--print-to-pdf={output_path}",
            html_path.as_uri(),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not output_path.exists():
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            raise RuntimeError(
                f"chrome --print-to-pdf failed (exit {result.returncode})"
            )
