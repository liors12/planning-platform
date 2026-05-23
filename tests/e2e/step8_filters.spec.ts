/**
 * Step 8 — verdict pills as filter toggles.
 *
 * Each section header's verdict pills (תקין, נדרש תיקון, …) are clickable
 * toggles. Default state hides passing/N/A verdicts, shows problem-shaped
 * ones. State is persisted to localStorage at `filters:project_{id}` so a
 * reload restores the same view.
 *
 * Acceptance scenarios (all 4 must pass):
 *   1. Default — only non-passing rows visible.
 *   2. Toggle — clicking the "תקין" pill (off → on) reveals passing
 *      rows; clicking again hides them.
 *   3. Persistence — toggle, reload, state survives.
 *   4. Empty state — turning every pill off in one section shows the
 *      "אין סעיפים להצגה. הפעל מסננים בכותרת." message instead of an
 *      empty list.
 *
 * Pre-reqs: Vite (1420) + sidecar (17321) up. Project
 * "מתחם הטייסים-ההסתדרות" (407-1048248) exists with a completed
 * submission and findings JSON.
 */

import { test, expect, Page } from "@playwright/test";

const PROJECT_NAME_HE = "מתחם הטייסים-ההסתדרות";

// IDs we'll need to target one section deterministically. Discipline
// section is "בדיקה רב-תחומית". We'll use the `data-section` attribute
// added in Step 8 to scope selectors to a single section.
const DISCIPLINES_SECTION = '[data-section="disciplines"]';
const CONTENT_SECTION = '[data-section="content"]';

const PILL_PASS = '.verdict-pill-toggle[data-verdict="pass"]';
const PILL_FAIL = '.verdict-pill-toggle[data-verdict="fail"]';

/**
 * Navigate from home → project → Findings tab. Waits until at least one
 * finding row is visible (means the engine output loaded). Returns once
 * the page is in a stable, post-render state.
 */
async function openProjectFindings(page: Page) {
  await page.goto("/", { waitUntil: "networkidle" });
  // The startup-race fix (Task #14) retries fetch up to ~2.2s; give it
  // breathing room before clicking.
  await page.waitForTimeout(3500);
  await page
    .locator(".sidebar-item a", { hasText: PROJECT_NAME_HE })
    .first()
    .click();
  await page.locator('nav.tabs button.tab', { hasText: "ממצאים" }).first().click();
  // Findings load is lazy — wait for at least one row.
  await page.locator(".finding-row").first().waitFor({ state: "visible", timeout: 20_000 });
}

/**
 * Count rows in a section that match a verdict. We use the verdict-badge
 * text since the same span renders per row.
 */
async function rowsWithVerdict(page: Page, sectionSel: string, verdictLabelHe: string): Promise<number> {
  return await page
    .locator(`${sectionSel} .finding-row .verdict-badge`, { hasText: verdictLabelHe })
    .count();
}

