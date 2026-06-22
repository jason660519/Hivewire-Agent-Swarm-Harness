#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="${HIVEWIRE_BENCHMARK_PROFILE:-weekly-proxycheap-baseline}"
PLIST_DIR="${HIVEWIRE_LAUNCHD_DIR:-$HOME/Library/LaunchAgents}"
PLIST_PATH="${HIVEWIRE_LAUNCHD_PLIST:-$PLIST_DIR/com.hivewire.benchmark.${PROFILE}.plist}"
LABEL="com.hivewire.benchmark.${PROFILE}"
GUI_DOMAIN="gui/$(id -u)"

"$ROOT_DIR/setup_hivewire_benchmark_scheduler.sh"

echo
echo "About to install Hivewire benchmark scheduler:"
echo "  Label: $LABEL"
echo "  Plist: $PLIST_PATH"
echo "  Domain: $GUI_DOMAIN"
echo

if [[ "${HIVEWIRE_CONFIRM_INSTALL:-}" != "install" ]]; then
  echo "Not installed. To confirm, rerun with:"
  echo "  HIVEWIRE_CONFIRM_INSTALL=install $0"
  exit 1
fi

launchctl bootstrap "$GUI_DOMAIN" "$PLIST_PATH"
echo "Installed $LABEL"
