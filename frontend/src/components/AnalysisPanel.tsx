"use client";

import type { Portfolio } from "@/lib/types";
import { useStored } from "@/lib/useStored";
import { Heatmap } from "./Heatmap";
import { RiskView } from "./RiskView";

const VIEWS = { heatmap: "Heatmap", risk: "Risk" } as const;
type View = keyof typeof VIEWS;
const isView = (value: unknown): value is View => typeof value === "string" && value in VIEWS;

const CAPTIONS: Record<View, string> = {
  heatmap: "Holdings by weight and P&L",
  risk: "Portfolio risk, 1 trading day",
};

interface Props {
  portfolio: Portfolio | null;
  positionsKey: string;
  onSelect: (ticker: string) => void;
}

/** One panel, several views of the portfolio. */
export function AnalysisPanel({ portfolio, positionsKey, onSelect }: Props) {
  const [view, setView] = useStored<View>("finally.analysis-view", "heatmap", isView);

  const heading = (
    <div className="flex items-center gap-3 px-3 pt-2 pb-1">
      <div role="group" aria-label="Analysis view" className="flex text-xs">
        {(Object.keys(VIEWS) as View[]).map((name) => (
          <button
            key={name}
            type="button"
            aria-pressed={view === name}
            onClick={() => setView(name)}
            className={`-ml-px border border-line px-2 py-0.5 first:ml-0 ${
              view === name ? "bg-raised text-ink" : "text-muted hover:text-ink"
            }`}
          >
            {VIEWS[name]}
          </button>
        ))}
      </div>
      <h2 className="truncate text-sm font-medium text-muted">{CAPTIONS[view]}</h2>
    </div>
  );

  return view === "heatmap" ? (
    <Heatmap portfolio={portfolio} onSelect={onSelect} heading={heading} />
  ) : (
    <RiskView heading={heading} positionsKey={positionsKey} />
  );
}
