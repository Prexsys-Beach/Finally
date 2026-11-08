# Analytics & Prediction Extension Plan

## 1. Goal

Make the assistant better at analysis and prediction, in a form that can be tested now on the simulator and later fed with purchased market data, without changes to the tools.

Build the tools first, buy data later. Every piece below runs on simulated data, so its correctness can be proven before money is spent. The prediction journal (Phase 5) then becomes the yardstick for judging whether a data purchase is worth it.

### What changes for the user

- The main chart opens with history instead of filling in from page load.
- Indicator overlays and a risk panel show what the assistant is reasoning from.
- The assistant looks things up before answering (history, indicators, risk, forecasts, backtests) and shows which lookups it used.
- Forecasts are ranges with probabilities, not single price targets.
- Every prediction the assistant makes is logged and scored, with a running hit rate and calibration.

### Non-goals

- Training ML models. Nothing here learns weights; on a random walk there is nothing to learn, and on real data it is a separate project.
- News, sentiment and fundamentals. They need a data source the app doesn't have; they belong with the data purchase (Section 9).
- Changing how trades execute. Trades still go through `place_trade` with the same validation.

---

## 2. Current State (what this builds on)

| Area | Today | Gap |
|---|---|---|
| Prices | `PriceCache` holds only the latest `PriceUpdate` per ticker (`backend/app/market/cache.py`) | No history anywhere on the backend |
| Charts | `frontend/src/lib/history.ts` accumulates up to 3,600 one-second points from SSE | Empty on every page load |
| Sources | `MarketDataSource` interface; simulator (`simulated`/`seeded`) and Massive (`live`/`eod`) | No interface for historical bars |
| Portfolio history | `portfolio_snapshots` every 30s plus after each trade | Usable for drawdown and Sharpe once enough accumulates |
| Assistant | `backend/app/chat.py`: one `completion()` call with `response_format=LLMResponse`, context is a JSON snapshot of portfolio and watchlist | Can't look anything up; sees one instant |

The simulator matters for interpreting results. `GBMSimulator` is geometric Brownian motion with per-ticker drift and volatility (`seed_prices.py`), correlated within sector groups, plus random 2-5% jumps (0.1% chance per tick). Future moves are independent of past ones, so **no predictor can beat chance on simulated data**. That is a feature here: it is the control group.

---

## 3. Design Principles

1. **Source-agnostic.** History is recorded from `PriceCache`, never from a specific source, so it works the same for the simulator, Massive, or a future vendor.
2. **Label the data.** Every bar records where it came from (`recorded`, `synthetic`, `vendor`). Backtests, forecasts and prediction stats can filter on it, and the UI says when it is showing synthetic history.
3. **Analytics are pure functions.** `numpy` in, numbers out, no I/O. Easy to unit-test against known values; reusable by API routes and assistant tools alike.
4. **Read-only tools, one place for actions.** The assistant may call lookup tools as many times as it needs. Trades and watchlist changes stay in the final structured response, executed exactly as today.
5. **No look-ahead.** Any calculation for time *t* uses data up to *t* only. Tests enforce it (Section 8).
6. **Honest uncertainty.** Forecasts are distributions; predictions carry a confidence and are scored against it.
7. **Each phase ships alone.** One PR per phase, each useful without the later ones.

---

## 4. Phases at a Glance

| Phase | Delivers | Depends on |
|---|---|---|
| 1. Price history | `price_bars` table, bar recorder, backfill providers, bars API, charts that open with history | — |
| 2. Indicators & risk | `app/analytics/` module, analytics API, chart overlays, risk panel | 1 |
| 3. Assistant tools | Tool-calling loop in chat, lookup tools, "analysis used" shown in chat | 2 |
| 4. Forecasts | Monte Carlo portfolio and ticker forecasts, fan chart | 1, 2 |
| 5. Prediction journal | `predictions` table, resolver, scorecard, baseline predictor | 3 |
| 6. Backtesting | Strategy runner, backtest API and tool | 1, 2 |

Recommended order: 1 → 2 → 3 → 5, then 4 and 6 in either order. Phase 3 is the biggest single improvement to the assistant; Phase 5 is what makes it measurable.

---

## 5. Phase Details

### Phase 1 — Price History

**Schema** (`backend/app/db/schema.sql`):

```sql
CREATE TABLE IF NOT EXISTS price_bars (
    ticker TEXT NOT NULL,
    timeframe TEXT NOT NULL,          -- '1m' or '1d'
    start_ts INTEGER NOT NULL,        -- Unix seconds, bar open time (UTC)
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    origin TEXT NOT NULL,             -- 'recorded' | 'synthetic' | 'vendor'
    PRIMARY KEY (ticker, timeframe, start_ts)
) WITHOUT ROWID;
```

