#!/usr/bin/env bash
#
# scripts/bootstrap.sh — one-command self-hosted bootstrap for Context Engine.
#
# Brings up the full backend stack (Postgres + pgvector, Redis, API, worker)
# via docker compose, applies Alembic migrations, and seeds the deterministic
# demo workspace so you can immediately run scripts/smoke.sh.
#
# Safe to re-run: every step is idempotent.
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
    || die "docker is not installed. See https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 \
    || die "docker compose v2 is required (run \"docker compose version\" to verify)."
command -v curl >/dev/null 2>&1 \
    || die "curl is required on the host for health checks."
ok "docker, docker compose v2, curl present"

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
docker compose up -d --build
ok "docker compose up -d complete"

# ── 4. Wait for API readiness ───────────────────────────────────
log "4/5  Waiting for API readiness at ${BASE_URL}/health/ready (up to ${HEALTH_TIMEOUT_S}s)"
deadline=$(( $(date +%s) + HEALTH_TIMEOUT_S ))
attempt=0
until curl -fsS "${BASE_URL}/health/ready" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$(date +%s)" -ge "$deadline" ]; then
        warn "API did not become ready in ${HEALTH_TIMEOUT_S}s. Recent api logs:"
        docker compose logs --tail 80 api >&2 || true
        die "Giving up — check logs with: docker compose logs -f api"
    fi
    if [ $((attempt % 5)) -eq 0 ]; then
        info "still waiting… (elapsed $((attempt * 2))s)"
    fi
    sleep 2
done
ok "API is ready at ${BASE_URL}"

# ── 5. Migrations + demo seed ───────────────────────────────────
log "5/5  Migrations and demo seed"
docker compose exec -T api alembic upgrade head
ok "alembic upgrade head"

seed_out=$(docker compose exec -T api python scripts/seed_demo.py --json)
printf "%s\n" "$seed_out"
workspace_id=$(printf "%s" "$seed_out" \
    | sed -n 's/.*"workspace_id"[^"]*"\([^"]*\)".*/\1/p' \
    | head -n1)
[ -n "$workspace_id" ] || die "seed_demo.py did not return a workspace_id"
ok "demo workspace ready: ${workspace_id}"

cat <<EOF

==> Bootstrap complete.

    API:           ${BASE_URL}
    Health:        ${BASE_URL}/health
    OpenAPI docs:  ${BASE_URL}/docs
    Workspace id:  ${workspace_id}

    Next steps:
      bash scripts/smoke.sh           # verify boot, health, seed, and one query
      docker compose logs -f api      # tail api logs
      docker compose ps               # show container status
      docker compose down             # stop containers (named volumes persist)

EOF
