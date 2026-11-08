import {
  ColorType,
  type DeepPartial,
  type ChartOptions,
  type Time,
  TickMarkType,
} from "lightweight-charts";

const date = (time: Time) => new Date((time as number) * 1000);

const clock = (time: Time) =>
  date(time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

const dateTime = (time: Time) =>
  date(time).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

const dayOnly = (time: Time) =>
  date(time).toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });

/** Axis labels: dates where the scale crosses a day, local times within one. */
function tickMark(time: Time, type: TickMarkType) {
  const value = date(time);
  switch (type) {
    case TickMarkType.Year:
      return String(value.getFullYear());
    case TickMarkType.Month:
      return value.toLocaleDateString([], { month: "short" });
    case TickMarkType.DayOfMonth:
      return value.toLocaleDateString([], { month: "short", day: "numeric" });
    case TickMarkType.Time:
      return value.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    default:
      return clock(time);
  }
}

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
    tickMarkFormatter: tickMark,
  },
  localization: { timeFormatter: clock },
};

/** Time display for a chart's resolution: seconds, minutes or days. */
export function timeOptions(resolution: "second" | "minute" | "day"): DeepPartial<ChartOptions> {
  const formatter = { second: clock, minute: dateTime, day: dayOnly }[resolution];
  return {
    timeScale: { timeVisible: resolution !== "day", secondsVisible: resolution === "second" },
    localization: { timeFormatter: formatter },
  };
}
