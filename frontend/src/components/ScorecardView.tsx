"use client";

import { type ReactNode, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatHorizon, formatMoney } from "@/lib/format";
import type { DataMode, Outcome, PredictionRecord, PredictionScore, PredictionStats } from "@/lib/types";

const REFRESH_MS = 15000;

const percent = (fraction: number | null | undefined, digits = 1) =>
  fraction === null || fraction === undefined ? "–" : `${(fraction * 100).toFixed(digits)}%`;

const OUTCOMES: Record<Outcome | "pending", { label: string; className: string }> = {
  hit: { label: "Hit", className: "text-up" },
  miss: { label: "Miss", className: "text-down" },
  void: { label: "Void", className: "text-muted" },
  pending: { label: "Pending", className: "text-muted" },
};

const MODE_NAMES: Record<DataMode, string> = {
  simulated: "simulated prices",
  seeded: "simulated prices from real closes",
  live: "live market data",
  eod: "end-of-day closes",
};

function Figure({ label, value, detail, title }: { label: string; value: string; detail?: string; title: string }) {
  return (
    <div title={title} className="min-w-0">
      <div className="truncate text-xs text-muted">{label}</div>
      <div className="truncate font-medium">{value}</div>
      {detail && <div className="truncate text-xs text-muted">{detail}</div>}
    </div>
  );
}

const W = 150;
const H = 96;
const PAD = { left: 26, right: 8, top: 8, bottom: 16 };
const x = (stated: number) => PAD.left + ((stated - 0.5) / 0.5) * (W - PAD.left - PAD.right);
const y = (observed: number) => H - PAD.bottom - observed * (H - PAD.top - PAD.bottom);

/** Stated confidence against how often those calls came true. On the diagonal is honest. */
export function CalibrationChart({ calibration }: { calibration: PredictionScore["calibration"] }) {
  const largest = Math.max(1, ...calibration.map((b) => b.count));
  return (
    <svg
      role="img"
      aria-label="Calibration: stated confidence against observed hit rate"
      width={W}
      height={H}
      className="shrink-0 text-muted"
      data-testid="calibration-chart"
    >
      <line x1={x(0.5)} y1={y(0.5)} x2={x(1)} y2={y(1)} stroke="currentColor" strokeDasharray="3 3" strokeWidth={1} />
      <line x1={PAD.left} y1={y(0)} x2={W - PAD.right} y2={y(0)} stroke="#2b3543" strokeWidth={1} />
      {[0, 0.5, 1].map((v) => (
        <text key={v} x={PAD.left - 4} y={y(v) + 3} textAnchor="end" fontSize={9} fill="currentColor">
          {v * 100}%
        </text>
      ))}
      {[0.5, 0.75, 1].map((v) => (
        <text key={v} x={x(v)} y={H - 4} textAnchor={v === 1 ? "end" : "middle"} fontSize={9} fill="currentColor">
          {v * 100}%
        </text>
      ))}
      {calibration.map((bucket) => (
        <circle
          key={bucket.range[0]}
          cx={x(bucket.stated)}
          cy={y(bucket.observed)}
          r={4 + 3 * Math.sqrt(bucket.count / largest)}
          fill="#209dd7"
          stroke="var(--color-canvas)"
          strokeWidth={2}
        >
          <title>{`Stated ${percent(bucket.stated, 0)}, came true ${percent(bucket.observed, 0)} of ${bucket.count}`}</title>
        </circle>
      ))}
    </svg>
  );
}

function OutcomeCell({ outcome, title }: { outcome: Outcome | null; title?: string }) {
  const shown = OUTCOMES[outcome ?? "pending"];
  return (
    <span className={shown.className} title={title}>
      {shown.label}
    </span>
  );
}

const time = (iso: string) =>
  new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

interface Props {
  heading: ReactNode;
  mode: DataMode | null;
}

