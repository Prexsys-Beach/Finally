"use client";

import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { formatMoney, formatPercent } from "@/lib/format";
import { squarify } from "@/lib/treemap";
import type { Portfolio } from "@/lib/types";

const CASH = "Cash";
const FULL_COLOR_AT_PERCENT = 5;
const GAP = 2;
const CHAR_WIDTH = 8.5; // Generous for this font, so estimates err towards fitting
const SIDE_PADDING = 16;
const STACKED_HEIGHT = 62; // Two lines plus padding
const LINE_HEIGHT = 30; // One line plus padding

type TileContent = "stacked" | "inline" | "label" | "none";

/** The most a tile can show without clipping. Short tiles keep their value on one line. */
export function tileContent(label: string, value: string, width: number, height: number): TileContent {
  const fits = (characters: number) => characters * CHAR_WIDTH + SIDE_PADDING <= width;
  if (height >= STACKED_HEIGHT && fits(Math.max(label.length, value.length))) return "stacked";
  if (height >= LINE_HEIGHT && fits(label.length + value.length + 1)) return "inline";
  if (height >= LINE_HEIGHT && fits(label.length)) return "label";
  return "none";
}

function TileText({ content, label, value }: { content: TileContent; label: string; value: string }) {
  if (content === "none") return null;
  if (content === "stacked") {
    return (
      <>
        <div className="font-semibold">{label}</div>
        <div className="text-sm">{value}</div>
      </>
    );
  }
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="font-semibold">{label}</span>
      {content === "inline" && <span className="text-sm">{value}</span>}
    </div>
  );
}

const tilePadding = (content: TileContent) => (content === "stacked" ? "p-2" : "px-2 py-0.5");

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
  heading?: ReactNode;
}

const DEFAULT_HEADING = (
  <h2 className="px-3 pt-2 pb-1 text-sm font-medium text-muted">Holdings by weight and P&L</h2>
);

export function Heatmap({ portfolio, onSelect, heading = DEFAULT_HEADING }: Props) {
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
      {heading}
      <div ref={area} className="relative mx-3 mb-3 min-h-0 flex-1 overflow-hidden" data-testid="heatmap">
        {tiles.map((tile) => {
          const position = portfolio?.positions.find((p) => p.ticker === tile.id);
          const weight = total > 0 ? (tile.value / total) * 100 : 0;
          const box = {
            left: tile.x,
            top: tile.y,
            width: Math.max(tile.width - GAP, 0),
            height: Math.max(tile.height - GAP, 0),
          };
          if (!position) {
            const value = formatMoney(tile.value);
            const content = tileContent(CASH, value, tile.width, tile.height);
            return (
              <div
                key={tile.id}
                data-testid="heatmap-tile-cash"
                title={`Cash: ${value}, ${weight.toFixed(1)}% of portfolio`}
                className={`cash-tile tile absolute overflow-hidden ${tilePadding(content)}`}
                style={box}
              >
                <TileText content={content} label={CASH} value={value} />
              </div>
            );
          }
          const percent = position.unrealized_pnl_percent;
          const value = formatPercent(percent);
          const content = tileContent(tile.id, value, tile.width, tile.height);
          return (
            <button
              key={tile.id}
              type="button"
              data-testid={`heatmap-tile-${tile.id}`}
              title={`${tile.id}: ${value}, ${weight.toFixed(1)}% of portfolio`}
              onClick={() => onSelect(tile.id)}
              className={`tile absolute overflow-hidden text-left text-[#f2f5f8] hover:brightness-110 ${tilePadding(content)}`}
              style={{ ...box, background: tileColor(percent) }}
            >
              <TileText content={content} label={tile.id} value={value} />
            </button>
          );
        })}
      </div>
    </section>
  );
}
