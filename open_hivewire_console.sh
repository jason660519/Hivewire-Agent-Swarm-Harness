#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$ROOT_DIR/co-routing"
PORT="${HIVEWIRE_CONSOLE_PORT:-8799}"
URL="http://127.0.0.1:${PORT}/"
DATA_URL="http://127.0.0.1:${PORT}/data"
STARTED_PID=""

cd "$APP_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to start the Hivewire console."
  echo "Install it from https://docs.astral.sh/uv/ and run this launcher again."
  exit 1
fi

server_ready() {
  curl -fsS "$DATA_URL" >/dev/null 2>&1
}

open_url() {
  if command -v open >/dev/null 2>&1; then
    open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 &
  else
    echo "Open this URL in your browser: $URL"
  fi
}

if server_ready; then
  echo "Hivewire console server is already running on port $PORT."
  open_url
  echo "Opened $URL"
  exit 0
fi

echo "Starting Hivewire co-routing console on port $PORT..."
uv run python -m benchmark.dashboard --port "$PORT" &
STARTED_PID="$!"

cleanup() {
  if [[ -n "$STARTED_PID" ]] && kill -0 "$STARTED_PID" >/dev/null 2>&1; then
    kill "$STARTED_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

for _ in {1..50}; do
  if server_ready; then
    open_url
    echo "Opened $URL"
    echo
    echo "Console is running. Keep this terminal open; press Ctrl-C to stop."
    wait "$STARTED_PID"
    exit 0
  fi
  sleep 0.1
done

echo "Dashboard server did not become ready at $DATA_URL."
exit 1
