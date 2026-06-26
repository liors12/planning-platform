import { useEffect, useState } from "react";
import { getSettings, putSettings, SettingsOut } from "../api";
import { buildHash } from "../route";

export function Settings() {
  const [settings, setSettings] = useState<SettingsOut | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getSettings()
      .then(setSettings)
      .catch((e) => setErr(String(e)));
  }, []);

  return (
    <article className="page-settings">
      <header className="page-header">
        <a className="back-link" href={buildHash({ kind: "home" })}>← חזרי</a>
        <h1>הגדרות מערכת</h1>
      </header>

      {err && <div className="error">{err}</div>}

      <AnthropicCard settings={settings} onSaved={setSettings} />
      <GeminiCard settings={settings} onSaved={setSettings} />

      <p className="settings-data-dir-note muted">
        לשינוי מיקום הנתונים, הגדירי את משתנה הסביבה PLATFORM_DATA_DIR לפני הפעלת התוכנה.
      </p>
    </article>
  );
}

// ── Anthropic card ──────────────────────────────────────────────────────────

function AnthropicCard({
  settings,
  onSaved,
}: {
  settings: SettingsOut | null;
  onSaved: (s: SettingsOut) => void;
}) {
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);

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
      onSaved(result);
      setInput("");
      setSaved(true);
      window.dispatchEvent(new CustomEvent("ai-settings-changed"));
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="settings-section card">
      <h2 className="card-title">מפתח API של Anthropic</h2>

      <div className="settings-status-row">
        <span className="settings-label">מצב נוכחי:</span>
        {settings === null && <span className="muted">טוענת...</span>}
        {settings?.anthropic_api_key_set === true && (
          <span className="badge badge-ok" data-testid="settings-key-set">מוגדר ✓</span>
        )}
        {settings?.anthropic_api_key_set === false && (
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
          {validationError && <span className="form-error">{validationError}</span>}
          <span className="form-hint muted">המפתח נשמר בבסיס הנתונים ללא הצפנה.</span>
        </label>

        {err && <div className="error">{err}</div>}
        {saved && (
          <div className="success-msg" data-testid="settings-saved-msg">המפתח נשמר בהצלחה.</div>
        )}

        <div className="form-actions">
          <a className="ghost-btn" href={buildHash({ kind: "home" })}>ביטול</a>
          <button type="submit" className="primary-btn" disabled={!canSave} data-testid="settings-save-btn">
            {saving ? "שומרת..." : "שמרי מפתח"}
          </button>
        </div>
      </form>
    </section>
  );
}

// ── Gemini card ─────────────────────────────────────────────────────────────

function GeminiCard({
  settings,
  onSaved,
}: {
  settings: SettingsOut | null;
  onSaved: (s: SettingsOut) => void;
}) {
  const [primary, setPrimary] = useState("");
  const [b1, setB1] = useState("");
  const [b2, setB2] = useState("");
  const [b3, setB3] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function validateKey(v: string): string | null {
    const t = v.trim();
    if (!t) return null;
    if (!t.startsWith("AIza")) return 'מפתח Gemini חייב להתחיל ב-"AIza"';
    return null;
  }

  const primaryErr = validateKey(primary);
  const b1Err = validateKey(b1);
  const b2Err = validateKey(b2);
  const b3Err = validateKey(b3);

  const hasAnyInput = [primary, b1, b2, b3].some((v) => v.trim().length > 0);
  const hasValidationError = !!(primaryErr || b1Err || b2Err || b3Err);
  const canSave = hasAnyInput && !hasValidationError && !saving;

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setErr(null);
    setSaved(false);
    try {
      const payload: Parameters<typeof putSettings>[0] = {};
      if (primary.trim()) payload.gemini_api_key = primary.trim();
      if (b1.trim()) payload.gemini_api_key_backup_1 = b1.trim();
      if (b2.trim()) payload.gemini_api_key_backup_2 = b2.trim();
      if (b3.trim()) payload.gemini_api_key_backup_3 = b3.trim();
      const result = await putSettings(payload);
      onSaved(result);
      setPrimary(""); setB1(""); setB2(""); setB3("");
      setSaved(true);
      window.dispatchEvent(new CustomEvent("ai-settings-changed"));
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  }

  const geminiSet = settings?.gemini_api_key_set;
  const backupCount = settings?.gemini_backup_count ?? 0;

  return (
    <section className="settings-section card">
      <h2 className="card-title">מפתחות API של Gemini</h2>
      <p className="muted" style={{ marginBottom: "0.75rem", fontSize: "0.85rem" }}>
        ניתן להזין עד 4 מפתחות. המערכת עוברת אוטומטית למפתח הבא כשמכסה נגמרת.
      </p>

      <div className="settings-status-row">
        <span className="settings-label">מצב נוכחי:</span>
        {settings === null && <span className="muted">טוענת...</span>}
        {geminiSet === true && (
          <span className="badge badge-ok" data-testid="gemini-key-set">
            מוגדר ✓{backupCount > 0 ? ` (+${backupCount} גיבוי)` : ""}
          </span>
        )}
        {geminiSet === false && (
          <span className="badge badge-missing" data-testid="gemini-key-missing">לא מוגדר</span>
        )}
      </div>

      <form onSubmit={onSave} className="form-card">
        <GeminiKeyField
          label="מפתח ראשי"
          value={primary}
          onChange={(v) => { setPrimary(v); setSaved(false); }}
          error={primaryErr}
          disabled={saving}
          testId="gemini-key-primary"
        />
        <GeminiKeyField
          label="מפתח גיבוי 1 (אופציונלי)"
          value={b1}
          onChange={(v) => { setB1(v); setSaved(false); }}
          error={b1Err}
          disabled={saving}
          testId="gemini-key-b1"
        />
        <GeminiKeyField
          label="מפתח גיבוי 2 (אופציונלי)"
          value={b2}
          onChange={(v) => { setB2(v); setSaved(false); }}
          error={b2Err}
          disabled={saving}
          testId="gemini-key-b2"
        />
        <GeminiKeyField
          label="מפתח גיבוי 3 (אופציונלי)"
          value={b3}
          onChange={(v) => { setB3(v); setSaved(false); }}
          error={b3Err}
          disabled={saving}
          testId="gemini-key-b3"
        />

        <span className="form-hint muted">המפתחות נשמרים בבסיס הנתונים ללא הצפנה.</span>

        {err && <div className="error">{err}</div>}
        {saved && (
          <div className="success-msg" data-testid="gemini-saved-msg">המפתחות נשמרו בהצלחה.</div>
        )}

        <div className="form-actions">
          <a className="ghost-btn" href={buildHash({ kind: "home" })}>ביטול</a>
          <button type="submit" className="primary-btn" disabled={!canSave} data-testid="gemini-save-btn">
            {saving ? "שומרת..." : "שמרי מפתחות"}
          </button>
        </div>
      </form>
    </section>
  );
}

function GeminiKeyField({
  label,
  value,
  onChange,
  error,
  disabled,
  testId,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  error: string | null;
  disabled: boolean;
  testId: string;
}) {
  return (
    <label className="form-field">
      <span className="form-label">{label}</span>
      <input
        type="password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="AIza..."
        disabled={disabled}
        dir="ltr"
        data-testid={testId}
        autoComplete="off"
      />
      {error && <span className="form-error">{error}</span>}
    </label>
  );
}
