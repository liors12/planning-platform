// Phase 2b Module D — "הערות רפרנטים" tab.
//
// Two-panel layout via SplitPane: left = grouped comment list + add form,
// right = current submission's PDF. Top button triggers --render-only via
// POST /submissions/{id}/render and polls the job until terminal.
//
// Comments live in the platform DB; on render, the engine merges them as
// extra §3 table rows tagged "(הערת רפרנט)". The engine's audit_results
// JSON is never touched, so re-running the engine never clobbers them.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createComment,
  deleteComment,
  exportExcel,
  extractReferentPdf,
  listComments,
  listDisciplines,
  openOutput,
  patchComment,
  pollJobUntilDone,
  renderSubmission,
  revealOutput,
  type CommentOut,
  type DisciplineDef,
  type ProjectOut,
  type ReferentExtractRow,
  type SubmissionOut,
} from "../api";
import { PdfViewer } from "./PdfViewer";
import { SplitPane } from "./SplitPane";

const SIDECAR_BASE = "http://127.0.0.1:17321";
const TOPIC_MAX_LEN = 60;

interface Props {
  project: ProjectOut;
  submission: SubmissionOut | null;
}

type ToastKind = "success" | "error";

interface Toast {
  kind: ToastKind;
  text: string;
}

interface ExtractedPreviewRow extends ReferentExtractRow {
  rowId: string;
}

export function CommentsTab({ project, submission }: Props) {
  // ── Gate ──────────────────────────────────────────────────────────────
  // Gate on has_audit_results, not status === "complete". A stuck status
  // label (e.g. left "failed" by an earlier render error) used to lock
  // the tab even though all downstream data — audit_results.m4.json,
  // PDF, Excel — was present and the comments render path was healthy.
  // Today Ellen hit exactly that on v24.3: status="failed",
  // has_audit_results=true. The presence of analyzed data is the real
  // precondition for adding referent comments.
  if (!submission || !submission.has_audit_results) {
    return (
      <div className="card placeholder-card">
        <span className="placeholder-phase">לא זמין</span>
        <h3>הערות רפרנטים</h3>
        <p className="muted">
          יש להריץ את התוכנה תחילה לפני הכנסת הערות רפרנטים.
        </p>
      </div>
    );
  }

  return <CommentsTabReady project={project} submission={submission} />;
}

