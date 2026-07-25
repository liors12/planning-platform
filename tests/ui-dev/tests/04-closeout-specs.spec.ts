import { test, expect } from "./fixtures";

// Close-out specs for audit items 5 / 13 / 14. All three pin UI contracts
// deterministically via route interception (no engine / Gemini needed).

test("item 5: failed report job shows NO success banner", async ({ page }) => {
  // Fake the render job lifecycle: enqueue OK, job terminates as failed.
  await page.route("**/submissions/*/render", (route) =>
    route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        id: "fake-job", job_type: "render_pdf", submission_id: 1,
        status: "queued", queued_at: "2026-07-01T12:00:00",
        started_at: null, completed_at: null, error: null,
      }),
    }),
  );
  await page.route("**/jobs/fake-job", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "fake-job", job_type: "render_pdf", submission_id: 1,
        status: "failed", queued_at: "2026-07-01T12:00:00",
        started_at: "2026-07-01T12:00:01", completed_at: "2026-07-01T12:00:02",
        error: JSON.stringify({ error_type: "RenderNonZeroExit", error_message: "render exit code 1" }),
      }),
    }),
  );
  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-submissions").click();
  await page.getByTestId("generate-report-pdf-v24.3").click();
  // Error surface appears; the success banner must not.
  await expect(page.getByText(/אירעה תקלה ביצירת הדוח|לא ניתן ליצור דוח/).first())
    .toBeVisible({ timeout: 20_000 });
  const body = await page.locator("body").innerText();
  expect(body).not.toContain("הדו״ח מוכן");
});

test("item 13: report freshness line renders date + changes hint", async ({ page }) => {
  // Inject freshness fields into the submissions list response.
  await page.route("**/projects/*/submissions", async (route) => {
    const resp = await route.fetch();
    const rows = await resp.json();
    for (const r of rows) {
      r.report_generated_at = "2026-07-01T09:30:00";
      r.report_changes_since = true;
    }
    await route.fulfill({ response: resp, body: JSON.stringify(rows) });
  });
  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-submissions").click();
  const fresh = page.getByTestId("report-freshness").first();
  await expect(fresh).toBeVisible();
  await expect(fresh).toContainText("דו\"ח אחרון הופק");
  await expect(fresh).toContainText("2026-07-01 09:30");
  await expect(fresh).toContainText("נוספו שינויים מאז הדו\"ח האחרון");
  // The report button stays enabled regardless of freshness.
  await expect(page.getByTestId("generate-report-pdf-v24.3")).toBeEnabled();
});

test("item 14: unified upload without extractable text shows the friendly message", async ({ page }) => {
  // CI has no GEMINI_API_KEY; a text-less PDF exercises the server's honest
  // "scanned document" path end-to-end through the unified endpoint -
  // friendly Hebrew message, no crash, no raw error.
  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-comments").click();
  const chooser = page.waitForEvent("filechooser");
  await page.getByTestId("pdf-extract-btn").click();
  (await chooser).setFiles({
    name: "empty.pdf", mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4\n%%EOF\n"),
  });
  await expect(page.getByText(/הקובץ סרוק ואינו מכיל טקסט/)).toBeVisible({ timeout: 20_000 });
  const body = await page.locator("body").innerText();
  expect(body).not.toContain("Error:");
  expect(body).not.toContain("HTTP 5");
});
