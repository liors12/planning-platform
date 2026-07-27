import { useEffect, useState } from "react";

interface Props {
  findings: unknown;
  /** Parent supplies this to wire row-click → PDF page jump. */
  onJumpToPage?: (pageNumber: number) => void;
  /** Used to scope the localStorage filter persistence key. */
  projectId: number;
  /** When false (seeded pilot without its plan file), page references
   * render as plain text instead of jump buttons. */
  pdfAvailable?: boolean;
}

// ── Filter taxonomy (Phase A) ─────────────────────────────────────────
// ONE global filter bar for the whole tab (the per-section chip-click
// filtering was invisible as an affordance). Default view shows only the
// actionable statuses; a toggle reveals everything. Session-scoped
// persistence (module variable) - a fresh app start returns to the
// actionable-first default.
type SectionKey = "format" | "content" | "disciplines";
type Verdict =
  | "pass" | "pass_with_note"
  | "fail" | "fail_borderline"
  | "not_submitted" | "requires_review"
  | "unevaluable" | "not_applicable" | "manual_review";

// Statuses that need Ellen's attention - the default view.
const ACTIONABLE: Verdict[] = ["fail", "fail_borderline", "requires_review",
  "manual_review", "not_submitted"];

// Filter-bar pills: one per user-facing status label (fail and
// fail_borderline share the "נדרש תיקון" label, so one pill drives both).
const FILTER_PILLS: Array<{ label: string; verdicts: Verdict[] }> = [
  { label: "נדרש תיקון", verdicts: ["fail", "fail_borderline"] },
  { label: "נדרשת השלמה", verdicts: ["requires_review"] },
  { label: "נדרשת בדיקה ידנית", verdicts: ["manual_review"] },
  { label: "לא הוגש", verdicts: ["not_submitted"] },
  { label: "תקין", verdicts: ["pass"] },
  { label: "תקין בהערה", verdicts: ["pass_with_note"] },
  { label: "לא ניתן לבדיקה", verdicts: ["unevaluable"] },
  { label: "לא רלוונטי", verdicts: ["not_applicable"] },
];

// Session (in-memory) persistence for the toggle + filters.
let sessionShowAll = false;
let sessionActivePills: string[] | null = null;

