import { cash, expect, money, open, test, trade } from "./helpers";

test.describe("trading", () => {
  test("buying moves cash into a position, and selling all closes it", async ({ page }) => {
    await open(page);
    const start = await cash(page);

    const bought = await trade(page, "Buy", "MSFT", 5);
    await expect(bought).toHaveText(/^Bought 5 MSFT at \$[\d,.]+$/);
    const price = money((await bought.innerText()).split(" at ")[1]);
    await expect.poll(() => cash(page)).toBeCloseTo(start - 5 * price, 1);

    const position = page.getByTestId("position-MSFT");
    await expect(position.getByRole("cell").nth(0)).toHaveText("5");
    await expect(position.getByRole("cell").nth(1)).toHaveText(`$${price.toLocaleString("en-US", { minimumFractionDigits: 2 })}`);

    const partial = await trade(page, "Sell", "MSFT", 2);
    await expect(partial).toHaveText(/^Sold 2 MSFT at /);
    await expect(position.getByRole("cell").nth(0)).toHaveText("3");

    await expect(await trade(page, "Sell", "MSFT", 3)).toHaveText(/^Sold 3 MSFT at /);
    await expect(position).toHaveCount(0);
    await expect.poll(() => cash(page)).toBeGreaterThan(start * 0.9);
  });

  test("refuses a buy larger than the cash balance", async ({ page }) => {
    await open(page);
    const start = await cash(page);
    await expect(await trade(page, "Buy", "NVDA", 1_000_000)).toContainText(/cash/i);
    await expect(page.getByTestId("position-NVDA")).toHaveCount(0);
    expect(await cash(page)).toBe(start);
  });

  test("refuses to sell shares that aren't held", async ({ page }) => {
    await open(page);
    const start = await cash(page);
    await expect(await trade(page, "Sell", "META", 1)).toContainText(/shares/i);
    expect(await cash(page)).toBe(start);
  });
});
