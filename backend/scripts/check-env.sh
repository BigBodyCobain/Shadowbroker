#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python3}"
"$PYTHON" -c "from services.env_check import validate_env; validate_env(strict=False)"