export function ScorecardView({ heading, mode }: Props) {
  const [stats, setStats] = useState<PredictionStats | null>(null);
  const [calls, setCalls] = useState<PredictionRecord[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      Promise.all([api.predictionStats(), api.predictions(20)]).then(
        ([nextStats, nextCalls]) => {
          if (cancelled) return;
          setStats(nextStats);
          setCalls(nextCalls);
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
  }, []);

  const scores = mode ? stats?.modes[mode] : undefined;
  const assistant = scores?.assistant;
  const baseline = scores?.baseline;
  const elsewhere = Object.entries(stats?.modes ?? {})
    .filter(([other]) => other !== mode)
    .map(([other, s]) => `${s.assistant.made} on ${MODE_NAMES[other as DataMode]}`);
  const simulated = mode === "simulated" || mode === "seeded";
  const shown = calls.filter((c) => c.data_mode === mode);

  return (
    <section aria-label="Prediction scorecard" className="flex min-h-56 min-w-0 flex-col">
      {heading}
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-2 text-sm" data-testid="scorecard-view">
        {!stats && <p className="py-2 text-muted">{failed ? "Couldn't load the scorecard. Retrying." : "Loading…"}</p>}
        {stats && !assistant && (
          <p className="py-2 text-muted">
            No predictions on {mode ? MODE_NAMES[mode] : "this data"} yet. Ask the assistant for a call, like
            &ldquo;Will NVDA be higher in an hour?&rdquo;
          </p>
        )}
        {assistant && baseline && (
          <>
            <div className="flex gap-4">
              <div className="grid min-w-0 flex-1 grid-cols-2 gap-x-4 gap-y-2">
                <Figure
                  label="Assistant hit rate"
                  value={assistant.settled ? `${percent(assistant.hit_rate)} (${assistant.hits}/${assistant.settled})` : "–"}
                  detail={
                    assistant.hit_rate_interval
                      ? `95%: ${percent(assistant.hit_rate_interval[0], 0)}–${percent(assistant.hit_rate_interval[1], 0)}`
                      : "nothing settled yet"
                  }
                  title="Share of settled calls that came true. The range is where the true rate likely lies; with few calls it is wide."
                />
                <Figure
                  label="Coin flip"
                  value={baseline.settled ? `${percent(baseline.hit_rate)} (${baseline.hits}/${baseline.settled})` : "–"}
                  detail="same tickers and horizons"
                  title="A random up or down call made alongside each of the assistant's, as the baseline to beat."
                />
                <Figure
                  label="Brier score"
                  value={assistant.brier === null ? "–" : assistant.brier.toFixed(3)}
                  detail="coin flip 0.250 · lower is better"
                  title="Squared gap between stated confidence and what happened. Confident misses cost the most."
                />
                <Figure
                  label="Calls"
                  value={`${assistant.made} made`}
                  detail={`${assistant.pending} pending · ${assistant.void} void`}
                  title="Void calls (the price didn't move, or wasn't recorded) don't count either way."
                />
              </div>
              <CalibrationChart calibration={assistant.calibration} />
            </div>
            {simulated && (
              <p className="mt-2 text-xs text-muted">
                These prices are simulated: a random walk no one can predict. Expect about 50% over time; a clearly
                better record would point to a bug.
              </p>
            )}
          </>
        )}
        {shown.length > 0 && (
          <table className="mt-2 w-full text-xs tabular-nums" data-testid="prediction-list">
            <thead className="text-left text-muted">
              <tr>
                <th className="font-normal">Made</th>
                <th className="font-normal">Call</th>
                <th className="font-normal">Over</th>
                <th className="text-right font-normal">From → to</th>
                <th className="pl-2 font-normal">Result</th>
                <th className="font-normal">Coin</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((call) => (
                <tr key={call.id} className="border-t border-line">
                  <td className="py-0.5 text-muted">{time(call.made_at)}</td>
                  <td>
                    {call.ticker} {call.direction === "up" ? "↑" : "↓"} {percent(call.confidence, 0)}
                  </td>
                  <td>{formatHorizon(call.horizon_minutes)}</td>
                  <td className="text-right">
                    {formatMoney(call.reference_price)} → {call.resolved_price === null ? "…" : formatMoney(call.resolved_price)}
                  </td>
                  <td className="pl-2">
                    <OutcomeCell outcome={call.outcome} title={call.note ?? undefined} />
                  </td>
                  <td>
                    <OutcomeCell outcome={call.baseline_outcome} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {elsewhere.length > 0 && <p className="mt-2 text-xs text-muted">Also recorded: {elsewhere.join(", ")}.</p>}
      </div>
    </section>
  );
}
