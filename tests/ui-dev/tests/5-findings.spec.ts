import { test, expect } from "./fixtures";
import { pilotPdfAvailable, stagePilotPdf } from "./helpers";

// Test 5: findings view renders all three sections, and a finding drawer
// opens. Arrange: findings.json only exists after an engine run (the seed
// ships audit_outputs but NOT findings.json — logged as campaign finding
// F-1: fresh install's ממצאים tab 409s with a raw English error). If spec 4
// already ran the audit this arrange is a no-op; standalone it runs the
// engine via the API.

let skipAll = false;
test.beforeAll(async ({ request }) => {
  const probe = await request.get("http://127.0.0.1:17321/submissions/1/findings");
  if (probe.ok()) return;
  if (!pilotPdfAvailable()) { skipAll = true; return; }
  stagePilotPdf();
  await request.post("http://127.0.0.1:17321/submissions/1/run-engine");
  await expect
    .poll(async () => {
      const r = await request.get("http://127.0.0.1:17321/submissions/1");
      return (await r.json()).status;
    }, { timeout: 280_000, intervals: [5_000] })
    .toBe("complete");
});

test("findings: sections render + drawer opens", async ({ page }) => {
  test.skip(skipAll, "no findings and no pilot PDF (CI) - runs locally");
  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-findings").click();

  // Three engine sections (disciplines / content / format).
  await expect(page.locator('[data-section="disciplines"]')).toBeVisible();
  await expect(page.locator('[data-section="content"]')).toBeVisible();
  await expect(page.locator('[data-section="format"]')).toBeVisible();

  // Expand the first finding row's drawer via its chevron button.
  const firstExpand = page.locator('[data-testid^="finding-expand-"]').first();
  await firstExpand.click();
  await expect(page.locator(".finding-row.expanded").first()).toBeVisible();
});
