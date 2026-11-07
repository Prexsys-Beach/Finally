import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import type { Portfolio, PriceUpdate, WatchlistEntry } from "@/lib/types";
import { useMarket } from "@/lib/useMarket";
import { ChatPanel, Message } from "./ChatPanel";
import { Header } from "./Header";
import { Heatmap, tileColor, tileContent } from "./Heatmap";
import { PositionsTable } from "./PositionsTable";
import { TradeBar } from "./TradeBar";
import { Watchlist, WatchlistRow } from "./Watchlist";

const entry: WatchlistEntry = { ticker: "AAPL", added_at: "", price: 100, day_change_percent: 1 };
const update = (price: number) => ({ ticker: "AAPL", price, day_change_percent: 1 }) as PriceUpdate;
const position = {
  ticker: "AAPL",
  quantity: 2.5,
  avg_cost: 100,
  cost_basis: 250,
  current_price: 110,
  market_value: 275,
  unrealized_pnl: 25,
  unrealized_pnl_percent: 10,
  day_change_percent: 1,
};
const portfolio: Portfolio = {
  cash_balance: 725,
  positions: [position],
  positions_value: 275,
  total_value: 1000,
  unrealized_pnl: 25,
};

describe("WatchlistRow", () => {
  const row = (price: number) => (
    <ul>
      <WatchlistRow entry={entry} update={update(price)} points={undefined} selected={false} onSelect={vi.fn()} onRemove={vi.fn()} />
    </ul>
  );

  it("flashes on change, then clears so the color fades", () => {
    vi.useFakeTimers();
    const { rerender } = render(row(100));
    const price = screen.getByTestId("price");
    expect(price.className).not.toContain("flash");

    rerender(row(101));
    expect(price).toHaveClass("flash-up");
    act(() => void vi.advanceTimersByTime(200));
    expect(price.className).not.toContain("flash");

    rerender(row(99));
    expect(price).toHaveClass("flash-down");
    vi.useRealTimers();
  });

  it("does not flash when the price is unchanged", () => {
    const { rerender } = render(row(100));
    rerender(row(100));
    expect(screen.getByTestId("price").className).not.toContain("flash");
  });

  it("explains a ticker with no price", () => {
    render(
      <ul>
        <WatchlistRow entry={{ ...entry, price: null }} update={undefined} points={undefined} selected={false} onSelect={vi.fn()} onRemove={vi.fn()} />
      </ul>,
    );
    expect(screen.getByTestId("price")).toHaveTextContent("No price yet");
  });
});

