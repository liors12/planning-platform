import { useEffect, useState } from "react";

interface Props {
  findings: unknown;
  /** Parent supplies this to wire row-click → PDF page jump. */
  onJumpToPage?: (pageNumber: number) => void;
  /** Used to scope the localStorage filter persistence key. */
  projectId: number;
}

// ── Filter taxonomy (Step 8) ──────────────────────────────────────────
// Each section gets its own toggle map keyed by verdict. Defaults below
// reflect the engineer's typical workflow: problem-shaped verdicts are
// ON by default so they're visible immediately; passing/N/A verdicts
// are OFF so they don't clutter the queue. Counts stay visible for OFF
// pills so the user can see what they're hiding.
type SectionKey = "format" | "content" | "disciplines";
type Verdict =
  | "pass" | "pass_with_note"
  | "fail" | "fail_borderline"
  | "not_submitted" | "requires_review"
  | "unevaluable" | "not_applicable";
type SectionFilter = Record<Verdict, boolean>;
type AllFilters = Record<SectionKey, SectionFilter>;

const DEFAULT_FILTER: SectionFilter = {
  // ON by default — problem-shaped + pass_with_note (these all need attention)
  fail: true,
  fail_borderline: true,
  not_submitted: true,
  requires_review: true,
  pass_with_note: true,
  // OFF by default — passing / not-applicable / unevaluable
  pass: false,
  not_applicable: false,
  unevaluable: false,
};

const DEFAULT_FILTERS: AllFilters = {
  format: { ...DEFAULT_FILTER },
  content: { ...DEFAULT_FILTER },
  disciplines: { ...DEFAULT_FILTER },
};

function filterStorageKey(projectId: number): string {
  return `filters:project_${projectId}`;
}

// Defensive load — if anything looks off (parse error, missing key,
// shape drift after a future schema change), fall back to defaults
// rather than blowing up the Findings tab for the user.
function loadFilters(projectId: number): AllFilters {
  try {
    const raw = localStorage.getItem(filterStorageKey(projectId));
    if (!raw) return structuredClone(DEFAULT_FILTERS);
    const parsed = JSON.parse(raw);
    const out: AllFilters = structuredClone(DEFAULT_FILTERS);
    for (const sec of ["format", "content", "disciplines"] as SectionKey[]) {
      if (parsed?.[sec] && typeof parsed[sec] === "object") {
        for (const v of Object.keys(DEFAULT_FILTER) as Verdict[]) {
          if (typeof parsed[sec][v] === "boolean") {
            out[sec][v] = parsed[sec][v];
          }
        }
      }
    }
    return out;
  } catch {
    return structuredClone(DEFAULT_FILTERS);
  }
}

function saveFilters(projectId: number, f: AllFilters) {
  try { localStorage.setItem(filterStorageKey(projectId), JSON.stringify(f)); }
  catch { /* localStorage full / disabled — silently degrade */ }
}

// ── Verdict taxonomy (Hebrew labels + CSS class) ──────────────────────
// Mirrors compliance_engine/report_generator.py VERDICT_TO_VCLASS_AND_LABEL,
// minus the dev-facing internals. See docs/architecture/engine_output_contract.md.
const VERDICT_LABEL_HE: Record<string, string> = {
  pass: "תקין",
  pass_with_note: "תקין בהערה",
  fail: "נדרש תיקון",
  fail_borderline: "נדרש תיקון",
  not_submitted: "לא הוגש",
  requires_review: "דורש בירור",
  unevaluable: "לא ניתן לבדיקה",
  not_applicable: "לא רלוונטי",
};

const VERDICT_CLASS: Record<string, string> = {
  pass: "v-ok",
  pass_with_note: "v-ok",
  fail: "v-fail",
  fail_borderline: "v-fail",
  not_submitted: "v-fail",
  requires_review: "v-review",
  unevaluable: "v-unknown",
  not_applicable: "v-na",
};

