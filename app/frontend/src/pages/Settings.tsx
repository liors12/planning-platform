import { useEffect, useState } from "react";
import { getSettings, putSettings } from "../api";
import { buildHash } from "../route";

export function Settings() {
  const [keySet, setKeySet] = useState<boolean | null>(null);
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) => setKeySet(s.anthropic_api_key_set))
      .catch((e) => setErr(String(e)));
  }, []);

  function validate(v: string): string | null {
    const t = v.trim();
    if (!t) return null;
    if (!t.startsWith("sk-ant-")) return 'מפתח Anthropic חייב להתחיל ב-"sk-ant-"';
    return null;
  }

  const validationError = validate(input);
  const canSave = input.trim().length > 0 && !validationError && !saving;

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setErr(null);
    setSaved(false);
    try {
      const result = await putSettings({ anthropic_api_key: input.trim() });
      setKeySet(result.anthropic_api_key_set);
      setInput("");
      setSaved(true);
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <article className="page-settings">
      <header className="page-header">
        <a className="back-link" href={buildHash({ kind: "home" })}>← חזרי</a>
        <h1>הגדרות מערכת</h1>
      </header>

      <section className="settings-section card">
        <h2 className="card-title">מפתח API של Anthropic</h2>

        <div className="settings-status-row">
          <span className="settings-label">מצב נוכחי:</span>
          {keySet === null && <span className="muted">טוענת...</span>}
          {keySet === true && (
            <span className="badge badge-ok" data-testid="settings-key-set">מוגדר ✓</span>
          )}
          {keySet === false && (
            <span className="badge badge-missing" data-testid="settings-key-missing">לא מוגדר</span>
          )}
        </div>

        <form onSubmit={onSave} className="form-card">
          <label className="form-field">
            <span className="form-label">מפתח API חדש</span>
            <input
              type="password"
              value={input}
              onChange={(e) => { setInput(e.target.value); setSaved(false); }}
              placeholder="sk-ant-..."
              disabled={saving}
              dir="ltr"
              data-testid="settings-api-key-input"
              autoComplete="off"
            />
            {validationError && (
              <span className="form-error">{validationError}</span>
            )}
            <span className="form-hint muted">
              המפתח נשמר בבסיס הנתונים ללא הצפנה.
            </span>
          </label>

          {err && <div className="error">{err}</div>}
          {saved && (
            <div className="success-msg" data-testid="settings-saved-msg">
              המפתח נשמר בהצלחה.
            </div>
          )}

          <div className="form-actions">
            <a className="ghost-btn" href={buildHash({ kind: "home" })}>ביטול</a>
            <button
              type="submit"
              className="primary-btn"
              disabled={!canSave}
              data-testid="settings-save-btn"
            >
              {saving ? "שומרת..." : "שמרי מפתח"}
            </button>
          </div>
        </form>
      </section>
    </article>
  );
}
