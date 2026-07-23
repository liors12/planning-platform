import { defineConfig } from "@playwright/test";
import path from "path";

// Split-UI harness (QA campaign Phase 2). Two real servers:
//   1. Vite dev server on 1420 — the actual frontend code.
//   2. The Python sidecar on 17321 (the frontend hardcodes this port) with a
//      FRESH data dir per run — the sidecar seeds the pilot project + global
//      guidelines on first boot, so every run starts from known state.
// The `bash -c` wrapper wipes the data dir before boot; specs that need the
// real pilot PDF stage it themselves (see helpers.ts stagePilotPdf).
//
// Scope note (accepted gap, see QA_CAMPAIGN.md): this harness does NOT cover
// the Tauri shell / WebView2 packaging — that stays with the CI API probes.

const REPO = path.resolve(__dirname, "../..");
export const DATA_DIR = path.join(__dirname, ".qa-ui-data");
// CI passes QA_SUITE_PYTHON=python3; local default is the Homebrew build
// (WeasyPrint needs the Homebrew Pango stack on macOS).
const PY = process.env.QA_SUITE_PYTHON ?? "/opt/homebrew/bin/python3.13";

export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:1420",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `npm --prefix ${REPO}/app/frontend run dev`,
      url: "http://127.0.0.1:1420",
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: `bash -c 'rm -rf "${DATA_DIR}" && mkdir -p "${DATA_DIR}" && cd ${REPO}/app/sidecar && exec "${PY}" -m sidecar.main'`,
      url: "http://127.0.0.1:17321/health",
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        PLATFORM_DATA_DIR: DATA_DIR,
        PLATFORM_PYTHON: PY,
      },
    },
  ],
});
