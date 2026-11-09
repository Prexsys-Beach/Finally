# FinAlly Backend

FastAPI backend for the FinAlly AI Trading Workstation.

## Structure

- `app/` - Application code
  - `main.py` - `create_app()`, startup and shutdown
  - `db/` - Schema, connections and seed data
  - `routes/` - HTTP layer (portfolio, watchlist, chat, market, analytics, predictions, settings, system)
  - `portfolio.py`, `watchlist.py`, `settings.py` - Trading, watchlist and user settings
  - `chat.py`, `assistant_tools.py` - LLM chat and the assistant's read-only lookup tools
  - `predictions.py` - The prediction journal
  - `analytics/` - Indicators, portfolio risk, Monte Carlo forecasts, backtests
  - `market/` - Market data subsystem
    - `models.py` - PriceUpdate dataclass
    - `cache.py` - Thread-safe price cache
    - `interface.py` - MarketDataSource abstract interface
    - `simulator.py` - GBM-based market simulator
    - `massive_client.py` - Massive/Polygon.io API client
    - `factory.py` - Data source factories
    - `stream.py` - SSE streaming endpoint
    - `seed_prices.py` - Default ticker prices and parameters
    - `bars.py`, `history.py`, `recorder.py` - Price bars, backfill providers and the bar recorder

- `tests/` - Unit and integration tests, mirroring `app/` (`market/`, `analytics/`)

## Running Tests

```bash
# Install dependencies, including the test tools
uv sync --extra dev

# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=app --cov-report=html

# Run specific test file
uv run pytest tests/market/test_simulator.py

# Run with verbose output
uv run pytest -v
```

## Environment Variables

See the root `.env.example` for the full list. The main ones:

- `OPENROUTER_API_KEY` - AI chat. `LLM_MOCK=true` gives deterministic replies instead.
- `MASSIVE_API_KEY` - Optional. If set, use real market data from Massive API. If not set, use the built-in simulator. `MASSIVE_SEED_SIMULATOR` and `MASSIVE_POLL_INTERVAL` tune it.
- `HISTORY_BACKFILL_DAYS`, `HISTORY_RETENTION_DAYS`, `CHAT_MAX_TOOL_ROUNDS` - Price history and assistant lookups.
- `FINALLY_DB_PATH`, `FINALLY_STATIC_DIR` - Where the SQLite file lives and where the built frontend is served from.

## Development

```bash
# Install dependencies
uv sync --extra dev

# Run linter
uv run ruff check .

# Format code
uv run ruff format .
```
