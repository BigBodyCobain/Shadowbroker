#!/bin/bash

trap 'kill 0' EXIT SIGINT SIGTERM

echo "======================================================="
echo "   W O R M H O L E   -   Local Agent Start             "
echo "======================================================="
echo ""

# Check for Python 3
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "[!] ERROR: Python is not installed."
    echo "[!] Install Python 3.10-3.12 from https://python.org"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/backend"

if [ ! -d "venv" ]; then
    echo "[*] Creating Python virtual environment..."
    $PYTHON_CMD -m venv venv
    if [ $? -ne 0 ]; then
        echo "[!] ERROR: Failed to create virtual environment."
        exit 1
    fi
fi

source venv/bin/activate
echo "[*] Installing Python dependencies (first run only)..."
pip install -q -r requirements.txt
if [ $? -ne 0 ]; then
    echo ""
    echo "[!] ERROR: pip install failed. See errors above."
    exit 1
fi

echo ""
echo "[*] Starting Wormhole Local Agent on 127.0.0.1:8787"
echo "[*] Press Ctrl+C to stop"
echo ""

export MESH_ONLY=true
export MESH_RNS_ENABLED=true
python wormhole_server.py
