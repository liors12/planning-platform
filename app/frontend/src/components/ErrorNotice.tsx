// Shared user-facing error display (first-look round 1, item 8).
//
// Ellen must never see raw API errors ("Error: GET /x → HTTP 409: {json}").
// Every fetch/API error rendering routes through this component: a Hebrew
// title, a one-line explanation, optional numbered "מה לעשות" steps, and a
// collapsible "פרטים טכניים" section holding the raw error for support.

interface Props {
  /** The raw error (String(e) from api.ts fetchOrThrow) - shown only inside פרטים טכניים. */
  error: string;
  title?: string;
  explanation?: string;
  steps?: string[];
  /** Compact style for inline placements (no block padding). */
  compact?: boolean;
}

export function ErrorNotice({ error, title, explanation, steps, compact }: Props) {
  return (
    <div className={"error-notice" + (compact ? " error-notice-compact" : "")}
         role="alert" data-testid="error-notice">
      <div className="error-notice-title">{title ?? "אירעה תקלה"}</div>
      <p className="error-notice-body">
        {explanation ?? "הפעולה לא הושלמה. נסי שוב בעוד רגע; אם התקלה חוזרת, פני לתמיכה."}
      </p>
      {steps && steps.length > 0 && (
        <>
          <div className="error-notice-steps-title">מה לעשות:</div>
          <ol className="error-notice-steps">
            {steps.map((s, i) => <li key={i}>{s}</li>)}
          </ol>
        </>
      )}
      <details className="error-notice-details">
        <summary>פרטים טכניים</summary>
        <pre dir="ltr">{error}</pre>
      </details>
    </div>
  );
}

/** Heuristic router: technical-looking errors (raw fetch/API strings) render
 * as the full ErrorNotice; already-friendly Hebrew validation messages keep
 * the plain inline error style. */
export function MaybeApiError({ error, title }: { error: string; title?: string }) {
  const technical = /HTTP \d|→|Error:|TypeError|fetch|\{"detail"/.test(error);
  if (!technical) return <div className="error">{error}</div>;
  return <ErrorNotice error={error} title={title} compact />;
}
