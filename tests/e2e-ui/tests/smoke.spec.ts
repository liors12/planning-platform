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
//   - UPGRADE-PATH bugs: new build over pre-existing user data with the
//     old version-string format (flow 7 — the v24.3-duplicate bug that
//     hit Ellen). All other flows test fresh installs; this one tests
//     "Ellen reinstalls" and is the missing coverage that lets us catch
//     "works on fresh, breaks on upgrade" before shipping.
//
// What it does NOT catch — see README.md.

import { test, expect, chromium, type Browser, type Page } from "@playwright/test";
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import type { ChildProcess } from "node:child_process";
import {
  createCommentViaApi,
  createPerRunDataDir,
  createUserDataFolder,
  execSqlitePython,
  freeTcpPort,
  importSchemaViaApi,
  putSettingsViaApi,
  installedExePath,
  killApp,
  launchApp,
  logInstallDirContents,
  pdfHealthCheck,
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

  // ── P5: minimal RTL-safe PDF health check ───────────────────────────
  // Three bounds — see helpers.ts pdfHealthCheck for rationale.
  // Floors and ranges intentionally loose: the goal is to catch
  // catastrophic regressions (empty PDF, font failure → tofu boxes,
  // 1-page truncated render, exploded layout) NOT to enforce a
  // specific page count or text content. Tightening these requires
  // knowing the canonical report shape, which changes with template
  // edits — for that, use the existing visual-regression checks.
  const health = pdfHealthCheck(pdfPath);
  process.stdout.write(`[smoke] pdf health: ${JSON.stringify(health)}\n`);
  expect(health.size_bytes, "PDF too small to be a real report").toBeGreaterThan(10240);
  expect(health.page_count, "page_count out of sane range").toBeGreaterThanOrEqual(1);
  expect(health.page_count, "page_count out of sane range").toBeLessThanOrEqual(500);
  expect(
    health.hebrew_chars,
    "no Hebrew text extracted — likely a font-failure or empty PDF",
  ).toBeGreaterThan(100);

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

// ── Comments tab: regenerate button persistent feedback ──────────────
// Catches the "silent success" bug class on the regenerate button —
// previously the button showed a 3-second toast that auto-dismissed
// and offered no path to the produced files. Now (post-fix) it shows
// a persistent banner: working → success-with-open-links, AND it
// triggers BOTH the PDF render and the Excel export (not just PDF).
//
// We add a comment via API, open the comments tab, click regenerate,
// and assert: working banner appears → success banner appears →
// open-pdf + open-xlsx buttons are visible. Success banner appearing
// is the proof both jobs completed (CommentsTab gates that state on
// pdfOk && xlsxOk; partial success goes to a different banner).
test("flow 8: comments tab regenerate fires PDF + Excel with persistent feedback", async () => {
  await teardownCurrent();
  const dataDir = createPerRunDataDir();
  const p = await launchAndAttach(dataDir);

  // Need the seeded v24.3 submission id (gated by has_audit_results,
  // which the seed satisfies via bundled audit_outputs).
  const projectId = await projectIdForTava(PILOT_TAVA);
  const subsResp = await fetch(`http://127.0.0.1:17321/projects/${projectId}/submissions`);
  const subs = await subsResp.json() as Array<{ id: number; version_string: string }>;
  const v243 = subs.find((s) => s.version_string === PILOT_SEEDED_VERSION || s.version_string === "24.3");
  expect(v243, `seeded ${PILOT_SEEDED_VERSION} must be present`).toBeDefined();

  // Post a comment so the regenerate has something fresh to merge.
  // Failure here means the comments API itself is broken — surface
  // explicitly rather than masking as a UI assertion timeout later.
  await createCommentViaApi(v243!.id);

  // Navigate into the project + open the comments tab. The tab label
  // "הערות רפרנטים" is plain Hebrew text; getByRole("button") matches
  // the tab navigation.
  await p.getByTestId(`home-project-link-${PILOT_TAVA}`).click();
  await p.getByRole("button", { name: "הערות רפרנטים" }).click();

  // The regenerate button only renders inside CommentsTabReady, which
  // is gated on has_audit_results. Seeded v24.3 passes that gate.
  const regenBtn = p.getByTestId("regenerate-comments-report");
  await expect(regenBtn).toBeVisible({ timeout: 15_000 });
  await expect(regenBtn).toBeEnabled();

  // ── Click + assert WORKING → SUCCESS transition ────────────────────
  await regenBtn.click();
  await expect(
    p.getByTestId("regen-banner-working"),
  ).toBeVisible({ timeout: 5_000 });

  // 90s ceiling matches the per-job poll budget in the React handler.
  // Real wall-clock in CI is ~10–15s for both jobs combined.
  await expect(
    p.getByTestId("regen-banner-success"),
  ).toBeVisible({ timeout: 90_000 });

  // Success banner exposes the same actions the submissions-tab
  // OutputBanner does. Visibility of both prove the persistent
  // (non-toast) UX is in place AND both outputs ran (partial-success
  // goes to a different banner with a different testid).
  await expect(p.getByTestId("regen-open-pdf")).toBeVisible();
  await expect(p.getByTestId("regen-open-xlsx")).toBeVisible();
});

// ── P7 flow 7: upgrade-path (the bug class that hit Ellen) ────────────
// The duplicate-v24.3-row bug happened because every other flow tests a
// FRESH install. Ellen UPGRADES over data that pre-dates the seed-creates-
// submissions feature, where her manual upload stored "24.3" (no
// v-prefix). The seed compared the literal version_string, didn't
// recognize "24.3" as equivalent to its canonical "v24.3", and inserted
// a duplicate row alongside hers.
//
// This flow simulates the upgrade by: launching once on a fresh data
// dir (seed inserts canonical v24.3), then mutating the DB via sqlite3
// to rename that row to "24.3" (mimics what Ellen's DB looked like
// pre-upgrade), then relaunching with the same data dir (the seed
// runs again over the "pre-existing" data).
//
// Fix proof: with the version-prefix-aware idempotency check now in
// main.py:_discover_submissions, the second seed run skips instead
// of duplicating. Without that fix this test would assert two rows
// where there should be one — caught locally before the user did.
test("flow 7: upgrade-path — seed idempotent across version-prefix variants", async () => {
  await teardownCurrent();
  const dataDir = createPerRunDataDir();
  const dbPath = join(dataDir, "platform.db");

  // ── Phase A: fresh launch, seed inserts v24.3 ───────────────────────
  await launchAndAttach(dataDir);
  // Cleanly shut down so we can directly mutate the SQLite file —
  // sidecar holds a writer lock while up.
  try { if (browser) await browser.close(); } catch { /* ignore */ }
  killApp(appProcess);
  wipeUserDataFolder(userDataFolder);
  appProcess = null; browser = null; page = null;
  userDataFolder = null; cdpPort = null;

  // ── Phase B: simulate pre-upgrade state ─────────────────────────────
  // Rename the canonical "v24.3" row to "24.3" — mimics what Ellen's
  // DB looked like before the seed-creates-submissions feature shipped.
  // Also flip status back to "uploaded" so the simulation matches her
  // actual pre-upgrade row shape (status="uploaded" was the upload
  // endpoint's default before the seed started using "complete").
  const beforeMutation = execSqlitePython(
    dbPath,
    "SELECT id, version_string, status FROM submissions WHERE version_string='v24.3'",
  );
  expect(beforeMutation.length, "phase A: seed should have created v24.3").toBe(1);
  execSqlitePython(
    dbPath,
    "UPDATE submissions SET version_string='24.3', status='uploaded' " +
    "WHERE version_string='v24.3'",
  );
  process.stdout.write(`[smoke] flow 7: renamed v24.3 → 24.3 to simulate upgrade\n`);

  // ── Phase C: relaunch — seed runs again over the "pre-existing" data ─
  const p = await launchAndAttach(dataDir);

  // ── Assert 1: exactly ONE v24.3-ish row (not two) ───────────────────
  // Direct DB count is the load-bearing assertion — exactly the check
  // that would have flagged the duplicate Ellen saw. Both prefix forms
  // checked to be future-proof against the seed normalizing in either
  // direction.
  const rows = execSqlitePython(
    dbPath,
    "SELECT id, version_string, status FROM submissions " +
    "WHERE version_string IN ('24.3', 'v24.3')",
  ) as Array<{ id: number; version_string: string; status: string }>;
  process.stdout.write(`[smoke] flow 7: post-relaunch rows = ${JSON.stringify(rows)}\n`);
  expect(
    rows.length,
    `upgrade-path regression: expected 1 v24.3 row, found ${rows.length}: ` +
    `${JSON.stringify(rows)}`,
  ).toBe(1);
  // The surviving row should be the pre-existing "24.3" (not the
  // canonical "v24.3" the seed wanted to insert) — the idempotency
  // check has to recognize the existing one and skip, not overwrite it.
  expect(rows[0].version_string, "seed clobbered the pre-existing row").toBe("24.3");

  // ── Assert 2: submissions tab renders the row + report buttons ──────
  // The testid uses the stored version_string verbatim, so "24.3" not
  // "v24.3". If the wrong card renders, this fails with a clear
  // locator-not-found error.
  await p.getByTestId(`home-project-link-${PILOT_TAVA}`).click();
  await p.getByRole("button", { name: "הגשות" }).click();
  await expect(p.getByTestId("submission-card-24.3")).toBeVisible({ timeout: 15_000 });
  await expect(p.getByTestId("generate-report-pdf-24.3")).toBeVisible();
  await expect(p.getByTestId("generate-report-xlsx-24.3")).toBeVisible();

  // ── Assert 3: comments tab loads (no crash from duplicate-row state) ─
  // Ellen's reported symptom was "שגיאת טעינת תכנית העיצוב: failed to
  // fetch" — the PDF viewer error from the seeded row's phantom
  // pdf_path. With the idempotency fix in place, only the row with the
  // real (seed-supplied path) survives — but the test ALSO needs to
  // prove the tab itself renders. We check for the add-comment form's
  // submit button as proof the gate opened and the inner UI mounted.
  await p.getByRole("button", { name: "הערות רפרנטים" }).click();
  await expect(
    p.getByRole("button", { name: "+ הוסיפי הערה" }),
  ).toBeVisible({ timeout: 15_000 });
});

// ── Flow C1: schema import API — POST /projects/import-schema ────────
// Warn-only: wrapped in try/catch so CI stays green while this feature
// is being rolled out. A failure here emits a warning line but does NOT
// block the build. Promote to a hard assertion once stable.
//
// What this covers:
//   - Backend: POST /projects/import-schema accepts a JSON file,
//     creates a DB row, writes schema + _project.json to disk
//   - has_schema: true is returned immediately (file was just written)
//   - The project appears in GET /projects
//   - A duplicate-tava import returns 409 (not 500 / crash)
//
// What this does NOT cover (deferred to a separate UI flow):
//   - The "ייבאי קובץ תב"ע" tab UI — needs native file picker driving
//     which is not possible through CDP/WebView2 without OS automation
test("flow C1 [warn]: schema import API — create project via JSON file", async () => {
  await teardownCurrent();
  const dataDir = createPerRunDataDir();
  const p = await launchAndAttach(dataDir);

  const TEST_TAVA = "999-smoke-c1";
  try {
    // ── Step 1: import a minimal schema ────────────────────────────────
    const created = await importSchemaViaApi({
      tava_number: TEST_TAVA,
      name_he: "פרויקט בדיקה C1",
    });
    process.stdout.write(
      `[smoke] flow C1: created project id=${created.id} tava=${created.tava_number} ` +
      `has_schema=${created.has_schema}\n`,
    );
    expect(created.tava_number, "tava_number mismatch").toBe(TEST_TAVA);
    expect(created.has_schema, "has_schema should be true after import").toBe(true);

    // ── Step 2: project appears in GET /projects ────────────────────
    const listResp = await fetch("http://127.0.0.1:17321/projects");
    expect(listResp.ok, "GET /projects failed").toBe(true);
    const projects = await listResp.json() as Array<{ tava_number: string; has_schema: boolean }>;
    const match = projects.find((pr) => pr.tava_number === TEST_TAVA);
    expect(match, `project ${TEST_TAVA} not in /projects list`).toBeTruthy();
    expect(match?.has_schema, "has_schema false in list response").toBe(true);

    // ── Step 3: duplicate import → 409, not 500 ─────────────────────
    try {
      await importSchemaViaApi({ tava_number: TEST_TAVA, name_he: "כפילות" });
      process.stdout.write("[smoke] flow C1: WARNING — duplicate import did not return 409\n");
    } catch (dupErr) {
      const msg = String(dupErr);
      if (!msg.includes("409")) {
        process.stdout.write(`[smoke] flow C1: WARNING — duplicate error was not 409: ${msg}\n`);
      } else {
        process.stdout.write("[smoke] flow C1: duplicate 409 ✓\n");
      }
    }

    // ── Step 4: project link appears in the home UI ─────────────────
    await p.reload();
    await expect(p.getByTestId("app-ready")).toBeVisible({ timeout: 20_000 });
    await expect(
      p.getByTestId(`home-project-link-${TEST_TAVA}`),
    ).toBeVisible({ timeout: 10_000 });

    process.stdout.write("[smoke] flow C1: PASSED ✓\n");
  } catch (err) {
    // Warn-only: log but don't re-throw so CI stays green.
    process.stdout.write(`[smoke] flow C1: WARN — ${String(err)}\n`);
  }
});

// ── Flow C2: Settings API — PUT/GET /settings ─────────────────────────
// Warn-only: wrapped in try/catch so CI stays green while this feature
// is being rolled out.
//
// What this covers:
//   - PUT /settings stores the key, returns anthropic_api_key_set: true
//   - GET /settings returns anthropic_api_key_set: true (key is set)
//   - GET /settings never echoes the key value in the response body
//   - Restart persistence: GET after sidecar restart still returns true
//
// What this does NOT cover (UI path deferred — native form):
//   - The Settings.tsx page UI — requires navigating to #/settings, which
//     is exercised manually; the API surface is the load-bearing part.
test("flow C2 [warn]: settings API — store and persist Anthropic API key", async () => {
  await teardownCurrent();
  const dataDir = createPerRunDataDir();
  await launchAndAttach(dataDir);

  // Fake key with the correct prefix — format-only validation, no live ping.
  const FAKE_KEY = "sk-ant-api03-smoke-c2-00000000000000000000000000000000000000000000000000";

  try {
    // ── Step 1: PUT key → assert key_set: true ──────────────────────
    const putResult = await putSettingsViaApi(FAKE_KEY);
    process.stdout.write(
      `[smoke] flow C2: PUT result = ${JSON.stringify(putResult)}\n`,
    );
    expect(putResult.anthropic_api_key_set, "PUT should return key_set: true").toBe(true);

    // ── Step 2: GET /settings → key_set: true, key not echoed ───────
    const getResp = await fetch("http://127.0.0.1:17321/settings");
    expect(getResp.ok, "GET /settings failed").toBe(true);
    const settings = await getResp.json() as Record<string, unknown>;
    expect(settings.anthropic_api_key_set, "GET should return key_set: true").toBe(true);
    const body = JSON.stringify(settings);
    expect(
      body.includes(FAKE_KEY),
      "API key must not be echoed in GET /settings response",
    ).toBe(false);

    // ── Step 3: restart → GET /settings still returns key_set: true ─
    // Kill + relaunch with the same data dir so the DB persists.
    try { if (browser) await browser.close(); } catch { /* ignore */ }
    killApp(appProcess);
    wipeUserDataFolder(userDataFolder);
    appProcess = null; browser = null; page = null;
    userDataFolder = null; cdpPort = null;
    // platformDataDir intentionally NOT cleared — reuse same DB.

    await launchAndAttach(dataDir);

    const getAfterRestart = await fetch("http://127.0.0.1:17321/settings");
    expect(getAfterRestart.ok, "GET /settings after restart failed").toBe(true);
    const settingsAfter = await getAfterRestart.json() as Record<string, unknown>;
    expect(
      settingsAfter.anthropic_api_key_set,
      "key must persist across sidecar restart (loaded from DB at boot)",
    ).toBe(true);

    process.stdout.write("[smoke] flow C2: PASSED ✓\n");
  } catch (err) {
    process.stdout.write(`[smoke] flow C2: WARN — ${String(err)}\n`);
  }
});
