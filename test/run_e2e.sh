#!/usr/bin/env bash
# Build the app and run the Playwright suite against it. Exits with the result.
# Failure reports land in test/playwright-report and test/test-results.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v docker >/dev/null 2>&1; then
  export PATH="$PATH:/Applications/Docker.app/Contents/Resources/bin"
fi
compose=(docker compose -p finally-e2e -f "$DIR/docker-compose.test.yml")

"${compose[@]}" up --build --abort-on-container-exit --exit-code-from playwright
status=$?
"${compose[@]}" down -v --remove-orphans
exit "$status"
