import { useCallback, useEffect, useRef, useState } from "react";
import {
  getAttachmentReview,
  listDisciplines,
  listProjectAttachments,
  openAttachmentReport,
  runAttachmentReview,
  setAttachmentStatus,
  uploadPlanAttachment,
  uploadPlanAttachmentRevision,
  type PlanAttachmentOut,
  type AttachmentReview,
  type DisciplineDef,
  type ProjectOut,
} from "../api";
import { MaybeApiError } from "./ErrorNotice";
import { displayDate } from "../lib/duration";
import { IsolateLtr } from "../lib/bidi";

// v0.2.0: נספחי תוכנית עיצוב - typed, versioned attachments with a status
// flow and MAPPED reviews (only the checks mapped to the attachment's type
// run; see attachment_check_mapping.json).

const STATUS_HE: Record<PlanAttachmentOut["status"], string> = {
  prepared: "הוכן",
  sent: "נשלח",
  response_received: "התקבלה תשובה",
  closed: "נסגר",
};
const STATUS_FLOW: PlanAttachmentOut["status"][] = [
  "prepared", "sent", "response_received", "closed",
];

const VERDICT_HE: Record<string, string> = {
  pass: "תקין",
  fail: "נדרש תיקון",
  requires_review: "נדרשת בדיקה",
  manual_review: "נדרשת בדיקה ידנית",
  not_submitted: "לא הוגש",
};
const VERDICT_CLASS: Record<string, string> = {
  pass: "v-ok", fail: "v-fail", requires_review: "v-review",
  manual_review: "v-review", not_submitted: "v-fail",
};

// v0.2.3: the version is the server's number, read as "גרסה 2". A row from
// before v0.2.3 whose free-text label has no number shows the label as is.
export function versionLabel(att: PlanAttachmentOut): string {
  return att.version_number !== null ? `גרסה ${att.version_number}` : `גרסה ${att.version_string}`;
}

// Same words as the דו"ח התייחסות (attachments.py _readability_he).
function readabilityHe(f: NonNullable<AttachmentReview["files"]>[number]): string {
  if (f.garbled) return "לא ניתן לקרוא את הטקסט בקובץ";
  if (f.pages && f.unreadable_pages === 0) return "קריא";
  if (f.unreadable_pages >= f.pages) return "אין בקובץ טקסט קריא";
  return `קריא בחלקו (${f.pages - f.unreadable_pages} מתוך ${f.pages} עמודים)`;
}

export function AttachmentsTab({ project }: { project: ProjectOut }) {
  const [attachments, setAttachments] = useState<PlanAttachmentOut[] | null>(null);
  const [disciplines, setDisciplines] = useState<DisciplineDef[]>([]);
  const [err, setErr] = useState<string | null>(null);

  // Upload form
  const [type, setType] = useState("");
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  // v0.2.3 §3f: after an upload the check runs by itself. Per attachment:
  // "checking" while it runs, "done" once the report is ready.
  const [phase, setPhase] = useState<Record<number, "checking" | "done">>({});

  const refresh = useCallback(async () => {
    try {
      setAttachments(await listProjectAttachments(project.id));
      setErr(null);
    } catch (e) {
      setErr(String(e));
    }
  }, [project.id]);

  useEffect(() => {
    refresh();
    listDisciplines().then((d) => setDisciplines(d.disciplines)).catch(() => {});
  }, [refresh]);

  async function onUpload() {
    const files = Array.from(fileRef.current?.files ?? []);
    if (files.length === 0 || !type) return;
    setUploading(true);
    setErr(null);
    let att: PlanAttachmentOut;
    try {
      att = await uploadPlanAttachment(project.id, type, files);
      if (fileRef.current) fileRef.current.value = "";
    } catch (e) {
      setErr(String(e));
      setUploading(false);
      return;
    }
    setUploading(false);
    await checkNow(att.id);
  }

  // Shared by upload and revision: show "בודקת...", run (or await) the
  // check, then "הבדיקה הסתיימה - הדו"ח מוכן".
  async function checkNow(attId: number, alreadyRun = false) {
    setPhase((p) => ({ ...p, [attId]: "checking" }));
    await refresh();
    try {
      if (!alreadyRun) await runAttachmentReview(attId);
      setPhase((p) => ({ ...p, [attId]: "done" }));
    } catch (e) {
      setErr(String(e));
      setPhase((p) => { const n = { ...p }; delete n[attId]; return n; });
    }
    await refresh();
  }

  const label = (key: string) =>
    disciplines.find((d) => d.key === key)?.label ?? key;

  return (
    <div className="attachments-tab-root">
      <div className="card attachment-upload-card">
        <h3 className="card-title">העלאת נספח</h3>
        <div className="attachment-upload-grid">
          <select value={type} onChange={(e) => setType(e.target.value)}
                  data-testid="attachment-type" aria-label="סוג נספח">
            <option value="">בחרי סוג נספח ▾</option>
            {disciplines.map((d) => (
              <option key={d.key} value={d.key}>{d.label}</option>
            ))}
          </select>
          <input ref={fileRef} type="file" accept=".pdf,.dxf,.dwfx,.dwf" multiple
                 aria-label="קובצי הנספח - אפשר לבחור כמה קבצים"
                 data-testid="attachment-file" />
          <button type="button" className="primary-btn"
                  data-testid="attachment-upload-submit"
                  disabled={uploading || !type}
                  onClick={onUpload}>
            {uploading ? "מעלה את הקבצים..." : "העלי נספח"}
          </button>
        </div>
      </div>

      {err && <MaybeApiError error={err} title="לא ניתן להשלים את הפעולה" />}
      {attachments !== null && attachments.length === 0 && (
        <p className="muted" data-testid="attachments-empty">
          אין עדיין נספחים לפרויקט זה. העלי נספח ראשון בטופס למעלה.
        </p>
      )}

      {/* v0.2.3 §3h: newest on top. */}
      {[...(attachments ?? [])].sort((a, b) => b.id - a.id).map((att) => (
        <AttachmentCard key={att.id} att={att} typeLabel={label(att.discipline_key)}
                        phase={phase[att.id] ?? null}
                        onRevised={(next) => checkNow(next.id, true)}
                        onChanged={refresh} />
      ))}
    </div>
  );
}

