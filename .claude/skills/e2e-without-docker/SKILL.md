---
name: e2e-without-docker
description: Run the FinAlly Playwright E2E suite without Docker (e.g. cloud sessions) by serving the built frontend from the backend with a throwaway database.
---

# E2E without Docker

Where Docker isn't available (e.g. cloud sessions), serve the built frontend from the backend with a throwaway database, then point Playwright at it:

```bash
cd frontend && npm run build
cd ../backend && LLM_MOCK=true MASSIVE_API_KEY= FINALLY_DB_PATH=/tmp/finally-e2e.db \
  FINALLY_STATIC_DIR=../frontend/out uv run uvicorn app.main:app --port 8000 &
cd ../test && npm ci && npx playwright install chromium   # or set CHROME_PATH instead
BASE_URL=http://127.0.0.1:8000 npx playwright test
```

Delete `/tmp/finally-e2e.db` before each run: `01-fresh-start` expects an untouched database. If the browser download is blocked, set `CHROME_PATH` to an installed Chrome (e.g. `/usr/bin/google-chrome`). If an HTTP proxy is set, add `NO_PROXY=127.0.0.1,localhost`.
