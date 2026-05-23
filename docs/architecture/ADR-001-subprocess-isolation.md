# ADR-001: Heavy operations run as isolated Python subprocesses

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-05-18 |
| **Decider** | Lior Levin |
| **Supersedes** | — |
| **Related** | [docs/architecture/job_types.md](./job_types.md) |

---

## Context

The compliance platform's target deployment is **Ellen's Windows machine, 8 GB RAM**. Ellen runs other applications alongside the platform — Word, Outlook, a DWG viewer, a browser with multiple tabs. Realistic baseline OS + other apps consumes 4-5 GB.

The platform performs several memory-heavy operations:

- **DWG parsing** (v8a-3 onwards): libredwg CLI conversion + ezdxf entity walk on multi-plot DWG files. Transient peaks of 1.5-2 GB during the entity walk, depending on file size and INSERT-block depth.
- **PDF generation**: WeasyPrint rendering of the 60-page Hebrew RTL audit report with embedded Heebo font and inline SVG. Transient peak ~800 MB-1.2 GB.
- **Audit regeneration** (`scripts/run_audit.py`): orchestrates content + format + discipline checks, extraction-cache hydration, optional LLM extraction. Peak ~2 GB when LLM extraction is active.
- **Word doc template generation** (`scripts/gen_discipline_feedback_templates.py`): lighter (~100 MB peak) but follows the same discipline for consistency.

If any of these run **in-process** inside a long-lived FastAPI sidecar:

1. **Resident memory stays high after the job ends.** Python's allocator returns memory to the arena, not to the OS. A sidecar that ran a 2 GB job 30 minutes ago is still holding ~1.8 GB resident even though it's idle.
2. **Concurrent jobs compound.** Two simultaneous in-process jobs can push the sidecar's resident set to 3-4 GB, which on an 8 GB machine — with 4-5 GB already in use by the OS + Ellen's other apps — triggers swap. Swap on Windows means seconds-to-minutes UI freezes.
3. **A single bad input (malformed DWG, infinite loop in a checker) takes down the sidecar.** Restart loses any in-memory state and forces a cold-start for the next request.

## Decision

**All heavy operations run as isolated Python subprocesses spawned by the FastAPI sidecar.** The sidecar's role is dispatch + bookkeeping. It does not import compliance-engine modules at runtime.

```
HTTP request
     │
     ▼
[FastAPI sidecar]  ◄── stays under 100 MB resident
     │   (writes job_input.json to job-scoped temp dir,
     │    spawns subprocess, waits, reads job_output.json)
     │
     ▼
[subprocess.Popen("python3.13 scripts/run_audit.py …")]
     │   (does the work, writes JSON + PDF to disk, exits)
     │
     ▼
OS reclaims memory ────► sidecar reads disk output ────► HTTP response
```

The CLI invocation is the contract. The sidecar knows: which script to run, what arguments to pass, where to read output from, what wall-clock budget to enforce. It does not know how the work is done internally.

## Rationale

- **Subprocess exit releases all memory back to the OS unconditionally.** No allocator caching, no fragmentation accumulation. Each job starts from a known-zero state.
- **Crash isolation.** A SIGSEGV in libredwg, a Python `RecursionError` in a checker, an OOM-killer kill — none of these touch the sidecar. The sidecar reads `error.json` (or detects non-zero exit) and reports the failure cleanly.
- **Wall-clock budgets are enforceable.** `subprocess.Popen` + `proc.terminate()` after a timeout is a one-liner; thread cancellation in Python is unreliable.
- **Subprocess startup overhead is negligible at this scale.** Our jobs are minute-scale. Even Windows' slow Python startup (200-400 ms) is <1% of total job time.

## Implications (the 5 locked-in rules)

These are the operational rules. The job registry ([job_types.md](./job_types.md)) tracks the per-job-type values.

### 1. JSON-on-disk handoff, not stdin/stdout

Sidecar writes `job_input.json` to a job-scoped temp dir (e.g., `~/.platform/jobs/{uuid}/job_input.json`), spawns the subprocess with the dir as a CLI arg, subprocess writes `job_output.json` (or `error.json` on failure) and exits.

**Why:** survives sidecar crashes, debuggable post-mortem (the job dir is the audit trail), no pipe-buffer deadlocks on chunky stdout, no encoding-mode bugs on Windows.

### 2. Hard concurrency cap of 1 (configurable to 2)

Configured via `PLATFORM_MAX_CONCURRENT_JOBS` env var. Safe default: **1**. Ellen's 8 GB machine cannot safely run two heavy jobs concurrently.

**Why:** a `run_audit` (2 GB peak) + a `dwg_parse` (1.5 GB peak) running simultaneously would push resident set to 3.5 GB, which on top of OS + Ellen's apps triggers swap.

