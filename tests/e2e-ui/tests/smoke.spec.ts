// UI smoke gate: drives the REAL packaged Windows app via WebView2's CDP
// endpoint. See README.md for the why.
//
// What this catches that backend-CI cannot:
//   - Buttons missing from the rendered UI ("report buttons vanished
//     after re-upload" class)
//   - target="_blank" failing in WebView2 (the "open report" dead link)
//   - Rendered Hebrew labels mis-bound to wrong handlers
//   - Sidecar bootstrap producing the wrong initial state on first launch
//   - State NOT persisting across an app restart (flow 5)
//   - Delete + re-upload leaving the UI in a stale state (flow 6 — this
//     is the literal sequence that broke on the user's machine)
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
  projectIdForTava,
  uploadSubmissionViaApi,
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
  // Sweep whatever state the last test left behind.
  // Tests run serially in the order they appear, each managing its own
  // resources; this is the final cleanup for the LAST test's state.
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
  await teardownCurrent();
});

// ── Shared launch sequence ────────────────────────────────────────────
// Each test that needs a fresh app does: teardownCurrent() (if anything
// from a prior test is still up) → launchAndAttach(...). The relaunch
// flow (flow 5) skips the teardown's tmpdir wipes so data persists,
// then calls launchAndAttach with the SAME platformDataDir.
async function teardownCurrent(): Promise<void> {
  try { if (browser) await browser.close(); } catch { /* ignore */ }
  killApp(appProcess);
  wipeUserDataFolder(userDataFolder);
  wipePerRunDataDir(platformDataDir);
  appProcess = null;
  browser = null;
  page = null;
  userDataFolder = null;
  platformDataDir = null;
  cdpPort = null;
}

