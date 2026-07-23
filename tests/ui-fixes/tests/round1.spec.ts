import { test, expect, Page } from "@playwright/test";

// Gate C+D+G for fix/first-look-round1.
// C: item-6 friendly no-findings state; item-7 scan disabled without DXF.
// D: 1024x700 layout integrity (no horizontal overflow, labels intact,
//    sidebar footer visible).
// G: #/guidelines still renders and the sidebar link navigates to it.

async function assertNoRawApiText(page: Page) {
  const body = await page.locator("body").innerText();
  for (const marker of ["HTTP 4", "HTTP 5", "GET /", "POST /", '"detail"', "→ HTTP"]) {
    expect(body, `raw API text leaked: ${marker}`).not.toContain(marker);
  }
}

test("item 6: findings tab renders without raw API text", async ({ page }) => {
  // Post-F-1: the seed stages findings.json, so the tab shows real findings
  // (not the empty state). The invariant under test is unchanged - no raw
  // English API error ever reaches the screen.
  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-findings").click();
  await expect(page.locator('[data-section="disciplines"]')).toBeVisible();
  await assertNoRawApiText(page);
});

test("item 7: CAD scan disabled without DXF, hint shown, no raw 422", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-cad_layers").click();
  await expect(page.getByTestId("layer-mapping-discover-btn")).toBeDisabled();
  await expect(page.getByTestId("layer-mapping-no-dxf-hint")).toBeVisible();
  await assertNoRawApiText(page);
});

test("item 9 + D: 1024x700 — sidebar footer visible, no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 700 });
  await page.goto("/");
  await expect(page.getByTestId("sidebar-guidelines-link")).toBeInViewport();

  // No horizontal document overflow on home or submissions.
  const overflowX = () =>
    page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(await overflowX()).toBeLessThanOrEqual(0);

  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-submissions").click();
  expect(await overflowX()).toBeLessThanOrEqual(0);

  // Item 5: no button label truncation in the submission action row.
  const clipped = await page.evaluate(() =>
    Array.from(document.querySelectorAll(".submission-actions button"))
      .filter((el) => el.scrollWidth > el.clientWidth + 1)
      .map((el) => (el as HTMLElement).innerText),
  );
  expect(clipped, `clipped button labels: ${clipped.join(", ")}`).toHaveLength(0);
});

test("G: guidelines route renders via sidebar link", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("sidebar-guidelines-link").click();
  await expect(page).toHaveURL(/#\/guidelines$/);
  await expect(page.locator('[data-check-key="glass_railing_min_height_cm"]')).toBeVisible();
});