Prices are market data, not user data, so this table deliberately has no `user_id` (an exception to PLAN.md §7, which should note it). `start_ts` is an integer rather than an ISO string because every query on this table is a time range.

**Bar recorder** (`backend/app/market/bars.py`): a background task started in `main.py`'s lifespan next to `snapshot_loop`.
- Samples `PriceCache.get_all()` once per second and builds one-minute OHLC bars in memory.
- Writes each bar when its minute closes, with `origin='recorded'`. Skips a minute with no new price (use `PriceCache.version` and per-ticker timestamps), so a stalled Massive feed doesn't invent flat bars.
- Rolls one-minute bars into `'1d'` bars at UTC midnight.
- Retention: keep 30 days of `'1m'` bars (about 430k rows for 10 tickers running around the clock, roughly 30 MB); keep `'1d'` bars indefinitely.

**Backfill providers** (`backend/app/market/history.py`): a second, small interface beside `MarketDataSource`.

```python
class HistoryProvider(ABC):
    origin: Literal["synthetic", "vendor"]

    @abstractmethod
    async def fetch(self, requests: Sequence[BackfillRequest]) -> list[Bar]: ...
```

Each `BackfillRequest` is a ticker, timeframe, `[start, end)` range and an anchor price (built). Requests arrive in a batch so `SyntheticHistory` can generate tickers with the same range together and keep their correlations.

- `SyntheticHistory`: generates past bars with the same per-ticker `mu`/`sigma` and correlation as `GBMSimulator`, using `dt` of one minute (or one day) of trading time. It generates a path and rescales it so the last close equals the ticker's starting price, so history meets the live stream without a jump. Seedable for tests. Default depth: 5 days of `'1m'` and 1 year of `'1d'`.
- `MassiveHistory`: per-ticker aggregates via the Massive client (`list_aggs`). Depth and rate limits depend on the plan, so it backs off on rate-limit errors like the existing client does.
- Chosen in `factory.py` with the same environment rules as the live source: Massive key → `MassiveHistory`, otherwise `SyntheticHistory`. A purchased vendor is one more implementation.
- Runs at startup for tracked tickers and on watchlist add, and only fills gaps, so restarts don't refetch.

**API**: `GET /api/market/bars/{ticker}?timeframe=1m&limit=500` → bars oldest first, each with `origin`.

**Frontend**: `PriceChart` and the sparklines load bars first, then append SSE points as today. When the visible range includes synthetic bars, show a small "simulated history" label.

**Tests**: recorder aggregation (OHLC from a scripted tick sequence, skipped minutes, midnight rollup); gap-only backfill; synthetic history's measured volatility within tolerance of the configured `sigma`; last synthetic close equals start price; bars API shape and ordering.

### Phase 2 — Indicators & Risk

**Module** `backend/app/analytics/`, pure `numpy`:

- `indicators.py`: log returns, SMA, EMA, RSI (Wilder), MACD (12/26/9), Bollinger Bands (20, 2σ), realized volatility (annualized for the bar timeframe), ATR.
- `risk.py` (inputs: positions plus bars):
  - Portfolio volatility from the return covariance of held tickers.
  - Correlation matrix of held and watched tickers.
  - Beta against a benchmark: an equal-weighted basket of the watchlist while there is no index data (the simulator has none), and SPY once a real data source provides it. (Decided.)
  - Value at Risk and expected shortfall, 1-day, 95%: historical and parametric.
  - Concentration: largest position weight and the Herfindahl index.
  - From `portfolio_snapshots`: max drawdown and Sharpe ratio, reported only once there is enough history (at least a day; otherwise `null` with a reason).

**API**:
- `GET /api/analytics/ticker/{ticker}?timeframe=1m` → latest indicator values plus series for overlays.
- `GET /api/analytics/portfolio` → risk metrics, correlation matrix, and which bars (and origins) they were computed from.

**Frontend** (data-dense, matching the existing terminal layout):
- Toggleable overlays on the main chart: SMA/EMA, Bollinger Bands; RSI and MACD in a small sub-pane.
- A compact risk view: volatility, beta, VaR, top weight, and a correlation heatmap. It lives in the heatmap panel as a second view (see "Analysis panel views" in Section 7).

**Tests**: each indicator against hand-computed fixtures; edge cases (fewer bars than the window, constant prices, a single position); VaR against a known distribution; no look-ahead (Section 8).

