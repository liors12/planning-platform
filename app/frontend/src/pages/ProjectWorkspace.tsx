import { useEffect, useState } from "react";
import { archiveProject, getProject, getFindings, listSubmissions, patchProject, type ProjectOut, type SubmissionOut } from "../api";
import { AttachmentsTab } from "../components/AttachmentsTab";
import { CommentsTab } from "../components/CommentsTab";
import { ErrorNotice } from "../components/ErrorNotice";
import { DebugOverlay } from "../components/DebugOverlay";
import { LayerMappingTab } from "../components/LayerMappingTab";
import { SubmissionsTab } from "../components/SubmissionsTab";
import { FindingsView } from "../components/FindingsView";
import { PdfViewer } from "../components/PdfViewer";
import { SplitPane } from "../components/SplitPane";
import { buildHash, type Route } from "../route";
import { displayDate, timeSince } from "../lib/duration";

const SIDECAR_BASE = "http://127.0.0.1:17321";

interface Props {
  projectId: number;
  navigate: (r: Route) => void;
  onProjectChanged: () => void;
}

// Removed tabs: "guidelines" (now the GLOBAL top-level #/guidelines screen),
// and the "history" / "final" placeholders - stubs confused non-technical
// users; the report itself is produced from הגשות → "הפיקי דו״ח".
type TabKey = "overview" | "submissions" | "attachments" | "findings" | "comments" | "cad_layers";

const TAB_LABELS: Record<TabKey, string> = {
  overview: "סקירה כללית",
  submissions: "הגשות",
  attachments: "נספחי תוכנית עיצוב",
  findings: "ממצאים",
  comments: "הערות רפרנטים",
  cad_layers: "שכבות CAD",
};

const TAB_ORDER: TabKey[] = ["overview", "submissions", "attachments", "findings", "comments", "cad_layers"];

