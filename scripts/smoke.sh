#!/usr/bin/env bash
# Context Engine — launch smoke checks
# Usage:
#   bash scripts/smoke.sh
#   bash scripts/smoke.sh --docker
set -euo pipefail

RUN_DOCKER_SMOKE=0
SMOKE_PORT="${SMOKE_PORT:-18080}"
PROJECT_NAME="${SMOKE_PROJECT_NAME:-context-engine-smoke}"

for arg in "$@"; do
  case "$arg" in
    --docker)
      RUN_DOCKER_SMOKE=1
      ;;
    -h|--help)
      sed -n '1,12p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

info() { printf "\n==> %s\n" "$*"; }
ok() { printf "ok: %s\n" "$*"; }
warn() { printf "warn: %s\n" "$*" >&2; }

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

require_command python3
require_command npm

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" && -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi
PYTHON_BIN="${PYTHON_BIN:-python3}"

info "Shell script syntax"
for script in scripts/setup.sh scripts/start.sh scripts/dev.sh scripts/doctor.sh scripts/smoke.sh; do
  bash -n "$script"
done

info "Backend tests"
"${PYTHON_BIN}" -m pytest tests/ -q

info "Backend lint"
"${PYTHON_BIN}" -m ruff check app tests

info "Frontend tests"
(cd frontend && npm test)

info "Frontend build"
(cd frontend && npm run build)

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  info "Docker compose config"
  docker compose config --quiet
  docker compose -f docker-compose.smoke.yml -p "$PROJECT_NAME" config --quiet
else
  if [[ "$RUN_DOCKER_SMOKE" -eq 1 ]]; then
    echo "Docker with compose support is required for --docker" >&2
    exit 1
  fi
  warn "Docker compose unavailable; skipped Docker config validation"
fi

if [[ "$RUN_DOCKER_SMOKE" -ne 1 ]]; then
  ok "local smoke checks passed"
  exit 0
fi

info "Docker build/start/health smoke"
cleanup() {
  if [[ "${KEEP_SMOKE:-0}" != "1" ]]; then
    docker compose -f docker-compose.smoke.yml -p "$PROJECT_NAME" down -v >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

docker compose -f docker-compose.smoke.yml -p "$PROJECT_NAME" up --build -d

python3 - "$SMOKE_PORT" <<'PY'
import json
import sys
import time
import urllib.error
import urllib.request

port = sys.argv[1]
base = f"http://127.0.0.1:{port}"

def request(path, payload=None):
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
    req = urllib.request.Request(f"{base}{path}", data=body, headers=headers)
    last_exc = None
    for _ in range(5):
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_exc = exc
            time.sleep(2)
    raise RuntimeError(f"request failed after retries: {path}: {last_exc}")

def request_status(path, payload=None):
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
    req = urllib.request.Request(f"{base}{path}", data=body, headers=headers)
    last_exc = None
    for _ in range(5):
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                raw = response.read().decode("utf-8")
                return response.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"raw": raw}
            return exc.code, payload
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_exc = exc
            time.sleep(2)
    raise RuntimeError(f"request failed after retries: {path}: {last_exc}")

deadline = time.time() + 180
last_error = None
while time.time() < deadline:
    try:
        health = request("/health")
        if health.get("status") == "ok":
            break
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        last_error = exc
    time.sleep(3)
else:
    raise SystemExit(f"container health did not become ok: {last_error}")

seed = request("/api/seed-demo", {})
seed_total = (
    seed.get("createdDocuments", 0)
    + seed.get("existingDocuments", 0)
    + seed.get("documents_created", 0)
    + seed.get("documents_updated", 0)
)
if seed_total <= 0:
    raise SystemExit(f"seed-demo did not create, update, or reuse documents: {seed}")
workspace_id = seed.get("workspaceId") or seed.get("workspace_id")
if not workspace_id:
    raise SystemExit(f"seed-demo did not return a workspace id: {seed}")

stats = request("/api/stats")
if stats.get("components", 0) <= 0 or stats.get("sources", 0) <= 0:
    raise SystemExit(f"stats missing seeded graph data: {stats}")

query = request("/api/query", {"question": "What is blocking launch?", "top_k": 3})
if query.get("schema_version") != "query.v1" or not query.get("answer"):
    raise SystemExit(f"query did not return a grounded query.v1 answer: {query}")

zoom_status, zoom_body = request_status(
    "/api/connectors/zoom/connect",
    {"workspace_id": workspace_id, "token": "smoke-zoom-token"},
)
if zoom_status != 400 or "coming soon" not in str(zoom_body).lower():
    raise SystemExit(f"zoom setup guardrail failed: status={zoom_status} body={zoom_body}")

notion_status, notion_body = request_status(
    "/api/connectors/notion/connect",
    {"workspace_id": workspace_id, "token": "smoke-notion-token"},
)
if notion_status != 404 or "notion" not in str(notion_body).lower():
    raise SystemExit(f"notion setup guardrail failed: status={notion_status} body={notion_body}")

print("ok: docker API smoke passed")
PY

ok "docker smoke checks passed"