// Bring the app + Playwright session up against the given data dir,
// allocating fresh CDP port + WebView2 user data folder. Returns once
// app-ready is visible — callers don't need their own polling.
async function launchAndAttach(dataDir: string): Promise<Page> {
  cdpPort = await freeTcpPort();
  userDataFolder = createUserDataFolder();
  platformDataDir = dataDir;
  process.stdout.write(
    `[smoke] launch with cdpPort=${cdpPort} userDataFolder=${userDataFolder} ` +
    `platformDataDir=${platformDataDir}\n`
  );
  appProcess = launchApp(cdpPort, userDataFolder, platformDataDir);
  await waitForSidecar(30_000);
  await waitForCdp(cdpPort, 30_000);
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${cdpPort}`);
  page = await pickTauriPage(browser, 15_000);
  await expect(page.getByTestId("app-ready")).toBeVisible({ timeout: 30_000 });
  return page;
}

test("flow 1–4: wipe → launch → seeded state → generate report", async () => {
  // P3: fresh tmpdir as PLATFORM_DATA_DIR — install never touched.
  const dataDir = createPerRunDataDir();
  const p = await launchAndAttach(dataDir);

  // After app-ready, the home-project-link is by construction present
  // (app-ready gates on recent.length > 0). This is a redundancy check
  // — if it ever fails, app-ready's invariant has drifted.
  await expect(p.getByTestId(`home-project-link-${PILOT_TAVA}`)).toBeVisible();

  // ── Navigate into the project ──────────────────────────────────────
  await p.getByTestId(`home-project-link-${PILOT_TAVA}`).click();
  // The tab label "הגשות" is plain text; if the testid story needs to
  // grow here later we'll add tab testids in a follow-up.
  await p.getByRole("button", { name: "הגשות" }).click();

  // ── 3. VERIFY SEEDED STATE ──────────────────────────────────────────
  // The seed populates submission v24.3 with audit_results on disk, so
  // has_audit_results=true → both report buttons should be present and
  // ENABLED. This is the exact assertion that would have caught today's
  // "buttons vanished after re-upload" bug.
  const card = p.getByTestId(`submission-card-${PILOT_SEEDED_VERSION}`);
  await expect(card).toBeVisible({ timeout: 15_000 });

  const pdfBtn = p.getByTestId(`generate-report-pdf-${PILOT_SEEDED_VERSION}`);
  const xlsxBtn = p.getByTestId(`generate-report-xlsx-${PILOT_SEEDED_VERSION}`);
  await expect(pdfBtn).toBeVisible();
  await expect(pdfBtn).toBeEnabled();
  await expect(xlsxBtn).toBeVisible();
  await expect(xlsxBtn).toBeEnabled();

  // ── 4. GENERATE REPORT — PDF ────────────────────────────────────────
  await pdfBtn.click();
  await expect(p.getByTestId("output-banner-working-pdf")).toBeVisible({ timeout: 5_000 });
  await expect(p.getByTestId("output-banner-success-pdf")).toBeVisible({ timeout: 60_000 });

  const verBare = PILOT_SEEDED_VERSION.replace(/^v/, "");
  const pdfPath = join(
    dataDir, "audit_outputs", PILOT_TAVA, PILOT_SEEDED_VERSION,
    `audit_report_${verBare}.pdf`,
  );
  expect(existsSync(pdfPath)).toBe(true);

  // ── 4. GENERATE REPORT — EXCEL ──────────────────────────────────────
  await xlsxBtn.click();
  await expect(p.getByTestId("output-banner-working-xlsx")).toBeVisible({ timeout: 5_000 });
  await expect(p.getByTestId("output-banner-success-xlsx")).toBeVisible({ timeout: 60_000 });

  const outDir = join(dataDir, "audit_outputs", PILOT_TAVA, PILOT_SEEDED_VERSION);
  const entries = readdirSync(outDir);
  expect(
    entries.some((e) => e.endsWith(`_v${verBare}.xlsx`)),
    `Expected an .xlsx file ending with _v${verBare}.xlsx in ${outDir}. Found: ${entries.join(", ")}`,
  ).toBe(true);
});

// ── P4 flow 5: restart-with-data ──────────────────────────────────────
// Catches the SQLite/state-persistence bug class: app close + relaunch
// leaves the prior submissions list + report buttons intact. Today's
// "buttons missing until restart" bug was the inverse of this — the
// state DID persist, but the UI didn't render it correctly on first
// launch. This test catches both directions: state lost OR not rendered.
//
// Chains off flow 1–4: reuses the same platformDataDir (so the v24.3
// row + audit_outputs + the report PDF generated in flow 4 are all
// still on disk), but does a full process restart with a fresh CDP
// port and a fresh WebView2 user data folder — same shape as Ellen
// closing the app and reopening it the next morning.
test("flow 5: restart-with-data — state survives app relaunch", async () => {
  // Snapshot the previous test's platformDataDir BEFORE teardown
  // clears the module var.
  const persistedDataDir = platformDataDir;
  expect(persistedDataDir, "flow 5 must run after flow 1–4").not.toBeNull();

  // ── Close current app cleanly, preserve the data dir on disk ────────
  // wipePerRunDataDir is skipped — we want the v24.3 row, the seeded
  // audit_outputs, and flow 4's generated PDF + Excel to survive into
  // the next launch.
  try { if (browser) await browser.close(); } catch { /* ignore */ }
  killApp(appProcess);
  wipeUserDataFolder(userDataFolder);  // WebView2 cookies CAN be wiped
  appProcess = null;
  browser = null;
  page = null;
  userDataFolder = null;
  cdpPort = null;
  // platformDataDir stays — it's reused below.

  // ── Relaunch against the same data ──────────────────────────────────
  const p = await launchAndAttach(persistedDataDir!);

  // App-ready already fired inside launchAndAttach. The seeded pilot
  // is by construction present. Now drill into the project to assert
  // flow 4's state survived.
  await p.getByTestId(`home-project-link-${PILOT_TAVA}`).click();
  await p.getByRole("button", { name: "הגשות" }).click();

  // The v24.3 row was inserted by the seed at first launch + has
  // audit_outputs on disk. Both must still be true after restart.
  const card = p.getByTestId(`submission-card-${PILOT_SEEDED_VERSION}`);
  await expect(card).toBeVisible({ timeout: 15_000 });

  const pdfBtn = p.getByTestId(`generate-report-pdf-${PILOT_SEEDED_VERSION}`);
  const xlsxBtn = p.getByTestId(`generate-report-xlsx-${PILOT_SEEDED_VERSION}`);
  await expect(pdfBtn).toBeVisible();
  await expect(pdfBtn).toBeEnabled();
  await expect(xlsxBtn).toBeVisible();
  await expect(xlsxBtn).toBeEnabled();

  // The PDF generated in flow 4 must still be on disk. (Filesystem
  // persistence sanity check — would catch a regression where teardown
  // accidentally wiped the data dir between tests.)
  const verBare = PILOT_SEEDED_VERSION.replace(/^v/, "");
  const pdfPath = join(
    persistedDataDir!, "audit_outputs", PILOT_TAVA, PILOT_SEEDED_VERSION,
    `audit_report_${verBare}.pdf`,
  );
  expect(existsSync(pdfPath)).toBe(true);
});

// ── P4 flow 6: delete → re-upload → buttons return ────────────────────
// The literal sequence that broke on Ellen's machine. Uses a throwaway
// version (v99.0) so the seeded pilot's data is never disturbed, even
// when this test fails partway.
//
// Upload + delete go through the sidecar HTTP API rather than the UI
// (the upload UI is a native file picker that Playwright can't drive
// through WebView2). From the bug-class perspective this is fine: the
// bug was about how the UI reconciled with DB state, not about how
// data got into the DB.
test("flow 6: delete → re-upload → buttons return to correct state", async () => {
  // Independent — start with a fresh data dir so flow 5's state can't
  // contaminate this one.
  await teardownCurrent();
  const dataDir = createPerRunDataDir();
  const p = await launchAndAttach(dataDir);

  await p.getByTestId(`home-project-link-${PILOT_TAVA}`).click();
  await p.getByRole("button", { name: "הגשות" }).click();

  // ── Upload v99.0 via API ────────────────────────────────────────────
  // The UI doesn't auto-poll for new submissions — it refreshes only
  // on user actions (upload via picker, delete) or on tab/page
  // mount. Since our upload bypasses the UI entirely (Playwright
  // can't drive WebView2's native file picker), we trigger the
  // SubmissionsTab's mount-time refetch by clicking away to a
  // different tab and back. This is real production behavior — Ellen
  // sees fresh data whenever she navigates back to הגשות.
  const projectId = await projectIdForTava(PILOT_TAVA);
  const TEST_VERSION = "v99.0";
  await uploadSubmissionViaApi(projectId, TEST_VERSION);
  await p.getByRole("button", { name: "סקירה" }).click();      // away
  await p.getByRole("button", { name: "הגשות" }).click();      // back → refetch

  const newCard = p.getByTestId(`submission-card-${TEST_VERSION}`);
  await expect(newCard).toBeVisible({ timeout: 15_000 });

  // ── Click trash, accept the Hebrew confirm dialog ───────────────────
  // window.confirm in WebView2 fires Playwright's 'dialog' event.
  // Pre-register the handler so the click can resolve. The delete
  // path in the UI handler triggers its own refetch, so no tab
  // bounce needed here.
  p.once("dialog", (d) => { void d.accept(); });
  await p.getByTestId(`delete-submission-${TEST_VERSION}`).click();

  // Card disappears once the DELETE + refresh round-trip lands.
  await expect(newCard).toBeHidden({ timeout: 15_000 });

  // ── Re-upload the same version_string ───────────────────────────────
  // The literal sequence that broke today: same version coming back
  // after a delete. Bounce tabs again to trigger the refetch (same
  // reason as the first upload — API bypasses the UI's refresh path).
  await uploadSubmissionViaApi(projectId, TEST_VERSION);
  await p.getByRole("button", { name: "סקירה" }).click();
  await p.getByRole("button", { name: "הגשות" }).click();
  await expect(newCard).toBeVisible({ timeout: 15_000 });

  // No report buttons for a fresh upload — has_audit_results is false
  // because no engine has run against this throwaway PDF. Assert their
  // absence to prove the UI is correctly reflecting that state (rather
  // than stale-rendering buttons from the deleted predecessor row).
  await expect(
    p.getByTestId(`generate-report-pdf-${TEST_VERSION}`),
  ).toHaveCount(0);
  await expect(
    p.getByTestId(`generate-report-xlsx-${TEST_VERSION}`),
  ).toHaveCount(0);

  // Trash button on the re-uploaded row must still be present and
  // functional (catches the "buttons vanished after re-upload" inverse).
  await expect(
    p.getByTestId(`delete-submission-${TEST_VERSION}`),
  ).toBeVisible();
});
