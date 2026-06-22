import { useEffect, useRef, useState } from "react";
import {
  deleteAttachment, deleteSubmission, exportExcel, getArchitectResponse,
  listAttachments, listSubmissions, openOutput, openUrl, pollJobUntilDone,
  renderSubmission, revealOutput, runEngine, setWorkflowStage,
  uploadArchitectResponse, uploadAttachment, uploadSubmission,
  type ArchitectResponseRow, type AttachmentOut, type ProjectOut,
  type SubmissionOut, type WorkflowStage,
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
//
// `rawError` is the stringified JSON.parse of job.error from the
// sidecar — usually shaped {error_type, error_message, stderr_tail?}.
// We grep across the WHOLE string (incl. stderr_tail) because the
// engine's actual cause sometimes only appears in stderr while
// error_message is just "returned 1" / "render exit code 1".
function friendlyError(rawError: string | undefined | null): string {
  // Pull out stderr_tail if present so we search the engine's prints too.
  let haystack = String(rawError ?? "");
  try {
    const parsed = JSON.parse(haystack);
    haystack = [parsed.error_message, parsed.stderr_tail, parsed.stdout_tail]
      .filter(Boolean).join("\n");
  } catch { /* not JSON — search rawError as-is */ }

  if (/EngineNotAvailable|sidecar_python|WinError 2/i.test(haystack)) {
    return "פעולה זו אינה זמינה בגרסה הנוכחית. " +
           "להפקת הדוח עבור גרסה קיימת, השתמשי בכפתור \"הפיקי דו״ח\".";
  }
  if (/metadata not found/i.test(haystack)) {
    return "לא ניתן ליצור דוח עבור גרסה זו — חסר קובץ מידע על הגרסה. " +
           "נסי למחוק את הגרסה ולהעלות אותה מחדש.";
  }
  if (/schema not found/i.test(haystack)) {
    return "לא ניתן ליצור דוח עבור הפרויקט — חסר קובץ הגדרות. " +
           "פני לתמיכה.";
  }
  if (/audit_results.*needs|Run a full audit/i.test(haystack)) {
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

  // Spinner while a workflow-stage PATCH is in-flight.
  const [stageLoading, setStageLoading] = useState<Record<number, boolean>>({});

  // Spinner while architect response is uploading.
  const [responseUploading, setResponseUploading] = useState<Record<number, boolean>>({});

  // Loaded response rows per submission (B3 verification table).
  const [responseRows, setResponseRows] = useState<Record<number, ArchitectResponseRow[] | null>>({});
  const [responseRowsLoading, setResponseRowsLoading] = useState<Record<number, boolean>>({});
  const [verifyLoading, setVerifyLoading] = useState<Record<number, boolean>>({});

  // A1 attachment state per submission.
  const [attachments, setAttachments] = useState<Record<number, AttachmentOut[] | null>>({});
  const [attachmentsLoading, setAttachmentsLoading] = useState<Record<number, boolean>>({});
  const [attachmentUploading, setAttachmentUploading] = useState<Record<number, boolean>>({});
  const [attachmentDeleting, setAttachmentDeleting] = useState<Record<number, Set<number>>>({});

  // Upload form state
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const cadFileInputRef = useRef<HTMLInputElement | null>(null);
  const [version, setVersion] = useState("");
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [cadFile, setCadFile] = useState<File | null>(null);
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
      await uploadSubmission(project.id, version.trim(), pdfFile, cadFile);
      setVersion("");
      setPdfFile(null);
      setCadFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      if (cadFileInputRef.current) cadFileInputRef.current.value = "";
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
        // Pass the WHOLE error JSON (incl. stderr_tail) so friendlyError
        // can grep across every field for cause strings like
        // "metadata not found".
        setOutputStatus((p) => ({
          ...p,
          [submissionId]: { kind: "error", what: kind,
                            friendly: friendlyError(terminal.error) },
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

  async function onDeleteSubmission(sub: SubmissionOut) {
    const bareVer = sub.version_string.replace(/^v/, "");
    if (!window.confirm(
      `האם למחוק לצמיתות את גרסה ${bareVer} וכל הקבצים שנוצרו עבורה?`
    )) return;
    setErr(null);
    try {
      await deleteSubmission(sub.id);
      // Drop any per-submission UI state for this row before the list
      // refresh so stale OutputStatus banners don't render in a row
      // that's about to disappear.
      setOutputStatus((p) => { const n = { ...p }; delete n[sub.id]; return n; });
      refresh();
      onSubmissionsChanged();
    } catch (e) {
      setErr(friendlyError(String(e)) ||
             "אירעה תקלה במחיקת הגרסה. הפרטים נשמרו לקובץ יומן.");
    }
  }

  async function onRunEngine(submissionId: number) {
    setErr(null);
    try {
      const job = await runEngine(submissionId);
      setActiveJobs((prev) => ({ ...prev, [submissionId]: job.id }));
      refresh();
    } catch (e) {
      // Friendly Hebrew for the 503 EngineNotAvailable response so the
      // user never sees the raw "HTTP 503: {...}" string. Anything else
      // still falls through to the generic detail (we route through
      // friendlyError so the same translation logic the output buttons
      // use applies here too).
      setErr(friendlyError(String(e)));
    }
  }

  async function onOpenMavat() {
    const url = `https://mavat.iplan.gov.il/SV4/1/1001/${encodeURIComponent(project.tava_number)}`;
    try { await openUrl(url); }
    catch { /* silently ignore — worst case the browser doesn't open */ }
  }

  async function onUploadResponse(submissionId: number, file: File) {
    setResponseUploading((p) => ({ ...p, [submissionId]: true }));
    setErr(null);
    try {
      const updated = await uploadArchitectResponse(submissionId, file);
      setSubs((prev) => prev?.map((s) => s.id === submissionId ? updated : s) ?? prev);
      onSubmissionsChanged();
    } catch (e) {
      setErr(String(e));
    } finally {
      setResponseUploading((p) => ({ ...p, [submissionId]: false }));
    }
  }

  async function onLoadResponse(submissionId: number) {
    if (responseRows[submissionId] !== undefined) return; // already loaded
    setResponseRowsLoading((p) => ({ ...p, [submissionId]: true }));
    try {
      const info = await getArchitectResponse(submissionId);
      setResponseRows((p) => ({ ...p, [submissionId]: info.rows }));
    } catch (e) {
      setResponseRows((p) => ({ ...p, [submissionId]: [] }));
    } finally {
      setResponseRowsLoading((p) => ({ ...p, [submissionId]: false }));
    }
  }

  async function onMarkVerified(submissionId: number) {
    setVerifyLoading((p) => ({ ...p, [submissionId]: true }));
    try {
      const updated = await setWorkflowStage(submissionId, "verified");
      setSubs((prev) => prev?.map((s) => s.id === submissionId ? updated : s) ?? prev);
      onSubmissionsChanged();
    } catch (e) {
      setErr(String(e));
    } finally {
      setVerifyLoading((p) => ({ ...p, [submissionId]: false }));
    }
  }

  async function onLoadAttachments(submissionId: number) {
    if (attachments[submissionId] !== undefined) return;
    setAttachmentsLoading((p) => ({ ...p, [submissionId]: true }));
    try {
      const list = await listAttachments(submissionId);
      setAttachments((p) => ({ ...p, [submissionId]: list }));
    } catch {
      setAttachments((p) => ({ ...p, [submissionId]: [] }));
    } finally {
      setAttachmentsLoading((p) => ({ ...p, [submissionId]: false }));
    }
  }

  async function onUploadAttachment(submissionId: number, file: File) {
    setAttachmentUploading((p) => ({ ...p, [submissionId]: true }));
    try {
      const att = await uploadAttachment(submissionId, file);
      setAttachments((p) => ({
        ...p,
        [submissionId]: [...(p[submissionId] ?? []), att],
      }));
    } catch (e) {
      setErr(String(e));
    } finally {
      setAttachmentUploading((p) => ({ ...p, [submissionId]: false }));
    }
  }

  async function onDeleteAttachment(submissionId: number, attachmentId: number) {
    setAttachmentDeleting((p) => ({
      ...p,
      [submissionId]: new Set([...(p[submissionId] ?? []), attachmentId]),
    }));
    try {
      await deleteAttachment(submissionId, attachmentId);
      setAttachments((p) => ({
        ...p,
        [submissionId]: (p[submissionId] ?? []).filter((a) => a.id !== attachmentId),
      }));
    } catch (e) {
      setErr(String(e));
    } finally {
      setAttachmentDeleting((p) => {
        const next = new Set(p[submissionId] ?? []);
        next.delete(attachmentId);
        return { ...p, [submissionId]: next };
      });
    }
  }

  async function onSetStage(submissionId: number, stage: WorkflowStage) {
    setStageLoading((p) => ({ ...p, [submissionId]: true }));
    try {
      const updated = await setWorkflowStage(submissionId, stage);
      setSubs((prev) => prev?.map((s) => s.id === submissionId ? updated : s) ?? prev);
    } catch (e) {
      setErr(String(e));
    } finally {
      setStageLoading((p) => ({ ...p, [submissionId]: false }));
    }
  }

  return (
    <div className="submissions-tab">
      {/* ── Upload form ─────────────────────────────────────────────── */}
      <section className="card upload-card">
        <div className="upload-card-header">
          <h3>הגשה חדשה</h3>
          <span className="tava-meta">
            {'תב"ע '}
            <code dir="ltr">{project.tava_number}</code>
            {" "}
            <button type="button" className="ghost-btn small" onClick={onOpenMavat}>
              צפי בתכנון זמין ↗
            </button>
          </span>
        </div>
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
              <span className="form-label">קובץ DXF / DWG (אופציונלי)</span>
              <input
                ref={cadFileInputRef}
                type="file"
                accept=".dxf,.dwg"
                onChange={(e) => setCadFile(e.target.files?.[0] ?? null)}
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
          // engine_run_available is False in the Windows-frozen package — the
          // worker can't spawn cfg.sidecar_python in that environment. Until
          // _process_one gets an in-process branch (V0.2), the button stays
          // disabled with a Hebrew "feature not available" tooltip so Ellen
          // doesn't hit the misleading SchemaNotFound / WinError 2 dead end.
          const canRunEngine =
            sub.engine_run_available
            && project.has_schema
            && (sub.status === "uploaded" || sub.status === "failed" || sub.status === "complete");
          return (
            <article key={sub.id} className="submission-card"
              data-testid={`submission-card-${sub.version_string}`}>
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
                <div className="submission-header-right">
                  <Pill kind={SUB_STATUS_KIND[sub.status] ?? "queued"}>
                    {SUB_STATUS_LABEL_HE[sub.status] ?? sub.status}
                  </Pill>
                  {/* Trash button: lets Ellen self-recover from a bad
                      upload without needing dev SQL surgery. Disabled
                      mid-analysis so we don't delete a row whose job
                      is mid-flight. */}
                  <button
                    type="button"
                    className="icon-btn danger"
                    data-testid={`delete-submission-${sub.version_string}`}
                    onClick={() => onDeleteSubmission(sub)}
                    disabled={!!activeJobId || sub.status === "analyzing"}
                    title="מחקי גרסה זו"
                    aria-label={`מחקי גרסה ${sub.version_string}`}
                  >
                    🗑
                  </button>
                </div>
              </header>

              <WorkflowStepper stage={sub.workflow_stage ?? "draft"} />

              {sub.workflow_stage === "draft" && sub.has_report_xlsx && (
                <div className="mark-sent-row">
                  <button
                    type="button"
                    className="ghost-btn small"
                    disabled={stageLoading[sub.id]}
                    onClick={() => onSetStage(sub.id, "sent")}
                  >
                    {stageLoading[sub.id]
                      ? <><span className="spinner" aria-hidden="true" />מעדכנת...</>
                      : "סימנתי כנשלח לאדריכל ✓"}
                  </button>
                </div>
              )}

              {sub.workflow_stage === "response_received" && (
                <ResponseReviewSection
                  rows={responseRows[sub.id]}
                  loading={responseRowsLoading[sub.id]}
                  verifyLoading={verifyLoading[sub.id]}
                  onLoad={() => onLoadResponse(sub.id)}
                  onMarkVerified={() => onMarkVerified(sub.id)}
                />
              )}

              {sub.workflow_stage === "sent" && (
                <div className="response-upload-row">
                  <label className={`ghost-btn small response-upload-label${responseUploading[sub.id] ? " disabled" : ""}`}>
                    {responseUploading[sub.id]
                      ? <><span className="spinner" aria-hidden="true" />מעלה תשובה...</>
                      : "העלאת תשובת אדריכל (אקסל) ↑"}
                    <input
                      type="file"
                      accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                      className="sr-only"
                      disabled={responseUploading[sub.id]}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) onUploadResponse(sub.id, f);
                        e.target.value = "";
                      }}
                    />
                  </label>
                  {sub.has_architect_response && (
                    <span className="response-uploaded-note muted">תשובה הועלתה ✓</span>
                  )}
                </div>
              )}

              <AttachmentSection
                attachments={attachments[sub.id]}
                loading={attachmentsLoading[sub.id]}
                uploading={attachmentUploading[sub.id]}
                deleting={attachmentDeleting[sub.id]}
                onLoad={() => onLoadAttachments(sub.id)}
                onUpload={(f) => onUploadAttachment(sub.id, f)}
                onDelete={(id) => onDeleteAttachment(sub.id, id)}
              />

              <div className="submission-actions">
                <button
                  className="primary-btn"
                  onClick={() => onRunEngine(sub.id)}
                  disabled={!canRunEngine || !!activeJobId || sub.status === "analyzing"}
                  title={
                    !sub.engine_run_available
                      ? "פעולה זו אינה זמינה בגרסה הנוכחית"
                      : !project.has_schema
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
                        data-testid={`generate-report-pdf-${sub.version_string}`}
                        onClick={() => onGenerateOutput(sub.id, "pdf")}
                        disabled={busy}
                      >
                        {busy && st?.what === "pdf" ? (
                          <><span className="spinner" aria-hidden="true" />מפיקה דו״ח…</>
                        ) : "הפיקי דו״ח"}
                      </button>
                      <button
                        className="ghost-btn"
                        data-testid={`generate-report-xlsx-${sub.version_string}`}
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

              <LastReportSection
                hasPdf={sub.has_report_pdf}
                hasXlsx={sub.has_report_xlsx}
                onOpen={(k) => onOpenOutput(sub.id, k)}
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

// ─── B3: Response review section ─────────────────────────────────────────────

function ResponseReviewSection({
  rows, loading, verifyLoading, onLoad, onMarkVerified,
}: {
  rows: ArchitectResponseRow[] | null | undefined;
  loading: boolean | undefined;
  verifyLoading: boolean | undefined;
  onLoad: () => void;
  onMarkVerified: () => void;
}) {
  const isLoaded = rows !== null && rows !== undefined;

  if (!isLoaded && !loading) {
    return (
      <div className="response-review-section">
        <button type="button" className="ghost-btn small" onClick={onLoad}>
          הצגת תשובות האדריכל ▼
        </button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="response-review-section">
        <span className="spinner" aria-hidden="true" />{" "}
        <span className="muted">טוענת תשובות...</span>
      </div>
    );
  }

  const filled = (rows ?? []).filter(
    (r) => r.treatment_status || r.architect_notes
  );

  return (
    <div className="response-review-section">
      <div className="response-review-header">
        <span className="response-review-title">תשובות האדריכל</span>
        <span className="muted response-review-count">
          {filled.length} / {(rows ?? []).length} ממצאים עם תשובה
        </span>
      </div>

      {(rows ?? []).length === 0 ? (
        <p className="muted">לא נמצאו שורות בקובץ התשובה.</p>
      ) : (
        <div className="response-table-wrap">
          <table className="response-table" dir="rtl">
            <colgroup>
              <col className="rt-col-original" span={3} />
              <col className="rt-col-response" span={2} />
            </colgroup>
            <thead>
              <tr className="rt-group-row">
                <th colSpan={3} className="rt-group-header rt-group-original-hdr">
                  ממצא מקורי
                </th>
                <th colSpan={2} className="rt-group-header rt-group-response-hdr">
                  תשובת האדריכל
                </th>
              </tr>
              <tr>
                <th>נושא</th>
                <th>סטטוס ממצא</th>
                <th className="rt-divider-col">תיאור</th>
                <th>סטטוס טיפול</th>
                <th>הערות</th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((r, i) => (
                <tr key={i}
                    className={r.treatment_status || r.architect_notes ? "" : "rt-empty"}>
                  <td>{r.topic_he ?? "—"}</td>
                  <td>{r.finding_status ?? "—"}</td>
                  <td className="rt-desc rt-divider-col">{r.description ?? "—"}</td>
                  <td>
                    {r.treatment_status
                      ? <span className="rt-treatment">{r.treatment_status}</span>
                      : <span className="muted">—</span>}
                  </td>
                  <td className="rt-notes">{r.architect_notes ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="response-verify-row">
        <button
          type="button"
          className="ghost-btn small"
          disabled={verifyLoading}
          onClick={onMarkVerified}
        >
          {verifyLoading
            ? <><span className="spinner" aria-hidden="true" />מעדכנת...</>
            : "סימנתי כמאומת ✓"}
        </button>
      </div>
    </div>
  );
}

function pdfNameOf(p: string): string {
  const idx = Math.max(p.lastIndexOf("/"), p.lastIndexOf("\\"));
  return idx >= 0 ? p.slice(idx + 1) : p;
}

// ─── Workflow stepper ────────────────────────────────────────────────────

const WORKFLOW_STEPS: { key: WorkflowStage; label: string }[] = [
  { key: "draft",             label: "הוכנה" },
  { key: "sent",              label: "נשלח לאדריכל" },
  { key: "response_received", label: "התקבלה תשובה" },
  { key: "verified",          label: "נסגר" },
];

const STAGE_IDX: Record<WorkflowStage, number> = {
  draft: 0, sent: 1, response_received: 2, verified: 3,
};

function WorkflowStepper({ stage }: { stage: WorkflowStage }) {
  const current = STAGE_IDX[stage] ?? 0;
  return (
    <ol className="workflow-stepper" aria-label="שלבי הטיפול">
      {WORKFLOW_STEPS.map((step, idx) => {
        const state = idx < current ? "done" : idx === current ? "active" : "future";
        return (
          <li key={step.key} className={`ws-step ws-${state}`}>
            <span className="ws-dot" aria-hidden="true">
              {state === "done" ? "✓" : idx + 1}
            </span>
            <span className="ws-label">{step.label}</span>
          </li>
        );
      })}
    </ol>
  );
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
    if (kind === "success") return k === "pdf"
      ? "הדו״ח מוכן ✓  •  שמור בתיקיית התוצאות של הפרויקט"
      : "קובץ האקסל מוכן ✓  •  שמור בתיקיית התוצאות של הפרויקט";
    return ""; // error label comes from status.friendly
  };

  if (status.kind === "working") {
    return (
      <div className="output-banner output-working" role="status" aria-live="polite"
           data-testid={`output-banner-working-${status.what}`}>
        <span className="spinner" aria-hidden="true" />
        <span>{labelFor(status.what, "working")}</span>
      </div>
    );
  }

  if (status.kind === "success") {
    return (
      <div className="output-banner output-success" role="status" aria-live="polite"
           data-testid={`output-banner-success-${status.what}`}>
        <span className="output-icon" aria-hidden="true">✓</span>
        <span className="output-msg">{labelFor(status.what, "success")}</span>
        <button className="ghost-btn small" type="button"
                data-testid={`open-output-${status.what}`}
                onClick={() => onOpen(status.what)}>
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
    <div className="output-banner output-error" role="alert"
         data-testid={`output-banner-error-${status.what}`}>
      <span className="output-icon" aria-hidden="true">✗</span>
      <span className="output-msg">{status.friendly}</span>
      <button className="output-dismiss" type="button" aria-label="סגרי" onClick={onDismiss}>✕</button>
    </div>
  );
}

// ─── Last generated report section ──────────────────────────────────────────
// Persistent access to existing report files. Complements the transient
// OutputBanner (which only appears right after generating in the current
// session). When has_report_pdf / has_report_xlsx come back true on list
// refresh, these buttons let the user open a report generated in a prior
// session — without having to regenerate it.

// ─── A1: Attachment section ───────────────────────────────────────────────────

function AttachmentSection({
  attachments, loading, uploading, deleting, onLoad, onUpload, onDelete,
}: {
  attachments: AttachmentOut[] | null | undefined;
  loading: boolean | undefined;
  uploading: boolean | undefined;
  deleting: Set<number> | undefined;
  onLoad: () => void;
  onUpload: (f: File) => void;
  onDelete: (id: number) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const isLoaded = attachments !== null && attachments !== undefined;

  if (!isLoaded && !loading) {
    return (
      <div className="attachment-section">
        <button type="button" className="ghost-btn small att-toggle-btn" onClick={onLoad}>
          📎 קבצים מצורפים ▼
        </button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="attachment-section">
        <span className="spinner" aria-hidden="true" />{" "}
        <span className="muted">טוענת קבצים...</span>
      </div>
    );
  }

  const list = attachments ?? [];

  function _formatBytes(n: number): string {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  }

  return (
    <div className="attachment-section">
      <div className="att-header">
        <span className="att-title">קבצים מצורפים</span>
        <span className="muted att-count">{list.length} קבצים</span>
        <label className={`ghost-btn small att-upload-label${uploading ? " disabled" : ""}`}>
          {uploading
            ? <><span className="spinner" aria-hidden="true" />מעלה...</>
            : "+ הוסיפי קובץ"}
          <input
            ref={inputRef}
            type="file"
            className="sr-only"
            disabled={uploading}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) { onUpload(f); e.target.value = ""; }
            }}
          />
        </label>
      </div>
      {list.length === 0 ? (
        <p className="muted att-empty">אין קבצים מצורפים.</p>
      ) : (
        <ul className="att-list" dir="rtl">
          {list.map((a) => {
            const isDel = deleting?.has(a.id);
            return (
              <li key={a.id} className="att-item">
                <span className="att-filename">{a.filename}</span>
                <span className="muted att-size">{_formatBytes(a.file_size)}</span>
                <button
                  type="button"
                  className="att-delete-btn"
                  disabled={isDel}
                  aria-label={`מחיקת ${a.filename}`}
                  onClick={() => onDelete(a.id)}
                >
                  {isDel ? <span className="spinner" aria-hidden="true" /> : "×"}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function LastReportSection({
  hasPdf, hasXlsx, onOpen,
}: {
  hasPdf: boolean;
  hasXlsx: boolean;
  onOpen: (k: "pdf" | "xlsx") => void;
}) {
  if (!hasPdf && !hasXlsx) return null;
  return (
    <div className="last-report-section">
      <span className="last-report-label">דו״ח סקירה אחרון:</span>
      {hasPdf && (
        <button type="button" className="ghost-btn small" onClick={() => onOpen("pdf")}>
          פתחי דו״ח PDF
        </button>
      )}
      {hasXlsx && (
        <button type="button" className="ghost-btn small" onClick={() => onOpen("xlsx")}>
          פתחי אקסל
        </button>
      )}
    </div>
  );
}
