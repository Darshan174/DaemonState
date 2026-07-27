#!/usr/bin/env bash
# End-to-end smoke for the supported PostgreSQL personal self-hosting profile.
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

project_name="daemonstate-selfhost-smoke-${PPID}-${RANDOM}"
requested_port="${SELF_HOST_SMOKE_PORT:-0}"

if [[ ! "${requested_port}" =~ ^[0-9]{1,5}$ ]] || (( requested_port > 65535 )); then
  echo "SELF_HOST_SMOKE_PORT must be 0 (automatic) or between 1 and 65535." >&2
  exit 1
fi

command -v docker >/dev/null 2>&1 || {
  echo "Docker is required." >&2
  exit 1
}
command -v python3 >/dev/null 2>&1 || {
  echo "Python 3 is required." >&2
  exit 1
}
docker compose version >/dev/null 2>&1 || {
  echo "Docker Compose v2 is required." >&2
  exit 1
}
docker compose up --help | grep -- '--wait-timeout' >/dev/null || {
  echo "Docker Compose must support 'up --wait --wait-timeout'." >&2
  exit 1
}
docker info >/dev/null 2>&1 || {
  echo "The Docker daemon is not reachable." >&2
  exit 1
}

clean_environment=(
  env
  -i
  "HOME=${HOME}"
  "PATH=${PATH}"
  "PORT=${requested_port}"
  "BIND_ADDRESS=127.0.0.1"
  "POSTGRES_PASSWORD=self-host-smoke-password"
  "ENCRYPTION_KEY=MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
  "ALLOWED_HOSTS=localhost,127.0.0.1"
  "DAEMONSTATE_PROJECT_PATH=${repo_root}"
  "ENVIRONMENT=development"
  "DEMO_ENDPOINTS_ENABLED=true"
  "SERVER_API_KEY="
  "PRINCIPAL_API_KEYS="
  "LITELLM_API_KEY="
  "ENABLE_LOCAL_EMBEDDER=false"
  "OTEL_ENABLED=false"
  "PUBLIC_BASE_URL="
  "GOOGLE_CLIENT_ID="
  "GOOGLE_CLIENT_SECRET="
  "GOOGLE_REDIRECT_URI="
  "SLACK_CLIENT_ID="
  "SLACK_CLIENT_SECRET="
  "SLACK_REDIRECT_URI="
  "ZOOM_CLIENT_ID="
  "ZOOM_CLIENT_SECRET="
  "ZOOM_REDIRECT_URI="
)
for docker_variable in DOCKER_CONFIG DOCKER_CONTEXT DOCKER_HOST DOCKER_CERT_PATH DOCKER_TLS_VERIFY; do
  if [[ -n "${!docker_variable:-}" ]]; then
    clean_environment+=("${docker_variable}=${!docker_variable}")
  fi
done

compose() {
  "${clean_environment[@]}" docker compose \
    --project-directory "${repo_root}" \
    --file "${repo_root}/docker-compose.yml" \
    --env-file /dev/null \
    --project-name "${project_name}" \
    "$@"
}

cleanup() {
  local status="$?"
  trap - EXIT
  if [[ "${status}" -ne 0 ]]; then
    echo "self-host smoke failed; preserving bounded diagnostics:" >&2
    compose ps --all >&2 || true
    compose logs --no-color --tail 200 db migrate app worker >&2 || true
  fi
  if [[ "${KEEP_SELF_HOST_SMOKE:-0}" != "1" ]]; then
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  else
    echo "kept smoke project: ${project_name}" >&2
  fi
  exit "${status}"
}
trap cleanup EXIT

echo "self-host smoke project: ${project_name}"
compose config --quiet
compose up --build --detach --wait --wait-timeout 300

published_address="$(compose port app 8000)"
smoke_port="${published_address##*:}"
if [[ ! "${smoke_port}" =~ ^[0-9]{1,5}$ ]] || (( smoke_port < 1 || smoke_port > 65535 )); then
  echo "Could not determine the published app port: ${published_address}" >&2
  exit 1
fi

python3 - "${smoke_port}" <<'PY'
import json
import sys
import urllib.request

base = f"http://127.0.0.1:{sys.argv[1]}"


def request(path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"content-type": "application/json"} if body is not None else {}
    req = urllib.request.Request(f"{base}{path}", data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        raw = response.read().decode()
    return json.loads(raw) if raw else {}


ready = request("/health/ready")
if ready.get("status") not in {"ok", "ready"}:
    raise SystemExit(f"readiness response was not healthy: {ready}")

with urllib.request.urlopen(f"{base}/", timeout=20) as response:
    landing = response.read().decode()
if "<!doctype html" not in landing.lower():
    raise SystemExit("bundled dashboard HTML was not served")

for path, marker in (
    ("/assets/legal/LICENSE", "Sustainable Use License"),
    ("/assets/legal/NOTICE", "Copyright (c) 2026"),
    ("/assets/legal/THIRD_PARTY_NOTICES.txt", "SIL OPEN FONT LICENSE"),
):
    with urllib.request.urlopen(f"{base}{path}", timeout=20) as response:
        legal_text = response.read().decode()
    if marker not in legal_text:
        raise SystemExit(f"legal artifact was not served correctly: {path}")

seed = request("/api/seed-demo", {})
workspace_id = seed.get("workspaceId") or seed.get("workspace_id")
if not workspace_id:
    raise SystemExit(f"demo seed returned no workspace id: {seed}")

stats = request("/api/stats")
if stats.get("components", 0) <= 0 or stats.get("sources", 0) <= 0:
    raise SystemExit(f"demo data was not persisted: {stats}")
PY

compose exec -T app sh -c 'touch /data/.self-host-smoke-marker'
compose down --remove-orphans
compose up --detach --wait --wait-timeout 180

published_address="$(compose port app 8000)"
smoke_port="${published_address##*:}"
compose exec -T app test -f /data/.self-host-smoke-marker

python3 - "${smoke_port}" <<'PY'
import json
import sys
import urllib.request

with urllib.request.urlopen(
    f"http://127.0.0.1:{sys.argv[1]}/api/stats",
    timeout=20,
) as response:
    stats = json.loads(response.read().decode())
if stats.get("components", 0) <= 0 or stats.get("sources", 0) <= 0:
    raise SystemExit(f"seeded data did not survive restart: {stats}")
PY

echo "ok: PostgreSQL migration, dashboard, API, worker, and volume persistence passed"
