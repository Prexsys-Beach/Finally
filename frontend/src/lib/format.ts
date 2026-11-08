const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const quantity = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });

export const formatMoney = (value: number | null) =>
  value === null ? "–" : money.format(value);

export const formatQuantity = (value: number) => quantity.format(value);

/** Rounded as displayed, so a sign or color never sits on a value shown as zero. */
const shown = (value: number) => Math.round(value * 100) / 100;

const sign = (value: number) => (shown(value) > 0 ? "+" : shown(value) < 0 ? "−" : "");

export const formatSignedMoney = (value: number | null) =>
  value === null ? "–" : `${sign(value)}${money.format(Math.abs(value))}`;

export const formatPercent = (value: number | null) =>
  value === null ? "–" : `${sign(value)}${Math.abs(value).toFixed(2)}%`;

export const trendClass = (value: number | null) =>
  !value || !shown(value) ? "text-muted" : value > 0 ? "text-up" : "text-down";

/** A prediction horizon: "30 min", "2 h", "1.5 h", "3 d". */
export function formatHorizon(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 1440) {
    const hours = minutes / 60;
    return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} h`;
  }
  const days = minutes / 1440;
  return `${Number.isInteger(days) ? days : days.toFixed(1)} d`;
}
