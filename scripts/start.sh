#!/usr/bin/env bash
# Context Engine — production start script
# Usage: bash scripts/start.sh
set -euo pipefail

PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"

echo "Starting Context Engine on port ${PORT}…"
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --workers "${WORKERS}"
