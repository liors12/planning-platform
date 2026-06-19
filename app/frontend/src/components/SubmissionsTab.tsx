import { useEffect, useRef, useState } from "react";
import {
  exportExcel, listSubmissions, openOutput, pollJobUntilDone,
  renderSubmission, revealOutput, runEngine, uploadSubmission,
  type ProjectOut, type SubmissionOut,
} from "../api";
import { EngineStatus } from "./EngineStatus";

// One-of state per submission's output. Drives the WORKING / SUCCESS /
// FAILURE banner that today is missing — Ellen clicks a button and
// sees nothing change in the UI, even though the file silently lands
// on disk. This makes every step of the flow visible.
type OutputStatus =
  | null
  | { kind: "working";  what: "pdf" | "xlsx" }
  | { kind: "success";  what: "pdf" | "xlsx" }
  | { kind: "error";    what: "pdf" | "xlsx"; friendly: string };

// Map known engine failure shapes to a plain-Hebrew sentence Ellen can
// act on. Anything we don't recognize gets a generic message that
// points at the persistent log (Feature 1 / f610e4c). Never surface
// English / module names / "סכמה" / "מנוע" in the UI.
function friendlyError(rawError: string | undefined | null): string {
  const msg = String(rawError ?? "");
  if (/metadata not found/i.test(msg)) {
    return "לא ניתן ליצור דוח עבור גרסה זו — חסר קובץ מידע על הגרסה. " +
           "נסי למחוק את הגרסה ולהעלות אותה מחדש.";
  }
  if (/schema not found/i.test(msg)) {
    return "לא ניתן ליצור דוח עבור הפרויקט — חסר קובץ הגדרות. " +
           "פני לתמיכה.";
  }
  if (/audit_results.*needs|Run a full audit/i.test(msg)) {
    return "אין עדיין תוצאות סקירה לגרסה זו. " +
           "יש להריץ את התוכנה תחילה לפני הפקת דוח.";
  }
  // Generic safe fallback — never expose the raw technical text.
  return "אירעה תקלה ביצירת הדוח. הפרטים נשמרו לקובץ יומן.";
}

interface Props {
  project: ProjectOut;
  onSubmissionsChanged: () => void;
}

function Pill({ kind, children }: { kind: string; children: React.ReactNode }) {
  return <span className={"status-badge s-" + kind}>{children}</span>;
}

const SUB_STATUS_LABEL_HE: Record<string, string> = {
  uploaded: "הועלה",
  extracting: "מבצע חילוץ",
  analyzing: "התוכנה רצה",
  complete: "הושלם",
  failed: "נכשל",
};

const SUB_STATUS_KIND: Record<string, string> = {
  uploaded: "queued",
  extracting: "running",
  analyzing: "running",
  complete: "completed",
  failed: "failed",
};

