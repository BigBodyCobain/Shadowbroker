#!/usr/bin/env bash
# Cross-platform Tauri production build.
#
# Prerequisites:
#   - Rust toolchain (rustup.rs)
#   - Tauri CLI: cargo install tauri-cli@^2
#   - Node.js 18+ (for frontend build)
#   - Node.js 18+ (for frontend build and asset/release tooling)
#
# What this script does:
#   1. Generates branded bundle icons in src-tauri/icons/
#   2. Builds the frontend as a static export (NEXT_OUTPUT=export)
#   3. Copies the export to src-tauri/companion-www for the companion server
#   4. Runs cargo tauri build to produce the native bundle
#   5. Writes SHA256SUMS.txt, release-manifest.json, and latest.json
#
# The static export is used for:
#   - Tauri webview content (frontendDist in tauri.conf.json)
#   - Companion server static assets (companion-www bundle resource)
#
# The web deployment (Docker/Vercel) is unaffected - it continues to use
# output: 'standalone' via the normal `npm run build` without NEXT_OUTPUT.
#
# Usage:
#   ./build.sh
#   ./build.sh --clean
#
# Output:
#   Platform-specific bundle in src-tauri/target/release/bundle/
#   - Linux:   .deb, .AppImage
#   - macOS:   .dmg, .app
#   - Windows: .msi, .exe
#
# This is a polished unsigned app build path. Updater signing is configured
# when TAURI_SIGNING_PRIVATE_KEY_PATH/TAURI_SIGNING_PRIVATE_KEY is available.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
FRONTEND_OUT="$FRONTEND_DIR/out"
ICON_SCRIPT="$SCRIPT_DIR/scripts/generate-icons.cjs"
EXPORT_SCRIPT="$SCRIPT_DIR/scripts/build-frontend-export.cjs"
BACKEND_RUNTIME_SCRIPT="$SCRIPT_DIR/scripts/build-backend-runtime.cjs"
MANIFEST_SCRIPT="$SCRIPT_DIR/scripts/write-release-manifest.cjs"
LOCAL_UPDATER_KEY="$REPO_ROOT/release-secrets/shadowbroker-updater.key"
LOCAL_UPDATER_KEY_PASSWORD="$REPO_ROOT/release-secrets/shadowbroker-updater.key.pass"
CLEAN=0

for arg in "$@"; do
    case "$arg" in
        --clean)
            CLEAN=1
            ;;
        *)
            echo "ERROR: unknown argument: $arg"
            echo "Usage: ./build.sh [--clean]"
            exit 1
            ;;
    esac
done

ensure_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "ERROR: required command not found: $1"
        exit 1
    fi
}

ensure_cmd npm
ensure_cmd node
ensure_cmd cargo

if ! cargo tauri -V >/dev/null 2>&1; then
    echo "ERROR: cargo tauri is required for desktop packaging."
    echo "Install it with: cargo install tauri-cli@^2"
    exit 1
fi

if [ "$CLEAN" -eq 1 ]; then
    echo "=== Cleaning previous desktop release artifacts ==="
    rm -rf \
        "$FRONTEND_OUT" \
        "$SCRIPT_DIR/src-tauri/companion-www" \
        "$SCRIPT_DIR/src-tauri/backend-runtime" \
        "$SCRIPT_DIR/src-tauri/icons" \
        "$SCRIPT_DIR/src-tauri/target/release/bundle" \
        "$SCRIPT_DIR/src-tauri/target/release/wix" \
        "$SCRIPT_DIR/src-tauri/target/release/nsis"
    echo ""
fi

echo "=== Generating branded desktop icons ==="
node "$ICON_SCRIPT"
echo ""

echo "=== Building frontend static export for desktop packaging ==="
echo ""
node "$EXPORT_SCRIPT"
echo ""

echo "=== Staging managed backend runtime for desktop packaging ==="
node "$BACKEND_RUNTIME_SCRIPT"
echo ""

if [ ! -d "$FRONTEND_OUT" ]; then
    echo "ERROR: frontend/out/ does not exist after build."
    echo ""
    echo "Possible causes:"
    echo "  - Dynamic routes without generateStaticParams"
    echo "  - Build errors in the frontend"
    echo ""
    echo "Try running manually:"
    echo "  node desktop-shell/tauri-skeleton/scripts/build-frontend-export.cjs"
    exit 1
fi
if [ ! -d "$SCRIPT_DIR/src-tauri/backend-runtime" ]; then
    echo "ERROR: src-tauri/backend-runtime/ does not exist after staging."
    exit 1
fi

echo "Copying frontend export to companion-www..."
rm -rf "$SCRIPT_DIR/src-tauri/companion-www"
cp -r "$FRONTEND_OUT" "$SCRIPT_DIR/src-tauri/companion-www"
echo "  -> $(find "$SCRIPT_DIR/src-tauri/companion-www" -type f | wc -l | tr -d ' ') files"
echo ""

cd "$SCRIPT_DIR/src-tauri"

export SHADOWBROKER_BACKEND_URL="${SHADOWBROKER_BACKEND_URL:-http://127.0.0.1:8000}"
if [ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ] && [ -z "${TAURI_SIGNING_PRIVATE_KEY_PATH:-}" ] && [ -f "$LOCAL_UPDATER_KEY" ]; then
    TAURI_SIGNING_PRIVATE_KEY="$(cat "$LOCAL_UPDATER_KEY")"
    export TAURI_SIGNING_PRIVATE_KEY
    if [ -z "${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}" ] && [ -f "$LOCAL_UPDATER_KEY_PASSWORD" ]; then
        TAURI_SIGNING_PRIVATE_KEY_PASSWORD="$(cat "$LOCAL_UPDATER_KEY_PASSWORD")"
        export TAURI_SIGNING_PRIVATE_KEY_PASSWORD
    fi
fi

echo "=== ShadowBroker Tauri Build ==="
echo "Frontend dist:    $FRONTEND_OUT"
echo "Companion www:    $SCRIPT_DIR/src-tauri/companion-www"
echo "Backend runtime:  $SCRIPT_DIR/src-tauri/backend-runtime"
echo "Backend URL:      $SHADOWBROKER_BACKEND_URL"
if [ -n "${TAURI_SIGNING_PRIVATE_KEY:-}" ] || [ -n "${TAURI_SIGNING_PRIVATE_KEY_PATH:-}" ]; then
    echo "Updater signing:  enabled"
else
    echo "Updater signing:  disabled (set TAURI_SIGNING_PRIVATE_KEY_PATH to emit update signatures)"
fi
echo ""

cargo tauri build

BUNDLE_DIR="$SCRIPT_DIR/src-tauri/target/release/bundle"
if [ -d "$BUNDLE_DIR" ]; then
    echo ""
    echo "=== Writing release manifest ==="
    node "$MANIFEST_SCRIPT" "$BUNDLE_DIR"
fi
