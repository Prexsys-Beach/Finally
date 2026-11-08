import type { Page } from "@playwright/test";
import { expect, open, test } from "./helpers";

async function send(page: Page, text: string) {
  await page.getByLabel("Message the assistant").fill(text);
  await page.getByLabel("Message the assistant").press("Enter");
  await expect(page.getByTestId("chat-loading")).toHaveCount(0);
}

test.describe("assistant lookups (mock LLM)", () => {
  test("a reply lists its lookups and brings the Risk view forward", async ({ page }) => {
    await open(page);
    const views = page.getByRole("group", { name: "Analysis view" });
    await views.getByRole("button", { name: "Heatmap" }).click();
    await expect(page.getByTestId("heatmap")).toBeVisible();
    await expect(page.getByRole("button", { name: "Auto" })).toHaveAttribute("aria-pressed", "true");

    await send(page, "analyze NVDA and check my risk");
    await expect(page.getByTestId("chat-lookups").last()).toHaveText(
      "Analysis used: NVDA indicators (1d) · portfolio risk",
    );
    await expect(page.getByTestId("risk-view")).toBeVisible();

    // A reply that only reads indicators leaves the view alone
    await views.getByRole("button", { name: "Heatmap" }).click();
    await send(page, "analyze AAPL");
    await expect(page.getByTestId("chat-lookups").last()).toHaveText("Analysis used: AAPL indicators (1d)");
    await expect(page.getByTestId("heatmap")).toBeVisible();

    // Lookups are stored with the conversation
    await page.reload();
    await expect(page.getByTestId("chat-lookups")).toHaveCount(2);
  });

  test("with auto-switch off, the view stays put", async ({ page }) => {
    await open(page);
    const auto = page.getByRole("button", { name: "Auto" });
    await page.getByRole("group", { name: "Analysis view" }).getByRole("button", { name: "Heatmap" }).click();
    await auto.click();
    await expect(auto).toHaveAttribute("aria-pressed", "false");

    await send(page, "what is my risk?");
    await expect(page.getByTestId("chat-lookups").last()).toHaveText("Analysis used: portfolio risk");
    await expect(page.getByTestId("heatmap")).toBeVisible();

    // The settings menu shows the same setting
    await page.getByRole("button", { name: "Settings" }).click();
    const box = page.getByRole("checkbox", { name: /Show the analysis the assistant used/ });
    await expect(box).not.toBeChecked();
    await box.check();
    await expect(auto).toHaveAttribute("aria-pressed", "true");
  });
});
