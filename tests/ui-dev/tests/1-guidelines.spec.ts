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

// v0.2.1: assert the OPEN-ENDPOINT is called, not Playwright's download
// event. Chromium happily downloads; the packaged WebView2 shell does not,
// so a download-event assertion passes while the real app is broken. That
// exact false-green shipped the dead "הורדת PDF" button in v0.1.0-v0.2.0.
test("guidelines v0.2.1: כללי splits into source-section sub-groups", async ({ page, request }) => {
  await page.goto("/#/guidelines");
  const general = page.getByTestId("guidelines-group-general");
  const subGroups = general.locator('[data-testid^="guidelines-subgroup-"]');
  await expect(subGroups.first()).toBeVisible();

  // Counts on screen must match the API, per sub-group - not just in total.
  const rows = await (await request.get("http://127.0.0.1:17321/guidelines")).json();
  const expected = new Map<string, number>();
  for (const g of rows.filter((r: { discipline_key: string }) => r.discipline_key === "general")) {
    const key = (g.section_title || "").trim() || "הנחיות מינהלת";
    expected.set(key, (expected.get(key) ?? 0) + 1);
  }
  expect(expected.size).toBeGreaterThan(1);
  await expect(subGroups).toHaveCount(expected.size);
  for (const [title, n] of expected) {
    await expect(general.getByTestId(`guidelines-subgroup-${title}`))
      .toContainText(`${n} הנחיות`);
  }
});

test("guidelines: PDF button calls the sidecar open-endpoint", async ({ page, request }) => {
  await page.goto("/#/guidelines");
  const btn = page.getByTestId("guidelines-pdf-download");
  const callPromise = page.waitForRequest(
    (r) => r.url().includes("/guidelines/open-pdf") && r.method() === "POST",
  );
  await btn.click();
  const req = await callPromise;
  const resp = await req.response();
  expect(resp?.status()).toBe(204);

  // The button tells the whole story: working, then opened. Ellen gets no
  // browser download shelf here - the file is opened by the OS.
  await expect(btn).toHaveAttribute("data-pdf-state", "opened");
  await expect(btn).toContainText("הקובץ נפתח");

  // ...and the endpoint it calls really does produce a PDF.
  const pdf = await request.get("http://127.0.0.1:17321/guidelines/export-pdf");
  expect(pdf.status()).toBe(200);
  const buf = await pdf.body();
  expect(buf.subarray(0, 4).toString("ascii")).toBe("%PDF");
  expect(buf.length).toBeGreaterThan(1000);
});