**As built**:
- Indicator parameters are fixed: SMA 20, EMA 50, Bollinger (20, 2σ), RSI 14, MACD (12, 26, 9), ATR 14. The ticker endpoint also returns simple signals (RSI overbought/oversold, price vs the bands and the SMA, MACD above or below its signal) for the assistant tools in Phase 3.
- Portfolio risk defaults to daily bars (a trading year of 252), with `?timeframe=1m` for a calendar day of minutes scaled to one trading day by the square root of time. Weights are shares of total value including cash, so cash dampens volatility, beta and VaR. Parametric figures assume zero mean.
- The Sharpe ratio treats elapsed time as trading time, which matches the simulator; with real data it understates both return and volatility.
- The panel toggle is **Heatmap · Risk** for now. **Scorecard** arrives with Phase 5, and `analysis_panel_auto_switch` with Phase 3, when assistant messages first use risk tools; a switch with nothing to trigger it would only confuse.

### Phase 3 — Assistant Tools

Replace the single structured call in `handle_chat` with a short tool-calling loop.

**Tools** (all read-only, each a thin wrapper over Phase 1-2 functions, returning compact JSON):

| Tool | Returns |
|---|---|
| `get_bars(ticker, timeframe, limit)` | Recent OHLC bars, downsampled if long |
| `get_indicators(ticker, timeframe)` | Latest indicator values and simple signals (e.g. RSI > 70) |
| `get_portfolio_risk()` | Phase 2 risk metrics |
| `get_correlations(tickers)` | Correlation submatrix |
| `run_forecast(target, horizon)` | Phase 4 percentile bands (once Phase 4 lands) |
| `run_backtest(ticker, strategy, params)` | Phase 6 summary (once Phase 6 lands) |
| `get_prediction_record()` | Phase 5 hit rate and calibration (once Phase 5 lands) |

**Loop**:
1. Send the system prompt, context, history and tools.
2. Run any requested tool calls and append the results; repeat up to 4 rounds.
3. Make the final call with `response_format=LLMResponse`, unchanged except for the `predictions` field added in Phase 5.
4. Execute trades and watchlist changes exactly as today.

The total time budget stays bounded: a per-call timeout plus an overall limit (about 45s). When the limit is hit, the final call goes ahead with whatever tool results exist.

**First task: a spike** to confirm tool calling and structured output work together for `openrouter/openai/gpt-oss-120b` on Cerebras through LiteLLM (follow the cerebras-inference skill). If they can't be combined in one call, keep them in separate calls: tool rounds without `response_format`, then one final structured call without tools. The plan above already allows that.

**Chat UI**: each assistant message shows a one-line "Analysis used" list (e.g. `indicators NVDA 1m · portfolio risk`), stored in the existing `actions` JSON as `tool_calls`.

**System prompt additions**: look things up before making claims about trends or risk; cite the numbers used; state the data mode (`simulated`, `seeded`, `live`, `eod`) and, on simulated data, avoid presenting patterns as predictive.

**Mock mode**: `LLM_MOCK=true` gains deterministic tool use (e.g. "analyze NVDA" calls `get_indicators`), so E2E tests can check the "Analysis used" line.

**Tests**: loop with a fake model (tool round limit, timeout fallback, unknown tool name, bad arguments returned to the model as an error result rather than raised); tools never write to the database; existing chat tests still pass.

### Phase 4 — Forecasts

**Monte Carlo** (`backend/app/analytics/forecast.py`):
- Estimate per-ticker volatility and the correlation matrix from log returns of recorded (or vendor) bars, with synthetic bars as fallback, reporting which was used.
- Drift defaults to zero. Drift estimated from days or weeks of data is mostly noise and would make forecasts look more confident than they are; a configured or long-history estimate can replace it later.
- Simulate 5,000 correlated GBM paths with jumps matching the simulator's event model (configurable off for real data).
- Output percentiles (5/25/50/75/95) over the horizon, probability of loss, and probability of crossing a given level.
- Targets: one ticker, or the current portfolio (positions plus cash).

**API**: `GET /api/analytics/forecast?target=portfolio&horizon=1d`.

**Frontend**: a fan of percentile bands extending the P&L chart (and optionally the ticker chart), with the probability of loss shown beside it.

Statistical models such as ARIMA are deferred. On simulated data they can only find noise, and they add a heavy dependency; revisit with real data.

**Tests**: on paths generated with known `sigma`, the forecast's spread matches theory within tolerance; seeded runs are reproducible; the portfolio forecast with only cash is flat.

