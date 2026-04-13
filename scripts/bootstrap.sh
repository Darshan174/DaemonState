#!/usr/bin/env bash
#
# scripts/bootstrap.sh — shell bootstrap wrapper for Context Engine.
#
# Brings up the full backend stack (Postgres + pgvector, Redis, API, worker)
# via docker compose, applies Alembic migrations, and seeds the deterministic
# demo workspace so you can immediately run the backend smoke path.
#
# Safe to re-run: every step is idempotent. This script is a lower-level shell
# wrapper around the same public contracts used by `ctxe demo` and `ctxe verify`.
#
# Usage:
#   bash scripts/bootstrap.sh
#
# Optional env:
#   BASE_URL          default http://localhost:8000
#   HEALTH_TIMEOUT_S  default 120   (seconds to wait for /health/ready)

set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

BASE_URL=${BASE_URL:-http://localhost:8000}
HEALTH_TIMEOUT_S=${HEALTH_TIMEOUT_S:-120}

log()  { printf "\n==> %s\n" "$*"; }
ok()   { printf "    [OK]   %s\n" "$*"; }
info() { printf "    [info] %s\n" "$*"; }
warn() { printf "    [warn] %s\n" "$*" >&2; }
die()  { printf "    [FAIL] %s\n" "$*" >&2; exit 1; }

# ── 1. Preflight ────────────────────────────────────────────────
log "1/5  Preflight"
command -v docker >/dev/null 2>&1 \
    || die "docker is not installed. Install: https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 \
    || die "docker compose v2 is required. Run 'docker compose version' to check. If you have docker-compose (v1) install the v2 plugin."
command -v curl >/dev/null 2>&1 \
    || die "curl is required for health checks. Install: apt install curl / brew install curl"

# Verify Docker daemon is running.
docker info >/dev/null 2>&1 \
    || die "Docker daemon is not running. Start it with: sudo systemctl start docker (Linux) or open Docker Desktop (macOS/Windows)."

docker_version=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "unknown")
compose_version=$(docker compose version --short 2>/dev/null || echo "unknown")
ok "docker ${docker_version}, compose ${compose_version}, curl present"

# ── 2. Environment file ─────────────────────────────────────────
log "2/5  Environment file"
if [ ! -f .env ]; then
    cp .env.example .env
    ok ".env created from .env.example"
else
    ok ".env already exists (left untouched)"
fi

# Generate ENCRYPTION_KEY if blank.
current_key=$(grep -E '^ENCRYPTION_KEY=' .env | head -n1 | cut -d= -f2- || true)
if [ -z "${current_key:-}" ]; then
    if command -v openssl >/dev/null 2>&1; then
        new_key=$(openssl rand -base64 32 | tr -d '\n')
    elif command -v python3 >/dev/null 2>&1; then
        new_key=$(python3 -c "from secrets import token_urlsafe; print(token_urlsafe(32))")
    else
        die "Cannot generate ENCRYPTION_KEY — install openssl or python3."
    fi
    # Portable in-place sed (GNU vs BSD).
    if sed --version >/dev/null 2>&1; then
        sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=${new_key}|" .env
    else
        sed -i '' "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=${new_key}|" .env
    fi
    ok "ENCRYPTION_KEY generated and written to .env"
else
    ok "ENCRYPTION_KEY already set"
fi

# ── 3. Start containers ─────────────────────────────────────────
log "3/5  Starting containers (postgres, redis, api, worker)"
if ! docker compose up -d --build 2>&1; then
    warn "docker compose up failed. Common causes:"
    warn "  - Port conflict: another process using 8000/5432/6379 (override in .env)"
    warn "  - Disk full: 'docker system df' to check"
    warn "  - Image build error: check Dockerfile syntax or missing dependencies"
    die "docker compose up -d --build failed"
fi
ok "docker compose up -d complete"