function CommentsTabReady({ project, submission }: { project: ProjectOut; submission: SubmissionOut }) {
  const [disciplines, setDisciplines] = useState<DisciplineDef[]>([]);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [comments, setComments] = useState<CommentOut[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  const [toast, setToast] = useState<Toast | null>(null);

  // ── Regenerate-button feedback (P1 pattern, same shape as
  //    SubmissionsTab.OutputBanner) ─────────────────────────────────────
  // The previous version showed a 3-second auto-dismiss toast that was
  // easy to miss + offered no path to the produced files. The persistent
  // banner here matches the P1 success state from the submissions tab:
  // working → success-with-open-links → error. "Success" includes both
  // the PDF and the Excel — the regenerate flow now produces BOTH, since
  // the user expects updated comments to show up in either output.
  //
  // partial means one of the two jobs failed; we still surface the one
  // that succeeded so the user has something to open.
  type RegenStatus =
    | { kind: "working" }
    | { kind: "success" }
    | { kind: "partial"; pdfOk: boolean; xlsxOk: boolean }
    | { kind: "error"; friendly: string }
    | null;
  const [regenStatus, setRegenStatus] = useState<RegenStatus>(null);

  // PdfViewer reload via URL nonce — bumped after each successful render.
  const [pdfNonce, setPdfNonce] = useState(0);

  // ── PDF-extraction flow ───────────────────────────────────────────────
  const [extracting, setExtracting] = useState(false);
  const [extractErr, setExtractErr] = useState<string | null>(null);
  const [truncWarn, setTruncWarn] = useState<string | null>(null);
  const [preview, setPreview] = useState<ExtractedPreviewRow[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const pdfInputRef = useRef<HTMLInputElement>(null);

  // ── Load disciplines + comments ───────────────────────────────────────
  useEffect(() => {
    let alive = true;
    listDisciplines()
      .then((d) => {
        if (!alive) return;
        setDisciplines(d.disciplines);
        setStatuses(d.statuses);
      })
      .catch((e) => alive && setLoadErr(String(e)));
    return () => { alive = false; };
  }, []);

  const refreshComments = useCallback(async () => {
    try {
      const list = await listComments(submission.id);
      setComments(list);
      setLoadErr(null);
    } catch (e) {
      setLoadErr(String(e));
    }
  }, [submission.id]);

  useEffect(() => {
    setComments(null);
    refreshComments();
  }, [refreshComments]);

  // ── Toast auto-dismiss ────────────────────────────────────────────────
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  // ── Regenerate handler — PDF + Excel together ────────────────────────
  // Both outputs are produced in parallel so the user gets a single
  // "done" moment rather than two staggered ones. Each call enqueues
  // its own job; we await both before declaring success. If only one
  // succeeds we still surface the working file so nothing is lost.
  async function handleRegenerate() {
    setRegenStatus({ kind: "working" });
    let pdfOk = false;
    let xlsxOk = false;
    try {
      const [pdfJob, xlsxJob] = await Promise.all([
        renderSubmission(submission.id),
        exportExcel(submission.id),
      ]);
      // 90s for PDF (WeasyPrint can be slow on large reports), 60s for
      // Excel (always fast — pure openpyxl). No per-poll progress
      // callback — the working banner is sufficient feedback.
      const noProgress = () => { /* no-op */ };
      const [pdfTerm, xlsxTerm] = await Promise.allSettled([
        pollJobUntilDone(pdfJob.id, noProgress, 1000, 90_000),
        pollJobUntilDone(xlsxJob.id, noProgress, 1000, 60_000),
      ]);
      pdfOk = pdfTerm.status === "fulfilled" && pdfTerm.value.status === "completed";
      xlsxOk = xlsxTerm.status === "fulfilled" && xlsxTerm.value.status === "completed";
      if (pdfOk) setPdfNonce((n) => n + 1);   // reload the embedded viewer
      if (pdfOk && xlsxOk) {
        setRegenStatus({ kind: "success" });
      } else if (pdfOk || xlsxOk) {
        setRegenStatus({ kind: "partial", pdfOk, xlsxOk });
      } else {
        setRegenStatus({
          kind: "error",
          friendly: "אירעה תקלה ביצירת הדו״ח. הפרטים נשמרו לקובץ יומן.",
        });
      }
    } catch (e) {
      console.error("regenerate failed", e);
      setRegenStatus({
        kind: "error",
        friendly: "אירעה תקלה ביצירת הדו״ח. הפרטים נשמרו לקובץ יומן.",
      });
    }
  }

  function updatePreviewRow(rowId: string, patch: Partial<ExtractedPreviewRow>) {
    setPreview((prev) =>
      prev?.map((r) => (r.rowId === rowId ? { ...r, ...patch } : r)) ?? null,
    );
  }

  function removePreviewRow(rowId: string) {
    setPreview((prev) => prev?.filter((r) => r.rowId !== rowId) ?? null);
  }

  async function handlePdfFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = ""; // allow re-selecting same file
    if (file.size > 20 * 1024 * 1024) {
      setExtractErr("הקובץ גדול מדי — העלי קובץ עד 20MB.");
      return;
    }
    setExtracting(true);
    setExtractErr(null);
    setTruncWarn(null);
    setPreview(null);
    setSaveErr(null);
    try {
      const result = await extractReferentPdf(submission.id, file);
      if (result.error === "scan") {
        setExtractErr(
          result.error_message ??
            "לא ניתן לחלץ טקסט מה-PDF — ייתכן שהוא סרוק. המרי לפורמט טקסט ונסי שוב.",
        );
      } else if (result.comments.length === 0) {
        setExtractErr("לא נמצאו הערות ב-PDF. ניתן להוסיף הערות ידנית בטופס למטה.");
      } else {
        if (result.truncation_warning) setTruncWarn(result.truncation_warning);
        setPreview(
          result.comments.map((c) => ({ ...c, rowId: crypto.randomUUID() })),
        );
      }
    } catch (err) {
      setExtractErr("שגיאה בחילוץ ה-PDF. בדקי שהקובץ תקין ונסי שוב.");
      console.error("extractReferentPdf failed", err);
    }
    setExtracting(false);
  }

  async function handleSavePreview() {
    if (!preview || saving) return;
    setSaving(true);
    setSaveErr(null);
    let failed = 0;
    let firstId: string | undefined;
    for (const row of preview) {
      try {
        const created = await createComment(submission.id, {
          discipline_key: row.discipline_key,
          status: row.status,
          topic_he: row.topic_he.trim() || row.action_he.trim().slice(0, TOPIC_MAX_LEN),
          action_he: row.action_he.trim(),
        });
        if (!firstId) firstId = created.id;
      } catch {
        failed++;
      }
    }
    setSaving(false);
    await refreshComments();
    if (failed > 0) {
      setSaveErr(
        `${failed} הערות לא נשמרו. ${preview.length - failed} נשמרו בהצלחה.`,
      );
    } else {
      setPreview(null);
      setSaveErr(null);
      if (firstId) scrollIntoView(firstId);
    }
  }

  async function onOpenRegen(kind: "pdf" | "xlsx") {
    try {
      await openOutput(submission.id, kind);
    } catch (e) {
      setToast({ kind: "error", text: 'לא ניתן לפתוח את הקובץ — נסי "פתחי תיקייה".' });
      console.error("openOutput failed", e);
    }
  }

  async function onRevealRegen(kind: "pdf" | "xlsx") {
    try {
      await revealOutput(submission.id, kind);
    } catch (e) {
      setToast({ kind: "error", text: 'לא ניתן לפתוח את התיקייה.' });
      console.error("revealOutput failed", e);
    }
  }

  // ── Grouping for display ──────────────────────────────────────────────
  const grouped = useMemo(() => {
    if (!comments) return [];
    const labelOf = new Map(disciplines.map((d) => [d.key, d.label]));
    const byKey = new Map<string, CommentOut[]>();
    for (const c of comments) {
      if (!byKey.has(c.discipline_key)) byKey.set(c.discipline_key, []);
      byKey.get(c.discipline_key)!.push(c);
    }
    // Preserve discipline order from the canonical list.
    return disciplines
      .filter((d) => byKey.has(d.key))
      .map((d) => ({
        key: d.key,
        label: labelOf.get(d.key) ?? d.key,
        items: byKey.get(d.key)!,
      }));
  }, [comments, disciplines]);

  const pdfUrl = `${SIDECAR_BASE}/submissions/${submission.id}/pdf?v=${pdfNonce}`;

  // Ref for scrolling a newly-added comment into view.
  const lastAddedIdRef = useRef<string | null>(null);
  function scrollIntoView(id: string) {
    requestAnimationFrame(() => {
      const el = document.getElementById(`comment-${id}`);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }

  return (
    <div className="comments-tab-root">
      <div className="comments-toolbar">
        <button
          className="primary-btn render-btn"
          data-testid="regenerate-comments-report"
          onClick={handleRegenerate}
          disabled={regenStatus?.kind === "working"}
        >
          {regenStatus?.kind === "working" ? (
            <>
              <span className="spinner" aria-hidden="true" />
              יוצרת דו״ח מעודכן + אקסל, נא להמתין...
            </>
          ) : (
            'צרי דו"ח מעודכן'
          )}
        </button>
        <button
          className="ghost-btn"
          data-testid="pdf-extract-btn"
          type="button"
          onClick={() => pdfInputRef.current?.click()}
          disabled={extracting}
        >
          {extracting ? (
            <><span className="spinner" aria-hidden="true" /> מחלצת הערות מ-PDF...</>
          ) : (
            "העלי הערות PDF"
          )}
        </button>
        <input
          ref={pdfInputRef}
          type="file"
          accept=".pdf,application/pdf"
          style={{ display: "none" }}
          onChange={handlePdfFileChange}
        />
        <span className="muted comments-meta">
          הגשה <span dir="ltr">{submission.version_string}</span> ·{" "}
          {comments?.length ?? 0} הערות
        </span>
      </div>

      <RegenBanner
        status={regenStatus}
        onOpen={onOpenRegen}
        onReveal={onRevealRegen}
        onDismiss={() => setRegenStatus(null)}
      />

      {(extractErr || (preview !== null)) && (
        <div className="card pdf-extract-card">
          <div className="pdf-extract-header">
            <h4 className="pdf-extract-title">
              {extractErr ? "שגיאת חילוץ PDF" : "תצוגה מקדימה — הערות שחולצו"}
            </h4>
            <button
              type="button"
              className="ghost-btn small"
              onClick={() => { setPreview(null); setExtractErr(null); setTruncWarn(null); setSaveErr(null); }}
            >
              סגרי ✕
            </button>
          </div>
          {extractErr && <div className="error">{extractErr}</div>}
          {truncWarn && <div className="warning-banner">{truncWarn}</div>}
          {saveErr && <div className="error">{saveErr}</div>}
          {preview !== null && preview.length === 0 && (
            <p className="muted">לא נמצאו הערות לשמירה.</p>
          )}
          {preview?.map((row) => (
            <div key={row.rowId} className="pdf-extract-row">
              <div className="pdf-extract-row-header">
                <select
                  value={row.discipline_key}
                  onChange={(e) => updatePreviewRow(row.rowId, { discipline_key: e.target.value })}
                  aria-label="דיסציפלינה"
                >
                  <option value="">בחרי דיסציפלינה ▾</option>
                  {disciplines.map((d) => (
                    <option key={d.key} value={d.key}>{d.label}</option>
                  ))}
                </select>
                <select
                  value={row.status}
                  onChange={(e) => updatePreviewRow(row.rowId, { status: e.target.value })}
                  aria-label="סטטוס"
                >
                  <option value="">בחרי סטטוס ▾</option>
                  {statuses.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
                <span
                  className={
                    "conf-badge " +
                    (row.confidence === "high" ? "conf-high" : "conf-low")
                  }
                  title={
                    row.confidence === "high"
                      ? "המודל זיהה את הדיסציפלינה והסטטוס בביטחון גבוה"
                      : "הסיווג אינו ודאי — מומלץ לבדוק"
                  }
                >
                  {row.confidence === "high" ? "ודאות גבוהה" : "ודאות נמוכה"}
                </span>
              </div>
              <input
                type="text"
                value={row.topic_he}
                maxLength={TOPIC_MAX_LEN}
                onChange={(e) => updatePreviewRow(row.rowId, { topic_he: e.target.value })}
                placeholder={`נושא (עד ${TOPIC_MAX_LEN} תווים)`}
              />
              <textarea
                value={row.action_he}
                onChange={(e) => updatePreviewRow(row.rowId, { action_he: e.target.value })}
                placeholder="פעולה נדרשת"
                rows={3}
              />
              <button
                type="button"
                className="icon-btn danger"
                aria-label="הסירי שורה"
                onClick={() => removePreviewRow(row.rowId)}
              >
                🗑
              </button>
            </div>
          ))}
          {preview !== null && preview.length > 0 && (
            <div className="pdf-extract-actions">
              <button
                type="button"
                className="primary-btn"
                data-testid="pdf-extract-save-btn"
                onClick={handleSavePreview}
                disabled={
                  saving ||
                  preview.some(
                    (r) => !r.discipline_key || !r.status || !r.action_he.trim(),
                  )
                }
              >
                {saving ? "שומרת..." : `שמרי ${preview.length} הערות`}
              </button>
            </div>
          )}
        </div>
      )}

      {loadErr && <div className="error error-block">{loadErr}</div>}

      <SplitPane
        storageKey={`splitter:comments_project_${project.id}`}
        defaultStartFraction={0.50}
        minFraction={0.30}
        maxFraction={0.75}
      >
        <CommentListPanel
          grouped={grouped}
          disciplines={disciplines}
          statuses={statuses}
          submissionId={submission.id}
          loading={comments === null}
          onChanged={async (newId) => {
            await refreshComments();
            if (newId) {
              lastAddedIdRef.current = newId;
              scrollIntoView(newId);
            }
          }}
        />
        <PdfViewer fileUrl={pdfUrl} target={null} />
      </SplitPane>

      {toast && (
        <div
          className={"comments-toast " + (toast.kind === "success" ? "ok" : "err")}
          role="status"
        >
          {toast.text}
        </div>
      )}
    </div>
  );
}

// ── Persistent regenerate-status banner (P1 pattern from SubmissionsTab) ──
// Stays visible until the user dismisses it (no auto-fade like the old
// 3-second toast). The success state exposes the same actions the
// submissions-tab banner does — open PDF, open Excel, open folder.
type RegenBannerStatus =
  | { kind: "working" }
  | { kind: "success" }
  | { kind: "partial"; pdfOk: boolean; xlsxOk: boolean }
  | { kind: "error"; friendly: string }
  | null;

function RegenBanner({
  status, onOpen, onReveal, onDismiss,
}: {
  status: RegenBannerStatus;
  onOpen: (k: "pdf" | "xlsx") => void;
  onReveal: (k: "pdf" | "xlsx") => void;
  onDismiss: () => void;
}) {
  if (!status) return null;

  if (status.kind === "working") {
    return (
      <div className="output-banner output-working" role="status" aria-live="polite"
           data-testid="regen-banner-working">
        <span className="spinner" aria-hidden="true" />
        <span>יוצרת דו״ח מעודכן + אקסל, נא להמתין...</span>
      </div>
    );
  }

  if (status.kind === "success") {
    return (
      <div className="output-banner output-success" role="status" aria-live="polite"
           data-testid="regen-banner-success">
        <span className="output-icon" aria-hidden="true">✓</span>
        <span className="output-msg">
          הדו״ח המעודכן והאקסל מוכנים ✓ • שמורים בתיקיית התוצאות של הפרויקט
        </span>
        <button className="ghost-btn small" type="button"
                data-testid="regen-open-pdf"
                onClick={() => onOpen("pdf")}>פתחי דו״ח</button>
        <button className="ghost-btn small" type="button"
                data-testid="regen-open-xlsx"
                onClick={() => onOpen("xlsx")}>פתחי אקסל</button>
        <button className="ghost-btn small" type="button"
                onClick={() => onReveal("pdf")}>פתחי תיקייה</button>
        <button className="output-dismiss" type="button" aria-label="סגרי"
                onClick={onDismiss}>✕</button>
      </div>
    );
  }

  if (status.kind === "partial") {
    // One succeeded, one failed. Show what worked + a calm note about
    // the other. The "failed" half is recoverable by clicking the
    // regenerate button again — common cause is a transient lock on
    // the output file.
    return (
      <div className="output-banner output-success" role="status" aria-live="polite"
           data-testid="regen-banner-partial">
        <span className="output-icon" aria-hidden="true">⚠</span>
        <span className="output-msg">
          {status.pdfOk && !status.xlsxOk && "הדו״ח עודכן ✓ • האקסל לא נוצר — לחצי שוב על הכפתור."}
          {!status.pdfOk && status.xlsxOk && "האקסל עודכן ✓ • הדו״ח לא נוצר — לחצי שוב על הכפתור."}
        </span>
        {status.pdfOk && (
          <button className="ghost-btn small" type="button"
                  onClick={() => onOpen("pdf")}>פתחי דו״ח</button>
        )}
        {status.xlsxOk && (
          <button className="ghost-btn small" type="button"
                  onClick={() => onOpen("xlsx")}>פתחי אקסל</button>
        )}
        <button className="output-dismiss" type="button" aria-label="סגרי"
                onClick={onDismiss}>✕</button>
      </div>
    );
  }

  // error
  return (
    <div className="output-banner output-error" role="alert"
         data-testid="regen-banner-error">
      <span className="output-icon" aria-hidden="true">✗</span>
      <span className="output-msg">{status.friendly}</span>
      <button className="output-dismiss" type="button" aria-label="סגרי"
              onClick={onDismiss}>✕</button>
    </div>
  );
}

// ─── Left panel — list + add form ────────────────────────────────────────

interface GroupedItem {
  key: string;
  label: string;
  items: CommentOut[];
}

function CommentListPanel({
  grouped,
  disciplines,
  statuses,
  submissionId,
  loading,
  onChanged,
}: {
  grouped: GroupedItem[];
  disciplines: DisciplineDef[];
  statuses: string[];
  submissionId: number;
  loading: boolean;
  onChanged: (newId?: string) => Promise<void> | void;
}) {
  return (
    <div className="comments-list-panel">
      {loading ? (
        <p className="muted">טוענת הערות...</p>
      ) : grouped.length === 0 ? (
        <p className="muted comments-empty">
          אין עדיין הערות. הוסיפי הערה ראשונה בטופס למטה.
        </p>
      ) : (
        grouped.map((g) => (
          <section className="comments-group" key={g.key}>
            <h3 className="comments-group-title">{g.label}</h3>
            {g.items.map((c) => (
              <CommentRow
                key={c.id}
                comment={c}
                disciplines={disciplines}
                statuses={statuses}
                submissionId={submissionId}
                onChanged={onChanged}
              />
            ))}
          </section>
        ))
      )}

      <AddCommentForm
        disciplines={disciplines}
        statuses={statuses}
        submissionId={submissionId}
        onCreated={onChanged}
      />
    </div>
  );
}

// ─── Single comment row (view + inline edit + inline delete-confirm) ─────

const STATUS_CLASS: Record<string, string> = {
  "תקין": "status-ok",
  "לא תקין": "status-fail",
  "נדרשת השלמה": "status-rev",
};

function CommentRow({
  comment,
  disciplines,
  statuses,
  submissionId,
  onChanged,
}: {
  comment: CommentOut;
  disciplines: DisciplineDef[];
  statuses: string[];
  submissionId: number;
  onChanged: (newId?: string) => Promise<void> | void;
}) {
  const [mode, setMode] = useState<"view" | "edit" | "confirm-delete">("view");
  const [expanded, setExpanded] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [editStatus, setEditStatus] = useState(comment.status);
  const [editTopic, setEditTopic] = useState(comment.topic_he);
  const [editAction, setEditAction] = useState(comment.action_he);
  const [editDiscipline, setEditDiscipline] = useState(comment.discipline_key);

  useEffect(() => {
    setEditStatus(comment.status);
    setEditTopic(comment.topic_he);
    setEditAction(comment.action_he);
    setEditDiscipline(comment.discipline_key);
  }, [comment]);

  async function save() {
    setErr(null);
    try {
      await patchComment(submissionId, comment.id, {
        discipline_key: editDiscipline,
        status: editStatus,
        topic_he: editTopic,
        action_he: editAction,
      });
      setMode("view");
      await onChanged();
    } catch (e) {
      setErr(String(e));
    }
  }

  async function doDelete() {
    setErr(null);
    try {
      await deleteComment(submissionId, comment.id);
      await onChanged();
    } catch (e) {
      setErr(String(e));
      setMode("view");
    }
  }

  const statusCls = STATUS_CLASS[comment.status] ?? "status-rev";

  if (mode === "edit") {
    return (
      <div className="comment-row comment-row-edit" id={`comment-${comment.id}`}>
        <div className="comment-edit-grid">
          <select
            value={editDiscipline}
            onChange={(e) => setEditDiscipline(e.target.value)}
          >
            {disciplines.map((d) => (
              <option key={d.key} value={d.key}>{d.label}</option>
            ))}
          </select>
          <select
            value={editStatus}
            onChange={(e) => setEditStatus(e.target.value)}
          >
            {statuses.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <input
            type="text"
            value={editTopic}
            maxLength={TOPIC_MAX_LEN}
            onChange={(e) => setEditTopic(e.target.value)}
            placeholder="נושא"
          />
          <textarea
            value={editAction}
            onChange={(e) => setEditAction(e.target.value)}
            placeholder="פעולה נדרשת"
            rows={3}
          />
        </div>
        {err && <div className="error">{err}</div>}
        <div className="comment-row-actions">
          <button className="primary-btn small" onClick={save}>שמרי</button>
          <button className="ghost-btn small" onClick={() => setMode("view")}>
            ביטול
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="comment-row" id={`comment-${comment.id}`}>
      <div className="comment-row-head">
        <span className={"status-badge " + statusCls}>{comment.status}</span>
        <span className="comment-topic">{comment.topic_he}</span>
        <div className="comment-row-icons">
          <button
            className="icon-btn"
            title="ערכי"
            aria-label="ערכי"
            onClick={() => setMode("edit")}
          >
            ✎
          </button>
          <button
            className="icon-btn danger"
            title="מחקי"
            aria-label="מחקי"
            onClick={() => setMode("confirm-delete")}
          >
            🗑
          </button>
        </div>
      </div>
      <div
        className={"comment-action " + (expanded ? "" : "clamped")}
        onClick={() => setExpanded((x) => !x)}
      >
        {comment.action_he}
      </div>
      {!expanded && comment.action_he.length > 120 && (
        <button className="comment-expand" onClick={() => setExpanded(true)}>
          הציגי הכל
        </button>
      )}

      {mode === "confirm-delete" && (
        <div className="comment-confirm-row">
          <span>בטוח?</span>
          <button className="primary-btn small danger" onClick={doDelete}>
            כן
          </button>
          <button className="ghost-btn small" onClick={() => setMode("view")}>
            לא
          </button>
        </div>
      )}
      {err && <div className="error">{err}</div>}
    </div>
  );
}

// ─── Add-comment form (sticky bottom) ─────────────────────────────────────

function AddCommentForm({
  disciplines,
  statuses,
  submissionId,
  onCreated,
}: {
  disciplines: DisciplineDef[];
  statuses: string[];
  submissionId: number;
  onCreated: (newId?: string) => Promise<void> | void;
}) {
  const [discipline, setDiscipline] = useState("");
  const [status, setStatus] = useState("");
  const [topic, setTopic] = useState("");
  const [action, setAction] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const ready = Boolean(
    discipline && status && topic.trim().length > 0 && action.trim().length > 0,
  );

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const created = await createComment(submissionId, {
        discipline_key: discipline,
        status,
        topic_he: topic.trim(),
        action_he: action.trim(),
      });
      // Reset form
      setDiscipline("");
      setStatus("");
      setTopic("");
      setAction("");
      await onCreated(created.id);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="add-comment-form card" onSubmit={submit}>
      <h4 className="add-comment-title">הוספת הערה</h4>
      <div className="add-comment-grid">
        <select
          value={discipline}
          onChange={(e) => setDiscipline(e.target.value)}
          aria-label="דיסציפלינה"
        >
          <option value="">בחרי דיסציפלינה ▾</option>
          {disciplines.map((d) => (
            <option key={d.key} value={d.key}>{d.label}</option>
          ))}
        </select>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          aria-label="סטטוס"
        >
          <option value="">בחרי סטטוס ▾</option>
          {statuses.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <div className="topic-wrap">
          <input
            type="text"
            value={topic}
            maxLength={TOPIC_MAX_LEN}
            onChange={(e) => setTopic(e.target.value)}
            placeholder={`נושא (עד ${TOPIC_MAX_LEN} תווים)`}
          />
          <span className="topic-counter muted">
            {topic.length}/{TOPIC_MAX_LEN}
          </span>
        </div>
        <textarea
          value={action}
          onChange={(e) => setAction(e.target.value)}
          placeholder="פעולה נדרשת"
          rows={3}
        />
      </div>
      {err && <div className="error">{err}</div>}
      <div className="add-comment-actions">
        <button
          type="submit"
          className="primary-btn"
          disabled={!ready || busy}
        >
          {busy ? "מוסיפה..." : "+ הוסיפי הערה"}
        </button>
      </div>
    </form>
  );
}
