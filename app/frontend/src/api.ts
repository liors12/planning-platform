// Typed client for the FastAPI sidecar. Hardcoded base URL for Phase 2a;
// Phase 4 will read the port from a Tauri-provided env var so production
// builds can randomize the sidecar port.
const SIDECAR_BASE = "http://127.0.0.1:17321";

// ── Common types ──────────────────────────────────────────────────────────

export interface HealthResponse {
  status: "ok";
  sidecar_version: string;
  bind: string;
  db: {
    journal_mode: string;
    cipher_version: string;
    sqlite_version: string;
    schema_version: string | null;
    last_started_at: string | null;
  };
  data_dir: string;
  max_concurrent_jobs: number;
}

export type ProjectStatus = "active" | "awaiting_review" | "signed" | "archived";

export interface ProjectOut {
  id: number;
  name_he: string;
  name_en: string | null;
  tava_number: string;
  address: string | null;
  status: ProjectStatus;
  created_at: string;
  archived_at: string | null;
  has_schema: boolean;
  latest_submission: SubmissionSummary | null;
  submission_count: number | null;
}

export interface SubmissionSummary {
  id: number;
  version_string: string;
  status: string;
  uploaded_at: string;
}

export type SubmissionStatus =
  | "uploaded"
  | "extracting"
  | "analyzing"
  | "complete"
  | "failed";

export type WorkflowStage = "draft" | "sent" | "response_received" | "verified";

export interface SubmissionOut {
  id: number;
  project_id: number;
  version_string: string;
  status: SubmissionStatus;
  workflow_stage: WorkflowStage;
  pdf_path: string;
  dwg_path: string | null;
  findings_json_path: string | null;
  uploaded_at: string;
  has_audit_results: boolean;
  has_report_pdf: boolean;
  has_report_xlsx: boolean;
  /** False on win32+frozen — the subprocess that runs the full audit
   * can't spawn an external Python in the packaged build. UI disables
   * the "הפעילי את התוכנה" button when false. */
  engine_run_available: boolean;
}

export type JobStatus = "queued" | "running" | "completed" | "failed";

export interface JobOut {
  id: string;
  job_type: string;
  submission_id: number | null;
  status: JobStatus;
  queued_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;       // JSON-encoded blob when status === "failed"
}

// ── Fetch helpers ─────────────────────────────────────────────────────────

// Wraps fetch() with retry+backoff for transport failures (ATS block,
// CORS preflight refused, connection refused, DNS, CSP, etc.). Native
// fetch() rejects with the opaque "TypeError: Load failed" for all of
// those — same string for every cause. This wrapper:
//
//   1. Retries up to 3 times on transport failure with backoff
//      200ms → 500ms → 1500ms (~2.2s total wait before giving up).
//      Solves the startup race where the React app mounts and fires
//      listProjects() in milliseconds, but the Python sidecar takes
//      1-3s to import FastAPI + bind 17321.
//
//   2. On final failure, throws an Error whose message includes the
//      URL, the retry count, and the first stack frame — so we can
//      debug from the UI without opening DevTools.
//
// HTTP 4xx/5xx are NOT retried here — fetch() resolves for those (it only
// rejects on transport failure). They flow through jsonOrThrow below.
// AbortError (user cancellation) is also not retried.
//
// The production fix for the race lives in Tauri Rust (Phase 5): the
// wrapper will gate window.show() on /health 200 OK so the WebView can't
// even start to load before the sidecar is ready. Once that lands, this
// retry becomes belt-and-braces (still useful for transient sidecar
// crashes / restarts during dev).
const FETCH_RETRY_DELAYS_MS = [200, 500, 1500] as const;

async function fetchOrThrow(url: string, init?: RequestInit): Promise<Response> {
  let lastErr: Error | null = null;
  for (let attempt = 0; attempt <= FETCH_RETRY_DELAYS_MS.length; attempt++) {
    if (attempt > 0) {
      await new Promise((r) => setTimeout(r, FETCH_RETRY_DELAYS_MS[attempt - 1]));
    }
    try {
      return await fetch(url, init);
    } catch (e) {
      lastErr = e as Error;
      // User cancellation — don't keep retrying.
      if (lastErr.name === "AbortError") break;
    }
  }
  const err = lastErr ?? new Error("unknown fetch failure");
  const firstFrame =
    err.stack?.split("\n").find((l) => l.trim().length > 0)?.trim() ?? "n/a";
  throw new Error(
    `${err.name}: ${err.message} | URL: ${url} | retries: ${FETCH_RETRY_DELAYS_MS.length} | at ${firstFrame}`,
  );
}

