import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import type {
  HistoryCutoff,
  Portfolio,
  PortfolioAnalytics,
  PriceUpdate,
  WatchlistEntry,
} from "@/lib/types";
import { useMarket } from "@/lib/useMarket";
import { ChatPanel, Message } from "./ChatPanel";
import { Header } from "./Header";
import { AnalysisPanel } from "./AnalysisPanel";
import { Heatmap, tileColor, tileContent } from "./Heatmap";
import { correlationColor, RiskView } from "./RiskView";
import { SettingsMenu } from "./SettingsMenu";
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
    vi.spyOn(api, "bars").mockResolvedValue([]);
    render(<Watchlist entries={[entry]} prices={{}} selected={null} onSelect={onSelect} onChange={onChange} />);
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

  it("draws sparklines from stored bars, kept current by live prices", async () => {
    const bars = [100, 101, 102].map((close, i) => ({
      time: 60 * i,
      open: close,
      high: close,
      low: close,
      close,
      origin: "recorded" as const,
    }));
    vi.spyOn(api, "bars").mockResolvedValue(bars);
    const props = { entries: [entry], selected: null, onSelect: vi.fn(), onChange: vi.fn() };
    const { rerender } = render(<Watchlist {...props} prices={{}} />);
    const segments = () =>
      screen.getByTestId("sparkline").querySelector("path")?.getAttribute("d")?.split("L").length;
    await waitFor(() => expect(segments()).toBe(3));

    const live = { ...update(103), timestamp: 185 };
    rerender(<Watchlist {...props} prices={{ AAPL: live }} />);
    rerender(<Watchlist {...props} prices={{ AAPL: { ...live, price: 104 } }} />);
    expect(segments()).toBe(4);
    expect(api.bars).toHaveBeenCalledWith("AAPL", "1m", 60);
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

const settingsResponse = (cutoff: HistoryCutoff = "month", auto = true) => ({
  settings: { synthetic_history_cutoff: cutoff, analysis_panel_auto_switch: auto },
  choices: {
    synthetic_history_cutoff: ["never", "day", "week", "month", "quarter", "year"] as HistoryCutoff[],
    analysis_panel_auto_switch: [true, false],
  },
});

describe("SettingsMenu", () => {
  const response = (cutoff: HistoryCutoff, auto = true) => settingsResponse(cutoff, auto);

  it("loads on open and saves a change", async () => {
    vi.spyOn(api, "settings").mockResolvedValue(response("month"));
    const save = vi.spyOn(api, "updateSettings").mockResolvedValue(response("never"));
    render(<SettingsMenu />);
    expect(api.settings).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Settings" }));
    const select = screen.getByLabelText("Stop using simulated history after");
    await waitFor(() => expect(select).toHaveValue("month"));
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Never",
      "1 day",
      "1 week",
      "1 month",
      "1 quarter",
      "1 year",
    ]);

    await userEvent.selectOptions(select, "never");
    expect(save).toHaveBeenCalledWith({ synthetic_history_cutoff: "never" });
    await waitFor(() => expect(select).toHaveValue("never"));
  });

  it("turns the analysis auto-switch on and off", async () => {
    vi.spyOn(api, "settings").mockResolvedValue(response("month", true));
    const save = vi.spyOn(api, "updateSettings").mockResolvedValue(response("month", false));
    render(<SettingsMenu />);
    await userEvent.click(screen.getByRole("button", { name: "Settings" }));
    const box = screen.getByRole("checkbox", { name: /Show the analysis the assistant used/ });
    await waitFor(() => expect(box).toBeChecked());
    await userEvent.click(box);
    expect(save).toHaveBeenCalledWith({ analysis_panel_auto_switch: false });
    await waitFor(() => expect(box).not.toBeChecked());
  });

  it("shows why a save failed and closes on Escape", async () => {
    vi.spyOn(api, "settings").mockResolvedValue(response("month"));
    vi.spyOn(api, "updateSettings").mockRejectedValue(new Error("Unknown setting"));
    render(<SettingsMenu />);
    await userEvent.click(screen.getByRole("button", { name: "Settings" }));
    const select = screen.getByLabelText("Stop using simulated history after");
    await waitFor(() => expect(select).toHaveValue("month"));
    await userEvent.selectOptions(select, "day");
    expect(await screen.findByRole("alert")).toHaveTextContent("Unknown setting");
    expect(select).toHaveValue("month"); // Put back after the failed save

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByLabelText("Stop using simulated history after")).not.toBeInTheDocument();
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
    expect(screen.queryByTestId("chat-lookups")).not.toBeInTheDocument();
  });

  it("lists the lookups behind a reply", () => {
    const lookup = (name: string, args: Record<string, unknown>, status: "ok" | "failed" = "ok") => ({
      name,
      arguments: args,
      status,
      error: status === "ok" ? null : "No price history for ZZZZ.",
    });
    const actions = {
      trades: [],
      watchlist_changes: [],
      tool_calls: [
        lookup("get_indicators", { ticker: "nvda" }),
        lookup("get_bars", { ticker: "AAPL", timeframe: "1m" }),
        lookup("get_portfolio_risk", {}),
        lookup("get_correlations", {}),
        lookup("get_indicators", { ticker: "ZZZZ" }, "failed"),
      ],
    };
    render(<ul><Message message={{ role: "assistant", content: "Here you go", actions }} /></ul>);
    expect(screen.getByTestId("chat-lookups")).toHaveTextContent(
      "Analysis used: NVDA indicators (1d) · AAPL prices (1m) · portfolio risk · correlations · ZZZZ indicators (1d), unavailable",
    );
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

const risk: PortfolioAnalytics = {
  timeframe: "1d",
  returns: 252,
  as_of: 0,
  origins: { synthetic: 500 },
  total_value: 10000,
  cash_weight: 0.25,
  benchmark: "Equal-weighted watchlist (2 tickers)",
  correlation: { tickers: ["AAPL", "JPM"], matrix: [[1, 0.42], [0.42, 1]] },
  volatility: 0.2534,
  beta: 1.12,
  value_at_risk: {
    level: 0.95,
    horizon: "1 trading day",
    historical: { percent: 2.5, amount: 250 },
    parametric: { percent: 2.4, amount: 240 },
  },
  expected_shortfall: {
    level: 0.95,
    horizon: "1 trading day",
    historical: { percent: 3.1, amount: 310 },
    parametric: { percent: 3.0, amount: 300 },
  },
  positions: [{ ticker: "AAPL", weight: 0.75, volatility: 0.3, beta: 1.2 }],
  concentration: { top: { ticker: "AAPL", weight: 0.75 }, herfindahl: 1, effective_positions: 1 },
  performance: { max_drawdown: { percent: 1.5, peak_at: "", trough_at: "" }, sharpe: null, note: "needs a day" },
  notes: [],
};

describe("RiskView", () => {
  it("shows the figures, the correlation grid and what they were measured on", async () => {
    vi.spyOn(api, "portfolioAnalytics").mockResolvedValue(risk);
    render(<RiskView heading={<h2>Risk</h2>} positionsKey="AAPL:1" />);
    const view = await screen.findByTestId("risk-view");
    await waitFor(() => expect(view).toHaveTextContent("25.3%"));
    expect(view).toHaveTextContent("1.12");
    expect(view).toHaveTextContent("$250.00 · 2.50%");
    expect(view).toHaveTextContent("normal $240.00");
    expect(view).toHaveTextContent("AAPL 75.0%");
    expect(view).toHaveTextContent("cash 25.0%");
    const cells = screen.getAllByRole("cell", { name: ".4" });
    expect(cells.map((cell) => cell.title)).toEqual(["AAPL / JPM: 0.42", "JPM / AAPL: 0.42"]);
    expect(screen.getByTestId("risk-basis")).toHaveTextContent(
      "252 daily returns, including simulated history.",
    );
  });

  it("explains missing figures", async () => {
    const empty = {
      ...risk,
      volatility: null,
      beta: null,
      value_at_risk: null,
      expected_shortfall: null,
      concentration: null,
      origins: { recorded: 10 },
      notes: ["No positions: portfolio risk appears once you hold shares."],
    };
    vi.spyOn(api, "portfolioAnalytics").mockResolvedValue(empty);
    render(<RiskView heading={null} positionsKey="" />);
    expect(await screen.findByText(/No positions/)).toBeInTheDocument();
    expect(screen.getByTestId("risk-basis")).not.toHaveTextContent("simulated");
  });

  it("reloads when positions change", async () => {
    const load = vi.spyOn(api, "portfolioAnalytics").mockResolvedValue(risk);
    const { rerender } = render(<RiskView heading={null} positionsKey="" />);
    rerender(<RiskView heading={null} positionsKey="AAPL:1" />);
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  });

  it("colors correlation on a diverging scale with gray at zero", () => {
    expect(correlationColor(0)).toContain("0%");
    expect(correlationColor(0.5)).toContain("#d95926 50%");
    expect(correlationColor(-1)).toContain("#3987e5 100%");
    expect(correlationColor(null)).toBe("var(--color-tile-flat)");
  });
});

describe("AnalysisPanel", () => {
  const stubResize = () =>
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        disconnect() {}
      },
    );

  const setup = (auto: boolean) => {
    localStorage.clear();
    stubResize();
    vi.spyOn(api, "settings").mockResolvedValue(settingsResponse("month", auto));
    vi.spyOn(api, "portfolioAnalytics").mockResolvedValue(risk);
    const props = { portfolio, positionsKey: "", onSelect: vi.fn() };
    const view = render(<AnalysisPanel {...props} />);
    const request = (at: number) =>
      view.rerender(<AnalysisPanel {...props} viewRequest={{ view: "risk", at }} />);
    return { request };
  };

  it("switches between the heatmap and risk", async () => {
    setup(true);
    expect(screen.getByRole("heading")).toHaveTextContent("Holdings by weight and P&L");
    expect(api.portfolioAnalytics).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Risk" }));
    expect(screen.getByRole("button", { name: "Risk" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByTestId("risk-view")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Heatmap" }));
    expect(screen.getByTestId("heatmap")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("brings the requested view forward when auto-switch is on", async () => {
    const { request } = setup(true);
    await waitFor(() => expect(screen.getByRole("button", { name: "Auto" })).toHaveAttribute("aria-pressed", "true"));
    request(1);
    expect(await screen.findByTestId("risk-view")).toBeInTheDocument();

    // A manual choice stands until the next request
    await userEvent.click(screen.getByRole("button", { name: "Heatmap" }));
    expect(screen.getByTestId("heatmap")).toBeInTheDocument();
    request(2);
    expect(await screen.findByTestId("risk-view")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("stays put when auto-switch is off, and the toggle saves the setting", async () => {
    const { request } = setup(false);
    const auto = screen.getByRole("button", { name: "Auto" });
    await waitFor(() => expect(auto).toHaveAttribute("aria-pressed", "false"));
    request(1);
    expect(screen.getByTestId("heatmap")).toBeInTheDocument();

    const save = vi.spyOn(api, "updateSettings").mockResolvedValue(settingsResponse("month", true));
    await userEvent.click(auto);
    expect(save).toHaveBeenCalledWith({ analysis_panel_auto_switch: true });
    await waitFor(() => expect(auto).toHaveAttribute("aria-pressed", "true"));
    vi.unstubAllGlobals();
  });
});
