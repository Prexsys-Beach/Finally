"use client";

import {
  AreaSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  LineSeries,
  LineStyle,
  type SeriesType,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { toSeries } from "@/lib/history";
import type { Forecast, ForecastHorizon, Snapshot } from "@/lib/types";
import { useStored } from "@/lib/useStored";
import { chartOptions, timeOptions } from "./chartOptions";

const HORIZONS: ForecastHorizon[] = ["1h", "1d", "1w"];
const isHorizon = (value: unknown): value is ForecastHorizon | null =>
  value === null || HORIZONS.includes(value as ForecastHorizon);
const FORECAST_REFRESH_MS = 60000;

// Amber, validated with the chart's blue against the surface. Inner band
// dashed, outer band dotted, so the bands read without relying on color.
const FAN_COLOR = "#c98500";
const FAN_LINES = [
  { band: "p95", title: "95%", style: LineStyle.Dotted },
  { band: "p75", title: "75%", style: LineStyle.Dashed },
  { band: "p50", title: "median", style: LineStyle.Solid },
  { band: "p25", title: "25%", style: LineStyle.Dashed },
  { band: "p5", title: "5%", style: LineStyle.Dotted },
] as const;

/** The portfolio forecast for a horizon, refreshed each minute and after trades. */
function useForecast(horizon: ForecastHorizon | null, positionsKey: string) {
  const [forecast, setForecast] = useState<Forecast | null>(null);
  useEffect(() => {
    setForecast(null);
    if (!horizon) return;
    let cancelled = false;
    const load = () =>
      api.forecast("portfolio", horizon).then(
        (result) => !cancelled && setForecast(result),
        () => undefined, // Keep what is shown; the next refresh retries
      );
    void load();
    const timer = setInterval(() => void load(), FORECAST_REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [horizon, positionsKey]);
  return forecast;
}

/** One line: the 90% range at the horizon and the chance of ending lower. */
export function forecastSummary(forecast: Forecast): string {
  const end = (band: keyof Forecast["bands"]) => forecast.bands[band].at(-1) ?? forecast.current_value;
  if (forecast.notes.length > 0 && end("p5") === end("p95")) return forecast.notes.join(" ");
  const loss = Math.round(forecast.probability_of_loss * 100);
  return `${forecast.horizon_label}: 90% between ${formatMoney(end("p5"))} and ${formatMoney(end("p95"))} · median ${formatMoney(end("p50"))} · ${loss}% chance of a loss`;
}

interface Props {
  snapshots: Snapshot[];
  /** Changes when positions change, so the forecast reloads after a trade. */
  positionsKey?: string;
}

export function PnlChart({ snapshots, positionsKey = "" }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Area"> | null>(null);
  const [horizon, setHorizon] = useStored<ForecastHorizon | null>("finally.forecast", null, isHorizon);
  const forecast = useForecast(horizon, positionsKey);

  useEffect(() => {
    if (!container.current) return;
    const created = createChart(container.current, chartOptions);
    chart.current = created;
    series.current = created.addSeries(AreaSeries, {
      lineColor: "#209dd7",
      lineWidth: 2,
      topColor: "rgba(32, 157, 215, 0.22)",
      bottomColor: "rgba(32, 157, 215, 0.02)",
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    return () => {
      created.remove();
      chart.current = null;
      series.current = null;
    };
  }, []);

  const points = toSeries(
    snapshots.map((snapshot) => ({
      time: Date.parse(snapshot.recorded_at) / 1000,
      value: snapshot.total_value,
    })),
  );

  useEffect(() => {
    series.current?.setData(
      points.map((point) => ({ time: point.time as UTCTimestamp, value: point.value })),
    );
  }, [snapshots]);

  // Only on a new point, so the regular refresh doesn't undo a user's zoom
  useEffect(() => {
    chart.current?.timeScale().fitContent();
  }, [points.length]);

  // The fan starts at today's value and opens out to the horizon
  useEffect(() => {
    const target = chart.current;
    if (!target) return;
    target.applyOptions(timeOptions(forecast && forecast.horizon !== "1h" ? "minute" : "second"));
    if (!forecast) return;
    const added: ISeriesApi<SeriesType>[] = FAN_LINES.map(({ band, title, style }) => {
      const line = target.addSeries(LineSeries, {
        color: FAN_COLOR,
        lineWidth: band === "p50" ? 2 : 1,
        lineStyle: style,
        title,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      });
      line.setData([
        { time: forecast.as_of as UTCTimestamp, value: forecast.current_value },
        ...forecast.times.map((time, i) => ({ time: time as UTCTimestamp, value: forecast.bands[band][i] })),
      ]);
      return line;
    });
    target.timeScale().fitContent();
    return () => added.forEach((line) => target.removeSeries(line));
  }, [forecast]);

  return (
    <section aria-label="Portfolio value over time" className="flex min-h-56 min-w-0 flex-col border-line xl:border-l">
      <div className="flex items-center gap-3 px-3 pt-2 pb-1">
        <h2 className="text-sm font-medium text-muted">Portfolio value over time</h2>
        <div role="group" aria-label="Forecast" className="ml-auto flex items-center text-xs">
          <span className="mr-1.5 text-muted">Forecast</span>
          {HORIZONS.map((name) => (
            <button
              key={name}
              type="button"
              aria-pressed={horizon === name}
              title={`Monte Carlo range for the next ${name === "1h" ? "hour" : name === "1d" ? "day" : "week"}. Click again to hide.`}
              onClick={() => setHorizon(horizon === name ? null : name)}
              className={`-ml-px border border-line px-2 py-0.5 first:ml-0 ${
                horizon === name ? "bg-raised text-ink" : "text-muted hover:text-ink"
              }`}
            >
              {name}
            </button>
          ))}
        </div>
      </div>
      {forecast && (
        <p className="truncate px-3 pb-1 text-xs text-muted" data-testid="forecast-summary" title={forecastSummary(forecast)}>
          {forecastSummary(forecast)}
        </p>
      )}
      <div className="relative min-h-0 flex-1">
        <div ref={container} className="absolute inset-0" data-testid="pnl-chart" data-points={points.length} />
        {points.length < 2 && !forecast && (
          <p className="absolute inset-x-3 top-3 text-sm text-muted">
            Your value is recorded every 30 seconds, so the line appears shortly.
          </p>
        )}
      </div>
    </section>
  );
}
