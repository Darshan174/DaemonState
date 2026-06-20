#!/usr/bin/env bash
# Context Engine — production start script
# Usage: bash scripts/start.sh
set -euo pipefail

PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"
PYTHON_BIN="${PYTHON_BIN:-}"

if [[ -z "${PYTHON_BIN}" && -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "Starting Context Engine on port ${PORT}…"
exec "${PYTHON_BIN}" -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --workers "${WORKERS}"
