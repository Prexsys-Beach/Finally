# FinAlly — AI Trading Workstation

A visually stunning AI-powered trading workstation that streams live market data, simulates portfolio trading, and integrates an LLM chat assistant that can analyze positions and execute trades via natural language.

Built entirely by coding agents as a capstone project for an agentic AI coding course.

## Features

- **Live price streaming** via SSE with green/red flash animations
- **Simulated portfolio** — $10k virtual cash, market orders, instant fills
- **Portfolio visualizations** — heatmap (treemap), P&L chart, positions table
- **Price history** — charts open with stored one-minute and daily bars (live, 1D, 5D, 1Y), labeled when they include simulated history
- **Indicators and risk** — SMA, EMA, Bollinger Bands, RSI and MACD on the chart; a Risk view with volatility, beta, VaR, drawdown, Sharpe and correlations
- **Forecasts and backtests** — a Monte Carlo fan on the P&L chart; long-only strategies replayed on stored history
- **AI chat assistant** — looks things up before answering (indicators, risk, forecasts, backtests), analyzes holdings, suggests and auto-executes trades
- **Prediction journal** — the assistant's directional calls are logged and scored against a coin flip on a Scorecard
- **Watchlist management** — track tickers manually or via AI
- **Dark terminal aesthetic** — Bloomberg-inspired, data-dense layout

## Architecture

Single Docker container serving everything on port 8000:

- **Frontend**: Next.js (static export) with TypeScript and Tailwind CSS
- **Backend**: FastAPI (Python/uv) with SSE streaming
- **Database**: SQLite with lazy initialization
- **AI**: LiteLLM → OpenRouter (Cerebras inference) with structured outputs
- **Market data**: Built-in GBM simulator (default) or Massive API (optional)

## Quick Start

```bash
# Starts Docker Desktop if needed, creates .env, builds, runs, and opens the browser
scripts/start_mac.sh            # Windows: scripts\start_windows.ps1

# Stop. Your portfolio is kept in the finally-data Docker volume.
scripts/stop_mac.sh             # Windows: scripts\stop_windows.ps1
```

Add your `OPENROUTER_API_KEY` to `.env` to enable AI chat. Pass `--build` (Windows: `-Build`) to load code or `.env` changes, even while the app is running. To start again from $10,000, stop the app and run `docker volume rm finally-data`.

To run it by hand:

```bash
docker build -t finally .
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key for AI chat |
| `MASSIVE_API_KEY` | No | Massive (Polygon.io) key for real market data; omit to use simulator |
| `MASSIVE_SEED_SIMULATOR` | No | `true` with a Massive key starts the simulator from real closes |
| `MASSIVE_POLL_INTERVAL` | No | Seconds between Massive polls; default 15 |
| `LLM_MOCK` | No | Set `true` for deterministic mock LLM responses (testing) |
| `HISTORY_BACKFILL_DAYS` | No | Days of one-minute history to backfill; default 5, `0` turns it off |
| `HISTORY_RETENTION_DAYS` | No | Days of one-minute bars to keep; default 30 |
| `CHAT_MAX_TOOL_ROUNDS` | No | Lookup rounds the assistant may take before answering; default 4, `0` turns lookups off |

## Testing

```bash
cd backend && uv sync --extra dev && uv run pytest         # backend unit tests
cd frontend && npm ci && npm test && npm run lint          # frontend unit tests and type check
test/run_e2e.sh                                            # end-to-end, in Docker
```

The E2E script runs the Playwright suite in Docker against a throwaway app, with a fresh database and mock LLM replies. It doesn't touch a running app or its data. Failure reports land in `test/playwright-report`.

## Project Structure

```
finally/
├── frontend/    # Next.js static export
├── backend/     # FastAPI uv project
├── planning/    # Spec (PLAN.md), analytics plan, market data docs
├── test/        # Playwright E2E tests and run_e2e.sh
├── db/          # SQLite volume mount (runtime)
└── scripts/     # Start/stop helpers
```

## License

See [LICENSE](LICENSE).
