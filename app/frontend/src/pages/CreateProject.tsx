import { useRef, useState } from "react";
import { createProject, importSchema } from "../api";
import { buildHash, type Route } from "../route";

interface Props {
  navigate: (r: Route) => void;
  onCreated: () => void;        // bump the sidebar refresh key
}

interface DuplicateTavaInfo {
  existing_project: {
    id: number;
    name_he: string;
    tava_number: string;
    status: string;
  };
  message_he: string;
}

/** Try to parse a 409 duplicate-tava error from the api.ts thrown Error. */
function parseDuplicateTava(rawError: string): DuplicateTavaInfo | null {
  // api.ts error format: "POST /projects → HTTP 409: {\"detail\":{...}}"
  const m = rawError.match(/HTTP 409:\s*(\{.*\})/s);
  if (!m) return null;
  try {
    const body = JSON.parse(m[1]);
    const detail = body?.detail;
    if (detail?.error === "duplicate_tava_active" && detail?.existing_project) {
      return {
        existing_project: detail.existing_project,
        message_he: detail.message_he ?? "",
      };
    }
  } catch {
    /* fallthrough */
  }
  return null;
}

type Tab = "manual" | "import";

interface SchemaPreview {
  tava: string;
  name: string;
}

export function CreateProject({ navigate, onCreated }: Props) {
  const [tab, setTab] = useState<Tab>("manual");

  // ── Manual tab state ──────────────────────────────────────────────────
  const [nameHe, setNameHe] = useState("");
  const [tava, setTava] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [address, setAddress] = useState("");

  // ── Import tab state ──────────────────────────────────────────────────
  const fileRef = useRef<HTMLInputElement>(null);
  const [schemaFile, setSchemaFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<SchemaPreview | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);

  // ── Shared state ──────────────────────────────────────────────────────
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [dupe, setDupe] = useState<DuplicateTavaInfo | null>(null);

  const canSubmitManual = nameHe.trim().length > 0 && tava.trim().length > 0 && !submitting;
  const canSubmitImport = schemaFile !== null && preview !== null && !previewErr && !submitting;

  // ── Schema file selection + preview ──────────────────────────────────
  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null;
    setSchemaFile(file);
    setPreview(null);
    setPreviewErr(null);
    setErr(null);
    setDupe(null);
    if (!file) return;

    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(reader.result as string);
        const t = String(data?.tava_number ?? "").trim();
        if (!t) {
          setPreviewErr('הקובץ אינו מכיל שדה "tava_number". בדקי שהקובץ הוא קובץ תב"ע תקין.');
          return;
        }
        const n = String(data?.name_he ?? "").trim() || `פרויקט ${t}`;
        setPreview({ tava: t, name: n });
      } catch {
        setPreviewErr("הקובץ שנבחר אינו JSON תקין. בדקי את הקובץ ונסי שוב.");
      }
    };
    reader.onerror = () => setPreviewErr("שגיאה בקריאת הקובץ. נסי לבחור אותו שוב.");
    reader.readAsText(file, "utf-8");
  }

  // ── Manual submit ─────────────────────────────────────────────────────
  async function onSubmitManual(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmitManual) return;
    setSubmitting(true);
    setErr(null);
    setDupe(null);
    try {
      const project = await createProject({
        name_he: nameHe.trim(),
        tava_number: tava.trim(),
        name_en: nameEn.trim() || null,
        address: address.trim() || null,
      });
      onCreated();
      navigate({ kind: "project", projectId: project.id });
    } catch (e) {
      const raw = String(e);
      const dup = parseDuplicateTava(raw);
      if (dup) setDupe(dup);
      else setErr(raw);
    } finally {
      setSubmitting(false);
    }
  }

  // ── Import submit ─────────────────────────────────────────────────────
  async function onSubmitImport(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmitImport || !schemaFile) return;
    setSubmitting(true);
    setErr(null);
    setDupe(null);
    try {
      const project = await importSchema(schemaFile);
      onCreated();
      navigate({ kind: "project", projectId: project.id });
    } catch (e) {
      const raw = String(e);
      const dup = parseDuplicateTava(raw);
      if (dup) setDupe(dup);
      else setErr(raw);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <article className="page-create-project">
      <header className="page-header">
        <a className="back-link" href={buildHash({ kind: "home" })}>← חזרי</a>
        <h1>פרויקט חדש</h1>
        <p className="muted">
          הזיני פרטים ידנית, או ייבאי קובץ תב"ע קיים.
        </p>
      </header>

      {/* Tab switcher */}
      <div className="tab-bar" role="tablist">
        <button
          role="tab"
          aria-selected={tab === "manual"}
          className={`tab-btn${tab === "manual" ? " tab-btn--active" : ""}`}
          onClick={() => { setTab("manual"); setErr(null); setDupe(null); }}
          type="button"
          data-testid="tab-manual"
        >
          הזיני ידנית
        </button>
        <button
          role="tab"
          aria-selected={tab === "import"}
          className={`tab-btn${tab === "import" ? " tab-btn--active" : ""}`}
          onClick={() => { setTab("import"); setErr(null); setDupe(null); }}
          type="button"
          data-testid="tab-import"
        >
          ייבאי קובץ תב"ע
        </button>
      </div>

      {/* ── Tab A: manual form ─────────────────────────────────────────── */}
      {tab === "manual" && (
        <form onSubmit={onSubmitManual} className="form-card">
          <label className="form-field">
            <span className="form-label">
              שם הפרויקט (עברית) <span className="required">*</span>
            </span>
            <input
              type="text"
              value={nameHe}
              onChange={(e) => setNameHe(e.target.value)}
              placeholder="לדוגמה: מתחם הטייסים-ההסתדרות"
              disabled={submitting}
              autoFocus
              required
            />
          </label>

          <label className="form-field">
            <span className="form-label">
              מספר תב"ע <span className="required">*</span>
            </span>
            <input
              type="text"
              value={tava}
              onChange={(e) => setTava(e.target.value)}
              placeholder="לדוגמה: 407-1048248"
              disabled={submitting}
              dir="ltr"
              required
            />
          </label>

          <label className="form-field">
            <span className="form-label">שם באנגלית (אופציונלי)</span>
            <input
              type="text"
              value={nameEn}
              onChange={(e) => setNameEn(e.target.value)}
              placeholder="לדוגמה: Hatayasim-Hahistadrut Complex"
              disabled={submitting}
              dir="ltr"
            />
          </label>

          <label className="form-field">
            <span className="form-label">כתובת (אופציונלי)</span>
            <input
              type="text"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="עיר / שכונה / רחוב"
              disabled={submitting}
            />
          </label>

          {err && <div className="error">{err}</div>}
          <DupeBlock dupe={dupe} tavaHint={tava.trim()} />

          <div className="form-actions">
            <a className="ghost-btn" href={buildHash({ kind: "home" })}>ביטול</a>
            <button type="submit" className="primary-btn" disabled={!canSubmitManual}>
              {submitting ? "שומרת..." : "צרי פרויקט"}
            </button>
          </div>
        </form>
      )}

      {/* ── Tab B: schema file import ──────────────────────────────────── */}
      {tab === "import" && (
        <form onSubmit={onSubmitImport} className="form-card">
          <label className="form-field">
            <span className="form-label">
              קובץ תב"ע (JSON) <span className="required">*</span>
            </span>
            <input
              ref={fileRef}
              type="file"
              accept=".json,application/json"
              onChange={onFileChange}
              disabled={submitting}
              data-testid="schema-file-input"
            />
            <span className="form-hint muted">
              הקובץ חייב להכיל שדה "tava_number" ברמה הראשית.
            </span>
          </label>

          {previewErr && <div className="error">{previewErr}</div>}

          {preview && !previewErr && (
            <div className="import-preview card">
              <div className="import-preview-row">
                <span className="import-preview-label">מספר תב"ע</span>
                <span className="import-preview-value" dir="ltr">{preview.tava}</span>
              </div>
              <div className="import-preview-row">
                <span className="import-preview-label">שם הפרויקט</span>
                <span className="import-preview-value">{preview.name}</span>
              </div>
            </div>
          )}

          {err && <div className="error">{err}</div>}
          <DupeBlock dupe={dupe} tavaHint={preview?.tava ?? ""} />

          <div className="form-actions">
            <a className="ghost-btn" href={buildHash({ kind: "home" })}>ביטול</a>
            <button
              type="submit"
              className="primary-btn"
              disabled={!canSubmitImport}
              data-testid="import-schema-submit"
            >
              {submitting ? "מייבאת..." : "ייבאי פרויקט"}
            </button>
          </div>
        </form>
      )}
    </article>
  );
}

function DupeBlock({
  dupe,
  tavaHint,
}: {
  dupe: DuplicateTavaInfo | null;
  tavaHint: string;
}) {
  if (!dupe) return null;
  return (
    <div className="warning-block dupe-block">
      <strong>{dupe.message_he || `פרויקט עם תב"ע ${tavaHint} כבר קיים.`}</strong>
      <div className="dupe-actions">
        <a
          className="primary-btn"
          href={buildHash({ kind: "project", projectId: dupe.existing_project.id })}
        >
          פתחי את הפרויקט הקיים: {dupe.existing_project.name_he}
        </a>
        <span className="muted">
          ניתן להוסיף לו הגשה חדשה דרך טאב "הגשות".
        </span>
      </div>
    </div>
  );
}
