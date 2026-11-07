"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { formatMoney, formatPercent } from "@/lib/format";
import { squarify } from "@/lib/treemap";
import type { Portfolio } from "@/lib/types";

const CASH = "Cash";
const FULL_COLOR_AT_PERCENT = 5;
const GAP = 2;

/** Diverging scale: neutral at zero, full color at ±5%. Tiles also print the signed value. */
export function tileColor(percent: number | null): string {
  if (!percent) return "var(--color-tile-flat)";
  const strength = Math.min(Math.abs(percent) / FULL_COLOR_AT_PERCENT, 1);
  const pole = percent > 0 ? "var(--color-tile-up)" : "var(--color-tile-down)";
  return `color-mix(in oklab, ${pole} ${Math.round(25 + strength * 75)}%, var(--color-tile-flat))`;
}

interface Props {
  portfolio: Portfolio | null;
  onSelect: (ticker: string) => void;
}

export function Heatmap({ portfolio, onSelect }: Props) {
  const area = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (!area.current) return;
    const observer = new ResizeObserver(([entry]) => setSize(entry.contentRect));
    observer.observe(area.current);
    return () => observer.disconnect();
  }, []);

  const tiles = useMemo(() => {
    if (!portfolio) return [];
    const items = [
      ...portfolio.positions.map((p) => ({ id: p.ticker, value: p.market_value ?? p.cost_basis })),
      { id: CASH, value: portfolio.cash_balance },
    ];
    return squarify(items, size.width, size.height);
  }, [portfolio, size]);

  const total = portfolio?.total_value ?? 0;

  return (
    <section aria-label="Portfolio heatmap" className="flex min-h-56 min-w-0 flex-col">
      <h2 className="px-3 pt-2 pb-1 text-sm font-medium text-muted">Holdings by weight and P&L</h2>
      <div ref={area} className="relative mx-3 mb-3 min-h-0 flex-1 overflow-hidden" data-testid="heatmap">
        {tiles.map((tile) => {
          const position = portfolio?.positions.find((p) => p.ticker === tile.id);
          const weight = total > 0 ? (tile.value / total) * 100 : 0;
          const roomy = tile.width > 56 && tile.height > 38;
          const box = {
            left: tile.x,
            top: tile.y,
            width: Math.max(tile.width - GAP, 0),
            height: Math.max(tile.height - GAP, 0),
          };
          if (!position) {
            return (
              <div
                key={tile.id}
                data-testid="heatmap-tile-cash"
                className="cash-tile tile absolute overflow-hidden p-2"
                style={box}
              >
                <div className="font-semibold">Cash</div>
                {roomy && <div className="text-sm">{formatMoney(tile.value)}</div>}
              </div>
            );
          }
          const percent = position.unrealized_pnl_percent;
          return (
            <button
              key={tile.id}
              type="button"
              data-testid={`heatmap-tile-${tile.id}`}
              title={`${tile.id}: ${formatPercent(percent)}, ${weight.toFixed(1)}% of portfolio`}
              onClick={() => onSelect(tile.id)}
              className="tile absolute overflow-hidden p-2 text-left text-[#f2f5f8] hover:brightness-110"
              style={{ ...box, background: tileColor(percent) }}
            >
              <div className="font-semibold">{tile.id}</div>
              {roomy && <div className="text-sm">{formatPercent(percent)}</div>}
            </button>
          );
        })}
      </div>
    </section>
  );
}
