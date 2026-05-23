# Phase 2a — Completion + Sign-off

**Status:** ✅ Complete — all 8 acceptance criteria green
**Spec reference:** [docs/product_spec_v0.1.md § 5 (Module A) + § 10 (Phase 2)](./product_spec_v0.1.md)
**Date completed:** 2026-05-18
**Effort vs. estimate:** Single session; ~7 hrs backend + ~3 hrs frontend = **~10 hrs** total. Well under the 35-45 hr estimate (and far under the spec's half-of-4-weeks budget).

---

## Acceptance criteria — 8/8 ✅

Verified by `app/sidecar/scripts/acceptance_test_phase_2a.py` (runs end-to-end
including a sidecar restart). Full output preserved at the bottom of this doc.

| # | Criterion | Evidence |
|---|---|---|
| 1 | Create project "מתחם הטייסים-ההסתדרות" / תב"ע 407-1048248 via UI | `POST /projects` → id=1, `has_schema=true` |
| 2 | Upload v24.3 architect PDF | `POST /projects/1/submissions` (multipart) — **100,378,949 bytes** streamed to `~/.platform/projects/1/submissions/v24.3/v24.3.pdf` |
| 3 | Run Engine — status transitions queued → running → completed | All three transitions observed; engine ran in subprocess via the path-bridge; total ~70 s |
| 4 | Findings JSON returned | All 7 top-level keys present; discipline counts **9 pass / 8 fail / 16 requires_review** match v8j baseline exactly |
| 5 | Restart app; project, submission, findings persist | Sidecar SIGTERM'd then re-started; all three round-trip via fresh DB connection; verdict counts byte-identical |
| 6 | Sidebar shows project with correct status badge | `GET /projects` returns `status=active`, `submission_count=1`, `latest_submission.status=complete` |
| 7 | 2nd project; switching preserves each project's state | Project A: schema present + 1 submission; Project B: schema absent + 0 submissions — fully independent |
| 8 | Engine failure surfaces a useful error | Run-engine on a no-schema project → HTTP 409 with explanatory Hebrew/English message |

---

## Bugs found + fixed during smoke test

Four real bugs surfaced while building the engine integration. All are now
stable and re-verified by the acceptance test.

### Bug 1 — Missing `python-multipart` dependency

**Symptom:** Sidecar crashed at startup with `RuntimeError: Form data
requires "python-multipart" to be installed` as soon as any endpoint declared
`File()` or `Form()` parameters.

**Fix:** `pip install python-multipart` + added the dep to `requirements.txt`.

**Lesson:** FastAPI's docs list it as a hidden requirement for multipart
endpoints; we missed it because Phase 1 had no multipart routes.

### Bug 2 — `asyncio.Queue.put_nowait()` called cross-thread

**Symptom:** Engine job stayed in `queued` indefinitely. Worker loop alive,
but never woke up to process the queued job.

**Root cause:** FastAPI runs **sync** route handlers in a threadpool. The
`/run-engine` handler called `queue.put_nowait(job_id)` from a worker
thread, but the queue's pending getter future is owned by the event loop on
the main thread. Cross-thread `put_nowait` corrupted the asyncio internals
silently (no exception; the future just never resolved).

**Fix:** `EngineQueue.start()` captures the event loop reference;
`enqueue_run_audit` routes the put via
`asyncio.run_coroutine_threadsafe(queue.put(job_id), loop)`.

**Where:** `app/sidecar/sidecar/queue_worker.py`, `EngineQueue.enqueue_run_audit`.

### Bug 3 — Two `QUEUE` singletons from `python -m sidecar.main` + uvicorn

**Symptom:** `RuntimeError: EngineQueue.start() was not called` raised from
`enqueue_run_audit`, even though the startup log clearly showed "engine queue
worker started".

**Root cause:** `python -m sidecar.main` loads `sidecar/main.py` under the
`__main__` module name. Then `main()` calls `uvicorn.run("sidecar.main:app", ...)`,
where the **string form** makes uvicorn re-import the module under its
canonical name `sidecar.main`. Both modules execute the top-level
`QUEUE = EngineQueue(...)` line, producing two distinct singleton instances.
The lifespan ran on `sidecar.main`'s instance (setting its `_loop`); the
route handlers — bound to the same `sidecar.main` namespace — should have
referenced the same instance. But because of subtle import-order timing,
the route's closure-captured `queue` ended up referencing `__main__`'s
QUEUE, whose `start()` never ran.

**Fix:** Pass the `app` object directly to `uvicorn.run(app, ...)` instead
of as a string. Avoids the re-import; preserves the single-instance invariant.

**Where:** `app/sidecar/sidecar/main.py`, `main()` function.

### Bug 4 — SQLAlchemy `DetachedInstanceError` in the queue worker

**Symptom:** Engine job marked `failed` immediately with
`DetachedInstanceError: Instance <Project at 0x...> is not bound to a Session`.

**Root cause:** The worker's `_process_one` opened a session, captured the
ORM `sub` and `project` instances, closed the session, then accessed
`sub.version_string` / `project.tava_number` outside the session — which
SQLAlchemy tried to lazy-refresh against a closed session.

**Fix:** Capture the scalar values (`project_id`, `project_tava_number`,
`submission_version_string`, `submission_pdf_path`) inside the `with
Session(...)` block as plain strings/ints. The subprocess.run heavy work
operates on those scalars; the next session is reopened only to persist
results.

**Where:** `app/sidecar/sidecar/queue_worker.py`, `_process_one`.

### Relationship to the Phase 2b commitment ticket

None of the four bugs are blocked by, or block, the
[Phase 2b run_audit.py `--job-dir` migration](./phase_2b_commitments.md).
They're independent. Bug 4's "capture scalars" pattern is mildly ugly and
could go away once the worker delegates everything to the standardized
job-dir contract — at which point the worker becomes a thin pass-through
and there's no risk of accidental ORM-after-session access. But the cleanup
is incidental, not the ticket's primary purpose.

---

## How to open the UI locally on your Mac

### Option A — Native shell + hot reload (recommended for daily dev)

```bash
cd /Users/liorlevin/Desktop/planning-platform/app/tauri
cargo tauri dev
```

This:
1. Starts Vite at `http://127.0.0.1:1420` (frontend hot-reload).
2. Spawns the FastAPI sidecar via `python -m sidecar.main` (dev path —
   uses your Homebrew Python so you can edit `app/sidecar/` and just
   restart the app to pick up changes).
3. Opens the Tauri shell window with the React UI loaded.

The sidebar auto-loads the projects from earlier acceptance-test runs
(unless you wiped the DB). To test the full flow against 407-1048248:

1. **Create project** → "+ פרויקט חדש" → Hebrew name + tava `407-1048248` →
   "צור פרויקט". The new project appears in the sidebar under "פעילים"; the
   workspace opens automatically.
2. **Upload PDF** → "הגשות" tab → form: version `v24.3` + select the PDF
   from `projects/407-1048248/submissions/v24.3/v24.3.pdf` → "העלה הגשה".
   The upload streams ~100 MB to `~/.platform/projects/{id}/submissions/v24.3/`.
3. **Run engine** → "הפעל מנוע" on the new submission card.
   You'll see the status pill go `הועלה → המנוע רץ → הושלם` over ~70 s.
   The verdict-count pills appear inline when complete.
4. **Findings** → switch to the "ממצאים" tab to see the full breakdown
   plus a collapsible raw `findings.json` dump.

### Option B — Browser-only dev (faster iteration on the UI)

If you don't need the native window (e.g., debugging React in Chrome
DevTools):

