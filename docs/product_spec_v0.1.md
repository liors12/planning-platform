# Product Specification — Municipal Compliance Platform UI
## Ness Ziona Urban Renewal Authority — v1.0 (Pilot)

**Document status:** Draft v0.1 — pending review
**Author:** Lior (with synthesis from 5 AI consultations)
**Date:** May 2026
**Target release:** Pilot to Ellen, ~3 months from kickoff
**Future scope:** Commercial sale to additional municipalities (v2+)

---

## 1. Executive summary

A local-first Windows desktop application that wraps the existing deterministic Python compliance engine and gives Ellen (the Ness Ziona Urban Renewal Authority director) a complete UI for her end-to-end submission review workflow.

The app handles:
- **Upload** of architect submissions (PDF + CAD) per project
- **Automated compliance review** against the project's statutory plan (תב"ע) and municipal guidelines
- **Editable guidelines** with automatic versioning and re-downloadable requirements documents
- **Structured discipline manager feedback** (post-meeting overrides)
- **Final document generation** of the engineer's compliance opinion (חוות דעת) with municipal letterhead, ready for Ellen to sign

The engine itself is unchanged — the app is the UI layer + project/version management around what already works.

**Success criteria (v1 pilot):**
- Ellen completes the full v25 submission cycle entirely inside the app, end-to-end
- Final חוות דעת PDF is signature-ready and identical in quality to what she'd produce manually
- Three discipline managers' feedback captured in-app, no spreadsheets or printouts needed
- App runs reliably on her 8GB Windows machine without freezes
- Ness Ziona IT approves the installer for ongoing use

---

## 2. Product principles

1. **Local-first.** All data on Ellen's machine. No cloud dependency. No external API calls during normal operation.
2. **Deterministic.** Same input → same output, always. Every finding traces to its source. Legal defensibility is the north star.
3. **Auditable.** Every change versioned. Every override attributed. Every report shows which guidelines version it was generated against.
4. **Hebrew RTL throughout.** Not retrofitted; designed RTL from day one.
5. **Cross-platform development.** Lior develops on Mac, Ellen runs on Windows. Build pipeline supports both.
6. **Free/open-source stack.** No paid licenses in the dependency tree. Code signing deferred to commercial phase.
7. **Memory-conscious.** Heavy operations isolated to subprocesses so RAM is reclaimed cleanly. Target environment: 8GB Windows machine with SSD.
8. **Build once, sell to many.** Pilot architecture must support multi-municipality without rewrite. Municipality-specific data stays in profile packages, not code.

---

## 3. Users & use cases

### Primary user: Ellen
- Licensed engineer, government professional, ~40-60yo, non-developer
- Manages 5-10 concurrent urban renewal projects, each with its own תב"ע
- Receives architect submissions ~every 2 months per project
- Conducts review meetings with three discipline managers per submission
- Signs the final חוות דעת as the engineer of record
- Hebrew native, English functional
- Uses Outlook, Excel, Word daily; not a power user but tech-comfortable

### Indirect users (don't operate the software but consume its output)
- **Architects** (e.g., Kika Braz) — receive the final חוות דעת and respond
- **Discipline managers** (waste / landscape / infrastructure / city architect) — review printed templates Ellen brings to meetings
- **Municipality leadership** — may receive periodic summary reports

### Future users (v2+)
- Authority directors at other Israeli municipalities (Holon, Ramat Gan, Rishon LeZion, Lod)
- Possibly: discipline managers who use the system directly (currently only Ellen does)

### Primary workflows

**Workflow 1: New submission review (the daily-use flow)**
1. Ellen receives architect PDF for an active project
2. Upload submission via app → engine auto-runs vision extraction + rule checks
3. Review the engine's compliance report inside the app
4. Cross-reference findings against the architect's PDF (side-by-side view)
5. Schedule meetings with three discipline managers
6. Generate printed templates from app, take to meetings
7. Enter manager verdicts into app after each meeting
8. Generate final חוות דעת with all overrides incorporated
9. Sign, export PDF, send to architect

**Workflow 2: Guidelines update**
1. Ellen identifies a policy change needed (e.g., updated parking ratio standard)
2. Open guidelines editor in app
3. Modify rule threshold
4. App creates new immutable version
5. Re-download updated submission requirements doc to send to architects
6. Next submission to that project automatically uses the new guidelines version

**Workflow 3: Multi-submission iteration**
1. Architect submits v24.3 (revision after discipline feedback)
2. Upload to same project → new submission version created
3. Engine identifies what changed from v24.2
4. Ellen reviews delta-focused report, not the full review again
5. Final חוות דעת for v24.3 references the change history

