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
