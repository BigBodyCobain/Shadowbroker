#!/usr/bin/env bash
# ============================================================
#  WORMHOLE KILLER — macOS / Linux
#  Finds and terminates any orphaned wormhole_server.py processes
# ============================================================

echo ""
echo " ========================================"
echo "  SHADOWBROKER WORMHOLE CLEANUP (Unix)"
echo " ========================================"
echo ""

FOUND=0

# Kill any python process running wormhole_server.py
PIDS=$(pgrep -f "wormhole_server\.py" 2>/dev/null)
if [ -n "$PIDS" ]; then
    for PID in $PIDS; do
        echo " [KILL] Terminating wormhole process PID: $PID"
        kill -TERM "$PID" 2>/dev/null
        FOUND=1
    done
    # Give them a moment, then force-kill any survivors
    sleep 2
    for PID in $PIDS; do
        if kill -0 "$PID" 2>/dev/null; then
            echo " [FORCE] Force-killing PID: $PID"
            kill -9 "$PID" 2>/dev/null
        fi
    done
fi

# Also check port 8787 for anything lingering
PORT_PID=$(lsof -ti :8787 2>/dev/null)
if [ -n "$PORT_PID" ]; then
    for PID in $PORT_PID; do
        echo " [KILL] Terminating process on port 8787, PID: $PID"
        kill -TERM "$PID" 2>/dev/null
        FOUND=1
    done
fi

if [ "$FOUND" -eq 0 ]; then
    echo " [OK] No orphaned wormhole processes found."
else
    echo ""
    echo " [DONE] All wormhole processes terminated."
fi

echo ""
