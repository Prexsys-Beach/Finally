# FinAlly Project - the Finance Ally

All project documentation is in the `planning` directory.

The key document is `planning/PLAN.md`, the spec: features, API endpoints, schema, environment variables and the LLM integration. Read the relevant section before changing a feature, and keep it current when you do. For LLM calls, use the cerebras skill (LiteLLM via OpenRouter, `openrouter/openai/gpt-oss-120b` on Cerebras, structured outputs). Consult the other docs only when required: `planning/ANALYTICS_PLAN.md` for price history, indicators, risk, the assistant's tools, forecasts, the prediction journal and backtesting; the market data design is summarized in `planning/MARKET_DATA_SUMMARY.md`, with `MARKET_INTERFACE.md`, `MARKET_SIMULATOR.md` and `MASSIVE_API.md` beside it and the original design and review in `planning/archive`. Backend code conventions and module notes are in `backend/CLAUDE.md`.

## Status

The platform described in PLAN.md is built: market data (simulator and Massive), SQLite persistence, portfolio and trading, watchlist, AI chat with auto-executed trades, the Next.js terminal UI, Docker packaging, start/stop scripts, and unit and E2E test suites. The analytics extension in `ANALYTICS_PLAN.md` is built too (all six phases): recorded and backfilled price history, indicators and portfolio risk, assistant lookup tools, Monte Carlo forecasts, the prediction journal and backtesting. New work is changes to this existing app, so read the relevant code before editing.

## Commands

```bash
# Backend unit tests (pytest)
cd backend && uv sync --extra dev && uv run pytest

# Backend lint
cd backend && uv run ruff check .

# Frontend unit tests, type check, static build (output in frontend/out)
cd frontend && npm ci && npm test && npm run lint && npm run build

# E2E suite in Docker (preferred; fresh database, mock LLM)
test/run_e2e.sh
```

Where Docker isn't available (e.g. cloud sessions), use the `e2e-without-docker` skill.
