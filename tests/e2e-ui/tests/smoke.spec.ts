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
  assertDataWiped,
  dataDir,
  installedExePath,
  killApp,
  launchApp,
  logInstallDirContents,
  waitForCdp,
  waitForSidecar,
  wipeData,
} from "./helpers";

// The seeded pilot project + submission. Must match
// app/sidecar/seed/* — if those change, update here.
const PILOT_TAVA = "407-1048248";
const PILOT_SEEDED_VERSION = "v24.3";

// Arbitrary high port that's almost never in use on a GH runner.
const CDP_PORT = 9223;

let appProcess: ChildProcess | null = null;
let browser: Browser | null = null;
let page: Page | null = null;

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
  try { if (browser) await browser.close(); } catch { /* ignore */ }
  killApp(appProcess);
  appProcess = null;
});

test("flow 1–4: wipe → launch → seeded state → generate report", async () => {
  // ── 1. WIPE (data only — install stays put) ─────────────────────────
  // The spec said "wipe the whole folder", but Tauri NSIS currentUser
  // mode installs the app into the SAME folder as the sidecar's data dir
  // (%LOCALAPPDATA%\Planning Platform\). Wiping everything would brick
  // the install. wipeData() removes only the known data names — DB
  // files, projects/, audit_outputs/, logs/, jobs/ — leaving binaries.
  wipeData();
  assertDataWiped();

  // ── 2. LAUNCH ───────────────────────────────────────────────────────
  // App starts cold (no data dir), sidecar boots, seed re-populates the
  // pilot project. Then WebView2 must expose its CDP endpoint so we can
  // attach Playwright.
  appProcess = launchApp(CDP_PORT);
  await waitForSidecar(30_000);
  const wsUrl = await waitForCdp(CDP_PORT, 30_000);
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${CDP_PORT}`);
  const contexts = browser.contexts();
  if (contexts.length === 0) throw new Error("CDP returned no browser contexts");
  const pages = contexts[0].pages();
  page = pages.length > 0 ? pages[0] : await contexts[0].newPage();
  // Avoid unused-var lint
  expect(wsUrl).toMatch(/^ws:/);

  // Wait for the home list to populate. The seed runs inside the sidecar
  // startup hook; by the time /health answers, the seed should be done,
  // but the React app still needs to fetch /projects and render. We
  // assert on the testid we added rather than text to dodge RTL issues.
  await expect(
    page.getByTestId(`home-project-link-${PILOT_TAVA}`)
  ).toBeVisible({ timeout: 15_000 });

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

  // PDF must land in <data_dir>/audit_outputs/<tava>/v<ver>/audit_report_<ver>.pdf
  const verBare = PILOT_SEEDED_VERSION.replace(/^v/, "");
  const pdfPath = join(
    dataDir(), "audit_outputs", PILOT_TAVA, PILOT_SEEDED_VERSION,
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
  const outDir = join(dataDir(), "audit_outputs", PILOT_TAVA, PILOT_SEEDED_VERSION);
  const entries = readdirSync(outDir);
  expect(
    entries.some((e) => e.endsWith(`_v${verBare}.xlsx`)),
    `Expected an .xlsx file ending with _v${verBare}.xlsx in ${outDir}. Found: ${entries.join(", ")}`
  ).toBe(true);
});
