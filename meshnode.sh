#!/usr/bin/env bash
# ShadowBroker Mesh Node — lightweight, headless
# Syncs the Infonet chain only. No map, no frontend, no data feeds.

set -e

echo "==================================================="
echo "    S H A D O W B R O K E R   --   MESH NODE"
echo "==================================================="
echo ""
echo "  Lightweight node — syncs the Infonet chain only."
echo "  No map, no frontend, no data feeds."
echo "  Press Ctrl+C to stop."
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "[!] ERROR: Python 3 is not installed."
    echo "[!] Install Python 3.10-3.12"
    exit 1
fi

PYVER=$(python3 --version 2>&1 | awk '{print $2}')
echo "[*] Found Python $PYVER"

cd "$(dirname "$0")/backend"

# Setup venv
if [ ! -d "venv" ]; then
    echo "[*] Creating Python virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "[*] Installing Python dependencies..."
pip install -q -r requirements.txt

# Install ws for ais_proxy
if [ ! -d "node_modules/ws" ]; then
    if command -v npm &>/dev/null; then
        echo "[*] Installing backend Node.js dependencies..."
        npm ci --omit=dev --silent 2>/dev/null || true
    fi
fi

echo "[*] Dependencies OK."

# Auto-enable node
echo "[*] Auto-enabling node participation..."
mkdir -p data
echo '{"enabled":true,"updated_at":0}' > data/node.json

echo ""
echo "==================================================="
echo "  Mesh node starting on port 8000"
echo "  Mode: MESH_ONLY (no data feeds)"
echo "  Relay: ${MESH_RELAY_PEERS:-default}"
echo "  Press Ctrl+C to stop"
echo "==================================================="
echo ""

export MESH_ONLY=true
export MESH_NODE_MODE=participant
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
