#!/usr/bin/env bash
# Context Engine — development mode (hot reload on both backend and frontend)
# Usage: bash scripts/dev.sh
set -euo pipefail

echo "Starting Context Engine in development mode…"
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:5000"
echo ""

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" && -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Trap to kill both processes on exit
cleanup() { kill 0 2>/dev/null; }
trap cleanup EXIT INT TERM

# Start backend
"${PYTHON_BIN}" -m uvicorn app.main:app --host localhost --port 8000 --reload &

# Start frontend dev server
(cd frontend && npm run dev) &

wait
