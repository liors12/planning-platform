// v0.2.2 pre-merge visual check (not a gate). The app scrolls an inner
// container, so fullPage is useless; instead hide every group but one and use
// a viewport tall enough to hold it.
import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
const OUT = process.env.VISUAL_OUT ?? path.join(__dirname, "../visual");

test("guidelines screen, as Ellen reads it", async ({ page }) => {
  fs.mkdirSync(OUT, { recursive: true });
  await page.setViewportSize({ width: 1400, height: 3600 });
  await page.goto("/#/guidelines");
  await page.locator('[data-check-key="glass_railing_min_height_cm"]').waitFor();

  const cards = page.locator("details.guidelines-group");
  const n = await cards.count();
  for (let i = 0; i < n; i++) await cards.nth(i).evaluate((d: any) => (d.open = false));
  const general = cards.nth(n - 1);
  await general.evaluate((d: any) => (d.open = true));

  const subs = general.locator("details.guidelines-subgroup");
  const sn = await subs.count();
  const titles: string[] = [];
  for (let s = 0; s < sn; s++)
    titles.push((await subs.nth(s).locator("summary").first().innerText()).split("\n")[0].trim());

  for (let s = 0; s < sn; s++) {
    await general.evaluate((card: any, keep: number) => {
      card.querySelectorAll("details.guidelines-subgroup").forEach((d: any, i: number) => {
        d.style.display = i === keep ? "" : "none";
      });
    }, s);
    await page.waitForTimeout(200);
    await subs.nth(s).scrollIntoViewIfNeeded();
    await subs.nth(s).screenshot({ path: path.join(OUT, `g-${s}.png`) });
    console.log(`[${s}] ${titles[s]}`);
  }
  await general.evaluate((card: any) => {
    card.querySelectorAll("details.guidelines-subgroup").forEach((d: any) => (d.style.display = ""));
  });
  await general.evaluate((d: any) => (d.open = false));
  await cards.nth(6).evaluate((d: any) => (d.open = true));
  await page.waitForTimeout(200);
  await cards.nth(6).screenshot({ path: path.join(OUT, "g-arch.png") });
  expect(sn).toBeGreaterThan(0);
});
