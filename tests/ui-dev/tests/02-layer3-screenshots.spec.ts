import { test, expect } from "./fixtures";

// Layer 3a — full-page screenshots of the key screens at both viewports,
// stable filenames, uploaded as CI artifacts for pre-release judgment review.

const VIEWPORTS = [
  { name: "1024x700", width: 1024, height: 700 },
  { name: "1280x800", width: 1280, height: 800 },
];

const SCREENS: Array<{ name: string; go: (page: import("@playwright/test").Page) => Promise<void> }> = [
  { name: "home", go: async (p) => { await p.goto("/"); await p.getByTestId("home-project-link-407-1048248").waitFor(); } },
  { name: "project-overview", go: async (p) => { await p.goto("/"); await p.getByTestId("home-project-link-407-1048248").click(); await p.getByTestId("tab-overview").waitFor(); } },
  { name: "submissions", go: async (p) => { await p.getByTestId("tab-submissions").click(); await p.getByTestId("submission-card-v24.3").waitFor(); } },
  { name: "findings", go: async (p) => { await p.getByTestId("tab-findings").click(); } },
  { name: "comments", go: async (p) => { await p.getByTestId("tab-comments").click(); } },
  { name: "cad-layers", go: async (p) => { await p.getByTestId("tab-cad_layers").click(); } },
  { name: "guidelines", go: async (p) => { await p.goto("/#/guidelines"); await p.getByTestId("guideline-row-1").waitFor(); } },
  { name: "guidelines-edit-dialog", go: async (p) => { await p.getByTestId("guideline-edit-1").click(); await p.getByTestId("guideline-edit-value").waitFor(); } },
  { name: "create-project", go: async (p) => { await p.goto("/#/projects/new"); await p.getByTestId("create-name-he").waitFor(); } },
  { name: "settings", go: async (p) => { await p.goto("/#/settings"); } },
];

for (const vp of VIEWPORTS) {
  test(`screenshots @ ${vp.name}`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width: vp.width, height: vp.height });
    for (const screen of SCREENS) {
      await screen.go(page);
      await page.waitForTimeout(250);
      await page.screenshot({
        path: `screenshots/${vp.name}/${screen.name}.png`,
        fullPage: true,
      });
    }
    expect(true).toBe(true);
  });
}
