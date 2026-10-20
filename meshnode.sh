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
echo "  Private hashchain relay: gate messages + offline DM spool."
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

export MESH_ONLY=true
export SHADOWBROKER_MESH_NODE_RUNTIME=true
export MESH_NODE_MODE=participant
export MESH_INFONET_ALLOW_CLEARNET_SYNC=false
export MESH_ARTI_ENABLED=true
export MESH_DM_HASHCHAIN_SPOOL_LIMIT=2
export MESH_DM_HASHCHAIN_SPOOL_TTL_S=3600
export MESH_BOOTSTRAP_SEED_PEERS="${MESH_BOOTSTRAP_SEED_PEERS:-}"
export MESH_INFONET_FLEET_JOIN="${MESH_INFONET_FLEET_JOIN:-true}"
export MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY="${MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY:-ul1d0kj/ODPIp0OhHzX8eLAVXzJ3CVvzW1vn2IC6q3I=}"
export MESH_SYNC_TIMEOUT_S="${MESH_SYNC_TIMEOUT_S:-45}"
export MESH_RELAY_PUSH_TIMEOUT_S="${MESH_RELAY_PUSH_TIMEOUT_S:-45}"
export MESH_SYNC_MAX_PEERS_PER_CYCLE="${MESH_SYNC_MAX_PEERS_PER_CYCLE:-5}"
export MESH_SWARM_MANIFEST_PULL_INTERVAL_S="${MESH_SWARM_MANIFEST_PULL_INTERVAL_S:-300}"

echo ""
echo "==================================================="
echo "  Mesh node starting on port 8000"
echo "  Mode: MESH_ONLY (no data feeds)"
echo "  Bootstrap: ${MESH_BOOTSTRAP_SEED_PEERS:-sb-testnet fleet defaults}"
echo "  Swarm: announce + signed manifest pull (fleet join)"
echo "  Press Ctrl+C to stop"
echo "==================================================="
echo ""

python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
