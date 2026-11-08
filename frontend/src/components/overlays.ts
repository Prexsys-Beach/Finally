import {
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  LineSeries,
  LineStyle,
  type SeriesType,
  type UTCTimestamp,
} from "lightweight-charts";
import type { IndicatorSeries } from "@/lib/types";

export type OverlayId = "sma" | "ema" | "bollinger" | "rsi" | "macd";

/**
 * Colors validated together with the price line (#209dd7) against the chart
 * surface for contrast and color-vision separation. RSI and MACD sit in their
 * own panes, so their lines reuse the price blue.
 */
export const OVERLAYS: { id: OverlayId; label: string; color: string; title: string }[] = [
  { id: "sma", label: "SMA", color: "#d95926", title: "Simple moving average, 20 bars" },
  { id: "ema", label: "EMA", color: "#9085e9", title: "Exponential moving average, 50 bars" },
  { id: "bollinger", label: "BB", color: "#c98500", title: "Bollinger Bands: 20-bar average ± 2 standard deviations" },
  { id: "rsi", label: "RSI", color: "#209dd7", title: "Relative Strength Index, 14 bars, in its own pane" },
  { id: "macd", label: "MACD", color: "#209dd7", title: "MACD (12, 26, 9) in its own pane" },
];

const SIGNAL_COLOR = "#d95926";
const GUIDE_COLOR = "#5b6878";
const HISTOGRAM_UP = "rgba(62, 207, 142, 0.45)";
const HISTOGRAM_DOWN = "rgba(255, 123, 114, 0.45)";
const SUB_PANE_HEIGHT = 80;

export const isOverlayList = (value: unknown): value is OverlayId[] =>
  Array.isArray(value) && value.every((v) => OVERLAYS.some((o) => o.id === v));

const color = (id: OverlayId) => OVERLAYS.find((o) => o.id === id)!.color;

function points(series: IndicatorSeries, values: (number | null)[]) {
  return series.time.flatMap((time, i) =>
    values[i] === null ? [] : [{ time: time as UTCTimestamp, value: values[i] as number }],
  );
}

/** Draws the chosen overlays; returns a function that removes them and their panes. */
export function drawOverlays(chart: IChartApi, data: IndicatorSeries, on: OverlayId[]): () => void {
  const added: ISeriesApi<SeriesType>[] = [];
  const line = (values: (number | null)[], options: object, pane = 0) => {
    const series = chart.addSeries(
      LineSeries,
      { lineWidth: 1, priceLineVisible: false, crosshairMarkerVisible: false, ...options },
      pane,
    );
    series.setData(points(data, values));
    added.push(series);
    return series;
  };

  if (on.includes("sma")) line(data.sma_20, { color: color("sma"), title: "SMA 20" });
  if (on.includes("ema")) line(data.ema_50, { color: color("ema"), title: "EMA 50" });
  if (on.includes("bollinger")) {
    const band = { color: color("bollinger"), lineStyle: LineStyle.Dashed, lastValueVisible: false };
    line(data.bollinger_upper, { ...band, title: "BB" });
    line(data.bollinger_lower, band);
  }

  let pane = 1;
  if (on.includes("rsi")) {
    const rsi = line(data.rsi_14, { color: color("rsi"), title: "RSI 14" }, pane);
    for (const level of [70, 30]) {
      rsi.createPriceLine({
        price: level,
        color: GUIDE_COLOR,
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: "",
      });
    }
    pane += 1;
  }
  if (on.includes("macd")) {
    const histogram = chart.addSeries(
      HistogramSeries,
      { priceLineVisible: false, lastValueVisible: false },
      pane,
    );
    histogram.setData(
      data.time.flatMap((time, i) => {
        const value = data.macd_histogram[i];
        return value === null
          ? []
          : [{ time: time as UTCTimestamp, value, color: value >= 0 ? HISTOGRAM_UP : HISTOGRAM_DOWN }];
      }),
    );
    added.push(histogram);
    line(data.macd, { color: color("macd"), title: "MACD" }, pane);
    line(data.macd_signal, { color: SIGNAL_COLOR, title: "Signal" }, pane);
  }
  // Size the panes once they are laid out: each indicator pane gets a fixed
  // height and the price pane the rest. Sizing is cosmetic, so it never throws.
  const frame = requestAnimationFrame(() => {
    try {
      const panes = chart.panes();
      if (panes.length < 2) return;
      const total = panes.reduce((sum, pane) => sum + pane.getHeight(), 0);
      const sub = Math.min(SUB_PANE_HEIGHT, Math.floor(total / (panes.length + 1)));
      panes[0].setHeight(total - sub * (panes.length - 1));
      panes.slice(1).forEach((pane) => pane.setHeight(sub));
    } catch {
      // Keep the library's default sizes
    }
  });

  return () => {
    cancelAnimationFrame(frame);
    for (const series of added) chart.removeSeries(series);
    for (let i = chart.panes().length - 1; i >= 1; i -= 1) chart.removePane(i);
  };
}
