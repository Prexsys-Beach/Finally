"use client";

import { useMemo, useState } from "react";
import { AnalysisPanel, type ViewRequest } from "@/components/AnalysisPanel";
import { ChatPanel } from "@/components/ChatPanel";
import { Header } from "@/components/Header";
import { PnlChart } from "@/components/PnlChart";
import { PositionsTable } from "@/components/PositionsTable";
import { PriceChart } from "@/components/PriceChart";
import { TradeBar } from "@/components/TradeBar";
import { Watchlist } from "@/components/Watchlist";
import { livePortfolio } from "@/lib/portfolio";
import type { ChatActions } from "@/lib/types";
import { useAccount } from "@/lib/useAccount";
import { useMarket } from "@/lib/useMarket";

/** Lookups that read portfolio risk; replies that use them bring the Risk view forward. */
const RISK_LOOKUPS = ["get_portfolio_risk", "get_correlations"];

export default function Home() {
  const { prices, status, history } = useMarket();
  const { portfolio, snapshots, watchlist, mode, offline, refresh } = useAccount();
  const [picked, setPicked] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(true);
  const [viewRequest, setViewRequest] = useState<ViewRequest | null>(null);

  const onAssistantActions = async (actions: ChatActions) => {
    await refresh();
    // A prediction outranks a risk lookup: it is what the reply was about
    const predicted = actions.predictions?.some((call) => call.status === "ok");
    const usedRisk = actions.tool_calls?.some(
      (call) => call.status === "ok" && RISK_LOOKUPS.includes(call.name),
    );
    if (predicted) setViewRequest({ view: "scorecard", at: Date.now() });
    else if (usedRisk) setViewRequest({ view: "risk", at: Date.now() });
  };

  const selected = picked ?? watchlist[0]?.ticker ?? null;
  const positionsKey = (portfolio?.positions ?? []).map((p) => `${p.ticker}:${p.quantity}`).join(",");
  const live = useMemo(
    () => (portfolio ? livePortfolio(portfolio, prices) : null),
    [portfolio, prices],
  );

  return (
    <div className="flex min-h-dvh flex-col lg:h-dvh">
      <Header portfolio={live} status={status} mode={mode} />
      {offline && (
        <p role="alert" className="border-b border-line bg-tile-down px-4 py-1 text-sm">
          The server isn&apos;t responding. Showing the last known values.
        </p>
      )}
      <main
        className={`grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[250px_minmax(0,1fr)] ${
          chatOpen
            ? "lg:grid-cols-[250px_minmax(0,1fr)_330px]"
            : "lg:grid-cols-[250px_minmax(0,1fr)_44px]"
        }`}
      >
        <Watchlist
          entries={watchlist}
          prices={prices}
          selected={selected}
          onSelect={setPicked}
          onChange={refresh}
        />
        <div className="flex min-h-0 min-w-0 flex-col border-line md:border-l">
          <section aria-label="Price chart" className="flex min-h-72 flex-[3] flex-col">
            <PriceChart ticker={selected} points={selected ? history[selected] : undefined} update={selected ? prices[selected] : undefined} />
          </section>
          <TradeBar ticker={selected} onTraded={refresh} />
          <div className="grid min-h-64 flex-[2] grid-cols-1 border-t border-line xl:grid-cols-2">
            <AnalysisPanel
              portfolio={live}
              positionsKey={positionsKey}
              onSelect={setPicked}
              viewRequest={viewRequest}
              mode={mode}
            />
            <PnlChart snapshots={snapshots} />
          </div>
          <PositionsTable positions={live?.positions ?? []} selected={selected} onSelect={setPicked} />
        </div>
        <ChatPanel
          open={chatOpen}
          onToggle={() => setChatOpen((open) => !open)}
          onActions={onAssistantActions}
        />
      </main>
    </div>
  );
}