describe("Watchlist", () => {
  const setup = () => {
    const onChange = vi.fn().mockResolvedValue(undefined);
    const onSelect = vi.fn();
    render(<Watchlist entries={[entry]} prices={{}} history={{}} selected={null} onSelect={onSelect} onChange={onChange} />);
    return { onChange, onSelect };
  };

  it("adds a ticker", async () => {
    const add = vi.spyOn(api, "addTicker").mockResolvedValue(undefined);
    const { onChange } = setup();
    await userEvent.type(screen.getByLabelText("Ticker to add"), "pypl{Enter}");
    expect(add).toHaveBeenCalledWith("PYPL");
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(screen.getByLabelText("Ticker to add")).toHaveValue("");
  });

  it("removes a ticker", async () => {
    const remove = vi.spyOn(api, "removeTicker").mockResolvedValue(undefined);
    setup();
    await userEvent.click(screen.getByRole("button", { name: "Remove AAPL from watchlist" }));
    expect(remove).toHaveBeenCalledWith("AAPL");
  });

  it("shows why an add failed", async () => {
    vi.spyOn(api, "addTicker").mockRejectedValue(new Error("AAPL is already on the watchlist"));
    setup();
    await userEvent.type(screen.getByLabelText("Ticker to add"), "AAPL{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("already on the watchlist");
  });

  it("selects a ticker on click", async () => {
    const { onSelect } = setup();
    await userEvent.click(screen.getByRole("button", { name: /^AAPL/ }));
    expect(onSelect).toHaveBeenCalledWith("AAPL");
  });
});

describe("TradeBar", () => {
  const filled = { id: "1", ticker: "AAPL", side: "buy" as const, quantity: 2, price: 100, executed_at: "" };

  it("buys the selected ticker and confirms", async () => {
    const trade = vi.spyOn(api, "trade").mockResolvedValue({ trade: filled, portfolio });
    const onTraded = vi.fn().mockResolvedValue(undefined);
    render(<TradeBar ticker="AAPL" onTraded={onTraded} />);

    await userEvent.type(screen.getByLabelText("Quantity"), "2");
    await userEvent.click(screen.getByRole("button", { name: "Buy" }));

    expect(trade).toHaveBeenCalledWith("AAPL", 2, "buy");
    expect(await screen.findByTestId("trade-result")).toHaveTextContent("Bought 2 AAPL at $100.00");
    expect(onTraded).toHaveBeenCalled();
  });

  it("shows the server's reason for a rejected trade", async () => {
    vi.spyOn(api, "trade").mockRejectedValue(new Error("Insufficient cash"));
    render(<TradeBar ticker="AAPL" onTraded={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Quantity"), "2");
    await userEvent.click(screen.getByRole("button", { name: "Sell" }));
    expect(await screen.findByTestId("trade-result")).toHaveTextContent("Insufficient cash");
  });

  it("disables trading without a valid quantity", async () => {
    render(<TradeBar ticker="AAPL" onTraded={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Buy" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Quantity"), "-1");
    expect(screen.getByRole("button", { name: "Buy" })).toBeDisabled();
  });

  it("lets the user type another ticker, and follows a new selection", async () => {
    const { rerender } = render(<TradeBar ticker="AAPL" onTraded={vi.fn()} />);
    const input = screen.getByLabelText("Ticker");
    await userEvent.clear(input);
    await userEvent.type(input, "msft");
    expect(input).toHaveValue("MSFT");
    rerender(<TradeBar ticker="NVDA" onTraded={vi.fn()} />);
    expect(input).toHaveValue("NVDA");
  });
});

describe("Header", () => {
  it("shows values, connection and data source", () => {
    render(<Header portfolio={portfolio} status="reconnecting" mode="simulated" />);
    expect(screen.getByTestId("total-value")).toHaveTextContent("$1,000.00");
    expect(screen.getByTestId("cash-balance")).toHaveTextContent("$725.00");
    expect(screen.getByTestId("connection-status")).toHaveTextContent("Reconnecting");
    expect(screen.getByTestId("data-mode")).toHaveTextContent("Simulated prices");
  });
});

describe("PositionsTable", () => {
  it("lists positions", () => {
    render(<PositionsTable positions={[position]} selected={null} onSelect={vi.fn()} />);
    const row = screen.getByTestId("position-AAPL");
    expect(row).toHaveTextContent("2.5");
    expect(row).toHaveTextContent("+$25.00");
    expect(row).toHaveTextContent("+10.00%");
  });

  it("guides a new user", () => {
    render(<PositionsTable positions={[]} selected={null} onSelect={vi.fn()} />);
    expect(screen.getByText(/No positions yet/)).toBeInTheDocument();
  });
});

describe("Heatmap", () => {
  it("colors by P&L direction and leaves zero neutral", () => {
    expect(tileColor(3)).toContain("tile-up");
    expect(tileColor(-3)).toContain("tile-down");
    expect(tileColor(0)).toBe("var(--color-tile-flat)");
    expect(tileColor(null)).toBe("var(--color-tile-flat)");
  });

  it("caps color strength", () => {
    expect(tileColor(50)).toBe(tileColor(5));
  });

  it("renders positions and cash once measured", async () => {
    let notify: ResizeObserverCallback = () => undefined;
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: ResizeObserverCallback) {
          notify = callback;
        }
        observe() {}
        disconnect() {}
      },
    );
    render(<Heatmap portfolio={portfolio} onSelect={vi.fn()} />);
    act(() => notify([{ contentRect: { width: 400, height: 300 } } as ResizeObserverEntry], {} as ResizeObserver));

    expect(screen.getByTestId("heatmap-tile-cash")).toHaveTextContent("Cash");
    expect(screen.getByTestId("heatmap-tile-AAPL")).toHaveTextContent("+10.00%");
    vi.unstubAllGlobals();
  });
});

describe("tileContent", () => {
  it("stacks the label and value in a large tile", () => {
    expect(tileContent("JPM", "+0.03%", 200, 100)).toBe("stacked");
  });

  it("keeps the value on one line in a short tile", () => {
    expect(tileContent("JPM", "+0.03%", 200, 40)).toBe("inline");
  });

  it("drops the value when only the label fits", () => {
    expect(tileContent("JPM", "+0.03%", 60, 40)).toBe("label");
  });

  it("shows nothing in a tile too small for text", () => {
    expect(tileContent("JPM", "+0.03%", 20, 100)).toBe("none");
    expect(tileContent("JPM", "+0.03%", 200, 20)).toBe("none");
  });
});

