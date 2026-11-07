import { clippedTiles, expect, open, plottedLine, test, tileState, trade } from "./helpers";

test.describe("portfolio views", () => {
  test.beforeEach(async ({ page }) => {
    await open(page);
    await expect(await trade(page, "Buy", "TSLA", 8)).toHaveText(/^Bought 8 TSLA/);
    await expect(await trade(page, "Buy", "JPM", 2)).toHaveText(/^Bought 2 JPM/);
  });

  test.afterEach(async ({ page }) => {
    await expect(await trade(page, "Sell", "TSLA", 8)).toHaveText(/^Sold 8 TSLA/);
    await expect(await trade(page, "Sell", "JPM", 2)).toHaveText(/^Sold 2 JPM/);
  });

  test("heatmap sizes tiles by weight and colors them by P&L", async ({ page }) => {
    const tsla = page.getByTestId("heatmap-tile-TSLA");
    const jpm = page.getByTestId("heatmap-tile-JPM");
    await expect(tsla).toBeVisible();
    await expect(jpm).toBeVisible();
    await expect(page.getByTestId("heatmap-tile-cash")).toBeVisible();

    const area = async (tile: typeof tsla) => {
      const box = (await tile.boundingBox())!;
      return box.width * box.height;
    };
    // $2,000 of TSLA against $390 of JPM
    expect(await area(tsla)).toBeGreaterThan(3 * (await area(jpm)));

    // Prices are random, so wait for a real gain or loss to judge the color
    await expect.poll(async () => (await tileState(tsla)).percent, { timeout: 20_000 }).not.toBe(0);
    const { percent, red, green } = await tileState(tsla);
    if (percent > 0) expect(green).toBeGreaterThan(red);
    else expect(red).toBeGreaterThan(green);

    await tsla.click();
    await expect(page.getByTestId("chart-ticker")).toHaveText("TSLA");
  });

  test("heatmap text fits its tile at every size", async ({ page }) => {
    await expect(await trade(page, "Buy", "V", 0.1)).toHaveText(/^Bought 0.1 V/);
    await expect(page.getByTestId("heatmap-tile-V")).toBeVisible();
    expect(await clippedTiles(page)).toEqual([]);
    await expect(await trade(page, "Sell", "V", 0.1)).toHaveText(/^Sold 0.1 V/);
  });

  test("P&L chart plots the portfolio's value", async ({ page }) => {
    // Trades can fill at the price they opened at, leaving every snapshot equal
    // and the line truly flat. Record a value after a holding has really moved.
    const tile = page.getByTestId("heatmap-tile-TSLA");
    await expect.poll(async () => (await tileState(tile)).percent, { timeout: 20_000 }).not.toBe(0);
    await expect(await trade(page, "Sell", "TSLA", 1)).toHaveText(/^Sold 1 TSLA/);
    await expect(await trade(page, "Buy", "TSLA", 1)).toHaveText(/^Bought 1 TSLA/);

    const chart = page.getByTestId("pnl-chart");
    await expect.poll(async () => Number(await chart.getAttribute("data-points"))).toBeGreaterThan(1);
    await expect.poll(async () => (await plottedLine(chart)).rows).toBeGreaterThan(5);
    await expect.poll(async () => (await plottedLine(chart)).start).toBeLessThan(0.25);
  });
});
