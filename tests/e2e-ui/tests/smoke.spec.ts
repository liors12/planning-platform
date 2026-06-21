// Flows 1–4 of the UI smoke gate: wipe → install/launch → verify seeded
// state → generate report. Drives the REAL packaged Windows app via
// WebView2's CDP endpoint. See README.md for the why.
//
// What this catches that backend-CI cannot:
//   - Buttons missing from the rendered UI (today's "report buttons
//     vanished after re-upload" class)
//   - target="_blank" failing in WebView2 (today's "open report" dead link)
//   - Rendered Hebrew labels mis-bound to wrong handlers
//   - Sidecar bootstrap producing the wrong initial state on first launch
//
// What it does NOT catch — see README.md.

import { test, expect, chromium, type Browser, type Page } from "@playwright/test";
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import type { ChildProcess } from "node:child_process";
import {
  createPerRunDataDir,
  createUserDataFolder,
  freeTcpPort,
  installedExePath,
  killApp,
  launchApp,
  logInstallDirContents,
  pickTauriPage,
  waitForCdp,
  waitForSidecar,
  wipePerRunDataDir,
  wipeUserDataFolder,
} from "./helpers";

// The seeded pilot project + submission. Must match
// app/sidecar/seed/* — if those change, update here.
const PILOT_TAVA = "407-1048248";
const PILOT_SEEDED_VERSION = "v24.3";

let appProcess: ChildProcess | null = null;
let browser: Browser | null = null;
let page: Page | null = null;
// Per-run isolation state — all filled in inside the test, cleaned up
// in afterAll regardless of pass/fail.
let cdpPort: number | null = null;
let userDataFolder: string | null = null;
let platformDataDir: string | null = null;

test.beforeAll(async () => {
  // Sanity: skip the whole suite on non-Windows so a developer running
  // `npm test` on macOS gets a clear "this is Windows-only" rather than
  // a confusing `LOCALAPPDATA not set` ten frames deep.
  if (process.platform !== "win32") {
    test.skip(true, "UI smoke gate only runs on Windows (real WebView2)");
  }
  // Diagnostic listing first — proves what's actually on disk, regardless
  // of whether the exe-discovery below succeeds.
  logInstallDirContents();
  installedExePath(); // throws with a useful listing if no shell exe found
});

test.afterAll(async () => {
  // Teardown order matters: close CDP first (so Playwright doesn't log
  // noisy disconnect errors), then force-kill the app + sidecar tree +
  // any orphan msedge.exe holding the WebView2 user data folder open,
  // THEN delete both per-run tmpdirs. Each step is best-effort and
  // never throws, so a single failed teardown doesn't mask the real
  // test result.
  //
  // P3 note: wipePerRunDataDir targets a tmpdir we created — the
  // install folder at %LOCALAPPDATA%\Planning Platform\ is never
  // touched here, even on failure.
  try { if (browser) await browser.close(); } catch { /* ignore */ }
  killApp(appProcess);
  wipeUserDataFolder(userDataFolder);
  wipePerRunDataDir(platformDataDir);
  appProcess = null;
  userDataFolder = null;
  platformDataDir = null;
  cdpPort = null;
});

