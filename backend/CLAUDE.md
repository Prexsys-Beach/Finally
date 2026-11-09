# Backend — Developer Guide

## Running the Server

Python 3.12 (pinned in `.python-version`). Lint with `uv run ruff check .`; tests need `uv sync --extra dev`.

```bash
uv run --env-file ../.env uvicorn app.main:app --port 8000
```

The database is created and seeded on first start.

| Variable | Default | Purpose |
|---|---|---|
| `FINALLY_DB_PATH` | `db/finally.db` in the project root | SQLite file |
| `FINALLY_STATIC_DIR` | `backend/static` | Frontend build, served at `/` if present |

## Application Layout

- `app/main.py` — `create_app()`, startup and shutdown
- `app/db/` — schema, connections, `transaction()`, seed data (the package lives here rather than `backend/db/` so it ships in the wheel)
- `app/portfolio.py` — valuation, trades, snapshots. Use `place_trade()` for every trade, including LLM trades, so validation and ticker tracking stay in one place
- `app/watchlist.py` — watchlist rules, plus `tracked_tickers()` and `release_ticker()`
- `app/chat.py` — LLM chat. Lookup rounds with tools first, then a separate structured call for the answer (asking for both at once produced unrequested trades). Auto-executes through `place_trade()` and the watchlist functions. `CHAT_MAX_TOOL_ROUNDS` (default 4, 0 turns lookups off) caps the lookup rounds. Set `LLM_MOCK=true` for deterministic replies: `buy 5 AAPL`, `sell 1 MSFT`, `add PYPL`, `remove NFLX` act; `predict NVDA up` records a prediction; `analyze NVDA`, `forecast`, `backtest NVDA` and any mention of `risk` run real lookups
- `app/predictions.py` — the prediction journal: `record()` (validates, takes the price from the cache, adds a coin-flip baseline), `resolve_due()` (settles against the recorded one-minute bar, or the live price if fresh; otherwise void), `stats()` and `recent()`. `resolve_loop` runs every 30 seconds from the lifespan
- `app/assistant_tools.py` — the assistant's read-only tools, wrapping the analytics service. Errors go back to the model as `{"error": ...}`, never raised. The `mcp` dependency is there because litellm imports its MCP module whenever a call passes `tools`
- `app/settings.py` — user settings: allowed values, defaults, storage
- `app/routes/` — HTTP layer only

Routes are `async` and call SQLite directly on the event loop. Queries are small and local, so this is fine for a single user, and it serializes writes.

## Market Data API

The market data subsystem lives in `app/market/`; import from the package (`app/market/__init__.py`).

### Core Types

`PriceUpdate.change` and `change_percent` are tick-to-tick; use `day_change_percent` for daily change.

- **`MarketDataSource`** — Abstract interface implemented by `SimulatorDataSource` and `MassiveDataSource`. Lifecycle: `start(tickers)` -> `add_ticker()` / `remove_ticker()` -> `stop()`. The `mode` property is `"simulated"`, `"live"` or `"eod"`.

- **`create_market_data_source(cache)`** — Factory. Returns `MassiveDataSource` if `MASSIVE_API_KEY` is set, otherwise `SimulatorDataSource`. `MASSIVE_POLL_INTERVAL` sets the Massive poll seconds (default 15).

Prices can be `None`, for example just after startup, so handle that. Follow the "Integration Rules" in `planning/MARKET_INTERFACE.md`, especially tracking watchlist and open positions together. In Massive tests, build snapshots from real models rather than `MagicMock`.

### Price History

- `app/market/bars.py` — `Bar` (OHLC with `origin`: `recorded`, `synthetic` or `vendor`), storage helpers, and `bars_for_analysis()`, which drops synthetic bars once real history covers the user's cutoff (`app/settings.py`, `synthetic_cutoff_days()`)
- `app/market/history.py` — `HistoryProvider` for backfill: `SyntheticHistory` (the simulator's model, ending at the current price) and `MassiveHistory` (aggregates). A new data vendor is one more provider
- `app/market/recorder.py` — `HistoryService`, started in the lifespan: samples the `PriceCache` every second into one-minute bars (folded into daily bars as it goes), backfills before the earliest stored bar for each new ticker, and prunes one-minute bars past `HISTORY_RETENTION_DAYS`. Its database work runs on one worker thread
- `create_history_service(db_path, cache)` picks the provider: Massive when prices are real Massive prices, otherwise synthetic (including `MASSIVE_SEED_SIMULATOR`)

| Variable | Default | Purpose |
|---|---|---|
| `HISTORY_BACKFILL_DAYS` | 5 | Days of one-minute history to backfill; 0 turns backfill off |
| `HISTORY_RETENTION_DAYS` | 30 | Days of one-minute bars to keep |

### Analytics

- `app/analytics/indicators.py` and `risk.py` — pure numpy functions. Indicators are causal (no look-ahead; `tests/analytics/test_indicators.py` checks it by truncation) and return NaN through their warm-up
- `app/analytics/forecast.py` — Monte Carlo math: covariance from one-minute returns scaled per second of trading, paths with no expected return, percentile bands. Horizons map to trading time by data mode (the simulator trades around the clock; real markets about 6.5 hours a day)
- `app/analytics/backtest.py` — long-only strategies (buy and hold, SMA crossover, RSI mean reversion) as functions from closes to 0/1 decisions. A decision at bar t's close trades at bar t+1's close, so nothing looks ahead; zero fees, optional slippage. Add a strategy by adding a function to `STRATEGIES`
- `app/analytics/service.py` — `ticker_analytics()`, `portfolio_analytics()`, `forecast()` and `backtest()`: read bars through `bars_for_analysis()` so the synthetic-history cutoff applies, and report the bar origins they used. The assistant's tools (`app/assistant_tools.py`) call these rather than the math directly