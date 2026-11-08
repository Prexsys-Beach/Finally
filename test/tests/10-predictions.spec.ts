import type { Page } from "@playwright/test";
import { expect, open, test } from "./helpers";

async function send(page: Page, text: string) {
  await page.getByLabel("Message the assistant").fill(text);
  await page.getByLabel("Message the assistant").press("Enter");
  await expect(page.getByTestId("chat-loading")).toHaveCount(0);
}

test.describe("prediction journal (mock LLM)", () => {
  test("a prediction is recorded, shown in chat and on the scorecard", async ({ page }) => {
    await open(page);
    await page.getByRole("group", { name: "Analysis view" }).getByRole("button", { name: "Heatmap" }).click();
    await expect(page.getByRole("button", { name: "Auto" })).toHaveAttribute("aria-pressed", "true");

    await send(page, "predict NVDA up 70% 30m");
    await expect(page.getByTestId("chat-action").last()).toHaveText(
      "✓ Predicted NVDA up over 30 min · 70% confidence",
    );

    // The reply made a prediction, so the scorecard comes forward
    const scorecard = page.getByTestId("scorecard-view");
    await expect(scorecard).toBeVisible();
    await expect(scorecard).toContainText("These prices are simulated");
    const row = page.getByTestId("prediction-list").locator("tbody tr").first();
    await expect(row).toContainText("NVDA ↑ 70%");
    await expect(row).toContainText("30 min");
    await expect(row).toContainText("Pending");

    // A call on an untracked ticker is refused and explained
    await send(page, "predict ZZZZ down");
    await expect(page.getByTestId("chat-action").last()).toHaveText("✕ Didn't record a prediction for ZZZZ");
    await expect(page.getByTestId("chat-assistant").last()).toContainText("ZZZZ isn't tracked");

    await page.reload();
    await expect(page.getByTestId("scorecard-view")).toBeVisible();
    await expect(page.getByTestId("prediction-list").locator("tbody tr")).toHaveCount(1);
  });

  test("the journal API serves stats per data mode", async ({ request }) => {
    const stats = await (await request.get("/api/predictions/stats")).json();
    expect(stats.modes.simulated.assistant.made).toBeGreaterThan(0);
    expect(stats.modes.simulated.baseline.made).toBe(stats.modes.simulated.assistant.made);
  });
});
