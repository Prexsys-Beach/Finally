"use client";

import { type FormEvent, useState } from "react";
import { api } from "@/lib/api";
import { formatMoney, formatPercent, trendClass } from "@/lib/format";
import type { PricePoint, PriceUpdate, WatchlistEntry } from "@/lib/types";
import { useSparklines } from "@/lib/useBars";
import { useFlash } from "@/lib/useFlash";
import { Sparkline } from "./Sparkline";

interface RowProps {
  entry: WatchlistEntry;
  update: PriceUpdate | undefined;
  points: PricePoint[] | undefined;
  selected: boolean;
  onSelect: (ticker: string) => void;
  onRemove: (ticker: string) => void;
}

export function WatchlistRow({ entry, update, points, selected, onSelect, onRemove }: RowProps) {
  const price = update?.price ?? entry.price;
  const change = update?.day_change_percent ?? entry.day_change_percent;
  const flash = useFlash(price);
  return (
    <li
      data-testid={`watchlist-row-${entry.ticker}`}
      className={`group relative border-b border-line ${selected ? "bg-raised shadow-[inset_2px_0_0_var(--color-accent)]" : ""}`}
    >
      <button
        type="button"
        aria-pressed={selected}
        onClick={() => onSelect(entry.ticker)}
        className="grid w-full grid-cols-[1fr_auto] items-center gap-x-2 py-1 pr-6 pl-3 text-left hover:bg-raised"
      >
        <span className="font-semibold">{entry.ticker}</span>
        <span data-testid="price" className={`price-cell rounded-sm px-1 text-right font-medium ${flash}`}>
          {price === null ? "No price yet" : formatMoney(price)}
        </span>
        <Sparkline points={points} />
        <span className={`px-1 text-right text-sm ${trendClass(change)}`}>{formatPercent(change)}</span>
      </button>
      <button
        type="button"
        aria-label={`Remove ${entry.ticker} from watchlist`}
        onClick={() => onRemove(entry.ticker)}
        className="absolute top-1 right-1 size-5 text-muted opacity-40 group-hover:opacity-100 hover:text-ink focus-visible:opacity-100"
      >
        ×
      </button>
    </li>
  );
}

interface Props {
  entries: WatchlistEntry[];
  prices: Record<string, PriceUpdate>;
  selected: string | null;
  onSelect: (ticker: string) => void;
  onChange: () => Promise<void>;
}

export function Watchlist({ entries, prices, selected, onSelect, onChange }: Props) {
  const [ticker, setTicker] = useState("");
  const sparklines = useSparklines(
    entries.map((entry) => entry.ticker),
    prices,
  );
  const [error, setError] = useState<string | null>(null);

  const run = async (action: Promise<unknown>) => {
    setError(null);
    try {
      await action;
      await onChange();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work. Try again.");
      return false;
    }
  };

  const add = async (event: FormEvent) => {
    event.preventDefault();
    const value = ticker.trim();
    if (value && (await run(api.addTicker(value)))) setTicker("");
  };

  return (
    <aside aria-label="Watchlist" className="flex min-h-0 flex-col">
      <h2 className="px-3 pt-2 pb-1 text-sm font-medium text-muted">Watchlist</h2>
      <form onSubmit={add} className="flex gap-1 border-b border-line px-3 pb-2">
        <input
          aria-label="Ticker to add"
          placeholder="Add ticker"
          value={ticker}
          onChange={(event) => setTicker(event.target.value.toUpperCase())}
          className="min-w-0 flex-1 border border-line bg-canvas px-2 py-0.5 placeholder:text-muted"
        />
        <button type="submit" className="border border-line px-2 hover:bg-raised">
          Add
        </button>
      </form>
      {error && (
        <p role="alert" className="border-b border-line px-3 py-1 text-sm text-down">
          {error}
        </p>
      )}
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {entries.map((entry) => (
          <WatchlistRow
            key={entry.ticker}
            entry={entry}
            update={prices[entry.ticker]}
            points={sparklines[entry.ticker]}
            selected={entry.ticker === selected}
            onSelect={onSelect}
            onRemove={(value) => void run(api.removeTicker(value))}
          />
        ))}
        {entries.length === 0 && (
          <li className="px-3 py-3 text-sm text-muted">Add a ticker to start watching prices.</li>
        )}
      </ul>
    </aside>
  );
}
