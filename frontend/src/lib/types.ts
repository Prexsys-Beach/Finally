export type Direction = "up" | "down" | "flat";
export type Side = "buy" | "sell";
export type ConnectionStatus = "connected" | "reconnecting" | "disconnected";
export type DataMode = "simulated" | "seeded" | "live" | "eod";

export interface PriceUpdate {
  ticker: string;
  price: number;
  previous_price: number;
  timestamp: number;
  change: number;
  change_percent: number;
  direction: Direction;
  previous_close: number | null;
  day_change_percent: number | null;
}

export type Timeframe = "1m" | "1d";
export type BarOrigin = "recorded" | "synthetic" | "vendor";

export interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  origin: BarOrigin;
}

export type HistoryCutoff = "never" | "day" | "week" | "month" | "quarter" | "year";

export interface Settings {
  synthetic_history_cutoff: HistoryCutoff;
}

export interface SettingsResponse {
  settings: Settings;
  choices: { [K in keyof Settings]: Settings[K][] };
}

export interface PricePoint {
  time: number;
  value: number;
}

export interface WatchlistEntry {
  ticker: string;
  added_at: string;
  price: number | null;
  day_change_percent: number | null;
}

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  cost_basis: number;
  current_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_percent: number | null;
  day_change_percent: number | null;
}

export interface Portfolio {
  cash_balance: number;
  positions: Position[];
  positions_value: number;
  total_value: number;
  unrealized_pnl: number;
}

export interface Snapshot {
  total_value: number;
  recorded_at: string;
}

export interface Trade {
  id: string;
  ticker: string;
  side: Side;
  quantity: number;
  price: number;
  executed_at: string;
}

export interface TradeResult {
  ticker: string;
  side: Side;
  quantity: number;
  price: number | null;
  status: "ok" | "failed";
  error: string | null;
}

export interface WatchlistResult {
  ticker: string;
  action: "add" | "remove";
  status: "ok" | "failed";
  error: string | null;
}

export interface ChatActions {
  trades: TradeResult[];
  watchlist_changes: WatchlistResult[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  actions: ChatActions | null;
}

export interface Health {
  market_data: { mode: DataMode };
}
