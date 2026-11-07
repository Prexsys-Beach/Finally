import { describe, expect, it } from "vitest";
import { formatMoney, formatPercent, formatSignedMoney } from "./format";
import { appendPoint, MAX_POINTS, toSeries } from "./history";
import { livePortfolio } from "./portfolio";
import { squarify } from "./treemap";
import type { Portfolio, PricePoint, PriceUpdate } from "./types";

describe("format", () => {
  it("shows a dash for unknown values", () => {
    expect(formatMoney(null)).toBe("–");
    expect(formatPercent(null)).toBe("–");
  });

  it("signs values", () => {
    expect(formatPercent(1.234)).toBe("+1.23%");
    expect(formatPercent(-1.234)).toBe("−1.23%");
    expect(formatSignedMoney(-5)).toBe("−$5.00");
    expect(formatPercent(0)).toBe("0.00%");
  });
});

describe("appendPoint", () => {
  it("keeps one point per second, latest wins", () => {
    const points: PricePoint[] = [];
    appendPoint(points, 100.2, 1);
    appendPoint(points, 100.8, 2);
    appendPoint(points, 101.1, 3);
    expect(points).toEqual([{ time: 100, value: 2 }, { time: 101, value: 3 }]);
  });

  it("never lets time go backwards", () => {
    const points: PricePoint[] = [];
    appendPoint(points, 100, 1);
    appendPoint(points, 90, 2);
    expect(points).toEqual([{ time: 100, value: 2 }]);
  });

  it("caps history", () => {
    const points: PricePoint[] = [];
    for (let i = 0; i < MAX_POINTS + 5; i++) appendPoint(points, i, i);
    expect(points).toHaveLength(MAX_POINTS);
    expect(points[0].time).toBe(5);
  });

  it("dedupes snapshots recorded in the same second", () => {
    expect(toSeries([{ time: 5.1, value: 1 }, { time: 5.9, value: 2 }])).toEqual([{ time: 5, value: 2 }]);
  });
});

describe("squarify", () => {
  const items = [
    { id: "a", value: 6 },
    { id: "b", value: 6 },
    { id: "c", value: 4 },
    { id: "d", value: 3 },
    { id: "e", value: 2 },
    { id: "f", value: 2 },
    { id: "g", value: 1 },
  ];

  it("makes each area proportional to its value and fills the space", () => {
    const rects = squarify(items, 600, 400);
    expect(rects).toHaveLength(items.length);
    const scale = (600 * 400) / 24;
    for (const rect of rects) expect(rect.width * rect.height).toBeCloseTo(rect.value * scale, 5);
  });

  it("stays inside the bounds without overlapping", () => {
    const rects = squarify(items, 600, 400);
    for (const a of rects) {
      expect(a.x).toBeGreaterThanOrEqual(-1e-6);
      expect(a.y).toBeGreaterThanOrEqual(-1e-6);
      expect(a.x + a.width).toBeLessThanOrEqual(600 + 1e-6);
      expect(a.y + a.height).toBeLessThanOrEqual(400 + 1e-6);
      for (const b of rects) {
        if (a === b) continue;
        const overlapX = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
        const overlapY = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
        expect(overlapX <= 1e-6 || overlapY <= 1e-6).toBe(true);
      }
    }
  });

  it("gives a single item the whole area", () => {
    expect(squarify([{ id: "cash", value: 10 }], 300, 200)[0]).toMatchObject({ x: 0, y: 0, width: 300, height: 200 });
  });

  it("drops empty values and handles an unmeasured container", () => {
    expect(squarify([{ id: "a", value: 0 }], 100, 100)).toEqual([]);
    expect(squarify([{ id: "a", value: 1 }], 0, 0)).toEqual([]);
  });
});

describe("livePortfolio", () => {
  const portfolio: Portfolio = {
    cash_balance: 9000,
    positions: [
      {
        ticker: "AAPL",
        quantity: 10,
        avg_cost: 100,
        cost_basis: 1000,
        current_price: 100,
        market_value: 1000,
        unrealized_pnl: 0,
        unrealized_pnl_percent: 0,
        day_change_percent: 0,
      },
    ],
    positions_value: 1000,
    total_value: 10000,
    unrealized_pnl: 0,
  };

  it("reprices positions and totals from the stream", () => {
    const update = { ticker: "AAPL", price: 110, day_change_percent: 2 } as PriceUpdate;
    const live = livePortfolio(portfolio, { AAPL: update });
    expect(live.total_value).toBe(10100);
    expect(live.unrealized_pnl).toBe(100);
    expect(live.positions[0].unrealized_pnl_percent).toBeCloseTo(10);
  });

  it("keeps server values when a price is missing", () => {
    expect(livePortfolio(portfolio, {}).total_value).toBe(10000);
  });
});
