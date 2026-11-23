#!/usr/bin/env bash
# Start the backend and frontend together and restart either one if it exits.
# Usage: ./scripts/dev-servers.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"

# Generate/reuse a matching ADMIN_KEY for both processes.
ADMIN_KEY="$(cd "$ROOT/frontend" && node -e "process.stdout.write(require('./scripts/dev-admin.cjs').ensureDevAdminKey(process.cwd()))")"
export ADMIN_KEY

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

start_backend() {
  (cd "$ROOT/backend" && exec "$PYTHON" main.py) &
  BACKEND_PID=$!
  echo "[dev] backend started (pid $BACKEND_PID)"
}

start_frontend() {
  (cd "$ROOT/frontend" && exec npm run dev:frontend) &
  FRONTEND_PID=$!
  echo "[dev] frontend started (pid $FRONTEND_PID)"
}

wait_healthy() {
  local url="$1" name="$2" i
  for i in $(seq 1 90); do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      echo "[dev] $name healthy"
      return 0
    fi
    sleep 1
  done
  echo "[dev] $name did not become healthy" >&2
  return 1
}

start_backend
start_frontend
wait_healthy http://127.0.0.1:8000/api/health backend || true
wait_healthy http://127.0.0.1:3000/ frontend || true

while true; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "[dev] backend exited — restarting"
    start_backend
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo "[dev] frontend exited — restarting"
    start_frontend
  fi
  sleep 2
done
