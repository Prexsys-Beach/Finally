#!/usr/bin/env bash
# Start FinAlly in Docker. Safe to run repeatedly.
# Usage: scripts/start_mac.sh [--build] [--no-open]
set -euo pipefail

IMAGE=finally
CONTAINER=finally
VOLUME=finally-data
URL=http://localhost:8000
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

build=false
open_browser=true
for arg in "$@"; do
  case "$arg" in
    --build) build=true ;;
    --no-open) open_browser=false ;;
    *) echo "Usage: $0 [--build] [--no-open]" >&2; exit 2 ;;
  esac
done

# Docker Desktop's CLI isn't always on PATH
if ! command -v docker >/dev/null 2>&1; then
  export PATH="$PATH:/Applications/Docker.app/Contents/Resources/bin"
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker isn't installed. Get it from https://www.docker.com/products/docker-desktop/" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker isn't running. Start Docker Desktop, then run this again." >&2
  exit 1
fi

cd "$ROOT"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Add your OPENROUTER_API_KEY to enable AI chat."
fi

if [ "$build" = true ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building the $IMAGE image. The first build takes a few minutes."
  docker build -t "$IMAGE" .
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
fi

if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = "true" ]; then
  echo "FinAlly is already running at $URL"
  echo "To load code or .env changes: scripts/stop_mac.sh, then scripts/start_mac.sh --build"
else
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  docker run -d \
    --name "$CONTAINER" \
    --env-file .env \
    -v "$VOLUME:/app/db" \
    -p 8000:8000 \
    "$IMAGE" >/dev/null

  printf "Starting"
  for _ in $(seq 1 60); do
    if curl -fs -m 2 "$URL/api/health" >/dev/null 2>&1; then
      break
    fi
    if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" != "true" ]; then
      echo
      echo "FinAlly stopped during startup. Its logs:" >&2
      docker logs --tail 30 "$CONTAINER" >&2
      exit 1
    fi
    printf "."
    sleep 1
  done
  echo
  if ! curl -fs -m 2 "$URL/api/health" >/dev/null 2>&1; then
    echo "FinAlly didn't respond in time. Check: docker logs $CONTAINER" >&2
    exit 1
  fi
  echo "FinAlly is running at $URL"
fi

echo "Stop it with scripts/stop_mac.sh"
if [ "$open_browser" = true ]; then
  if command -v open >/dev/null 2>&1; then
    open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 || true
  fi
fi
