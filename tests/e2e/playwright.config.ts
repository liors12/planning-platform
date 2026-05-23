import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the planning-platform e2e suite.
 *
 * The tests target the Vite dev server at http://127.0.0.1:1420, which
 * is the SAME bundle the Tauri wrapper's WKWebView loads in dev. Running
 * against Vite (rather than the wrapper itself) lets headless CI exercise
 * the React app without needing macOS Screen Recording perms (see
 * docs/known_issues.md #17). The contract is: if the React code works
 * here, it works in the wrapper.
 *
 * Before running: ensure the sidecar (port 17321) and Vite (port 1420)
 * are up — `scripts/prep_cowork_session.sh` brings both up cleanly.
 */
export default defineConfig({
  testDir: ".",
  fullyParallel: false, // tests share localStorage / sidecar state
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? "line" : "list",
  use: {
    baseURL: "http://127.0.0.1:1420",
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1400, height: 900 } },
    },
  ],
});
