import { useEffect, useState } from "react";

/**
 * Hidden developer debug overlay. Toggle with Cmd+Shift+D (or Ctrl+Shift+D
 * on Windows/Linux). When open, shows the raw findings JSON for the
 * currently-displayed findings, plus a tiny system-status block.
 *
 * Deliberately not discoverable from the regular UI — meant for Lior +
 * Claude Code, not for Ellen or discipline managers.
 */

interface Props {
  /** Raw findings object currently loaded in the workspace, if any. */
  findings: unknown | null;
}

export function DebugOverlay({ findings }: Props) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const cmdOrCtrl = e.metaKey || e.ctrlKey;
      if (cmdOrCtrl && e.shiftKey && (e.key === "D" || e.key === "d")) {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (open && e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;

  return (
    <div className="debug-overlay" role="dialog" aria-label="חלון פיתוח">
      <div className="debug-overlay-card">
        <header className="debug-header">
          <span className="debug-eyebrow">דיבאג · Cmd+Shift+D לסגירה</span>
          <button className="debug-close" onClick={() => setOpen(false)} aria-label="סגרי">✕</button>
        </header>
        <div className="debug-body">
          <h3>findings.json</h3>
          {findings === null ? (
            <p className="muted">אין findings טעונים כעת. פתחי פרויקט עם הגשה שהתוכנה סיימה להריץ.</p>
          ) : (
            <pre dir="ltr" className="debug-json">
              {JSON.stringify(findings, null, 2)}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}
