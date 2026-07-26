import { test, expect } from "./fixtures";
import { MIN_PDF } from "./helpers";

// v0.2.0 Phase 2f - attachments tab specs. All against the seeded pilot.

async function openAttachments(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-attachments").click();
}

async function uploadTraffic(page: import("@playwright/test").Page) {
  await page.getByTestId("attachment-type").selectOption("sec-3-4");
  await page.getByTestId("attachment-version").fill("v1");
  await page.getByTestId("attachment-file").setInputFiles({
    name: "traffic.pdf", mimeType: "application/pdf", buffer: MIN_PDF,
  });
  await page.getByTestId("attachment-upload-submit").click();
}

test("attachments: upload with type renders a card", async ({ page }) => {
  await openAttachments(page);
  await expect(page.getByTestId("attachments-empty")).toBeVisible();
  await uploadTraffic(page);
  const card = page.locator('[data-testid^="attachment-card-"]').first();
  await expect(card).toBeVisible();
  await expect(card).toContainText("תנועה");
  await expect(card).toContainText("הוכן");
});

test("attachments: mapped-only review - traffic checks in, gan-yard out", async ({ page }) => {
  await openAttachments(page);
  await uploadTraffic(page);
  const card = page.locator('[data-testid^="attachment-card-"]').first();
  await card.locator('[data-testid^="attachment-run-review-"]').click();
  const review = card.locator('[data-testid^="attachment-review-"]');
  await expect(review).toBeVisible();
  // Mapped traffic checks present.
  await expect(review).toContainText("בדיקת חשבון מאזן החניה");
  await expect(review).toContainText("חניות אורחים 30%");
  // An UNMAPPED check (public-buildings' gan-yard) must NOT appear.
  const text = await review.innerText();
  expect(text).not.toContain("חצר גן 200");
  // File-quality checks always run.
  await expect(review).toContainText("פורמט קובץ");
});

test("attachments: revision auto-runs the review", async ({ page, request }) => {
  // The DB persists across specs in one invocation - count relatively.
  // The baseline comes from the API (the DOM count races the initial fetch).
  await openAttachments(page);
  const cards = page.locator('[data-testid^="attachment-card-"]');
  const before =
    (await (await request.get("http://127.0.0.1:17321/projects/1/attachments")).json()).length;
  await expect(cards).toHaveCount(before);
  await uploadTraffic(page);
  await expect(cards).toHaveCount(before + 1);
  await cards.first().locator('[data-testid^="attachment-revision-"]').setInputFiles({
    name: "traffic-v2.pdf", mimeType: "application/pdf", buffer: MIN_PDF,
  });
  // A new card appears, marked as revision, ALREADY reviewed (auto-run).
  await expect(cards).toHaveCount(before + 2);
  const rev = cards.last();
  await expect(rev).toContainText("גרסה מתוקנת");
  await expect(rev.locator('[data-testid^="attachment-report-"]')).toBeVisible();
});

test("1f closure: UI-added guideline flows into its discipline's attachment review", async ({ page, request }) => {
  // Add a gardens guideline via the UI...
  await page.goto("/#/guidelines");
  await page.getByTestId("add-guideline-global").click();
  await page.getByTestId("add-guideline-discipline").selectOption("sec-3-2");
  await page.getByTestId("add-guideline-title").fill("הנחיית גינון לבדיקת נספח");
  await page.getByTestId("add-guideline-body").fill("נוסח הנחיה לבדיקת זרימה אל בדיקת הנספח.");
  await page.getByTestId("add-guideline-save").click();
  await expect(page.getByTestId("guidelines-group-sec-3-2")
    .getByText("הנחיית גינון לבדיקת נספח")).toBeVisible();

  // ...upload a gardens attachment and run its review - zero extra config.
  await openAttachments(page);
  await page.getByTestId("attachment-type").selectOption("sec-3-2");
  await page.getByTestId("attachment-version").fill("v1");
  await page.getByTestId("attachment-file").setInputFiles({
    name: "gardens.pdf", mimeType: "application/pdf", buffer: MIN_PDF,
  });
  await page.getByTestId("attachment-upload-submit").click();
  // Pin the exact new card by its API id (last() is fragile in the
  // shared-DB run where earlier specs left attachments behind).
  const atts = await (await request.get("http://127.0.0.1:17321/projects/1/attachments")).json();
  const gardens = atts.filter((a: { discipline_key: string }) => a.discipline_key === "sec-3-2").pop();
  const card = page.getByTestId(`attachment-card-${gardens.id}`);
  await expect(card).toBeVisible();
  await card.getByTestId(`attachment-run-review-${gardens.id}`).click();
  await expect(card.getByTestId(`attachment-review-${gardens.id}`))
    .toContainText("הנחיית גינון לבדיקת נספח");
});

test("attachments: comment linkage + דוח התייחסות", async ({ page, request }) => {
  await openAttachments(page);
  await uploadTraffic(page);
  const card = page.locator('[data-testid^="attachment-card-"]').first();
  await card.locator('[data-testid^="attachment-run-review-"]').click();
  await expect(card.locator('[data-testid^="attachment-review-"]')).toBeVisible();

  // Link a comment to the attachment from the comments tab.
  await page.getByTestId("tab-comments").click();
  await page.getByTestId("comment-attachment-link").selectOption({ index: 1 });
  await page.locator(".add-comment-grid select").first().selectOption("sec-3-4");
  await page.locator(".add-comment-grid select").nth(1).selectOption({ index: 1 });
  await page.locator(".add-comment-grid input").first().fill("הערה מקושרת לנספח");
  await page.locator(".add-comment-grid textarea").fill("בדיקת קישור הערה לנספח התנועה.");
  await page.getByRole("button", { name: "+ הוסיפי הערה" }).click();
  await expect(page.getByText("הערה מקושרת לנספח").first()).toBeVisible();

  // The comment is persisted with attachment_id.
  const comments = await (await request.get("http://127.0.0.1:17321/submissions/1/comments")).json();
  const linked = comments.find((c: { topic_he: string }) => c.topic_he === "הערה מקושרת לנספח");
  expect(linked?.attachment_id).not.toBeNull();

  // The report button calls the sidecar open-endpoint (NOT an <a download>,
  // which the packaged WebView2 shell blocks silently).
  const reportCall = page.waitForRequest(
    (r) => /\/attachments\/\d+\/open-report$/.test(r.url()) && r.method() === "POST",
  );
  await page.getByTestId("tab-attachments").click();
  await card.locator('[data-testid^="attachment-report-"]').click();
  expect((await (await reportCall).response())?.status()).toBe(204);

  // ...and that report really is a PDF including the linked comment.
  const atts = await (await request.get("http://127.0.0.1:17321/projects/1/attachments")).json();
  const rep = await request.get(`http://127.0.0.1:17321/attachments/${atts[0].id}/report-pdf`);
  expect(rep.status()).toBe(200);
  const buf = await rep.body();
  expect(buf.subarray(0, 4).toString("ascii")).toBe("%PDF");
  expect(buf.length).toBeGreaterThan(1000);
});
