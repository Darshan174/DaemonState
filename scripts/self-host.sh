#!/usr/bin/env bash
# Start the supported personal Docker self-hosting profile.
# This profile is deliberately bound to loopback by default.
set -Eeuo pipefail
umask 077

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

fail() {
  echo "error: $*" >&2
  exit 1
}

set_env_value() {
  local key="$1"
  local value="$2"
  local temporary
  temporary="$(mktemp "${repo_root}/.env.tmp.XXXXXX")"
  if ! awk -v key="${key}" -v value="${value}" '
    BEGIN { found = 0 }
    index($0, key "=") == 1 {
      print key "=" value
      found = 1
      next
    }
    { print }
    END {
      if (!found) {
        print key "=" value
      }
    }
  ' .env >"${temporary}"; then
    rm -f "${temporary}"
    return 1
  fi
  chmod 0600 "${temporary}"
  mv "${temporary}" .env
}

read_env_value() {
  local key="$1"
  awk -v key="${key}" '
    index($0, key "=") == 1 {
      print substr($0, length(key) + 2)
      exit
    }
  ' .env
}

command -v docker >/dev/null 2>&1 || fail "Docker is required."
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required."
docker compose up --help | grep -- '--wait-timeout' >/dev/null \
  || fail "Docker Compose must support 'up --wait --wait-timeout'; upgrade Compose v2."
docker info >/dev/null 2>&1 || fail "The Docker daemon is not reachable."
if ! command -v python3 >/dev/null 2>&1 && ! command -v openssl >/dev/null 2>&1; then
  fail "python3 or openssl is required to generate first-run secrets."
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  set_env_value "POSTGRES_PASSWORD" "$(
    python3 -c 'import secrets; print(secrets.token_hex(32))' 2>/dev/null \
      || openssl rand -hex 32
  )"
  set_env_value "ENCRYPTION_KEY" "$(
    python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())' 2>/dev/null \
      || openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'
  )"
  chmod 0600 .env
  echo "Created a permission-restricted .env with generated local secrets."
else
  chmod 0600 .env
fi

postgres_password="${POSTGRES_PASSWORD:-$(read_env_value "POSTGRES_PASSWORD")}"
encryption_key="${ENCRYPTION_KEY:-$(read_env_value "ENCRYPTION_KEY")}"
if [[ -z "${postgres_password}" || "${postgres_password}" == "daemonstate" ]]; then
  fail "Set a non-example POSTGRES_PASSWORD in .env before starting. Do not change it after the database volume is initialized."
fi
if [[ -z "${encryption_key}" ]]; then
  fail "Set ENCRYPTION_KEY in .env before starting so connector credentials are encrypted."
fi
if [[ ! "${postgres_password}" =~ ^[A-Za-z0-9._~-]+$ ]]; then
  fail "POSTGRES_PASSWORD may contain only URL-safe letters, digits, '.', '_', '~', and '-'."
fi

file_bind_address="$(read_env_value "BIND_ADDRESS")"
bind_address="${BIND_ADDRESS:-${file_bind_address:-127.0.0.1}}"
if [[ "${bind_address}" != "127.0.0.1" ]]; then
  if [[ "${DAEMONSTATE_ALLOW_REMOTE_BIND:-0}" != "1" ]]; then
    fail "The supported personal profile requires BIND_ADDRESS=127.0.0.1. Use an SSH tunnel for remote dashboard access."
  fi
  python3 - "${bind_address}" <<'PY' >/dev/null 2>&1 || fail "BIND_ADDRESS must be an IPv4 address accepted by Docker."
import ipaddress
import sys

ipaddress.IPv4Address(sys.argv[1])
PY
  echo "warning: remote binding was explicitly enabled; the dashboard has no browser login." >&2
fi

file_allowed_hosts="$(read_env_value "ALLOWED_HOSTS")"
allowed_hosts="${ALLOWED_HOSTS:-${file_allowed_hosts:-localhost,127.0.0.1}}"
if [[ -z "${allowed_hosts}" || "${allowed_hosts}" == "*" ]]; then
  fail "ALLOWED_HOSTS must explicitly list trusted hostnames; use localhost,127.0.0.1 for personal hosting."
fi

file_port="$(read_env_value "PORT")"
port="${PORT:-${file_port:-8000}}"
if [[ ! "${port}" =~ ^[0-9]{1,5}$ ]] || (( port < 1 || port > 65535 )); then
  fail "PORT in .env must be between 1 and 65535."
fi

file_project_path="$(read_env_value "DAEMONSTATE_PROJECT_PATH")"
project_path="${DAEMONSTATE_PROJECT_PATH:-${file_project_path:-.}}"
if [[ ! -d "${project_path}" ]]; then
  fail "DAEMONSTATE_PROJECT_PATH must name an existing directory."
fi
project_path="$(cd "${project_path}" && pwd -P)"
if [[ "${project_path}" == "/" || "${project_path}" == "${HOME}" ]]; then
  fail "DAEMONSTATE_PROJECT_PATH cannot expose the filesystem root or your entire home directory."
fi
export DAEMONSTATE_PROJECT_PATH="${project_path}"

docker compose config --quiet
docker compose up --build --detach --wait --wait-timeout 300

echo
echo "DaemonState is ready at http://${bind_address}:${port}"
echo "Data is persisted in the Compose pg_data and daemonstate_uploads volumes."
echo "Use 'docker compose logs -f app worker' to follow the services."
