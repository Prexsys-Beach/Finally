import { expect, type Locator, type Page, test as base } from "@playwright/test";

/** Every test fails on an uncaught browser error, whatever it was checking. */
export const test = base.extend<{ failOnPageError: void }>({
  failOnPageError: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await use();
      expect(errors, "uncaught browser errors").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

export const money = (text: string) => Number(text.replace(/[^0-9.]/g, ""));

export async function open(page: Page, url = "/") {
  await page.goto(url);
  await expect(page.getByTestId("watchlist-row-AAPL")).toBeVisible();
  await expect(page.getByTestId("connection-status")).toHaveAttribute("data-status", "connected");
}

export async function cash(page: Page) {
  const text = await page.getByTestId("cash-balance").innerText();
  return money(text);
}

export async function trade(page: Page, side: "Buy" | "Sell", ticker: string, quantity: number) {
  const bar = page.getByRole("form", { name: "Trade" });
  await bar.getByLabel("Ticker", { exact: true }).fill(ticker);
  await bar.getByLabel("Quantity").fill(String(quantity));
  await bar.getByRole("button", { name: side, exact: true }).click();
  return page.getByTestId("trade-result");
}

/**
 * Measures the plotted line from its pixels. The axis label and last-price line
 * share its color, so only the plot canvas is read. `start` also has to skip the
 * dotted last-price line, which spans the whole width, so a pixel counts only if
 * it belongs to a solid stroke: a horizontal run for flat stretches, or the pixel
 * below for steep ones. A flat line can blur across two rows, so neither test
 * works alone.
 *   rows:  pixel rows crossed, which is only many if the line really moves
 *   start: where the line begins, as a fraction of the plot's width
 */
export async function plottedLine(chart: Locator) {
  return chart.evaluate((element) => {
    const plot = [...element.querySelectorAll("canvas")].sort(
      (a, b) => b.width * b.height - a.width * a.height,
    )[0];
    if (!plot?.width || !plot.height) return { rows: 0, start: 1 };
    const { data, width, height } = plot
      .getContext("2d", { willReadFrequently: true })!
      .getImageData(0, 0, plot.width, plot.height);
    const matches = (x: number, y: number) => {
      const i = (y * width + x) * 4;
      return (
        Math.abs(data[i] - 0x20) < 16 &&
        Math.abs(data[i + 1] - 0x9d) < 16 &&
        Math.abs(data[i + 2] - 0xd7) < 16 &&
        data[i + 3] > 200
      );
    };
    let rows = 0;
    let start = width;
    for (let y = 0; y < height - 1; y += 1) {
      let crossed = false;
      for (let x = 0; x < width; x += 1) {
        if (!matches(x, y)) continue;
        crossed = true;
        const flat = [1, 2, 3].every((step) => x + step < width && matches(x + step, y));
        if (flat || matches(x, y + 1)) start = Math.min(start, x);
      }
      if (crossed) rows += 1;
    }
    return { rows, start: start / width };
  });
}

/** Heatmap tiles whose text doesn't fit inside them. */
export async function clippedTiles(page: Page) {
  return page.getByTestId("heatmap").evaluate((heatmap) =>
    [...heatmap.children]
      .filter((tile) => tile.scrollHeight > tile.clientHeight || tile.scrollWidth > tile.clientWidth)
      .map((tile) => tile.getAttribute("data-testid")),
  );
}

/** A heatmap tile's percent and painted color, read at the same moment. */
export async function tileState(tile: Locator) {
  return tile.evaluate((element) => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const context = canvas.getContext("2d")!;
    context.fillStyle = getComputedStyle(element).backgroundColor;
    context.fillRect(0, 0, 1, 1);
    const [red, green] = context.getImageData(0, 0, 1, 1).data;
    const match = (element.getAttribute("title") ?? "").match(/([+−]?)(\d+\.\d+)%,/);
    const size = Number(match?.[2] ?? 0);
    return { percent: match?.[1] === "−" ? -size : size, red, green };
  });
}
