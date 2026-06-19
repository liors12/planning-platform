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
  listComments,
  listDisciplines,
  patchComment,
  pollJobUntilDone,
  renderSubmission,
  type CommentOut,
  type DisciplineDef,
  type ProjectOut,
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
  const [rendering, setRendering] = useState(false);
  const [renderStage, setRenderStage] = useState<string>("");

  // PdfViewer reload via URL nonce — bumped after each successful render.
  const [pdfNonce, setPdfNonce] = useState(0);

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

  // ── Render button handler ─────────────────────────────────────────────
  async function handleRender() {
    setRendering(true);
    setRenderStage("מכינה דו\"ח...");
    try {
      const job = await renderSubmission(submission.id);
      const terminal = await pollJobUntilDone(
        job.id,
        (j) => {
          if (j.status === "queued") setRenderStage("בתור...");
          else if (j.status === "running") setRenderStage("מעדכנת את הדו\"ח...");
        },
        1000,
        90_000,
      );
      if (terminal.status === "completed") {
        setPdfNonce((n) => n + 1);
        setToast({ kind: "success", text: "הדו\"ח עודכן בהצלחה" });
      } else {
        setToast({
          kind: "error",
          text: 'שגיאה בעדכון הדו"ח — נסי שוב',
        });
      }
    } catch (e) {
      console.error("render failed", e);
      setToast({ kind: "error", text: 'שגיאה בעדכון הדו"ח — נסי שוב' });
    } finally {
      setRendering(false);
      setRenderStage("");
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
          onClick={handleRender}
          disabled={rendering}
        >
          {rendering ? (
            <>
              <span className="spinner" aria-hidden="true" />
              {renderStage || "מעדכנת..."}
            </>
          ) : (
            'צרי דו"ח מעודכן'
          )}
        </button>
        <span className="muted comments-meta">
          הגשה <span dir="ltr">{submission.version_string}</span> ·{" "}
          {comments?.length ?? 0} הערות
        </span>
      </div>

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
