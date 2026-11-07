import { formatMoney, formatPercent, formatQuantity, formatSignedMoney, trendClass } from "@/lib/format";
import type { Position } from "@/lib/types";

interface Props {
  positions: Position[];
  selected: string | null;
  onSelect: (ticker: string) => void;
}

const HEADINGS = ["Quantity", "Avg cost", "Price", "Unrealized P&L", "Change"];

export function PositionsTable({ positions, selected, onSelect }: Props) {
  return (
    <section aria-label="Positions" className="max-h-44 shrink-0 overflow-y-auto border-t border-line">
      {positions.length === 0 ? (
        <p className="px-3 py-3 text-sm text-muted">
          No positions yet. Buy shares with the trade bar or ask the assistant.
        </p>
      ) : (
        <table className="w-full text-right text-sm" data-testid="positions-table">
          <thead className="sticky top-0 bg-canvas text-muted">
            <tr>
              <th scope="col" className="px-3 py-1 text-left font-normal">Ticker</th>
              {HEADINGS.map((heading) => (
                <th key={heading} scope="col" className="px-3 py-1 font-normal">{heading}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr
                key={p.ticker}
                data-testid={`position-${p.ticker}`}
                className={`border-t border-line ${p.ticker === selected ? "bg-raised" : ""}`}
              >
                <th scope="row" className="px-3 py-0.5 text-left font-semibold">
                  <button type="button" onClick={() => onSelect(p.ticker)} className="hover:underline">
                    {p.ticker}
                  </button>
                </th>
                <td className="px-3">{formatQuantity(p.quantity)}</td>
                <td className="px-3">{formatMoney(p.avg_cost)}</td>
                <td className="px-3">{formatMoney(p.current_price)}</td>
                <td className={`px-3 ${trendClass(p.unrealized_pnl)}`}>{formatSignedMoney(p.unrealized_pnl)}</td>
                <td className={`px-3 ${trendClass(p.unrealized_pnl_percent)}`}>{formatPercent(p.unrealized_pnl_percent)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
