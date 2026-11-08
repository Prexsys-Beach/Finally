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
  analysis_panel_auto_switch: boolean;
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

export interface ToolCallRecord {
  name: string;
  arguments: Record<string, unknown>;
  status: "ok" | "failed";
  error: string | null;
}

export type CallDirection = "up" | "down";

export interface PredictionResult {
  id: string | null;
  ticker: string;
  direction: CallDirection;
  confidence: number;
  horizon_minutes: number;
  reference_price: number | null;
  resolves_at: string | null;
  status: "ok" | "failed";
  error: string | null;
}

export interface ChatActions {
  trades: TradeResult[];
  watchlist_changes: WatchlistResult[];
  /** Absent on messages stored before the prediction journal */
  predictions?: PredictionResult[];
  /** Absent on messages stored before the assistant had tools */
  tool_calls?: ToolCallRecord[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  actions: ChatActions | null;
}

export interface Health {
  market_data: { mode: DataMode };
}

export interface IndicatorSeries {
  time: number[];
  sma_20: (number | null)[];
  ema_50: (number | null)[];
  bollinger_upper: (number | null)[];
  bollinger_lower: (number | null)[];
  rsi_14: (number | null)[];
  macd: (number | null)[];
  macd_signal: (number | null)[];
  macd_histogram: (number | null)[];
}

export interface TickerAnalytics {
  ticker: string;
  timeframe: Timeframe;
  bars: number;
  origins: Partial<Record<BarOrigin, number>>;
  latest: Record<string, number | null> | null;
  signals: Record<string, string | null> | null;
  series: IndicatorSeries | null;
}

export interface MoneyFigure {
  percent: number;
  amount: number;
}

export interface TailRisk {
  level: number;
  horizon: string;
  historical: MoneyFigure | null;
  parametric: MoneyFigure | null;
}

export interface PositionRisk {
  ticker: string;
  weight: number;
  volatility: number | null;
  beta: number | null;
}

export interface PortfolioAnalytics {
  timeframe: Timeframe;
  returns: number;
  as_of: number | null;
  origins: Partial<Record<BarOrigin, number>>;
  total_value: number;
  cash_weight: number | null;
  benchmark: string;
  correlation: { tickers: string[]; matrix: (number | null)[][] | null };
  volatility: number | null;
  beta: number | null;
  value_at_risk: TailRisk | null;
  expected_shortfall: TailRisk | null;
  positions: PositionRisk[];
  concentration: {
    top: { ticker: string; weight: number };
    herfindahl: number;
    effective_positions: number;
  } | null;
  performance: {
    max_drawdown: { percent: number; peak_at: string; trough_at: string } | null;
    sharpe: number | null;
    note: string | null;
  };
  notes: string[];
}

export type Outcome = "hit" | "miss" | "void";

export interface PredictionRecord {
  id: string;
  ticker: string;
  direction: CallDirection;
  confidence: number;
  horizon_minutes: number;
  reference_price: number;
  data_mode: DataMode;
  made_at: string;
  resolves_at: string;
  resolved_price: number | null;
  outcome: Outcome | null;
  note: string | null;
  baseline_direction: CallDirection | null;
  baseline_outcome: Outcome | null;
}

export interface PredictionScore {
  made: number;
  settled: number;
  hits: number;
  void: number;
  pending: number;
  hit_rate: number | null;
  hit_rate_interval: [number, number] | null;
  brier: number | null;
  calibration: { range: [number, number]; count: number; stated: number; observed: number }[];
}

export interface PredictionStats {
  modes: Partial<Record<DataMode, { assistant: PredictionScore; baseline: PredictionScore }>>;
}

export type ForecastHorizon = "1h" | "1d" | "1w";

export interface Forecast {
  target: string;
  horizon: ForecastHorizon;
  horizon_label: string;
  data_mode: DataMode;
  as_of: number;
  current_value: number;
  times: number[];
  bands: Record<"p5" | "p25" | "p50" | "p75" | "p95", number[]>;
  probability_of_loss: number;
  expected_shortfall_5: number;
  volatility: number | null;
  returns_used: number;
  origins: Partial<Record<BarOrigin, number>>;
  paths: number;
  notes: string[];
}
