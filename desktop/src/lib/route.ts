import type { RouteStop } from "@/api/types";

/** Colours of a route's days (repeating after the last), bright on dark and light maps. */
export const DAY_COLORS = [
  "#f5a524",
  "#38bdf8",
  "#f472b6",
  "#4ade80",
  "#a78bfa",
  "#facc15",
  "#2dd4bf",
] as const;

export function dayColor(day: number): string {
  return DAY_COLORS[(Math.max(day, 1) - 1) % DAY_COLORS.length]!;
}

export interface RouteDay {
  day: number;
  /** Date of the day (from its first stop), "YYYY-MM-DD". */
  date: string;
  /** The day's stops with their position in the route (from 0). */
  stops: { stop: RouteStop; index: number }[];
}

/** The route's stops grouped by the day they start on, in order. */
export function routeDays(stops: RouteStop[]): RouteDay[] {
  const days: RouteDay[] = [];
  stops.forEach((stop, index) => {
    let current = days[days.length - 1];
    if (!current || current.day !== stop.day) {
      current = { day: stop.day, date: stop.start.slice(0, 10), stops: [] };
      days.push(current);
    }
    current.stops.push({ stop, index });
  });
  return days;
}

/**
 * Label of a group of stops (positions from 0) drawn as one marker: their numbers, runs
 * shortened ("1–3, 29"); "…" after the first runs when that is too long for a badge.
 */
export function stopsLabel(indices: number[], maxLength = 9): string {
  const sorted = [...indices].sort((a, b) => a - b);
  const runs: string[] = [];
  for (let i = 0; i < sorted.length;) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j]! + 1) j++;
    runs.push(j === i ? String(sorted[i]! + 1) : `${sorted[i]! + 1}–${sorted[j]! + 1}`);
    i = j + 1;
  }
  let label = runs[0] ?? "";
  for (const run of runs.slice(1)) {
    if (`${label}, ${run}`.length > maxLength) return `${label}…`;
    label = `${label}, ${run}`;
  }
  return label;
}