test.describe("Step 8 — findings filter pills", () => {
  // Playwright Test gives each test its own browser context (so its own
  // localStorage). No explicit clear needed across tests — and we MUST
  // NOT use addInitScript to wipe, because it re-runs on every
  // navigation including page.reload(), which would break the
  // persistence test by clearing the state we just wrote.

  test("1. default state — passing rows are hidden, problem rows are shown", async ({ page }) => {
    await openProjectFindings(page);

    // Discipline section as the witness: in the v24.3 baseline it has
    // 9 pass + 8 fail + 16 requires_review. Default filters hide 'pass',
    // show 'fail' and 'requires_review'.
    const passRows = await rowsWithVerdict(page, DISCIPLINES_SECTION, "תקין");
    const failRows = await rowsWithVerdict(page, DISCIPLINES_SECTION, "נדרש תיקון");
    const reviewRows = await rowsWithVerdict(page, DISCIPLINES_SECTION, "דורש בירור");

    expect(passRows, "passing rows must be filtered out by default").toBe(0);
    expect(failRows, "failing rows must be visible by default").toBeGreaterThan(0);
    expect(reviewRows, "requires_review rows must be visible by default").toBeGreaterThan(0);

    // The "תקין" pill must exist (count > 0) and be in the OFF state.
    const passPill = page.locator(`${DISCIPLINES_SECTION} ${PILL_PASS}`);
    await expect(passPill).toBeVisible();
    await expect(passPill).toHaveAttribute("aria-pressed", "false");
    // …while a problem pill must be in the ON state.
    const failPill = page.locator(`${DISCIPLINES_SECTION} ${PILL_FAIL}`);
    await expect(failPill).toBeVisible();
    await expect(failPill).toHaveAttribute("aria-pressed", "true");
  });

  test("2. toggle — clicking תקין shows passing rows, clicking again hides them", async ({ page }) => {
    await openProjectFindings(page);

    const passPill = page.locator(`${DISCIPLINES_SECTION} ${PILL_PASS}`);
    expect(await rowsWithVerdict(page, DISCIPLINES_SECTION, "תקין")).toBe(0);

    // Off → On
    await passPill.click();
    await expect(passPill).toHaveAttribute("aria-pressed", "true");
    expect(
      await rowsWithVerdict(page, DISCIPLINES_SECTION, "תקין"),
      "passing rows must appear after enabling תקין pill",
    ).toBeGreaterThan(0);

    // On → Off
    await passPill.click();
    await expect(passPill).toHaveAttribute("aria-pressed", "false");
    expect(
      await rowsWithVerdict(page, DISCIPLINES_SECTION, "תקין"),
      "passing rows must disappear after disabling תקין pill",
    ).toBe(0);
  });

  test("3. persistence — toggle תקין, reload, state restored", async ({ page }) => {
    await openProjectFindings(page);

    const passPill = page.locator(`${DISCIPLINES_SECTION} ${PILL_PASS}`);
    await passPill.click(); // off → on
    await expect(passPill).toHaveAttribute("aria-pressed", "true");

    // Read what we just wrote so the assertion later is meaningful.
    const stored = await page.evaluate(() => {
      const keys = Object.keys(localStorage).filter((k) => k.startsWith("filters:project_"));
      return keys.length === 1 ? { key: keys[0], val: JSON.parse(localStorage.getItem(keys[0])!) } : null;
    });
    expect(stored, "exactly one filters:project_* entry must exist").not.toBeNull();
    expect(stored!.val?.disciplines?.pass, "disciplines.pass must be true in localStorage").toBe(true);

    // Reload — but DON'T clear localStorage this time. We override the
    // beforeEach guard by re-navigating directly.
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(3500);
    // Sidebar drops us back at home after reload; re-enter project.
    await page.locator(".sidebar-item a", { hasText: PROJECT_NAME_HE }).first().click();
    await page.locator('nav.tabs button.tab', { hasText: "ממצאים" }).first().click();
    await page.locator(".finding-row").first().waitFor({ state: "visible", timeout: 20_000 });

    await expect(passPill).toHaveAttribute("aria-pressed", "true");
    expect(
      await rowsWithVerdict(page, DISCIPLINES_SECTION, "תקין"),
      "passing rows must still be visible after reload",
    ).toBeGreaterThan(0);
  });

  test("4. empty state — turn off every pill in content section, see the Hebrew message", async ({ page }) => {
    await openProjectFindings(page);

    // Click every ON pill in the content section so the section ends up
    // with no enabled verdicts. The default-OFF pills are already off.
    const onPills = page.locator(`${CONTENT_SECTION} .verdict-pill-toggle[aria-pressed="true"]`);
    const n = await onPills.count();
    expect(n, "content section must start with at least one ON pill").toBeGreaterThan(0);
    for (let i = 0; i < n; i++) {
      // Always click the first remaining ON pill — the selector re-resolves.
      await page.locator(`${CONTENT_SECTION} .verdict-pill-toggle[aria-pressed="true"]`).first().click();
    }
    // No more ON pills in content section
    await expect(page.locator(`${CONTENT_SECTION} .verdict-pill-toggle[aria-pressed="true"]`)).toHaveCount(0);

    // Empty-filtered message must appear, and there must be zero rows.
    await expect(
      page.locator(`${CONTENT_SECTION} .findings-empty-filtered`),
    ).toHaveText("אין סעיפים להצגה. הפעל מסננים בכותרת.");
    expect(
      await page.locator(`${CONTENT_SECTION} .finding-row`).count(),
      "no rows should be visible when every pill is off",
    ).toBe(0);
  });
});
