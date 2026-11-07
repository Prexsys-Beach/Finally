import { expect, open, test } from "./helpers";

test.describe("watchlist", () => {
  test("adds a ticker, keeps it across a reload, then removes it", async ({ page }) => {
    await open(page);
    await page.getByLabel("Ticker to add").fill("pypl");
    await page.getByLabel("Ticker to add").press("Enter");

    const row = page.getByTestId("watchlist-row-PYPL");
    await expect(row.getByTestId("price")).toHaveText(/^\$[\d,]+\.\d{2}$/);

    await page.reload();
    await expect(row).toBeVisible();

    await page.getByRole("button", { name: "Remove PYPL from watchlist" }).click();
    await expect(row).toHaveCount(0);

    await page.reload();
    await expect(page.getByTestId("watchlist-row-AAPL")).toBeVisible();
    await expect(row).toHaveCount(0);
  });

  test("refuses a duplicate ticker", async ({ page }) => {
    await open(page);
    await page.getByLabel("Ticker to add").fill("AAPL");
    await page.getByLabel("Ticker to add").press("Enter");
    await expect(page.getByRole("complementary", { name: "Watchlist" }).getByRole("alert")).toContainText(
      "already on the watchlist",
    );
    await expect(page.getByTestId("watchlist-row-AAPL")).toHaveCount(1);
  });
});
