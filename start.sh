#!/bin/bash

# Graceful shutdown: kill all child processes on exit/interrupt
trap 'kill 0' EXIT SIGINT SIGTERM

echo "======================================================="
echo "   S H A D O W B R O K E R   -   macOS / Linux Start   "
echo "======================================================="
echo ""

# Check for stale docker-compose.yml from pre-migration clones
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/docker-compose.yml" ] && grep -q '^\s*build:' "$SCRIPT_DIR/docker-compose.yml" 2>/dev/null; then
    echo ""
    echo "================================================================"
    echo "  [!] WARNING: Your docker-compose.yml is outdated."
    echo ""
    echo "  It contains 'build:' directives, which means Docker will"
    echo "  compile from local source instead of pulling pre-built images."
    echo "  You will NOT receive updates this way."
    echo ""
    echo "  If you use Docker, re-clone the repository:"
    echo "    git clone https://github.com/BigBodyCobain/Shadowbroker.git"
    echo "    cd Shadowbroker && docker compose pull && docker compose up -d"
    echo "================================================================"
    echo ""
fi

# Check for Node.js
if ! command -v npm &> /dev/null; then
    echo "[!] ERROR: npm is not installed. Please install Node.js 18+ (https://nodejs.org/)"
    exit 1
fi
echo "[*] Found Node.js $(node --version)"

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

PYVER=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
echo "[*] Found Python $PYVER"
export BACKEND_BASE_PYTHON="$PYTHON_CMD"
PY_MINOR=$(echo "$PYVER" | cut -d. -f2)
if [ "$PY_MINOR" -ge 13 ] 2>/dev/null; then
    echo "[!] WARNING: Python $PYVER detected. Some packages may fail to build."
    echo "[!] Recommended: Python 3.10, 3.11, or 3.12."
    echo ""
fi

# Get the directory where this script lives
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Zombie cleanup ─────────────────────────────────────────────────
# Kill leftover processes from a previous crashed session.
echo ""
echo "[*] Clearing zombie processes..."

# Kill anything listening on ports 8000 or 3000
for PORT in 8000 3000; do
    if command -v lsof &> /dev/null; then
        PIDS=$(lsof -ti :$PORT 2>/dev/null)
    elif command -v ss &> /dev/null; then
        PIDS=$(ss -tlnp "sport = :$PORT" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u)
    elif command -v fuser &> /dev/null; then
        PIDS=$(fuser $PORT/tcp 2>/dev/null)
    else
        PIDS=""
    fi
    for P in $PIDS; do
        kill -9 "$P" 2>/dev/null
    done
done

# Kill orphaned uvicorn and ais_proxy processes
pkill -9 -f "uvicorn.*main:app" 2>/dev/null
pkill -9 -f "ais_proxy" 2>/dev/null

# Brief pause for OS to release ports
sleep 1

echo "[*] Ports clear."
# ───────────────────────────────────────────────────────────────────

echo ""
echo "[*] Setting up backend..."
cd "$SCRIPT_DIR/backend"
VENV_MARKER=".venv-dir"
PINNED_VENV_DIR=""
if [ -f "$VENV_MARKER" ]; then
    PINNED_VENV_DIR="$(head -n 1 "$VENV_MARKER" | tr -d '\r')"
fi

# Check if UV is available (preferred, much faster installs)
if command -v uv &> /dev/null; then
    echo "[*] Using UV for Python dependency management."
    PRIMARY_VENV_DIR="venv"
    if [ -n "$PINNED_VENV_DIR" ]; then
        PRIMARY_VENV_DIR="$PINNED_VENV_DIR"
    fi
    REPAIR_VENV_DIR="venv-repair-$$"
    VENV_DIR="$PRIMARY_VENV_DIR"
    VENV_PY="$VENV_DIR/bin/python3"
    if [ -x "$VENV_PY" ] && ! "$VENV_PY" --version >/dev/null 2>&1; then
        echo "[*] Existing backend Python venv is stale. Rebuilding it..."
        rm -rf "$PRIMARY_VENV_DIR" 2>/dev/null || true
        if [ -d "$PRIMARY_VENV_DIR" ]; then
            VENV_DIR="$REPAIR_VENV_DIR"
            VENV_PY="$VENV_DIR/bin/python3"
            echo "[*] Primary venv could not be replaced cleanly. Falling back to $REPAIR_VENV_DIR..."
        fi
    fi
    if [ "$VENV_DIR" != "$PRIMARY_VENV_DIR" ] && [ -x "$VENV_PY" ] && ! "$VENV_PY" --version >/dev/null 2>&1; then
        rm -rf "$VENV_DIR"
    fi
    export BACKEND_VENV_DIR="$VENV_DIR"
    if [ ! -d "$VENV_DIR" ]; then
        echo "[*] Creating Python virtual environment..."
        rm -rf "$VENV_DIR"
        uv venv "$VENV_DIR"
        if [ $? -ne 0 ]; then
            echo "[!] ERROR: Failed to create virtual environment."
            exit 1
        fi
    fi
    "$VENV_PY" --version >/dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "[!] ERROR: Backend virtual environment could not start Python after repair."
        exit 1
    fi
    echo "[*] Installing Python dependencies via UV (fast)..."
    cd "$SCRIPT_DIR"
    UV_PROJECT_ENVIRONMENT="$SCRIPT_DIR/backend/$VENV_DIR" uv sync --frozen --no-dev
    cd "$SCRIPT_DIR/backend"