```bash
# Terminal 1 — backend
cd /Users/liorlevin/Desktop/planning-platform/app/sidecar
/opt/homebrew/bin/python3.13 -m sidecar.main

# Terminal 2 — frontend
cd /Users/liorlevin/Desktop/planning-platform/app/frontend
npm run dev
```

Browser at `http://127.0.0.1:1420/`. Same UI, regular browser DevTools.

### Option C — Production-bundled .app

```bash
cd /Users/liorlevin/Desktop/planning-platform/app/tauri
cargo tauri build
open "target/release/bundle/macos/Planning Platform.app"
```

This produces a self-contained `.app` with the PyInstaller-bundled sidecar
inside (no host Python needed). Slower iteration (rebuild on every change)
but proves the production stack works.

### Reset the local state

If you want to start fresh (wipe all projects, submissions, findings):

```bash
pkill -f "sidecar.main\|Planning Platform.app"
rm -f ~/.platform/platform.db ~/.platform/platform.db-wal ~/.platform/platform.db-shm
rm -rf ~/.platform/projects
# Then re-launch via Option A/B/C.
```

The pre-existing engine schema at
`projects/407-1048248/project-schema-407-1048248-v2.json` is **not** touched
by the reset — only platform state under `~/.platform/` is removed.

---

## Files created / modified in Phase 2a

