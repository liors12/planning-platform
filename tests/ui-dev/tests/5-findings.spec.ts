import { test, expect } from "./fixtures";
import { pilotPdfAvailable, stagePilotPdf } from "./helpers";

// Test 5: findings view renders all three sections, and a finding drawer
// opens. Post-F-1 the seed stages findings.json from the bundled
// audit_results, so the probe below normally succeeds immediately (also on
// CI). The engine-run fallback stays for a data dir where findings were
// removed and the pilot PDF is available locally.

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
