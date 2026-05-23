# Phase 2b — Committed deliverables (must land before Module B is declared complete)

Tickets opened during Phase 2a planning that **must close** before Module B (the
findings UI + pdf.js viewer) is signed off. Documenting here so they don't
slide into a "Phase 4 cleanup pass" that never happens.

## CLOSED — 2026-05-19 · Ticket #1 — Migrate `scripts/run_audit.py` to the ADR-001 `--job-dir` contract

**Closed at Phase 2b checkpoint #1.** Evidence:

| What | Status |
|---|---|
| `scripts/run_audit.py --job-dir DIR` is canonical | ✅ |
| Legacy positional CLI retained as backward-compat wrapper (~5 lines) | ✅ |
| Sidecar dispatch rewritten — `engine_bridge.py` shrunk to schema lookup only (`has_schema`, `resolve_schema`); no more directory-copying or `metadata.json` synthesis | ✅ |
| `job_types.md` `run_audit` row updated to new CLI + input schema | ✅ |
| Regression: byte-identical `audit_results.json` across 4 paths (pre-migration baseline, legacy wrapper post-migration, `--job-dir` direct, sidecar `/run-engine` UI flow) | ✅ — SHA `c0e2142653135cbecf2c56bfb70580dee8656970` on all four |
| Acceptance test 8/8 still green (Phase 2a) | ✅ |

**Baseline fixture** lives at `tests/regression/v8j_baseline_v24.3.json`.
**One residual:** `compliance_engine/format_rules_checker.py:35` defaults `rules_path` to a relative path (`Path("submission_format_rules.json")`). The sidecar's subprocess spawn now passes `cwd=PROJECT_ROOT` to handle this. Cleaner fix (absolute default, or explicit path in `job_input.json`) is a small future cleanup, not Phase 2b-blocking.

Original ticket body preserved below for the audit trail.

---

## Ticket #1 (original text) — Migrate `scripts/run_audit.py` to the ADR-001 `--job-dir` contract

**Why this exists:** Phase 2a's engine integration uses the **path bridge**
approach (Approach B from the Phase 2a kickoff decision matrix): the sidecar
copies the user's uploaded PDF into the engine's legacy layout
(`<REPO>/projects/{tava_number}/submissions/v{version}/`), generates a
`metadata.json`, reuses the existing `project-schema-{tava}-v2.json` file,
and invokes `run_audit.py {tava} {version}` with its current CLI. This works,
but violates the uniform `--job-dir` worker contract that ADR-001 and
`docs/architecture/job_types.md` already specify (and that `dwg_parse.py`
already uses).

**What "done" looks like:**

1. `scripts/run_audit.py` accepts `--job-dir DIR` as the canonical invocation:
   ```
   python3.13 scripts/run_audit.py --job-dir DIR
   ```
   where `DIR/job_input.json` contains:
   ```json
   {
     "pdf_path": "absolute path",
     "schema_path": "absolute path",
     "extracts_path": "absolute path (optional)",
     "discipline_findings_path": "absolute path (optional)",
     "project_key": "407-1048248",
     "submission_version": "24.3"
   }
   ```
   and on success the worker writes `DIR/job_output.json` with the full
   `audit_results.json` payload (current shape), or `DIR/error.json` on
   failure with a structured error.

2. The legacy positional CLI (`run_audit.py {project_key} {version}`) is
   either removed OR retained as a deprecated wrapper that constructs a
   `job_input.json` internally + invokes the new path. Either is acceptable;
   the wrapper preserves shell-script compatibility for any external callers.

3. The sidecar's engine-job dispatch is rewritten to use the canonical
   `--job-dir` form. The path-bridge code in `app/sidecar/sidecar/jobs/` is
   removed. No more directory-copying or `metadata.json` synthesis in the
   sidecar.

4. `docs/architecture/job_types.md` `run_audit` row updated to reflect the new
   CLI + schema. Marked `Shipped (Phase 2b)` once landed.

5. Regression check: every existing v8j flow (`run_audit.py 407-1048248 24.3`)
   continues to produce byte-identical `audit_results.json` against a known
   input. Either via the wrapper or via direct migration of test scripts.

**Owner:** Lior + Claude Code, Phase 2b sprint.

**Effort:** ~4 hrs (~3 hrs migration + 1 hr regression check).

**Risk:** Low — the engine internals (`compliance_engine/audit.py`,
`run_full_audit()`) already accept paths; only the CLI shell needs rewriting.