test("flow 1–4: wipe → launch → seeded state → generate report", async () => {
  // ── 1. FRESH STATE (per-run tmpdir, install never touched) ──────────
  // P3: instead of "wipe data in place" (which risked the install
  // folder, since NSIS currentUser puts binaries in the same dir as
  // default data), we create a fresh tmpdir and pass it as
  // PLATFORM_DATA_DIR. The sidecar honors that env var (config.py:68)
  // and writes its entire data tree there. Fresh by construction —
  // no wipe needed, no install-dir surgery, no risk of corrupting
  // a real install on a developer's machine.
  cdpPort = await freeTcpPort();
  userDataFolder = createUserDataFolder();
  platformDataDir = createPerRunDataDir();
  process.stdout.write(
    `[smoke] launch with cdpPort=${cdpPort} userDataFolder=${userDataFolder} ` +
    `platformDataDir=${platformDataDir}\n`
  );

  // ── 2. LAUNCH ───────────────────────────────────────────────────────
  appProcess = launchApp(cdpPort, userDataFolder, platformDataDir);
  await waitForSidecar(30_000);
  const wsUrl = await waitForCdp(cdpPort, 30_000);
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${cdpPort}`);
  // P2: pick the Tauri main window page deterministically rather than
  // taking pages()[0]. On a slow boot the first target is often
  // about:blank, and clicks against it silently no-op.
  page = await pickTauriPage(browser, 15_000);
  // Avoid unused-var lint
  expect(wsUrl).toMatch(/^ws:/);

  // ── P1: deterministic app-ready handshake ──────────────────────────
  // This is the FIRST UI assertion and runs before any click. The
  // app-ready marker fires only when /health 200 + /projects loaded
  // + at least one project rendered — proving the seeded data is on
  // screen, not just that some fetch returned 200. Today's race-prone
  // failure mode ("project loaded but submission didn't") happened
  // because clicks fired before the UI had reconciled with the
  // backend; this gate eliminates that class of flake.
  await expect(
    page.getByTestId("app-ready")
  ).toBeVisible({ timeout: 30_000 });

  // After app-ready, the home-project-link is by construction present
  // (app-ready gates on recent.length > 0). This is a redundancy check
  // — if it ever fails, app-ready's invariant has drifted.
  await expect(
    page.getByTestId(`home-project-link-${PILOT_TAVA}`)
  ).toBeVisible();

  // ── Navigate into the project ──────────────────────────────────────
  await page.getByTestId(`home-project-link-${PILOT_TAVA}`).click();

  // Switch to the submissions tab — that's where flows 3-4 happen.
  // The tab label "הגשות" is plain text; if the testid story needs to
  // grow here later we'll add tab testids in a follow-up.
  await page.getByRole("button", { name: "הגשות" }).click();

  // ── 3. VERIFY SEEDED STATE ──────────────────────────────────────────
  // The seed populates submission v24.3 with audit_results on disk, so
  // has_audit_results=true → both report buttons should be present and
  // ENABLED. This is the exact assertion that would have caught today's
  // "buttons vanished after re-upload" bug.
  const card = page.getByTestId(`submission-card-${PILOT_SEEDED_VERSION}`);
  await expect(card).toBeVisible({ timeout: 15_000 });

  const pdfBtn = page.getByTestId(`generate-report-pdf-${PILOT_SEEDED_VERSION}`);
  const xlsxBtn = page.getByTestId(`generate-report-xlsx-${PILOT_SEEDED_VERSION}`);
  await expect(pdfBtn).toBeVisible();
  await expect(pdfBtn).toBeEnabled();
  await expect(xlsxBtn).toBeVisible();
  await expect(xlsxBtn).toBeEnabled();

  // ── 4. GENERATE REPORT — PDF ────────────────────────────────────────
  // Click and watch for working → success transitions. Then assert the
  // PDF actually exists on disk where the sidecar said it would.
  await pdfBtn.click();
  await expect(
    page.getByTestId("output-banner-working-pdf")
  ).toBeVisible({ timeout: 5_000 });
  await expect(
    page.getByTestId("output-banner-success-pdf")
  ).toBeVisible({ timeout: 60_000 });

  // PDF must land in <platformDataDir>/audit_outputs/<tava>/v<ver>/audit_report_<ver>.pdf
  // (PLATFORM_DATA_DIR redirected the data tree to our tmpdir.)
  const verBare = PILOT_SEEDED_VERSION.replace(/^v/, "");
  const pdfPath = join(
    platformDataDir!, "audit_outputs", PILOT_TAVA, PILOT_SEEDED_VERSION,
    `audit_report_${verBare}.pdf`
  );
  expect(existsSync(pdfPath)).toBe(true);

  // ── 4. GENERATE REPORT — EXCEL ──────────────────────────────────────
  await xlsxBtn.click();
  await expect(
    page.getByTestId("output-banner-working-xlsx")
  ).toBeVisible({ timeout: 5_000 });
  await expect(
    page.getByTestId("output-banner-success-xlsx")
  ).toBeVisible({ timeout: 60_000 });

  // Excel filename embeds Hebrew + version — verify by listing the dir
  // rather than constructing the bidi string in JS (where escape
  // semantics get fiddly).
  const outDir = join(platformDataDir!, "audit_outputs", PILOT_TAVA, PILOT_SEEDED_VERSION);
  const entries = readdirSync(outDir);
  expect(
    entries.some((e) => e.endsWith(`_v${verBare}.xlsx`)),
    `Expected an .xlsx file ending with _v${verBare}.xlsx in ${outDir}. Found: ${entries.join(", ")}`
  ).toBe(true);
});
