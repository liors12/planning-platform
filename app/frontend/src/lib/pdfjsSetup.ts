// One-time pdf.js worker registration. Imported by main.tsx so the worker
// URL is set BEFORE any react-pdf <Document> mounts.
//
// react-pdf 9.x ships a worker file as an .mjs ES module under
// `pdfjs-dist/build/`. Vite's URL constructor resolves it at build time
// and outputs the worker as a separate hashed file in the production bundle.

import { pdfjs } from "react-pdf";

// `new URL(..., import.meta.url)` is a Vite-recognized pattern for asset
// resolution. The .toString() coerces to the string GlobalWorkerOptions wants.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();
