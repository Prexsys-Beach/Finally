import type {
  Bar,
  ChatActions,
  ChatMessage,
  Health,
  Portfolio,
  PortfolioAnalytics,
  Settings,
  SettingsResponse,
  Side,
  Snapshot,
  TickerAnalytics,
  Timeframe,
  Trade,
  WatchlistEntry,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: init?.body ? { "content-type": "application/json" } : undefined,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : null;
    throw new Error(detail ?? `Request failed with status ${response.status}`);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => request<Health>("/api/health"),
  portfolio: () => request<Portfolio>("/api/portfolio"),
  history: () =>
    request<{ snapshots: Snapshot[] }>("/api/portfolio/history").then((r) => r.snapshots),
  watchlist: () =>
    request<{ tickers: WatchlistEntry[] }>("/api/watchlist").then((r) => r.tickers),
  addTicker: (ticker: string) => post("/api/watchlist", { ticker }),
  removeTicker: (ticker: string) =>
    request<void>(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" }),
  trade: (ticker: string, quantity: number, side: Side) =>
    post<{ trade: Trade; portfolio: Portfolio }>("/api/portfolio/trade", {
      ticker,
      quantity,
      side,
    }),
  chatHistory: () =>
    request<{ messages: ChatMessage[] }>("/api/chat").then((r) => r.messages),
  chat: (message: string) =>
    post<ChatActions & { message: string }>("/api/chat", { message }),
  bars: (ticker: string, timeframe: Timeframe, limit: number) =>
    request<{ bars: Bar[] }>(
      `/api/market/bars/${encodeURIComponent(ticker)}?timeframe=${timeframe}&limit=${limit}`,
    ).then((r) => r.bars),
  settings: () => request<SettingsResponse>("/api/settings"),
  tickerAnalytics: (ticker: string, timeframe: Timeframe, limit: number) =>
    request<TickerAnalytics>(
      `/api/analytics/ticker/${encodeURIComponent(ticker)}?timeframe=${timeframe}&limit=${limit}`,
    ),
  portfolioAnalytics: (timeframe: Timeframe = "1d") =>
    request<PortfolioAnalytics>(`/api/analytics/portfolio?timeframe=${timeframe}`),
  updateSettings: (changes: Partial<Settings>) =>
    request<SettingsResponse>("/api/settings", { method: "PUT", body: JSON.stringify(changes) }),
};
