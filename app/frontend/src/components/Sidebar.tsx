import { useEffect, useState } from "react";
import { listProjects, type ProjectOut, type ProjectStatus } from "../api";
import { buildHash, type Route } from "../route";

interface Props {
  currentRoute: Route;
  refreshKey: number;        // bump to force a re-fetch (after create / archive)
}

const STATUS_LABEL_HE: Record<ProjectStatus, string> = {
  active: "פעילים",
  awaiting_review: "ממתינים לבדיקה",
  signed: "חתומים",
  archived: "בארכיון",
};

const STATUS_ORDER: ProjectStatus[] = ["active", "awaiting_review", "signed", "archived"];

export function Sidebar({ currentRoute, refreshKey }: Props) {
  const [projects, setProjects] = useState<ProjectOut[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);

  useEffect(() => {
    // Clear any stale error from a previous failed attempt — otherwise a
    // startup-race TypeError on the first fetch would linger next to the
    // successful retry's data (see api.ts fetchOrThrow + Task #14).
    listProjects(showArchived)
      .then((p) => { setErr(null); setProjects(p); })
      .catch((e) => setErr(String(e)));
  }, [refreshKey, showArchived]);

  const grouped = STATUS_ORDER.map((s) => ({
    status: s,
    projects: projects.filter((p) => p.status === s),
  })).filter((g) => g.projects.length > 0);

  const activeProjectId =
    currentRoute.kind === "project" ? currentRoute.projectId : null;

  return (
    <aside className="sidebar">
      <header className="sidebar-header">
        <a className="brand-link" href={buildHash({ kind: "home" })}>
          <div className="brand-eyebrow">מינהלת ההתחדשות העירונית</div>
          <div className="brand-title">נס ציונה</div>
        </a>
        <a
          className="primary-btn new-project-btn"
          href={buildHash({ kind: "new_project" })}
        >
          + פרויקט חדש
        </a>
      </header>

      {err && <div className="error">{err}</div>}

      {grouped.length === 0 && !err && (
        <p className="muted sidebar-empty">אין פרויקטים עדיין.</p>
      )}

      {grouped.map((g) => (
        <section key={g.status} className="sidebar-group">
          <h3 className="sidebar-group-title">{STATUS_LABEL_HE[g.status]}</h3>
          <ul className="sidebar-list">
            {g.projects.map((p) => (
              <li
                key={p.id}
                className={
                  "sidebar-item" + (p.id === activeProjectId ? " active" : "")
                }
              >
                <a href={buildHash({ kind: "project", projectId: p.id })}>
                  <div className="sidebar-item-name">{p.name_he}</div>
                  <div className="sidebar-item-meta">
                    <span dir="ltr">{p.tava_number}</span>
                    {p.submission_count !== null && p.submission_count > 0 && (
                      <span className="sidebar-item-count">
                        {p.submission_count === 1
                          ? "הגשה אחת"
                          : `${p.submission_count} הגשות`}
                      </span>
                    )}
                  </div>
                </a>
              </li>
            ))}
          </ul>
        </section>
      ))}

      <footer className="sidebar-footer">
        <label className="archived-toggle">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
          />
          הצג פרויקטים בארכיון
        </label>
      </footer>
    </aside>
  );
}