**Acceptance gate:** Module B (Phase 2b) is **not** signed off until this
ticket closes. Sign-off doc for Module B must reference this ticket's
resolution.

## Ticket #3 — Clean up relative paths in compliance_engine

**Status:** OPEN. Low urgency. Not blocking. Target closure: before Phase 3
or Phase 4 (whichever ships first).

**Why this exists:** `compliance_engine/format_rules_checker.py:35` defaults
`rules_path` to `Path("submission_format_rules.json")` — a CWD-relative path.
The v8j-era flow worked because the engine was always invoked with
`cwd=PROJECT_ROOT`. After the Phase 2b `--job-dir` migration, the sidecar's
subprocess no longer naturally has that cwd, so `queue_worker._process_one`
explicitly passes `cwd=str(_RUN_AUDIT_PATH.parent.parent)` (= PROJECT_ROOT)
to `subprocess.run`. This is a workaround, not a fix.

**Why not fix it now:** Phase 2b's mandate is finite. The workaround is one
line, well-commented, and zero risk. Cleaning up the engine module's
defaults is a small refactor across `compliance_engine/` that should land
when we have buffer.

**What "done" looks like:**

1. `format_rules_checker.check_submission_format()` either accepts the rules
   path as an explicit required argument (no default), OR computes a default
   absolute path relative to `compliance_engine/__file__`.
2. `compliance_engine/audit.py::run_full_audit` passes the rules path
   explicitly to `check_submission_format`.
3. `run_audit.py` constructs the absolute path from `ROOT` and passes it
   through `job_input.json` (new optional key `format_rules_path`).
4. `queue_worker._process_one` drops the `cwd=PROJECT_ROOT` workaround.
5. **Regression**: byte-identical `findings.json` against
   `tests/regression/v8j_baseline_v24.3.json` after the cleanup.

**Caveat for future contributors:** when adding new code in
`compliance_engine/` or its workers — **do not** introduce another
relative-path default. A grep over `compliance_engine/` + `scripts/` at
ticket-close time confirmed that `format_rules_checker.py:35` is currently
the **only** instance of `Path("…json")` with a relative default. Keep it
that way.

**Owner:** Claude Code, opportunistic — pick up when there's slack in any
Phase 3+ sprint.

**Effort:** ~1 hr (refactor + regression run).

---

## Ticket #2 — Verify PDF-viewer first-page latency on Ellen's machine before Phase 4 sign-off

**Why this exists:** Phase 2b acceptance criterion #2 — "עמוד ראשון מופיע
תוך זמן סביר" — is graded against the dev machine (Lior's M1, NVMe, target
**< 3 s**). Ellen's production machine is a different beast: 8 GB RAM, SSD,
CPU below M1, and Office Range apps competing for memory at all times. There
is real risk that what is "instant" on the dev box becomes painful on hers.

**What "done" looks like:**

1. With the production-build `.app` installed on Ellen's machine, open a
   project with the v24.3 PDF (100 MB, 63 pages) and time "click Findings tab
   → first page renders". Target: **< 8 s**.
2. If observed latency is between 8 s and 30 s: tolerable, but document the
   number and revisit in a polish pass.
3. If observed latency is ≥ 30 s: **trigger re-engineering** — options
   include server-side page thumbnails (sidecar pre-renders pages to JPEG),
   chunked rendering, or replacing react-pdf with a lighter viewer.
   Re-engineering work goes into its own ticket; Phase 4 sign-off blocks
   until it ships.
4. Record the actual measurement in the Phase 4 sign-off doc.

**Owner:** Lior (machine access) + Claude Code (any re-engineering needed).

**Phase**: Verification happens during Phase 4 (UTM + Windows install
work). Does NOT block Phase 2b acceptance; the dev-machine threshold (< 3 s)
gates Phase 2b sign-off.

**Risk:** Medium. Modern react-pdf with Range requests + page virtualization
typically renders the first page of a 100 MB PDF in 1-4 s on a mid-range
machine. But Hebrew BIDI, font subsetting, and embedded raster scans can all
multiply that. Worst real-world cases I've seen: 15-20 s on 4-core Intel.

## How to track these

This file is the authoritative list. Add new tickets here when they're opened.
When a ticket closes, mark it `## CLOSED — <date>` at the top of its section
and add a brief evidence note (commit SHA / smoke test result), but keep the
ticket text for the audit trail.