async function jsonOrThrow<T>(res: Response, what: string): Promise<T> {
  if (!res.ok) {
    let detail = "";
    try {
      detail = JSON.stringify(await res.json());
    } catch {
      try { detail = await res.text(); } catch { detail = "<no body>"; }
    }
    throw new Error(`${what} → HTTP ${res.status}: ${detail}`);
  }
  return res.json();
}

// ── Health ────────────────────────────────────────────────────────────────

export async function getHealth(): Promise<HealthResponse> {
  return jsonOrThrow<HealthResponse>(
    await fetchOrThrow(`${SIDECAR_BASE}/health`),
    "/health",
  );
}

// ── Diagnostics ───────────────────────────────────────────────────────────

export type DiagnosticsStatus = "healthy" | "degraded" | "error";

export interface FileCheck {
  path: string;
  exists: boolean;
}

export interface DiagnosticsResponse {
  status: DiagnosticsStatus;
  sidecar: { running: boolean; uptime_seconds: number; port: number };
  db: { connected: boolean; backend: string; encrypted: boolean; path: string };
  seed: {
    schema_file: FileCheck;
    metadata_file: FileCheck;
    audit_results_file: FileCheck;
  };
  projects: { count: number; names: string[] };
  weasyprint: FileCheck;
  render_ready: boolean;
  excel_ready: boolean;
  errors: string[];
}

export async function getDiagnostics(): Promise<DiagnosticsResponse> {
  return jsonOrThrow<DiagnosticsResponse>(
    await fetchOrThrow(`${SIDECAR_BASE}/diagnostics`),
    "/diagnostics",
  );
}

/** True iff the error looks like the sidecar is unreachable (network
 * failure, ECONNREFUSED, etc.) rather than a 4xx/5xx HTTP response.
 * Used by routes to swap the generic "TypeError: Failed to fetch" for
 * a Hebrew message pointing the user at the diagnostics panel. */
export function isSidecarUnreachable(err: unknown): boolean {
  const msg = String(err ?? "");
  return /Failed to fetch|NetworkError|ECONNREFUSED|fetch failed/i.test(msg);
}

// ── Projects ──────────────────────────────────────────────────────────────

export async function listProjects(includeArchived = false): Promise<ProjectOut[]> {
  const qs = includeArchived ? "?include_archived=true" : "";
  return jsonOrThrow<ProjectOut[]>(
    await fetchOrThrow(`${SIDECAR_BASE}/projects${qs}`),
    "GET /projects",
  );
}

export async function getProject(id: number): Promise<ProjectOut> {
  return jsonOrThrow<ProjectOut>(
    await fetchOrThrow(`${SIDECAR_BASE}/projects/${id}`),
    `GET /projects/${id}`,
  );
}

export interface ProjectCreatePayload {
  name_he: string;
  tava_number: string;
  name_en?: string | null;
  address?: string | null;
}

