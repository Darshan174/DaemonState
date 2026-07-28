#!/usr/bin/env bash
# DaemonState — bare-metal self-hosting supervisor
# Usage: bash scripts/start.sh
# Set DAEMONSTATE_START_WORKER=0 to run only the API.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

read_env_value() {
  local key="$1"
  [[ -f .env ]] || return 0
  awk -v key="${key}" '
    index($0, key "=") == 1 {
      print substr($0, length(key) + 2)
      exit
    }
  ' .env
}

file_port="$(read_env_value "PORT")"
file_workers="$(read_env_value "WORKERS")"
file_bind_address="$(read_env_value "BIND_ADDRESS")"
PORT="${PORT:-${file_port:-8000}}"
WORKERS="${WORKERS:-${file_workers:-1}}"
BIND_ADDRESS="${BIND_ADDRESS:-${file_bind_address:-127.0.0.1}}"
PYTHON_BIN="${PYTHON_BIN:-}"
START_SYNC_WORKER="${DAEMONSTATE_START_WORKER:-1}"

if [[ -z "${PYTHON_BIN}" && -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ ! "${PORT}" =~ ^[0-9]{1,5}$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "PORT must be between 1 and 65535." >&2
  exit 1
fi
if [[ ! "${WORKERS}" =~ ^[0-9]+$ ]] || (( WORKERS < 1 )); then
  echo "WORKERS must be a positive integer." >&2
  exit 1
fi
if [[ "${BIND_ADDRESS}" != "127.0.0.1" ]]; then
  if [[ "${DAEMONSTATE_ALLOW_REMOTE_BIND:-0}" != "1" ]]; then
    echo "The supported workstation profile requires BIND_ADDRESS=127.0.0.1." >&2
    echo "Use the hardened production profile for remote API access." >&2
    exit 1
  fi
  if ! "${PYTHON_BIN}" - "${BIND_ADDRESS}" <<'PY' >/dev/null 2>&1
import ipaddress
import sys

ipaddress.IPv4Address(sys.argv[1])
PY
  then
    echo "BIND_ADDRESS must be an IPv4 address." >&2
    exit 1
  fi
  echo "warning: remote workstation binding was explicitly enabled; local action endpoints are exposed." >&2
fi

api_pid=""
worker_pid=""

stop_processes() {
  trap - EXIT INT TERM
  for pid in "${worker_pid}" "${api_pid}"; do
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill -TERM "${pid}" 2>/dev/null || true
    fi
  done
  for pid in "${worker_pid}" "${api_pid}"; do
    if [[ -n "${pid}" ]]; then
      wait "${pid}" 2>/dev/null || true
    fi
  done
}

handle_interrupt() {
  stop_processes
  exit 130
}

trap stop_processes EXIT
trap handle_interrupt INT TERM

echo "Starting DaemonState API on ${BIND_ADDRESS}:${PORT}…"
"${PYTHON_BIN}" -m uvicorn app.main:app \
  --host "${BIND_ADDRESS}" \
  --port "${PORT}" \
  --workers "${WORKERS}" &
api_pid="$!"

case "${BIND_ADDRESS}" in
  "::"|"::1")
    readiness_url="http://[::1]:${PORT}/health/ready"
    display_url="http://[::1]:${PORT}"
    ;;
  "0.0.0.0")
    readiness_url="http://127.0.0.1:${PORT}/health/ready"
    display_url="http://127.0.0.1:${PORT}"
    ;;
  *)
    readiness_url="http://${BIND_ADDRESS}:${PORT}/health/ready"
    display_url="http://${BIND_ADDRESS}:${PORT}"
    ;;
esac

ready=0
for _ in $(seq 1 120); do
  if ! kill -0 "${api_pid}" 2>/dev/null; then
    break
  fi
  if "${PYTHON_BIN}" - "${readiness_url}" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

with urllib.request.urlopen(sys.argv[1], timeout=1) as response:
    raise SystemExit(0 if response.status == 200 else 1)
PY
  then
    ready=1
    break
  fi
  sleep 1
done

if [[ "${ready}" -ne 1 ]]; then
  echo "DaemonState API did not become ready." >&2
  if ! kill -0 "${api_pid}" 2>/dev/null; then
    set +e
    wait "${api_pid}"
    exit_status="$?"
    set -e
    if [[ "${exit_status}" -eq 0 ]]; then
      exit 1
    fi
    exit "${exit_status}"
  else
    stop_processes
    api_pid=""
    worker_pid=""
    exit 1
  fi
fi

echo "DaemonState API is ready at ${display_url}"

if [[ "${START_SYNC_WORKER}" == "0" ]]; then
  wait "${api_pid}"
  exit "$?"
fi

echo "Starting connector sync worker…"
"${PYTHON_BIN}" -m app.cli.main worker sync --watch &
worker_pid="$!"

while kill -0 "${api_pid}" 2>/dev/null && kill -0 "${worker_pid}" 2>/dev/null; do
  sleep 2
done

set +e
if ! kill -0 "${api_pid}" 2>/dev/null; then
  wait "${api_pid}"
  exit_status="$?"
  echo "DaemonState API stopped (status ${exit_status})." >&2
else
  wait "${worker_pid}"
  exit_status="$?"
  echo "DaemonState sync worker stopped (status ${exit_status})." >&2
fi
set -e

exit "${exit_status}"
