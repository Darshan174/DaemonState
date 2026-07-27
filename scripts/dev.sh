#!/usr/bin/env bash
# DaemonState — development mode
# Usage: bash scripts/dev.sh
# Opt in to backend reloads with DAEMONSTATE_BACKEND_RELOAD=1.
set -euo pipefail

echo "Starting DaemonState in development mode…"
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

# Keep the API stable by default. The frontend remains hot-reloaded by Vite,
# while backend reloads are opt-in so concurrent edits cannot repeatedly drop
# every open product page.
BACKEND_ARGS=(app.main:app --host localhost --port 8000)
if [[ "${DAEMONSTATE_BACKEND_RELOAD:-0}" == "1" ]]; then
  BACKEND_ARGS+=(--reload)
fi
"${PYTHON_BIN}" -m uvicorn "${BACKEND_ARGS[@]}" &

# Start frontend dev server
(cd frontend && npm run dev) &

wait