export function ProjectWorkspace({ projectId, navigate, onProjectChanged }: Props) {
  const [project, setProject] = useState<ProjectOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("overview");

  // Findings tab state (loads latest complete submission's findings)
  const [findings, setFindings] = useState<unknown | null>(null);
  const [findingsErr, setFindingsErr] = useState<string | null>(null);
  const [latestCompleteSub, setLatestCompleteSub] = useState<SubmissionOut | null>(null);
  // Targeted PDF page - set by FindingsView when user clicks a row / page pill.
  // Wrapped in {page, nonce} so clicking the SAME page twice still triggers a
  // re-jump (useful when the user scrolled away and wants to come back).
  const [pdfTarget, setPdfTarget] = useState<{ page: number; nonce: number } | null>(null);
  const jumpToPdfPage = (page: number) =>
    setPdfTarget((prev) => ({ page, nonce: (prev?.nonce ?? 0) + 1 }));

  function refresh() {
    // Clear stale error so a startup-race TypeError doesn't linger next
    // to the successful retry's data (see api.ts fetchOrThrow + Task #14).
    getProject(projectId)
      .then((p) => { setErr(null); setProject(p); })
      .catch((e) => setErr(String(e)));
  }

  useEffect(() => { refresh(); setTab("overview"); setFindings(null); setLatestCompleteSub(null); /* eslint-disable-next-line */ }, [projectId]);

  // Lazy-load findings when the user switches to the Findings or Comments
  // tab. Comments tab only needs latestCompleteSub (not the findings JSON).
  useEffect(() => {
    if (!project) return;
    if (tab !== "findings" && tab !== "comments") return;
    if (tab === "findings") {
      setFindings(null);
      setFindingsErr(null);
    }
    setLatestCompleteSub(null);
    listSubmissions(project.id)
      .then((subs) => {
        // Comments tab: pick the newest submission that has analyzed
        // data on disk, regardless of stuck status labels. Findings tab
        // keeps the stricter rule - needs the engine's "complete"
        // verdict before showing the structured findings UI.
        const picked = tab === "comments"
          ? subs.find((s) => s.has_audit_results)
          : subs.find((s) => s.status === "complete");
        if (!picked) return;
        setLatestCompleteSub(picked);
        if (tab === "findings") return getFindings(picked.id);
      })
      .then((data) => { if (tab === "findings" && data !== undefined) setFindings(data); })
      .catch((e) => setFindingsErr(String(e)));
  }, [tab, project]);

  async function onArchive() {
    if (!project) return;
    if (!window.confirm(`האם להעביר את "${project.name_he}" לארכיון?`)) return;
    try {
      await archiveProject(project.id);
      onProjectChanged();
      navigate({ kind: "home" });
    } catch (e) {
      setErr(String(e));
    }
  }

  if (err) return <ErrorNotice error={err} title="לא ניתן לטעון את הפרויקט" />;
  if (!project) return <div className="muted">טוענת...</div>;

  return (
    <article className="page-project">
      <header className="page-header project-header">
        <div>
          <a className="back-link" href={buildHash({ kind: "home" })}>← חזרי</a>
          <h1>{project.name_he}</h1>
          <div className="project-meta">
            <span><strong>תב"ע:</strong> <span dir="ltr">{project.tava_number}</span></span>
            {project.address && <span><strong>כתובת:</strong> {project.address}</span>}
            {project.name_en && <span dir="ltr"><strong>EN:</strong> {project.name_en}</span>}
          </div>
        </div>
        <div className="project-actions">
          {project.status !== "archived" && (
            <button className="ghost-btn danger" onClick={onArchive}>
              העבירי לארכיון
            </button>
          )}
        </div>
      </header>

      <nav className="tabs">
        {TAB_ORDER.map((t) => (
          <button
            key={t}
            className={"tab" + (t === tab ? " active" : "")}
            data-testid={`tab-${t}`}
            onClick={() => setTab(t)}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </nav>

      <section className="tab-content">
        {tab === "overview" && <OverviewTab project={project} onSaved={setProject} />}
        {tab === "submissions" && (
          <SubmissionsTab
            project={project}
            onSubmissionsChanged={() => { refresh(); onProjectChanged(); }}
          />
        )}
        {tab === "attachments" && <AttachmentsTab project={project} />}
        {tab === "findings" && (
          <FindingsTabContent
            project={project}
            findings={findings}
            err={findingsErr}
            sub={latestCompleteSub}
            pdfTarget={pdfTarget}
            onJumpToPdfPage={jumpToPdfPage}
          />
        )}
        {tab === "comments" && (
          <CommentsTab project={project} submission={latestCompleteSub} />
        )}
        {tab === "cad_layers" && (
          <LayerMappingTab project={project} />
        )}
      </section>
      <DebugOverlay findings={findings} />
    </article>
  );
}

const PROJECT_STATUS_HE: Record<string, string> = {
  active: "פעיל",
  awaiting_review: "ממתין לבדיקה",
  signed: "חתום",
  archived: "בארכיון",
};

const SUBMISSION_STATUS_HE: Record<string, string> = {
  uploaded: "הועלה",
  extracting: "מבצע חילוץ",
  analyzing: "בבדיקה",
  complete: "הושלם",
  failed: "נכשל",
};

function OverviewTab({ project, onSaved }: { project: ProjectOut; onSaved: (p: ProjectOut) => void }) {
  const since = project.tava_approval_date ? timeSince(project.tava_approval_date) : null;
  return (
    <div className="card overview-card">
      <dl className="kv">
        <dt>שם הפרויקט</dt><dd>{project.name_he}</dd>
        {project.name_en && <><dt>שם באנגלית</dt><dd dir="ltr">{project.name_en}</dd></>}
        <dt>מספר תב"ע</dt><dd dir="ltr">{project.tava_number}</dd>
        <dt>כתובת</dt><dd>{project.address ?? "-"}</dd>
        <dt>משרד האדריכלים</dt>
        <dd><ArchitectField project={project} onSaved={onSaved} /></dd>
        <dt>זמן מאז אישור התב"ע</dt>
        <dd data-testid="overview-tava-age">
          {project.tava_approval_date && since ? (
            <>
              {since}
              <span className="muted"> (אושרה ב-<span dir="ltr">{displayDate(project.tava_approval_date)}</span>)</span>
            </>
          ) : (
            <span className="warn">תאריך אישור חסר</span>
          )}
        </dd>
        <dt>סטטוס</dt><dd>{PROJECT_STATUS_HE[project.status] ?? project.status}</dd>
        <dt>נוצר</dt><dd>{project.created_at.replace("T", " ").slice(0, 16)}</dd>
        <dt>בדיקה אוטומטית</dt>
        <dd>
          {project.has_schema ? (
            <span className="ok">זמינה - נתוני התב"ע טעונים במערכת</span>
          ) : (
            <span className="warn">לא זמינה - נתוני התב"ע טרם נטענו לפרויקט זה</span>
          )}
        </dd>
        <dt>מספר הגשות</dt><dd>{project.submission_count ?? 0}</dd>
        <dt>הגשה אחרונה</dt>
        <dd>
          {project.latest_submission ? (
            <>
              <span dir="ltr">{project.latest_submission.version_string}</span>
              {" · "}
              {SUBMISSION_STATUS_HE[project.latest_submission.status] ?? project.latest_submission.status}
              {" · "}
              <span className="muted">{project.latest_submission.uploaded_at.replace("T", " ").slice(0, 16)}</span>
            </>
          ) : "אין"}
        </dd>
      </dl>
    </div>
  );
}

// The firm is read by Ellen, not from the file: on the real submission it
// appears only as a logo on the cover, never as text (checked on all 63 pages).
function ArchitectField({ project, onSaved }: { project: ProjectOut; onSaved: (p: ProjectOut) => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(project.design_architect ?? "");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      onSaved(await patchProject(project.id, { design_architect: value.trim() || null }));
      setEditing(false);
    } catch {
      setErr("השמירה לא הצליחה. נסי שוב.");
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <span className="architect-field">
        <span data-testid="overview-architect">
          {project.design_architect ?? <span className="muted">לא זוהה</span>}
        </span>
        {" "}
        <button type="button" className="ghost-btn small" data-testid="overview-architect-edit"
                onClick={() => { setValue(project.design_architect ?? ""); setEditing(true); }}>
          {project.design_architect ? "עריכה" : "הוסיפי"}
        </button>
      </span>
    );
  }
  return (
    <span className="architect-field">
      <input type="text" value={value} maxLength={255} autoFocus
             data-testid="overview-architect-input"
             placeholder="שם משרד האדריכלים"
             onChange={(e) => setValue(e.target.value)}
             onKeyDown={(e) => { if (e.key === "Enter") void save(); if (e.key === "Escape") setEditing(false); }} />
      {" "}
      <button type="button" className="primary-btn small" disabled={saving}
              data-testid="overview-architect-save" onClick={() => void save()}>
        {saving ? "שומרת..." : "שמירה"}
      </button>
      {" "}
      <button type="button" className="ghost-btn small" disabled={saving}
              onClick={() => setEditing(false)}>ביטול</button>
      {err && <span className="warn"> {err}</span>}
    </span>
  );
}

function FindingsTabContent({
  project,
  findings,
  err,
  sub,
  pdfTarget,
  onJumpToPdfPage,
}: {
  project: ProjectOut;
  findings: unknown | null;
  err: string | null;
  sub: SubmissionOut | null;
  pdfTarget: { page: number; nonce: number } | null;
  onJumpToPdfPage: (page: number) => void;
}) {
  // Round-1 item 6: "no findings yet" is a NORMAL state, not an error -
  // the seed (and any fresh upload) has no findings until an engine run.
  if (err && /HTTP 409/.test(err) && /no findings yet/.test(err)) {
    return (
      <div className="findings-empty-state" data-testid="findings-empty-state">
        <h3>עדיין אין ממצאים בגרסה זו</h3>
        <p>כדי לראות את ממצאי הבדיקה, יש להריץ תחילה את הבדיקה על ההגשה.</p>
        <ol>
          <li>עברי ללשונית "הגשות"</li>
          <li>מצאי את ההגשה</li>
          <li>לחצי על "הפעילי את התוכנה"</li>
          <li>חזרי לכאן כשהבדיקה תסתיים.</li>
        </ol>
      </div>
    );
  }
  if (err) return <ErrorNotice error={err} title="לא ניתן לטעון את הממצאים" />;
  if (findings === null && sub === null) {
    return (
      <div className="card">
        <p className="muted">
          עדיין אין הגשה שהתוכנה סיימה עבורה ניתוח. עברי לטאב "הגשות", העלי תכנית עיצוב,
          ולחצי על "הפעילי את התוכנה".
        </p>
      </div>
    );
  }
  if (findings === null) return <p className="muted">טוענת ממצאים...</p>;
  // Side-by-side: findings on visual RIGHT (start, ~55%), tasrit on the LEFT
  // (end, ~45%). Splitter position persisted per-project to localStorage.
  const pdfUrl = sub ? `${SIDECAR_BASE}/submissions/${sub.id}/pdf` : null;
  // Phase A3: when the plan PDF isn't on disk (the seeded pilot ships
  // without its 100MB source), skip the split view entirely - a slim
  // explanatory bar + the findings list at full width.
  const pdfAvailable = sub?.has_pdf !== false;
  if (sub && !pdfAvailable) {
    return (
      <div className="findings-tab-root">
        <p className="muted findings-meta">
          מציג ממצאים עבור גרסה <span dir="ltr">{sub.version_string}</span> של תכנית העיצוב.
        </p>
        <div className="pdf-unavailable-bar" data-testid="pdf-unavailable-bar">
          קובץ התכנית של הגשת הדוגמה אינו כלול בתוכנה. בהגשות חדשות שיועלו
          למערכת - התכנית תוצג כאן. ההערות והפקת הדו"ח פועלות כרגיל.
        </div>
        <FindingsView findings={findings} projectId={project.id} pdfAvailable={false} />
      </div>
    );
  }
  return (
    <div className="findings-tab-root">
      {sub && (
        <p className="muted findings-meta">
          מציג ממצאים עבור גרסה <span dir="ltr">{sub.version_string}</span> של תכנית העיצוב.
        </p>
      )}
      {sub && pdfUrl ? (
        <SplitPane
          storageKey={`splitter:project_${project.id}`}
          defaultStartFraction={0.55}
          minFraction={0.30}
          maxFraction={0.75}
        >
          <FindingsView findings={findings} onJumpToPage={onJumpToPdfPage} projectId={project.id} />
          <PdfViewer fileUrl={pdfUrl} target={pdfTarget} />
        </SplitPane>
      ) : (
        <FindingsView findings={findings} onJumpToPage={onJumpToPdfPage} projectId={project.id} />
      )}
    </div>
  );
}

