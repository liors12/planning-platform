import { test, expect } from "@playwright/test";
import { MIN_PDF } from "./helpers";

// Test 3: create a project, upload a PDF, verify the submission card renders.

test("upload: new project + PDF upload renders submission card", async ({ page }) => {
  await page.goto("/#/projects/new");
  await page.getByTestId("create-name-he").fill("פרויקט העלאה");
  await page.getByTestId("create-tava").fill("999-0000002");
  await page.getByTestId("create-submit").click();
  await expect(page).toHaveURL(/#\/projects\/\d+$/);

  await page.getByTestId("tab-submissions").click();
  await page.getByTestId("upload-version").fill("v1.0");
  await page.getByTestId("upload-pdf").setInputFiles({
    name: "test.pdf",
    mimeType: "application/pdf",
    buffer: MIN_PDF,
  });
  await page.getByTestId("upload-submit").click();

  const card = page.getByTestId("submission-card-v1.0");
  await expect(card).toBeVisible();
  await expect(page.getByTestId("submission-status-v1.0")).toHaveAttribute(
    "data-status", "uploaded",
  );
});
