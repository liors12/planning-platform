import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  /** Children: exactly [start (RTL: right), end (RTL: left)]. */
  children: [React.ReactNode, React.ReactNode];
  /** localStorage key — typically `splitter:project_{id}`. Persists the
   * START-pane (visual right under RTL) fraction in [minFraction..maxFraction]. */
  storageKey: string;
  /** Default fraction for the start (right) pane. 0.55 = 55%. */
  defaultStartFraction?: number;
  minFraction?: number;
  maxFraction?: number;
}

/**
 * Horizontal split pane with a draggable divider, RTL-native.
 *
 * Layout uses `flex-direction: row-reverse` on `.app-shell` already; here we
 * use `row` and let the document direction handle the visual flow. The
 * "start" child (children[0]) ends up on the visual RIGHT under RTL, which
 * is where Module B's findings list belongs (primary reading-flow position).
 *
 * Position is persisted to localStorage as a fraction (e.g., 0.55). The
 * caller passes the storageKey scoped per-project (`splitter:project_{id}`)
 * so each project remembers its own splitter position. Phase 4 migrates this
 * into a `user_preferences` table.
 */
export function SplitPane({
  children,
  storageKey,
  defaultStartFraction = 0.55,
  minFraction = 0.25,
  maxFraction = 0.75,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [fraction, setFraction] = useState<number>(() => {
    try {
      const stored = window.localStorage.getItem(storageKey);
      if (stored !== null) {
        const v = parseFloat(stored);
        if (Number.isFinite(v) && v >= minFraction && v <= maxFraction) {
          return v;
        }
      }
    } catch { /* localStorage unavailable; fall through */ }
    return defaultStartFraction;
  });

  // Persist on change (debounced via React batching is fine — writes are cheap).
  useEffect(() => {
    try { window.localStorage.setItem(storageKey, String(fraction)); } catch { /* ignore */ }
  }, [storageKey, fraction]);

  const draggingRef = useRef(false);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    draggingRef.current = true;
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!draggingRef.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    if (rect.width <= 0) return;
    // Under RTL, the visual right edge corresponds to layout x=0 in flex `row`
    // (because the container's direction:rtl flips the inline axis). The
    // start child takes rect.right - clientX from the right edge.
    const fromRight = rect.right - e.clientX;
    let next = fromRight / rect.width;
    next = Math.max(minFraction, Math.min(maxFraction, next));
    setFraction(next);
  }, [minFraction, maxFraction]);

  const onPointerUp = useCallback((e: React.PointerEvent) => {
    draggingRef.current = false;
    (e.currentTarget as Element).releasePointerCapture?.(e.pointerId);
  }, []);

  const startPct = `${(fraction * 100).toFixed(2)}%`;
  const endPct   = `${((1 - fraction) * 100).toFixed(2)}%`;

  return (
    <div ref={containerRef} className="split-pane">
      <div className="split-pane-start" style={{ flexBasis: startPct }}>
        {children[0]}
      </div>
      <div
        className="split-pane-divider"
        role="separator"
        aria-orientation="vertical"
        aria-label="התאימי רוחב חלוקת המסך"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      />
      <div className="split-pane-end" style={{ flexBasis: endPct }}>
        {children[1]}
      </div>
    </div>
  );
}