### Backend (sidecar)

```
app/sidecar/sidecar/models.py            [extended]  Project +4 cols, +Submission, +Job
app/sidecar/sidecar/storage.py           [new]       file-storage helpers + sanitization
app/sidecar/sidecar/engine_bridge.py     [new]       Approach B path bridge to run_audit.py
app/sidecar/sidecar/queue_worker.py      [new]       EngineQueue + worker + orphan recovery
app/sidecar/sidecar/projects.py          [rewrite]   POST/GET/PATCH/archive + has_schema flag
app/sidecar/sidecar/submissions.py       [new]       multipart upload + run-engine + findings
app/sidecar/sidecar/jobs_routes.py       [new]       GET /jobs/{id}
app/sidecar/sidecar/main.py              [rewrite]   wire routers + queue in lifespan;
                                                     uvicorn.run(app, ...) not the string form
app/sidecar/sidecar/db.py                [+sqlite_version pragma]
app/sidecar/requirements.txt             [+python-multipart]
app/sidecar/scripts/smoke_test_phase_2a.py        [new]
app/sidecar/scripts/acceptance_test_phase_2a.py   [new]
```

### Frontend

```
app/frontend/src/api.ts                  [rewrite]   typed client for all Phase 2a endpoints
app/frontend/src/route.ts                [new]       tiny hash-based router (3 routes)
app/frontend/src/App.tsx                 [rewrite]   shell + router + home page
app/frontend/src/components/Sidebar.tsx          [new]   RTL sidebar with status groups
app/frontend/src/components/SubmissionsTab.tsx   [new]   upload + list + engine button
app/frontend/src/components/EngineStatus.tsx     [new]   job polling + result display
app/frontend/src/components/FindingsView.tsx     [new]   verdict-count pills + raw JSON
app/frontend/src/pages/CreateProject.tsx         [new]   project creation form
app/frontend/src/pages/ProjectWorkspace.tsx      [new]   tabs + per-project workspace
app/frontend/src/styles.css              [rewrite]   full Phase 2a styles, RTL logical props
```

### Docs

```
docs/architecture/engine_output_contract.md  [new]  Module B's parsing target
docs/phase_2b_commitments.md                 [new]  run_audit.py --job-dir migration ticket
docs/phase_2a_completion.md                  [new]  this doc
```

---

## Phase 2a → Phase 2b transition

Outstanding for Phase 2b (per the kickoff brief and the commitment ticket):

1. **Module B — pdf.js viewer + side-by-side findings UI.** The current
   findings view is a raw JSON dump with verdict-count pills. Module B
   replaces it with the rich findings list + clickable page references that
   open the embedded PDF viewer.
2. **`run_audit.py` → `--job-dir` contract migration.** See
   [`phase_2b_commitments.md`](./phase_2b_commitments.md) ticket #1. Engine
   bridge (the `Approach B` path-staging code) is deleted as part of this
   work.
3. **Hebrew project search.** Defer was explicitly granted in the Phase 2a
   kickoff Q&A.

Per the kickoff brief: Phase 2b kicks off **after explicit approval**.
This doc lands as the close-out for Phase 2a.