// ── Verdict taxonomy (Hebrew labels + CSS class) ──────────────────────
// Mirrors compliance_engine/report_generator.py VERDICT_TO_VCLASS_AND_LABEL,
// minus the dev-facing internals. See docs/architecture/engine_output_contract.md.
const VERDICT_LABEL_HE: Record<string, string> = {
  pass: "תקין",
  pass_with_note: "תקין בהערה",
  fail: "נדרש תיקון",
  fail_borderline: "נדרש תיקון",
  not_submitted: "לא הוגש",
  requires_review: "נדרשת השלמה",
  manual_review: "נדרשת בדיקה ידנית",
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
  shafa: 'שפ"ע - אשפה ופינוי פסולת',
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

export function FindingsView({ findings, onJumpToPage, projectId, pdfAvailable = true }: Props) {
  void projectId;
  const data: any = findings ?? {};
  const formatRules: Rule[] = Array.isArray(data.format) ? data.format : [];
  const contentRules: Rule[] = Array.isArray(data.content) ? data.content : [];
  const disciplineRules: Rule[] = Array.isArray(data.disciplines) ? data.disciplines : [];

  // Phase A state: show-all toggle, explicit status pills, free-text search.
  const [showAll, setShowAll] = useState(sessionShowAll);
  const [activePills, setActivePills] = useState<string[]>(
    () => sessionActivePills ?? [],
  );
  const [searchRaw, setSearchRaw] = useState("");
  const [search, setSearch] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchRaw.trim()), 200);
    return () => clearTimeout(t);
  }, [searchRaw]);
  useEffect(() => { sessionShowAll = showAll; }, [showAll]);
  useEffect(() => { sessionActivePills = activePills; }, [activePills]);

  const allRules = [...disciplineRules, ...contentRules, ...formatRules];
  const actionableCount = allRules.filter((r) => ACTIONABLE.includes(r.verdict as Verdict)).length;

  // Effective visible verdicts: explicit pills win; otherwise the
  // actionable-first default (or everything when the toggle is on).
  const pillVerdicts = new Set(
    FILTER_PILLS.filter((p) => activePills.includes(p.label)).flatMap((p) => p.verdicts),
  );
  const visible = (r: Rule): boolean => {
    const v = r.verdict as Verdict;
    const statusOk = activePills.length > 0
      ? pillVerdicts.has(v)
      : (showAll || ACTIONABLE.includes(v));
    if (!statusOk) return false;
    if (!search) return true;
    const hay = `${r.rule_name_he ?? ""} ${r.notes_he ?? ""} ${r.remediation_he ?? ""}`;
    return hay.toLowerCase().includes(search.toLowerCase());
  };

  const sections: Array<{ key: SectionKey; title: string; rules: Rule[] }> = [
    { key: "disciplines", title: "בדיקה רב-תחומית", rules: disciplineRules },
    { key: "content",     title: 'תאימות תוכן לתב"ע', rules: contentRules },
    { key: "format",      title: "תאימות פורמט", rules: formatRules },
  ];

  const anyFilterActive = activePills.length > 0 || search !== "";
  const nothingActionable = actionableCount === 0 && !showAll && !anyFilterActive;

  return (
    <div className="findings-list">
      <div className="findings-summary-bar" data-testid="findings-summary">
        <span className="findings-summary-counts">
          {allRules.length} סעיפים נבדקו · <b>{actionableCount}</b> דורשים את תשומת ליבך
        </span>
        <button type="button" className={"ghost-btn small" + (showAll ? " pressed" : "")}
                data-testid="findings-show-all-toggle"
                aria-pressed={showAll}
                onClick={() => setShowAll((s) => !s)}>
          {showAll ? "הציגי רק סעיפים לטיפול" : "הציגי את כל הסעיפים"}
        </button>
      </div>

      <div className="findings-filter-bar" data-testid="findings-filter-bar">
        {FILTER_PILLS.map((p) => {
          const on = activePills.includes(p.label);
          return (
            <button key={p.label} type="button"
                    className={"filter-pill" + (on ? " pressed" : "")}
                    aria-pressed={on}
                    onClick={() => setActivePills((prev) =>
                      on ? prev.filter((x) => x !== p.label) : [...prev, p.label])}>
              {p.label}
            </button>
          );
        })}
        {anyFilterActive && (
          <button type="button" className="ghost-btn small"
                  data-testid="findings-clear-filters"
                  onClick={() => { setActivePills([]); setSearchRaw(""); }}>
            נקי סינון
          </button>
        )}
        <input
          type="search"
          className="findings-search"
          placeholder="חיפוש בממצאים..."
          value={searchRaw}
          onChange={(e) => setSearchRaw(e.target.value)}
          data-testid="findings-search"
        />
      </div>

      {nothingActionable && (
        <div className="findings-all-clear" data-testid="findings-all-clear">
          כל הסעיפים תקינים - אין ממצאים הדורשים טיפול.
        </div>
      )}

      {sections.map((sec) => (
        <FindingsSection
          key={sec.key}
          sectionKey={sec.key}
          title={sec.title}
          rules={sec.rules}
          visible={visible}
          onJumpToPage={onJumpToPage}
          pdfAvailable={pdfAvailable}
        />
      ))}
    </div>
  );
}

