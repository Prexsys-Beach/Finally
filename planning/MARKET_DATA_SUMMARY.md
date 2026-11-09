# Market Data Backend — Summary

**Status:** Complete. The simulator is ready for use. Massive's end-of-day mode has been run with a real key. Massive's `live` mode is tested only against the real client with faked HTTP, because the available key has no snapshot access.

The original review missed two defects that stopped Massive working at all, because `MagicMock` fixtures hid them. Both were fixed on 2026-11-06. See "Massive Fixes" below.

## What Was Built

A complete market data subsystem in `backend/app/market/` (11 modules, three of them for price history; see `ANALYTICS_PLAN.md`) providing live price simulation and real market data via a unified interface.

### Architecture

```
MarketDataSource (ABC)
├── SimulatorDataSource  →  GBM simulator (default, no API key needed)
└── MassiveDataSource    →  Massive REST poller (when MASSIVE_API_KEY set)
        │
        ▼
   PriceCache (thread-safe, in-memory)
        │
        ├──→ SSE stream endpoint (/api/stream/prices)
        ├──→ Portfolio valuation
        └──→ Trade execution
```

### Modules

| File | Purpose |
|------|---------|
| `models.py` | `PriceUpdate` — immutable frozen dataclass (ticker, price, previous_price, timestamp, previous_close, change, direction, day_change_percent) |
| `interface.py` | `MarketDataSource` — abstract base class defining `start/stop/add_ticker/remove_ticker/get_tickers/mode`, plus `normalize_ticker()` |
| `cache.py` | `PriceCache` — thread-safe price store with version counter for SSE change detection |
| `seed_prices.py` | Realistic seed prices, per-ticker GBM params (drift/volatility), correlation groups |
| `simulator.py` | `GBMSimulator` (Geometric Brownian Motion with Cholesky-correlated moves) + `SimulatorDataSource` |
| `massive_client.py` | `MassiveDataSource` — REST poller via the `massive` package: snapshots, or end-of-day closes if the plan has no snapshot access |
| `factory.py` | `create_market_data_source()` — selects simulator or Massive based on `MASSIVE_API_KEY`; reads `MASSIVE_POLL_INTERVAL` and `MASSIVE_SEED_SIMULATOR`; also `create_history_service()` |
| `stream.py` | `create_stream_router()` — FastAPI SSE endpoint factory using version-based change detection |
| `bars.py`, `history.py`, `recorder.py` | Price history: OHLC bars and storage, backfill providers, and the service that records bars from the cache |

### Key Design Decisions

- **Strategy pattern** — both data sources implement the same ABC; downstream code is source-agnostic
- **PriceCache as single point of truth** — producers write, consumers read; no direct coupling
- **GBM with correlated moves** — Cholesky decomposition of sector-based correlation matrix; tech stocks correlate at 0.6, finance at 0.5, cross-sector at 0.3
- **Random shock events** — ~0.1% chance per tick per ticker of a 2-5% move for visual drama
- **SSE over WebSockets** — simpler, one-way push, universal browser support

## Test Suite

**163 tests, all passing** in 11 modules in `backend/tests/market/` (the backend suite has 427). The original 92, in the first seven modules below, were also run on `massive` 2.2.0 and 2.9.1; the rest were run on the locked version only.

| Module | Tests | Coverage |
|--------|-------|----------|
| test_models.py | 11 | models.py: 100% |
| test_cache.py | 13 | cache.py: 100% |
| test_simulator.py | 22 | simulator.py: 98% |
| test_simulator_source.py | 10 | (integration tests) |
| test_factory.py | 11 | factory.py: 100% |
| test_massive.py | 13 | massive_client.py: 97% (with the module below) |
| test_massive_real_models.py | 19 | Real `massive` client and models, with only HTTP faked |
| test_bars.py, test_history.py, test_recorder.py | 22, 16, 8 | Price bars, backfill providers, the bar recorder |
| test_seeded_simulator.py | 18 | Simulator seeded from real closes |

Coverage was 93% when measured on the first 92 tests; it hasn't been re-measured. The main gap then was `stream.py` at 33%.

## Code Review & Fixes Applied

A comprehensive code review identified 7 issues. All were resolved:

1. **pyproject.toml build config** — added `[tool.hatch.build.targets.wheel] packages = ["app"]`
2. **Lazy imports removed** — `massive` is a core dependency; imports moved to top level
3. **SSE return type fixed** — `_generate_events` annotated as `AsyncGenerator[str, None]`
4. **Public `get_tickers()`** — added to `GBMSimulator` to avoid private attribute access
5. **Correlation constants cleaned up** — removed unused `DEFAULT_CORR`, consolidated into `CROSS_GROUP_CORR`
6. **Unused test imports removed** — `pytest`, `math`, `asyncio` cleaned from 4 test files
7. **Massive test mocks fixed** — `source._client` set in tests, patches target correct names

## Massive Fixes (2026-11-06)

1. **Snapshot URL** — the code passed an Enum where the client needs `"stocks"`, so the live API returned 404
2. **Trade timestamp** — `last_trade.timestamp` doesn't exist; now `sip_timestamp`, treated as nanoseconds
3. **Basic plan** — no snapshot access, so a 403 now switches to end-of-day closes (`mode == "eod"`)
4. **Missing fields** — price falls back from last trade to minute bar, today's bar, then previous close
5. **Daily change** — added `previous_close` and `day_change_percent`, from both sources
6. **Smaller fixes** — `retries=0` so a 429 costs one request, removed tickers stay removed, tickers are normalised in both sources
7. **Tests** — Massive fixtures use real models, because `MagicMock` invents attributes

Before relying on `live` mode, run the smoke test in `MARKET_INTERFACE.md` with a key that has snapshot access.

## Demo

A Rich terminal demo is available at `backend/market_data_demo.py`:

```bash
cd backend
uv run market_data_demo.py
```

Displays a live-updating dashboard with all 10 tickers, sparklines, color-coded direction arrows, and an event log for notable price moves. Runs 60 seconds or until Ctrl+C.

## Usage for Downstream Code

```python
from app.market import PriceCache, create_market_data_source

# Startup
cache = PriceCache()
source = create_market_data_source(cache)  # Reads MASSIVE_API_KEY, MASSIVE_POLL_INTERVAL
await source.start(["AAPL", "GOOGL", "MSFT", ...])

# Read prices
update = cache.get("AAPL")          # PriceUpdate or None
price = cache.get_price("AAPL")     # float or None
all_prices = cache.get_all()        # dict[str, PriceUpdate]
mode = source.mode                  # "simulated", "live" or "eod"

# Dynamic watchlist
await source.add_ticker("TSLA")
await source.remove_ticker("GOOGL")

# Shutdown
await source.stop()
```
