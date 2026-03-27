#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python3}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$REPO_ROOT/venv"

"$PYTHON" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -r "$REPO_ROOT/requirements-dev.txt"
