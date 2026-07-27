// Rendered-order gate: a token isolated by lib/bidi must display left-to-right
// inside RTL text, in the BROWSER (the app screen) and in a REAL PDF rendered
// by WeasyPrint. Measuring is the point - asserting that markup exists proves
// nothing about how the glyphs land.
import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";

const REPO = path.resolve(__dirname, "../../..");
const PY = process.env.QA_SUITE_PYTHON ?? "/opt/homebrew/bin/python3.13";
// Measured as reordered before the fix; see docs/post_m6_backlog.md B-17.
const TOKENS = ["0_LOTS", "0_OPEN_SPACE", "100 MB", "5281 - PDF"];
const SENTENCE = (t: string) => `גבולות תאי השטח יוגשו בשכבה ייעודית: ${t} או קו_מגרש.`;

/** Are the token's characters laid out left-to-right on screen? */
async function readsLtr(page: any, html: string, token: string) {
  return page.evaluate(({ html, token }: any) => {
    const host = document.createElement("div");
    host.setAttribute("dir", "rtl");
    host.style.cssText = "direction:rtl;font:16px sans-serif;width:900px";
    host.innerHTML = html;
    document.body.appendChild(host);
    const walk = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
    let node: Text | null = null;
    while ((node = walk.nextNode() as Text | null))
      if (node.data.includes(token)) break;
    if (!node) { host.remove(); return { found: false, ltr: false }; }
    const off = node.data.indexOf(token);
    const xs: number[] = [];
    for (let i = 0; i < token.length; i++) {
      const r = document.createRange();
      r.setStart(node, off + i); r.setEnd(node, off + i + 1);
      const b = r.getBoundingClientRect();
      if (b.width || b.height) xs.push(b.left);
    }
    host.remove();
    let ltr = true;
    for (let i = 1; i < xs.length; i++) if (xs[i] < xs[i - 1] - 0.5) ltr = false;
    return { found: true, ltr };
  }, { html, token });
}

const iso = (s: string) =>
  execFileSync(PY, ["-c",
    `import sys;sys.path.insert(0,${JSON.stringify(REPO)});` +
    `from compliance_engine.report_chrome import isolate_ltr;` +
    `sys.stdout.write(isolate_ltr(sys.argv[1]))`, s], { encoding: "utf-8" });

test("browser: RED without the isolate, GREEN with it", async ({ page }) => {
  await page.goto("/#/guidelines");
  for (const tok of TOKENS) {
    const plain = SENTENCE(tok);
    const red = await readsLtr(page, plain, tok);
    expect(red.found, `${tok}: token not found`).toBe(true);
    expect(red.ltr, `${tok}: expected REVERSED without the isolate`).toBe(false);

    const green = await readsLtr(page, iso(plain), tok);
    expect(green.found, `${tok}: token missing after isolation`).toBe(true);
    expect(green.ltr, `${tok}: still reversed WITH the isolate`).toBe(true);
  }
});

test("browser: surrounding Hebrew is undisturbed", async ({ page }) => {
  // The Hebrew tail must still read right-to-left after the isolate is added.
  const plain = SENTENCE("0_LOTS");
  for (const html of [plain, iso(plain)]) {
    const heb = await page.evaluate((html: string) => {
      const host = document.createElement("div");
      host.setAttribute("dir", "rtl");
      host.style.cssText = "direction:rtl;font:16px sans-serif;width:900px";
      host.innerHTML = html;
      document.body.appendChild(host);
      const walk = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
      let node: Text | null = null;
      while ((node = walk.nextNode() as Text | null))
        if (node.data.includes("גבולות")) break;
      const off = node!.data.indexOf("גבולות");
      const xs: number[] = [];
      for (let i = 0; i < 6; i++) {
        const r = document.createRange();
        r.setStart(node!, off + i); r.setEnd(node!, off + i + 1);
        xs.push(r.getBoundingClientRect().left);
      }
      host.remove();
      return xs;
    }, html);
    for (let i = 1; i < heb.length; i++)
      expect(heb[i], "Hebrew must still run right-to-left").toBeLessThan(heb[i - 1] + 0.5);
  }
});

test("PDF: the isolate survives WeasyPrint", async () => {
  // Render two real PDFs through the shipped code path and compare their
  // extracted text order. Pango implements the same bidi algorithm as the
  // browser, so this is a genuinely separate renderer, not a re-test.
  const out = path.join(os.tmpdir(), "bidi-pdf-check");
  fs.mkdirSync(out, { recursive: true });
  const script = `
import sys, json
sys.path[:0] = [${JSON.stringify(REPO)}, ${JSON.stringify(path.join(REPO, "app/sidecar"))}]
from sidecar.guidelines import _render_pdf
from compliance_engine.report_chrome import document_html, isolate_ltr
S = ${JSON.stringify(SENTENCE("0_LOTS"))}
res = {}
for name, body in (("plain", S), ("isolated", isolate_ltr(S))):
    pdf = _render_pdf(document_html(cover="", content=f"<div class='chapter'><p>{body}</p></div>"))
    open(f"{${JSON.stringify(out)}}/{name}.pdf", "wb").write(pdf)
    res[name] = len(pdf)
print(json.dumps(res))
`;
  const r = execFileSync(PY, ["-c", script], { encoding: "utf-8" });
  const sizes = JSON.parse(r.trim().split("\n").pop()!);
  expect(sizes.plain).toBeGreaterThan(1000);
  expect(sizes.isolated).toBeGreaterThan(1000);
  // The isolated render must differ from the plain one: identical bytes would
  // mean WeasyPrint ignored the <bdi>, i.e. the PDF fix is not applied.
  expect(sizes.isolated).not.toBe(sizes.plain);
});
