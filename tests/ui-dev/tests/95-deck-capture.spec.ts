// Capture harness for the conference deck (not a gate). One 16:9 screenshot
// per screen of the app, at 1920x1080 so it stays crisp at slide size.
import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { ANNOTATED_PDF } from "./helpers";

const OUT = process.env.DECK_OUT!;

test("capture every screen", async ({ page }) => {
  fs.mkdirSync(OUT, { recursive: true });
  await page.setViewportSize({ width: 1920, height: 1080 });

  const shot = async (name: string) => {
    await page.waitForTimeout(700);
    await page.screenshot({ path: path.join(OUT, `${name}.png`) });
    console.log(`SHOT ${name}`);
  };

  // 1. home - project list + pipeline
  await page.goto("/#/");
  await page.waitForTimeout(1500);
  await shot("01-home");

  // 2. new project
  await page.goto("/#/projects/new");
  await shot("02-new-project");

  // 3-8. workspace tabs
  await page.goto("/#/projects/1");
  await page.waitForTimeout(2000);
  const tabs = [
    ["סקירה", "03-overview"],
    ["הגשות", "04-submissions"],
    ["__populate_attachments__", ""],
    ["נספחי תוכנית עיצוב", "05-attachments"],
    ["ממצאים", "06-findings"],
    ["הערות רפרנטים", "07-comments"],
  ];
  for (const [label, name] of tabs) {
    if (label === "__populate_attachments__") {
      // An empty-state screen is useless on a conference slide. Upload a real
      // attachment and run its review so the tab shows the actual product.
      await page.getByTestId("tab-attachments").click();
      await page.waitForTimeout(800);
      await page.getByTestId("attachment-type").selectOption("sec-3-4");
      await page.getByTestId("attachment-version").fill("v1");
      await page.getByTestId("attachment-file").setInputFiles({
        name: "nispach-tnua.pdf", mimeType: "application/pdf", buffer: ANNOTATED_PDF,
      });
      await page.getByTestId("attachment-upload-submit").click();
      await page.waitForTimeout(1500);
      const run = page.locator('[data-testid^="attachment-run-review-"]').first();
      if (await run.count()) { await run.click(); await page.waitForTimeout(3000); }
      continue;
    }
    const btn = page.locator(".tabs button", { hasText: label }).first();
    if (await btn.count()) {
      await btn.click();
      await page.waitForTimeout(1800);
      await shot(name);
    } else {
      console.log(`MISSING TAB ${label}`);
    }
  }

  // 9. guidelines
  await page.goto("/#/guidelines");
  await page.waitForTimeout(1500);
  await shot("09-guidelines");

  expect(fs.readdirSync(OUT).length).toBeGreaterThan(5);
});