describe("Message", () => {
  it("shows executed and failed actions inline", () => {
    const actions = {
      trades: [
        { ticker: "AAPL", side: "buy" as const, quantity: 3, price: 100, status: "ok" as const, error: null },
        { ticker: "NVDA", side: "buy" as const, quantity: 9, price: null, status: "failed" as const, error: "Insufficient cash" },
      ],
      watchlist_changes: [{ ticker: "PYPL", action: "add" as const, status: "ok" as const, error: null }],
    };
    render(<ul><Message message={{ role: "assistant", content: "Done", actions }} /></ul>);
    const lines = screen.getAllByTestId("chat-action").map((node) => node.textContent);
    expect(lines).toEqual(["✓ Added PYPL to watchlist", "✓ Bought 3 AAPL at $100.00", "✕ Didn't buy 9 NVDA"]);
  });
});

describe("ChatPanel", () => {
  const setup = () => {
    const onActions = vi.fn().mockResolvedValue(undefined);
    render(<ChatPanel open onToggle={vi.fn()} onActions={onActions} />);
    return onActions;
  };

  it("loads earlier messages", async () => {
    vi.spyOn(api, "chatHistory").mockResolvedValue([{ role: "user", content: "earlier", actions: null }]);
    setup();
    expect(await screen.findByText("earlier")).toBeInTheDocument();
  });

  it("shows a loading state, then the reply, then refreshes the account", async () => {
    vi.spyOn(api, "chatHistory").mockResolvedValue([]);
    let reply: (value: Awaited<ReturnType<typeof api.chat>>) => void = () => undefined;
    vi.spyOn(api, "chat").mockReturnValue(new Promise((resolve) => (reply = resolve)));
    const onActions = setup();

    await userEvent.type(screen.getByLabelText("Message the assistant"), "hello{Enter}");
    expect(screen.getByTestId("chat-loading")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

    await act(async () => reply({ message: "Hi there", trades: [], watchlist_changes: [] }));
    expect(screen.getByText("Hi there")).toBeInTheDocument();
    expect(screen.queryByTestId("chat-loading")).not.toBeInTheDocument();
    expect(onActions).toHaveBeenCalled();
  });

  it("returns the text for retry when the assistant fails", async () => {
    vi.spyOn(api, "chatHistory").mockResolvedValue([]);
    vi.spyOn(api, "chat").mockRejectedValue(new Error("The assistant is unavailable right now."));
    setup();

    await userEvent.type(screen.getByLabelText("Message the assistant"), "hello{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("unavailable");
    expect(screen.getByLabelText("Message the assistant")).toHaveValue("hello");
    expect(screen.queryByTestId("chat-user")).not.toBeInTheDocument();
  });
});

describe("useMarket", () => {
  class FakeEventSource {
    static CLOSED = 2;
    static instance: FakeEventSource;
    readyState = 0;
    onopen = () => {};
    onerror = () => {};
    onmessage: (event: { data: string }) => void = () => {};
    close = vi.fn();
    constructor() {
      FakeEventSource.instance = this;
    }
  }

  function Probe() {
    const { prices, status, history } = useMarket();
    return <p>{`${status} ${prices.AAPL?.price ?? "none"} ${history.AAPL?.length ?? 0}`}</p>;
  }

  it("tracks connection state and accumulates prices", () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const { unmount } = render(<Probe />);
    const source = FakeEventSource.instance;
    expect(screen.getByText("reconnecting none 0")).toBeInTheDocument();

    act(() => source.onopen());
    expect(screen.getByText("connected none 0")).toBeInTheDocument();

    act(() => source.onmessage({ data: JSON.stringify({ AAPL: update(100) }) }));
    expect(screen.getByText("connected 100 1")).toBeInTheDocument();

    act(() => source.onerror());
    expect(screen.getByText("reconnecting 100 1")).toBeInTheDocument();

    source.readyState = FakeEventSource.CLOSED;
    act(() => source.onerror());
    expect(screen.getByText("disconnected 100 1")).toBeInTheDocument();

    unmount();
    expect(source.close).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
