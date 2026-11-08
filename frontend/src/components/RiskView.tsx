"use client";

import { type ReactNode, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import type { MoneyFigure, PortfolioAnalytics } from "@/lib/types";

const REFRESH_MS = 30000;

const percent = (fraction: number | null | undefined, digits = 1) =>
  fraction === null || fraction === undefined ? "–" : `${(fraction * 100).toFixed(digits)}%`;

const number = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined ? "–" : value.toFixed(digits);

const loss = (figure: MoneyFigure | null | undefined) =>
  figure ? `${formatMoney(figure.amount)} · ${figure.percent.toFixed(2)}%` : "–";

/** Diverging scale for correlation: blue below zero, orange above, gray at zero. */
export function correlationColor(value: number | null): string {
  if (value === null) return "var(--color-tile-flat)";
  const strength = Math.round(Math.min(Math.abs(value), 1) * 100);
  const pole = value > 0 ? "#d95926" : "#3987e5";
  return `color-mix(in oklab, ${pole} ${strength}%, var(--color-tile-flat))`;
}

function Figure({ label, value, detail, title }: { label: string; value: string; detail?: string; title: string }) {
  return (
    <div title={title} className="min-w-0">
      <div className="truncate text-xs text-muted">{label}</div>
      <div className="truncate font-medium">{value}</div>
      {detail && <div className="truncate text-xs text-muted">{detail}</div>}
    </div>
  );
}

function CorrelationGrid({ tickers, matrix }: { tickers: string[]; matrix: (number | null)[][] }) {
  return (
    <div
      role="table"
      aria-label="Correlation of daily returns"
      data-testid="correlation-matrix"
      className="grid gap-px text-[10px] leading-none"
      style={{ gridTemplateColumns: `auto repeat(${tickers.length}, minmax(0, 1fr))` }}
    >
      <div role="row" className="contents">
        <span role="columnheader" />
        {tickers.map((ticker) => (
          <span role="columnheader" key={ticker} className="truncate pb-0.5 text-center text-muted">
            {ticker}
          </span>
        ))}
      </div>
      {tickers.map((row, i) => (
        <div role="row" key={row} className="contents">
          <span role="rowheader" className="pr-1 text-right text-muted">
            {row}
          </span>
          {tickers.map((column, j) => {
            const value = matrix[i][j];
            return (
              <span
                role="cell"
                key={column}
                title={`${row} / ${column}: ${number(value)}`}
                className="py-1 text-center text-[#f2f5f8] tabular-nums"
                style={{ background: i === j ? "var(--color-raised)" : correlationColor(value) }}
              >
                {i === j ? "" : number(value, 1).replace("0.", ".")}
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
}

interface Props {
  heading: ReactNode;
  /** Changes when positions change, so the figures reload after a trade. */
  positionsKey: string;
}

export function RiskView({ heading, positionsKey }: Props) {
  const [data, setData] = useState<PortfolioAnalytics | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api.portfolioAnalytics("1d").then(
        (result) => {
          if (cancelled) return;
          setData(result);
          setFailed(false);
        },
        () => !cancelled && setFailed(true),
      );
    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [positionsKey]);

  const synthetic = (data?.origins.synthetic ?? 0) > 0;
  const top = data?.concentration?.top;
  const performance = data?.performance;

  return (
    <section aria-label="Portfolio risk" className="flex min-h-56 min-w-0 flex-col">
      {heading}
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-2 text-sm" data-testid="risk-view">
        {!data && (
          <p className="py-2 text-muted">{failed ? "Couldn't load risk figures. Retrying." : "Loading risk…"}</p>
        )}
        {data && (
          <>
            {!data.concentration && <p className="py-1 text-muted">{data.notes.join(" ")}</p>}
            {data.concentration && (
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
                <Figure
                  label="Volatility"
                  value={percent(data.volatility)}
                  detail="annualized"
                  title="Standard deviation of the portfolio's daily returns, scaled to a year. Cash counts as riskless."
                />
                <Figure
                  label="Beta"
                  value={number(data.beta)}
                  detail="vs watchlist"
                  title={`How much the portfolio moves with the market. Benchmark: ${data.benchmark}.`}
                />
                <Figure
                  label="1-day VaR 95%"
                  value={loss(data.value_at_risk?.historical)}
                  detail={`normal ${formatMoney(data.value_at_risk?.parametric?.amount ?? null)}`}
                  title="On 1 trading day in 20, expect to lose at least this much. From past returns; the second figure assumes normal returns."
                />
                <Figure
                  label="Expected shortfall"
                  value={loss(data.expected_shortfall?.historical)}
                  detail={`normal ${formatMoney(data.expected_shortfall?.parametric?.amount ?? null)}`}
                  title="The average loss on those worst 1 in 20 days."
                />
                <Figure
                  label="Largest position"
                  value={top ? `${top.ticker} ${percent(top.weight)}` : "–"}
                  detail={`cash ${percent(data.cash_weight)}`}
                  title="Share of total portfolio value, cash included."
                />
                <Figure
                  label="Effective positions"
                  value={number(data.concentration?.effective_positions, 1)}
                  detail={`HHI ${number(data.concentration?.herfindahl)}`}
                  title="How many equal positions would be this concentrated (1 / Herfindahl index of invested weights)."
                />
                <Figure
                  label="Max drawdown"
                  value={performance?.max_drawdown ? `${performance.max_drawdown.percent.toFixed(2)}%` : "–"}
                  detail="since first trade"
                  title="Largest fall in total portfolio value from a previous high."
                />
                <Figure
                  label="Sharpe ratio"
                  value={number(performance?.sharpe)}
                  detail={performance?.sharpe === null ? "needs 1 day" : "annualized"}
                  title={performance?.note ?? "Annualized return per unit of volatility, with a risk-free rate of 0."}
                />
              </div>
            )}
            {data.correlation.matrix && data.correlation.tickers.length > 1 && (
              <div className="mt-3">
                <div className="mb-1 flex items-center justify-between text-xs text-muted">
                  <span>Correlation of daily returns</span>
                  <span className="flex items-center gap-1" aria-hidden>
                    −1
                    <span
                      className="h-2 w-16"
                      style={{ background: `linear-gradient(to right, #3987e5, var(--color-tile-flat), #d95926)` }}
                    />
                    +1
                  </span>
                </div>
                <CorrelationGrid tickers={data.correlation.tickers} matrix={data.correlation.matrix} />
              </div>
            )}
            <p className="mt-2 text-xs text-muted" data-testid="risk-basis">
              {data.returns} daily returns{synthetic ? ", including simulated history" : ""}.
              {data.concentration && data.notes.length > 0 && ` ${data.notes.join(" ")}`}
            </p>
          </>
        )}
      </div>
    </section>
  );
}