export async function createProject(payload: ProjectCreatePayload): Promise<ProjectOut> {
  return jsonOrThrow<ProjectOut>(
    await fetchOrThrow(`${SIDECAR_BASE}/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
    "POST /projects",
  );
}

export async function patchProject(
  id: number,
  patch: Partial<ProjectCreatePayload>,
): Promise<ProjectOut> {
  return jsonOrThrow<ProjectOut>(
    await fetchOrThrow(`${SIDECAR_BASE}/projects/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
    `PATCH /projects/${id}`,
  );
}

export async function importSchema(schemaFile: File): Promise<ProjectOut> {
  const form = new FormData();
  form.append("schema_file", schemaFile, schemaFile.name);
  return jsonOrThrow<ProjectOut>(
    await fetchOrThrow(`${SIDECAR_BASE}/projects/import-schema`, {
      method: "POST",
      body: form,
    }),
    "POST /projects/import-schema",
  );
}

export async function archiveProject(id: number): Promise<ProjectOut> {
  return jsonOrThrow<ProjectOut>(
    await fetchOrThrow(`${SIDECAR_BASE}/projects/${id}/archive`, { method: "POST" }),
    `POST /projects/${id}/archive`,
  );
}

// ── Submissions ───────────────────────────────────────────────────────────

export async function listSubmissions(projectId: number): Promise<SubmissionOut[]> {
  return jsonOrThrow<SubmissionOut[]>(
    await fetchOrThrow(`${SIDECAR_BASE}/projects/${projectId}/submissions`),
    `GET /projects/${projectId}/submissions`,
  );
}

export async function getSubmission(id: number): Promise<SubmissionOut> {
  return jsonOrThrow<SubmissionOut>(
    await fetchOrThrow(`${SIDECAR_BASE}/submissions/${id}`),
    `GET /submissions/${id}`,
  );
}

export async function uploadSubmission(
  projectId: number,
  versionString: string,
  pdf: File,
  dwg?: File | null,
): Promise<SubmissionOut> {
  const form = new FormData();
  form.append("version_string", versionString);
  form.append("pdf", pdf, pdf.name);
  if (dwg) form.append("dwg", dwg, dwg.name);
  return jsonOrThrow<SubmissionOut>(
    await fetchOrThrow(`${SIDECAR_BASE}/projects/${projectId}/submissions`, {
      method: "POST",
      body: form,
    }),
    `POST /projects/${projectId}/submissions`,
  );
}

export async function runEngine(submissionId: number): Promise<JobOut> {
  return jsonOrThrow<JobOut>(
    await fetchOrThrow(`${SIDECAR_BASE}/submissions/${submissionId}/run-engine`, {
      method: "POST",
    }),
    `POST /submissions/${submissionId}/run-engine`,
  );
}

export async function getFindings(submissionId: number): Promise<unknown> {
  return jsonOrThrow<unknown>(
    await fetchOrThrow(`${SIDECAR_BASE}/submissions/${submissionId}/findings`),
    `GET /submissions/${submissionId}/findings`,
  );
}

// ── Jobs ──────────────────────────────────────────────────────────────────

export async function getJob(id: string): Promise<JobOut> {
  return jsonOrThrow<JobOut>(
    await fetchOrThrow(`${SIDECAR_BASE}/jobs/${id}`),
    `GET /jobs/${id}`,
  );
}

/**
 * Poll a job until it reaches a terminal state. Calls `onUpdate` whenever
 * the status changes (queued → running → completed/failed).
 */
export async function pollJobUntilDone(
  id: string,
  onUpdate: (j: JobOut) => void,
  intervalMs = 1500,
  timeoutMs = 360_000,
): Promise<JobOut> {
  const deadline = Date.now() + timeoutMs;
  let last: JobStatus | null = null;
  while (Date.now() < deadline) {
    const j = await getJob(id);
    if (j.status !== last) {
      onUpdate(j);
      last = j.status;
    }
    if (j.status === "completed" || j.status === "failed") return j;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error(`job ${id} did not reach terminal status within ${timeoutMs}ms`);
}

// ── Phase 2b Module D: discipline comments + render ──────────────────────

export interface DisciplineDef {
  key: string;
  label: string;
}

export interface DisciplinesResponse {
  disciplines: DisciplineDef[];
  statuses: string[];
}

export interface CommentOut {
  id: string;
  submission_id: number;
  discipline_key: string;
  status: string;
  topic_he: string;
  action_he: string;
  author: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface CommentCreatePayload {
  discipline_key: string;
  status: string;
  topic_he: string;
  action_he: string;
}

export type CommentPatchPayload = Partial<CommentCreatePayload>;

export async function listDisciplines(): Promise<DisciplinesResponse> {
  return jsonOrThrow<DisciplinesResponse>(
    await fetchOrThrow(`${SIDECAR_BASE}/disciplines`),
    "GET /disciplines",
  );
}

export async function listComments(submissionId: number): Promise<CommentOut[]> {
  return jsonOrThrow<CommentOut[]>(
    await fetchOrThrow(`${SIDECAR_BASE}/submissions/${submissionId}/comments`),
    `GET /submissions/${submissionId}/comments`,
  );
}

export async function createComment(
  submissionId: number,
  payload: CommentCreatePayload,
): Promise<CommentOut> {
  return jsonOrThrow<CommentOut>(
    await fetchOrThrow(`${SIDECAR_BASE}/submissions/${submissionId}/comments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
    `POST /submissions/${submissionId}/comments`,
  );
}

export async function patchComment(
  submissionId: number,
  commentId: string,
  patch: CommentPatchPayload,
): Promise<CommentOut> {
  return jsonOrThrow<CommentOut>(
    await fetchOrThrow(
      `${SIDECAR_BASE}/submissions/${submissionId}/comments/${commentId}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      },
    ),
    `PATCH /submissions/${submissionId}/comments/${commentId}`,
  );
}

export async function deleteComment(
  submissionId: number,
  commentId: string,
): Promise<void> {
  const res = await fetchOrThrow(
    `${SIDECAR_BASE}/submissions/${submissionId}/comments/${commentId}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    throw new Error(
      `DELETE /submissions/${submissionId}/comments/${commentId} → HTTP ${res.status}`,
    );
  }
}

export async function renderSubmission(submissionId: number): Promise<JobOut> {
  return jsonOrThrow<JobOut>(
    await fetchOrThrow(`${SIDECAR_BASE}/submissions/${submissionId}/render`, {
      method: "POST",
    }),
    `POST /submissions/${submissionId}/render`,
  );
}

export async function exportExcel(submissionId: number): Promise<JobOut> {
  return jsonOrThrow<JobOut>(
    await fetchOrThrow(`${SIDECAR_BASE}/submissions/${submissionId}/export-excel`, {
      method: "POST",
    }),
    `POST /submissions/${submissionId}/export-excel`,
  );
}

/** Convenience URLs for <a href> downloads. The browser handles the
 * file save dialog; we don't need fetch+blob plumbing for this. */
export function reportPdfUrl(submissionId: number, nonce?: number): string {
  const v = nonce ? `?v=${nonce}` : "";
  return `${SIDECAR_BASE}/submissions/${submissionId}/report.pdf${v}`;
}
export function reportXlsxUrl(submissionId: number, nonce?: number): string {
  const v = nonce ? `?v=${nonce}` : "";
  return `${SIDECAR_BASE}/submissions/${submissionId}/report.xlsx${v}`;
}

/** Permanently delete a submission (DB row + dependent rows + on-disk
 * folder + derived audit_outputs). After delete, the same version_string
 * can be uploaded fresh. */
export async function deleteSubmission(submissionId: number): Promise<void> {
  await fetchOrThrow(`${SIDECAR_BASE}/submissions/${submissionId}`, {
    method: "DELETE",
  });
}

/** Open the generated report in the OS default app via the sidecar.
 * Works inside the Tauri webview, where `target="_blank"` does nothing. */
export async function openOutput(submissionId: number, kind: "pdf" | "xlsx"): Promise<void> {
  await fetchOrThrow(
    `${SIDECAR_BASE}/submissions/${submissionId}/open-output?kind=${kind}`,
    { method: "POST" },
  );
}

/** Open the containing folder in the OS file manager (highlights the file). */
export async function revealOutput(submissionId: number, kind: "pdf" | "xlsx"): Promise<void> {
  await fetchOrThrow(
    `${SIDECAR_BASE}/submissions/${submissionId}/reveal-output?kind=${kind}`,
    { method: "POST" },
  );
}

/** Open an external URL in the OS default browser via the sidecar.
 * Used for Mavat links — the Tauri webview ignores target="_blank". */
export async function openUrl(url: string): Promise<void> {
  await fetchOrThrow(
    `${SIDECAR_BASE}/submissions/open-url?url=${encodeURIComponent(url)}`,
    { method: "POST" },
  );
}

export async function setWorkflowStage(
  submissionId: number,
  stage: WorkflowStage,
): Promise<SubmissionOut> {
  return jsonOrThrow<SubmissionOut>(
    await fetchOrThrow(`${SIDECAR_BASE}/submissions/${submissionId}/stage`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage }),
    }),
    "set workflow stage",
  );
}


// ── Settings (Group C2) ───────────────────────────────────────────────────

export interface SettingsOut {
  anthropic_api_key_set: boolean;
}

export interface SettingsPutPayload {
  anthropic_api_key: string;
}

export async function getSettings(): Promise<SettingsOut> {
  return jsonOrThrow<SettingsOut>(
    await fetchOrThrow(`${SIDECAR_BASE}/settings`),
    "GET /settings",
  );
}

export async function putSettings(payload: SettingsPutPayload): Promise<SettingsOut> {
  return jsonOrThrow<SettingsOut>(
    await fetchOrThrow(`${SIDECAR_BASE}/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
    "PUT /settings",
  );
}

// ── Referent PDF extraction (Phase 2b Module D extension) ────────────────

export interface ReferentExtractRow {
  discipline_key: string;
  status: string;
  topic_he: string;
  action_he: string;
}

export interface ReferentExtractResult {
  comments: ReferentExtractRow[];
  raw_text: string;
  used_ai: boolean;
  /** "scan" when the PDF is scanned/image-only and yielded no text. */
  error?: string;
}

export async function extractReferentPdf(
  submissionId: number,
  pdfFile: File,
): Promise<ReferentExtractResult> {
  const form = new FormData();
  form.append("pdf_file", pdfFile, pdfFile.name);
  return jsonOrThrow<ReferentExtractResult>(
    await fetchOrThrow(
      `${SIDECAR_BASE}/submissions/${submissionId}/extract-referent-pdf`,
      { method: "POST", body: form },
    ),
    `POST /submissions/${submissionId}/extract-referent-pdf`,
  );
}

// ── Phase 1 demo: subprocess-isolation echo ──────────────────────────────

export interface EchoResponse {
  job_id: string;
  duration_s: number;
  output: {
    echo: { message: string; extra: unknown };
    worker_info: {
      pid: number; ppid: number;
      python: string; python_version: string; platform: string;
      executed_at: string;
    };
  };
}

export async function postEcho(message: string): Promise<EchoResponse> {
  return jsonOrThrow<EchoResponse>(
    await fetchOrThrow(`${SIDECAR_BASE}/jobs/echo`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    }),
    "/jobs/echo",
  );
}
