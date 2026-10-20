import { test, expect } from "./fixtures";

// v0.2.3 §3 a-c - the project overview tab, against the seeded pilot
// (407-1048248, approved 06.08.2025 per its schema and Mavat).

async function openOverview(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-overview").click();
}

test("overview: the tab is called סקירה כללית", async ({ page }) => {
  await openOverview(page);
  await expect(page.getByTestId("tab-overview")).toHaveText("סקירה כללית");
});

test("overview: time since the תב\"ע was approved, with the date", async ({ page }) => {
  await openOverview(page);
  const age = page.getByTestId("overview-tava-age");
  await expect(age).toContainText("06.08.2025");
  // The wording depends on today's date; its SHAPE does not.
  await expect(age).toHaveText(/^(פחות מחודש|חודש|חודשיים|\d+ חודשים|שנה|שנתיים|\d+ שנים)( ו-?\S.*)?\s*\(אושרה ב-06\.08\.2025\)$/);
  await expect(age).not.toContainText("תאריך אישור חסר");
});

test("overview: architecture firm - 'לא זוהה' until Ellen enters it, then kept", async ({ page }) => {
  await openOverview(page);
  await expect(page.getByTestId("overview-architect")).toHaveText("לא זוהה");
  await page.getByTestId("overview-architect-edit").click();
  await page.getByTestId("overview-architect-input").fill('קיקה ברא"ז אדריכלים');
  await page.getByTestId("overview-architect-save").click();
  await expect(page.getByTestId("overview-architect")).toHaveText('קיקה ברא"ז אדריכלים');
  await page.reload();
  await page.getByTestId("tab-overview").click();
  await expect(page.getByTestId("overview-architect")).toHaveText('קיקה ברא"ז אדריכלים');
  // put it back so later specs see the seeded state
  await page.getByTestId("overview-architect-edit").click();
  await page.getByTestId("overview-architect-input").fill("");
  await page.getByTestId("overview-architect-save").click();
  await expect(page.getByTestId("overview-architect")).toHaveText("לא זוהה");
});
