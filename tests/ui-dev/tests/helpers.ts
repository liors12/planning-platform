import { copyFileSync, existsSync, mkdirSync } from "fs";
import path from "path";
import { DATA_DIR } from "../playwright.config";

const REPO = path.resolve(__dirname, "../../..");

const PILOT_PDF = path.join(REPO, "projects/407-1048248/submissions/v24.3/v24.3.pdf");

// The 100MB pilot PDF is NOT committed — available locally only. Specs that
// need a real engine run skip honestly when it's absent (CI).
export function pilotPdfAvailable(): boolean {
  return existsSync(PILOT_PDF);
}

// Stage the real pilot PDF into the seeded submission's expected path so
// audit runs and the PDF pane work. Idempotent; no-op when unavailable.
export function stagePilotPdf(): void {
  const src = PILOT_PDF;
  if (!existsSync(src)) return;
  const dstDir = path.join(DATA_DIR, "projects/407-1048248/submissions/v24.3");
  mkdirSync(dstDir, { recursive: true });
  const dst = path.join(dstDir, "v24.3.pdf");
  if (!existsSync(dst)) copyFileSync(src, dst);
}

// Minimal-valid PDF bytes for upload tests (same magic as the CI e2e smoke).
export const MIN_PDF = Buffer.from("%PDF-1.4\n%%EOF\n");

/** Multi-page PDF builder. `pages` is one array of text lines per page.
 * Lines are kept short so they stay inside the MediaBox - a long line runs
 * off the page and only the on-page part is extractable, which silently
 * starved an earlier fixture. */
function buildPdf(pages: string[][]): Buffer {
  const objs: string[] = [];
  const pageObjNums: number[] = [];
  // 1 = catalog, 2 = pages node, 3 = font; page objects and their content
  // streams follow in pairs.
  objs.push("<< /Type /Catalog /Pages 2 0 R >>");
  objs.push("__PAGES__");
  objs.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
  pages.forEach((lines) => {
    const stream = "BT /F1 9 Tf 20 800 Td " +
      lines.map((l, i) => (i === 0 ? `(${l}) Tj` : `0 -12 Td (${l}) Tj`)).join(" ") +
      " ET";
    const contentNum = objs.length + 2;   // this page obj, then its stream
    pageObjNums.push(objs.length + 1);
    objs.push("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] " +
              `/Resources << /Font << /F1 3 0 R >> >> /Contents ${contentNum} 0 R >>`);
    objs.push(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
  });
  objs[1] = `<< /Type /Pages /Kids [${pageObjNums.map((n) => `${n} 0 R`).join(" ")}] ` +
            `/Count ${pages.length} >>`;

  let pdf = "%PDF-1.4\n";
  const offsets: number[] = [];
  objs.forEach((body, i) => {
    offsets.push(pdf.length);
    pdf += `${i + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = pdf.length;
  pdf += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
  for (const off of offsets) pdf += `${String(off).padStart(10, "0")} 00000 n \n`;
  pdf += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\n` +
         `startxref\n${xref}\n%%EOF\n`;
  return Buffer.from(pdf, "latin1");
}

/** THE CASE THAT BROKE THE FIRST THRESHOLD. A real submission is ~60 sheets
 * exported from CAD: every sheet carries a title block (project, tava, date,
 * scale, sheet number) and NOTHING else as text - all annotation is vector.
 * Document-wide that is ~1800 characters, which sails past any per-document
 * threshold and re-enables presence detection on a file we cannot actually
 * read. Per PAGE it is ~30 characters, which is obviously not readable.
 * This fixture must produce ZERO "לא הוגש". */
const _titleBlock = (n: number) => [
  `TAVA 407-1048248 v24.3 SHEET ${n}/60`,
];
export const TITLE_BLOCK_ONLY_PDF = buildPdf(
  Array.from({ length: 60 }, (_, i) => _titleBlock(i + 1)),
);

/** The opposite fixture: pages with realistic annotation density, so the
 * document IS readable and absence of a marker is real evidence. Each page
 * carries ~600 characters, the order of magnitude a genuinely annotated
 * sheet reaches - not a hair over the threshold. Text is Latin filler so it
 * matches no Hebrew guideline marker. */
const _annotationLines = [
  "ROOM SCHEDULE lobby 24.5 sqm storage 8.2 sqm plant room 11.0 sqm",
  "corridor width 1.80 m clear headroom 2.40 m finished floor level",
  "DIMENSIONS north elevation 42.60 m south elevation 42.60 m east",
  "elevation 18.30 m west elevation 18.30 m parapet height 1.10 m",
  "NOTES all dimensions in metres unless noted otherwise verify on",
  "site before fabrication refer to structural drawings for slab",
  "thicknesses and to services drawings for duct routes coordinate",
  "with landscape package at all external interfaces do not scale",
  "GENERAL setting out from grid intersection A1 datum level 0.00",
  "corresponds to finished ground floor level as shown on section",
];
export const ANNOTATED_PDF = buildPdf(
  Array.from({ length: 8 }, () => _annotationLines),
);

/** THE SILENT CASE. Half the sheets exported with a text layer, half
 * vector-only. It clears any ratio rule, so suppression switches off - and
 * any item that lives only on the unreadable half is reported "לא הוגש"
 * with nothing on screen to warn Ellen. Worse than the fully-vector file,
 * which at least announces itself. */
export const MIXED_PDF = buildPdf([
  ..._annotationLines.map(() => _annotationLines).slice(0, 4),
  ...Array.from({ length: 4 }, (_, i) => [`TAVA 407-1048248 v24.3 SHEET ${i + 5}/8`]),
]);
