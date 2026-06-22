import { useEffect, useState } from "react";
import {
  discoverLayerMappings,
  listLayerMappings,
  updateLayerMapping,
  LAYER_ROLES,
  LAYER_ROLE_LABELS,
  type LayerMappingOut,
  type ProjectOut,
} from "../api";

interface Props {
  project: ProjectOut;
}

const CONFIDENCE_LABELS: Record<string, string> = {
  AUTO:      "זוהה אוטומטית",
  HEURISTIC: "הצעה אוטומטית",
  MANUAL:    "אושר ידנית",
  UNKNOWN:   "לא ידוע",
};

export function LayerMappingTab({ project }: Props) {
  const [rows, setRows] = useState<LayerMappingOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [discovering, setDiscovering] = useState(false);
  // Per-row saving state: layer_name → "saving" | "saved" | null
  const [saving, setSaving] = useState<Record<string, "saving" | "saved" | null>>({});
  // Local edits before save: layer_name → role
  const [edits, setEdits] = useState<Record<string, string>>({});

  useEffect(() => {
    listLayerMappings(project.id)
      .then((data) => { setRows(data); setErr(null); })
      .catch((e) => setErr(String(e)));
  }, [project.id]);

  async function onDiscover() {
    setDiscovering(true);
    setErr(null);
    try {
      const data = await discoverLayerMappings(project.id);
      setRows(data);
      setEdits({});
    } catch (e) {
      setErr(String(e));
    } finally {
      setDiscovering(false);
    }
  }

  async function onSaveRow(layerName: string) {
    const role = edits[layerName] ?? rows?.find((r) => r.layer_name === layerName)?.role ?? "UNKNOWN";
    setSaving((s) => ({ ...s, [layerName]: "saving" }));
    setErr(null);
    try {
      const updated = await updateLayerMapping(project.id, layerName, role, true);
      setRows((prev) =>
        prev ? prev.map((r) => (r.layer_name === layerName ? updated : r)) : prev
      );
      setEdits((e) => { const copy = { ...e }; delete copy[layerName]; return copy; });
      setSaving((s) => ({ ...s, [layerName]: "saved" }));
      setTimeout(() => setSaving((s) => ({ ...s, [layerName]: null })), 1500);
    } catch (e) {
      setErr(String(e));
      setSaving((s) => ({ ...s, [layerName]: null }));
    }
  }

  const pendingCount = rows?.filter((r) => !r.confirmed).length ?? 0;

  return (
    <div className="layer-mapping-tab">
      <div className="layer-mapping-header">
        <div>
          <h2 className="card-title">מיפוי שכבות CAD</h2>
          <p className="muted layer-mapping-desc">
            הגדירי את התפקיד של כל שכבה בקובץ DXF כדי לאפשר בדיקות גיאומטריות אוטומטיות.
          </p>
        </div>
        <button
          className="ghost-btn"
          onClick={onDiscover}
          disabled={discovering}
          data-testid="layer-mapping-discover-btn"
        >
          {discovering ? (
            <><span className="spinner" aria-hidden="true" /> סורקת...</>
          ) : "סרקי שכבות מחדש"}
        </button>
      </div>

      {err && <div className="error">{err}</div>}

      {rows === null && !err && (
        <div className="muted">טוענת שכבות...</div>
      )}

      {rows !== null && rows.length === 0 && (
        <div className="card layer-mapping-empty">
          <p>לא נמצאו שכבות. העלי קובץ DXF בלשונית ״הגשות״ ולאחר מכן לחצי על ״סרקי שכבות מחדש״.</p>
        </div>
      )}

      {rows !== null && rows.length > 0 && (
        <>
          {pendingCount > 0 && (
            <div className="banner banner-warn" data-testid="layer-mapping-pending-banner">
              {pendingCount} שכבות טרם אושרו — בדיקות גיאומטריות לא יופעלו עד לאישור שכבת גבול המגרש לפחות.
            </div>
          )}

          <table className="layer-mapping-table" data-testid="layer-mapping-table">
            <thead>
              <tr>
                <th>שם שכבה</th>
                <th>תפקיד</th>
                <th>אמינות זיהוי</th>
                <th>סטטוס</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const currentRole = edits[row.layer_name] ?? row.role;
                const isDirty = edits[row.layer_name] !== undefined && edits[row.layer_name] !== row.role;
                const savingState = saving[row.layer_name];
                return (
                  <tr key={row.layer_name} className={row.confirmed ? "" : "layer-row-unconfirmed"}>
                    <td className="layer-name" dir="ltr" data-testid={`layer-name-${row.layer_name}`}>
                      {row.layer_name}
                    </td>
                    <td>
                      <select
                        value={currentRole}
                        onChange={(e) =>
                          setEdits((prev) => ({ ...prev, [row.layer_name]: e.target.value }))
                        }
                        data-testid={`layer-role-select-${row.layer_name}`}
                      >
                        {LAYER_ROLES.map((r) => (
                          <option key={r} value={r}>{LAYER_ROLE_LABELS[r]}</option>
                        ))}
                      </select>
                    </td>
                    <td className="muted">
                      {CONFIDENCE_LABELS[row.confidence] ?? row.confidence}
                    </td>
                    <td>
                      {row.confirmed ? (
                        <span className="badge badge-ok" data-testid={`layer-confirmed-${row.layer_name}`}>
                          מאושר ✓
                        </span>
                      ) : (
                        <span className="badge badge-missing">ממתין לאישור</span>
                      )}
                    </td>
                    <td>
                      {savingState === "saved" ? (
                        <span className="layer-saved-msg">נשמר ✓</span>
                      ) : (
                        <button
                          className="primary-btn primary-btn-sm"
                          onClick={() => onSaveRow(row.layer_name)}
                          disabled={savingState === "saving"}
                          data-testid={`layer-save-btn-${row.layer_name}`}
                        >
                          {savingState === "saving" ? (
                            <><span className="spinner" aria-hidden="true" /> שומרת</>
                          ) : isDirty ? "שמרי" : "אשרי"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
