#!/usr/bin/env bash
#
# scripts/smoke.sh — end-to-end self-hosted smoke verification.
#
# Proves four things against a running Context Engine stack:
#   1. BOOT   — docker compose reports api+postgres+redis running
#   2. HEALTH — /health returns ok AND /health/ready returns ready
#   3. SEED   — the deterministic demo workspace exists (idempotently seeded)
#   4. QUERY  — POST /api/query against the demo returns a source-backed answer
#
# Exit code 0 on success, non-zero (with a descriptive failure) otherwise.
#
# Usage:
#   bash scripts/smoke.sh
#
# Optional env:
#   BASE_URL         default http://localhost:8000
#   SMOKE_QUESTION   default "What is the Starter Plan?"
#   SMOKE_EXPECT     default "$29"    (substring that must appear in answer)

set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

BASE_URL=${BASE_URL:-http://localhost:8000}
SMOKE_QUESTION=${SMOKE_QUESTION:-"What is the Starter Plan?"}
SMOKE_EXPECT=${SMOKE_EXPECT:-"\$29"}

step() { printf "\n==> %s\n" "$*"; }
pass() { printf "    [PASS] %s\n" "$*"; }
fail() { printf "    [FAIL] %s\n" "$*" >&2; exit 1; }

require() {
    command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

require curl
require docker

# ── 1. BOOT ─────────────────────────────────────────────────────
step "1/4 BOOT — docker compose containers"
docker compose version >/dev/null 2>&1 || fail "docker compose v2 not available"
running=$(docker compose ps --services --filter "status=running" 2>/dev/null || true)
for svc in postgres redis api; do
    printf "%s\n" "$running" | grep -qx "$svc" \
        || fail "service '$svc' is not running (docker compose ps output below)\n$(docker compose ps)"
done
pass "postgres, redis, api are running"

# ── 2. HEALTH ───────────────────────────────────────────────────
step "2/4 HEALTH — /health and /health/ready"
health=$(curl -fsS --max-time 10 "${BASE_URL}/health") \
    || fail "GET ${BASE_URL}/health did not return 200"
printf "%s" "$health" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' \
    || fail "/health did not return status=ok: $health"
pass "/health → ok"

ready=$(curl -fsS --max-time 10 "${BASE_URL}/health/ready") \
    || fail "GET ${BASE_URL}/health/ready did not return 200 (DB or Redis unreachable?)"
printf "%s" "$ready" | grep -q '"status"[[:space:]]*:[[:space:]]*"ready"' \
    || fail "/health/ready did not return status=ready: $ready"
printf "%s" "$ready" | grep -q '"database"[[:space:]]*:[[:space:]]*"ok"' \
    || fail "/health/ready reports database not ok: $ready"
printf "%s" "$ready" | grep -q '"redis"[[:space:]]*:[[:space:]]*"ok"' \
    || fail "/health/ready reports redis not ok: $ready"
pass "/health/ready → ready (database + redis ok)"

# ── 3. SEED ─────────────────────────────────────────────────────
step "3/4 SEED — demo workspace"
seed_out=$(docker compose exec -T api python scripts/seed_demo.py --json) \
    || fail "seed_demo.py failed — is the api container healthy? (docker compose logs api)"
workspace_id=$(printf "%s" "$seed_out" \
    | sed -n 's/.*"workspace_id"[^"]*"\([^"]*\)".*/\1/p' \
    | head -n1)
[ -n "$workspace_id" ] || fail "seed_demo.py output missing workspace_id:\n$seed_out"
seed_status=$(printf "%s" "$seed_out" \
    | sed -n 's/.*"status"[^"]*"\([^"]*\)".*/\1/p' \
    | head -n1)
pass "demo workspace ${workspace_id} (${seed_status:-unknown})"

# ── 4. QUERY ────────────────────────────────────────────────────
step "4/4 QUERY — source-backed answer"
query_payload=$(printf '{"workspace_id":"%s","question":"%s"}' \
    "$workspace_id" "$SMOKE_QUESTION")
query_out=$(curl -fsS --max-time 30 \
    -X POST \
    -H 'Content-Type: application/json' \
    -d "$query_payload" \
    "${BASE_URL}/api/query") \
    || fail "POST /api/query failed"

printf "%s" "$query_out" | grep -q '"answer"' \
    || fail "query response missing 'answer' field:\n$query_out"
printf "%s" "$query_out" | grep -Fq "$SMOKE_EXPECT" \
    || fail "query answer did not contain expected token '${SMOKE_EXPECT}':\n$query_out"
printf "%s" "$query_out" | grep -q '"components"' \
    || fail "query response missing 'components' field (no provenance attached):\n$query_out"
pass "query returned an answer containing '${SMOKE_EXPECT}' with provenance"

cat <<EOF

==> SMOKE PASSED.

    Boot:   postgres + redis + api running
    Health: /health ok, /health/ready ok (db + redis)
    Seed:   demo workspace ${workspace_id} (${seed_status:-unknown})
    Query:  "${SMOKE_QUESTION}" returned a source-backed answer

    Context Engine is up, healthy, seeded, and answering queries.

EOF
