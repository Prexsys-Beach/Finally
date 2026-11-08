import { expect, open, plottedLine, test } from "./helpers";

test.describe("price history", () => {
  test("the chart opens with history and switches ranges", async ({ page }) => {
    await open(page);
    const chart = page.getByTestId("price-chart");
    const ranges = page.getByRole("group", { name: "Chart range" });
    await expect(ranges.getByRole("button", { name: "1D" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("synthetic-history")).toBeVisible();
    // History spans the whole width at once, rather than filling in from the left
    await expect.poll(async () => (await plottedLine(chart)).start).toBeLessThan(0.05);

    await ranges.getByRole("button", { name: "1Y" }).click();
    await expect(ranges.getByRole("button", { name: "1Y" })).toHaveAttribute("aria-pressed", "true");
    await expect.poll(async () => (await plottedLine(chart)).rows).toBeGreaterThan(5);

    await ranges.getByRole("button", { name: "Live" }).click();
    await expect(page.getByTestId("synthetic-history")).toHaveCount(0);
  });

  test("bars are served for every default ticker", async ({ request }) => {
    for (const ticker of ["AAPL", "NFLX"]) {
      const body = await (await request.get(`/api/market/bars/${ticker}?timeframe=1d&limit=400`)).json();
      expect(body.bars.length).toBeGreaterThan(300);
    }
  });

  test("the history cutoff setting is saved", async ({ page }) => {
    await open(page);
    await page.getByRole("button", { name: "Settings" }).click();
    const select = page.getByLabel("Stop using simulated history after");
    await expect(select).toHaveValue("month");
    await select.selectOption("quarter");
    await page.reload();
    await page.getByRole("button", { name: "Settings" }).click();
    await expect(page.getByLabel("Stop using simulated history after")).toHaveValue("quarter");
    await page.getByLabel("Stop using simulated history after").selectOption("month");
  });
});
