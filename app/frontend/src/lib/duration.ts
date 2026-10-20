// Time since a date, in the Hebrew Ellen reads on the overview tab (v0.2.3).
// Under a year: "X חודשים". A year or more: "X שנים ו-Y חודשים". Singular and
// dual forms are the ones Hebrew uses - "שנה", "שנתיים", "חודש", "חודשיים" -
// so 14 months reads "שנה ו-2 חודשים", not "1 שנים ו-2 חודשים".

function years(n: number): string {
  if (n === 1) return "שנה";
  if (n === 2) return "שנתיים";
  return `${n} שנים`;
}

function months(n: number): string {
  if (n === 1) return "חודש";
  if (n === 2) return "חודשיים";
  return `${n} חודשים`;
}

/** Whole calendar months from `fromIso` (YYYY-MM-DD) to `today`. */
export function monthsBetween(fromIso: string, today: Date): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(fromIso);
  if (!m) return null;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  let total = (today.getFullYear() - y) * 12 + (today.getMonth() + 1 - mo);
  if (today.getDate() < d) total -= 1;   // the month is not complete yet
  return total;
}

/** "שנה ו-2 חודשים", "5 חודשים", "פחות מחודש"; null for a bad or future date. */
export function timeSince(fromIso: string, today: Date = new Date()): string | null {
  const total = monthsBetween(fromIso, today);
  if (total === null || total < 0) return null;
  if (total === 0) return "פחות מחודש";
  const y = Math.floor(total / 12);
  const mo = total % 12;
  if (y === 0) return months(mo);
  if (mo === 0) return years(y);
  // "ו-" before a digit ("ו-3 חודשים"), attached before a word ("וחודשיים").
  return mo <= 2 ? `${years(y)} ו${months(mo)}` : `${years(y)} ו-${months(mo)}`;
}

/** 2025-08-06 -> 06.08.2025, the date form used across the app. */
export function displayDate(iso: string): string {
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}
