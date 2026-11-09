import type { Page } from "@playwright/test";
import { expect, open, test } from "./helpers";

async function send(page: Page, text: string) {
  await page.getByLabel("Message the assistant").fill(text);
  await page.getByLabel("Message the assistant").press("Enter");
  await expect(page.getByTestId("chat-loading")).toHaveCount(0);
}

test.describe("backtests", () => {
  test("the assistant can backtest a strategy", async ({ page }) => {
    await open(page);
    await send(page, "backtest NVDA");
    await expect(page.getByTestId("chat-lookups").last()).toHaveText(
      "Analysis used: NVDA backtest (SMA crossover)",
    );
  });

  test("the API replays a strategy on stored history", async ({ request }) => {
    const response = await request.post("/api/analytics/backtest", {
      data: { ticker: "AAPL", strategy: "sma_crossover", params: { fast: 5, slow: 20 } },
    });
    expect(response.ok()).toBe(true);
    const body = await response.json();
    expect(body.bars).toBeGreaterThan(200);
    expect(typeof body.total_return).toBe("number");
    expect(typeof body.buy_and_hold_return).toBe("number");
    expect(body.equity_curve.length).toBeGreaterThan(10);
  });
});
