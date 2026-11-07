"use client";

import { createChart, type IChartApi, type ISeriesApi, LineSeries, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { formatMoney, formatPercent, trendClass } from "@/lib/format";
import type { PricePoint, PriceUpdate } from "@/lib/types";
import { chartOptions } from "./chartOptions";

interface Props {
  ticker: string | null;
  points: PricePoint[] | undefined;
  update: PriceUpdate | undefined;
}

const asChartPoint = (point: PricePoint) => ({
  time: point.time as UTCTimestamp,
  value: point.value,
});

export function PriceChart({ ticker, points, update }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Line"> | null>(null);

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

  // Selecting a ticker swaps the whole series; ticks then extend it
  useEffect(() => {
    series.current?.setData((points ?? []).map(asChartPoint));
    chart.current?.timeScale().fitContent();
  }, [ticker, points === undefined]);

  useEffect(() => {
    const last = points?.at(-1);
    if (last) series.current?.update(asChartPoint(last));
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
      </div>
      <div ref={container} className="min-h-0 flex-1" data-testid="price-chart" />
    </>
  );
}
