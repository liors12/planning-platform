import { defineConfig } from "@playwright/test";

// Tests drive the REAL installed Windows app over CDP. We never spawn a
// browser ourselves — every test attaches via `chromium.connectOverCDP`
// to WebView2's debug port. So Playwright's bundled browsers aren't
// needed and we skip the `playwright install` step entirely in CI.
export default defineConfig({
  testDir: "./tests",
  // One worker only — there's a single packaged app instance on the
  // runner. Parallelism would fight over the CDP port and %LOCALAPPDATA%.
  workers: 1,
  fullyParallel: false,
  // Two minutes per test: install + sidecar boot + render can each take
  // ~30s individually on a cold runner.
  timeout: 120_000,
  expect: { timeout: 15_000 },
  // First cut: don't retry. A green run on the first try is the signal
  // we want; retries would mask the flakiness we're trying to measure
  // before promoting this from warn-only to a hard gate.
  retries: 0,
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  use: {
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off",
  },
});
