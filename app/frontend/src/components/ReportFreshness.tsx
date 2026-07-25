import type { SubmissionOut } from "../api";

/** Round-2 addendum 5: report-freshness awareness next to the report
 * buttons (both tabs). Never disables anything - regeneration stays
 * legitimate (lost file, fresh copy); this only tells Ellen whether a new
 * run would add anything. */
export function ReportFreshness({ sub }: { sub: SubmissionOut | null }) {
  if (!sub?.report_generated_at) return null;
  const when = sub.report_generated_at.replace("T", " ").slice(0, 16);
  return (
    <div className="report-freshness" data-testid="report-freshness">
      <span className="muted">דו"ח אחרון הופק: <span dir="ltr">{when}</span></span>
      {sub.report_changes_since === false && (
        <span className="muted report-fresh-hint">
          לא נוספו שינויים מאז הדו"ח האחרון
        </span>
      )}
      {sub.report_changes_since === true && (
        <span className="report-stale-hint">
          נוספו שינויים מאז הדו"ח האחרון - מומלץ להפיק מחדש
        </span>
      )}
    </div>
  );
}