---

## 4. Architecture

### High-level diagram

```
┌─────────────────────────────────────────────────────────┐
│                  Tauri v2 Desktop Shell                 │
│           (WebView2 on Windows / WebKit on Mac)         │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  React + Vite Frontend (TypeScript)             │   │
│  │  - Project sidebar + tabbed workspace           │   │
│  │  - Embedded pdf.js viewer                       │   │
│  │  - Data grids for rule review                   │   │
│  │  - Forms for discipline feedback                │   │
│  └─────────────────┬───────────────────────────────┘   │
│                    │ HTTP (localhost only)              │
│  ┌─────────────────▼───────────────────────────────┐   │
│  │  FastAPI Sidecar (PyInstaller --onedir)         │   │
│  │  - Always running, lightweight (~100MB)         │   │
│  │  - Manages job queue                            │   │
│  │  - Spawns worker subprocesses for heavy ops     │   │
│  │  - Persists state to SQLite                     │   │
│  └─────────────────┬───────────────────────────────┘   │
│                    │ spawn()                            │
│  ┌─────────────────▼───────────────────────────────┐   │
│  │  Worker Subprocesses (transient)                │   │
│  │  - Compliance engine runs                       │   │
│  │  - WeasyPrint PDF generation                    │   │
│  │  - libredwg DWG parsing                         │   │
│  │  - Vision LLM extraction (future v8a-2)         │   │
│  │  Exit when work complete → OS reclaims memory   │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  Storage:                                               │
│  - SQLite + SQLCipher (encrypted at rest)               │
│  - File system: PDFs, DWGs, generated reports, JSON     │
└─────────────────────────────────────────────────────────┘
```

### Memory management strategy

**Persistent footprint (always on):** ~600 MB
- Tauri shell + WebView2: ~300 MB
- FastAPI orchestrator: ~100 MB
- React state + open views: ~200 MB

**Peak transient (during operation):**
- DWG parsing subprocess: +1.2 GB (released on exit)
- PDF generation subprocess: +300 MB (released on exit)
- Engine regeneration subprocess: +250 MB (released on exit)
- pdf.js viewer with loaded submission: +400 MB (released on unmount)

**Constraints derived from Ellen's 8GB SSD machine:**
- Windows + background apps consume ~3.5 GB
- Available for the app: ~4.5 GB
- Peak operation must stay below 2 GB to leave headroom

### Subprocess isolation rule
Every operation that uses >100 MB of memory or runs >2 seconds runs in a separate Python subprocess. The orchestrator dispatches jobs and reads results from disk after completion.

---

## 5. Feature modules

### Module A: Project & Submission Management

**Purpose:** First-class project navigation. Always know which project you're in.

**UI structure:**
- **Right-anchored sidebar** (RTL): list of projects with status badges (active / awaiting review / signed / archived)
- Each project expandable to show submission iterations (v24.1, v24.2, v24.3 + status)
- **Top toolbar:** project search, command palette (Ctrl+K), settings, recent activity
- **Main canvas:** project workspace with tabs (Overview / Submission / Findings / Guidelines / History / Final Opinion)

**Acceptance criteria:**
- [ ] Switch projects in ≤ 1 click from anywhere in the app
- [ ] App launches directly into the most-recent active project + submission
- [ ] Sidebar reflects status changes within 1 second of underlying state change
- [ ] Project search returns results in <100ms
- [ ] Command palette (Ctrl+K) supports: jump-to-project, jump-to-submission, jump-to-finding
- [ ] Archived projects collapsed by default; visible via toggle

**Project creation flow:**
- "+ New Project" button in sidebar
- Form: project name, תב"ע number, address, plot identifiers (1-N), creation date
- Optional: upload statutory plan PDF + DWG at creation
- On save: creates project directory, initializes versioning, ready for first submission

