import { useEffect, useRef, useState } from "react";
import {
  listSubmissions, runEngine, uploadSubmission,
  type ProjectOut, type SubmissionOut,
} from "../api";
import { EngineStatus } from "./EngineStatus";

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
  analyzing: "המנוע רץ",
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

  // Upload form state
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const dwgInputRef = useRef<HTMLInputElement | null>(null);
  const [version, setVersion] = useState("");
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [dwgFile, setDwgFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState("");

  function refresh() {
    listSubmissions(project.id)
      .then(setSubs)
      .catch((e) => setErr(String(e)));
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [project.id]);

  async function onUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!pdfFile || !version.trim()) return;
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
      setErr(String(e));
    } finally {
      setUploading(false);
      setUploadProgress("");
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
            "הפעל את המנוע" יהיה מושבת. הוספת סכמות תהיה זמינה בעדכון הבא.
          </div>
        )}
        <form onSubmit={onUpload}>
          <div className="upload-grid">
            <label className="form-field">
              <span className="form-label">גרסה</span>
              <input
                type="text"
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                placeholder="לדוגמה: v24.3"
                disabled={uploading}
                dir="ltr"
                required
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

          {uploadProgress && <div className="muted upload-progress">{uploadProgress}</div>}

          <div className="form-actions">
            <button
              type="submit"
              className="primary-btn"
              disabled={uploading || !pdfFile || !version.trim()}
            >
              {uploading ? "מעלה..." : "העלה הגשה"}
            </button>
          </div>
        </form>
      </section>

      {err && <div className="error">{err}</div>}

      {/* ── Submissions list ────────────────────────────────────────── */}
      <section className="submissions-list">
        <h3>הגשות קודמות</h3>
        {subs === null && <p className="muted">טוען...</p>}
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
                  {sub.status === "complete" ? "הפעל שוב את המנוע" : "הפעל את המנוע"}
                </button>
              </div>

              {activeJobId && (
                <EngineStatus
                  jobId={activeJobId}
                  submissionId={sub.id}
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
