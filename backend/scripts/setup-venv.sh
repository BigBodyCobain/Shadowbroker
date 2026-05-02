#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python3.11}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$REPO_ROOT/venv"
VENV_MARKER="$REPO_ROOT/.venv-dir"

"$PYTHON" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
cd "$REPO_ROOT"
"$VENV_DIR/bin/python" -m pip install -e .
"$VENV_DIR/bin/pip" install pytest pytest-asyncio ruff black
printf 'venv\n' > "$VENV_MARKER"
