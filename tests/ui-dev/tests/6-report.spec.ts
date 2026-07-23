import { test, expect } from "./fixtures";
import { stagePilotPdf } from "./helpers";

// Test 6: generate the audit report PDF from the seeded pilot submission
// and verify the success banner. Render job runs WeasyPrint locally.

test("report: הפיקי דו״ח produces the ready banner", async ({ page }) => {
  test.setTimeout(240_000);
  stagePilotPdf();

  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-submissions").click();

  await page.getByTestId("generate-report-pdf-v24.3").click();
  await expect(page.getByTestId("output-banner-success-pdf")).toBeVisible({ timeout: 200_000 });
});
