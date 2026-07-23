import { test as base, expect, Page } from "@playwright/test";

// Layer 1c — the class-killer: after EVERY test's final render, no raw API
// text may be visible anywhere in the DOM. Import { test, expect } from this
// file instead of @playwright/test and the assertion runs automatically.

export const LEAK_MARKERS = ["HTTP 4", "HTTP 5", "GET /", "POST /", "PATCH /", '"detail"', "→ HTTP"];

export async function assertNoDomLeakage(page: Page): Promise<void> {
  if (page.isClosed()) return;
  const body = await page.locator("body").innerText().catch(() => "");
  for (const marker of LEAK_MARKERS) {
    expect(body, `raw API text leaked into visible DOM: ${marker}`).not.toContain(marker);
  }
}

export const test = base.extend({});
test.afterEach(async ({ page }) => {
  await assertNoDomLeakage(page);
});

export { expect };