### 3. Wall-clock budgets per job type, enforced by SIGKILL

Sidecar SIGKILLs runaways at the budget. No exceptions, no soft-kill grace period (one was added in development and discovered to be how a hung libredwg invocation pinned the machine for 40 minutes).

Budgets are documented per job in [job_types.md](./job_types.md).

### 4. Subprocess uses the same Python interpreter as the platform installer

On macOS dev: `/opt/homebrew/bin/python3.13`. On Windows: the bundled Python in the platform's MSI installer (target: 3.13.x).

**Why:** WeasyPrint depends on Pango/Cairo native libraries that are installed at a known prefix. A venv embedded inside the FastAPI process would not see those. Using the platform's installer Python guarantees the native deps resolve.

### 5. No shared module imports between sidecar and workers

The sidecar does **not** `from compliance_engine.audit import ...`. The CLI invocation is the only interface. See "Prohibited patterns" below.

## Prohibited patterns

These look convenient and are not.

### ❌ Direct import inside the sidecar

```python
# sidecar/handlers.py
from compliance_engine.audit import run_full_audit

@app.post("/audit/{project_key}")
async def run_audit_handler(project_key: str):
    # This pulls all of compliance_engine into the sidecar process —
    # WeasyPrint, ezdxf (if v8a-3), PyMuPDF, and every transitive dep.
    # The sidecar's resident set jumps from ~80 MB to ~400 MB just at import.
    results = run_full_audit(...)
    return results
```

### ✅ Subprocess invocation instead

```python
# sidecar/handlers.py
import subprocess, json, uuid
from pathlib import Path

@app.post("/audit/{project_key}")
async def run_audit_handler(project_key: str, version: str):
    job_dir = Path.home() / ".platform" / "jobs" / str(uuid.uuid4())
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job_input.json").write_text(json.dumps({
        "project_key": project_key, "version": version,
    }), encoding="utf-8")

    result = subprocess.run(
        [PYTHON_BIN, "scripts/run_audit.py", project_key, version,
         "--job-dir", str(job_dir)],
        timeout=300,                       # per job_types.md budget
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        err = json.loads((job_dir / "error.json").read_text(encoding="utf-8"))
        raise HTTPException(500, err)
    output = json.loads((job_dir / "job_output.json").read_text(encoding="utf-8"))
    return output
```

### ❌ Thread pool for "lightweight" jobs

```python
# sidecar/template_handler.py
from concurrent.futures import ThreadPoolExecutor
from scripts.gen_discipline_feedback_templates import main as gen_templates

executor = ThreadPoolExecutor(max_workers=2)

@app.post("/templates/generate")
async def gen_templates_handler():
    # "It's only 100 MB peak, surely this is fine" — until python-docx
    # bug, malformed audit JSON, or a future enrichment grows the peak.
    # The rule has no carve-outs. Once one path bypasses isolation,
    # peak-memory guarantees evaporate.
    future = executor.submit(gen_templates)
    return await asyncio.wrap_future(future)
```

### ❌ Caching a subprocess result by re-importing

```python
# sidecar/cache.py
from compliance_engine.report_generator import generate_audit_pdf
# Even importing for "just the type definitions" pulls the module's
# top-level imports — WeasyPrint, fitz (PyMuPDF), etc. Forbidden.
```

If you need shared type definitions between sidecar and workers, put them in a **tiny** `compliance_engine/types.py` with stdlib-only imports (dataclasses, enums, str). Import from that module is allowed.

## Consequences

**Positive:**
- Sidecar memory bounded regardless of job complexity.
- Worker crashes are isolated; sidecar uptime is independent of worker correctness.
- Jobs are debuggable individually — each `~/.platform/jobs/{uuid}/` is a self-contained reproduction.
- Trivial to add new job types: write a script, add to job registry, sidecar dispatches.

**Negative:**
- Subprocess startup adds 200-400 ms on Windows. Acceptable for minute-scale jobs.
- No in-memory caching between jobs (e.g., WeasyPrint font config). Each subprocess pays the cold-start cost. Acceptable; the alternative violates the rule.
- Job results round-trip through disk. For very large outputs (>100 MB) this is wasteful, but our outputs are <20 MB and disk I/O on SSD is <100 ms.

## What this constraint does NOT govern

- **Sidecar's own hot path** (config loading, cached audit-results lookup, feedback SQLite queries, webhook handling) — all in-process, all <10 MB.
- **Read-only data files** referenced by both sidecar and workers (e.g., `discipline_rules.json`) — these are file-system shared, not memory-shared. Sidecar can read its own copy for routing decisions; workers read theirs for compute.

## References

- Job registry: [docs/architecture/job_types.md](./job_types.md)
- Submission requirements (deployment constraints): `submission_requirements_v1.docx`
- Python subprocess docs: https://docs.python.org/3/library/subprocess.html