function AttachmentCard({
  att, typeLabel, phase, onRevised, onChanged,
}: {
  att: PlanAttachmentOut;
  typeLabel: string;
  phase: "checking" | "done" | null;
  onRevised: (next: PlanAttachmentOut) => void;
  onChanged: () => void;
}) {
  const [review, setReview] = useState<AttachmentReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [reportState, setReportState] =
    useState<"idle" | "working" | "opened">("idle");
  // The card has one error slot; the title tells Ellen which action failed.
  const [errTitle, setErrTitle] = useState("לא ניתן להשלים את הפעולה");
  const [err, setErr] = useState<string | null>(null);
  const revisionRef = useRef<HTMLInputElement>(null);
  // v0.2.3 §3h: a row is collapsed until Ellen opens it.
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (att.has_review && phase !== "checking") {
      getAttachmentReview(att.id).then(setReview).catch(() => {});
    }
  }, [att.id, att.has_review, phase]);

  async function onRun() {
    setBusy(true);
    setErr(null);
    try {
      setReview(await runAttachmentReview(att.id));
      onChanged();
    } catch (e) { setErr(String(e)); }
    setBusy(false);
  }

  async function onRevision(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;
    e.target.value = "";
    setBusy(true);
    setErr(null);
    try {
      // The server runs the check as part of the revision upload.
      onRevised(await uploadPlanAttachmentRevision(att.id, files));
    } catch (e2) { setErr(String(e2)); }
    setBusy(false);
  }

  // Same three-state story as the guidelines PDF button: the file is
  // generated then opened by the OS, so the button must say so.
  async function onReport() {
    if (reportState === "working") return;
    setReportState("working");
    setErr(null);
    try {
      await openAttachmentReport(att.id);
      setReportState("opened");
      window.setTimeout(() => setReportState("idle"), 4000);
    } catch (e) {
      setErrTitle("לא ניתן להפיק את הקובץ");
      setErr(String(e));
      setReportState("idle");
    }
  }

  async function onStatus(s: PlanAttachmentOut["status"]) {
    setBusy(true);
    try { await setAttachmentStatus(att.id, s); onChanged(); }
    catch (e) { setErr(String(e)); }
    setBusy(false);
  }

  return (
    <div className="card attachment-card"
         data-testid={`attachment-card-${att.id}`}>
      <div className="attachment-row">
        <button type="button" className="attachment-row-toggle"
                aria-expanded={open}
                data-testid={`attachment-toggle-${att.id}`}
                onClick={() => setOpen((o) => !o)}>
          <span className="attachment-row-chevron" aria-hidden="true">{open ? "▾" : "◂"}</span>
          <b>{typeLabel}</b>
          <span className="muted" data-testid={`attachment-version-${att.id}`}>
            {versionLabel(att)}
          </span>
          {att.source_attachment_id !== null && (
            <span className="badge badge-manual">גרסה מתוקנת</span>
          )}
          {att.uploaded_at && (
            <span className="muted" dir="ltr">{displayDate(att.uploaded_at.slice(0, 10))}</span>
          )}
          <span className="attachment-row-status" data-testid={`attachment-row-status-${att.id}`}>
            {STATUS_HE[att.status]}
          </span>
        </button>
        {att.has_review && (
          <button type="button" className="ghost-btn"
                  disabled={busy || reportState === "working"}
                  data-pdf-state={reportState}
                  data-testid={`attachment-report-${att.id}`}
                  onClick={onReport}>
            {reportState === "working" && "מכינה את הקובץ..."}
            {reportState === "opened" && "הקובץ נפתח"}
            {reportState === "idle" && 'הפיקי דו"ח התייחסות'}
          </button>
        )}
      </div>

      {phase === "checking" && (
        <div className="banner attachment-phase" role="status"
             data-testid={`attachment-checking-${att.id}`}>
          <span className="spinner" aria-hidden="true" /> בודקת...
        </div>
      )}
      {phase === "done" && (
        <div className="banner banner-ok attachment-phase" role="status"
             data-testid={`attachment-done-${att.id}`}>
          <span>הבדיקה הסתיימה - הדו"ח מוכן</span>
          <button type="button" className="primary-btn small"
                  disabled={reportState === "working"}
                  data-testid={`attachment-open-report-${att.id}`}
                  onClick={onReport}>
            {reportState === "working" ? "מכינה את הקובץ..." : 'פתחי את הדו"ח'}
          </button>
        </div>
      )}

      {err && <MaybeApiError error={err} title={errTitle} />}

      {open && (<div className="attachment-body" data-testid={`attachment-body-${att.id}`}>
      <span className="attachment-status-stepper">
        {STATUS_FLOW.map((s) => (
          <button key={s} type="button"
                  className={"status-step" + (att.status === s ? " current" : "")}
                  disabled={busy}
                  data-testid={`attachment-status-${att.id}-${s}`}
                  onClick={() => onStatus(s)}>
            {STATUS_HE[s]}
          </button>
        ))}
      </span>

      <div className="attachment-actions">
        <button type="button" className="primary-btn" disabled={busy}
                data-testid={`attachment-run-review-${att.id}`}
                onClick={onRun}>
          {busy ? "בודקת..." : att.has_review ? "בדיקה חוזרת" : "הריצי בדיקה"}
        </button>
        <label className="ghost-btn attachment-revision-label">
          העלאת גרסה מתוקנת ↑
          <input ref={revisionRef} type="file" className="sr-only" multiple
                 accept=".pdf,.dxf,.dwfx,.dwf" onChange={onRevision}
                 data-testid={`attachment-revision-${att.id}`} />
        </label>
      </div>

      <div className="attachment-files muted" data-testid={`attachment-files-${att.id}`}>
        {att.files.length === 1 ? "קובץ: " : `${att.files.length} קבצים: `}
        {att.files.map((f, i) => (
          <span key={i}>{i > 0 && " · "}<IsolateLtr text={f.name} /></span>
        ))}
      </div>

      {review?.files && review.files.length > 1 && (
        <table className="attachment-files-table" data-testid={`attachment-files-review-${att.id}`}>
          <thead><tr><th>קובץ</th><th>עמודים</th><th>קריאות הטקסט</th><th>פריטים שנמצאו בקובץ</th></tr></thead>
          <tbody>
            {review.files.map((f, i) => (
              <tr key={i}>
                <td><IsolateLtr text={f.name} /></td>
                <td>{f.pages}</td>
                <td>{readabilityHe(f)}</td>
                <td>{f.found.length ? f.found.join(", ") : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {review && (
        <ul className="attachment-review-list"
            data-testid={`attachment-review-${att.id}`}>
          {review.checks.map((c) => (
            <li key={c.rule_code} className="finding-row">
              <div className="finding-row-main">
                <span className={"verdict-badge " + (VERDICT_CLASS[c.verdict] ?? "v-review")}>
                  {VERDICT_HE[c.verdict] ?? c.verdict}
                </span>
                <div className="finding-row-body">
                  <div className="finding-row-title">
                    <span className="finding-row-name">{c.rule_name_he}</span>
                  </div>
                  <div className="finding-row-brief">{c.notes_he}</div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      </div>)}
    </div>
  );
}
