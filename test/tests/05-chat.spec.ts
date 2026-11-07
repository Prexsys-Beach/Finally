import { cash, expect, open, test } from "./helpers";
import type { Page } from "@playwright/test";

async function send(page: Page, text: string) {
  await page.getByLabel("Message the assistant").fill(text);
  await page.getByLabel("Message the assistant").press("Enter");
}

test.describe("AI chat (mock LLM)", () => {
  test("shows a loading state, then the reply", async ({ page }) => {
    await open(page);
    await page.route("**/api/chat", async (route) => {
      if (route.request().method() === "POST") await new Promise((done) => setTimeout(done, 800));
      await route.continue();
    });
    await send(page, "hello there");
    await expect(page.getByTestId("chat-loading")).toBeVisible();
    await expect(page.getByTestId("chat-assistant").last()).toContainText("Mock response");
    await expect(page.getByTestId("chat-loading")).toHaveCount(0);
  });

  test("executes a trade and shows it inline", async ({ page }) => {
    await open(page);
    const start = await cash(page);
    await send(page, "buy 2 AMZN");
    await expect(page.getByTestId("chat-action").last()).toHaveText(/^✓ Bought 2 AMZN at \$/);
    await expect(page.getByTestId("position-AMZN")).toBeVisible();
    await expect.poll(() => cash(page)).toBeLessThan(start);

    await send(page, "sell 2 AMZN");
    await expect(page.getByTestId("chat-action").last()).toHaveText(/^✓ Sold 2 AMZN at \$/);
    await expect(page.getByTestId("position-AMZN")).toHaveCount(0);
  });

  test("reports a trade that fails validation", async ({ page }) => {
    await open(page);
    const start = await cash(page);
    await send(page, "buy 1000000 AAPL");
    await expect(page.getByTestId("chat-action").last()).toHaveText("✕ Didn't buy 1,000,000 AAPL");
    expect(await cash(page)).toBe(start);
  });

  test("changes the watchlist", async ({ page }) => {
    await open(page);
    const row = page.getByTestId("watchlist-row-SHOP");
    await send(page, "add SHOP");
    await expect(page.getByTestId("chat-action").last()).toHaveText("✓ Added SHOP to watchlist");
    await expect(row).toBeVisible();
    await send(page, "remove SHOP");
    await expect(page.getByTestId("chat-action").last()).toHaveText("✓ Removed SHOP from watchlist");
    await expect(row).toHaveCount(0);
  });

  test("keeps the conversation across a reload", async ({ page }) => {
    await open(page);
    await send(page, "remember this message");
    await expect(page.getByTestId("chat-user").last()).toHaveText("remember this message");
    await expect(page.getByTestId("chat-assistant").last()).toContainText("Mock response");
    await page.reload();
    await expect(page.getByTestId("chat-user").last()).toHaveText("remember this message");
  });

  test("panel collapses and reopens", async ({ page }) => {
    await open(page);
    const input = page.getByLabel("Message the assistant");
    await page.getByRole("button", { name: "Hide" }).click();
    await expect(input).toHaveCount(0);
    await page.getByRole("button", { name: "Open assistant" }).click();
    await expect(input).toBeVisible();
  });
});
