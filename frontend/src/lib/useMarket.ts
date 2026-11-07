"use client";

import { useEffect, useRef, useState } from "react";
import { appendPoint } from "./history";
import type { ConnectionStatus, PricePoint, PriceUpdate } from "./types";

/** Live prices from SSE, plus per-ticker history accumulated since page load. */
export function useMarket() {
  const [prices, setPrices] = useState<Record<string, PriceUpdate>>({});
  const [status, setStatus] = useState<ConnectionStatus>("reconnecting");
  const history = useRef<Record<string, PricePoint[]>>({});

  useEffect(() => {
    const source = new EventSource("/api/stream/prices");
    source.onopen = () => setStatus("connected");
    source.onerror = () =>
      setStatus(source.readyState === EventSource.CLOSED ? "disconnected" : "reconnecting");
    source.onmessage = (event: MessageEvent<string>) => {
      const update: Record<string, PriceUpdate> = JSON.parse(event.data);
      const now = Date.now() / 1000;
      for (const { ticker, price } of Object.values(update)) {
        appendPoint((history.current[ticker] ??= []), now, price);
      }
      setPrices(update);
      setStatus("connected");
    };
    return () => source.close();
  }, []);

  return { prices, status, history: history.current };
}