interface Rule {
  rule_code: string;
  rule_name_he?: string;
  verdict: string;
  notes_he?: string;
  remediation_he?: string;
  evidence_visual?: string;
  compliance_note?: string;
  evidence_pages?: number[];
  evidence?: { evidence_pages?: number[]; evidence_visual?: string; compliance_note?: string };
  ta_shetach_id?: string;
  discipline?: string;
  severity?: string;
}

const DISCIPLINE_LABEL_HE: Record<string, string> = {
  shafa: 'שפ"ע — אשפה ופינוי פסולת',
  gardens: "גנים ונוף",
  infra: "תשתיות",
  fire: "רחבות כיבוי",
  drainage: "ניקוז וחלחול",
  roofs: "גגות וחזית חמישית",
  arch: "אדריכלות וחזיתות",
  balcony: "מרפסות",
  laundry: "מסתורי כביסה",
  env: "הנחיות סביבתיות",
};

function pagesOf(r: Rule): number[] {
  return r.evidence_pages ?? r.evidence?.evidence_pages ?? [];
}

function visualOf(r: Rule): string {
  return (r.evidence_visual ?? r.evidence?.evidence_visual ?? "").trim();
}

function noteOf(r: Rule): string {
  return (r.compliance_note ?? r.evidence?.compliance_note ?? "").trim();
}

function countVerdicts(rules: Rule[]): Array<{ verdict: string; count: number }> {
  const map: Record<string, number> = {};
  for (const r of rules) map[r.verdict] = (map[r.verdict] ?? 0) + 1;
  // Stable order: failure-shaped first (most actionable), then review, then ok, then na/unknown.
  const order = ["fail", "fail_borderline", "not_submitted", "requires_review",
                 "pass", "pass_with_note", "unevaluable", "not_applicable"];
  return order
    .filter((v) => map[v])
    .map((v) => ({ verdict: v, count: map[v] }));
}

export function FindingsView({ findings, onJumpToPage, projectId }: Props) {
  const data: any = findings ?? {};
  const formatRules: Rule[] = Array.isArray(data.format) ? data.format : [];
  const contentRules: Rule[] = Array.isArray(data.content) ? data.content : [];
  const disciplineRules: Rule[] = Array.isArray(data.disciplines) ? data.disciplines : [];

  // Per-project, per-section verdict toggles. Re-loaded when projectId
  // changes (e.g. user switches projects). Writes are debounced through
  // React's normal render cadence — on each toggle we both update state
  // AND persist to localStorage so a reload restores the exact view.
  const [filters, setFilters] = useState<AllFilters>(() => loadFilters(projectId));
  useEffect(() => {
    setFilters(loadFilters(projectId));
  }, [projectId]);

  function toggle(section: SectionKey, verdict: Verdict) {
    setFilters((prev) => {
      const next: AllFilters = {
        ...prev,
        [section]: { ...prev[section], [verdict]: !prev[section][verdict] },
      };
      saveFilters(projectId, next);
      return next;
    });
  }

  const sections: Array<{ key: SectionKey; title: string; rules: Rule[] }> = [
    { key: "disciplines", title: "בדיקה רב-תחומית", rules: disciplineRules },
    { key: "content",     title: 'תאימות תוכן לתב"ע', rules: contentRules },
    { key: "format",      title: "תאימות פורמט", rules: formatRules },
  ];

  return (
    <div className="findings-list">
      {sections.map((sec) => (
        <FindingsSection
          key={sec.key}
          sectionKey={sec.key}
          title={sec.title}
          rules={sec.rules}
          enabled={filters[sec.key]}
          onToggleVerdict={(v) => toggle(sec.key, v)}
          onJumpToPage={onJumpToPage}
        />
      ))}
    </div>
  );
}

