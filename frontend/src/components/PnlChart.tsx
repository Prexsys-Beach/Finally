"use client";

import { AreaSeries, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { toSeries } from "@/lib/history";
import type { Snapshot } from "@/lib/types";
import { chartOptions } from "./chartOptions";

export function PnlChart({ snapshots }: { snapshots: Snapshot[] }) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Area"> | null>(null);

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

  return (
    <section aria-label="Portfolio value over time" className="flex min-h-56 min-w-0 flex-col border-line xl:border-l">
      <h2 className="px-3 pt-2 pb-1 text-sm font-medium text-muted">Portfolio value over time</h2>
      <div className="relative min-h-0 flex-1">
        <div ref={container} className="absolute inset-0" data-testid="pnl-chart" data-points={points.length} />
        {points.length < 2 && (
          <p className="absolute inset-x-3 top-3 text-sm text-muted">
            Your value is recorded every 30 seconds, so the line appears shortly.
          </p>
        )}
      </div>
    </section>
  );
}