else
    echo "[*] UV not found, using pip (install UV for faster installs: https://docs.astral.sh/uv/)"
    PRIMARY_VENV_DIR="venv"
    if [ -n "$PINNED_VENV_DIR" ]; then
        PRIMARY_VENV_DIR="$PINNED_VENV_DIR"
    fi
    REPAIR_VENV_DIR="venv-repair-$$"
    VENV_DIR="$PRIMARY_VENV_DIR"
    VENV_PY="$VENV_DIR/bin/python3"
    if [ -x "$VENV_PY" ] && ! "$VENV_PY" --version >/dev/null 2>&1; then
        echo "[*] Existing backend Python venv is stale. Rebuilding it..."
        rm -rf "$PRIMARY_VENV_DIR" 2>/dev/null || true
        if [ -d "$PRIMARY_VENV_DIR" ]; then
            VENV_DIR="$REPAIR_VENV_DIR"
            VENV_PY="$VENV_DIR/bin/python3"
            echo "[*] Primary venv could not be replaced cleanly. Falling back to $REPAIR_VENV_DIR..."
        fi
    fi
    if [ "$VENV_DIR" != "$PRIMARY_VENV_DIR" ] && [ -x "$VENV_PY" ] && ! "$VENV_PY" --version >/dev/null 2>&1; then
        rm -rf "$VENV_DIR"
    fi
    export BACKEND_VENV_DIR="$VENV_DIR"
    if [ ! -d "$VENV_DIR" ]; then
        echo "[*] Creating Python virtual environment..."
        $PYTHON_CMD -m venv "$VENV_DIR"
        if [ $? -ne 0 ]; then
            echo "[!] ERROR: Failed to create virtual environment."
            exit 1
        fi
    fi
    "$VENV_PY" --version >/dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "[!] ERROR: Backend virtual environment could not start Python after repair."
        exit 1
    fi
    echo "[*] Installing Python dependencies (this may take a minute)..."
    "$VENV_PY" -m pip install -q .
fi
if [ $? -ne 0 ]; then
    echo ""
    echo "[!] ERROR: Python dependency install failed. See errors above."
    echo "[!] If you see Rust/cargo errors, your Python version may be too new."
    echo "[!] Recommended: Python 3.10, 3.11, or 3.12."
    exit 1
fi
printf '%s\n' "$VENV_DIR" > "$VENV_MARKER"
echo "[*] Backend dependencies OK."
if [ ! -d "node_modules/ws" ]; then
    echo "[*] Installing backend Node.js dependencies..."
    npm ci --omit=dev --silent
fi
echo "[*] Backend Node.js dependencies OK."

cd "$SCRIPT_DIR"

echo ""
echo "[*] Setting up frontend..."
cd "$SCRIPT_DIR/frontend"
FRONTEND_DEPS_OK=1
if [ ! -d "node_modules" ]; then
    FRONTEND_DEPS_OK=0
fi
if [ "$FRONTEND_DEPS_OK" -eq 1 ]; then
    node -e "require.resolve('next/dist/bin/next',{paths:['.']});require.resolve('lucide-react',{paths:['.']});require.resolve('maplibre-gl',{paths:['.']});require.resolve('@swc/helpers/_/_interop_require_default',{paths:['.']})" >/dev/null 2>&1 || FRONTEND_DEPS_OK=0
fi
if [ "$FRONTEND_DEPS_OK" -eq 0 ]; then
    echo "[*] Frontend install is missing required packages. Repairing with npm ci..."
    npm ci
    if [ $? -ne 0 ]; then
        echo "[!] ERROR: frontend dependency install failed. See errors above."
        exit 1
    fi
fi
echo "[*] Frontend dependencies OK."

echo ""
echo "======================================================="
echo "  Starting services...                                 "
echo "  Dashboard: http://localhost:3000                     "
echo "  Keep this window open! Initial load takes ~10s.      "
echo "======================================================="
echo "  (Press Ctrl+C to stop)"
echo ""

npm run dev
