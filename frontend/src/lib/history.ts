import type { PricePoint } from "./types";

export const MAX_POINTS = 3600;

/**
 * Append in place, one point per second. Charts need strictly increasing
 * times, so a later tick in the same second replaces the earlier one.
 */
export function appendPoint(points: PricePoint[], time: number, value: number): void {
  const second = Math.floor(time);
  const last = points.at(-1);
  if (last && second <= last.time) {
    last.value = value;
    return;
  }
  points.push({ time: second, value });
  if (points.length > MAX_POINTS) points.shift();
}

/** Snapshots to chart points: ascending, one per second, latest wins. */
export function toSeries(rows: { time: number; value: number }[]): PricePoint[] {
  const points: PricePoint[] = [];
  for (const row of rows) appendPoint(points, row.time, row.value);
  return points;
}
