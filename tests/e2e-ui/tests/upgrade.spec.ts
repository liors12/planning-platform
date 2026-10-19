// Upgrade probe - the UI half. Runs ONLY when the upgrade-probe job in
// ui-smoke.yml sets SENTINEL_NAME; in every other run it skips, so the normal
// smoke suite is unaffected.
//
// By the time this runs, the job has: installed the OLD build, written a
// sentinel project through the old app's own API, stopped it, and installed
// the NEW build over it. This spec launches the NEW shell exactly as Ellen
// would - with NO PLATFORM_DATA_DIR override, so the sidecar falls back to its
// real default, %LOCALAPPDATA%\Planning Platform, which is also the install
// dir - and asserts the sentinel is visible on the home screen.
//
// SAFETY: the usual smoke teardown wipes the data dir. Here the data dir IS
// the install dir and holds the row under test, so this spec never wipes it;
// it only kills the app and removes the throwaway WebView2 profile folder.
import { test, expect, chromium, type Browser } from "@playwright/test";
import type { ChildProcess } from "node:child_process";
import {
  createUserDataFolder, freeTcpPort, killApp, launchApp, pickTauriPage,
  waitForCdp, waitForSidecar, wipeUserDataFolder,
} from "./helpers";

const SENTINEL = process.env.SENTINEL_NAME;

test.skip(!SENTINEL, "upgrade probe only - SENTINEL_NAME not set");

let app: ChildProcess | null = null;
let browser: Browser | null = null;
let profile: string | null = null;

test.afterAll(async () => {
  try { if (browser) await browser.close(); } catch { /* ignore */ }
  killApp(app);
  wipeUserDataFolder(profile);     // WebView2 profile only - never the data dir
});

test("upgrade: sentinel written by the old build is visible in the new app", async () => {
  const port = await freeTcpPort();
  profile = createUserDataFolder();
  // "" -> config.py's `os.environ.get("PLATFORM_DATA_DIR") or _default_data_dir()`
  // falls through to the real default. That is the whole point of this test.
  app = launchApp(port, profile, "");
  await waitForSidecar(60_000);
  await waitForCdp(port, 60_000);
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  const page = await pickTauriPage(browser, 20_000);
  await expect(page.getByTestId("app-ready")).toBeVisible({ timeout: 45_000 });

  // The home screen and the sidebar both render name_he for every project.
  await expect(page.getByText(SENTINEL!, { exact: false }).first())
    .toBeVisible({ timeout: 20_000 });
  await page.screenshot({ path: "test-results/upgrade-sentinel-visible.png", fullPage: true });
});
