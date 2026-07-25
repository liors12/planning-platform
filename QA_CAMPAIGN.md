# QA Campaign — July 2026 (`qa/campaign-202607`)

Full QA campaign before Ellen installs the released build
(`v0.1.0-20260722-c9c6041`, main = `c9c6041`). **Future sessions: read this
file first** — every phase updates the status table and findings log below.

## The 6-phase plan

| # | Phase | Goal |
|---|-------|------|
| 0 | Campaign infra | This branch + this file + release-step safety gate |
| 1 | WebView2 attach fix | Playwright/WebDriver can drive the packaged app in CI (broken since June — CDP port never binds) |
| 2 | Test suite | Full UI test suite in whatever harness style Phase 1 proves out |
| 3 | Run + triage | Run suite, classify every failure (app bug / test bug / infra) |
| 4 | Fix loop | Fix app bugs found, re-run until clean |
| 5 | Skill | Distill the campaign into a repeatable QA skill |
| 6 | Release | Merge, re-tag, verify release, hand to Ellen |

## Status table

| Phase | Status | Date | Verdict |
|-------|--------|------|---------|
| 0 — infra | DONE | 2026-07-22 | Branch + this file + release steps gated to main/tags (branch dispatches must not clobber Ellen's release) |
| 1 — attach | **GATE 1: BLOCKED** | 2026-07-23 | All sanctioned attempts exhausted; see verdict + fallback below |
| 2 — suite | **GATE 2 (UPGRADED): DONE** | 2026-07-23 | Permanent 5-layer suite: Layer-0 gates (em-dash + jargon lexicon), Layer-1 states/affordances/DOM-leakage, Layer-2 viewport matrix, Layer-3 screenshots + codified judgment, F1-F6 flows — 17/17 green, gates self-tested (see Phase 2 upgraded section) |
| 3 — run+triage | not started | | |
| 4 — fix loop | not started | | |
| 5 — skill | not started | | |
| 6 — release | not started | | |

## Phase 1 — attach attempts (stop at first success)

Baseline failure: `WebView2 CDP endpoint :<port> never responded. Last error:
TypeError: fetch failed` — app launches clean (sidecar starts, zero stderr),
port never binds. Harness: `tests/e2e-ui/tests/helpers.ts` sets
`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=<port>`;
Playwright `chromium.connectOverCDP`. Unchanged since the last green run
(June 29); `app/tauri/` incl. Cargo.lock also unchanged → runner-side runtime
change is the prime suspect.

| Attempt | What | Result | Run | Notes |
|---------|------|--------|-----|-------|
| A — runtime visibility | Log WebView2/Edge runtime version in the UI-gate step | **DONE** | 29987110063 | Runner WebView2 Evergreen = **150.0.4078.65** (150 line shipped 2026-07-02; last green run June 29 ran on 149.0.4022.x). CDP still dead on every port — regression window confirmed |
| B — pipe transport | `--remote-debugging-pipe` instead of port | **N/A by design** | — | Three independent blockers, no run needed: (1) `--remote-debugging-pipe` serves CDP over file descriptors 3/4 **of the browser process**, which must be created by the parent with those fds pre-opened — but the browser process here is spawned by the WebView2 loader inside Tauri, three process layers away from the test harness; the harness cannot pre-open fds on a process it doesn't spawn. (2) `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` can pass the flag but nothing inherits the pipe ends, so the browser would write CDP into nowhere. (3) Playwright's `connectOverCDP` accepts only an HTTP/WS endpoint URL — it has no pipe transport for attach (pipe is used internally only for browsers Playwright itself launches). |
| C — pinned runtime | `WEBVIEW2_BROWSER_EXECUTABLE_FOLDER` → downloaded fixed-version runtime (149.0.4022.98, June-era) | **BLOCKED-ON-TOOLING** | 29990564206 | Edge enterprise MSI payload chain (MSI → Binary.MicrosoftEdgeInstaller → `102~` 196MB inner blob) is not 7z-extractable; the pin was never applied, so the 149-restores-CDP hypothesis is UNTESTED, not disproven |
| D — tauri-driver | tauri-driver + msedgedriver, versions logged and EXACTLY matched (150.0.4078.65 ↔ 150.0.4078.65) | **FAILED** | 29990564206, 29991472588 | tauri-driver installs, starts, listens; session create hung 60s (run 1) / 500 after ~65s (run 2) — version mismatch ruled out. D-DIRECT variant (msedgedriver in MS-documented WebView2 mode, no tauri-driver) returned 400 Bad Request in 2s = capability shape rejected, INCONCLUSIVE about the runtime — the one probe with a known client-side bug left |
| E — debug build | `cargo tauri build --debug --no-bundle` + tauri-driver probe | **FAILED (rich evidence)** | 29991472588 | 500 in ~5s — but the app DID launch under driver control: `[tauri] FAILED to spawn sidecar` (expected, unbundled) + Chromium `Chrome_WidgetWin_0` window-class teardown logged. The WebDriver stack can LAUNCH the app; the attach handshake is what fails. Debug-vs-release makes no difference |

## Findings log

- 2026-07-22 · Phase 0 · Release steps ("Compute release tag", "Delete previous
  pre-releases", "Create GitHub Release") ran on EVERY successful run including
  branch dispatches — a QA dispatch would have deleted Ellen's release. Gated
  all three to `main`/tags on this branch. Must flow to main at campaign end.

## Gate 1 verdict (2026-07-23)

**BLOCKED.** No attach route works against the runner's current WebView2
(150.0.4078.65, the 150 line that shipped 2026-07-02, right in the
last-green (Jun 29, 149.0.4022.x) → first-red window). Raw CDP port never
binds; tauri-driver/WebDriver (exact driver↔runtime match) fails the session
handshake on both release and debug builds — while demonstrably able to
LAUNCH the app. The block is in the attach handshake, runner-side.

**Phase-2 harness style: undecided — awaiting fallback decision (see below).**

**Most promising fallback (cheap):** fix the D-DIRECT capability shape.
Its 400 Bad Request in 2s is a CLIENT error (malformed capabilities — likely
needs `ms:edgeOptions: {webviewOptions: {}}` per Microsoft's WebView2
WebDriver docs), not a runtime rejection — it is the only probe that failed
on OUR side rather than the runtime's. Cost if it works: Phase 2 is written
WebDriver-style. Second fallback: pin the runner image / try windows-2022
(may still carry pre-150 WebView2) — zero fidelity cost but ties QA to an
aging image. Last resort: split UI QA — frontend logic via plain
Playwright+Chromium against the dev server (high fidelity for UI logic,
loses packaged-shell integration), packaged bundle stays covered by the 49
API-level probes.

## Gate 1 addendum (2026-07-23, run 29993523783) — Attempt D FINAL

**WEBVIEW2-DIRECT-DEAD.** With the CORRECT capability shape (browserName
"webview2" + ms:edgeOptions.webviewOptions {} + binary = packaged exe —
accepted, no 400), msedgedriver launched the app, waited 60s, and returned:

    session not created: DevToolsActivePort file doesn't exist

This is the smoking gun unifying every failure: msedgedriver's own official
WebView2 attach waits for the runtime to open its DevTools interface — and
the 150.0.4078.65 runtime never opens it. Same root cause as the raw-CDP
"port never binds" and the tauri-driver hang. The block is IN the WebView2
150 runtime (or a policy applied to it on the runner image); no client-side
route can work against it.

**Attempt D is FINAL. Phase 1 closed: BLOCKED at the runtime.** Remaining
fallback options (owner decision): (1) runner-image pin / windows-2022 try;
(2) split UI QA — dev-server Playwright for UI logic + existing 49 API
probes for the bundle; (3) wait out a runtime fix / file upstream issue.

## Phase 2 — split-UI test suite (Gate 2, 2026-07-23)

Harness: `tests/ui-dev/` — Playwright (Chromium) against the Vite dev server
(1420) + real sidecar (17321) with a FRESH wiped+seeded data dir per run
(`playwright.config.ts` webServer array). Selectors are data-testid only.
Suite runs serially (workers=1); spec 5 arranges its own precondition via
API when run standalone.

**Accepted gap:** does NOT cover Tauri shell / WebView2 packaging. The
packaged bundle stays covered by the 49 CI API-level probes.

| # | Spec | Covers | Status | RED proof (feature broken → test fails) | GREEN |
|---|------|--------|--------|------------------------------------------|-------|
| 1 | 1-guidelines | Edit 105→110 → גרסה 2 + history shows both | PASS | Sabotaged `version=old.version` (no bump) in guidelines.py → `toContainText` failed on version marker | 1 passed |
| 2 | 2-create-project | Manual create → redirect to workspace | PASS | Removed post-create `navigate()` → `toHaveURL` failed | 1 passed |
| 3 | 3-upload | New project + PDF upload → card renders | PASS | Removed post-upload `refresh()` → card `element(s) not found` | 1 passed |
| 4 | 4-audit-run | הפעילי את התוכנה → analyzing → הושלם (real engine) | PASS | Sabotaged run_audit job (exit 2) → `Expected "complete", Received "failed"` | 1 passed (1.6m) |
| 5 | 5-findings | 3 sections render + drawer opens | PASS | Removed the format section from FindingsView → `element(s) not found` | 1 passed |
| 6 | 6-report | הפיקי דו״ח → success banner | PASS | Sabotaged --render-only (exit 2) → success banner never appeared | 1 passed |

Tests that couldn't be written: none of the six scoped flows was blocked.

**Red-green byproduct — a real test bug caught and fixed:** spec 4 originally
asserted `data-status == "complete"` directly and PASSED against a sabotaged
engine in 2.5s — the seed ships the pilot as status=complete, so the assert
raced the click. Fixed to require the `analyzing` transition first, then
completion of that run.

### Findings for Gate 3/4 (not fixed in Phase 2)

- **F-1 · FIXED (fix/f1-seed-findings, 2026-07-23)** — (b) was fixed by
  round-1 item 6 (friendly Hebrew empty state on the exact 409 signature);
  (a) fixed at the seed layer: `_discover_submissions` now stages
  `findings.json` from the bundled audit_results on insert AND heals
  pre-existing complete rows whose findings are unrecorded or missing on
  disk. Fresh install renders findings immediately; the 409 empty-state
  contract stays pinned by a route-interception test. Original finding:
  the seed ships `audit_outputs`
  (`has_audit_results=true`, report generation works) but NOT `findings.json`,
  so `GET /submissions/1/findings` 409s until an engine run — and the UI
  surfaces the raw English error string ("Error: GET /submissions/1/findings →
  HTTP 409: …"). Two sub-issues: (a) seed inconsistency, (b) raw technical
  English leaked to Ellen (violates the Hebrew-only rule).
- **F-2 · dev-mode render writes into the repo** — the render job's legacy
  positional path writes `audit_outputs/` at the REPO root in dev (frozen
  Windows uses the data dir). Dev-only annoyance; noted.
- **F-3 · sidecar teardown noise** — `sqlcipher3 ProgrammingError: SQLite
  objects created in a thread can only be used in that same thread` in sidecar
  logs during engine runs (non-fatal, worker-thread connection cleanup).

## Phase 2 UPGRADED — permanent 5-layer suite (Gate 2, 2026-07-23)

Prereq honored: fix/first-look-round1 merged to main (bd7d3d5) and this
branch rebased onto it. CI: `.github/workflows/qa-suite.yml` runs Layer-0
gates (ubuntu, pytest) + the full Playwright suite with screenshot artifacts
on every push/PR to main.

### Inventory (17/17 PASS locally; specs 4+5 skip honestly on CI - the 100MB
pilot PDF is not committed, so real-audit flows run locally only)

- **Layer 0a** em-dash gate `tests/test_no_emdash.py` - PASS. Self-test:
  planted `—` in App.tsx → gate failed; removed → passed.
- **Layer 0b** jargon lexicon `qa/jargon-lexicon.txt` + `tests/test_jargon_lexicon.py`
  (+ whitelist `qa/jargon-whitelist.txt`) - PASS. On first run it caught 4 REAL
  violations, all fixed: EngineStatus worker/MAX_CONCURRENT + subprocess/ADR
  explainers → plain Hebrew; stderr label → פרטים טכניים; run-engine tooltip
  'אין סכמה' → plain wording; Diagnostics 'סכמת פרויקט' label + '(sidecar)'
  suffix; cad_compliance 'בסכמה' finding note → 'בנתוני התב"ע'. Self-test:
  planted 'סכמה' → failed; removed → passed.
- **Layer 1a/1b** `00-layer1-states.spec.ts` (6 tests) - dashboard seeded
  render + pill emphasis; findings friendly empty state; CAD scan disabled +
  hint; comments gated pre-audit; run-engine disabled without schema data;
  guidelines+settings load. All PASS.
- **Layer 1c** DOM-leakage afterEach (`fixtures.ts`) wired into EVERY spec -
  markers: HTTP 4/5, "GET /", "POST /", "PATCH /", '"detail"', "→ HTTP".
  Self-test: planted raw HTTP text into the home title → dashboard test
  failed with "raw API text leaked"; removed → passed.
- **Layer 2** `01-layer2-viewports.spec.ts` - 1024x700 + 1280x800 across
  home/overview/submissions/findings/cad/guidelines/settings: no horizontal
  overflow, no clipped button labels, sidebar footer in viewport. PASS.
  Self-test: planted max-width:40px on action buttons → clipped-label
  assertion failed; removed → passed.
- **Layer 3a** `02-layer3-screenshots.spec.ts` - 10 screens x 2 viewports,
  stable filenames under screenshots/, uploaded as CI artifacts. PASS.
- **Layer 3b** codified judgment - dashboard counter emphasis (nonzero =
  stage color, zero = ps-zero muted) asserted in layer1 dashboard test.
- **F1-F6** flows - F1 guidelines edit+history (+ NEW export-pdf download
  assertion, red-green: broke the export URL → download never fired → red;
  restored → green), F2 create, F3 upload, F4 audit (הושלם), F5 findings
  drawer, F6 report banner. Red-green proofs for F2-F6 recorded in the
  earlier Phase-2 section; ordering fixed so layer specs run before flows
  mutate the seed (screenshots capture pristine state).

### CI proof (run 30001507704 on 8ea9fb4, PR #16)
- layer0-gates job: 3 passed (em-dash x2 + jargon).
- ui-suite job: **15 passed, 2 skipped** (specs 4+5 skip on CI - the 100MB
  pilot PDF is local-only; spec 6 report-render now RUNS on CI after
  committing the small pilot schema/metadata/overlay JSONs).
- Screenshot artifacts uploaded (qa-suite-screenshots, 10 screens x 2
  viewports).
- First CI run also caught F-4 (see findings): the dev render path resolves
  repo-root projects/ files - fixed for CI by committing them; the underlying
  path coupling remains backlog B-4.

### Untestable in the split model (honest list)
- Tauri shell / WebView2 packaging behavior (window creation, sidecar spawn
  wiring, installer layout) - covered only by the 49 API probes + Layer 4
  manual checklist.
- Native OS dialogs (file-picker interactions beyond setInputFiles, shell
  open/reveal of generated files).
- Real-audit flows on CI (pilot PDF not committed) - run locally.

## Layer 4 - packaged-app manual checklist (placeholder)

10-minute pre-release walkthrough on the packaged Windows app. CONTENT TO BE
DRAFTED BY LIOR AT RELEASE TIME. Slots: install/over-install, first boot,
guidelines edit→audit→report cycle, one upload, findings + report open,
window resize sanity, uninstall-data-survival.

## Layer 5 - standing process rules

1. **Every FLAG / AMBIGUOUS in any agent report becomes a numbered backlog
   item in this file.** No verbal-only caveats.
2. The jargon lexicon grows on every new finding (see qa/jargon-lexicon.txt).

### Backlog (from prior FLAG/AMBIGUOUS items)

**Cleanup sweep (chore/backlog-cleanup, 2026-07-24):** B-7 (test
expectations updated to the deliberate not_submitted/parking-transparency
behavior), B-8 (WAL/SHM untracked + global ignore), B-9 (frozen
SEED_FROZEN_AT timestamp on seed-discovered submissions - dates in UI are
now deterministic), B-10 (nsis dir cleaned pre-build + upload glob scoped
to APP_VERSION + release-cleanup filter generalized past v0.1.0), B-4/F-2
(render PDF output untracked; audit_outputs/*/ ignore now actually keeps
git status clean - note the dev render still READS inputs from the repo
root, the F-4 coupling, unchanged), B-5/F-3 (check_same_thread=False on
the sqlite connect - pool teardown may close idle connections cross-thread,
which is safe; the noisy ProgrammingError is gone at the source).
Still open by nature: B-1 (needs a manual Windows click), B-2 (needs real
architect-response data), B-3 (product decision), B-6 (external WebView2
fix).

- B-1 (AMBIGUOUS, UI audit 2026-07-22): "צפי בתכנון זמין ↗" mavat link relies
  on the Tauri opener capability - verify one manual click on Windows.
- B-2 (AMBIGUOUS, UI audit 2026-07-22): comparison badge "X/Y תוקנו" not yet
  observed populated end-to-end on real architect-response data.
- B-3 (PARTIAL, UI audit 2026-07-22): Anthropic key card removed from UI, but
  the /settings backend still stores a key nothing consumes - decide drop/use.
- B-4 (F-2): dev-mode render writes into the repo's audit_outputs/ instead of
  the data dir.
- B-5 (F-3): sqlcipher cross-thread teardown noise in sidecar logs during
  engine runs (non-fatal).
- B-6: WebView2-150 attach block (Phase 1) - revisit when a new runner image
  or WebView2 fix ships; the harness pieces (tauri-driver probe steps) remain
  on this branch's workflow for a quick retest.
- B-7 (Phase 3, 2026-07-23, dev-only): 3 pytest failures in
  tests/test_content_compliance_determinism.py (unit_count_missing_data,
  parking_deferred_when_status_is_deferred, no_api_key_yields_unevaluable) -
  engine determinism expectations without an API key; do not block releases.
- B-8 (Phase 3, 2026-07-23, dev-only): tests/ui-dev/.qa-ui-data/platform.db-shm
  and .db-wal were accidentally committed in PR #17; the test data dir is
  wiped each run so they churn git status on every suite run. Remove from the
  index + gitignore.
- B-10 (release v0.1.1, 2026-07-23): the release-upload glob
  ("Planning Platform*x64-setup.exe") also matched the previous version's
  exe restored from the actions cache, attaching a stale 0.1.0 asset to the
  v0.1.1 release (removed manually). Pin the glob to the current version
  from tauri.conf.json or clean bundle/nsis before building.
- B-9 (Phase 3, 2026-07-23, dev-only): Layer-3 screenshots contain upload
  timestamps, so submissions/overview screenshots churn on every fresh-seed
  run even with no UI change. Consider masking timestamps at capture time.

## Phase 3 — full systematic run (2026-07-23, post F-1 fix, main 6c4fea3)

Fresh wipe+seed on main. Results: pytest 103 passed / 3 failed (B-7, known
dev-only); ui-dev 18/18; ui-fixes 4/4; layer-0 gates 3/3; frontend build +
tsc clean; real engine audit on the pilot completed inside spec 4 (1.6m).
Zero blocks-Ellen failures. Screenshot refresh committed (findings tab now
renders findings on fresh seed - the F-1 truth change); B-7/B-8/B-9 logged,
not fixed, per triage policy.
