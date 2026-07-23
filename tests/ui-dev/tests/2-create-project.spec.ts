import { test, expect } from "./fixtures";

// Round-2 addendum: create-project input validation.
// תב"ע allows digits/hyphens/slash/quotes/Hebrew only; name needs >=2 Hebrew
// letters; submit stays disabled while any field is invalid.

test("create project validation: Latin תב\"ע blocked, valid one succeeds", async ({ page, request }) => {
  await page.goto("/#/projects/new");
  await page.getByTestId("create-name-he").fill("פרויקט ולידציה");

  // Latin letters in תב"ע → red hint + disabled submit.
  await page.getByTestId("create-tava").fill("ABC-123");
  await expect(page.getByTestId("create-tava-hint")).toBeVisible();
  await expect(page.getByTestId("create-submit")).toBeDisabled();

  // Name with fewer than 2 Hebrew letters → its own hint + disabled submit.
  await page.getByTestId("create-tava").fill("407-1048299");
  await expect(page.getByTestId("create-tava-hint")).toHaveCount(0);
  await page.getByTestId("create-name-he").fill("a1");
  await expect(page.getByTestId("create-name-hint")).toBeVisible();
  await expect(page.getByTestId("create-submit")).toBeDisabled();

  // Valid values (407-1048248-style format; unused number to avoid the
  // seeded pilot's duplicate-tava guard) → creation succeeds.
  await page.getByTestId("create-name-he").fill("פרויקט ולידציה");
  await expect(page.getByTestId("create-submit")).toBeEnabled();
  await page.getByTestId("create-submit").click();
  await expect(page.getByTestId("tab-overview")).toBeVisible();

  // Cleanup: archive the project so the home "recent" list (capped at 5)
  // keeps showing the seeded pilot for the downstream flow specs.
  const pid = Number(new URL(page.url()).hash.match(/projects\/(\d+)/)![1]);
  await request.post(`http://127.0.0.1:17321/projects/${pid}/archive`);
});

// Test 2: manual project creation → redirect into the new workspace.

test("create project: manual form → workspace", async ({ page }) => {
  await page.goto("/#/projects/new");
  await page.getByTestId("create-name-he").fill("פרויקט בדיקה אוטומטית");
  await page.getByTestId("create-tava").fill("999-0000001");
  await page.getByTestId("create-submit").click();

  // Redirects to #/projects/<id>; the workspace tab bar renders.
  await expect(page).toHaveURL(/#\/projects\/\d+$/);
  await expect(page.getByTestId("tab-overview")).toBeVisible();
  await expect(page.getByTestId("tab-submissions")).toBeVisible();
});
