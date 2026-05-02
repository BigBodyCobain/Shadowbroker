#!/usr/bin/env bash
# Cross-platform Tauri dev launcher.
#
# Prerequisites:
#   - Rust toolchain (rustup.rs)
#   - Tauri CLI: cargo install tauri-cli@^2
#   - Node.js 18+ and the frontend dev server running on :3000
#   - Backend running on :8000 (or set SHADOWBROKER_BACKEND_URL)
#
# Usage:
#   ./dev.sh                                # default backend at http://127.0.0.1:8000
#   SHADOWBROKER_ADMIN_KEY=secret ./dev.sh  # with admin key for privileged commands
#
# This script starts Tauri in dev mode, which:
#   1. Opens a native window pointed at the frontend dev server (http://127.0.0.1:3000)
#   2. Injects window.__SHADOWBROKER_DESKTOP__ for native command routing
#   3. Proxies privileged commands to the backend with X-Admin-Key header
#
# Platform notes:
#   Linux:   Requires webkit2gtk-4.1 and libayatana-appindicator3 dev packages.
#            Debian/Ubuntu: sudo apt install libwebkit2gtk-4.1-dev libayatana-appindicator3-dev
#   macOS:   Xcode command-line tools required.
#   Windows: Run from Git Bash, WSL, or MSYS2. Visual Studio C++ build tools required.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$SCRIPT_DIR/src-tauri/icons" ]; then
    if command -v node >/dev/null 2>&1; then
        node "$SCRIPT_DIR/scripts/generate-icons.cjs"
    fi
fi

cd "$SCRIPT_DIR/src-tauri"

export SHADOWBROKER_BACKEND_URL="${SHADOWBROKER_BACKEND_URL:-http://127.0.0.1:8000}"

echo "=== ShadowBroker Tauri Dev Shell ==="
echo "Backend URL: $SHADOWBROKER_BACKEND_URL"
echo "Admin key:   ${SHADOWBROKER_ADMIN_KEY:+(set)}"
echo ""
echo "Make sure the frontend dev server is running on http://127.0.0.1:3000"
echo "Make sure the backend is running on $SHADOWBROKER_BACKEND_URL"
echo ""

cargo tauri dev
