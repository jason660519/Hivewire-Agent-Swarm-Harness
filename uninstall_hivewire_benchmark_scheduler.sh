#!/usr/bin/env bash
set -euo pipefail

PROFILE="${HIVEWIRE_BENCHMARK_PROFILE:-weekly-proxycheap-baseline}"
PLIST_DIR="${HIVEWIRE_LAUNCHD_DIR:-$HOME/Library/LaunchAgents}"
PLIST_PATH="${HIVEWIRE_LAUNCHD_PLIST:-$PLIST_DIR/com.hivewire.benchmark.${PROFILE}.plist}"
LABEL="com.hivewire.benchmark.${PROFILE}"
GUI_DOMAIN="gui/$(id -u)"

echo "About to uninstall Hivewire benchmark scheduler:"
echo "  Label: $LABEL"
echo "  Plist: $PLIST_PATH"
echo "  Domain: $GUI_DOMAIN"
echo

if [[ "${HIVEWIRE_CONFIRM_UNINSTALL:-}" != "uninstall" ]]; then
  echo "Not uninstalled. To confirm, rerun with:"
  echo "  HIVEWIRE_CONFIRM_UNINSTALL=uninstall $0"
  exit 1
fi

launchctl bootout "$GUI_DOMAIN" "$PLIST_PATH" 2>/dev/null || launchctl remove "$LABEL" 2>/dev/null || true
rm -f "$PLIST_PATH"
echo "Uninstalled $LABEL"
