#!/bin/bash

echo "======================================================="
echo "   S H A D O W B R O K E R   -   macOS / Linux Stop   "
echo "======================================================="

echo ""
echo "[*] Killing all ShadowBroker processes..."

stop_port() {
    local PORT="$1"
    local PIDS=""
    if command -v lsof >/dev/null 2>&1; then
        PIDS="$(lsof -ti :"$PORT" 2>/dev/null)"
    elif command -v ss >/dev/null 2>&1; then
        PIDS="$(ss -tlnp "sport = :$PORT" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u)"
    elif command -v fuser >/dev/null 2>&1; then
        PIDS="$(fuser "$PORT/tcp" 2>/dev/null)"
    fi
    for PID in $PIDS; do
        echo "    Killing PID $PID (port $PORT)"
        kill -9 "$PID" 2>/dev/null || true
    done
}

for PORT in 8000 3000 8787; do
    stop_port "$PORT"
done

echo "[*] Killing orphaned uvicorn and ais_proxy processes..."
pkill -9 -f "uvicorn.*main:app" 2>/dev/null || true
pkill -9 -f "ais_proxy" 2>/dev/null || true
pkill -9 -f "wormhole_server.py" 2>/dev/null || true

sleep 1

echo ""
echo "[*] All processes stopped. Ports 8000/3000 should be free."
echo ""