function FindingsSection({
  sectionKey, title, rules, enabled, onToggleVerdict, onJumpToPage,
}: {
  sectionKey: SectionKey;
  title: string;
  rules: Rule[];
  enabled: SectionFilter;
  onToggleVerdict: (v: Verdict) => void;
  onJumpToPage?: (n: number) => void;
}) {
  // Counts always reflect ALL rules in the section, regardless of which
  // filters are on — the count beside each pill is what the user is
  // showing/hiding, not just what's currently visible.
  const counts = countVerdicts(rules);
  const [collapsed, setCollapsed] = useState(false);
  // Apply filters: keep only rules whose verdict is currently enabled.
  const visibleRules = rules.filter((r) => enabled[r.verdict as Verdict]);
  // Three distinct empty cases (engine vs filter vs collapsed) — the
  // UX message differs.
  const noRulesAtAll = rules.length === 0;
  const allFiltered = !noRulesAtAll && visibleRules.length === 0;

  return (
    <section className="findings-section" data-section={sectionKey}>
      <header className="findings-section-header"
              onClick={() => setCollapsed((c) => !c)}
              role="button"
              aria-expanded={!collapsed}>
        <span className="section-chevron">{collapsed ? "›" : "⌄"}</span>
        <h3 className="findings-section-title">{title}</h3>
        <span className="findings-section-total">{rules.length} סעיפים</span>
        <span className="findings-section-counts">
          {counts.map(({ verdict, count }) => {
            const v = verdict as Verdict;
            const on = enabled[v];
            return (
              <button
                key={verdict}
                type="button"
                className={
                  "verdict-pill verdict-pill-toggle " +
                  (VERDICT_CLASS[verdict] ?? "v-na") +
                  (on ? " is-on" : " is-off")
                }
                aria-pressed={on}
                data-verdict={verdict}
                title={(on ? "סנן החוצה: " : "הצג: ") + (VERDICT_LABEL_HE[verdict] ?? verdict)}
                onClick={(e) => {
                  // Critical: pill click must NOT bubble to the header
                  // which toggles collapse.
                  e.stopPropagation();
                  onToggleVerdict(v);
                }}
              >
                <span className="verdict-count">{count}</span>
                {VERDICT_LABEL_HE[verdict] ?? verdict}
              </button>
            );
          })}
        </span>
      </header>
      {!collapsed && (
        <ul className="findings-rows">
          {noRulesAtAll && <li className="muted findings-empty">אין סעיפים</li>}
          {allFiltered && (
            <li className="muted findings-empty findings-empty-filtered">
              אין סעיפים להצגה. הפעל מסננים בכותרת.
            </li>
          )}
          {/*
            Composite React key — `${rule_code}::${ta_shetach_id ?? idx}`.

            Why: 7 content rules (CONTENT_UNIT_COUNT, CONTENT_BUILDING_
            AREA_MAIN/SERVICE_ABOVE/SERVICE_BELOW, CONTENT_BUILDING_
            HEIGHT, CONTENT_PARKING_RATIO, CONTENT_SETBACKS) and a
            handful of discipline rules have `scope: "per_ta_shetach"`
            in content_rules.json. The engine emits one result PER PLOT
            for each such rule, all sharing the same `rule_code` but
            distinguished by `ta_shetach_id` ("plot_1", "plot_2", …).
            Keying React rows by `rule_code` alone collides (the
            "Encountered two children with the same key" warning) and
            lets React drop/duplicate row identity across re-renders —
            drawer state can flicker, page-pill highlights can stick to
            the wrong row.

            The composite matches React semantics to the engine
            contract: each emitted result is its own row identity. The
            `?? idx` fallback covers rules that aren't per-plot (where
            rule_code is already unique within the section).

            Invariant: `rule_code` MUST NOT contain "::" — see
            docs/architecture/engine_output_contract.md §"rule_code
            invariants". If that ever changes, the separator here has
            to change too.
          */}
          {visibleRules.map((r, idx) => (
            <FindingRow
              key={`${r.rule_code}::${r.ta_shetach_id ?? idx}`}
              rule={r}
              onJumpToPage={onJumpToPage}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function FindingRow({
  rule, onJumpToPage,
}: { rule: Rule; onJumpToPage?: (n: number) => void }) {
  const [expanded, setExpanded] = useState(false);
  const pages = pagesOf(rule);
  const visual = visualOf(rule);
  const note = noteOf(rule);
  const verdictClass = VERDICT_CLASS[rule.verdict] ?? "v-na";
  const verdictLabel = VERDICT_LABEL_HE[rule.verdict] ?? rule.verdict;
  const briefNote = (rule.notes_he ?? "").trim();

  // Brief evidence shown collapsed: prefer the engine's notes_he (which the
  // engine already crafted as the one-line summary), fall back to compliance_note.
  const brief = briefNote || note || visual;

  function onRowClick(e: React.MouseEvent) {
    // Ignore clicks on interactive children (page pills, expand button).
    const t = e.target as HTMLElement;
    if (t.closest(".page-pill") || t.closest(".row-expand-btn")) return;
    if (pages.length > 0 && onJumpToPage) {
      onJumpToPage(pages[0]);
    } else {
      setExpanded((x) => !x);
    }
  }

  const discTag = rule.discipline ? DISCIPLINE_LABEL_HE[rule.discipline] : null;
  const plotTag = rule.ta_shetach_id ? rule.ta_shetach_id.replace("plot_", "תא ") : null;
  // Defensive fallback if rule_name_he is missing from the engine (shouldn't
  // happen since we backfilled the engine to populate it for all sections,
  // but never expose the raw rule_code in user-facing UI).
  const displayName = (rule.rule_name_he ?? "").trim() || "סעיף ללא שם";

  return (
    <li className={"finding-row" + (expanded ? " expanded" : "")} onClick={onRowClick}>
      <div className="finding-row-main">
        <span className={"verdict-badge " + verdictClass}>{verdictLabel}</span>
        <div className="finding-row-body">
          <div className="finding-row-title">
            <span className="finding-row-name">{displayName}</span>
            {plotTag && <span className="finding-tag">{plotTag}</span>}
            {discTag && <span className="finding-tag finding-tag-discipline">{discTag}</span>}
          </div>
          {brief && <div className="finding-row-brief">{brief}</div>}
          {pages.length > 0 && (
            <div className="page-pills">
              {pages.slice(0, 6).map((p) => (
                <button
                  key={p}
                  className="page-pill"
                  onClick={(e) => { e.stopPropagation(); onJumpToPage?.(p); }}
                  title={`קפוץ לעמוד ${p}`}
                >
                  עמ' {p}
                </button>
              ))}
              {pages.length > 6 && (
                <span className="page-pill-more">+{pages.length - 6}</span>
              )}
            </div>
          )}
        </div>
        <button
          className="row-expand-btn"
          onClick={(e) => { e.stopPropagation(); setExpanded((x) => !x); }}
          aria-label={expanded ? "סגור פרטים" : "פתח פרטים"}
          aria-expanded={expanded}
        >
          {expanded ? "⌄" : "›"}
        </button>
      </div>
      {expanded && (
        <div className="finding-row-drawer">
          {visual && (
            <div className="drawer-block">
              <div className="drawer-label">תיאור ויזואלי מההגשה</div>
              <div className="drawer-body">{visual}</div>
            </div>
          )}
          {note && note !== brief && (
            <div className="drawer-block">
              <div className="drawer-label">הערת המנוע</div>
              <div className="drawer-body">{note}</div>
            </div>
          )}
          {rule.remediation_he && (
            <div className="drawer-block">
              <div className="drawer-label">פעולה נדרשת</div>
              <div className="drawer-body">{rule.remediation_he}</div>
            </div>
          )}
          {pages.length > 0 && (
            <div className="drawer-block">
              <div className="drawer-label">הפניות לעמודים בהגשה</div>
              <div className="drawer-body drawer-pages">
                {pages.map((p) => (
                  <button
                    key={p}
                    className="page-pill"
                    onClick={(e) => { e.stopPropagation(); onJumpToPage?.(p); }}
                  >
                    עמ' {p}
                  </button>
                ))}
              </div>
            </div>
          )}
          {pages.length === 0 && (
            <div className="drawer-block">
              <div className="muted">אין הפניית עמוד לסעיף זה.</div>
            </div>
          )}
        </div>
      )}
    </li>
  );
}
