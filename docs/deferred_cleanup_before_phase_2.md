# Deferred cleanup — process before Phase 2 starts

Small, low-risk cleanup tasks accumulated during Phase 1. None are blockers
for shipping Phase 1; do them as a single sweep before Module A work begins
in Phase 2 so we don't carry stale state into the new module surfaces.

## 1. Stale path references after the colon-rename

The repo was renamed from `/Users/liorlevin/Desktop/:planning-platform:/` to
`/Users/liorlevin/Desktop/planning-platform/` during Phase 1 (cargo couldn't
build from a path with literal colons — see ADR-001 history). The rename
left a few non-executing references behind:

- **`CONTEXT.md`** — body text references the old path / `:planning-platform:`
  in places. Update to the new path; nothing breaks if you don't, but it'll
  mislead future readers.
- **`reports/407-0977595/tashrit-analysis-2026-04-30.md`** — a single
  `**Source:**` line points at the old absolute path. Cosmetic.
- **`.claude/settings.local.json`** — cached Bash command allow-list grants
  reference the old path. Claude Code will re-prompt for permission on first
  use of any new path; the stale entries are inert. Safe to leave OR safe to
  prune. Pruning is faster than re-granting on first use of each path.

Action: 5-minute sweep to normalize the path string in the three files above.

## 2. PyInstaller `dist/` + `build/` directories tracked anywhere?

`app/sidecar/dist/` and `app/sidecar/build/` are PyInstaller's outputs from
Phase 1 verification. They're not tracked yet (no `.gitignore` exists for
this directory). Before Phase 2's first commit, add:

```
app/sidecar/build/
app/sidecar/dist/
app/tauri/target/
app/frontend/node_modules/
app/frontend/dist/
```

to a project-level `.gitignore`. The repo isn't currently under git but if/when
Phase 2 introduces version control, these large generated trees should be
excluded.

## 3. `PLATFORM_DB_KEY` default value

The Phase 1 default in `app/sidecar/sidecar/config.py` is the literal string
`phase1-dev-key-DO-NOT-SHIP`. The TODO is documented in the code; the cleanup
is to either (a) wire up the real PIN-derived key as part of Phase 2 settings
work, or (b) explicitly mark this file as production-blocking via a more
prominent warning. Recommend (a) once Phase 2's settings UI is in place.

## 4. `app/sidecar/run_sidecar.py` `--probe` mode

The forward-compat WeasyPrint probe lives in `run_sidecar.py` for now (see
PYINSTALLER_NOTES.md). It's harmless in production (only runs when
`--probe MODE` is on the CLI), but Phase 2 could move it to a dedicated
`scripts/probe.py` to keep the main entry point lean. Not urgent.

## 5. Echo job leftover

`/jobs/echo` exists as the day-1 proof of ADR-001 subprocess isolation. Once
Phase 2 has at least one real job type wired in (e.g., `run_audit`), the echo
endpoint can move to a `/_internal/` namespace or be removed entirely. The
React UI's echo button can disappear at the same time.

## 6. Empty `app/sidecar/dist/sidecar_full/` after sweeps

The 187 MB `sidecar_full` PyInstaller bundle is a probe artifact, not a
shipped binary. Delete it before merging Phase 2 work; the spec file
(`backend_full.spec`) is sufficient to rebuild on demand.
