import { useEffect, useState } from "react";
import { getDiagnostics, type DiagnosticsResponse, type FileCheck } from "../api";

interface Props {
  onClose: () => void;
}

export function DiagnosticsPanel({ onClose }: Props) {
  const [data, setData] = useState<DiagnosticsResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getDiagnostics()
      .then((d) => { if (!cancelled) { setData(d); setErr(null); } })
      .catch((e) => { if (!cancelled) setErr(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="diag-overlay" onClick={onClose} role="dialog" aria-label="לוח אבחון">
      <div className="diag-card" onClick={(e) => e.stopPropagation()}>
        <header className="diag-header">
          <h2>לוח אבחון מערכת</h2>
          <button className="diag-close" onClick={onClose} aria-label="סגרי">✕</button>
        </header>

        {loading && <p className="muted">טוענת נתוני אבחון…</p>}

        {err && !data && (
          <div className="error error-block">
            לא ניתן להתחבר לשרת הרקע. ייתכן ששירותי הרקע אינם פעילים.
            <details><summary>פרטים טכניים</summary><pre dir="ltr">{err}</pre></details>
          </div>
        )}

        {data && <DiagnosticsBody d={data} />}
      </div>
    </div>
  );
}

function DiagnosticsBody({ d }: { d: DiagnosticsResponse }) {
  const badgeClass =
    d.status === "healthy"  ? "diag-badge diag-healthy"  :
    d.status === "degraded" ? "diag-badge diag-degraded" :
                              "diag-badge diag-error";
  const badgeText =
    d.status === "healthy"  ? "תקין" :
    d.status === "degraded" ? "חלקי" :
                              "שגיאה";

  // Seed files: derive a single "found / missing" row that lists which
  // specific files (if any) are missing — matches the user-facing spec.
  const seedFiles: Array<[string, FileCheck]> = [
    ["סכמת פרויקט",     d.seed.schema_file],
    ["מטא-נתוני הגשה",  d.seed.metadata_file],
    ["תוצאות סקירה",    d.seed.audit_results_file],
  ];
  const missingSeed = seedFiles.filter(([, f]) => !f.exists);
  const seedOk = missingSeed.length === 0;

  return (
    <>
      <div className="diag-status-row">
        <span className={badgeClass}>{badgeText}</span>
        <span className="muted diag-uptime">
          זמן ריצה: {formatUptime(d.sidecar.uptime_seconds)}
        </span>
      </div>

      <dl className="diag-list">
        <CheckRow label="שרת רקע (sidecar)"
                  ok={d.sidecar.running}
                  yes="פעיל" no="לא פעיל" />
        <CheckRow label="מסד נתונים"
                  ok={d.db.connected}
                  yes="מחובר" no="שגיאה" />
        <CheckRow label="קבצי פרויקט"
                  ok={seedOk}
                  yes="נמצאו"
                  no={`חסרים: ${missingSeed.map(([n]) => n).join(", ")}`} />
        <CheckRow label="WeasyPrint"
                  ok={d.weasyprint.exists}
                  yes="נמצא" no="חסר" />
        <CheckRow label='מוכן להפקת דו"ח'
                  ok={d.render_ready}
                  yes="כן" no="לא" />
        <CheckRow label="מוכן להפקת אקסל"
                  ok={d.excel_ready}
                  yes="כן" no="לא" />
        <dt>מספר פרויקטים</dt>
        <dd>{d.projects.count}</dd>
      </dl>

      {d.errors.length > 0 && (
        <div className="diag-errors">
          <h3>שגיאות שזוהו</h3>
          <ul>
            {d.errors.map((e, i) => (
              <li key={i} className="error">{e}</li>
            ))}
          </ul>
        </div>
      )}

      <details className="diag-raw">
        <summary>מידע טכני מלא</summary>
        <pre dir="ltr">{JSON.stringify(d, null, 2)}</pre>
      </details>
    </>
  );
}

function CheckRow({ label, ok, yes, no }:
  { label: string; ok: boolean; yes: string; no: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd className={ok ? "diag-ok" : "diag-fail"}>
        <span className="diag-icon" aria-hidden="true">{ok ? "✅" : "❌"}</span>
        {ok ? yes : no}
      </dd>
    </>
  );
}

function formatUptime(s: number): string {
  if (s < 60) return `${s} שניות`;
  if (s < 3600) return `${Math.floor(s / 60)} דקות`;
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return m === 0 ? `${h} שעות` : `${h}:${String(m).padStart(2, "0")} שעות`;
}
