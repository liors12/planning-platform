import { test, expect } from "./fixtures";

// Layer 1a+1b — per-screen empty/error states and precondition affordances,
// asserted on the deterministic fresh-seed DB. The afterEach in fixtures.ts
// adds the Layer-1c DOM-leakage assertion to every test here.

test("dashboard: renders seeded pilot; zero-count pills muted, nonzero emphasized", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("home-project-link-407-1048248")).toBeVisible();
  // Layer 3b — codified judgment: seeded pilot is one draft-stage submission.
  await expect(page.locator(".pipeline-card.ps-draft")).not.toHaveClass(/ps-zero/);
  for (const stage of ["sent", "response_received", "verified"]) {
    await expect(page.locator(`.pipeline-card.ps-${stage}`)).toHaveClass(/ps-zero/);
  }
});

test("findings: fresh seed renders findings immediately (F-1 fix)", async ({ page }) => {
  // The seed stages findings.json from the bundled audit_results, so a
  // fresh install shows real findings with no engine run and no 409.
  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-findings").click();
  await expect(page.locator('[data-section="disciplines"]')).toBeVisible();
  await expect(page.locator('[data-section="content"]')).toBeVisible();
  await expect(page.locator('[data-section="format"]')).toBeVisible();
});

test("findings: a no-findings 409 still renders the friendly empty state", async ({ page }) => {
  // The 409 path no longer occurs on a fresh seed, but it remains reachable
  // (e.g. findings deleted on disk between engine runs). Pin the UI contract
  // by intercepting the findings request with the exact sidecar signature.
  await page.route("**/submissions/*/findings", (route) =>
    route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({
        detail: "submission 1 has no findings yet (status='complete'). POST /submissions/{id}/run-engine first.",
      }),
    }),
  );
  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-findings").click();
  await expect(page.getByTestId("findings-empty-state")).toBeVisible();
});

test("CAD: scan disabled without DXF, hint shown", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-cad_layers").click();
  await expect(page.getByTestId("layer-mapping-discover-btn")).toBeDisabled();
  await expect(page.getByTestId("layer-mapping-no-dxf-hint")).toBeVisible();
});

test("comments: gated before an audit exists on a schema-less project", async ({ page, request }) => {
  const r = await request.post("http://127.0.0.1:17321/projects", {
    data: { name_he: "פרויקט ללא בדיקה", tava_number: "999-0000077" },
  });
  const pid = (await r.json()).id;
  await page.goto(`/#/projects/${pid}`);
  await page.getByTestId("tab-comments").click();
  await expect(page.getByTestId("comments-gated")).toBeVisible();
});

test("run-engine affordance: disabled without schema data", async ({ page, request }) => {
  const r = await request.post("http://127.0.0.1:17321/projects", {
    data: { name_he: "פרויקט בלי נתוני תבע", tava_number: "999-0000078" },
  });
  const pid = (await r.json()).id;
  await page.goto(`/#/projects/${pid}`);
  await page.getByTestId("tab-submissions").click();
  await page.getByTestId("upload-version").fill("v1.0");
  await page.getByTestId("upload-pdf").setInputFiles({
    name: "t.pdf", mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4\n%%EOF\n"),
  });
  await page.getByTestId("upload-submit").click();
  await expect(page.getByTestId("submission-card-v1.0")).toBeVisible();
  await expect(page.getByTestId("run-engine-v1.0")).toBeDisabled();
});

test("re-run without a stored PDF: Hebrew explanation, not the generic failure", async ({ page }) => {
  // The seeded pilot has findings but ships no source PDF - clicking
  // "הפעילי שוב את התוכנה" must explain that honestly (the addendum bug:
  // it surfaced as the unrelated generic 'אירעה תקלה ביצירת הדוח').
  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-submissions").click();
  await page.getByTestId("run-engine-v24.3").click();
  await expect(page.getByText(/קובץ התכנית של גרסה זו אינו שמור/).first()).toBeVisible();
  const body = await page.locator("body").innerText();
  expect(body).not.toContain("אירעה תקלה ביצירת הדוח");
});

test("comparison affordance: disabled when no revised version exists", async ({ page }) => {
  // The seeded pilot has audit results but is not a revision of anything -
  // the comparison button must be visible-but-disabled with the hint.
  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-submissions").click();
  const btn = page.getByTestId("generate-comparison-v24.3");
  await expect(btn).toBeVisible();
  await expect(btn).toBeDisabled();
  await expect(btn).toHaveAttribute("title", "אין גרסה מתוקנת להשוואה");
});

test("guidelines + settings: load without errors", async ({ page }) => {
  await page.goto("/#/guidelines");
  await expect(page.locator('[data-check-key="glass_railing_min_height_cm"]')).toBeVisible();
  await page.goto("/#/settings");
  await expect(page.getByTestId("gemini-key-missing").or(page.getByTestId("gemini-key-set"))).toBeVisible();
});
