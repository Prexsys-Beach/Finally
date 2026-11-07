import { ColorType, type DeepPartial, type ChartOptions, type Time } from "lightweight-charts";

const clock = (time: Time) =>
  new Date((time as number) * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

/** Shared chart styling: recessive grid and axes, local time. */
export const chartOptions: DeepPartial<ChartOptions> = {
  autoSize: true,
  layout: {
    background: { type: ColorType.Solid, color: "#0d1117" },
    textColor: "#94a1b2",
    fontFamily: '"Sofia Sans Semi Condensed Variable", system-ui, sans-serif',
    fontSize: 12,
  },
  grid: { vertLines: { visible: false }, horzLines: { color: "#1c2430" } },
  rightPriceScale: { borderColor: "#2b3543" },
  timeScale: {
    borderColor: "#2b3543",
    timeVisible: true,
    secondsVisible: true,
    tickMarkFormatter: clock,
  },
  localization: { timeFormatter: clock },
};
