import type { Portfolio, Position, PriceUpdate } from "./types";

/** Reprice a server portfolio with the latest streamed prices. */
export function livePortfolio(
  portfolio: Portfolio,
  prices: Record<string, PriceUpdate>,
): Portfolio {
  const positions: Position[] = portfolio.positions.map((position) => {
    const update = prices[position.ticker];
    if (!update) return position;
    const marketValue = position.quantity * update.price;
    return {
      ...position,
      current_price: update.price,
      market_value: marketValue,
      unrealized_pnl: marketValue - position.cost_basis,
      unrealized_pnl_percent: (update.price / position.avg_cost - 1) * 100,
      day_change_percent: update.day_change_percent,
    };
  });
  const positionsValue = positions.reduce(
    (total, p) => total + (p.market_value ?? p.cost_basis),
    0,
  );
  return {
    ...portfolio,
    positions,
    positions_value: positionsValue,
    total_value: portfolio.cash_balance + positionsValue,
    unrealized_pnl: positions.reduce((total, p) => total + (p.unrealized_pnl ?? 0), 0),
  };
}
