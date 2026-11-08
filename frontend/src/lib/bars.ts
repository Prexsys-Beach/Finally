import { api } from "./api";
import type { Bar, PricePoint, Timeframe } from "./types";

export const TIMEFRAME_SECONDS: Record<Timeframe, number> = { "1m": 60, "1d": 86400 };

/** Start of the UTC bucket containing the time, matching the server's bars. */
export const bucketStart = (time: number, seconds: number) => Math.floor(time / seconds) * seconds;

/** Closing prices, one point per bar. */
export const barPoints = (bars: Bar[]): PricePoint[] =>
  bars.map((bar) => ({ time: bar.time, value: bar.close }));

export const hasSynthetic = (bars: Bar[]) => bars.some((bar) => bar.origin === "synthetic");

/**
 * Extend in place with a live price: it updates the bucket it falls in, or starts
 * the next one. A time before the last bucket is ignored.
 */
export function extendLive(
  points: PricePoint[],
  time: number,
  value: number,
  seconds: number,
  max = Infinity,
): void {
  const start = bucketStart(time, seconds);
  const last = points.at(-1);
  if (last && start < last.time) return;
  if (last && start === last.time) {
    last.value = value;
    return;
  }
  points.push({ time: start, value });
  if (points.length > max) points.shift();
}

const RETRY_MS = 5000;
const MAX_TRIES = 12;
const FILLED = 10;

/**
 * Load bars, and keep retrying while there are only a few: right after the app
 * starts, history is still being backfilled. Returns a cancel function.
 */
export function loadBars(
  ticker: string,
  timeframe: Timeframe,
  limit: number,
  onBars: (bars: Bar[]) => void,
): () => void {
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let tries = 0;
  const retry = () => {
    tries += 1;
    if (!cancelled && tries < MAX_TRIES) timer = setTimeout(() => void load(), RETRY_MS);
  };
  const load = async () => {
    try {
      const bars = await api.bars(ticker, timeframe, limit);
      if (cancelled) return;
      onBars(bars);
      if (bars.length < Math.min(FILLED, limit)) retry();
    } catch {
      retry();
    }
  };
  void load();
  return () => {
    cancelled = true;
    clearTimeout(timer);
  };
}
