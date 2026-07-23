import { defineConfig } from "@playwright/test";
import path from "path";

// Round-1 fix verification suite (gates C/D/G of fix/first-look-round1).
// Same split-model shape as the QA campaign harness: Vite dev server + real
// sidecar with a fresh seeded data dir.

const REPO = path.resolve(__dirname, "../..");
export const DATA_DIR = path.join(__dirname, ".qa-fixes-data");

export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
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
      command: `bash -c 'rm -rf "${DATA_DIR}" && mkdir -p "${DATA_DIR}" && cd ${REPO}/app/sidecar && exec /opt/homebrew/bin/python3.13 -m sidecar.main'`,
      url: "http://127.0.0.1:17321/health",
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        PLATFORM_DATA_DIR: DATA_DIR,
        PLATFORM_PYTHON: "/opt/homebrew/bin/python3.13",
      },
    },
  ],
});
