import type { Page } from "@playwright/test";
import { expect, open, test, trade } from "./helpers";

async function send(page: Page, text: string) {
  await page.getByLabel("Message the assistant").fill(text);
  await page.getByLabel("Message the assistant").press("Enter");
  await expect(page.getByTestId("chat-loading")).toHaveCount(0);
}

test.describe("forecasts", () => {
  test("the P&L chart shows a forecast fan for the chosen horizon", async ({ page }) => {
    await open(page);
    await expect(await trade(page, "Buy", "MSFT", 2)).toContainText("Bought");

    const horizons = page.getByRole("group", { name: "Forecast" });
    const loaded = page.waitForResponse((r) => r.url().includes("/api/analytics/forecast") && r.ok());
    await horizons.getByRole("button", { name: "1d" }).click();
    await loaded;
    const summary = page.getByTestId("forecast-summary");
    await expect(summary).toHaveText(
      /^1 day: 90% between \$[\d,]+\.\d{2} and \$[\d,]+\.\d{2} · median \$[\d,]+\.\d{2} · \d+% chance of a loss$/,
    );

    await horizons.getByRole("button", { name: "1w" }).click();
    await expect(summary).toContainText("1 week: 90% between");

    // The choice survives a reload; clicking it again hides the fan
    await page.reload();
    await expect(page.getByTestId("forecast-summary")).toContainText("1 week");
    await page.getByRole("group", { name: "Forecast" }).getByRole("button", { name: "1w" }).click();
    await expect(page.getByTestId("forecast-summary")).toHaveCount(0);
  });

  test("the assistant can run a forecast", async ({ page }) => {
    await open(page);
    await send(page, "forecast my portfolio");
    await expect(page.getByTestId("chat-lookups").last()).toHaveText("Analysis used: portfolio forecast (1d)");
  });
});
