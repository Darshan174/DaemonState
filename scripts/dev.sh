#!/usr/bin/env bash
# Context Engine — development mode (hot reload on both backend and frontend)
# Usage: bash scripts/dev.sh
set -euo pipefail

echo "Starting Context Engine in development mode…"
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:5000"
echo ""

# Trap to kill both processes on exit
cleanup() { kill 0 2>/dev/null; }
trap cleanup EXIT INT TERM

# Start backend
uvicorn app.main:app --host localhost --port 8000 --reload &

# Start frontend dev server
(cd frontend && npm run dev) &

wait