### Phase 5 — Prediction Journal

**Schema**:

```sql
CREATE TABLE IF NOT EXISTS predictions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    predictor TEXT NOT NULL,          -- 'assistant' | 'baseline'
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,          -- 'up' | 'down'
    confidence REAL NOT NULL,         -- 0.5 to 1.0
    horizon_minutes INTEGER NOT NULL,
    reference_price REAL NOT NULL,
    data_mode TEXT NOT NULL,          -- source.mode when made
    made_at TEXT NOT NULL,
    resolves_at TEXT NOT NULL,
    resolved_price REAL,
    outcome TEXT,                     -- 'hit' | 'miss' | 'void'
    chat_message_id TEXT
);
```

**Capturing predictions**: `LLMResponse` gains an optional `predictions: list[Prediction]` field (ticker, direction, confidence, horizon). Predictions are recorded two ways (decided):
- **Implicitly**: the system prompt asks the assistant to record a prediction whenever it states a directional view.
- **On request**: the user asks directly ("predict NVDA for the next hour"), and the assistant must answer with a recorded prediction, including its confidence, rather than declining or hedging.

The backend fills in the reference price from `PriceCache` and the data mode from the source; the model never supplies prices.

**Baseline**: whenever the assistant records a prediction, the backend records a matching `baseline` prediction for the same ticker and horizon with a random direction at 0.5 confidence. Assistant stats are always shown next to the baseline's.

**Resolver**: a background task (every 30s) resolves due predictions against `PriceCache`, or against bars if the price is missing. Predictions on tickers no longer tracked resolve as `void`.

**Scoring**: hit rate, Brier score, and calibration buckets (e.g. predictions made at 60-70% confidence and how often they came true), reported **separately per data mode**, so simulated results never mix with real ones.

**API**: `GET /api/predictions` (recent, with outcomes) and `GET /api/predictions/stats`.

**Frontend**: a scorecard view in the heatmap panel (Section 7) with hit rate vs baseline, Brier score, a small calibration chart, and recent predictions. Chat messages show recorded predictions inline next to trades.

**Expected result on the simulator**: about 50% hit rate for both predictors. A clearly better assistant score on simulated data points to a bug, most likely look-ahead.

**Tests**: resolver timing and outcomes; void handling; Brier and calibration math; reference price taken from the cache, not the model; stats split by data mode.

### Phase 6 — Backtesting

**Runner** (`backend/app/analytics/backtest.py`):
- Strategies: buy and hold, SMA crossover (fast/slow windows), RSI mean reversion (thresholds). Each strategy is a function from bars to target positions, so new ones are small.
- A signal computed at bar *t* trades at bar *t+1*'s close: no look-ahead by construction.
- Zero fees to match the app, with an optional slippage parameter.
- Output: total return, return vs buy-and-hold, max drawdown, number of trades, win rate, equity curve, and the origin mix of bars used.

**API and tool**: `POST /api/analytics/backtest` with `{ticker, strategy, params, timeframe, start, end}`; the same function backs the `run_backtest` tool.

**Frontend**: optional at first. The assistant presenting results in chat is enough; an equity-curve view can follow.

**Tests**: hand-built price series with known outcomes (e.g. a crossover on a V shape); look-ahead guard; buy-and-hold equals the price change.

---

## 6. API Summary (new)

| Method | Path | Phase |
|---|---|---|
| GET | `/api/settings` | 1 |
| PUT | `/api/settings` | 1 |
| GET | `/api/market/bars/{ticker}` | 1 |
| GET | `/api/analytics/ticker/{ticker}` | 2 |
| GET | `/api/analytics/portfolio` | 2 |
| GET | `/api/analytics/forecast` | 4 |
| GET | `/api/predictions` | 5 |
| GET | `/api/predictions/stats` | 5 |
| POST | `/api/analytics/backtest` | 6 |

`POST /api/chat` keeps its shape; responses gain `tool_calls` (Phase 3) and `predictions` (Phase 5).

---

## 7. Settings & Configuration

### User settings (in the app)

Two settings the user changes from the UI. They are stored in a new table so they survive restarts and the backend can act on them:

```sql
CREATE TABLE IF NOT EXISTS user_settings (
    user_id TEXT NOT NULL DEFAULT 'default',
    key TEXT NOT NULL,
    value TEXT NOT NULL,              -- JSON
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
```

API: `GET /api/settings` returns all settings with defaults filled in; `PUT /api/settings` with `{key: value}` validates and saves. Unknown keys and invalid values return 400. The UI reaches them from a small settings menu in the header.