---

## Acceptance-test output (verbatim)

```
=== Boot fresh sidecar ===
  sidecar up

=== Criterion 1 — Create 'מתחם הטייסים-ההסתדרות' (407-1048248) ===
  ✅ criterion 1 — created id=1, has_schema=true: PASS

=== Criterion 2 — Upload v24.3 PDF ===
  ✅ criterion 2 — submission id=1, 100,378,949 bytes stored: PASS

=== Criterion 3 — Run Engine + watch status transitions ===
    status → queued
    status → running
    status → completed
  ✅ criterion 3 — transitions: queued → running → completed: PASS

=== Criterion 4 — Fetch findings, verify shape + verdict counts ===
  ✅ criterion 4 — disciplines: {'fail': 8, 'requires_review': 16, 'pass': 9};
                   audit_run_id=407-1048248/v24.3: PASS

=== Criterion 5 — Restart sidecar; project, submission, findings persist ===
  sidecar back up
  ✅ criterion 5 — project + submission + findings all persisted after restart: PASS

=== Criterion 6 — list_projects exposes status badge data ===
  ✅ criterion 6 — sidebar payload: status=active, submission_count=1, latest=complete: PASS

=== Criterion 7 — Create 2nd project; switching preserves each one's state ===
  ✅ criterion 7 — p1(has_schema=true, 1 sub) vs p2(has_schema=false, 0 sub) — independent: PASS

=== Criterion 8 — Engine failure (schema missing) surfaces useful error ===
  ✅ criterion 8 — HTTP 409 with schema-explanation message: PASS

=== All criteria summary ===
  ✅ 1. created id=1, has_schema=true
  ✅ 2. submission id=1, 100,378,949 bytes stored
  ✅ 3. transitions: queued → running → completed
  ✅ 4. disciplines: {'fail': 8, 'requires_review': 16, 'pass': 9}
  ✅ 5. project + submission + findings all persisted after restart
  ✅ 6. sidebar payload: status=active, submission_count=1, latest=complete
  ✅ 7. p1(has_schema=true, 1 sub) vs p2(has_schema=false, 0 sub) — independent
  ✅ 8. HTTP 409 with schema-explanation message

🎯 PHASE 2A ACCEPTANCE TEST: ALL 8 CRITERIA PASSED.
```

## Polish pass (post-acceptance, pre-sign-off)

After the 8-criterion acceptance test landed green, a short polish pass
closed four UX/data-integrity gaps that surfaced during the user's manual
walk-through. ~1 hr of work; all four reverified via the same acceptance
test (still 8/8) plus targeted probes for the new edge cases.

### Item 1 — `tava_number` unique among active projects

**Problem:** It was possible to create two active projects with the same
תב"ע (e.g., two `407-1048248` rows existed in the dev DB after the manual
test). No constraint, no warning, no UX path to "you probably meant the
existing one".

**Fix — DB layer:**
- `db.py::initialize()` now runs a one-time dedupe pass on every boot:
  `DELETE FROM projects WHERE id IN (… keep oldest per tava_number where
  status != 'archived' …)`. Idempotent — no-op when the DB is clean.
- After dedupe, creates a **partial unique index**:
  `CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_active_tava
   ON projects (tava_number) WHERE status != 'archived'`.
  Archived projects are excluded so re-using a tava after archiving its
  previous occupant is legitimate (verified end-to-end below).

**Fix — API layer:** `POST /projects` does a pre-check + handles the
`IntegrityError` race-safely. Returns **HTTP 409** with a structured payload:
```json
{
  "detail": {
    "error": "duplicate_tava_active",
    "message_he": "פרויקט עם תב\"ע 407-1048248 כבר קיים (\"מתחם הטייסים-ההסתדרות\"). …",
    "existing_project": { "id": 1, "name_he": "…", "tava_number": "…", "status": "active" }
  }
}
```

