import { useEffect, useState } from "react";
import {
  editGuideline,
  guidelineHistory,
  guidelinesPdfUrl,
  listGuidelines,
  type GuidelineOut,
} from "../api";
import { MaybeApiError } from "../components/ErrorNotice";

// Global guidelines editor - city-wide submission rules (NOT project-keyed).
// Editing creates version+1; history stays queryable.

export function Guidelines() {
  const [rows, setRows] = useState<GuidelineOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<GuidelineOut | null>(null);
  const [historyFor, setHistoryFor] = useState<GuidelineOut | null>(null);

  function refresh() {
    listGuidelines()
      .then((data) => { setRows(data); setErr(null); })
      .catch((e) => setErr(String(e)));
  }

  useEffect(() => { refresh(); }, []);

  // Group by DOCUMENT SECTION in document order (rows arrive sorted by
  // sort_order from the API); fall back to discipline for unplaced rows.
  const bySection = new Map<string, GuidelineOut[]>();
  for (const g of rows ?? []) {
    const group = g.section_title ?? g.discipline;
    const list = bySection.get(group) ?? [];
    list.push(g);
    bySection.set(group, list);
  }

  return (
    <article className="page-guidelines">
      <header className="page-header">
        <div>
          <h1>הנחיות עירוניות לתוכנית העיצוב</h1>
          <p className="muted">
            הנחיות ההגשה החלות על כל תכניות העיצוב בעיר. עריכת ערך יוצרת גרסה
            חדשה - הבדיקה האוטומטית הבאה תשתמש בערך המעודכן.
          </p>
        </div>
        <a
          className="primary-btn"
          href={guidelinesPdfUrl()}
          download="guidelines.pdf"
          data-testid="guidelines-pdf-download"
        >
          הורדת PDF
        </a>
      </header>

      {err && <MaybeApiError error={err} title="לא ניתן לטעון את ההנחיות" />}
      {!rows && !err && <p className="muted">טוענת...</p>}
      {rows && rows.length === 0 && (
        <p className="muted">אין הנחיות מוגדרות עדיין.</p>
      )}

      {[...bySection.entries()].map(([sectionTitle, items]) => (
        <details key={sectionTitle} className="card guidelines-group" open>
          <summary className="card-title guidelines-section-summary">{sectionTitle}</summary>
          <ul className="guidelines-list" data-testid={`guidelines-group-${sectionTitle}`}>
            {items.map((g) => (
              <li key={g.id} className="guideline-row" data-testid={`guideline-row-${g.id}`}
                  data-check-key={g.check_key ?? undefined}>
                <div className="guideline-main">
                  <div className="guideline-title-line">
                    <b>{g.title}</b>
                    <span className={`badge ${g.guideline_type === "checkable" ? "badge-auto" : "badge-manual"}`}>
                      {g.guideline_type === "checkable" ? "נבדקת אוטומטית" : "ידנית"}
                    </span>
                    <span className="muted guideline-version">גרסה {g.version}</span>
                  </div>
                  {g.guideline_type === "checkable" && g.check_value !== null && (
                    <div className="guideline-value" data-testid={`guideline-value-${g.id}`}>
                      ערך נדרש: <b>{g.check_value}</b> {g.unit ?? ""}
                    </div>
                  )}
                  {g.body_text && <p className="muted guideline-body">{g.body_text}</p>}
                </div>
                <div className="guideline-actions">
                  <button type="button" className="ghost-btn"
                          data-testid={`guideline-edit-${g.id}`}
                          onClick={() => setEditing(g)}>
                    עריכה
                  </button>
                  <button type="button" className="ghost-btn"
                          data-testid={`guideline-history-${g.id}`}
                          onClick={() => setHistoryFor(g)}>
                    היסטוריה
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </details>
      ))}

      {editing && (
        <EditDialog
          guideline={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); refresh(); }}
        />
      )}
      {historyFor && (
        <HistoryDialog guideline={historyFor} onClose={() => setHistoryFor(null)} />
      )}
    </article>
  );
}

function EditDialog({
  guideline,
  onClose,
  onSaved,
}: {
  guideline: GuidelineOut;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState(guideline.title);
  const [bodyText, setBodyText] = useState(guideline.body_text ?? "");
  const [value, setValue] = useState(
    guideline.check_value !== null ? String(guideline.check_value) : "",
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function onSave() {
    setSaving(true);
    setErr(null);
    try {
      const payload: { title?: string; body_text?: string; check_value?: number } = {};
      if (title !== guideline.title) payload.title = title;
      if (bodyText !== (guideline.body_text ?? "")) payload.body_text = bodyText;
      if (guideline.guideline_type === "checkable" && value.trim() !== "") {
        const num = Number(value);
        if (Number.isNaN(num)) {
          setErr("הערך חייב להיות מספר");
          setSaving(false);
          return;
        }
        if (num !== guideline.check_value) payload.check_value = num;
      }
      await editGuideline(guideline.id, payload);
      onSaved();
    } catch (e) {
      setErr(String(e));
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <h2 className="card-title">עריכת הנחיה</h2>
        <p className="muted">
          השמירה יוצרת גרסה {guideline.version + 1}; הגרסה הנוכחית נשמרת בהיסטוריה.
        </p>
        <label className="form-label">
          <span>כותרת</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)}
                 data-testid="guideline-edit-title" />
        </label>
        <label className="form-label">
          <span>נוסח ההנחיה</span>
          <textarea rows={4} value={bodyText}
                    onChange={(e) => setBodyText(e.target.value)}
                    data-testid="guideline-edit-body" />
        </label>
        {guideline.guideline_type === "checkable" && (
          <label className="form-label">
            <span>ערך נדרש {guideline.unit ? `(${guideline.unit})` : ""}</span>
            <input dir="ltr" inputMode="decimal" value={value}
                   onChange={(e) => setValue(e.target.value)}
                   data-testid="guideline-edit-value" />
          </label>
        )}
        {err && <MaybeApiError error={err} title="לא ניתן לטעון את ההנחיות" />}
        <div className="modal-actions">
          <button type="button" className="primary-btn" disabled={saving}
                  onClick={onSave} data-testid="guideline-edit-save">
            {saving ? "שומרת..." : "שמירה"}
          </button>
          <button type="button" className="ghost-btn" onClick={onClose}>
            ביטול
          </button>
        </div>
      </div>
    </div>
  );
}

function HistoryDialog({
  guideline,
  onClose,
}: {
  guideline: GuidelineOut;
  onClose: () => void;
}) {
  const [versions, setVersions] = useState<GuidelineOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    guidelineHistory(guideline.id)
      .then((data) => { setVersions(data); setErr(null); })
      .catch((e) => setErr(String(e)));
  }, [guideline.id]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <h2 className="card-title">היסטוריית גרסאות - {guideline.title}</h2>
        {err && <MaybeApiError error={err} title="לא ניתן לטעון את ההנחיות" />}
        {!versions && !err && <p className="muted">טוענת...</p>}
        {versions && (
          <ul className="guideline-history-list" data-testid="guideline-history-list">
            {versions.map((v) => (
              <li key={v.id} className={v.is_active ? "active-version" : ""}>
                <div>
                  <b>גרסה {v.version}</b>
                  {v.is_active && <span className="badge badge-auto">פעילה</span>}
                  {v.check_value !== null && (
                    <span> · ערך: {v.check_value} {v.unit ?? ""}</span>
                  )}
                </div>
                {v.edited_at && (
                  <div className="muted">
                    עודכן: {v.edited_at.replace("T", " ").slice(0, 16)}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        <div className="modal-actions">
          <button type="button" className="ghost-btn" onClick={onClose}>
            סגירה
          </button>
        </div>
      </div>
    </div>
  );
}
