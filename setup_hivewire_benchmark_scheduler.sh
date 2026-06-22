#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$ROOT_DIR/co-routing"
PROFILE="${HIVEWIRE_BENCHMARK_PROFILE:-weekly-proxycheap-baseline}"
PROFILES_FILE="${HIVEWIRE_BENCHMARK_PROFILES:-$APP_DIR/benchmark/profiles.yaml}"
PROFILES_EXAMPLE="$APP_DIR/benchmark/profiles.yaml.example"
PLIST_DIR="${HIVEWIRE_LAUNCHD_DIR:-$HOME/Library/LaunchAgents}"
PLIST_PATH="${HIVEWIRE_LAUNCHD_PLIST:-$PLIST_DIR/com.hivewire.benchmark.${PROFILE}.plist}"

cd "$APP_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to generate the Hivewire benchmark scheduler plist."
  echo "Install it from https://docs.astral.sh/uv/ and run this script again."
  exit 1
fi

if [[ ! -f "$PROFILES_FILE" ]]; then
  if [[ ! -f "$PROFILES_EXAMPLE" ]]; then
    echo "Missing profile example: $PROFILES_EXAMPLE"
    exit 1
  fi
  cp "$PROFILES_EXAMPLE" "$PROFILES_FILE"
  echo "Created local benchmark profiles:"
  echo "  $PROFILES_FILE"
else
  echo "Using existing benchmark profiles:"
  echo "  $PROFILES_FILE"
fi

mkdir -p "$PLIST_DIR"
uv run python -m benchmark.scheduler \
  --profiles "$PROFILES_FILE" \
  --profile "$PROFILE" \
  --out "$PLIST_PATH"

echo
echo "DRY-RUN complete. The launchd plist was generated but not installed."
echo "Inspect it first:"
echo "  plutil -p \"$PLIST_PATH\""
echo
echo "When you are ready, install it manually with launchctl bootstrap:"
echo "  launchctl bootstrap <your-gui-domain> \"$PLIST_PATH\""
echo
echo "On this Mac, the gui domain is usually:"
echo "  gui/$(id -u)"
