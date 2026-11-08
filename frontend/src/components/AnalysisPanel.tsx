"use client";

import { useEffect, useState } from "react";
import { saveSettings, useSettings } from "@/lib/settings";
import type { Portfolio } from "@/lib/types";
import { useStored } from "@/lib/useStored";
import { Heatmap } from "./Heatmap";
import { RiskView } from "./RiskView";

const VIEWS = { heatmap: "Heatmap", risk: "Risk" } as const;
export type View = keyof typeof VIEWS;

/** A request from elsewhere (an assistant reply) to show a view. `at` makes repeats distinct. */
export interface ViewRequest {
  view: View;
  at: number;
}
const isView = (value: unknown): value is View => typeof value === "string" && value in VIEWS;

const CAPTIONS: Record<View, string> = {
  heatmap: "Holdings by weight and P&L",
  risk: "Portfolio risk, 1 trading day",
};

interface Props {
  portfolio: Portfolio | null;
  positionsKey: string;
  onSelect: (ticker: string) => void;
  viewRequest?: ViewRequest | null;
}

/** One panel, several views of the portfolio. */
export function AnalysisPanel({ portfolio, positionsKey, onSelect, viewRequest = null }: Props) {
  const [view, setView] = useStored<View>("finally.analysis-view", "heatmap", isView);
  const settings = useSettings();
  // Shown at once on a click; the saved value takes over when the save settles
  const [pendingAuto, setPendingAuto] = useState<boolean | null>(null);
  const autoSwitch = pendingAuto ?? settings?.settings.analysis_panel_auto_switch ?? false;

  const toggleAuto = () => {
    setPendingAuto(!autoSwitch);
    saveSettings({ analysis_panel_auto_switch: !autoSwitch })
      .catch(() => undefined)
      .finally(() => setPendingAuto(null));
  };

  // Only new requests switch the view; a manual choice stands until the next one
  useEffect(() => {
    if (viewRequest && autoSwitch) setView(viewRequest.view);
  }, [viewRequest]); // autoSwitch is read at the moment a request arrives

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
      <button
        type="button"
        aria-pressed={autoSwitch}
        disabled={!settings}
        title="Bring the Risk view forward when an assistant reply looks at portfolio risk"
        onClick={toggleAuto}
        className={`ml-auto border border-line px-2 py-0.5 text-xs ${
          autoSwitch ? "bg-raised text-ink" : "text-muted hover:text-ink"
        }`}
      >
        Auto
      </button>
    </div>
  );

  return view === "heatmap" ? (
    <Heatmap portfolio={portfolio} onSelect={onSelect} heading={heading} />
  ) : (
    <RiskView heading={heading} positionsKey={positionsKey} />
  );
}
