import net from "node:net";
import { expect, open, test } from "./helpers";

const PROXY_PORT = 8765;

/** Sits between the browser and the server, so a test can really cut the line. */
function cuttableProxy(target: URL) {
  const sockets = new Set<net.Socket>();
  const server = net.createServer((client) => {
    const upstream = net.connect(Number(target.port), target.hostname);
    client.pipe(upstream).pipe(client);
    for (const socket of [client, upstream]) {
      sockets.add(socket);
      socket.on("error", () => undefined);
      socket.on("close", () => {
        sockets.delete(socket);
        client.destroy();
        upstream.destroy();
      });
    }
  });
  return {
    connect: () => new Promise<void>((done) => server.listen(PROXY_PORT, "127.0.0.1", done)),
    cut: () =>
      new Promise<void>((done) => {
        server.close(() => done());
        for (const socket of sockets) socket.destroy();
      }),
  };
}

test.describe("SSE resilience", () => {
  test("reconnects after the connection drops, and prices resume", async ({ page, baseURL }) => {
    const proxy = cuttableProxy(new URL(baseURL!));
    await proxy.connect();
    await open(page, `http://127.0.0.1:${PROXY_PORT}/`);
    const status = page.getByTestId("connection-status");

    await proxy.cut();
    await expect(status).toHaveAttribute("data-status", "reconnecting");

    // Long enough for at least one retry to fail against a dead connection
    await page.waitForTimeout(5_000);
    await proxy.connect();
    await expect(status).toHaveAttribute("data-status", "connected", { timeout: 15_000 });

    const prices = page.getByTestId("price");
    const before = await prices.allInnerTexts();
    await expect.poll(() => prices.allInnerTexts()).not.toEqual(before);
    await proxy.cut();
  });
});
