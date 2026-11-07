# FinAlly Project - the Finance Ally

All project documentation is in the `planning` directory.

The key document is PLAN.md included in full below. Consult the other docs only when required: the market data design is summarized in `planning/MARKET_DATA_SUMMARY.md`, with more detail in `planning/archive`.

## Status

The platform described in PLAN.md is built: market data (simulator and Massive), SQLite persistence, portfolio and trading, watchlist, AI chat with auto-executed trades, the Next.js terminal UI, Docker packaging, start/stop scripts, and unit and E2E test suites. New work is changes to this existing app, so read the relevant code before editing.

## Commands

```bash
# Backend unit tests (pytest)
cd backend && uv sync --extra dev && uv run pytest

# Frontend unit tests, type check, static build (output in frontend/out)
cd frontend && npm ci && npm test && npm run lint && npm run build

# E2E suite in Docker (preferred; fresh database, mock LLM)
test/run_e2e.sh
```

### E2E without Docker

Where Docker isn't available (e.g. cloud sessions), serve the built frontend from the backend with a throwaway database, then point Playwright at it:

```bash
cd frontend && npm run build
cd ../backend && LLM_MOCK=true MASSIVE_API_KEY= FINALLY_DB_PATH=/tmp/finally-e2e.db \
  FINALLY_STATIC_DIR=../frontend/out uv run uvicorn app.main:app --port 8000 &
cd ../test && npm ci && npx playwright install chromium   # or set CHROME_PATH instead
BASE_URL=http://127.0.0.1:8000 npx playwright test
```

Delete `/tmp/finally-e2e.db` before each run: `01-fresh-start` expects an untouched database. If the browser download is blocked, set `CHROME_PATH` to an installed Chrome (e.g. `/usr/bin/google-chrome`). If an HTTP proxy is set, add `NO_PROXY=127.0.0.1,localhost`.

@planning/PLAN.md
