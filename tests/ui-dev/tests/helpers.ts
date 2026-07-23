import { copyFileSync, existsSync, mkdirSync } from "fs";
import path from "path";
import { DATA_DIR } from "../playwright.config";

const REPO = path.resolve(__dirname, "../../..");

// Stage the real pilot PDF into the seeded submission's expected path so
// audit runs and the PDF pane work. Idempotent.
export function stagePilotPdf(): void {
  const src = path.join(REPO, "projects/407-1048248/submissions/v24.3/v24.3.pdf");
  const dstDir = path.join(DATA_DIR, "projects/407-1048248/submissions/v24.3");
  mkdirSync(dstDir, { recursive: true });
  const dst = path.join(dstDir, "v24.3.pdf");
  if (!existsSync(dst)) copyFileSync(src, dst);
}

// Minimal-valid PDF bytes for upload tests (same magic as the CI e2e smoke).
export const MIN_PDF = Buffer.from("%PDF-1.4\n%%EOF\n");
