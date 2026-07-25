import { test, expect } from "./fixtures";

// Phase A specs - summary bar + actionable-first default (A1), explicit
// filter bar + search (A2), PDF-pane collapse + chip clipping (A3 + add-2).
// All run against the fresh seeded pilot (findings staged by the seed).

async function openFindings(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByTestId("home-project-link-407-1048248").click();
  await page.getByTestId("tab-findings").click();
  await expect(page.getByTestId("findings-summary")).toBeVisible();
}

test("A1: actionable-first default hides תקין; toggle reveals all", async ({ page }) => {
  await openFindings(page);
  // Summary bar shows total + actionable counts.
  await expect(page.getByTestId("findings-summary")).toContainText("סעיפים נבדקו");
  await expect(page.getByTestId("findings-summary")).toContainText("דורשים את תשומת ליבך");

  // Default: no passing rows on screen (v-ok badges hidden).
  expect(await page.locator(".finding-row .verdict-badge.v-ok").count()).toBe(0);
  const defaultRows = await page.locator(".finding-row").count();
  expect(defaultRows).toBeGreaterThan(0);

  // Toggle reveals the passing/NA rows too.
  await page.getByTestId("findings-show-all-toggle").click();
  expect(await page.locator(".finding-row .verdict-badge.v-ok").count()).toBeGreaterThan(0);
  const allRows = await page.locator(".finding-row").count();
  expect(allRows).toBeGreaterThan(defaultRows);
});

test("A2: search narrows results; clear-filters restores", async ({ page }) => {
  await openFindings(page);
  const before = await page.locator(".finding-row").count();
  await page.getByTestId("findings-search").fill("צובר");
  await expect
    .poll(async () => page.locator(".finding-row").count())
    .toBeLessThan(before);
  // Every visible row matches the search term.
  const texts = await page.locator(".finding-row").allInnerTexts();
  for (const t of texts) expect(t).toContain("צובר");
  await page.getByTestId("findings-clear-filters").click();
  await expect
    .poll(async () => page.locator(".finding-row").count())
    .toBe(before);
});

test("A2: status pill filters by pressed state", async ({ page }) => {
  await openFindings(page);
  await page.getByRole("button", { name: "לא הוגש", exact: true }).click();
  // Only not_submitted rows remain (v-fail class is shared, so assert by
  // badge text).
  const labels = await page.locator(".finding-row .verdict-badge").allInnerTexts();
  expect(labels.length).toBeGreaterThan(0);
  for (const l of labels) expect(l).toBe("לא הוגש");
  await page.getByTestId("findings-clear-filters").click();
});

test("A3 + add-2: pilot renders full-width with slim bar; chips not clipped @1024x700", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 700 });
  await openFindings(page);
  // Seeded pilot has no plan PDF -> slim explanatory bar + full-width list.
  await expect(page.getByTestId("pdf-unavailable-bar")).toBeVisible();
  await expect(page.getByTestId("pdf-unavailable-bar"))
    .toContainText("קובץ התכנית של הגשת הדוגמה אינו כלול בתוכנה");

  // No horizontal overflow.
  const overflowX = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflowX).toBeLessThanOrEqual(0);

  // Add-2 regression: discipline chips are fully inside their section card
  // (they used to be cut at the card's bottom edge by flex compression).
  const clipped = await page.evaluate(() => {
    const out: string[] = [];
    document.querySelectorAll(".finding-tag-discipline").forEach((chip) => {
      const section = chip.closest(".findings-section");
      if (!section) return;
      const c = chip.getBoundingClientRect();
      const s = section.getBoundingClientRect();
      if (c.bottom > s.bottom + 0.5 || c.top < s.top - 0.5) {
        out.push((chip.textContent ?? "").trim());
      }
    });
    return out;
  });
  expect(clipped, `clipped chips: ${clipped.join(", ")}`).toHaveLength(0);
});
