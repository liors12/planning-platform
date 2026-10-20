import { test, expect } from "./fixtures";
import { MIN_PDF, TITLE_BLOCK_ONLY_PDF, ANNOTATED_PDF, MIXED_PDF } from "./helpers";

// v0.2.0 Phase 2f - attachments tab specs. All against the seeded pilot.

async function openAttachments(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-attachments").click();
}

// v0.2.3: an upload runs its check by itself and ends on "הבדיקה הסתיימה".
// Wait for THAT, and return the new card by its id - with newest-on-top,
// "the first card" is whatever was on top before the upload landed.
async function awaitUploaded(page: import("@playwright/test").Page) {
  const done = page.locator('[data-testid^="attachment-done-"]');
  await expect(done).toBeVisible();
  const id = Number((await done.getAttribute("data-testid"))!.split("-").pop());
  return { id, card: page.getByTestId(`attachment-card-${id}`) };
}

async function uploadTraffic(page: import("@playwright/test").Page) {
  await page.getByTestId("attachment-type").selectOption("sec-3-4");
  await page.getByTestId("attachment-file").setInputFiles({
    name: "traffic.pdf", mimeType: "application/pdf", buffer: MIN_PDF,
  });
  await page.getByTestId("attachment-upload-submit").click();
  return awaitUploaded(page);
}

test("attachments: upload with type renders a card", async ({ page }) => {
  await openAttachments(page);
  await expect(page.getByTestId("attachments-empty")).toBeVisible();
  const { id: newId, card } = await uploadTraffic(page);
  await expect(card).toBeVisible();
  await expect(card).toContainText("תנועה");
  await expect(card).toContainText("הוכן");
});

