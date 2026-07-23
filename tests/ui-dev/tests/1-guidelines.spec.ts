import { test, expect } from "./fixtures";

// Test 1 (Ellen's new feature, highest priority): edit a guideline value
// 105→110, verify version bump to 2, verify history shows both versions.
// Fresh DB per run → the glass-railing guideline is always seeded id=1 v1@105.

test("guidelines: edit 105→110 creates version 2; history shows both", async ({ page }) => {
  await page.goto("/#/guidelines");

  // Seeded glass-railing row (id=1) shows value 105, version 1.
  const row = page.getByTestId("guideline-row-1");
  await expect(row).toBeVisible();
  await expect(page.getByTestId("guideline-value-1")).toContainText("105");

  // Edit → set value to 110 → save.
  await page.getByTestId("guideline-edit-1").click();
  const valueInput = page.getByTestId("guideline-edit-value");
  await expect(valueInput).toBeVisible();
  await valueInput.fill("110");
  await page.getByTestId("guideline-edit-save").click();

  // The list refreshes: the active row is now the NEW id (2 versions exist,
  // new row id is 11 on a fresh seed of 10). Find it via its value testid.
  await expect(page.getByTestId("guideline-value-11")).toContainText("110");
  const newRow = page.getByTestId("guideline-row-11");
  await expect(newRow).toContainText("2"); // "גרסה 2" marker

  // History on the new row shows both versions with their values.
  await page.getByTestId("guideline-history-11").click();
  const history = page.getByTestId("guideline-history-list");
  await expect(history).toBeVisible();
  await expect(history).toContainText("110");
  await expect(history).toContainText("105");
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
