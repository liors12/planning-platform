# Phase 2b — Completion + Sign-off

**Status:** ✅ Complete — Step 7 (8/8) + Step 8 (4/4) green, engine baseline byte-identical to v8j
**Spec reference:** [docs/product_spec_v0.1.md § 5 (Module B) + § 10 (Phase 2)](./product_spec_v0.1.md)
**Date completed:** 2026-05-19
**Effort vs. estimate:** ~12 hrs across two sessions (Step 7 implementation + Step 8 filters + four production-hygiene follow-ups). Within the spec's Phase 2b budget.

---

## Acceptance criteria — 12/12 ✅

Verified by `tests/e2e/step8_filters.spec.ts` (Step 8) and
`/tmp/verify_step7.py` (Step 7, ad-hoc Playwright). All checks driven from the
agent directly via headed Chromium; no Cowork dispatch.

### Step 7 — side-by-side findings & PDF (8/8)

| # | Criterion | Evidence |
|---|---|---|
| 1 | Home page renders without `TypeError: Load failed` | `01_home.png` clean — no red error block |
| 2 | Both projects in sidebar under "פעילים" | "פרויקט בדיקה שני" (999-0000000) + "מתחם הטייסים-ההסתדרות" (407-1048248) |
| 3 | Both projects in "פרויקטים אחרונים" card | Same two with full meta (תב"ע, "הגשה אחת", "עודכן 2026-05-19") |
| 4 | Project workspace opens, tab switching works | סקירה → ממצאים navigation observed |
| 5 | Rule names render in Hebrew, no `CONTENT_*` / `FORMAT_*` leaks | Meta `english_code_leaks: []`; samples: "נספח חומריות", "פתחי ממ\"ד פונים לחזיתות משניות", "ללא חיפוי אבן טבעית", "שיפוע ניקוז קרקע ≥ 1%" |
| 6 | Hebrew text wraps as whole words, not letter-by-letter vertically | `04`/`05` screenshots — every row wraps as words; no vertical letter columns |
| 7 | Page-pill click jumps PDF on the left | `04_after_page_pill.png` — clicked "עמ' 30", PDF shows "עמוד 30 מתוך 63" with the page-30 "KIKA BRAZ" floor-plan rendered |
| 8 | Expand button opens the drawer | `05_drawer_open.png` — first row of "בדיקה רב-תחומית" expanded with "תיאור ויזואלי מההגשה" block visible; `aria-expanded="true"` |

### Step 8 — verdict pills as filter toggles (4/4)

| # | Criterion | Test |
|---|---|---|
| 1 | Default state — passing/N/A rows hidden, problem rows shown | `step8_filters.spec.ts › 1. default state` |
| 2 | Toggle תקין on → passing rows appear; click again → gone | `step8_filters.spec.ts › 2. toggle` |
| 3 | Persistence — toggle, reload, state restored from localStorage | `step8_filters.spec.ts › 3. persistence` |
| 4 | Empty state per section — "אין סעיפים להצגה. הפעל מסננים בכותרת." | `step8_filters.spec.ts › 4. empty state` |

```
Running 4 tests using 1 worker
  ✓  1. default state — passing rows are hidden, problem rows are shown (4.4s)
  ✓  2. toggle — clicking תקין shows passing rows, clicking again hides them (4.6s)
  ✓  3. persistence — toggle תקין, reload, state restored (8.7s)
  ✓  4. empty state — turn off every pill in content section, see the Hebrew message (4.4s)
  4 passed (22.5s)
```

### Engine baseline byte-identity ✅

```
8c5627f9b52a66d531b1661b6f419e55ee56e115028faa1fa36bf309e8b2fef8
  tests/regression/v8j_baseline_v24.3.json
  audit_outputs/407-1048248/v24.3/audit_results.json (pre-fix)
  audit_outputs/407-1048248/v24.3/audit_results.json (post-fix re-run)
```

Verdict counts from the post-fix re-run:
- content: `15 pass / 27 not_submitted / 11 requires_review / 26 not_applicable` (79 total)
- disciplines: `9 pass / 8 fail / 16 requires_review` (33 total)

Exact match with the baseline declared in `engine_output_contract.md §"Verdict counts"`.

---

## Features delivered

| Feature | Files | Notes |
|---|---|---|
| Side-by-side findings + PDF (split pane) | `SplitPane.tsx`, `PdfViewer.tsx`, `FindingsView.tsx` | Splitter position persisted per project at `splitter:project_{id}` |
| Findings list with collapsible drawer | `FindingsView.tsx` (`FindingRow`) | Per-row `aria-expanded`, drawer-block layout for visual/note/remediation/page-refs |
| Click-to-page: row click + page-pill click | `FindingRow.onRowClick` + `.page-pill` button | Row click defaults to `pages[0]` if present; page-pill click stops propagation and jumps to that exact page |
| `pdfTarget` lifted to `ProjectWorkspace` with `{page, nonce}` | `ProjectWorkspace.tsx` | Nonce bumps on every click so re-clicking the SAME page still re-jumps |
| Hebrew rule names propagated end-to-end | `compliance_engine/content_compliance_checker.py`, `format_rules_checker.py` | `rule_name_he` now populated in 6 result constructors (was missing in 3 of them) |
| Word-break fix (Hebrew wrapping) | `FindingsView.tsx`, `styles.css` (`.finding-row-name`, `.finding-row-title`) | Moved page-pills below brief instead of competing with title column; explicit `word-break: normal; overflow-wrap: break-word` |
| Verdict pills as filter toggles | `FindingsView.tsx`, `styles.css` | Per-section, per-project, persisted at `filters:project_{id}` |
| Distinct empty states | `FindingsView.tsx` (`noRulesAtAll` vs `allFiltered`) | "אין סעיפים" (engine returned none) vs "אין סעיפים להצגה. הפעל מסננים בכותרת." (user filtered them out) |
| `fetchOrThrow` retry+backoff layer | `app/frontend/src/api.ts` | 3 retries · 200/500/1500ms · transparent under the existing `listProjects`/`getProject`/etc API |
| `setErr(null)`-on-success cleanup | `Sidebar.tsx`, `App.tsx`, `ProjectWorkspace.tsx` | Stale error banners no longer linger next to data that loaded on a retry |
| DevTools overlay (Cmd+Shift+D) | `DebugOverlay.tsx` | Raw findings JSON dump for live debugging without DevTools |
| Composite React key (per-plot rules) | `FindingsView.tsx` `${rule_code}::${ta_shetach_id ?? idx}` | Eliminates the "same key" warning when per-plot rules emit one row per תא שטח |

---

## Bug fixes during phase

### A — Stale error sticks next to fresh data

**Symptom:** `Sidebar`, `Home`, and `ProjectWorkspace` each kept the
last `TypeError: Load failed` in their local `err` state, so a successful
refetch that landed via the retry layer left the red banner stuck above
the newly-rendered project list.

**Fix:** every `.then(setX)` paired with `.catch(setErr)` now calls
`setErr(null)` in the success path. Three call sites updated.

**Why a band-aid alone wasn't enough:** even with the error cleared on
success, the *first* failure still flashed visibly. Pairing with the
retry+backoff layer (Bug B) cuts the failure window from a hard-fail
visible flash to a sub-2s recoverable transient.

### B — Startup race: WebView fetches /projects before sidecar binds 17321

**Symptom:** opening the wrapper would flash `TypeError: Load failed`
in the sidebar + recent-projects card. Sometimes the data eventually
loaded (state stuck per Bug A); sometimes the error persisted because
the failed `useEffect` never re-fired.

**Root cause confirmed via diagnostic:** `app/tauri/src/lib.rs`
`setup()` calls `spawn_sidecar()` synchronously then returns. The
WebView loads `devUrl` in parallel. React fires `listProjects()`
within ms of WebView load. Python sidecar takes 1–3 s to import
FastAPI + bind the port. First fetch lands on a closed port.

**Fix (Phase 2b band-aid):** wrapped every `fetch()` in `api.ts` in
`fetchOrThrow(url, init)` — 3 retries with backoff 200/500/1500ms (~2.2s
total wait before giving up). Transport failures retry; HTTP 4xx/5xx
do not retry (those flow through `jsonOrThrow`); `AbortError`
short-circuits. Error message includes URL + first stack frame + retry
count so future failures are debuggable from the UI alone.

**Phase 5 production fix (deferred):** `app/tauri/src/lib.rs` will gate
`window.show()` on `/health 200` so the WebView cannot start loading
before the sidecar is ready. See Task #14.

### #18 — React key collision on per-plot rules

**Symptom:** Playwright console capture during Step 7 verification
logged `Encountered two children with the same key, CONTENT_UNIT_COUNT`
three times. The UI still rendered, but React could drop/duplicate
row identity across re-renders.

**Diagnosis:** `content_rules.json` defines `CONTENT_UNIT_COUNT` once,
with `"scope": "per_ta_shetach"`. The engine correctly emits **one
result per plot** for this rule (and 6 others — full list:
`CONTENT_BUILDING_AREA_MAIN/SERVICE_ABOVE/SERVICE_BELOW`,
`CONTENT_BUILDING_HEIGHT`, `CONTENT_PARKING_RATIO`,
`CONTENT_SETBACKS`, `CONTENT_UNIT_COUNT`). For a project with 11
plots, the content array contains 11 entries with the same
`rule_code` distinguished by `ta_shetach_id`. The frontend's
`key={r.rule_code}` collided.

**Fix:** composite React key in `FindingsView.tsx`:

```tsx
key={`${r.rule_code}::${r.ta_shetach_id ?? idx}`}
```

Engine output unchanged (sha256 still `8c5627f9…`). Source-of-truth
dedup confirmed: `jq '[.rules[].rule_code] | group_by(.) | map(select(length>1))'`
returns `[]` for both `content_rules.json` and
`submission_format_rules.json`.

### #18 invariant — `rule_code` MUST NOT contain `::`

The composite key above relies on `::` being impossible inside any
`rule_code`. Verified at the source rule files (all rule_codes match
`^[A-Z][A-Z0-9_]*$`). Documented as a contract in
`docs/architecture/engine_output_contract.md §"rule_code invariants"`
with three properties:

1. Uniqueness within a rules-config file (enforced by the jq one-liner
   above).
2. NOT unique within an engine-output array (per-plot rules emit N
   results sharing the same `rule_code`).
3. `::` is a reserved separator that must never appear in
   `rule_code`. If a future rule introduces a non-matching character,
   audit every composite-key consumer (start with
   `grep -rn '\${.*rule_code.*}::' app/frontend/`) and pick a new
   separator.

---

## Infrastructure & dev workflow

### `.app` wrapper around the Tauri dev binary

`cargo tauri dev` produces a bare Mach-O at
`target/debug/planning-platform` with no `Info.plist` — therefore no
bundle identifier — therefore no way for external tools (Cowork's
`request_access`, AppleScript by identifier, etc.) to find the running
process. The fix is a thin `.app` wrapper at
`app/tauri/target/debug/Planning Platform Dev.app/` with:

- `Contents/MacOS/planning-platform` → **symlink** to `target/debug/planning-platform` (auto-tracks `cargo build` rebuilds)
- `Contents/Info.plist` declaring `CFBundleIdentifier = co.nessziona.planning-platform.dev`

Identifier rationale: the `.dev` suffix coexists with a future signed
production bundle declared in `tauri.conf.json` as
`co.nessziona.planning-platform`. Two identifiers, two LaunchServices
registrations, zero shadowing.

Detailed walkthrough in `docs/dev_setup.md`.

### `scripts/prep_cowork_session.sh`

One-shot script that brings up a clean dev session. After Phase 2b
additions, it also runs a frontend-fetch smoke test (`GET /projects`
with `Origin: tauri://localhost` → expect a JSON array) so a CORS /
serialization regression fails the prep at script time rather than at
window-open time. Exit code 6 reserved for that failure.

Curl readiness checks throughout the script and the docs were audited
for missing `--fail` — without it, `curl -sS` returns exit 0 on HTTP
5xx and would mask a sick sidecar. Findings + before/after table in
`docs/known_issues.md` Task #10.

### ATS configuration

The wrapper's `Info.plist` declares:

```xml
<key>NSAppTransportSecurity</key>
<dict>
  <key>NSAllowsArbitraryLoads</key><true/>
  <key>NSAllowsLocalNetworking</key><true/>
</dict>
```

This is **dev-only** and must be replaced with a scoped
`NSExceptionDomains` block before any distributable build. Full
production replacement template in `docs/dev_setup.md §"Production
considerations" §1`.

### Playwright e2e suite — `tests/e2e/`

`tests/e2e/` is now the canonical location for end-to-end UI
verification. New in Phase 2b: `package.json` + `playwright.config.ts`
(targeting Vite at `http://127.0.0.1:1420`) + `step8_filters.spec.ts`
(four scenarios).

**Process change — Playwright is the new standard for checkpoint
verification, NOT Cowork.** Earlier in the session we relied on
dispatching to a Cowork instance with computer-use grants for visual
verification of each checkpoint. That worked but introduced two
problems: (a) round-trip latency between writing code and seeing the
result, and (b) no regression value — Cowork's screenshots aren't
re-runnable in CI. Playwright solves both: the agent runs the same
verification headed, reads the screenshots itself, and the spec stays
in the repo as a regression artefact. Step 8 was the first feature
verified end-to-end this way; Step 7 was retro-verified the same way
via `/tmp/verify_step7.py`. Future checkpoints should add a spec to
`tests/e2e/` rather than dispatching to Cowork.

---

## Tasks deferred

| Task | Title | Owner | Target phase | Blocking? |
|---|---|---|---|---|
| #12 | `prep_cowork_session.sh` wedges on exit (Vite pipe fd leak) | unassigned | Phase 2c hygiene | No — manual `kill -9 <pid>` workaround |
| #13 | Dev wrapper dies on screen lock / sleep / wake | unassigned | Phase 5 (signed `.app` should survive) | No — re-run prep on return |
| #14 | Tauri Rust gates `window.show()` on sidecar `/health 200` | unassigned | Phase 5 production startup | No — Phase 2b retry+backoff masks the race |
| #17 | macOS Screen Recording permission gap for agent `screencapture` | environment / user | host machine config | No — Playwright + Chrome MCP bypass it |
| #19 | Dev-mode console 404 (favicon / source-map) | unassigned | Phase 2c hygiene | No — UI renders normally |

Full root cause + reproduction for each in `docs/known_issues.md`.

---

## Production-grade TODOs before Phase 5

Documented in detail in [docs/dev_setup.md §"Production considerations"](./dev_setup.md#production-considerations). Headlines only:

1. **ATS narrow** — replace `NSAllowsArbitraryLoads=true` with
   `NSExceptionDomains` scoped to `127.0.0.1` + `localhost`.
2. **CSP preserved** — keep `connect-src` in `tauri.conf.json` pinned
   to `http://127.0.0.1:17321`; verify post-build in the shipped HTML.
3. **Sidecar startup gate (#14)** — Rust waits for `/health 200`
   before calling `window.show()`.
4. **Identifier** — production uses `co.nessziona.planning-platform`
   without the `.dev` suffix.

These four must land in the same Phase 5 sprint that produces the
first distributable `.app`. Leaving any of them at dev defaults will
either fail App Store / MDM review or break on Ellen's machine on
first launch.

---

## Next step — Ellen UI review (NOT Phase 3)

Phase 3 (Gemini vision pipeline) **does not start** before we run the
full Phase 2b stack in front of Ellen and capture her UX feedback.
This was the gating decision from earlier in the session: shipping
Module B blind to Ellen risks building Phase 3 on top of a UI
direction she'd want changed.

Concrete steps:

1. Schedule a 60-90 minute session with Ellen at her workstation
   (or via screen-share if remote).
2. Bring up the stack with `scripts/prep_cowork_session.sh` — confirm
   the smoke-test `READY` line includes the right identifier and
   `/projects` array.
3. Walk Ellen through:
   - Home → sidebar → project switching
   - Open "מתחם הטייסים-ההסתדרות"
   - Submissions tab — what's there now, what's planned
   - Findings tab — observe how she uses the filter pills, drawer,
     page-pill jumps. **The filters are the riskiest UX bet** —
     defaults are an educated guess; watch which verdicts she
     enables/disables in practice.
   - PDF viewer split pane — does the default 55/45 work for her? Is
     the zoom granularity right?
5. Record verbatim feedback in `docs/ellen_review_2026-05-XX.md`. Tag
   each item with `nice-to-have` / `before-Phase-3` / `before-Phase-5`.
6. Triage the `before-Phase-3` items into a Phase 2c hygiene round.
7. **Only after the Phase 2c items land** — kick off Phase 3 (Gemini
   vision pipeline).

This sequencing also gives us a clean dataset for Phase 3 work — Ellen
will have actually used Module B on real architect submissions, so the
vision pipeline targets the cases that matter to her, not the cases
we guessed at.

---

## Sign-off

Phase 2b acceptance criteria met (12/12). Engine output byte-identical
to v8j baseline. No new regressions introduced. Five tasks deferred
to backlog with documented workarounds. Production hardening checklist
in place for Phase 5.

Ready to schedule Ellen's review.