test("attachments: mapped-only review - traffic checks in, gan-yard out", async ({ page }) => {
  await openAttachments(page);
  const { id: newId, card } = await uploadTraffic(page);
  await card.locator('[data-testid^="attachment-toggle-"]').click();   // rows start collapsed
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

test("attachments v0.2.1: כללי format sub-group runs, booklet sub-group does not",
  async ({ page, request }) => {
  await openAttachments(page);
  const { id: newId, card } = await uploadTraffic(page);
  await card.locator('[data-testid^="attachment-toggle-"]').click();   // rows start collapsed
  await card.locator('[data-testid^="attachment-run-review-"]').click();
  await expect(card.locator('[data-testid^="attachment-review-"]')).toBeVisible();

  const atts = await (await request.get("http://127.0.0.1:17321/projects/1/attachments")).json();
  const review = await (await request.get(
    `http://127.0.0.1:17321/attachments/${newId}/review`)).json();
  // Match on rule_code (GUIDE_<id>), NOT on title: titles legitimately repeat
  // across sub-groups (e.g. "חתכים" is both a required CAD file in חלק א and
  // a booklet section in חלק ב), so a title comparison reports false leaks.
  const codes: string[] = review.checks.map((c: { rule_code: string }) => c.rule_code);

  // Pull the real rows from the API so the spec cannot drift from the seed.
  // Keyed on section_key, the structural id - never on the Hebrew section
  // title (B-23: the old mapping matched 'חלק א - פורמט קבצים' by title).
  const rows = await (await request.get("http://127.0.0.1:17321/guidelines")).json();
  const generalIds = (section: string) => rows
    .filter((g: { discipline_key: string; section_key: string | null }) =>
      g.discipline_key === "general" && g.section_key === section)
    .map((g: { id: number }) => `ATTACH_GUIDE_${g.id}`);

  const formatCodes = generalIds("part_a");
  const bookletCodes = generalIds("part_b");
  expect(formatCodes.length).toBeGreaterThan(0);
  expect(bookletCodes.length).toBeGreaterThan(0);

  // v0.2.3 (B-23): NO כללי row runs on a traffic sheet. Until v0.2.2 all 25
  // 'חלק א' rows did - the booklet's file rules and required-files list - and
  // a real traffic appendix answered 'לא הוגש' to fonts, page size and the
  // hydrology annex. The sheet's own file quality is ATTACH_FILE_*.
  for (const c of formatCodes) expect(codes).not.toContain(c);
  for (const c of bookletCodes) expect(codes).not.toContain(c);
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
  await cards.first().locator('[data-testid^="attachment-toggle-"]').click();
  await cards.first().locator('[data-testid^="attachment-revision-"]').setInputFiles({
    name: "traffic-v2.pdf", mimeType: "application/pdf", buffer: MIN_PDF,
  });
  // A new card appears, marked as revision, ALREADY reviewed (auto-run).
  await expect(cards).toHaveCount(before + 2);
  const rev = cards.first();   // v0.2.3: newest on top
  await expect(rev).toContainText("גרסה מתוקנת");
  await expect(rev.locator('[data-testid^="attachment-report-"]')).toBeVisible();
});

test("v0.2.3: versions are numbered by the app - גרסה 1, then 2, then 3", async ({ page, request }) => {
  await openAttachments(page);
  await expect(page.getByTestId("attachment-version")).toHaveCount(0);   // no free-text input
  await uploadTraffic(page);
  const api = "http://127.0.0.1:17321";
  const first = (await (await request.get(`${api}/projects/1/attachments`)).json()).pop();
  expect(first.version_number).toBe(1);
  await expect(page.getByTestId(`attachment-version-${first.id}`)).toHaveText("גרסה 1");
  // two revisions of the SAME source: 2 and 3, never two 2s
  for (const expected of [2, 3]) {
    const r = await request.post(`${api}/attachments/${first.id}/revision`, {
      multipart: { file: { name: `traffic-r${expected}.pdf`, mimeType: "application/pdf", buffer: MIN_PDF } },
    });
    expect((await r.json()).version_number).toBe(expected);
  }
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
  await page.getByTestId("attachment-file").setInputFiles({
    name: "gardens.pdf", mimeType: "application/pdf", buffer: MIN_PDF,
  });
  await page.getByTestId("attachment-upload-submit").click();
  await awaitUploaded(page);
  // Pin the exact new card by its API id (last() is fragile in the
  // shared-DB run where earlier specs left attachments behind).
  const atts = await (await request.get("http://127.0.0.1:17321/projects/1/attachments")).json();
  const gardens = atts.filter((a: { discipline_key: string }) => a.discipline_key === "sec-3-2").pop();
  const card = page.getByTestId(`attachment-card-${gardens.id}`);
  await expect(card).toBeVisible();
  await card.getByTestId(`attachment-toggle-${gardens.id}`).click();   // rows start collapsed
  await card.getByTestId(`attachment-run-review-${gardens.id}`).click();
  await expect(card.getByTestId(`attachment-review-${gardens.id}`))
    .toContainText("הנחיית גינון לבדיקת נספח");
});

test("attachments: comment linkage + דוח התייחסות", async ({ page, request }) => {
  await openAttachments(page);
  const { id: newId, card } = await uploadTraffic(page);
  await card.locator('[data-testid^="attachment-toggle-"]').click();   // rows start collapsed
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
  const reportBtn = card.locator('[data-testid^="attachment-report-"]');
  await reportBtn.click();
  expect((await (await reportCall).response())?.status()).toBe(204);
  await expect(reportBtn).toHaveAttribute("data-pdf-state", "opened");
  await expect(reportBtn).toContainText("הקובץ נפתח");

  // ...and that report really is a PDF including the linked comment.
  const atts = await (await request.get("http://127.0.0.1:17321/projects/1/attachments")).json();
  const rep = await request.get(`http://127.0.0.1:17321/attachments/${atts[0].id}/report-pdf`);
  expect(rep.status()).toBe(200);
  const buf = await rep.body();
  expect(buf.subarray(0, 4).toString("ascii")).toBe("%PDF");
  expect(buf.length).toBeGreaterThan(1000);
});

test("v0.2.2: no text layer SUPPRESSES לא הוגש entirely", async ({ page, request }) => {
  // Ellen's common case: a DWFX or CAD-exported PDF whose annotations are
  // vector graphics. We cannot read it, so "not found" would mean "I cannot
  // read this file" - never "the architect omitted it". ZERO findings may
  // say לא הוגש, and a notice must say why detection did not run.
  await openAttachments(page);
  await page.getByTestId("attachment-type").selectOption("sec-3-4");
  await page.getByTestId("attachment-file").setInputFiles({
    name: "vector-only.pdf", mimeType: "application/pdf", buffer: MIN_PDF,
  });
  await page.getByTestId("attachment-upload-submit").click();
  await awaitUploaded(page);

  const atts = await (await request.get("http://127.0.0.1:17321/projects/1/attachments")).json();
  const att = atts.filter((a: { file_path: string }) => a.file_path.endsWith("vector-only.pdf")).pop();
  const card = page.getByTestId(`attachment-card-${att.id}`);
  await expect(card).toBeVisible();
  await card.getByTestId(`attachment-toggle-${att.id}`).click();   // rows start collapsed
  await card.getByTestId(`attachment-run-review-${att.id}`).click();
  await expect(card.getByTestId(`attachment-review-${att.id}`)).toBeVisible();

  const review = await (await request.get(
    `http://127.0.0.1:17321/attachments/${att.id}/review`)).json();
  const notSubmitted = review.checks.filter(
    (c: { verdict: string }) => c.verdict === "not_submitted");
  expect(notSubmitted).toHaveLength(0);
  expect(review.text_layer_ok).toBe(false);
  expect(review.notice_he).toContain("לא בוצעה");
  // The notice leads the findings list.
  expect(review.checks[0].rule_code).toBe("ATTACH_NO_TEXT_LAYER_NOTICE");
});

test("v0.2.2: 60 sheets of title blocks only - ZERO לא הוגש", async ({ page, request }) => {
  // The case that broke the first threshold. A real submission is ~60 CAD
  // sheets; each carries a title block and nothing else as text. Document-wide
  // that is ~2000 characters, which passes ANY per-document threshold and
  // re-enables presence detection on a file we cannot read. Per page it is
  // ~34 characters. Readability must be judged PER PAGE.
  await openAttachments(page);
  await page.getByTestId("attachment-type").selectOption("sec-3-4");
  await page.getByTestId("attachment-file").setInputFiles({
    name: "sheets.pdf", mimeType: "application/pdf", buffer: TITLE_BLOCK_ONLY_PDF,
  });
  await page.getByTestId("attachment-upload-submit").click();
  await awaitUploaded(page);

  const atts = await (await request.get("http://127.0.0.1:17321/projects/1/attachments")).json();
  const att = atts.filter((a: { file_path: string }) => a.file_path.endsWith("sheets.pdf")).pop();
  const card = page.getByTestId(`attachment-card-${att.id}`);
  await expect(card).toBeVisible();
  await card.getByTestId(`attachment-toggle-${att.id}`).click();   // rows start collapsed
  await card.getByTestId(`attachment-run-review-${att.id}`).click();
  await expect(card.getByTestId(`attachment-review-${att.id}`)).toBeVisible();

  const review = await (await request.get(
    `http://127.0.0.1:17321/attachments/${att.id}/review`)).json();
  const notSubmitted = review.checks.filter(
    (c: { verdict: string }) => c.verdict === "not_submitted");
  expect(notSubmitted).toHaveLength(0);
  expect(review.text_layer_ok).toBe(false);
});

test("v0.2.2: densely annotated PDF with no matching markers yields לא הוגש", async ({ page, request }) => {
  // The other half: when pages carry real annotation text (~635 chars each),
  // the document IS readable and absence of every marker is real evidence.
  // Without this the suppression could be satisfied by never emitting לא הוגש.
  await openAttachments(page);
  await page.getByTestId("attachment-type").selectOption("sec-3-4");
  await page.getByTestId("attachment-file").setInputFiles({
    name: "annotated.pdf", mimeType: "application/pdf", buffer: ANNOTATED_PDF,
  });
  await page.getByTestId("attachment-upload-submit").click();
  await awaitUploaded(page);

  const atts = await (await request.get("http://127.0.0.1:17321/projects/1/attachments")).json();
  const att = atts.filter((a: { file_path: string }) => a.file_path.endsWith("annotated.pdf")).pop();
  const card = page.getByTestId(`attachment-card-${att.id}`);
  await expect(card).toBeVisible();
  await card.getByTestId(`attachment-toggle-${att.id}`).click();   // rows start collapsed
  await card.getByTestId(`attachment-run-review-${att.id}`).click();
  await expect(card.getByTestId(`attachment-review-${att.id}`)).toBeVisible();

  const review = await (await request.get(
    `http://127.0.0.1:17321/attachments/${att.id}/review`)).json();
  expect(review.text_layer_ok).toBe(true);
  const guideline = review.checks.filter(
    (c: { guideline_id?: number }) => c.guideline_id !== undefined);
  const notSubmitted = guideline.filter(
    (c: { verdict: string }) => c.verdict === "not_submitted").length;
  expect(guideline.length).toBeGreaterThan(3);
  expect(notSubmitted).toBeGreaterThan(guideline.length / 2);
});

test("v0.2.2: MIXED document - readable overall, some vector sheets", async ({ page, request }) => {
  // The silent case. 4 annotated sheets + 4 title-block sheets clears the 0.5
  // ratio, so the ratio rule alone would switch suppression off and report
  // לא הוגש for anything living on the vector half - with nothing on screen
  // to warn Ellen. ZERO לא הוגש, and a notice naming the page count.
  await openAttachments(page);
  await page.getByTestId("attachment-type").selectOption("sec-3-4");
  await page.getByTestId("attachment-file").setInputFiles({
    name: "mixed.pdf", mimeType: "application/pdf", buffer: MIXED_PDF,
  });
  await page.getByTestId("attachment-upload-submit").click();
  await awaitUploaded(page);

  const atts = await (await request.get("http://127.0.0.1:17321/projects/1/attachments")).json();
  const att = atts.filter((a: { file_path: string }) => a.file_path.endsWith("mixed.pdf")).pop();
  const card = page.getByTestId(`attachment-card-${att.id}`);
  await expect(card).toBeVisible();
  await card.getByTestId(`attachment-toggle-${att.id}`).click();   // rows start collapsed
  await card.getByTestId(`attachment-run-review-${att.id}`).click();
  await expect(card.getByTestId(`attachment-review-${att.id}`)).toBeVisible();

  const review = await (await request.get(
    `http://127.0.0.1:17321/attachments/${att.id}/review`)).json();
  expect(review.checks.filter((c: { verdict: string }) => c.verdict === "not_submitted"))
    .toHaveLength(0);
  // The census is reported, and the notice says how many sheets were skipped.
  expect(review.readable_pages).toBe(4);
  expect(review.unreadable_pages).toBe(4);
  expect(review.notice_he).toContain("4 מתוך 8");
  expect(review.checks[0].rule_code).toBe("ATTACH_NO_TEXT_LAYER_NOTICE");
});

test("v0.2.3: one attachment, several files (one PDF per תא שטח)", async ({ page, request }) => {
  await openAttachments(page);
  await page.getByTestId("attachment-type").selectOption("sec-3-4");
  await page.getByTestId("attachment-file").setInputFiles([
    { name: "plot-1.pdf", mimeType: "application/pdf", buffer: ANNOTATED_PDF },
    { name: "plot-2.pdf", mimeType: "application/pdf", buffer: ANNOTATED_PDF },
    { name: "plot-3.pdf", mimeType: "application/pdf", buffer: MIN_PDF },
  ]);
  await page.getByTestId("attachment-upload-submit").click();
  await awaitUploaded(page);
  const api = "http://127.0.0.1:17321";
  const atts = await (await request.get(`${api}/projects/1/attachments`)).json();
  const att = atts.filter((a: { file_path: string }) => a.file_path.endsWith("plot-1.pdf")).pop();
  expect(att.files.map((f: { name: string }) => f.name)).toEqual(["plot-1.pdf", "plot-2.pdf", "plot-3.pdf"]);
  await page.getByTestId(`attachment-toggle-${att.id}`).click();   // rows start collapsed
  await expect(page.getByTestId(`attachment-files-${att.id}`)).toContainText("3 קבצים");
  const review = await (await request.post(`${api}/attachments/${att.id}/run-review`)).json();
  expect(review.files).toHaveLength(3);
  // plot-3 has no text layer: absence proves nothing, for ANY file.
  expect(review.checks.filter((c: { verdict: string }) => c.verdict === "not_submitted")).toHaveLength(0);
});

test("v0.2.3: after upload the check runs by itself and says when the report is ready", async ({ page, request }) => {
  await openAttachments(page);
  await page.getByTestId("attachment-type").selectOption("sec-3-4");
  await page.getByTestId("attachment-file").setInputFiles({
    name: "auto-check.pdf", mimeType: "application/pdf", buffer: ANNOTATED_PDF,
  });
  await page.getByTestId("attachment-upload-submit").click();
  await awaitUploaded(page);
  const atts = await (await request.get("http://127.0.0.1:17321/projects/1/attachments")).json();
  const att = atts.filter((a: { file_path: string }) => a.file_path.endsWith("auto-check.pdf")).pop();
  const done = page.getByTestId(`attachment-done-${att.id}`);
  await expect(done).toHaveText(/הבדיקה הסתיימה - הדו"ח מוכן/);
  await expect(page.getByTestId(`attachment-checking-${att.id}`)).toHaveCount(0);
  await expect(page.getByTestId(`attachment-open-report-${att.id}`)).toHaveText('פתחי את הדו"ח');
  // no button had to be pressed for the review to exist
  const review = await request.get(`http://127.0.0.1:17321/attachments/${att.id}/review`);
  expect(review.status()).toBe(200);
});

test("v0.2.3: newest on top, every row collapsed until opened", async ({ page, request }) => {
  await openAttachments(page);
  await uploadTraffic(page);
  const atts = await (await request.get("http://127.0.0.1:17321/projects/1/attachments")).json();
  const newest = Math.max(...atts.map((a: { id: number }) => a.id));
  const cards = page.locator('[data-testid^="attachment-card-"]');
  await expect(cards.first()).toHaveAttribute("data-testid", `attachment-card-${newest}`);
  // collapsed: the row shows type, version, date, status - and nothing else
  const card = page.getByTestId(`attachment-card-${newest}`);
  await expect(card).toContainText("תנועה");
  await expect(card).toContainText("גרסה 1");
  await expect(page.getByTestId(`attachment-row-status-${newest}`)).toHaveText("הוכן");
  await expect(page.getByTestId(`attachment-body-${newest}`)).toHaveCount(0);
  for (const c of await cards.all()) {
    await expect(c.locator('[data-testid^="attachment-body-"]')).toHaveCount(0);
  }
  // the report button is on the row itself, once the check has run
  await expect(page.getByTestId(`attachment-report-${newest}`)).toBeVisible();
  await page.getByTestId(`attachment-toggle-${newest}`).click();
  await expect(page.getByTestId(`attachment-body-${newest}`)).toBeVisible();
  await expect(page.getByTestId(`attachment-toggle-${newest}`)).toHaveAttribute("aria-expanded", "true");
});
