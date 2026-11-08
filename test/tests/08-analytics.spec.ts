import { expect, open, test, trade } from "./helpers";

test.describe("analytics", () => {
  test("risk view measures the portfolio after a trade", async ({ page }) => {
    await open(page);
    await expect(await trade(page, "Buy", "NVDA", 3)).toContainText("Bought");

    const views = page.getByRole("group", { name: "Analysis view" });
    await views.getByRole("button", { name: "Risk" }).click();
    const risk = page.getByTestId("risk-view");
    await expect(risk).toContainText(/1-day VaR 95%\$[\d,]+\.\d{2} · \d+\.\d{2}%/);
    await expect(risk).toContainText(/Largest positionNVDA \d+\.\d%/);
    await expect(page.getByTestId("correlation-matrix").getByRole("rowheader")).toHaveCount(10);
    await expect(page.getByTestId("risk-basis")).toContainText("daily returns");

    // The choice of view survives a reload
    await page.reload();
    await expect(page.getByTestId("risk-view")).toBeVisible();
  });

  test("indicators draw on the chart, with RSI and MACD in their own panes", async ({ page }) => {
    await open(page);
    const chart = page.getByTestId("price-chart");
    const indicators = page.getByRole("group", { name: "Indicators" });
    const canvases = () => chart.locator("canvas").count();
    const before = await canvases();

    const analytics = page.waitForResponse((r) => r.url().includes("/api/analytics/ticker/"));
    await indicators.getByRole("button", { name: "SMA" }).click();
    expect((await analytics).ok()).toBe(true);
    await expect(indicators.getByRole("button", { name: "SMA" })).toHaveAttribute("aria-pressed", "true");

    await indicators.getByRole("button", { name: "RSI" }).click();
    await indicators.getByRole("button", { name: "MACD" }).click();
    await expect.poll(canvases).toBeGreaterThan(before);

    await indicators.getByRole("button", { name: "RSI" }).click();
    await indicators.getByRole("button", { name: "MACD" }).click();
    await expect.poll(canvases).toBe(before);

    await page.getByRole("group", { name: "Chart range" }).getByRole("button", { name: "Live" }).click();
    await expect(indicators.getByRole("button", { name: "SMA" })).toBeDisabled();
  });
});
