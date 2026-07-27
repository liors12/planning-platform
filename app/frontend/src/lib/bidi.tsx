/**
 * Bidi isolation for LTR technical tokens in Hebrew guideline text.
 *
 * Hebrew text carries Latin/numeric tokens the architect must copy exactly -
 * CAD layer names, file sizes, standard numbers, filenames. Inside an RTL
 * paragraph the Unicode bidi algorithm reorders some of them: "0_LOTS"
 * displays as "LOTS_0" and "100 MB" as "MB 100". The stored text is correct;
 * only the display is wrong. An architect copying a layer name off the screen
 * types the wrong string.
 *
 * TWO IMPLEMENTATIONS, ONE RULE. This is the TypeScript half; the PDFs use
 * compliance_engine/report_chrome.py:isolate_ltr. They are kept in step by
 * tests/test_bidi_isolation.py, which feeds both the same fixture list and
 * asserts identical segmentation. Change one, change the other, or that
 * test goes red.
 */
import React from "react";

const CONNECTORS = "_.:+-/×";
const TRIM = " \t,;()[]“”’\"'״׳.!?·";

const isHebrew = (c: string) => c >= "֐" && c <= "׿";
const isAsciiAlnum = (c: string) => /[A-Za-z0-9]/.test(c);

/** A word of ASCII alnum and connectors only: 100, MB, 0_LOTS, "-". */
function asciiTok(w: string): boolean {
  return w.length > 0 && [...w].every((c) => isAsciiAlnum(c) || CONNECTORS.includes(c));
}

/**
 * A FILENAME mixing Hebrew with ASCII - 407-1048248_הטייסים_24.3.pdf.
 * Deliberately narrow: it must carry a dot-extension. A Hebrew identifier
 * like תא_שטח_X renders correctly today and must not be forced to LTR.
 */
function mixedToken(w: string): boolean {
  return (
    [...w].some(isHebrew) &&
    /\.[A-Za-z0-9]{2,4}$/.test(w) &&
    [...w].some(isAsciiAlnum)
  );
}

/** Character spans to isolate, as [start, end) over `text`. */
export function ltrRuns(text: string): [number, number][] {
  const spans: [number, number, boolean][] = [];
  let i = 0;
  const n = text.length;
  while (i < n) {
    if (/\s/.test(text[i])) { i++; continue; }
    let j = i;
    while (j < n && !/\s/.test(text[j])) j++;
    let ws = i, we = j;
    while (ws < we && TRIM.includes(text[ws])) ws++;
    while (we > ws && TRIM.includes(text[we - 1])) we--;
    const core = text.slice(ws, we);
    if (core && (asciiTok(core) || mixedToken(core))) {
      const prev = spans[spans.length - 1];
      const gap = prev ? text.slice(prev[1], ws) : "";
      if (prev && asciiTok(core) && prev[2] && gap !== "" && gap.trim() === "") {
        prev[1] = we;
      } else {
        spans.push([ws, we, asciiTok(core)]);
      }
    }
    i = j;
  }
  return spans
    .filter(([a, b]) => [...text.slice(a, b)].some(isAsciiAlnum))
    .map(([a, b]) => [a, b] as [number, number]);
}

/**
 * Render `text` with each LTR technical run wrapped in a bidi isolate.
 * Returns React nodes, so callers keep using {} interpolation - no
 * dangerouslySetInnerHTML anywhere near guideline content.
 */
export function IsolateLtr({ text }: { text: string }): React.ReactElement {
  const runs = ltrRuns(text);
  if (runs.length === 0) return <>{text}</>;
  const out: React.ReactNode[] = [];
  let last = 0;
  runs.forEach(([a, b], k) => {
    if (a > last) out.push(text.slice(last, a));
    out.push(
      <bdi dir="ltr" key={k}>
        {text.slice(a, b)}
      </bdi>,
    );
    last = b;
  });
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}
