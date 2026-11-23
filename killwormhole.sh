#!/usr/bin/env bash
set -euo pipefail

# Compatibility wrapper: canonical script is kill_wormhole.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANONICAL="$SCRIPT_DIR/kill_wormhole.sh"

echo "[deprecated] killwormhole.sh is deprecated; use kill_wormhole.sh" >&2

if [ ! -x "$CANONICAL" ]; then
  echo "Canonical script not found or not executable: $CANONICAL" >&2
  exit 1
fi

exec "$CANONICAL" "$@"
