"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { DataMode, Portfolio, Snapshot, WatchlistEntry } from "./types";

const REFRESH_MS = 15000;

/** Server state: refreshed on a timer and after anything that changes it. */
export function useAccount() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [watchlist, setWatchlist] = useState<WatchlistEntry[]>([]);
  const [mode, setMode] = useState<DataMode | null>(null);
  const [offline, setOffline] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [nextPortfolio, nextSnapshots, nextWatchlist, health] = await Promise.all([
        api.portfolio(),
        api.history(),
        api.watchlist(),
        api.health(),
      ]);
      setPortfolio(nextPortfolio);
      setSnapshots(nextSnapshots);
      setWatchlist(nextWatchlist);
      setMode(health.market_data.mode);
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  return { portfolio, snapshots, watchlist, mode, offline, refresh };
}