function FindingsSection({
  sectionKey, title, rules, visible, onJumpToPage, pdfAvailable,
}: {
  sectionKey: SectionKey;
  title: string;
  rules: Rule[];
  visible: (r: Rule) => boolean;
  onJumpToPage?: (n: number) => void;
  pdfAvailable: boolean;
}) {
  // Counts always reflect ALL rules in the section - context for the
  // header regardless of active filters.
  const counts = countVerdicts(rules);
  const [collapsed, setCollapsed] = useState(false);
  const visibleRules = rules.filter(visible);
  const noRulesAtAll = rules.length === 0;
  const allFiltered = !noRulesAtAll && visibleRules.length === 0;

  return (
    <section className="findings-section" data-section={sectionKey}>
      {/* The whole header row is the collapse target - no dedicated icon
        * (round-2 addendum: the green chevron read as a mystery button). */}
      <header className="findings-section-header"
              onClick={() => setCollapsed((c) => !c)}
              role="button"
              aria-expanded={!collapsed}>
        <h3 className="findings-section-title">{title}</h3>
        <span className="findings-section-total">{rules.length} סעיפים</span>
        <span className="findings-section-counts">
          {counts.map(({ verdict, count }) => (
            <span key={verdict}
                  className={"verdict-pill " + (VERDICT_CLASS[verdict] ?? "v-na")}>
              <span className="verdict-count">{count}</span>
              {VERDICT_LABEL_HE[verdict] ?? verdict}
            </span>
          ))}
        </span>
      </header>
      {!collapsed && (
        <ul className="findings-rows">
          {noRulesAtAll && <li className="muted findings-empty">אין סעיפים</li>}
          {allFiltered && (
            <li className="muted findings-empty findings-empty-filtered">
              אין ממצאים תואמים
            </li>
          )}
          {/*
            Composite React key - `${rule_code}::${ta_shetach_id ?? idx}`.

            Why: 7 content rules (CONTENT_UNIT_COUNT, CONTENT_BUILDING_
            AREA_MAIN/SERVICE_ABOVE/SERVICE_BELOW, CONTENT_BUILDING_
            HEIGHT, CONTENT_PARKING_RATIO, CONTENT_SETBACKS) and a
            handful of discipline rules have `scope: "per_ta_shetach"`
            in content_rules.json. The engine emits one result PER PLOT
            for each such rule, all sharing the same `rule_code` but
            distinguished by `ta_shetach_id` ("plot_1", "plot_2", …).
            Keying React rows by `rule_code` alone collides (the
            "Encountered two children with the same key" warning) and
            lets React drop/duplicate row identity across re-renders -
            drawer state can flicker, page-pill highlights can stick to
            the wrong row.

            The composite matches React semantics to the engine
            contract: each emitted result is its own row identity. The
            `?? idx` fallback covers rules that aren't per-plot (where
            rule_code is already unique within the section).

            Invariant: `rule_code` MUST NOT contain "::" - see
            docs/architecture/engine_output_contract.md §"rule_code
            invariants". If that ever changes, the separator here has
            to change too.
          */}
          {visibleRules.map((r, idx) => (
            <FindingRow
              key={`${r.rule_code}::${r.ta_shetach_id ?? idx}`}
              rule={r}
              onJumpToPage={onJumpToPage}
              pdfAvailable={pdfAvailable}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function FindingRow({
  rule, onJumpToPage, pdfAvailable,
}: { rule: Rule; onJumpToPage?: (n: number) => void; pdfAvailable: boolean }) {
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
    if (pdfAvailable && pages.length > 0 && onJumpToPage) {
      onJumpToPage(pages[0]);
    } else {
      setExpanded((x) => !x);
    }
  }

  // Page references: jump buttons when the plan PDF is viewable, plain
  // text otherwise (the reference is still valuable on paper).
  const pagePill = (p: number) => pdfAvailable ? (
    <button
      key={p}
      className="page-pill"
      onClick={(e) => { e.stopPropagation(); onJumpToPage?.(p); }}
      title={`קפוץ לעמוד ${p}`}
    >
      עמ' {p}
    </button>
  ) : (
    <span key={p} className="page-pill page-pill-static">עמ' {p}</span>
  );

  const discTag = rule.discipline ? DISCIPLINE_LABEL_HE[rule.discipline] : null;
  const plotTag = rule.ta_shetach_id ? rule.ta_shetach_id.replace("plot_", "תא ") : null;
  // Defensive fallback if rule_name_he is missing from the engine (shouldn't
  // happen since we backfilled the engine to populate it for all sections,
  // but never expose the raw rule_code in user-facing UI).
  const displayName = (rule.rule_name_he ?? "").trim() || "סעיף ללא שם";

  return (
    <li className={"finding-row" + (expanded ? " expanded" : "")}
        data-testid={`finding-row-${rule.rule_code}${rule.ta_shetach_id ? "-" + rule.ta_shetach_id : ""}`}
        onClick={onRowClick}>
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
              {pages.slice(0, 6).map(pagePill)}
              {pages.length > 6 && (
                <span className="page-pill-more">+{pages.length - 6}</span>
              )}
            </div>
          )}
        </div>
        <button
          className="row-expand-btn"
          onClick={(e) => { e.stopPropagation(); setExpanded((x) => !x); }}
          aria-label={expanded ? "סגרי פרטים" : "פתחי פרטים"}
          data-testid={`finding-expand-${rule.rule_code}${rule.ta_shetach_id ? "-" + rule.ta_shetach_id : ""}`}
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
              <div className="drawer-label">הערת התוכנה</div>
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
                {pages.map(pagePill)}
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
