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
| 2 — suite | not started | | |
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

**Phase-2 harness style: undecided** — pending the one un-exhausted probe.

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