export function SubmissionsTab({ project, onSubmissionsChanged }: Props) {
  const [subs, setSubs] = useState<SubmissionOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Active engine job per submission. Keyed by submission_id.
  const [activeJobs, setActiveJobs] = useState<Record<number, string>>({});

  // Per-submission output state — one of: null, working, success, error.
  // Drives a visible banner under the action buttons so Ellen sees what
  // the app is doing at every step.
  const [outputStatus, setOutputStatus] = useState<Record<number, OutputStatus>>({});

  // Upload form state
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const dwgInputRef = useRef<HTMLInputElement | null>(null);
  const [version, setVersion] = useState("");
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [dwgFile, setDwgFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState("");
  const [validationErr, setValidationErr] = useState<string | null>(null);

  function refresh() {
    listSubmissions(project.id)
      .then(setSubs)
      .catch((e) => setErr(String(e)));
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [project.id]);

  async function onUpload(e: React.FormEvent) {
    e.preventDefault();
    // Inline validation rather than disabling the button — so the user
    // gets feedback explaining WHY the click didn't do anything.
    if (!version.trim()) {
      setValidationErr("יש להזין מספר גרסה");
      return;
    }
    if (!pdfFile) {
      setValidationErr("יש לבחור קובץ PDF");
      return;
    }
    setValidationErr(null);
    setUploading(true);
    setErr(null);
    setUploadProgress(`מעלה ${pdfFile.name} (${(pdfFile.size / 1024 / 1024).toFixed(1)} MB)...`);
    try {
      await uploadSubmission(project.id, version.trim(), pdfFile, dwgFile);
      setVersion("");
      setPdfFile(null);
      setDwgFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      if (dwgInputRef.current) dwgInputRef.current.value = "";
      refresh();
      onSubmissionsChanged();
    } catch (e) {
      // 409 = duplicate version — show as an inline validation message
      // (red text under the button), not as a top-level error banner.
      // Real failures (500, network, …) still go to the error banner so
      // they don't look like user mistakes.
      const raw = String(e);
      if (/HTTP 409/.test(raw)) {
        setValidationErr(
          `גרסה ${version.trim()} כבר הועלתה. לעדכון, מחקי את הגרסה הקיימת תחילה.`
        );
      } else {
        setErr(raw);
      }
    } finally {
      setUploading(false);
      setUploadProgress("");
    }
  }

  async function onGenerateOutput(
    submissionId: number,
    kind: "pdf" | "xlsx",
  ) {
    setOutputStatus((p) => ({ ...p, [submissionId]: { kind: "working", what: kind } }));
    try {
      const job = kind === "pdf"
        ? await renderSubmission(submissionId)
        : await exportExcel(submissionId);
      const terminal = await pollJobUntilDone(job.id, () => {}, 1000, 120_000);
      if (terminal.status !== "completed") {
        const detail = terminal.error
          ? (() => { try { return JSON.parse(terminal.error!).error_message || terminal.error; }
                     catch { return terminal.error; } })()
          : "job failed";
        setOutputStatus((p) => ({
          ...p,
          [submissionId]: { kind: "error", what: kind, friendly: friendlyError(detail) },
        }));
      } else {
        setOutputStatus((p) => ({ ...p, [submissionId]: { kind: "success", what: kind } }));
        refresh();
      }
    } catch (e) {
      setOutputStatus((p) => ({
        ...p,
        [submissionId]: { kind: "error", what: kind, friendly: friendlyError(String(e)) },
      }));
    }
  }

  async function onOpenOutput(submissionId: number, kind: "pdf" | "xlsx") {
    try { await openOutput(submissionId, kind); }
    catch (e) {
      setOutputStatus((p) => ({
        ...p,
        [submissionId]: { kind: "error", what: kind, friendly: friendlyError(String(e)) },
      }));
    }
  }
  async function onRevealOutput(submissionId: number, kind: "pdf" | "xlsx") {
    try { await revealOutput(submissionId, kind); }
    catch (e) {
      setOutputStatus((p) => ({
        ...p,
        [submissionId]: { kind: "error", what: kind, friendly: friendlyError(String(e)) },
      }));
    }
  }

  async function onRunEngine(submissionId: number) {
    setErr(null);
    try {
      const job = await runEngine(submissionId);
      setActiveJobs((prev) => ({ ...prev, [submissionId]: job.id }));
      refresh();
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <div className="submissions-tab">
      {/* ── Upload form ─────────────────────────────────────────────── */}
      <section className="card upload-card">
        <h3>הגשה חדשה</h3>
        {!project.has_schema && (
          <div className="warning-block">
            <strong>אזהרה:</strong> לא נמצא קובץ סכמה (project-schema) לתב"ע{" "}
            <code dir="ltr">{project.tava_number}</code>. ניתן להעלות את ה-PDF, אך כפתור
            "הפעילי את התוכנה" יהיה מושבת. הוספת סכמות תהיה זמינה בעדכון הבא.
          </div>
        )}
        <form onSubmit={onUpload}>
          <div className="upload-grid">
            <label className="form-field">
              <span className="form-label">גרסה</span>
              <input
                type="text"
                value={version}
                onChange={(e) => {
                  setVersion(e.target.value);
                  if (validationErr && e.target.value.trim()) setValidationErr(null);
                }}
                placeholder="לדוגמה: v24.3"
                disabled={uploading}
                dir="ltr"
              />
            </label>
            <label className="form-field">
              <span className="form-label">קובץ PDF (חובה)</span>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,application/pdf"
                onChange={(e) => setPdfFile(e.target.files?.[0] ?? null)}
                disabled={uploading}
                required
              />
            </label>
            <label className="form-field">
              <span className="form-label">קובץ DWG (אופציונלי)</span>
              <input
                ref={dwgInputRef}
                type="file"
                accept=".dwg,.dxf"
                onChange={(e) => setDwgFile(e.target.files?.[0] ?? null)}
                disabled={uploading}
              />
            </label>
          </div>

          {uploadProgress && (
            <div className="upload-progress" role="status" aria-live="polite">
              <span className="spinner" aria-hidden="true" />
              <span>{uploadProgress}</span>
            </div>
          )}

          <div className="form-actions">
            <button
              type="submit"
              className="primary-btn"
              disabled={uploading}
            >
              {uploading ? (
                <>
                  <span className="spinner" aria-hidden="true" />
                  מעלה...
                </>
              ) : (
                "העלי הגשה"
              )}
            </button>
          </div>
          {validationErr && (
            <div className="error upload-validation-err" role="alert">
              {validationErr}
            </div>
          )}
        </form>
      </section>

      {err && <div className="error">{err}</div>}

      {/* ── Submissions list ────────────────────────────────────────── */}
      <section className="submissions-list">
        <h3>הגשות קודמות</h3>
        {subs === null && <p className="muted">טוענת...</p>}
        {subs !== null && subs.length === 0 && (
          <p className="muted">אין הגשות עדיין.</p>
        )}
        {subs?.map((sub) => {
          const activeJobId = activeJobs[sub.id];
          const canRunEngine =
            project.has_schema && (sub.status === "uploaded" || sub.status === "failed" || sub.status === "complete");
          return (
            <article key={sub.id} className="submission-card">
              <header className="submission-header">
                <div>
                  <h4>
                    גרסה <span dir="ltr">{sub.version_string}</span>
                  </h4>
                  <div className="muted submission-meta">
                    הועלה: {sub.uploaded_at.replace("T", " ").slice(0, 19)}
                    {" · "}גודל PDF: {pdfNameOf(sub.pdf_path)}
                  </div>
                </div>
                <Pill kind={SUB_STATUS_KIND[sub.status] ?? "queued"}>
                  {SUB_STATUS_LABEL_HE[sub.status] ?? sub.status}
                </Pill>
              </header>

              <div className="submission-actions">
                <button
                  className="primary-btn"
                  onClick={() => onRunEngine(sub.id)}
                  disabled={!canRunEngine || !!activeJobId || sub.status === "analyzing"}
                  title={
                    !project.has_schema
                      ? `לא ניתן להריץ — אין סכמה לתב"ע ${project.tava_number}`
                      : ""
                  }
                >
                  {sub.status === "complete" ? "הפעילי שוב את התוכנה" : "הפעילי את התוכנה"}
                </button>

                {sub.has_audit_results && (() => {
                  const st = outputStatus[sub.id];
                  // Disable BOTH output buttons while EITHER is working —
                  // a stray click on the other one during a running job
                  // queues a second job that can corrupt state.
                  const busy = st?.kind === "working";
                  return (
                    <>
                      <button
                        className="ghost-btn"
                        onClick={() => onGenerateOutput(sub.id, "pdf")}
                        disabled={busy}
                      >
                        {busy && st?.what === "pdf" ? (
                          <><span className="spinner" aria-hidden="true" />מפיקה דו״ח…</>
                        ) : "הפיקי דו״ח"}
                      </button>
                      <button
                        className="ghost-btn"
                        onClick={() => onGenerateOutput(sub.id, "xlsx")}
                        disabled={busy}
                      >
                        {busy && st?.what === "xlsx" ? (
                          <><span className="spinner" aria-hidden="true" />מפיקה אקסל…</>
                        ) : "הפיקי אקסל"}
                      </button>
                    </>
                  );
                })()}
              </div>

              <OutputBanner
                status={outputStatus[sub.id]}
                onOpen={(k) => onOpenOutput(sub.id, k)}
                onReveal={(k) => onRevealOutput(sub.id, k)}
                onDismiss={() => setOutputStatus((p) => ({ ...p, [sub.id]: null }))}
              />

              {activeJobId && (
                <EngineStatus
                  jobId={activeJobId}
                  submissionId={sub.id}
                  projectId={project.id}
                  onTerminal={() => refresh()}
                />
              )}
            </article>
          );
        })}
      </section>
    </div>
  );
}

function pdfNameOf(p: string): string {
  const idx = Math.max(p.lastIndexOf("/"), p.lastIndexOf("\\"));
  return idx >= 0 ? p.slice(idx + 1) : p;
}

// ─── Output status banner ────────────────────────────────────────────────
// Visible feedback for the "הפיקי דו״ח" / "הפיקי אקסל" buttons. Replaces
// the previous silent state where Ellen clicked, waited, and saw nothing
// change in the UI even though the file silently saved to disk.

function OutputBanner({
  status, onOpen, onReveal, onDismiss,
}: {
  status: OutputStatus;
  onOpen: (k: "pdf" | "xlsx") => void;
  onReveal: (k: "pdf" | "xlsx") => void;
  onDismiss: () => void;
}) {
  if (!status) return null;

  const labelFor = (k: "pdf" | "xlsx", kind: "working" | "success" | "error") => {
    if (kind === "working") return k === "pdf" ? "יוצרת דו״ח, נא להמתין..." : "יוצרת קובץ אקסל, נא להמתין...";
    if (kind === "success") return k === "pdf" ? "הדו״ח מוכן ✓"       : "קובץ האקסל מוכן ✓";
    return ""; // error label comes from status.friendly
  };

  if (status.kind === "working") {
    return (
      <div className="output-banner output-working" role="status" aria-live="polite">
        <span className="spinner" aria-hidden="true" />
        <span>{labelFor(status.what, "working")}</span>
      </div>
    );
  }

  if (status.kind === "success") {
    return (
      <div className="output-banner output-success" role="status" aria-live="polite">
        <span className="output-icon" aria-hidden="true">✓</span>
        <span className="output-msg">{labelFor(status.what, "success")}</span>
        <button className="ghost-btn small" type="button" onClick={() => onOpen(status.what)}>
          {status.what === "pdf" ? "פתחי דו״ח" : "פתחי אקסל"}
        </button>
        <button className="ghost-btn small" type="button" onClick={() => onReveal(status.what)}>
          פתחי תיקייה
        </button>
        <button className="output-dismiss" type="button" aria-label="סגרי" onClick={onDismiss}>✕</button>
      </div>
    );
  }

  // error
  return (
    <div className="output-banner output-error" role="alert">
      <span className="output-icon" aria-hidden="true">✗</span>
      <span className="output-msg">{status.friendly}</span>
      <button className="output-dismiss" type="button" aria-label="סגרי" onClick={onDismiss}>✕</button>
    </div>
  );
}
