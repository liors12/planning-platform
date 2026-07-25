import { test, expect } from "./fixtures";

// F1 (Ellen's flow): edit the glass-railing value 105→110, verify version 2,
// history shows both versions, export-pdf downloads. Rows are located by
// data-check-key (stable across seeds), not by DB id.

const RAILING = '[data-check-key="glass_railing_min_height_cm"]';

test("guidelines: edit 105→110 creates version 2; history shows both", async ({ page }) => {
  await page.goto("/#/guidelines");

  const row = page.locator(RAILING);
  await expect(row).toBeVisible();
  await expect(row).toContainText("105");

  await row.locator('[data-testid^="guideline-edit-"]').click();
  const valueInput = page.getByTestId("guideline-edit-value");
  await expect(valueInput).toBeVisible();
  await valueInput.fill("110");
  await page.getByTestId("guideline-edit-save").click();

  // The active railing row is now the new version.
  await expect(page.locator(RAILING)).toContainText("110");
  await expect(page.locator(RAILING)).toContainText("2"); // "גרסה 2"

  await page.locator(RAILING).locator('[data-testid^="guideline-history-"]').click();
  const history = page.getByTestId("guideline-history-list");
  await expect(history).toBeVisible();
  await expect(history).toContainText("110");
  await expect(history).toContainText("105");
});

test("guidelines v0.2.0: discipline grouping + sticky nav", async ({ page }) => {
  await page.goto("/#/guidelines");
  await expect(page.getByTestId("guidelines-disc-nav")).toBeVisible();
  // The railing guideline (facade discipline) lives in the אדריכלות card.
  const archGroup = page.getByTestId("guidelines-group-sec-3-7");
  await expect(archGroup.locator(RAILING)).toBeVisible();
  // Nav chip scrolls to + expands the discipline card.
  await page.getByTestId("disc-nav-sec-3-1").click();
  await expect(page.getByTestId("guidelines-group-sec-3-1")).toBeVisible();
});

test("guidelines v0.2.0: add-guideline flow (מינהלת origin)", async ({ page }) => {
  await page.goto("/#/guidelines");
  await page.getByTestId("add-guideline-global").click();
  // Validation: empty form cannot save.
  await expect(page.getByTestId("add-guideline-save")).toBeDisabled();
  await page.getByTestId("add-guideline-discipline").selectOption("sec-3-2");
  await page.getByTestId("add-guideline-title").fill("הנחיית בדיקה חדשה לגינון");
  await page.getByTestId("add-guideline-body").fill("נוסח בדיקה ארוך מספיק עבור ולידציה.");
  await page.getByTestId("add-guideline-save").click();
  // Appears inside its discipline card with the origin badge.
  const group = page.getByTestId("guidelines-group-sec-3-2");
  await expect(group.getByText("הנחיית בדיקה חדשה לגינון")).toBeVisible();
  await expect(group.getByText("מינהלת").first()).toBeVisible();
});

test("guidelines: export-pdf downloads a real PDF", async ({ page }) => {
  await page.goto("/#/guidelines");
  const downloadPromise = page.waitForEvent("download");
  await page.getByTestId("guidelines-pdf-download").click();
  const download = await downloadPromise;
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const c of stream) chunks.push(c as Buffer);
  const buf = Buffer.concat(chunks);
  expect(buf.length).toBeGreaterThan(1000);
  expect(buf.subarray(0, 4).toString("ascii")).toBe("%PDF");
});
