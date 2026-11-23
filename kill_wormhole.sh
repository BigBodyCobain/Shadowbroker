#!/usr/bin/env bash
set -euo pipefail

echo "=========================================="
echo " SHADOWBROKER - Kill Wormhole Process"
echo "=========================================="
echo

# 1. Try graceful API shutdown via the backend
echo "[*] Attempting graceful shutdown via API..."
if curl -s -X POST http://127.0.0.1:8000/api/wormhole/leave > /dev/null 2>&1; then
    echo "[+] API leave request sent."
else
    echo "[-] Backend not reachable, skipping API call."
fi

# 2. Kill any process listening on port 8787 (Wormhole server)
echo "[*] Checking port 8787 for Wormhole process..."
if command -v lsof > /dev/null 2>&1; then
    PIDS=$(lsof -ti :8787 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        for PID in $PIDS; do
            echo "[*] Found PID $PID on port 8787, killing..."
            kill -TERM "$PID" 2>/dev/null || kill -9 "$PID" 2>/dev/null || true
            echo "[+] Killed PID $PID"
        done
    else
        echo "[-] No process found on port 8787."
    fi
elif command -v ss > /dev/null 2>&1; then
    PIDS=$(ss -tlnp 'sport = :8787' 2>/dev/null | grep -oP 'pid=\K[0-9]+' || true)
    if [ -n "$PIDS" ]; then
        for PID in $PIDS; do
            echo "[*] Found PID $PID on port 8787, killing..."
            kill -TERM "$PID" 2>/dev/null || kill -9 "$PID" 2>/dev/null || true
            echo "[+] Killed PID $PID"
        done
    else
        echo "[-] No process found on port 8787."
    fi
else
    echo "[-] Neither lsof nor ss available, skipping port check."
fi

# 3. Kill any python process running wormhole_server.py
echo "[*] Searching for wormhole_server.py processes..."
PIDS=$(pgrep -f "wormhole_server.py" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    for PID in $PIDS; do
        echo "[*] Killing wormhole_server.py PID $PID"
        kill -TERM "$PID" 2>/dev/null || kill -9 "$PID" 2>/dev/null || true
        echo "[+] Killed PID $PID"
    done
else
    echo "[-] No wormhole_server.py processes found."
fi

echo
echo "[+] Wormhole cleanup complete."
echo "    If processes persist, check 'ps aux | grep wormhole' manually."
