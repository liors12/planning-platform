import { test, expect } from "./fixtures";
import { pilotPdfAvailable, stagePilotPdf } from "./helpers";

// Test 4: run the engine on the seeded pilot submission (real PDF staged)
// and wait for the הושלם status. Real audit ≈ 60-120s locally.

test("audit run: pilot v24.3 completes", async ({ page }) => {
  test.skip(!pilotPdfAvailable(), "pilot PDF not available (CI) - real-audit flow runs locally only");
  test.setTimeout(300_000);
  stagePilotPdf();

  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-submissions").click();

  const runBtn = page.getByTestId("run-engine-v24.3");
  await expect(runBtn).toBeEnabled();
  await runBtn.click();

  const status = page.getByTestId("submission-status-v24.3");
  // The seed ships the pilot as status=complete, so asserting "complete"
  // directly races the click (red-cycle proof caught this). Require the
  // analyzing transition FIRST — proves a new run actually started — then
  // completion of THAT run.
  await expect(status).toHaveAttribute("data-status", "analyzing", { timeout: 30_000 });
  await expect(status).toHaveAttribute("data-status", "complete", { timeout: 280_000 });
});
