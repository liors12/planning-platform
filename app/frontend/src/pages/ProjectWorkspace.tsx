import { useEffect, useState } from "react";
import { archiveProject, getProject, getFindings, listSubmissions, type ProjectOut, type SubmissionOut } from "../api";
import { CommentsTab } from "../components/CommentsTab";
import { DebugOverlay } from "../components/DebugOverlay";
import { SubmissionsTab } from "../components/SubmissionsTab";
import { FindingsView } from "../components/FindingsView";
import { PdfViewer } from "../components/PdfViewer";
import { SplitPane } from "../components/SplitPane";
import { buildHash, type Route } from "../route";

const SIDECAR_BASE = "http://127.0.0.1:17321";

interface Props {
  projectId: number;
  navigate: (r: Route) => void;
  onProjectChanged: () => void;
}

type TabKey = "overview" | "submissions" | "findings" | "comments" | "guidelines" | "history" | "final";

const TAB_LABELS: Record<TabKey, string> = {
  overview: "סקירה",
  submissions: "הגשות",
  findings: "ממצאים",
  comments: "הערות רפרנטים",
  guidelines: "הנחיות",
  history: "היסטוריה",
  final: "חוות דעת",
};

const TAB_ORDER: TabKey[] = ["overview", "submissions", "findings", "comments", "guidelines", "history", "final"];

export function ProjectWorkspace({ projectId, navigate, onProjectChanged }: Props) {
  const [project, setProject] = useState<ProjectOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("overview");

  // Findings tab state (loads latest complete submission's findings)
  const [findings, setFindings] = useState<unknown | null>(null);
  const [findingsErr, setFindingsErr] = useState<string | null>(null);
  const [latestCompleteSub, setLatestCompleteSub] = useState<SubmissionOut | null>(null);
  // Targeted PDF page — set by FindingsView when user clicks a row / page pill.
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
        // keeps the stricter rule — needs the engine's "complete"
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

  if (err) return <div className="error error-block">{err}</div>;
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
            onClick={() => setTab(t)}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </nav>

      <section className="tab-content">
        {tab === "overview" && <OverviewTab project={project} />}
        {tab === "submissions" && (
          <SubmissionsTab
            project={project}
            onSubmissionsChanged={() => { refresh(); onProjectChanged(); }}
          />
        )}
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
        {tab === "guidelines" && <Placeholder badge="בקרוב" title="עורך הנחיות" desc="עריכת ערכי הסף של בדיקות התוכנה + יצירת גרסת מסמך דרישות מעודכן לאדריכל. יתווסף בעדכון הבא." />}
        {tab === "history" && <Placeholder badge="בקרוב" title="היסטוריה" desc="ציר זמן של כל הפעולות בפרויקט — יצירה, הגשות, ריצות בדיקה, עריכת הנחיות, החלטות מנהלי דיסציפלינה." />}
        {tab === "final" && <Placeholder badge="בקרוב" title="חוות דעת" desc="הפקת חוות הדעת הסופית עם שילוב משוב מנהלי הדיסציפלינות וחתימת מהנדס/ת המינהלת." />}
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

function OverviewTab({ project }: { project: ProjectOut }) {
  return (
    <div className="card overview-card">
      <dl className="kv">
        <dt>שם הפרויקט</dt><dd>{project.name_he}</dd>
        {project.name_en && <><dt>שם באנגלית</dt><dd dir="ltr">{project.name_en}</dd></>}
        <dt>מספר תב"ע</dt><dd dir="ltr">{project.tava_number}</dd>
        <dt>כתובת</dt><dd>{project.address ?? "—"}</dd>
        <dt>סטטוס</dt><dd>{PROJECT_STATUS_HE[project.status] ?? project.status}</dd>
        <dt>נוצר</dt><dd>{project.created_at.replace("T", " ").slice(0, 16)}</dd>
        <dt>סכמת בדיקה</dt>
        <dd>
          {project.has_schema ? (
            <span className="ok">קיימת — ניתן להריץ בדיקה אוטומטית</span>
          ) : (
            <span className="warn">חסרה — לא ניתן להריץ בדיקה אוטומטית. הוספת סכמות תהיה זמינה בעדכון הבא.</span>
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
  if (err) return <div className="error error-block">{err}</div>;
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

function Placeholder({ badge, title, desc }: { badge: string; title: string; desc: string }) {
  return (
    <div className="card placeholder-card">
      <span className="placeholder-phase">{badge}</span>
      <h3>{title}</h3>
      <p className="muted">{desc}</p>
    </div>
  );
}
