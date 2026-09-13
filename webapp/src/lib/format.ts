/**
 * Formatting helpers. Numbers use tabular figures in the UI (via CSS); these
 * just produce the strings.
 *
 * Timestamps are parsed by string, not `new Date(iso)`, on purpose: the backend
 * emits wall-clock times and we want to show exactly those digits regardless of
 * the viewer's timezone. Lead time ("+6 h") is derived from the hour index, not
 * the clock, so no timezone math is ever needed for correctness.
 */

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

interface TsParts {
  y: number;
  mo: number;
  d: number;
  hh: string;
  mm: string;
}

function parseTs(iso: string): TsParts | null {
  const m = iso.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  if (!m) return null;
  return { y: +m[1], mo: +m[2], d: +m[3], hh: m[4], mm: m[5] };
}

/** "14:00" */
export function clock(iso: string): string {
  const p = parseTs(iso);
  return p ? `${p.hh}:${p.mm}` : "—";
}

/** "Sat 14:00" — weekday is timezone-invariant for a calendar date. */
export function dayClock(iso: string): string {
  const p = parseTs(iso);
  if (!p) return "—";
  const wd = WEEKDAYS[new Date(Date.UTC(p.y, p.mo - 1, p.d)).getUTCDay()];
  return `${wd} ${p.hh}:${p.mm}`;
}

/** "2026-08-23 14:32" for the instrument-rail generated-at stamp. */
export function stamp(iso: string): string {
  const p = parseTs(iso);
  if (!p) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${p.y}-${pad(p.mo)}-${pad(p.d)} ${p.hh}:${p.mm}`;
}

/** Nearest integer, no separators (AQI/sub-indices are 0–500). */
export function int(n: number | null | undefined): string {
  return n == null || Number.isNaN(n) ? "—" : String(Math.round(n));
}

/** Fixed decimals. */
export function fixed(n: number | null | undefined, digits = 1): string {
  return n == null || Number.isNaN(n) ? "—" : n.toFixed(digits);
}

/** Fixed decimals with an explicit sign, e.g. "+2.4", "−1.8" (true minus sign). */
export function signed(n: number | null | undefined, digits = 1): string {
  if (n == null || Number.isNaN(n)) return "—";
  const s = Math.abs(n).toFixed(digits);
  if (n > 0) return `+${s}`;
  if (n < 0) return `−${s}`; // U+2212 minus, aligns better than hyphen
  return s;
}

/** Percent to given decimals, e.g. "23.1%". */
export function pct(n: number | null | undefined, digits = 1): string {
  return n == null || Number.isNaN(n) ? "—" : `${n.toFixed(digits)}%`;
}

const COMPASS = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
] as const;

/** 16-point compass label for a meteorological direction (degrees FROM). */
export function compass(deg: number): string {
  const i = Math.round((((deg % 360) + 360) % 360) / 22.5) % 16;
  return COMPASS[i];
}

/** Lead-time label from an hour offset: "now" at 0, "+6 h" otherwise. */
export function leadLabel(hours: number): string {
  return hours <= 0 ? "now" : `+${hours} h`;
}
