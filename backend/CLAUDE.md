# Backend — Developer Guide

## Project Setup

```bash
cd backend
uv sync --extra dev   # Install all dependencies including test/lint tools
```

## Running the Server

```bash
uv run --env-file ../.env uvicorn app.main:app --port 8000
```

API docs are at `http://localhost:8000/docs`. The database is created and seeded on first start.

| Variable | Default | Purpose |
|---|---|---|
| `FINALLY_DB_PATH` | `db/finally.db` in the project root | SQLite file |
| `FINALLY_STATIC_DIR` | `backend/static` | Frontend build, served at `/` if present |

## Application Layout

- `app/main.py` — `create_app()`, startup and shutdown
- `app/db/` — schema, connections, `transaction()`, seed data (the package lives here rather than `backend/db/` so it ships in the wheel)
- `app/portfolio.py` — valuation, trades, snapshots. Use `place_trade()` for every trade, including LLM trades, so validation and ticker tracking stay in one place
- `app/watchlist.py` — watchlist rules, plus `tracked_tickers()` and `release_ticker()`
- `app/chat.py` — LLM chat. Auto-executes through `place_trade()` and the watchlist functions. Set `LLM_MOCK=true` for deterministic replies: `buy 5 AAPL`, `sell 1 MSFT`, `add PYPL`, `remove NFLX`
- `app/settings.py` — user settings: allowed values, defaults, storage
- `app/routes/` — HTTP layer only

Routes are `async` and call SQLite directly on the event loop. Queries are small and local, so this is fine for a single user, and it serializes writes.

## Market Data API

The market data subsystem lives in `app/market/`. Use these imports:

```python
from app.market import PriceCache, PriceUpdate, MarketDataSource, DataMode
from app.market import create_market_data_source, normalize_ticker
```

### Core Types

- **`PriceUpdate`** — Immutable dataclass: `ticker`, `price`, `previous_price`, `timestamp`, `previous_close`, plus properties `change`, `change_percent`, `direction` ("up"/"down"/"flat"), `day_change_percent`, and `to_dict()` for JSON serialization. `change` and `change_percent` are tick-to-tick; use `day_change_percent` for daily change.

- **`PriceCache`** — Thread-safe in-memory store. Key methods:
  - `update(ticker, price, timestamp=None, previous_close=None) -> PriceUpdate` (`None` keeps the existing `previous_close`)
  - `get(ticker) -> PriceUpdate | None`
  - `get_price(ticker) -> float | None`
  - `get_all() -> dict[str, PriceUpdate]`
  - `remove(ticker)`
  - `version` property — monotonic counter, increments on every update (for SSE change detection)

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
- `app/analytics/service.py` — `ticker_analytics()` and `portfolio_analytics()`: read bars through `bars_for_analysis()` so the synthetic-history cutoff applies, and report the bar origins they used. Phase 3's assistant tools should call these rather than the math directly

### SSE Streaming

```python
from app.market import create_stream_router

router = create_stream_router(price_cache)  # Returns FastAPI APIRouter
# Endpoint: GET /api/stream/prices (text/event-stream)
```

### Seed Data

Default tickers: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX. Seed prices and per-ticker volatility/drift params are in `app/market/seed_prices.py`.

## Running Tests

```bash
uv run --extra dev pytest -v              # All tests
uv run --extra dev pytest --cov=app       # With coverage
uv run --extra dev ruff check app/ tests/ # Lint
```

## Demo

```bash
uv run market_data_demo.py   # Live terminal dashboard with simulated prices
```
