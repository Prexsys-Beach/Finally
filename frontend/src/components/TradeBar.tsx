"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { formatMoney, formatQuantity } from "@/lib/format";
import type { Side } from "@/lib/types";

interface Props {
  ticker: string | null;
  onTraded: () => Promise<void>;
}

const INPUT = "border border-line bg-canvas px-2 py-1 placeholder:text-muted";

export function TradeBar({ ticker, onTraded }: Props) {
  // Follows the selected ticker until the user types their own
  const [typed, setTyped] = useState<{ value: string; base: string | null } | null>(null);
  const [quantity, setQuantity] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ text: string; failed: boolean } | null>(null);

  const symbol = typed && typed.base === ticker ? typed.value : (ticker ?? "");
  const amount = Number(quantity);
  const ready = symbol.trim() !== "" && Number.isFinite(amount) && amount > 0 && !busy;

  const trade = async (side: Side) => {
    setBusy(true);
    setResult(null);
    try {
      const { trade: filled } = await api.trade(symbol.trim(), amount, side);
      const verb = side === "buy" ? "Bought" : "Sold";
      setResult({
        text: `${verb} ${formatQuantity(filled.quantity)} ${filled.ticker} at ${formatMoney(filled.price)}`,
        failed: false,
      });
      setQuantity("");
      await onTraded();
    } catch (e) {
      setResult({ text: e instanceof Error ? e.message : "The trade didn't go through.", failed: true });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      aria-label="Trade"
      onSubmit={(event) => event.preventDefault()}
      className="flex flex-wrap items-center gap-2 border-t border-line px-3 py-2"
    >
      <input
        aria-label="Ticker"
        placeholder="Ticker"
        value={symbol}
        onChange={(event) => setTyped({ value: event.target.value.toUpperCase(), base: ticker })}
        className={`${INPUT} w-24 font-semibold`}
      />
      <input
        aria-label="Quantity"
        placeholder="Quantity"
        inputMode="decimal"
        value={quantity}
        onChange={(event) => setQuantity(event.target.value)}
        className={`${INPUT} w-24`}
      />
      <button
        type="button"
        disabled={!ready}
        onClick={() => void trade("buy")}
        className="bg-submit px-4 py-1 font-semibold text-white hover:brightness-110"
      >
        Buy
      </button>
      <button
        type="button"
        disabled={!ready}
        onClick={() => void trade("sell")}
        className="border border-submit px-4 py-1 font-semibold hover:bg-submit"
      >
        Sell
      </button>
      {result && (
        <p role="status" data-testid="trade-result" className={`text-sm ${result.failed ? "text-down" : "text-muted"}`}>
          {result.text}
        </p>
      )}
    </form>
  );
}
