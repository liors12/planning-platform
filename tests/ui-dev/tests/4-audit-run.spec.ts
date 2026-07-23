import { test, expect } from "@playwright/test";
import { stagePilotPdf } from "./helpers";

// Test 4: run the engine on the seeded pilot submission (real PDF staged)
// and wait for the הושלם status. Real audit ≈ 60-120s locally.

test("audit run: pilot v24.3 completes", async ({ page }) => {
  test.setTimeout(300_000);
  stagePilotPdf();

  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-submissions").click();

  const runBtn = page.getByTestId("run-engine-v24.3");
  await expect(runBtn).toBeEnabled();
  await runBtn.click();

  const status = page.getByTestId("submission-status-v24.3");
  // analyzing first, then complete. Poll the data-status attribute.
  await expect(status).toHaveAttribute("data-status", "complete", { timeout: 280_000 });
});
