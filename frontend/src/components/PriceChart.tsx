"use client";

import { createChart, type IChartApi, type ISeriesApi, LineSeries, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { barPoints, bucketStart, hasSynthetic, TIMEFRAME_SECONDS } from "@/lib/bars";
import { formatMoney, formatPercent, trendClass } from "@/lib/format";
import type { IndicatorSeries, PricePoint, PriceUpdate, Timeframe } from "@/lib/types";
import { useBars } from "@/lib/useBars";
import { useStored } from "@/lib/useStored";
import { chartOptions, timeOptions } from "./chartOptions";
import { drawOverlays, isOverlayList, OVERLAYS, type OverlayId } from "./overlays";

/** Live: ticks since page load. The others: stored history, extended by ticks. */
export const RANGES = {
  Live: null,
  "1D": { timeframe: "1m", limit: 1440 },
  "5D": { timeframe: "1m", limit: 7200 },
  "1Y": { timeframe: "1d", limit: 365 },
} as const satisfies Record<string, { timeframe: Timeframe; limit: number } | null>;

export type Range = keyof typeof RANGES;
const DEFAULT_RANGE: Range = "1D";

interface Props {
  ticker: string | null;
  points: PricePoint[] | undefined;
  update: PriceUpdate | undefined;
}

const ANALYTICS_REFRESH_MS = 60000;

/** Indicator series matching the chart's bars, refreshed as new bars close. */
function useIndicators(ticker: string | null, timeframe: Timeframe, limit: number, enabled: boolean) {
  const key = enabled && ticker ? `${ticker}:${timeframe}:${limit}` : null;
  const [loaded, setLoaded] = useState<{ key: string; series: IndicatorSeries | null } | null>(null);

  useEffect(() => {
    if (!key || !ticker) return;
    let cancelled = false;
    const load = () =>
      api.tickerAnalytics(ticker, timeframe, limit).then(
        (result) => !cancelled && setLoaded({ key, series: result.series }),
        () => undefined, // Keep what is shown; the next refresh retries
      );
    void load();
    const timer = setInterval(() => void load(), ANALYTICS_REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [key]); // key covers ticker, timeframe and limit

  return loaded?.key === key ? loaded.series : null;
}

const asChartPoint = (point: PricePoint) => ({
  time: point.time as UTCTimestamp,
  value: point.value,
});

export function PriceChart({ ticker, points, update }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Line"> | null>(null);
  const lastTime = useRef(0);
  const [range, setRange] = useState<Range>(DEFAULT_RANGE);
  const [overlays, setOverlays] = useStored<OverlayId[]>("finally.overlays", [], isOverlayList);

  const history = RANGES[range];
  const bars = useBars(history ? ticker : null, history?.timeframe ?? "1m", history?.limit ?? 0);
  const indicators = useIndicators(
    ticker,
    history?.timeframe ?? "1m",
    history?.limit ?? 0,
    Boolean(history) && overlays.length > 0,
  );

  useEffect(() => {
    if (!chart.current || !indicators || !history) return;
    return drawOverlays(chart.current, indicators, overlays);
  }, [indicators, overlays, history]);

  const toggleOverlay = (id: OverlayId) =>
    setOverlays(overlays.includes(id) ? overlays.filter((o) => o !== id) : [...overlays, id]);

  useEffect(() => {
    if (!container.current) return;
    const created = createChart(container.current, chartOptions);
    chart.current = created;
    series.current = created.addSeries(LineSeries, { color: "#209dd7", lineWidth: 2 });
    return () => {
      created.remove();
      chart.current = null;
      series.current = null;
    };
  }, []);

  useEffect(() => {
    const resolution = !history ? "second" : history.timeframe === "1d" ? "day" : "minute";
    chart.current?.applyOptions(timeOptions(resolution));
  }, [history]);

  // Selecting a ticker or range swaps the whole series; ticks then extend it.
  // Live points grow in place, so only their arrival resets the series.
  const data = history ? (bars ? barPoints(bars) : undefined) : points;
  const dataKey = history ? bars : data === undefined;
  useEffect(() => {
    const chartPoints = (data ?? []).map(asChartPoint);
    series.current?.setData(chartPoints);
    lastTime.current = chartPoints.at(-1)?.time ?? 0;
    chart.current?.timeScale().fitContent();
  }, [ticker, range, dataKey]);

  useEffect(() => {
    let point: PricePoint | undefined;
    if (!history) point = points?.at(-1);
    else if (bars && update) {
      const seconds = TIMEFRAME_SECONDS[history.timeframe];
      point = { time: bucketStart(update.timestamp, seconds), value: update.price };
    }
    if (!point || point.time < lastTime.current) return;
    series.current?.update(asChartPoint(point));
    lastTime.current = point.time;
  }, [points, update]);

  return (
    <>
      <div className="flex items-baseline gap-3 px-3 pt-2 pb-1">
        <h2 className="text-lg font-semibold" data-testid="chart-ticker">
          {ticker ?? "Select a ticker"}
        </h2>
        {update && (
          <>
            <span className="text-lg">{formatMoney(update.price)}</span>
            <span className={`text-sm ${trendClass(update.day_change_percent)}`}>
              {formatPercent(update.day_change_percent)}
            </span>
          </>
        )}
        {history && bars && hasSynthetic(bars) && (
          <span
            className="text-xs text-muted"
            data-testid="synthetic-history"
            title="Before this session's recorded prices, the chart shows made-up history from the simulator's model."
          >
            Includes simulated history
          </span>
        )}
        <div role="group" aria-label="Indicators" className="ml-auto flex self-center text-xs">
          {OVERLAYS.map((overlay) => (
            <button
              key={overlay.id}
              type="button"
              title={history ? overlay.title : "Indicators need a 1D, 5D or 1Y range"}
              disabled={!history}
              aria-pressed={overlays.includes(overlay.id)}
              onClick={() => toggleOverlay(overlay.id)}
              className={`-ml-px flex items-center gap-1 border border-line px-2 py-0.5 first:ml-0 disabled:opacity-40 ${
                overlays.includes(overlay.id) ? "bg-raised text-ink" : "text-muted hover:text-ink"
              }`}
            >
              <span aria-hidden className="size-2 rounded-full" style={{ background: overlay.color }} />
              {overlay.label}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Chart range" className="flex self-center text-xs">
          {(Object.keys(RANGES) as Range[]).map((name) => (
            <button
              key={name}
              type="button"
              aria-pressed={range === name}
              onClick={() => setRange(name)}
              className={`border border-line px-2 py-0.5 -ml-px first:ml-0 ${
                range === name ? "bg-raised text-ink" : "text-muted hover:text-ink"
              }`}
            >
              {name}
            </button>
          ))}
        </div>
      </div>
      <div ref={container} className="min-h-0 flex-1" data-testid="price-chart" />
    </>
  );
}