**Fix — UI layer:** `CreateProject.tsx` parses the 409 detail, shows the
Hebrew explanation inline (not a generic error), and renders a primary
button that deep-links to the existing project. Wording per the brief:
"פרויקט עם תב"ע XXX כבר קיים — פתח את הפרויקט הקיים ([שם]). ניתן להוסיף לו
הגשה חדשה דרך טאב הגשות."

**DB cleanup actually performed:** On first boot after the migration
landed, the sidecar log emitted:
```
2026-05-18 22:25:39 WARNING [sidecar.db] dedupe migration: deleted 1
duplicate active projects (kept oldest per tava_number)
```
The newer of the two 407-1048248 rows (id=3) was the one removed, per the
brief's instruction.

**Probe transcript** (after fix, on a live sidecar):
```
POST /projects {tava=407-1048248}              → HTTP 409 + structured detail
POST /projects/1/archive                       → HTTP 200, status: archived
POST /projects {tava=407-1048248}              → HTTP 201, id=3 (new active)
```

### Item 2 — `submission_count` mismatch report

**Investigation:** The sidebar showed "1 הגשות" for project 999-0000000.
Direct DB inspection (`SELECT * FROM submissions WHERE project_id=2`)
confirmed: there really is one submission there. It was created by the
acceptance test's criterion 8 (upload to the no-schema project so the
`run-engine` endpoint can return 409). So:

**Conclusion:** No display bug, no phantom. The count is accurate. The
submission is acceptance-test residue, not a data-integrity issue. It will
be cleared the next time the DB is reset (instructions earlier in this doc).

**Side fix:** The number was always rendered as `"X הגשות"` (plural form)
regardless of count. For count==1 Hebrew grammar wants `"הגשה אחת"`.
Sidebar now branches:
```ts
{p.submission_count === 1 ? "הגשה אחת" : `${p.submission_count} הגשות`}
```

### Item 3 — Project header overflow

**Problem:** Long Hebrew project names like `"מתחם הטייסים-ההסתדרות"` (with
internal dash and no easy break points) overflowed the visible workspace
on the right edge.

**Fix:** Added `min-width: 0` to the flex child holding the title (without
it, flex refuses to shrink the child below its intrinsic width — the
classic CSS-flex gotcha for long Hebrew/Chinese strings). Plus
`overflow-wrap: anywhere` + `word-break: break-word` on the `h1` itself to
break inside dash-joined runs when needed. The `.project-actions` button
column gets `flex-shrink: 0` so it doesn't compete for space.

### Item 4 — "Run Engine" button label

**Status:** Wording fix. The condition
`sub.status === "complete" ? "הפעל שוב את המנוע" : "הפעל מנוע"`
was already correct in branching but the unfired label was missing the
article "את". Updated to `"הפעל את המנוע"`. After a successful run the
label correctly switches to `"הפעל שוב את המנוע"`. Submissions that
*failed* still show `"הפעל את המנוע"` (per the brief — only a *successful*
run flips the label).

### Polish pass — full file list

```
app/sidecar/sidecar/db.py            [+ dedupe migration + partial UNIQUE index]
app/sidecar/sidecar/projects.py      [+ structured 409 on duplicate_tava_active]
app/frontend/src/pages/CreateProject.tsx  [+ 409 parser + dupe-block UI + deep-link]
app/frontend/src/components/Sidebar.tsx   [Hebrew plural fix]
app/frontend/src/components/SubmissionsTab.tsx  [button label "הפעל את המנוע"]
app/frontend/src/styles.css          [header overflow fix + .dupe-block styles]
```

### Re-verification after polish

```
🎯 PHASE 2A ACCEPTANCE TEST: ALL 8 CRITERIA PASSED.   (re-run; identical output)

Edge probes:
✅ duplicate active tava            → 409 with structured detail + name
✅ archive then re-create same tava → 201 (partial index excludes archived)
✅ Hebrew plural: count=1 → "הגשה אחת" / count>1 → "X הגשות"
✅ frontend rebuilds clean: 39 modules, 164 KB JS, 8.5 KB CSS
```

---

## Sign-off

Phase 2a acceptance items met + polish pass landed. Awaiting explicit
approval before starting Phase 2b.
