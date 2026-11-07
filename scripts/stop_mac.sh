#!/usr/bin/env bash
# Stop FinAlly. Safe to run repeatedly. Your data stays in the Docker volume.
set -euo pipefail

CONTAINER=finally

if ! command -v docker >/dev/null 2>&1; then
  export PATH="$PATH:/Applications/Docker.app/Contents/Resources/bin"
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker isn't running, so FinAlly isn't either."
  exit 0
fi

if docker inspect "$CONTAINER" >/dev/null 2>&1; then
  docker stop "$CONTAINER" >/dev/null
  docker rm "$CONTAINER" >/dev/null
  echo "FinAlly stopped. Your portfolio is saved."
else
  echo "FinAlly isn't running."
fi
