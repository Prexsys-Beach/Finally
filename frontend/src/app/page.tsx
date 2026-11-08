"use client";

import { useMemo, useState } from "react";
import { ChatPanel } from "@/components/ChatPanel";
import { Header } from "@/components/Header";
import { Heatmap } from "@/components/Heatmap";
import { PnlChart } from "@/components/PnlChart";
import { PositionsTable } from "@/components/PositionsTable";
import { PriceChart } from "@/components/PriceChart";
import { TradeBar } from "@/components/TradeBar";
import { Watchlist } from "@/components/Watchlist";
import { livePortfolio } from "@/lib/portfolio";
import { useAccount } from "@/lib/useAccount";
import { useMarket } from "@/lib/useMarket";

export default function Home() {
  const { prices, status, history } = useMarket();
  const { portfolio, snapshots, watchlist, mode, offline, refresh } = useAccount();
  const [picked, setPicked] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(true);

  const selected = picked ?? watchlist[0]?.ticker ?? null;
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
            <Heatmap portfolio={live} onSelect={setPicked} />
            <PnlChart snapshots={snapshots} />
          </div>
          <PositionsTable positions={live?.positions ?? []} selected={selected} onSelect={setPicked} />
        </div>
        <ChatPanel
          open={chatOpen}
          onToggle={() => setChatOpen((open) => !open)}
          onActions={refresh}
        />
      </main>
    </div>
  );
}
