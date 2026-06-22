import { useEffect, useState } from "react";
import { getHealth, isSidecarUnreachable, listProjects, type ProjectOut, type WorkflowStage } from "./api";
import { DiagnosticsPanel } from "./components/DiagnosticsPanel";
import { Sidebar } from "./components/Sidebar";
import { CreateProject } from "./pages/CreateProject";
import { ProjectWorkspace } from "./pages/ProjectWorkspace";
import { Settings } from "./pages/Settings";
import { buildHash, useRoute } from "./route";

export default function App() {
  const [route, navigate] = useRoute();
  const [refreshKey, setRefreshKey] = useState(0);
  const [diagOpen, setDiagOpen] = useState(false);

  function bumpRefresh() { setRefreshKey((k) => k + 1); }

  return (
    <div className="app-shell">
      <Sidebar
        currentRoute={route}
        refreshKey={refreshKey}
        onOpenDiagnostics={() => setDiagOpen(true)}
      />
      {diagOpen && <DiagnosticsPanel onClose={() => setDiagOpen(false)} />}

      <main className="content">
        {route.kind === "home" && (
          <Home refreshKey={refreshKey} onOpenDiagnostics={() => setDiagOpen(true)} />
        )}
        {route.kind === "new_project" && (
          <CreateProject navigate={navigate} onCreated={bumpRefresh} />
        )}
        {route.kind === "project" && (
          <ProjectWorkspace
            key={route.projectId}      // re-mount on project switch
            projectId={route.projectId}
            navigate={navigate}
            onProjectChanged={bumpRefresh}
          />
        )}
        {route.kind === "settings" && <Settings />}
      </main>
    </div>
  );
}

const STAGE_LABEL_HE: Record<WorkflowStage, string> = {
  draft:             "הוכנה",
  sent:              "נשלח לאדריכל",
  response_received: "התקבלה תשובה",
  verified:          "נסגר",
};

const PIPELINE_STAGES: WorkflowStage[] = ["draft", "sent", "response_received", "verified"];

function Home({ refreshKey, onOpenDiagnostics }: { refreshKey: number; onOpenDiagnostics: () => void }) {
  const [projects, setProjects] = useState<ProjectOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [healthOk, setHealthOk] = useState(false);

  useEffect(() => {
    listProjects(false)
      .then((all) => { setErr(null); setUnreachable(false); setProjects(all); })
      .catch((e) => {
        if (isSidecarUnreachable(e)) {
          setUnreachable(true);
          setErr(null);
        } else {
          setUnreachable(false);
          setErr(String(e));
        }
      });
    getHealth()
      .then(() => setHealthOk(true))
      .catch(() => {});
  }, [refreshKey]);

  const active = projects?.filter((p) => p.status !== "archived") ?? [];
  const recent = active.slice(0, 5);
  const appReady = healthOk && projects !== null && projects.length > 0;

  // Count active projects by their latest submission's workflow_stage.
  const stageCounts: Record<WorkflowStage, number> = {
    draft: 0, sent: 0, response_received: 0, verified: 0,
  };
  for (const p of active) {
    const s = p.latest_submission?.workflow_stage;
    if (s && s in stageCounts) stageCounts[s]++;
  }
  const hasAny = active.some((p) => p.latest_submission);

  return (
    <article className="page-home">
      <header className="page-header home-header">
        <div className="home-eyebrow">מינהלת ההתחדשות העירונית · עיריית נס ציונה</div>
        <h1 className="home-title">בקרת תכניות עיצוב</h1>
        <p className="home-tagline">
          סקירה אוטומטית של תכניות עיצוב מול תב"ע מאושרת וחוברת ההנחיות העירונית,
          לקראת חוות דעת מהנדס/ת הוועדה המקומית.
        </p>
      </header>

      {/* ── Pipeline summary (C2) ─────────────────────────────────────── */}
      {hasAny && (
        <section className="pipeline-summary" aria-label="סיכום שלבי הגשה">
          {PIPELINE_STAGES.map((stage) => (
            <div key={stage} className={`pipeline-card ps-${stage}`}>
              <span className="ps-count">{stageCounts[stage]}</span>
              <span className="ps-label">{STAGE_LABEL_HE[stage]}</span>
            </div>
          ))}
        </section>
      )}

      <p className="home-cta-hint muted">
        בחרי פרויקט קיים מהסרגל בצד, או צרי פרויקט חדש בעזרת הכפתור
        "+ פרויקט חדש" בראש הסרגל.
      </p>

      <section className="card home-recent">
        <h2 className="card-title">פרויקטים אחרונים</h2>
        {unreachable && (
          <div className="error error-block">
            לא ניתן להתחבר לשרת הרקע. בדקי את{" "}
            <button className="error-inline-link" type="button" onClick={onOpenDiagnostics}>
              לוח האבחון
            </button>{" "}
            בתחתית המסך.
          </div>
        )}
        {err && <div className="error">{err}</div>}
        {!projects && !err && !unreachable && <p className="muted">טוענת...</p>}
        {projects && recent.length === 0 && (
          <p className="muted">אין עדיין פרויקטים. פתחי פרויקט ראשון כדי להתחיל.</p>
        )}
        {recent.length > 0 && (
          <ul className="home-recent-list" data-testid={appReady ? "app-ready" : undefined}>
            {recent.map((p) => {
              const ws = p.latest_submission?.workflow_stage;
              return (
                <li key={p.id}>
                  <a className="home-recent-link"
                     data-testid={`home-project-link-${p.tava_number}`}
                     href={buildHash({ kind: "project", projectId: p.id })}>
                    <div className="home-recent-name">{p.name_he}</div>
                    <div className="home-recent-meta">
                      <span dir="ltr">תב"ע {p.tava_number}</span>
                      {p.submission_count !== null && p.submission_count > 0 && (
                        <span>
                          {" · "}
                          {p.submission_count === 1
                            ? "הגשה אחת"
                            : `${p.submission_count} הגשות`}
                        </span>
                      )}
                      {p.latest_submission && (
                        <span>
                          {" · "}עודכן{" "}
                          {p.latest_submission.uploaded_at.replace("T", " ").slice(0, 10)}
                        </span>
                      )}
                    </div>
                  </a>
                  {ws && (
                    <span className={`stage-pill sp-${ws}`}>
                      {STAGE_LABEL_HE[ws]}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </article>
  );
}
