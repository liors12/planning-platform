# Job-type registry

The contract between the FastAPI sidecar and the worker subprocesses. See [ADR-001](./ADR-001-subprocess-isolation.md) for why work runs out-of-process.

**Rule:** every entry in this table corresponds to one CLI-invokable Python script. The sidecar may dispatch only what appears here. Adding a new job type means adding a row, writing the script, and writing its input/output schemas.

## Registry

| Job type | CLI invocation | Wall-clock budget | Peak memory budget | Input schema | Output | Status |
|---|---|---:|---:|---|---|---|
| `run_audit` | `python3.13 scripts/run_audit.py --job-dir DIR` (canonical); positional `{project_key} {version}` retained as backward-compat wrapper | 300 s | 2.0 GB | `{pdf_path: str, schema_path: str, project_key: str, submission_version: str, extracts_path?: str, discipline_findings_path?: str, audit_outputs_root?: str, feedback_db_path?: str}` | `{job_dir}/job_output.json` (full audit_results dict); on failure `{job_dir}/error.json` + non-zero exit | Shipped (Phase 2b — migrated from v8j positional CLI) |
| `gen_discipline_templates` | `python3.13 scripts/gen_discipline_feedback_templates.py` | 30 s | 150 MB | none (reads latest `audit_results.json` for hardcoded project) | `templates/v24_3_discipline_feedback_*.docx` (4 files) | Shipped (v8j post-ship) |
| `dwg_parse` | `python3.13 scripts/dwg_parse.py {dwg_path} --job-dir DIR` | 180 s | 1.5 GB | `{dwg_path: str}` | `{job_dir}/dwg_extract.json` (normalized plots + buildings + setbacks) | **Planned** (v8a-3, paused) |
| `extract_submission_data` | `python3.13 scripts/extract.py {pdf_path} --project-schema SCHEMA --job-dir DIR` | 120 s | 800 MB | `{pdf_path: str, allow_llm: bool}` | `{job_dir}/extraction_cache.json` | Planned (v8a-2, vision-LLM extractor) |

## Columns explained

- **Wall-clock budget** — sidecar SIGKILLs the subprocess at this deadline. See ADR-001 § 3. Choose conservatively: budget = 3× the worst observed runtime on a representative input.
- **Peak memory budget** — informational target, not enforced. Used to size the concurrency cap (ADR-001 § 2). If a worker breaches its budget under realistic input, either fix the worker or raise the budget — never silently bypass.
- **Input schema** — the contract the sidecar writes to `{job_dir}/job_input.json` before spawning. Workers MUST validate inputs; schema-mismatch failures land in `{job_dir}/error.json` with a clear message.
- **Output** — where the worker writes its result. For audits the path is fixed by historical convention; for newer jobs we use `{job_dir}/job_output.json` (ADR-001 § 1).

## Adding a job type

1. Pick a snake-case name. It becomes both the script name (`scripts/{name}.py`) and the sidecar dispatch key.
2. Write the worker as a standalone script. The script's `main()` must:
   - Parse a `--job-dir` argument (the per-invocation temp dir).
   - Read `job_input.json` from that dir (if the job has typed input).
   - Write `job_output.json` (success) or `error.json` (failure) before exiting.
   - Exit non-zero on failure. Sidecar uses exit code, not `error.json` presence, as the first failure signal.
3. Add a row to the table above. Wall-clock budget = 3× worst observed runtime; peak memory = max observed RSS plus 50% headroom.
4. Reference the input/output schemas. For non-trivial schemas, link to a JSON Schema file under `docs/architecture/schemas/`.
5. Update the sidecar's dispatch table (when it exists) to route requests to the new script.

## Concurrency interaction

The cap is **per-process**, not per-job-type. Two `gen_discipline_templates` invocations (150 MB each = 300 MB total) count the same as one `run_audit` (2 GB) for the concurrency budget. Until the sidecar supports per-job-type priority queuing, the safe rule is: serve the request that arrived first, queue everything else.

## Failure modes by job type

| Job | Common failure | Sidecar response |
|---|---|---|
| `run_audit` | Missing `metadata.json` or PDF | 404; surface path |
| `run_audit` | Format-rule engine crash | 500 with stack trace; engine bug |
| `run_audit` | LLM extractor timeout / API error | 502 with retry hint; transient |
| `gen_discipline_templates` | `audit_results.json` missing | 409 — run an audit first |
| `dwg_parse` | libredwg conversion failure | 422 with libredwg stderr |
| `dwg_parse` | DXF too malformed for ezdxf | 422 with `ezdxf.recover` audit errors |
| any | Wall-clock budget exceeded | 504 (gateway timeout); job dir preserved for forensics |
| any | OOM-killer (Windows) | 500; recommend reducing concurrency cap |

## Open items

- **Job-input/output JSON schemas** are not yet formally defined for the existing scripts (`run_audit`, `gen_discipline_templates`). Lock down before the sidecar starts importing this registry.
- **Sidecar dispatch table** doesn't exist yet — this registry is the design document for it.
- **Per-job-type queue priority** (ADR-001 § 2 implies a single queue; if real usage shows starvation for fast jobs behind slow ones, revisit).
