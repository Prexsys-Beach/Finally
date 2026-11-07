import { expect, open, plottedLine, test } from "./helpers";

const DEFAULTS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"];

test.describe("fresh start", () => {
  test("shows the default watchlist and $10,000", async ({ page }) => {
    await open(page);
    for (const ticker of DEFAULTS) {
      const row = page.getByTestId(`watchlist-row-${ticker}`);
      await expect(row.getByTestId("price")).toHaveText(/^\$[\d,]+\.\d{2}$/);
    }
    await expect(page.getByTestId("cash-balance")).toContainText("$10,000.00");
    await expect(page.getByTestId("total-value")).toContainText("$10,000.00");
    await expect(page.getByTestId("data-mode")).toHaveText("Simulated prices");
    await expect(page.getByTestId("positions-table")).toHaveCount(0);
    await expect(page.getByTestId("heatmap-tile-cash")).toBeVisible();
  });

  test("streams changing prices and fills in sparklines", async ({ page }) => {
    await open(page);
    const prices = page.getByTestId("price");
    const before = await prices.allInnerTexts();
    await expect.poll(() => prices.allInnerTexts()).not.toEqual(before);

    const sparkline = page.getByTestId("sparkline").locator("path").first();
    await expect.poll(async () => {
      const path = await sparkline.getAttribute("d");
      return path?.split("L").length ?? 0;
    }).toBeGreaterThan(2);
  });

  test("selecting a ticker draws its price chart", async ({ page }) => {
    await open(page);
    const row = page.getByTestId("watchlist-row-MSFT");
    await row.getByRole("button", { name: /^MSFT/ }).click();
    await expect(page.getByTestId("chart-ticker")).toHaveText("MSFT");
    await expect(row.getByRole("button", { name: /^MSFT/ })).toHaveAttribute("aria-pressed", "true");
    const chart = page.getByTestId("price-chart");
    await expect.poll(async () => (await plottedLine(chart)).rows).toBeGreaterThan(5);
  });
});
