import { useEffect, useState } from "react";
import { getHealth, isSidecarUnreachable, listProjects, type ProjectOut } from "./api";
import { DiagnosticsPanel } from "./components/DiagnosticsPanel";
import { Sidebar } from "./components/Sidebar";
import { CreateProject } from "./pages/CreateProject";
import { ProjectWorkspace } from "./pages/ProjectWorkspace";
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
      </main>
    </div>
  );
}

function Home({ refreshKey, onOpenDiagnostics }: { refreshKey: number; onOpenDiagnostics: () => void }) {
  const [recent, setRecent] = useState<ProjectOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  // P1 — deterministic app-ready handshake for the UI smoke gate.
  // The harness waits on data-testid="app-ready" before any click,
  // so the marker must reflect that the app has finished its initial
  // render (not just that an HTTP fetch returned 200). Today's race
  // — "project loaded but submission didn't" — happened because the
  // test clicked before React had painted the seeded data, hitting a
  // backend that wasn't fully ready and a UI that hadn't reconciled.
  //
  // The marker fires only when BOTH conditions hold:
  //   1. /health returned 200 (sidecar fully bound, not just listening)
  //   2. the project list has both loaded AND has at least one row
  //      (proves the seeded pilot is rendered on screen)
  // Each is necessary: /health 200 alone doesn't guarantee /projects
  // is reconciled; recent.length > 0 alone doesn't guarantee /health
  // (the recent fetch could have hit a stale-but-listening sidecar).
  const [healthOk, setHealthOk] = useState(false);

  useEffect(() => {
    // Clear stale error so a startup-race TypeError doesn't linger next
    // to the successful retry's data (see api.ts fetchOrThrow + Task #14).
    listProjects(false)
      .then((all) => { setErr(null); setUnreachable(false); setRecent(all.slice(0, 5)); })
      .catch((e) => {
        if (isSidecarUnreachable(e)) {
          setUnreachable(true);
          setErr(null);
        } else {
          setUnreachable(false);
          setErr(String(e));
        }
      });
    // Parallel /health probe — independent of /projects so a slow
    // project-list query doesn't delay readiness, and a /health blip
    // doesn't hide already-rendered data. Failures here are silent:
    // the existing unreachable/err surfaces handle the "no sidecar"
    // case via listProjects.
    getHealth()
      .then(() => setHealthOk(true))
      .catch(() => { /* listProjects path handles the user-facing error */ });
  }, [refreshKey]);

  const appReady = healthOk && recent !== null && recent.length > 0;

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
        {!recent && !err && !unreachable && <p className="muted">טוענת...</p>}
        {recent && recent.length === 0 && (
          <p className="muted">אין עדיין פרויקטים. פתחי פרויקט ראשון כדי להתחיל.</p>
        )}
        {recent && recent.length > 0 && (
          <ul className="home-recent-list" data-testid={appReady ? "app-ready" : undefined}>
            {recent.map((p) => (
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
              </li>
            ))}
          </ul>
        )}
      </section>
    </article>
  );
}