# ── 4. Wait for API readiness ───────────────────────────────────
log "4/5  Waiting for API readiness at ${BASE_URL}/health/ready (up to ${HEALTH_TIMEOUT_S}s)"
deadline=$(( $(date +%s) + HEALTH_TIMEOUT_S ))
attempt=0
until curl -fsS "${BASE_URL}/health/ready" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$(date +%s)" -ge "$deadline" ]; then
        warn "API did not become ready in ${HEALTH_TIMEOUT_S}s."
        warn ""
        warn "Diagnostic checklist:"
        warn "  1. Is the api container running?  → docker compose ps"
        warn "  2. Did it crash on startup?       → docker compose logs --tail 40 api"
        warn "  3. Is Postgres healthy?            → docker compose logs --tail 20 postgres"
        warn "  4. Is Redis healthy?               → docker compose logs --tail 10 redis"
        warn "  5. Port conflict?                  → lsof -i :8000"
        warn ""
        warn "Last 40 lines of api logs:"
        docker compose logs --tail 40 api >&2 || true
        die "Giving up. Increase HEALTH_TIMEOUT_S=${HEALTH_TIMEOUT_S} if the host is slow, or check the logs above."
    fi
    if [ $((attempt % 5)) -eq 0 ]; then
        elapsed=$((attempt * 2))
        # Show which services are up/down at each progress tick.
        running=$(docker compose ps --services --filter "status=running" 2>/dev/null | tr '\n' ' ' || true)
        info "still waiting… (${elapsed}s) — running: ${running:-none}"
    fi
    sleep 2
done
ok "API is ready at ${BASE_URL}"

# ── 5. Migrations + demo seed ───────────────────────────────────
log "5/5  Migrations and demo seed"
if ! docker compose exec -T api alembic upgrade head 2>&1; then
    warn "Alembic migration failed. Common fixes:"
    warn "  - 'target database is not up to date': run 'docker compose exec api alembic stamp head' then retry"
    warn "  - Connection refused: Postgres may not be ready yet — wait and retry"
    warn "  - Missing migration: check alembic/versions/ for the latest revision"
    die "alembic upgrade head failed"
fi
ok "alembic upgrade head"

# Seed via the HTTP surface (POST /api/seed-demo) so bootstrap exercises the
# same endpoint the frontend's "Run Demo Workspace" flow hits. This route
# delegates to the canonical seed_demo_workspace() and is idempotent.
seed_out=$(curl -fsS --max-time 60 \
    -X POST \
    -H 'Content-Type: application/json' \
    -d '{}' \
    "${BASE_URL}/api/seed-demo" 2>&1) \
    || die "POST ${BASE_URL}/api/seed-demo failed. If 404: rebuild the api container (docker compose up -d --build api). If 500: check docker compose logs api for the traceback."
printf "%s\n" "$seed_out"
workspace_id=$(printf "%s" "$seed_out" \
    | sed -n 's/.*"workspaceId"[^"]*"\([^"]*\)".*/\1/p' \
    | head -n1)
[ -n "$workspace_id" ] \
    || die "/api/seed-demo did not return a workspaceId. Response was: ${seed_out}"
ok "demo workspace ready: ${workspace_id}"

# Post-seed self-check: the seed endpoint returned 200, but was the
# workspace actually populated with a graph? Catches "seed succeeded
# structurally but the graph is empty" regressions — a broken
# _populate_demo_workspace() can return a fresh workspace row with
# zero components, and /api/seed-demo would still return ok.
graph_probe=$(curl -fsS --max-time 15 \
    "${BASE_URL}/api/graph?workspace_id=${workspace_id}" 2>&1) \
    || die "GET ${BASE_URL}/api/graph for the seeded workspace failed. Seed returned 200 but the graph endpoint errored. Check: docker compose logs api"
# Count nodes by matching "model_id" occurrences (one per node).
# The demo seed creates 20 components; anything below ~15 is a regression.
probe_nodes=$(printf "%s" "$graph_probe" | grep -o '"model_id"' | wc -l | tr -d ' ')
if [ "$probe_nodes" -lt 15 ]; then
    warn "Demo seed completed but workspace graph has only ${probe_nodes} node(s) — expected 15+ (seed defines 20 components)."
    warn "This usually means _populate_demo_workspace() in app/evals/demo_seed.py encountered a silent error."
    warn "Check: docker compose logs --tail 80 api"
    die "post-seed graph self-check failed: ${probe_nodes} nodes in workspace ${workspace_id}"
fi
ok "post-seed graph self-check: ${probe_nodes} nodes in workspace graph"

cat <<EOF

==> Bootstrap complete.

    API:           ${BASE_URL}
    Health:        ${BASE_URL}/health
    OpenAPI docs:  ${BASE_URL}/docs
    Workspace id:  ${workspace_id}

    Next steps:
      bash scripts/smoke.sh           # verify the stack (recommended, no extra deps)
      docker compose logs -f api      # tail api logs
      docker compose ps               # show container status
      docker compose down             # stop containers (named volumes persist)

    Maintainer / release-gate path (optional — not installed by bootstrap):
      python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
      ctxe verify --skip-frontend     # full gate, backend only (no Node.js required)
      ctxe verify                     # full gate including frontend (needs Node.js)

EOF
