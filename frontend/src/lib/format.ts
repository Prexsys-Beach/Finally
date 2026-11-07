const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const quantity = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });

export const formatMoney = (value: number | null) =>
  value === null ? "–" : money.format(value);

export const formatQuantity = (value: number) => quantity.format(value);

const sign = (value: number) => (value > 0 ? "+" : value < 0 ? "−" : "");

export const formatSignedMoney = (value: number | null) =>
  value === null ? "–" : `${sign(value)}${money.format(Math.abs(value))}`;

export const formatPercent = (value: number | null) =>
  value === null ? "–" : `${sign(value)}${Math.abs(value).toFixed(2)}%`;

export const trendClass = (value: number | null) =>
  !value ? "text-muted" : value > 0 ? "text-up" : "text-down";
