import { useEffect, useState } from "react";
import {
  createGuideline,
  editGuideline,
  guidelineHistory,
  listDisciplines,
  listGuidelines,
  openGuidelinesPdf,
  type DisciplineDef,
  type GuidelineOut,
} from "../api";
import { MaybeApiError } from "../components/ErrorNotice";

// Global guidelines editor - city-wide submission rules (NOT project-keyed).
// v0.2.0: PRIMARY grouping by canonical discipline (sticky nav + one
// collapsible card per discipline). Editing creates version+1; Ellen can add
// new guidelines (origin מינהלת) per discipline.
// v0.2.2: rows show title, version and body only. The source section drives
// the כללי sub-group headers but is no longer printed per row, and the
// auto/manual chip is gone - that distinction belongs in findings output,
// not in the rulebook.

export function Guidelines() {
  const [rows, setRows] = useState<GuidelineOut[] | null>(null);
  const [disciplines, setDisciplines] = useState<DisciplineDef[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<GuidelineOut | null>(null);
  const [historyFor, setHistoryFor] = useState<GuidelineOut | null>(null);
  const [addingFor, setAddingFor] = useState<string | "">("__closed__");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  // The PDF is generated then opened by the OS, which takes a beat and gives
  // no browser-level feedback of its own - so the button carries the whole
  // story: working, opened, or failed. Never silent.
  const [pdfState, setPdfState] = useState<"idle" | "working" | "opened">("idle");
  const [pdfErr, setPdfErr] = useState<string | null>(null);

  async function onOpenPdf() {
    if (pdfState === "working") return;
    setPdfState("working");
    setPdfErr(null);
    try {
      await openGuidelinesPdf();
      setPdfState("opened");
      window.setTimeout(() => setPdfState("idle"), 4000);
    } catch (e) {
      setPdfErr(String(e));
      setPdfState("idle");
    }
  }

  function refresh() {
    listGuidelines()
      .then((data) => { setRows(data); setErr(null); })
      .catch((e) => setErr(String(e)));
  }

  useEffect(() => {
    refresh();
    listDisciplines().then((d) => setDisciplines(d.disciplines)).catch(() => {});
  }, []);

  // Group by canonical discipline, in canonical order; rows without a
  // discipline fold into כללי.
  const byDiscipline = new Map<string, GuidelineOut[]>();
  for (const d of disciplines) byDiscipline.set(d.key, []);
  for (const g of rows ?? []) {
    const key = g.discipline_key && byDiscipline.has(g.discipline_key)
      ? g.discipline_key : "general";
    if (!byDiscipline.has(key)) byDiscipline.set(key, []);
    byDiscipline.get(key)!.push(g);
  }

  // v0.2.1: inside כללי only, split by the SOURCE DOCUMENT SECTION we kept
  // as metadata in Phase 1. Order follows first appearance (seed sort_order),
  // so the sub-groups read in document order. Authority-added rows carry no
  // source section and collect under "הנחיות מינהלת".
  const AUTHORITY_SUBGROUP = "הנחיות מינהלת";
  function subGroupsOf(items: GuidelineOut[]) {
    const groups = new Map<string, GuidelineOut[]>();
    for (const g of items) {
      const key = g.section_title?.trim() || AUTHORITY_SUBGROUP;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(g);
    }
    // The authority bucket always sorts last, however early a row appeared.
    return [...groups.entries()].sort(
      (a, b) =>
        Number(a[0] === AUTHORITY_SUBGROUP) - Number(b[0] === AUTHORITY_SUBGROUP),
    );
  }

  function renderRow(g: GuidelineOut) {
    return (
      <li key={g.id} className="guideline-row" data-testid={`guideline-row-${g.id}`}
          data-check-key={g.check_key ?? undefined}>
        <div className="guideline-main">
          <div className="guideline-title-line">
            <b>{g.title}</b>
            <span className="muted guideline-version"
                  title="מספר הגרסה עולה בכל עריכה; ההיסטוריה נשמרת">
              גרסה {g.version}
            </span>
            {g.origin && <span className="badge badge-origin">{g.origin}</span>}
          </div>
          {g.guideline_type === "checkable" && g.check_value !== null && (
            <div className="guideline-value" data-testid={`guideline-value-${g.id}`}>
              ערך נדרש: <b>{g.check_value}</b> {g.unit ?? ""}
            </div>
          )}
          {g.body_text && <p className="muted guideline-body">{g.body_text}</p>}
        </div>
        <div className="guideline-actions">
          <button type="button" className="primary-btn"
                  data-testid={`guideline-edit-${g.id}`}
                  onClick={() => setEditing(g)}>
            עריכה
          </button>
          <button type="button" className="icon-btn"
                  aria-label="היסטוריית גרסאות"
                  title="היסטוריית גרסאות"
                  data-testid={`guideline-history-${g.id}`}
                  onClick={() => setHistoryFor(g)}>
            {/* clock face - version history */}
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
                 fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 2" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      </li>
    );
  }

  function scrollToDiscipline(key: string) {
    setExpanded((e) => ({ ...e, [key]: true }));
    document.getElementById(`disc-${key}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <article className="page-guidelines">
      <header className="page-header">
        <div>
          <h1>הנחיות עירוניות לתוכנית העיצוב</h1>
          <p className="muted">
            הנחיות ההגשה החלות על כל תכניות העיצוב בעיר. עריכת ערך יוצרת גרסה
            חדשה - הבדיקה האוטומטית הבאה תשתמש בערך המעודכן.
          </p>
          <p className="muted guidelines-version-legend">
            לצד כל הנחיה מופיע מספר הגרסה שלה. המספר עולה בכל עריכה, וההיסטוריה
            המלאה נשמרת וזמינה בכפתור היסטוריה.
          </p>
        </div>
        <button
          type="button"
          className="primary-btn"
          onClick={onOpenPdf}
          disabled={pdfState === "working"}
          data-pdf-state={pdfState}
          data-testid="guidelines-pdf-download"
        >
          {pdfState === "working" && "מכינה את הקובץ..."}
          {pdfState === "opened" && "הקובץ נפתח"}
          {pdfState === "idle" && "הורדת PDF"}
        </button>
      </header>

      {pdfErr && <MaybeApiError error={pdfErr} title="לא ניתן להפיק את הקובץ" />}
      {err && <MaybeApiError error={err} title="לא ניתן לטעון את ההנחיות" />}
      {!rows && !err && <p className="muted">טוענת...</p>}
      {rows && rows.length === 0 && (
        <p className="muted">אין הנחיות מוגדרות עדיין.</p>
      )}

      {/* Sticky discipline nav - one chip per discipline with its count. */}
      {rows && rows.length > 0 && (
        <nav className="guidelines-disc-nav" data-testid="guidelines-disc-nav">
          {disciplines.map((d) => {
            const n = byDiscipline.get(d.key)?.length ?? 0;
            if (n === 0) return null;
            return (
              <button key={d.key} type="button" className="disc-nav-chip"
                      data-testid={`disc-nav-${d.key}`}
                      onClick={() => scrollToDiscipline(d.key)}>
                {d.label} <span className="disc-nav-count">{n}</span>
              </button>
            );
          })}
          <button type="button" className="ghost-btn small"
                  data-testid="add-guideline-global"
                  onClick={() => setAddingFor("")}>
            + הוסיפי הנחיה
          </button>
        </nav>
      )}

      {disciplines.map((d) => {
        const items = byDiscipline.get(d.key) ?? [];
        if (items.length === 0) return null;
        const isOpen = expanded[d.key] !== false;
        return (
          <details key={d.key} id={`disc-${d.key}`} className="card guidelines-group"
                   open={isOpen}
                   onToggle={(e) => setExpanded((x) => ({ ...x, [d.key]: (e.target as HTMLDetailsElement).open }))}>
            <summary className="card-title guidelines-section-summary">
              {d.label}
              <span className="muted guidelines-group-count"> · {items.length} הנחיות</span>
              <button type="button" className="ghost-btn small guidelines-group-add"
                      data-testid={`add-guideline-${d.key}`}
                      onClick={(e) => { e.preventDefault(); e.stopPropagation(); setAddingFor(d.key); }}>
                + הוסיפי הנחיה
              </button>
            </summary>
            {d.key === "general" ? (
              // כללי carries the whole submission rulebook (formats, booklet
              // structure, checklist), so a flat list of 81 rows is unusable.
              // Split it by source section; every other discipline is small
              // enough to stay flat.
              <div data-testid={`guidelines-group-${d.key}`}>
                {subGroupsOf(items).map(([title, subItems]) => (
                  <details key={title} className="guidelines-subgroup" open
                           data-testid={`guidelines-subgroup-${title}`}>
                    <summary className="guidelines-subgroup-summary">
                      {title}
                      <span className="muted guidelines-group-count">
                        {" "}· {subItems.length} הנחיות
                      </span>
                    </summary>
                    <ul className="guidelines-list">
                      {subItems.map(renderRow)}
                    </ul>
                  </details>
                ))}
              </div>
            ) : (
              <ul className="guidelines-list" data-testid={`guidelines-group-${d.key}`}>
                {items.map(renderRow)}
              </ul>
            )}
          </details>
        );
      })}

      {addingFor !== "__closed__" && (
        <AddDialog
          disciplines={disciplines}
          initialKey={addingFor}
          subCategories={subGroupsOf(byDiscipline.get("general") ?? [])
            .map(([t]) => t)
            .filter((t) => t !== AUTHORITY_SUBGROUP)}
          onClose={() => setAddingFor("__closed__")}
          onSaved={() => { setAddingFor("__closed__"); refresh(); }}
        />
      )}
      {editing && (
        <EditDialog
          guideline={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); refresh(); }}
        />
      )}
      {historyFor && (
        <HistoryDialog guideline={historyFor} onClose={() => setHistoryFor(null)} />
      )}
    </article>
  );
}

function AddDialog({
  disciplines, initialKey, subCategories, onClose, onSaved,
}: {
  disciplines: DisciplineDef[];
  initialKey: string;
  subCategories: string[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [disc, setDisc] = useState(initialKey);
  const [title, setTitle] = useState("");
  const [bodyText, setBodyText] = useState("");
  const [subCat, setSubCat] = useState("");
  const [subCatFree, setSubCatFree] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const hebrewCount = (title.match(/[א-ת]/g) ?? []).length;
  const valid = disc !== "" && hebrewCount >= 4 && bodyText.trim().length >= 10;

  // Sub-category is offered for כללי only - the other disciplines are small
  // enough to stay flat, so an extra field there would be noise.
  const showSubCat = disc === "general";
  const effectiveSubCat = subCat === "__free__" ? subCatFree.trim() : subCat;

  async function onSave() {
    if (!valid || saving) return;
    setSaving(true);
    setErr(null);
    try {
      await createGuideline({
        discipline_key: disc,
        title: title.trim(),
        body_text: bodyText.trim(),
        ...(showSubCat && effectiveSubCat ? { section_title: effectiveSubCat } : {}),
      });
      onSaved();
    } catch (e) {
      setErr(String(e));
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <h2 className="card-title">הוספת הנחיה</h2>
        <p className="muted">הנחיה חדשה מטעם המינהלת. נשמרת כגרסה 1 וניתנת לעריכה ככל הנחיה.</p>
        <label className="form-label">
          <span>תחום</span>
          <select value={disc} onChange={(e) => setDisc(e.target.value)}
                  data-testid="add-guideline-discipline">
            <option value="">בחרי תחום ▾</option>
            {disciplines.map((d) => (
              <option key={d.key} value={d.key}>{d.label}</option>
            ))}
          </select>
        </label>
        {showSubCat && (
          <label className="form-label">
            <span>תת-קטגוריה (לא חובה)</span>
            <select value={subCat} onChange={(e) => setSubCat(e.target.value)}
                    data-testid="add-guideline-subcategory">
              <option value="">ללא תת-קטגוריה</option>
              {subCategories.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
              <option value="__free__">תת-קטגוריה חדשה...</option>
            </select>
            {subCat === "__free__" && (
              <input value={subCatFree} onChange={(e) => setSubCatFree(e.target.value)}
                     placeholder="שם תת-הקטגוריה"
                     data-testid="add-guideline-subcategory-new" />
            )}
          </label>
        )}
        <label className="form-label">
          <span>כותרת</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)}
                 data-testid="add-guideline-title" />
          {title.length > 0 && hebrewCount < 4 && (
            <span className="small-error">הכותרת חייבת להכיל לפחות 4 אותיות בעברית</span>
          )}
        </label>
        <label className="form-label">
          <span>נוסח ההנחיה</span>
          <textarea rows={4} value={bodyText}
                    onChange={(e) => setBodyText(e.target.value)}
                    data-testid="add-guideline-body" />
          {bodyText.length > 0 && bodyText.trim().length < 10 && (
            <span className="small-error">נוסח ההנחיה חייב להכיל לפחות 10 תווים</span>
          )}
        </label>
        {err && <MaybeApiError error={err} title="לא ניתן לשמור את ההנחיה" />}
        <div className="modal-actions">
          <button type="button" className="primary-btn" disabled={!valid || saving}
                  onClick={onSave} data-testid="add-guideline-save">
            {saving ? "שומרת..." : "שמירה"}
          </button>
          <button type="button" className="ghost-btn" onClick={onClose}>
            ביטול
          </button>
        </div>
      </div>
    </div>
  );
}

function EditDialog({
  guideline,
  onClose,
  onSaved,
}: {
  guideline: GuidelineOut;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState(guideline.title);
  const [bodyText, setBodyText] = useState(guideline.body_text ?? "");
  const [value, setValue] = useState(
    guideline.check_value !== null ? String(guideline.check_value) : "",
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function onSave() {
    setSaving(true);
    setErr(null);
    try {
      const payload: { title?: string; body_text?: string; check_value?: number } = {};
      if (title !== guideline.title) payload.title = title;
      if (bodyText !== (guideline.body_text ?? "")) payload.body_text = bodyText;
      if (guideline.guideline_type === "checkable" && value.trim() !== "") {
        const num = Number(value);
        if (Number.isNaN(num)) {
          setErr("הערך חייב להיות מספר");
          setSaving(false);
          return;
        }
        if (num !== guideline.check_value) payload.check_value = num;
      }
      await editGuideline(guideline.id, payload);
      onSaved();
    } catch (e) {
      setErr(String(e));
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <h2 className="card-title">עריכת הנחיה</h2>
        <p className="muted">
          השמירה יוצרת גרסה {guideline.version + 1}; הגרסה הנוכחית נשמרת בהיסטוריה.
        </p>
        <label className="form-label">
          <span>כותרת</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)}
                 data-testid="guideline-edit-title" />
        </label>
        <label className="form-label">
          <span>נוסח ההנחיה</span>
          <textarea rows={4} value={bodyText}
                    onChange={(e) => setBodyText(e.target.value)}
                    data-testid="guideline-edit-body" />
        </label>
        {guideline.guideline_type === "checkable" && (
          <label className="form-label">
            <span>ערך נדרש {guideline.unit ? `(${guideline.unit})` : ""}</span>
            <input dir="ltr" inputMode="decimal" value={value}
                   onChange={(e) => setValue(e.target.value)}
                   data-testid="guideline-edit-value" />
          </label>
        )}
        {err && <MaybeApiError error={err} title="לא ניתן לטעון את ההנחיות" />}
        <div className="modal-actions">
          <button type="button" className="primary-btn" disabled={saving}
                  onClick={onSave} data-testid="guideline-edit-save">
            {saving ? "שומרת..." : "שמירה"}
          </button>
          <button type="button" className="ghost-btn" onClick={onClose}>
            ביטול
          </button>
        </div>
      </div>
    </div>
  );
}

function HistoryDialog({
  guideline,
  onClose,
}: {
  guideline: GuidelineOut;
  onClose: () => void;
}) {
  const [versions, setVersions] = useState<GuidelineOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    guidelineHistory(guideline.id)
      .then((data) => { setVersions(data); setErr(null); })
      .catch((e) => setErr(String(e)));
  }, [guideline.id]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <h2 className="card-title">היסטוריית גרסאות - {guideline.title}</h2>
        {err && <MaybeApiError error={err} title="לא ניתן לטעון את ההנחיות" />}
        {!versions && !err && <p className="muted">טוענת...</p>}
        {versions && (
          <ul className="guideline-history-list" data-testid="guideline-history-list">
            {versions.map((v) => (
              <li key={v.id} className={v.is_active ? "active-version" : ""}>
                <div>
                  <b>גרסה {v.version}</b>
                  {v.is_active && <span className="badge badge-auto">פעילה</span>}
                  {v.check_value !== null && (
                    <span> · ערך: {v.check_value} {v.unit ?? ""}</span>
                  )}
                </div>
                {v.edited_at && (
                  <div className="muted">
                    עודכן: {v.edited_at.replace("T", " ").slice(0, 16)}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        <div className="modal-actions">
          <button type="button" className="ghost-btn" onClick={onClose}>
            סגירה
          </button>
        </div>
      </div>
    </div>
  );
}
