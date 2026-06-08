import { useEffect, useState } from "react";
import { getFindings, getJob, pollJobUntilDone, type JobOut, type JobStatus } from "../api";
import { FindingsView } from "./FindingsView";

interface Props {
  jobId: string;
  submissionId: number;
  projectId: number;
  onTerminal: (j: JobOut) => void;
}

const STATUS_LABEL_HE: Record<JobStatus, string> = {
  queued: "ממתין בתור",
  running: "רץ כעת",
  completed: "הסתיים בהצלחה",
  failed: "נכשל",
};

const STATUS_CLASS: Record<JobStatus, string> = {
  queued: "s-queued",
  running: "s-running",
  completed: "s-completed",
  failed: "s-failed",
};

export function EngineStatus({ jobId, submissionId, projectId, onTerminal }: Props) {
  const [job, setJob] = useState<JobOut | null>(null);
  const [findings, setFindings] = useState<unknown | null>(null);
  const [findingsErr, setFindingsErr] = useState<string | null>(null);

  // First fetch + start polling.
  useEffect(() => {
    let cancelled = false;
    getJob(jobId)
      .then((j) => { if (!cancelled) setJob(j); })
      .catch((e) => { if (!cancelled) console.error(e); });

    pollJobUntilDone(jobId, (j) => {
      if (cancelled) return;
      setJob(j);
    })
      .then((terminal) => {
        if (cancelled) return;
        setJob(terminal);
        onTerminal(terminal);
        if (terminal.status === "completed") {
          getFindings(submissionId)
            .then((data) => { if (!cancelled) setFindings(data); })
            .catch((e) => { if (!cancelled) setFindingsErr(String(e)); });
        }
      })
      .catch((e) => {
        if (!cancelled) {
          console.error(e);
          setFindingsErr(String(e));
        }
      });

    return () => { cancelled = true; };
  }, [jobId, submissionId]);

  if (!job) return <div className="muted">טוען סטטוס...</div>;

  // Parse error JSON for friendlier display
  let parsedError: any = null;
  if (job.status === "failed" && job.error) {
    try { parsedError = JSON.parse(job.error); } catch { parsedError = { error_message: job.error }; }
  }

  return (
    <div className="engine-status">
      <header className="engine-status-header">
        <div>
          <div className="status-line">
            <span className={"status-badge " + STATUS_CLASS[job.status]}>
              {STATUS_LABEL_HE[job.status]}
            </span>
            <span className="muted">Job {job.id.slice(0, 8)}…</span>
          </div>
          <div className="muted">
            {job.queued_at && `הוכנס לתור: ${job.queued_at.replace("T", " ").slice(0, 19)}`}
            {job.completed_at && (
              <>{" · "}הסתיים: {job.completed_at.replace("T", " ").slice(0, 19)}</>
            )}
          </div>
        </div>
      </header>

      {job.status === "queued" && (
        <p className="muted">המנוע יתחיל ברגע ש-worker יתפנה (MAX_CONCURRENT_JOBS=1).</p>
      )}
      {job.status === "running" && (
        <p className="muted">
          המנוע רץ ב-subprocess מבודד לפי ADR-001 — לוקח כ-60-90 שניות לתב"ע 407-1048248.
        </p>
      )}

      {job.status === "failed" && parsedError && (
        <div className="error error-block">
          <strong>שגיאה: </strong>
          {parsedError.error_type && <code dir="ltr">{parsedError.error_type}</code>}
          <div className="error-message">{parsedError.error_message}</div>
          {parsedError.stderr_tail && (
            <details>
              <summary>stderr (פלט שגיאה של המנוע)</summary>
              <pre dir="ltr">{parsedError.stderr_tail}</pre>
            </details>
          )}
        </div>
      )}

      {findingsErr && <div className="error">{findingsErr}</div>}

      {findings !== null && <FindingsView findings={findings} projectId={projectId} />}
    </div>
  );
}
