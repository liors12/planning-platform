import { test, expect } from "./fixtures";
import type { Page } from "@playwright/test";

// Layer 2 — viewport matrix & layout integrity at 1024x700 and 1280x800:
// no horizontal document overflow, no clipped button labels, sidebar footer
// links reachable.

const VIEWPORTS = [
  { width: 1024, height: 700 },
  { width: 1280, height: 800 },
];

async function assertLayoutIntegrity(page: Page, screen: string) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, `${screen}: horizontal overflow`).toBeLessThanOrEqual(0);
  const clipped = await page.evaluate(() =>
    Array.from(document.querySelectorAll("button"))
      .filter((el) => el.offsetParent !== null && el.scrollWidth > el.clientWidth + 1)
      .map((el) => (el as HTMLElement).innerText.slice(0, 30)),
  );
  expect(clipped, `${screen}: clipped button labels: ${clipped.join(" | ")}`).toHaveLength(0);
  await expect(page.getByTestId("sidebar-guidelines-link"), `${screen}: sidebar footer`).toBeInViewport();
}

for (const vp of VIEWPORTS) {
  test(`layout ${vp.width}x${vp.height}: home / overview / submissions / findings / cad / guidelines / settings`, async ({ page }) => {
    await page.setViewportSize(vp);

    await page.goto("/");
    await expect(page.getByTestId("home-project-link-407-1048248")).toBeVisible();
    await assertLayoutIntegrity(page, "home");

    await page.getByTestId("home-project-link-407-1048248").click();
    await assertLayoutIntegrity(page, "overview");

    await page.getByTestId("tab-submissions").click();
    await expect(page.getByTestId("submission-card-v24.3")).toBeVisible();
    await assertLayoutIntegrity(page, "submissions");

    await page.getByTestId("tab-findings").click();
    await assertLayoutIntegrity(page, "findings");

    // Addendum 7: the add-comment form used to clip its selects past the
    // card edge and cut the submit button - the generic clipped-button +
    // overflow assertions now cover the comments tab too, plus an explicit
    // check that the form controls stay inside the card.
    await page.getByTestId("tab-comments").click();
    await assertLayoutIntegrity(page, "comments");
    const formClip = await page.evaluate(() => {
      const form = document.querySelector(".add-comment-form");
      if (!form) return ["form not rendered"];
      const f = form.getBoundingClientRect();
      const out: string[] = [];
      form.querySelectorAll("select, input, textarea, button").forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.left < f.left - 0.5 || r.right > f.right + 0.5 || r.bottom > f.bottom + 0.5) {
          out.push(el.tagName + ":" + ((el as HTMLElement).innerText || (el as HTMLInputElement).placeholder || "").slice(0, 20));
        }
      });
      return out;
    });
    expect(formClip, `comments form clipped controls: ${formClip.join(" | ")}`).toHaveLength(0);

    await page.getByTestId("tab-cad_layers").click();
    await assertLayoutIntegrity(page, "cad");

    await page.goto("/#/guidelines");
    await expect(page.locator('[data-check-key="glass_railing_min_height_cm"]')).toBeVisible();
    await assertLayoutIntegrity(page, "guidelines");

    await page.goto("/#/settings");
    await assertLayoutIntegrity(page, "settings");
  });
}