| Key | Values | Default | Introduced |
|---|---|---|---|
| `synthetic_history_cutoff` | `never`, `day`, `week`, `month`, `quarter`, `year` | `month` | Phase 1 |
| `analysis_panel_auto_switch` | `true`, `false` | `true` | Phase 3 |

**Synthetic history cutoff** (decided: default one month, user-selectable). Synthetic bars give charts and calculations something to work with before real history exists. Once a ticker has recorded (or vendor) bars covering the chosen span, synthetic bars for that ticker stop being used in forecasts, backtests, risk metrics and prediction stats. They are still drawn on charts, labeled. `never` means synthetic bars are always used.

- Coverage is checked per ticker and per timeframe. For one-minute calculations the effective span is the smaller of the setting and `HISTORY_RETENTION_DAYS`, since older one-minute bars are deleted; longer spans (`quarter`, `year`) are measured on daily bars.
- Every analytics response reports which origins it used, so the switch from synthetic to recorded is visible.
- On the plain simulator, recorded bars are simulated too. The setting matters mainly once a real data source is connected.

**Analysis panel views** (decided: a toggle on the heatmap panel). The heatmap panel gets a compact three-way toggle: **Heatmap · Risk · Scorecard**. The heatmap stays the default view.

When `analysis_panel_auto_switch` is on, a new assistant message brings the relevant view to the front:
- The message recorded a prediction → Scorecard.
- The message used a risk tool (`get_portfolio_risk`, `get_correlations`, or a portfolio `run_forecast`) → Risk.
- Otherwise the view doesn't change.

The view only switches on new messages, never when old ones load after a page refresh. A manual toggle always wins until the next qualifying message. The on/off switch sits on the panel itself (a small "auto" toggle beside the view tabs) and is the same setting as in the settings menu.

### Environment (new, all optional)

```bash
HISTORY_BACKFILL_DAYS=5        # Days of 1m bars to backfill
HISTORY_RETENTION_DAYS=30      # Days of 1m bars to keep
CHAT_MAX_TOOL_ROUNDS=4
```

Vendor credentials arrive with the data purchase.

---

## 8. Testing Strategy

- **Unit tests** for every analytics function against fixtures, following the existing pytest layout (`backend/tests/analytics/`).
- **Look-ahead tests**: for each indicator, backtest and forecast, computing at time *t* on the full series must equal computing on the series truncated at *t*. This is the single most important guard for trustworthy predictions.
- **Simulator sanity**: volatility measured from recorded and synthetic bars matches the configured `sigma` within tolerance.
- **Chat loop**: driven by a fake model, so no network in unit tests.
- **E2E** (`test/`, `LLM_MOCK=true`): chart shows history on first load; risk panel renders; a mocked "analyze NVDA" shows an "Analysis used" line; a mocked prediction appears in the scorecard.
- Frontend tests for new components, following `components.test.tsx`.

---

## 9. Evaluating a Data Purchase

Once Phases 1-5 are in place, a provider can be tried before committing:

1. Implement its `HistoryProvider` (and a `MarketDataSource` if it has live prices).
2. Backfill, then run backtests and forecasts on its history.
3. Run the assistant with it for a trial period and compare its prediction stats (in that data mode) against the baseline.

What to compare between providers:
- Depth of intraday history (one-minute bars over months, not days).
- Real-time vs delayed quotes, and polling rate limits.
- Corporate-action adjustment (splits, dividends).
- Extras that would enable new tools: news, fundamentals, index data for a true benchmark.
- Cost against the plan's actual usage (10-50 tickers).

A paid Massive plan is the lowest-effort first candidate, since the live client already exists and only `MassiveHistory` would be new.

---

## 10. Delivery

One PR per phase, on branches `feat/price-history`, `feat/analytics`, `feat/assistant-tools`, `feat/forecasts`, `feat/predictions`, `feat/backtesting`. Each PR includes its tests and any updates to `PLAN.md` (new tables, endpoints, and the `price_bars` exception to the `user_id` rule) and `CLAUDE.md`.

## 11. Decisions

1. **Benchmark**: equal-weighted watchlist basket until real index data exists, then SPY (Phase 2).
2. **Prediction capture**: both implicit (whenever the assistant states a directional view) and on request (Phase 5).
3. **Screen space**: a Heatmap · Risk · Scorecard toggle on the heatmap panel, with optional auto-switching on new assistant messages, controlled by a setting (Section 7).
4. **Synthetic history**: excluded from analysis once a ticker has a month of recorded history by default, adjustable to never, day, week, month, quarter or year (Section 7).
