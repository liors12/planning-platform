import { test, expect } from "./fixtures";

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
