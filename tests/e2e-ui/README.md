# UI smoke gate — real WebView2 on Windows

This suite drives the **packaged** Planning Platform Windows binary (the
NSIS-installed `.exe`) over WebView2's CDP debug port, asserts the user-
visible flow Ellen runs, and saves screenshots when anything fails. It
exists to close the gap that bit us today: backend CI was green but the
real UI in WebView2 behaved wrong (dead `target="_blank"` links, buttons
that vanished after re-upload, locked tabs from stuck status labels).

## Scope (Phase 1 — flows 1–4 only)

1. **Wipe data** under `%LOCALAPPDATA%\Planning Platform` so every run
   starts from a true fresh-data state. The install and the data dir
   share that folder (Tauri NSIS currentUser mode), so we wipe only the
   known data names — DB files, `projects/`, `audit_outputs/`, `logs/`,
   `jobs/` — and leave binaries in place. Same effect on the running
   app: it boots as if first-launched, seed re-populates the pilot.
2. **Launch** the installed `.exe` with `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=
   --remote-debugging-port=9223` (the env var is honored by the WebView2
   loader itself — no Tauri config change; production builds never set
   it, so the debug port stays closed in shipped installers). Wait for
   sidecar `/health` and for WebView2's CDP endpoint to be reachable.
3. **Verify seeded state** — the pilot project (`407-1048248`) and its
   seeded submission (`v24.3`) appear in the UI, and both report buttons
   (`הפיקי דו״ח`, `הפיקי אקסל`) render and are enabled.
4. **Generate report** — click each button, watch for the working → success
   banner transition, then assert the PDF / `.xlsx` actually exists on
   disk at the expected path under `audit_outputs/`.

Flows 5–8 (comments tab, delete-version, re-upload state, broken-button
guard) are intentionally deferred until 1–4 is proven reliable across
several runs.

## Why CDP and not `tauri-driver`

`tauri-driver` 2.x requires an exact `msedgedriver` ↔ Edge version match;
on `windows-latest` Edge auto-updates, so the pin drifts and the driver
hangs silently. CDP is the underlying mechanism `tauri-driver` uses
anyway, so going direct removes one layer of pinning fragility.

## What this suite CANNOT catch

Honest about the limits, so we don't over-trust the gate:

- **PDF visual fidelity.** We assert the file exists, not that the
  rendering looks right. Use the existing visual regression checks for
  that.
- **Perceived latency.** A 30-second render still passes; the spec only
  asks "does it eventually succeed."
- **First-install-on-fresh-machine effects.** Windows SmartScreen and
  Defender quarantine are bypassed by the `/S` installer; a real first
  user might see prompts we never trigger.
- **NSIS installer UX.** Silent install skips every dialog.
- **Race conditions that only appear under real-user interaction speeds.**

## Running locally

```powershell
# Prereq: NSIS installer already run with /S so the app is installed.
cd tests\e2e-ui
npm ci
npm test
```

The suite is Windows-only — it `test.skip`s on macOS/Linux with a clear
message rather than producing a confusing error.

## Status

**Hard gate** alongside the existing backend smoke. A UI regression
blocks the installer from publishing. Promoted from warn-only after
12+ green runs across the P1–P5 hardening pass with zero flakes (the
one transient red was a real test-scaffolding bug, not a flake).
