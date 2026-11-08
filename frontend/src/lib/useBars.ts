"use client";

import { useEffect, useRef, useState } from "react";
import { barPoints, extendLive, loadBars, TIMEFRAME_SECONDS } from "./bars";
import type { Bar, PricePoint, PriceUpdate, Timeframe } from "./types";

/** Bars for one ticker, or undefined until they arrive (or with no ticker). */
export function useBars(ticker: string | null, timeframe: Timeframe, limit: number) {
  const key = ticker ? `${ticker}:${timeframe}:${limit}` : null;
  const [loaded, setLoaded] = useState<{ key: string; bars: Bar[] } | null>(null);

  useEffect(() => {
    if (!ticker || !key) return;
    return loadBars(ticker, timeframe, limit, (bars) => setLoaded({ key, bars }));
  }, [key]); // key covers ticker, timeframe and limit

  return loaded?.key === key ? loaded.bars : undefined;
}

const SPARK_TIMEFRAME: Timeframe = "1m";
export const SPARK_POINTS = 60;

/** The last hour of one-minute closes per ticker, kept current by live prices. */
export function useSparklines(tickers: string[], prices: Record<string, PriceUpdate>) {
  const series = useRef<Record<string, PricePoint[]>>({});
  const [, setVersion] = useState(0);
  const tickerKey = tickers.join(",");

  useEffect(() => {
    const cancels = tickerKey
      .split(",")
      .filter(Boolean)
      .map((ticker) =>
        loadBars(ticker, SPARK_TIMEFRAME, SPARK_POINTS, (bars) => {
          const points = barPoints(bars);
          const current = series.current[ticker] ?? [];
          // Keep live points newer than what the server has written so far
          for (const point of current) {
            extendLive(points, point.time, point.value, TIMEFRAME_SECONDS[SPARK_TIMEFRAME]);
          }
          series.current[ticker] = points.slice(-SPARK_POINTS);
          setVersion((version) => version + 1);
        }),
      );
    return () => cancels.forEach((cancel) => cancel());
  }, [tickerKey]);

  useEffect(() => {
    for (const update of Object.values(prices)) {
      const points = (series.current[update.ticker] ??= []);
      extendLive(points, update.timestamp, update.price, TIMEFRAME_SECONDS[SPARK_TIMEFRAME], SPARK_POINTS);
    }
  }, [prices]);

  return series.current;
}
