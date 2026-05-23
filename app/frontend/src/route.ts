// Tiny hash-based router. Phase 2a's needs are minimal (3 routes) so a full
// TanStack Router setup would be over-engineered.

import { useEffect, useState } from "react";

export type Route =
  | { kind: "home" }
  | { kind: "new_project" }
  | { kind: "project"; projectId: number };

export function parseHash(hash: string): Route {
  // Strip leading "#" and "/"
  const s = hash.replace(/^#\/?/, "");
  if (s === "" || s === "/") return { kind: "home" };
  if (s === "projects/new") return { kind: "new_project" };
  const m = /^projects\/(\d+)$/.exec(s);
  if (m) return { kind: "project", projectId: Number(m[1]) };
  return { kind: "home" };  // fallback for unknown
}

export function buildHash(route: Route): string {
  switch (route.kind) {
    case "home": return "#/";
    case "new_project": return "#/projects/new";
    case "project": return `#/projects/${route.projectId}`;
  }
}

export function useRoute(): [Route, (r: Route) => void] {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  function navigate(r: Route) {
    const h = buildHash(r);
    if (window.location.hash !== h) {
      window.location.hash = h;
    } else {
      // Force update even on same-hash navigation (e.g., re-creating same project).
      setRoute(r);
    }
  }
  return [route, navigate];
}
