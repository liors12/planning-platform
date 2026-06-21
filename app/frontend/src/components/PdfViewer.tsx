import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Document, Page } from "react-pdf";

interface Target {
  page: number;
  /** Bumped by parent on every jump request, so re-jumping to the same page works. */
  nonce: number;
}

interface Props {
  fileUrl: string;
  /** Page-jump signal from parent (e.g. a findings row click). */
  target?: Target | null;
  onLoad?: (numPages: number) => void;
}

type FitMode = "fit-page" | "fit-width" | { kind: "scale"; value: number };

/**
 * PDF viewer — single-page rendering with prev/next/jump + zoom controls.
 *
 * Default mode: "fit-page" — scales the page so it fits the available
 * pane both horizontally AND vertically without scrollbars. Other modes:
 *   - "fit-width" — fit horizontally (vertical scroll allowed)
 *   - {kind: "scale", value: N} — explicit zoom factor
 *
 * Strict single-page virtualization (only the current page rendered) keeps
 * memory bounded regardless of file size. Thumbnail strip is later work.
 */
export function PdfViewer({ fileUrl, target, onLoad }: Props) {
  const [numPages, setNumPages] = useState<number | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mode, setMode] = useState<FitMode>("fit-page");
  const [naturalPageDims, setNaturalPageDims] = useState<{ w: number; h: number } | null>(null);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const [containerSize, setContainerSize] = useState<{ w: number; h: number } | null>(null);

  const documentFile = useMemo(() => ({ url: fileUrl, withCredentials: false }), [fileUrl]);

  // Observe container size for both fit modes.
  useEffect(() => {
    if (!containerRef.current) return;
    const el = containerRef.current;
    setContainerSize({ w: el.clientWidth, h: el.clientHeight });
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        setContainerSize({ w: e.contentRect.width, h: e.contentRect.height });
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Parent-driven jump.
  useEffect(() => {
    if (!target) return;
    if (target.page >= 1 && (!numPages || target.page <= numPages)) {
      setPageNumber(target.page);
    }
  }, [target, numPages]);

  const onDocumentLoadSuccess = useCallback(
    ({ numPages }: { numPages: number }) => {
      setNumPages(numPages);
      setLoadError(null);
      onLoad?.(numPages);
    },
    [onLoad],
  );

  const onDocumentLoadError = useCallback((_err: Error) => {
    setLoadError(
      "התכנית אינה זמינה לתצוגה — ההערות והפקת הדו״ח פועלות כרגיל."
    );
  }, []);

  function onPageLoadSuccess(p: { originalWidth: number; originalHeight: number }) {
    setNaturalPageDims({ w: p.originalWidth, h: p.originalHeight });
  }

  function goPrev() { setPageNumber((p) => Math.max(1, p - 1)); }
  function goNext() { setPageNumber((p) => (numPages ? Math.min(numPages, p + 1) : p)); }

  const [jumpInput, setJumpInput] = useState("");
  function onJumpSubmit(e: React.FormEvent) {
    e.preventDefault();
    const n = parseInt(jumpInput, 10);
    if (Number.isFinite(n) && n >= 1 && (!numPages || n <= numPages)) {
      setPageNumber(n);
      setJumpInput("");
    }
  }

  // Compute the effective render width passed to react-pdf <Page>.
  // (react-pdf scales the canvas off `width`; we never pass `height`.)
  function effectiveWidth(): number | undefined {
    if (!containerSize) return undefined;
    const padding = 24;
    const availW = Math.max(100, containerSize.w - padding);
    const availH = Math.max(100, containerSize.h - padding);
    if (mode === "fit-width") return availW;
    if (mode === "fit-page" && naturalPageDims) {
      // Choose the smaller of (fit-by-width) and (fit-by-height-projected-to-width)
      // so the page never overflows either axis.
      const widthScale = availW / naturalPageDims.w;
      const heightScale = availH / naturalPageDims.h;
      const scale = Math.min(widthScale, heightScale);
      return naturalPageDims.w * scale;
    }
    if (typeof mode === "object" && mode.kind === "scale" && naturalPageDims) {
      return naturalPageDims.w * mode.value;
    }
    return availW;  // safe default until we have natural dims
  }

  function zoomIn() {
    const cur = currentScale();
    setMode({ kind: "scale", value: Math.min(4, cur * 1.25) });
  }
  function zoomOut() {
    const cur = currentScale();
    setMode({ kind: "scale", value: Math.max(0.25, cur / 1.25) });
  }
  function currentScale(): number {
    if (!naturalPageDims) return 1.0;
    const w = effectiveWidth();
    if (!w) return 1.0;
    return w / naturalPageDims.w;
  }

  const atFirst = pageNumber <= 1;
  const atLast = numPages ? pageNumber >= numPages : true;
  const zoomPct = Math.round(currentScale() * 100);

  return (
    <div className="pdf-viewer">
      <div className="pdf-toolbar">
        {/* RTL: "prev" arrow points right (visual direction of going-back in Hebrew). */}
        <button onClick={goPrev} disabled={atFirst} title="עמוד קודם" aria-label="עמוד קודם">›</button>
        <button onClick={goNext} disabled={atLast} title="עמוד הבא" aria-label="עמוד הבא">‹</button>
        <span className="pdf-page-indicator">
          {numPages ? <>עמוד <strong>{pageNumber}</strong> מתוך <strong>{numPages}</strong></> : "טוענת..."}
        </span>
        <form className="pdf-jump-form" onSubmit={onJumpSubmit}>
          <label className="muted">קפיצה:</label>
          <input
            type="number"
            min={1}
            max={numPages ?? undefined}
            value={jumpInput}
            onChange={(e) => setJumpInput(e.target.value)}
            placeholder="#"
            dir="ltr"
          />
          <button type="submit" disabled={!jumpInput.trim()}>קפצי</button>
        </form>
        <div className="pdf-zoom-controls">
          <button onClick={zoomOut} title="הקטיני" aria-label="הקטיני">−</button>
          <span className="pdf-zoom-pct">{zoomPct}%</span>
          <button onClick={zoomIn} title="הגדילי" aria-label="הגדילי">+</button>
          <button
            onClick={() => setMode("fit-page")}
            title="התאימי לחלון"
            className={mode === "fit-page" ? "active" : ""}
          >התאימי לחלון</button>
          <button
            onClick={() => setMode("fit-width")}
            title="התאימי לרוחב"
            className={mode === "fit-width" ? "active" : ""}
          >רוחב</button>
        </div>
      </div>

      <div ref={containerRef} className="pdf-canvas-area">
        {loadError && (
          <div className="muted pdf-load-notice">{loadError}</div>
        )}
        <Document
          file={documentFile}
          onLoadSuccess={onDocumentLoadSuccess}
          onLoadError={onDocumentLoadError}
          loading={<div className="muted pdf-loading">טוענת תכנית עיצוב...</div>}
          error={null}
        >
          {numPages && containerSize && (
            <Page
              pageNumber={pageNumber}
              width={effectiveWidth()}
              renderTextLayer={true}
              renderAnnotationLayer={true}
              onLoadSuccess={onPageLoadSuccess}
              loading={<div className="muted pdf-loading">טוענת עמוד...</div>}
            />
          )}
        </Document>
      </div>
    </div>
  );
}
