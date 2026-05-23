"""Per-parcel rule resolver.

Given a submitted תכנית עיצוב, the compliance engine processes each תא שטח
separately. This module answers the question: "for this cell, which rules
apply?"

Resolution order (per CONTEXT.md → Architectural Decisions → Design plan ↔
statutory plan):

  1. Find the parcel's `governing_takanon_id` from project_data
     (it's a plan_number string, e.g. "407-0977595").
  2. Look up that plan in the project's `linked_statutory_plans[]` to
     recover its `version_label`.
  3. Resolve (project_id, version_label) → takanon_versions.id (the UUID
     used as the rules table foreign key).
  4. Load all active rules for that takanon_id.
  5. Apply project_rule_exceptions overrides — for each rule, if a row
     in `project_rule_exceptions` matches (project_id, rule_id), apply
     the override and mark `is_overridden=True`. The original parameters
     are preserved in `original_parameters` for audit.

Coverage-type semantics:
  - `primary` and `partial` plans contribute rules to parcels that point
    at them via `governing_takanon_id`.
  - `adjacent_reference` plans never contribute rules — they're context
    only. Even if a parcel's `governing_takanon_id` points at one (data
    inconsistency), the resolver returns an empty list and emits a
    warning to the caller.

This module does NOT evaluate rules. It only resolves WHICH rules to
evaluate. The evaluator is a separate task (see CONTEXT.md Open Tasks).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import warnings
from typing import Any

from .types import Rule, RuleType


logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def resolve_rules_for_parcel(
    parcel_id: str,
    project_data: dict,
    db_conn: sqlite3.Connection,
) -> list[Rule]:
    """Return the ordered list of rules to evaluate against `parcel_id`.

    Args:
        parcel_id: The parcel identifier from project_data (e.g. "plot_1").
        project_data: The parsed project schema JSON (the dict you get
            from `json.load(open("project-schema-*.json"))`). Must include
            `linked_statutory_plans[]`, `project.parcels[]`, and
            `project.meta.plan_number`.
        db_conn: Open SQLite connection. Must have at minimum the
            `projects`, `takanon_versions`, `rules`, and
            `project_rule_exceptions` tables populated.

    Returns:
        List of `Rule` instances. Empty list if:
          - The parcel doesn't exist in `project_data`.
          - The parcel has no `governing_takanon_id`.
          - The parcel's governing plan is `adjacent_reference` (warning emitted).
          - The plan exists in linked_statutory_plans but has no rules in DB
            (e.g., the partial-coverage plan whose תקנון hasn't been ingested).

        On the happy path, returns rules in `rule_code` order with overrides
        applied where applicable.

    Raises:
        ValueError: If project_data is malformed (missing required keys
            or referencing a plan_number not in linked_statutory_plans[]).
    """
    parcel = _find_parcel(parcel_id, project_data)
    if parcel is None:
        return []

    governing_plan_number = parcel.get("governing_takanon_id")
    if not governing_plan_number:
        return []

    # Verify the plan is in linked_statutory_plans + check coverage_type.
    link = _find_linked_plan(governing_plan_number, project_data)
    if link is None:
        raise ValueError(
            f"parcel {parcel_id!r} has governing_takanon_id="
            f"{governing_plan_number!r} but that plan is not in "
            f"project.linked_statutory_plans[]"
        )

    coverage_type = link.get("coverage_type")
    if coverage_type == "adjacent_reference":
        warnings.warn(
            f"parcel {parcel_id!r} points at plan {governing_plan_number!r} "
            f"which is linked as adjacent_reference; adjacent_reference "
            f"plans don't contribute rules. Returning empty rule set.",
            stacklevel=2,
        )
        return []

    # Resolve plan_number → takanon_versions.id via DB.
    project_id = _resolve_project_id(project_data, db_conn)
    takanon_id = _resolve_takanon_id(
        project_id=project_id,
        version_label=link.get("version_label"),
        db_conn=db_conn,
    )
    if takanon_id is None:
        # The plan is declared in JSON but its takanon row doesn't exist
        # in DB yet (e.g. 407-1048248 awaiting תקנון). Empty rules — caller
        # can decide whether that's actionable.
        logger.info(
            "no takanon_versions row for plan_number=%s "
            "(project_id=%s, version_label=%s)",
            governing_plan_number, project_id, link.get("version_label"),
        )
        return []

    rules = _load_rules(takanon_id, governing_plan_number, db_conn)
    rules_with_overrides = _apply_overrides(rules, project_id, db_conn)
    return rules_with_overrides


# ──────────────────────────────────────────────────────────────────────
# Helpers — JSON lookups
# ──────────────────────────────────────────────────────────────────────

def _find_parcel(parcel_id: str, project_data: dict) -> dict | None:
    parcels = project_data.get("project", {}).get("parcels", [])
    for p in parcels:
        if p.get("parcel_id") == parcel_id:
            return p
    return None


def _find_linked_plan(plan_number: str, project_data: dict) -> dict | None:
    for link in project_data.get("linked_statutory_plans", []):
        if link.get("plan_number") == plan_number:
            return link
    return None


# ──────────────────────────────────────────────────────────────────────
# Helpers — DB lookups
# ──────────────────────────────────────────────────────────────────────

def _resolve_project_id(project_data: dict, db_conn: sqlite3.Connection) -> str:
    """Look up projects.id (UUID) by plan_number from the JSON's project.meta."""
    meta = project_data.get("project", {}).get("meta", {})
    plan_number = meta.get("plan_number")
    if not plan_number:
        raise ValueError("project_data.project.meta.plan_number is missing")
    row = db_conn.execute(
        "SELECT id FROM projects WHERE plan_number = ?", (plan_number,)
    ).fetchone()
    if row is None:
        raise ValueError(
            f"no projects row found for plan_number={plan_number!r}; "
            f"did you run load_project.py?"
        )
    return row[0]


def _resolve_takanon_id(
    project_id: str,
    version_label: str | None,
    db_conn: sqlite3.Connection,
) -> str | None:
    if not version_label:
        return None
    row = db_conn.execute(
        "SELECT id FROM takanon_versions "
        "WHERE project_id = ? AND version_label = ?",
        (project_id, version_label),
    ).fetchone()
    return row[0] if row else None


def _load_rules(
    takanon_id: str,
    source_plan_number: str,
    db_conn: sqlite3.Connection,
) -> list[Rule]:
    """Load all active rules for a takanon, return as Rule objects."""
    cur = db_conn.execute(
        """SELECT id, rule_code, rule_type, plot, operator,
                  threshold, threshold_text, unit,
                  source_quote, source_page, description,
                  severity_if_violated, raw_json
           FROM rules
           WHERE takanon_version_id = ? AND is_active = 1
           ORDER BY rule_code""",
        (takanon_id,),
    )
    rules: list[Rule] = []
    for row in cur:
        (rule_uuid, rule_code, rule_type_str, plot, operator,
         threshold, threshold_text, unit, source_quote, source_page,
         description, severity, raw_json) = row

        params: dict[str, Any] = {
            "_rule_uuid": rule_uuid,  # internal — needed for override matching
            "operator": operator,
            "threshold": threshold,
            "threshold_text": threshold_text,
            "unit": unit,
            "source_quote": source_quote,
            "source_page": source_page,
            "description": description,
            "severity_if_violated": severity,
        }
        # Surface anything else from raw_json (applies_when, geometry_note, etc.)
        if raw_json:
            try:
                extra = json.loads(raw_json)
            except (TypeError, json.JSONDecodeError):
                extra = {}
            for k, v in extra.items():
                params.setdefault(k, v)

        rules.append(Rule(
            rule_id=rule_code,
            rule_type=RuleType.from_str(rule_type_str),
            source_takanon_id=source_plan_number,
            parameters=params,
            plot=plot,
        ))
    return rules


# ──────────────────────────────────────────────────────────────────────
# Helpers — exception application
# ──────────────────────────────────────────────────────────────────────

def _apply_overrides(
    rules: list[Rule],
    project_id: str,
    db_conn: sqlite3.Connection,
) -> list[Rule]:
    """Look up project_rule_exceptions for each rule, apply when matched.

    Override semantics: any active row in `project_rule_exceptions` with
    matching (project_id, rule_id) overrides the rule's parameters with
    a `_override` payload. The exception's `notes` becomes the
    `override_reason`. The pre-override parameters are preserved on the
    Rule via `original_parameters`.

    "Active" means: not expired (`expires_at` is NULL or > now).
    """
    if not rules:
        return rules

    rule_uuid_to_rule = {r.parameters.get("_rule_uuid"): r for r in rules}
    rule_uuids = [u for u in rule_uuid_to_rule if u]
    if not rule_uuids:
        return rules

    placeholders = ",".join("?" * len(rule_uuids))
    cur = db_conn.execute(
        f"""SELECT rule_id, exception_type, notes, plot, expires_at
            FROM project_rule_exceptions
            WHERE project_id = ?
              AND rule_id IN ({placeholders})
              AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)""",
        (project_id, *rule_uuids),
    )
    exceptions_by_rule_uuid: dict[str, dict] = {}
    for row in cur:
        rule_uuid, exception_type, notes, plot, expires_at = row
        # Last-write-wins if multiple exceptions match the same rule —
        # callers can enforce uniqueness via DB constraint if they want.
        exceptions_by_rule_uuid[rule_uuid] = {
            "exception_type": exception_type,
            "notes": notes,
            "plot": plot,
            "expires_at": expires_at,
        }

    out: list[Rule] = []
    for rule in rules:
        rule_uuid = rule.parameters.get("_rule_uuid")
        exc = exceptions_by_rule_uuid.get(rule_uuid)
        if exc is None:
            out.append(rule)
            continue

        # Apply override: copy original params and tag with override metadata.
        new_params = dict(rule.parameters)
        new_params["_override_type"] = exc["exception_type"]
        new_params["_override_plot_scope"] = exc["plot"]
        out.append(rule.with_override(
            new_parameters=new_params,
            reason=exc["notes"],
        ))
    return out
