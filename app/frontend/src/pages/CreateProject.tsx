import { useState } from "react";
import { createProject } from "../api";
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

export function CreateProject({ navigate, onCreated }: Props) {
  const [nameHe, setNameHe] = useState("");
  const [tava, setTava] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [address, setAddress] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [dupe, setDupe] = useState<DuplicateTavaInfo | null>(null);

  const canSubmit = nameHe.trim().length > 0 && tava.trim().length > 0 && !submitting;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
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
      if (dup) {
        setDupe(dup);
      } else {
        setErr(raw);
      }
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
          הזיני פרטים בסיסיים. ניתן יהיה לערוך אחר כך מהמסך של הפרויקט.
        </p>
      </header>

      <form onSubmit={onSubmit} className="form-card">
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

        {dupe && (
          <div className="warning-block dupe-block">
            <strong>{dupe.message_he || `פרויקט עם תב"ע ${tava.trim()} כבר קיים.`}</strong>
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
        )}

        <div className="form-actions">
          <a className="ghost-btn" href={buildHash({ kind: "home" })}>ביטול</a>
          <button type="submit" className="primary-btn" disabled={!canSubmit}>
            {submitting ? "שומרת..." : "צרי פרויקט"}
          </button>
        </div>
      </form>
    </article>
  );
}