**Project metadata stored:**
- Name (Hebrew + English)
- תב"ע number
- Plot polygon definitions (from תב"ע DWG when uploaded)
- Discipline manager contacts (4 people)
- Submission history
- Guidelines version pinned at creation (and any overrides)

---

### Module B: Compliance Review Workspace (the core screen)

**Purpose:** The screen Ellen spends most of her time in. Split-pane workspace for reviewing a single submission against the engine's findings, with the architect's PDF always at hand.

**UI structure:**
- **Left pane (in RTL: smaller, ~40% width):** the architect's PDF, embedded via pdf.js
- **Right pane (~60% width):** findings list, organized by chapter
  - §1 Qualitative (Ellen's section — text editor)
  - §2 Per-plot content compliance (collapsible by plot)
  - §3 Multi-discipline (collapsible by discipline)
  - §4 Priority action list
- **Splitter** between panes is draggable; saved per-user
- **Top bar:** submission selector (v24.1 / v24.2 / v24.3), regeneration status badge, "Generate Final Document" button

**Per-finding row contains:**
- Verdict badge (color-coded: green / red / yellow / gray)
- Rule title (Hebrew)
- Brief evidence summary (1-line)
- Inline action: expand for details
- Page reference link → clicks jump the PDF viewer to that page

**Expanded finding panel:**
- Full evidence (Cowork's visual description for §3, computed values for §2)
- Override controls (verdict radio + note field)
- Provenance: source JSON, rule version, override author (if any), timestamps
- "Show on PDF" button → highlights the relevant area on the embedded PDF (Phase 2 feature)

**Acceptance criteria:**
- [ ] Click any finding → PDF viewer scrolls to relevant page within 500ms
- [ ] PDF viewer handles 80-page rasterized files without freezing (lazy page rendering)
- [ ] Findings list supports filtering: "show only failing" / "show only changed" / "show only requires review"
- [ ] Splitter pane positions persist per project
- [ ] Override action shows immediately in UI (optimistic update); engine regeneration queues separately
- [ ] After any edit, top bar shows "Pending changes — Regenerate" badge
- [ ] Generate Final Document button disabled while regeneration is pending or running

**Performance targets:**
- Submission with 80-page PDF + 150 findings opens in <3 seconds
- Findings filter applies in <200ms
- PDF page navigation: <500ms latency

---

### Module C: Guidelines Editor

**Purpose:** Let Ellen modify the rules the engine checks against. Every change creates an immutable new version.

**UI structure:**
- **Left sidebar:** discipline categories (content / waste / landscape / infrastructure / architecture / etc.)
- **Main canvas:** rules in that discipline, displayed as inline-editable rows
- **Top bar:** version selector ("Current Guidelines v12 — applied to active submissions" with chip + history link)
- **Right drawer:** version history timeline + diff view

**Per-rule row:**
- Rule code + Hebrew name
- Rule type badge (numeric / geometric / document_presence / etc.)
- Editable threshold(s) or parameters
- Reference to source municipal text (citation)
- Last modified date + author

**Editing model:**
- Inline edit: click value, modify, blur to save (debounced)
- After ANY edit, banner appears: "Unsaved guideline changes — Save as new version"
- "Save as new version" → modal asks for change description (e.g., "Updated parking ratio per 2026 standard")
- New version becomes "Current"; previous is read-only in history
- Active submissions still reference the version they were generated against (no retroactive changes)

**Version history drawer:**
- Vertical timeline, reverse-chronological
- Each version: number, date, change summary, author, "Compare with previous" link
- Diff view: changed rules highlighted with before/after side-by-side in plain language
- "Re-download submission requirements doc" button on each version

**Acceptance criteria:**
- [ ] All rules from the existing rule schema appear in the editor with correct categorization
- [ ] Editing a numeric threshold and saving creates a new version row
- [ ] Old versions are visually distinct (desaturated, with lock icon) and explicitly read-only
- [ ] Diff view between any two versions shows only what changed, in plain Hebrew
- [ ] Re-download requirements doc generates an updated .docx reflecting the current version's rules
- [ ] No way to delete or rewrite past versions (immutability enforced)

**Out of scope for v1:**
- Adding entirely new rule types (only thresholds editable; rule logic stays code-side)
- Branching versions (linear history only)
- Multi-user concurrent editing

---

### Module D: Discipline Manager Feedback

**Purpose:** Capture each discipline manager's verdict per rule, after Ellen's meetings with them. Their feedback overrides the vision-extracted findings.

**UI structure:**
- **Top tabs:** one per discipline (שפ"ע / גינון / תשתיות / אדריכלות)
- **Main canvas:** inline data grid, one row per rule in that discipline
- **Right drawer:** rule detail, expanded form, additional findings

**Per-row controls:**
- Rule title
- Engine's current verdict (color-coded)
- Manager's verdict (3-state segmented control: תקין / נדרש תיקון / דורש בירור)
- Inline note field (single-line, expandable)
- Status icon: untouched / overridden / confirmed

**Right drawer (on row click):**
- Full rule text
- Engine's full evidence (Cowork's visual description + page references)
- Manager's full note (multi-line text area)
- "Additional findings" section: structured fields for things the manager raised that aren't in the existing rules
- Save automatically on blur

**Above-grid metadata:**
- Manager name (text field, pre-populated from project config)
- Meeting date
- Status: "Not started" / "In progress (X of Y rules)" / "Complete"

**Acceptance criteria:**
- [ ] Grid renders all relevant rules within 500ms (target: 30 rules per discipline)
- [ ] Verdict change saves to disk within 500ms (debounced)
- [ ] Status header updates progress count in real-time
- [ ] "Generate Final Document" disabled until at least one discipline has status "Complete" OR Ellen explicitly opts to generate with partial feedback
- [ ] Keyboard navigation: up/down arrows between rows, 1/2/3 to set verdict
- [ ] Bulk action: "Mark all unchanged as confirmed"
- [ ] Filter: "show only changed by manager" / "show only requires-review"

**Templates export:**
- Same data structure can be exported as printable .docx (the templates we just shipped) for in-person manager meetings
- Manager feedback from printed templates can be imported back into this view (manual entry, or future: form scanning)

---

### Module E: Final Document Generation

**Purpose:** Produce the signed-ready חוות דעת PDF with municipal letterhead, full provenance, and Ellen's signature line.

**UI structure:**
- **Main area:** preview of generated document (rendered as embedded PDF)
- **Right sidebar:** generation controls + signature management
- **Top bar:** "Regenerate" / "Export" / "Mark as Signed"

**Generation triggers:**
- Manual: "Generate Final Document" button (after all feedback captured)
- Cannot generate while regeneration is pending in any other tab

**Document content:**
- Cover page with municipal logo + project metadata + version stamp
- §1 Qualitative chapter (from Ellen's text editor)
- §2 Per-plot content compliance (full table)
- §3 Multi-discipline (with manager overrides incorporated, not Cowork findings)
- §4 Priority list (consolidated)
- Appendices: provenance audit, guidelines version reference, signature page

**Signature workflow:**
- "Mark as Signed" → prompts Ellen to confirm
- Once signed: document becomes immutable
- Signed copy stored in project archive with timestamp + version pin
- Subsequent regenerations create new revisions; signed version preserved

**Acceptance criteria:**
- [ ] Generated PDF identical in structure to current v8j output
- [ ] Cover includes municipal logo + project + תב"ע number + version + date
- [ ] All overrides from Module D reflected in §3
- [ ] Audit appendix shows: guidelines version, source JSON files, override authors, generation timestamp
- [ ] PDF generation completes in <30 seconds (subprocess-isolated)
- [ ] "Mark as Signed" locks the document and creates an immutable archive entry
- [ ] Export options: PDF, .docx (editable for Ellen's edits before sending)

---

### Cross-cutting: Audit & Provenance

Every finding in every report traces to its origin. This is non-negotiable for legal defensibility.

**Per-finding provenance includes:**
- Source: which JSON file, which page in source PDF, which extraction pass
- Rule: which rule code, which guidelines version
- Override: who applied it (Ellen or which manager), when, with what note
- Generation: timestamp of report generation, software version

**UI disclosure:**
- Collapsed by default in finding rows (small "i" icon)
- Expandable per-finding via right drawer
- "Audit Trail" project-level tab shows complete chronological log

**Acceptance criteria:**
- [ ] Every finding can produce its provenance chain in <500ms
- [ ] Provenance is exportable as a structured JSON for legal review
- [ ] No finding can exist without a complete provenance chain (enforced at the database level)

---

### Cross-cutting: Background Jobs & Long Operations

**Job types:**
- PDF extraction (vision LLM — future v8a-2; manual in v1)
- DWG parsing (libredwg → DXF → ezdxf → JSON)
- Engine regeneration (rule check against extracted data)
- WeasyPrint PDF generation
- Submission requirements doc generation

**UX:**
- Right-side "Jobs" panel (toggleable, collapsed by default)
- Each job shows: type, project, current phase, progress, started-at
- App-wide notification on job completion
- Cancel button for in-progress jobs (graceful, with rollback)
- Failed jobs surface with error details + retry button

**Acceptance criteria:**
- [ ] Long jobs (>5 sec) NEVER block the UI
- [ ] User can navigate to other projects/tabs while a job runs
- [ ] Job state persists across app restarts (recovery from crashes)
- [ ] Jobs panel shows accurate phase information (not generic "loading")

---

### Cross-cutting: Versioning

Applies to: guidelines, submissions, generated documents.

**Principles:**
- Immutable past versions (no rewriting history)
- Semantic labels (not Git hashes)
- Linear chronology
- Every artifact pins the versions it was generated against

**UI patterns:**
- Status chips: "Current" / "Previous" / "Archive"
- Timeline drawers with chronological events
- Diff views between versions, in plain Hebrew
- No branching, no merging

---

### Cross-cutting: Multi-Project Workspace

**Project switching:**
- Sidebar always visible
- Cmd/Ctrl+K command palette for fast switching
- Recent projects pinned at top
- Status badges for at-a-glance triage

**Data isolation:**
- Each project has its own SQLite tables (or schema namespace)
- File system: `projects/{project_id}/submissions/{version}/...`
- No cross-project data leakage in views or queries

---

### Cross-cutting: Backup & Data Integrity

**Backup strategy:**
- On clean app exit: encrypted SQLite backup written to configured destination
- Destination: municipal network drive (preferred) or local backup folder
- Manual: "Export Project Archive" → encrypted ZIP with all project files
- Restoration: "Import Project Archive" from settings

**Data integrity:**
- Every database write transactional
- WAL mode enabled (`PRAGMA journal_mode=WAL`)
- Atomic file writes via tempfile + rename pattern
- Job state persisted to enable recovery

---

## 6. Technical specifications

### Stack (locked in from consultation synthesis)

| Layer | Technology | License |
|---|---|---|
| Desktop shell | Tauri v2 | MIT/Apache 2.0 |
| Frontend | React 18 + Vite + TypeScript | MIT |
| UI library | shadcn/ui (Radix UI primitives) | MIT |
| Tables | TanStack Table v8 | MIT |
| Routing | TanStack Router | MIT |
| Server state | TanStack Query | MIT |
| Local state | Zustand | MIT |
| Forms | React Hook Form + Zod | MIT |
| PDF viewer | react-pdf (over pdf.js) | MIT |
| Icons | Lucide React (RTL-aware variants) | ISC |
| Backend | FastAPI + Pydantic | MIT |
| ORM | SQLAlchemy + Alembic | MIT |
| Database | SQLite + SQLCipher (community) | Public domain / BSD |
| Background jobs | In-process worker via subprocess.Popen | stdlib |
| PDF generation | WeasyPrint | BSD-3-Clause |
| CAD parsing | libredwg CLI subprocess | GPL v3 (subprocess-safe) |
| Fonts | Heebo (bundled) + Segoe UI Hebrew fallback | Apache 2.0 |
| Packaging | PyInstaller (--onedir) + Tauri NSIS | GPL exception / zlib |

### Frontend project structure

```
src/
├── routes/
│   ├── __root.tsx               # App shell, sidebar, routing
│   ├── projects/$projectId/
│   │   ├── overview.tsx
│   │   ├── submission.tsx       # Module B (the core screen)
│   │   ├── guidelines.tsx       # Module C
│   │   ├── feedback.tsx         # Module D
│   │   └── document.tsx         # Module E
│   └── settings.tsx
├── components/
│   ├── ProjectSidebar/
│   ├── SubmissionWorkspace/
│   │   ├── FindingsList/
│   │   ├── FindingRow/
│   │   ├── PdfViewer/           # react-pdf wrapper
│   │   └── Splitter/
│   ├── GuidelinesEditor/
│   ├── DisciplineGrid/
│   ├── JobsPanel/
│   └── ui/                      # shadcn/ui primitives
├── hooks/
│   ├── useProjects.ts
│   ├── useFindings.ts
│   ├── useJobs.ts
│   └── useGuidelines.ts
├── lib/
│   ├── api.ts                   # FastAPI client
│   ├── rtl.ts                   # RTL utilities (bidi isolation, etc.)
│   └── types.ts                 # Generated from Pydantic models
└── styles/
    └── globals.css              # RTL-aware base styles
```

### Backend project structure

```
backend/
├── main.py                      # FastAPI entry + Tauri lifecycle hooks
├── api/
│   ├── projects.py
│   ├── submissions.py
│   ├── guidelines.py
│   ├── findings.py
│   ├── jobs.py
│   └── documents.py
├── models/
│   ├── project.py               # SQLAlchemy models
│   ├── submission.py
│   ├── guidelines.py
│   └── audit.py
├── workers/
│   ├── engine_worker.py         # Spawned as subprocess
│   ├── dwg_worker.py            # Spawned as subprocess (uses libredwg)
│   ├── pdf_worker.py            # Spawned as subprocess (WeasyPrint)
│   └── extraction_worker.py     # Future v8a-2
├── services/
│   ├── job_queue.py
│   ├── backup.py
│   └── versioning.py
└── db/
    ├── migrations/
    └── session.py
```

### Inter-process communication

- React ↔ FastAPI: HTTP over localhost (127.0.0.1 only — NEVER 0.0.0.0)
- FastAPI ↔ Worker subprocesses: spawn + stdin/stdout for control + JSON files on disk for data
- FastAPI ↔ Tauri shell: stdin/stdout for graceful shutdown signaling

### CORS configuration

```python
allowed_origins = [
    "tauri://localhost",
    "http://tauri.localhost",
    "http://127.0.0.1:1420",  # Vite dev server
]
```

### Database schema notes

Tables (existing engine schema preserved):
- `projects`
- `submissions` (versioned)
- `submission_extracts` (vision-extracted JSON references)
- `discipline_findings` (vision-extracted + manager overrides)
- `guidelines_versions` (full snapshot per version)
- `rule_definitions` (current ruleset)
- `project_rule_exceptions`
- `takanon_versions`
- `audit_log` (every state change)
- `jobs` (queue + history)
- `documents` (generated artifacts with version pins)

New for UI:
- `user_preferences` (sidebar state, pane sizes, recent projects)
- `app_metadata` (version, schema version, last-startup timestamp)

### Build pipeline

**Development (Mac):**
1. `cd backend && pip install -e .` (engine + deps)
2. `cd frontend && npm install && npm run dev` (Vite hot reload at :1420)
3. `cd src-tauri && cargo tauri dev` (Tauri shell with hot reload)

**Production build (Mac → Windows via Parallels VM):**
1. `cd frontend && npm run build` → static assets in `dist/`
2. `cd backend && pyinstaller backend.spec --onedir` → `dist/backend/`
3. Copy `dist/backend/` into `src-tauri/binaries/`
4. `cd src-tauri && cargo tauri build` → NSIS installer in `dist/`
5. Transfer installer to Windows 11 VM for testing

**Critical PyInstaller .spec configurations:**
- `--onedir` mode (never `--onefile` — WeasyPrint extraction overhead)
- Explicit `add_data` for: GTK DLLs, Cairo binaries, font config files, libredwg CLI binary
- Hidden imports for SQLAlchemy dialects, FastAPI startup hooks
- `multiprocessing.freeze_support()` at entry point

**Critical Tauri configuration:**
- `bundle.externalBin`: point to PyInstaller output
- `windows.WebView2.silentInstall`: true (auto-install if missing on Win10)
- `nsis.installerLanguages`: include Hebrew
- `windows.shouldExecuteWith`: user mode (no admin required)

---

## 7. Memory management implementation

The rules below are operational summaries. Rationale, prohibited patterns, and worked
examples live in [ADR-001](architecture/ADR-001-subprocess-isolation.md). Per-job-type
budgets are in [job_types.md](architecture/job_types.md).

### Backend rules (subprocess isolation)

1. **No heavy work in the FastAPI sidecar.** Operations >100 ms or >100 MB spawn an isolated Python subprocess; sidecar stays under 100 MB resident. → ADR-001 § Decision
2. **JSON-on-disk handoff.** Each job has a temp dir; sidecar writes `job_input.json`, worker writes `job_output.json` (or `error.json`) and exits. No data over stdin/stdout. → ADR-001 § Implication 1
3. **Concurrency cap of 1 (configurable to 2).** `PLATFORM_MAX_CONCURRENT_JOBS=1` default for the 8 GB target. → ADR-001 § Implication 2
4. **Per-job wall-clock budgets, enforced by SIGKILL.** Budget values in [job_types.md](architecture/job_types.md). → ADR-001 § Implication 3
5. **Workers use the platform installer's bundled Python.** Same interpreter as the sidecar, not a nested venv — WeasyPrint and libredwg need known native-dep paths. → ADR-001 § Implication 4
6. **No shared module imports between sidecar and workers.** Sidecar never imports from `compliance_engine/` or `dwg_parser/`. CLI invocation is the only contract. → ADR-001 § Implication 5
7. **Worker subprocess sets a hard memory ceiling via OS APIs** (`resource.setrlimit` on Unix, `JobObject` on Windows) at the budget in [job_types.md](architecture/job_types.md).

### Frontend rules (WebView + pdf.js)

8. **pdf.js component fully unmounts on tab navigation.** No background caching of rendered pages.
9. **Page virtualization in pdf.js viewer.** Only ±5 pages around current view rendered.
10. **5-minute inactivity timer on pdf.js.** Unloads PDF after no interaction; shows "Click to reload" placeholder.

### Verification

- Per-job peak memory budgets documented in [job_types.md](architecture/job_types.md); CI smoke test asserts observed peak ≤ budget.
- Integration smoke test: open 80-page PDF + trigger DWG parse + regenerate report → total app memory stays under 2.5 GB.
- Long-run test: 8-hour simulated workflow → no memory growth in sidecar or shell.

---

## 8. Security & Compliance

### Israeli legal context
- Subject to **חוק הגנת הפרטיות** (Privacy Protection Law) and **תקנות הגנת הפרטיות 2017**
- Data classification: **רגישות בינונית** (medium sensitivity) — planning documents, professional opinions, no medical or sensitive personal data
- IT review by Ness Ziona מערך מערכות מידע required before deployment

### Implemented protections

| Concern | Implementation |
|---|---|
| Data at rest | SQLite + SQLCipher AES-256, key derived from Ellen's app PIN |
| Data in transit | Localhost only (127.0.0.1). No external network. CORS strict. |
| Authentication | Windows OS login + optional app PIN at launch (post-idle re-auth) |
| Audit trail | Every state change written to immutable audit_log |
| Backup | Encrypted automated to municipal network drive; encrypted manual export |
| Code signing | Deferred to commercial phase (~$500/year EV cert) |
| Update mechanism | Manual signed installer for pilot. Auto-updater in commercial (Tauri's built-in) |

### IT review readiness checklist
Before submitting to IT:
- [ ] Source code repository accessible for review (private GitHub or similar)
- [ ] Dependency SBOM exported (cargo + npm + pip)
- [ ] Network behavior documented (localhost only, no external calls)
- [ ] Data flow diagram showing all read/write paths
- [ ] Encryption-at-rest demonstrated (SQLCipher key management explained)
- [ ] Audit log structure documented
- [ ] Installation path and registry footprint documented
- [ ] Uninstall behavior documented (data preservation by default)

### Known open questions for IT
- Source code review or installer review only?
- Required logging standards (beyond our audit_log)?
- Approved network drive path for backups?
- Code signing required?
- Antivirus whitelisting process?
- Acceptable update mechanism (manual vs. auto)?

---

## 9. Quality & testing

### Test environments
- **Primary dev:** Lior's Mac, Vite hot reload + Tauri dev mode
- **Cross-platform validation:** Parallels Desktop + Windows 11 VM
- **Pilot validation:** Ellen's Windows machine (final installer testing only)

### Test categories

**Engine regression tests** (existing — don't break):
- All 150 existing rules produce expected verdicts on known inputs
- v8j discipline findings pipeline preserved
- WeasyPrint output stable

**RTL tests:**
- Visual regression: every screen rendered in RTL, screenshots compared
- Mixed-content: dates, version numbers, English file paths render correctly
- All Radix portals (modals, tooltips, popovers) preserve RTL inheritance

**Memory tests:**
- Subprocess isolation verified per worker
- 8-hour session test: no memory growth
- Peak operation test: <2.5GB total app memory

**End-to-end tests:**
- Create project → upload submission → view findings → enter feedback → generate final doc → sign
- Guidelines edit → version created → requirements doc updated
- Multi-project: 5 active projects, switch between without leakage

### Manual acceptance testing
Before pilot rollout, Lior personally walks through each workflow on Windows VM. Ellen tests with v25 submission as final acceptance.

---

## 10. Phased delivery plan

### Phase 1: Foundation (Weeks 1-2)
**Deliverables:**
- Tauri + React + Vite + FastAPI skeleton runs end-to-end on Mac
- PyInstaller --onedir builds the backend cleanly
- NSIS installer builds and installs to a Windows 11 VM
- Hello-world: app opens, shows a placeholder UI, FastAPI responds
- Basic project model (just create/list projects)
- SQLite + SQLCipher initialized with WAL mode

**Acceptance:** "I can install the app on Windows, it opens, I can create a named project, the data persists across restarts."

### Phase 2: Core review workspace (Weeks 3-6)
**Deliverables:**
- Module A (Project & Submission Management) functional
- Module B (Compliance Review Workspace) — first iteration with PDF viewer and findings list
- Engine integration: upload triggers existing engine, results displayed
- Basic background job system with Jobs panel
- WeasyPrint generation through subprocess works
- Existing engine output identical to current command-line output

**Acceptance:** "Ellen can upload v25 submission, see findings, view PDF side-by-side, regenerate report."

### Phase 3: Editing workflows (Weeks 7-9)
**Deliverables:**
- Module C (Guidelines Editor) with versioning
- Module D (Discipline Manager Feedback) with override pipeline
- Audit trail UI (collapsed by default)
- Final document generation (Module E) basic version
- Versioning system: guidelines + submissions
- RTL polish across all screens

**Acceptance:** "Ellen can do the full v25 workflow inside the app: review → discipline feedback → final document. No external tools."

### Phase 4: Polish, packaging, security (Weeks 10-12)
**Deliverables:**
- RTL audit and fixes across every screen
- Memory profiling + subprocess tuning
- Backup/restore working with municipal network drive
- Signed installer (if code signing cert acquired) or signed manually
- IT review documentation package
- User documentation (Hebrew)
- Final acceptance testing with Ellen on her machine

**Acceptance:** "Installer signed, IT review documentation ready, Ellen runs the app on her actual hardware successfully. v25 ships through the app."

### Phase 5 (post-pilot, deferred):
- v8a-2: automated vision LLM extraction (replaces manual Cowork pass)
- v8a-3 Phase 2-3: full DWG parser with setback computation
- Multi-tenant onboarding (municipal profile packages)
- Auto-updater with signed releases
- Commercial sales features

---

## 11. Open questions & decisions still needed

| # | Question | Owner | Blocking? |
|---|---|---|---|
| 1 | What format does IT want for review — source code or installer? | Ellen → IT | Phase 4 |
| 2 | What network drive path is approved for backups? | Ellen → IT | Phase 3 |
| 3 | Will IT require code signing for the pilot, or accept manual approval? | Ellen → IT | Phase 4 |
| 4 | Specific antivirus whitelisting process for the installer? | Ellen → IT | Phase 4 |
| 5 | Does IT have a security checklist we should design against? | Ellen → IT | Phase 1 (ideally) |
| 6 | Acceptable update mechanism (manual installer vs. auto-updater)? | Ellen → IT | Phase 5 |
| 7 | Ellen's exact CPU and Windows version (for performance baseline)? | Lior | Phase 1 |
| 8 | Specific Hebrew terminology preferences (e.g., "מהדורה" vs "גרסה" for submission versions)? | Ellen | Phase 3 |
| 9 | Keyboard shortcuts: include or skip in v1? | Lior | Phase 2 |
| 10 | Dark mode: include or skip in v1? | Lior | Phase 2 |

---

## 12. Out of scope for v1 (explicit non-goals)

These are deliberately excluded from v1 to keep the build focused. They become v2 work after the pilot stabilizes.

- **Automated vision LLM extraction** (v8a-2) — Cowork remains manual through v1
- **Full DWG parser integration** (v8a-3 Phase 2-3) — Phase 1 only (read תב"ע plots); buildings + setback computation deferred
- **Multi-tenant onboarding** — pilot is Ness Ziona only; municipal profile packages come in v2
- **Discipline manager direct access** — only Ellen uses the software in v1
- **Real-time collaboration** — single-user app, no concurrent editing
- **Auto-updater** — manual installer distribution in v1
- **Mobile/tablet support** — desktop only
- **Architect-facing portal** — they receive PDFs by email, don't access the app
- **Direct integration with municipal systems** (CRM, ERP) — out of scope; manual export/import only
- **Public-facing features** — entirely internal tool
- **Multi-language UI** — Hebrew only in v1

---

## 13. Glossary

- **תב"ע** — statutory zoning plan (legal document)
- **תכנית עיצוב** — design plan (architect's submission)
- **חוות דעת** — engineer's compliance opinion (the final document)
- **תא שטח** — individual plot within a תב"ע
- **שצ"פ** — public open space
- **קווי בניין** — building setback lines
- **מינהלת התחדשות עירונית** — urban renewal authority (Ellen's office)
- **שפ"ע** — environment & sanitation (one of the discipline managers)
- **ממ"ד** — protected residential space (mandatory in Israeli buildings)
- **מבא"ת** — national CAD standard for Israeli planning documents
- **Cowork** — Anthropic's vision-LLM-based extraction tool (currently used manually)
- **Engine** — the existing deterministic Python compliance system

---

## 14. Document changelog

- **v0.1 (May 2026)** — Initial draft from architecture consultation synthesis + Ellen's full-vision direction
- *Future revisions logged here*
