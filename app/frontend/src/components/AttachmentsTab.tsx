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
};
const VERDICT_CLASS: Record<string, string> = {
  pass: "v-ok", fail: "v-fail", requires_review: "v-review",
};

export function AttachmentsTab({ project }: { project: ProjectOut }) {
  const [attachments, setAttachments] = useState<PlanAttachmentOut[] | null>(null);
  const [disciplines, setDisciplines] = useState<DisciplineDef[]>([]);
  const [err, setErr] = useState<string | null>(null);

  // Upload form
  const [type, setType] = useState("");
  const [version, setVersion] = useState("v1");
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

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
    const file = fileRef.current?.files?.[0];
    if (!file || !type) return;
    setUploading(true);
    setErr(null);
    try {
      await uploadPlanAttachment(project.id, type, version, file);
      if (fileRef.current) fileRef.current.value = "";
      setVersion("v1");
      await refresh();
    } catch (e) {
      setErr(String(e));
    }
    setUploading(false);
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
          <input value={version} onChange={(e) => setVersion(e.target.value)}
                 dir="ltr" placeholder="גרסה" data-testid="attachment-version" />
          <input ref={fileRef} type="file" accept=".pdf,.dxf,.dwfx,.dwf"
                 data-testid="attachment-file" />
          <button type="button" className="primary-btn"
                  data-testid="attachment-upload-submit"
                  disabled={uploading || !type}
                  onClick={onUpload}>
            {uploading ? "מעלה..." : "העלי נספח"}
          </button>
        </div>
      </div>

      {err && <MaybeApiError error={err} title="לא ניתן להשלים את הפעולה" />}
      {attachments !== null && attachments.length === 0 && (
        <p className="muted" data-testid="attachments-empty">
          אין עדיין נספחים לפרויקט זה. העלי נספח ראשון בטופס למעלה.
        </p>
      )}

      {attachments?.map((att) => (
        <AttachmentCard key={att.id} att={att} typeLabel={label(att.discipline_key)}
                        onChanged={refresh} />
      ))}
    </div>
  );
}

function AttachmentCard({
  att, typeLabel, onChanged,
}: { att: PlanAttachmentOut; typeLabel: string; onChanged: () => void }) {
  const [review, setReview] = useState<AttachmentReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const revisionRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (att.has_review) {
      getAttachmentReview(att.id).then(setReview).catch(() => {});
    }
  }, [att.id, att.has_review]);

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
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    setBusy(true);
    setErr(null);
    try {
      const nextVer = "v" + (parseInt(att.version_string.replace(/^v/, ""), 10) + 1 || 2);
      await uploadPlanAttachmentRevision(att.id, nextVer, file);
      onChanged();
    } catch (e2) { setErr(String(e2)); }
    setBusy(false);
  }

  async function onReport() {
    setBusy(true);
    try { await openAttachmentReport(att.id); setErr(null); }
    catch (e) { setErr(String(e)); }
    setBusy(false);
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
      <div className="attachment-card-header">
        <b>{typeLabel}</b>
        <span dir="ltr" className="muted">{att.version_string}</span>
        {att.source_attachment_id !== null && (
          <span className="badge badge-manual">גרסה מתוקנת</span>
        )}
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
      </div>

      <div className="attachment-actions">
        <button type="button" className="primary-btn" disabled={busy}
                data-testid={`attachment-run-review-${att.id}`}
                onClick={onRun}>
          {busy ? "בודקת..." : "הריצי בדיקה"}
        </button>
        <label className="ghost-btn attachment-revision-label">
          העלאת גרסה מתוקנת ↑
          <input ref={revisionRef} type="file" className="sr-only"
                 accept=".pdf,.dxf,.dwfx,.dwf" onChange={onRevision}
                 data-testid={`attachment-revision-${att.id}`} />
        </label>
        {att.has_review && (
          <button type="button" className="ghost-btn" disabled={busy}
                  data-testid={`attachment-report-${att.id}`}
                  onClick={onReport}>
            הפיקי דו"ח התייחסות
          </button>
        )}
      </div>

      {err && <MaybeApiError error={err} title="לא ניתן להשלים את הפעולה" />}

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
    </div>
  );
}
