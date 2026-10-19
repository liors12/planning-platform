"""Gate: no workflow may publish, tag or delete a release except on a version tag.

On 2026-07-27 a push to main ran build-windows.yml's release job, which
published a GitHub Release labelled 0.2.1 that actually contained 0.2.2 code,
and deleted the real 0.2.1 release on the way. Nobody had approved a release;
the merge alone did it, because the release steps were gated on
`github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/')`.

The policy this file enforces, on EVERY workflow in .github/workflows/:

  1. Any step that publishes, tags or edits a release may run only when the
     ref is a version tag - its condition (step or job level) must require
     `startsWith(github.ref, 'refs/tags/v')` and must not admit any branch.
  2. A release created by softprops/action-gh-release must be `draft: true`.
     A human publishes; CI never does.
  3. Nothing deletes a release or a tag. Ever, under any condition.

WORKFLOWS_DIR overrides the directory, so the red half of the red-green can
be run against an older copy of the workflows.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WF_DIR = Path(os.environ.get("WORKFLOWS_DIR") or ROOT / ".github/workflows")

# A step is "release-writing" if it uses the release action or shells out to
# a command that creates, edits, publishes, tags or deletes.
WRITE_CMD = re.compile(
    r"gh\s+release\s+(create|edit|upload|delete)"
    r"|git\s+tag\b"
    r"|git\s+push\b[^\n]*(--tags|--delete|\s:refs/tags/|refs/tags/)"
    r"|--cleanup-tag"
)
DELETE_CMD = re.compile(r"gh\s+release\s+delete|--cleanup-tag|git\s+push\b[^\n]*--delete"
                        r"|git\s+tag\s+(-d|--delete)")
TAG_ONLY = "startsWith(github.ref, 'refs/tags/v')"


def _workflows():
    files = sorted(WF_DIR.glob("*.yml")) + sorted(WF_DIR.glob("*.yaml"))
    assert files, f"no workflow files found in {WF_DIR}"
    return [(f, yaml.safe_load(f.read_text(encoding="utf-8"))) for f in files]


def _steps():
    for f, wf in _workflows():
        for job_id, job in (wf.get("jobs") or {}).items():
            job_if = str(job.get("if") or "")
            for step in job.get("steps") or []:
                yield f.name, job_id, job_if, step


def _is_release_step(step) -> bool:
    uses = str(step.get("uses") or "")
    run = str(step.get("run") or "")
    return "action-gh-release" in uses or bool(WRITE_CMD.search(run))


def _label(fname, job_id, step) -> str:
    return f"{fname} :: {job_id} :: {step.get('name') or step.get('uses') or '<unnamed>'}"


def test_release_steps_run_only_on_version_tags():
    offenders = []
    for fname, job_id, job_if, step in _steps():
        if not _is_release_step(step):
            continue
        cond = f"{job_if} && {step.get('if') or ''}"
        if TAG_ONLY not in cond:
            offenders.append(f"{_label(fname, job_id, step)}  [if: {step.get('if')!r}]")
        elif "refs/heads/" in cond or "github.ref_name ==" in cond:
            offenders.append(f"{_label(fname, job_id, step)}  admits a branch: {cond!r}")
    assert not offenders, (
        "release-writing steps that can run without a version tag:\n  "
        + "\n  ".join(offenders)
    )


def test_releases_are_created_as_drafts():
    offenders = []
    for fname, job_id, _, step in _steps():
        if "action-gh-release" in str(step.get("uses") or ""):
            if (step.get("with") or {}).get("draft") is not True:
                offenders.append(_label(fname, job_id, step))
    assert not offenders, "releases created without draft: true:\n  " + "\n  ".join(offenders)


def test_nothing_deletes_a_release_or_tag():
    offenders = [_label(f, j, s) for f, j, _, s in _steps()
                 if DELETE_CMD.search(str(s.get("run") or ""))]
    assert not offenders, (
        "steps that delete releases or tags (forbidden under any condition):\n  "
        + "\n  ".join(offenders)
    )


def test_gate_actually_sees_release_steps():
    """Anti-vacuity: if no release step is found at all, the gate above
    passes for the wrong reason (e.g. the action was renamed)."""
    found = [s for *_, s in _steps() if _is_release_step(s)]
    if WF_DIR == ROOT / ".github/workflows":
        assert found, "no release step found - the gate would be vacuous"
