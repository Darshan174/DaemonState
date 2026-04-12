#!/usr/bin/env bash
#
# scripts/smoke.sh — end-to-end self-hosted smoke verification.
#
# Proves four things against a running Context Engine stack:
#   1. BOOT       — docker compose reports api+postgres+redis running
#   2. HEALTH     — /health returns ok AND /health/ready returns ready
#   3. SEED       — POST /api/seed-demo creates the canonical demo workspace
#                   and is idempotent (second call returns same workspace
#                   with status="existing")
#   4. QUERY      — POST /api/query returns a source-backed answer
#   5. GRAPH      — GET /api/graph returns 15+ nodes, all with provenance
#   6. MODELS     — GET /api/models returns 4+ models; model graph has nodes
#   7. BRIEF      — GET /api/founder-brief returns structured content
#   8. DECISIONS  — GET /api/decisions returns entries with names + values
#   9. SOURCES    — GET /api/source-documents returns processed docs with content
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
step "1/9 BOOT — docker compose containers"
docker compose version >/dev/null 2>&1 || fail "docker compose v2 not available"
running=$(docker compose ps --services --filter "status=running" 2>/dev/null || true)
for svc in postgres redis api; do
    printf "%s\n" "$running" | grep -qx "$svc" \
        || fail "service '$svc' is not running (docker compose ps output below)\n$(docker compose ps)"
done
pass "postgres, redis, api are running"

# ── 2. HEALTH ───────────────────────────────────────────────────
step "2/9 HEALTH — /health and /health/ready"
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
step "3/9 SEED — POST /api/seed-demo (idempotent)"

extract_field() {
    # extract_field <json> <key> — pulls the string value for a top-level key
    # out of the pretty-printed JSON response from /api/seed-demo.
    printf "%s" "$1" \
        | sed -n "s/.*\"$2\"[^\"]*\"\\([^\"]*\\)\".*/\\1/p" \
        | head -n1
}

seed_call() {
    # seed_call <attempt_label> — POSTs /api/seed-demo, echoes the response.
    curl -fsS --max-time 60 \
        -X POST \
        -H 'Content-Type: application/json' \
        -d '{}' \
        "${BASE_URL}/api/seed-demo" \
        || fail "POST /api/seed-demo ($1) returned non-2xx"
}

# First call — may return status="created" on a fresh stack or "existing" if
# a previous bootstrap/smoke already seeded this workspace.
first_out=$(seed_call "first")
workspace_id=$(extract_field "$first_out" "workspaceId")
first_status=$(extract_field "$first_out" "status")
[ -n "$workspace_id" ] || fail "first /api/seed-demo missing workspaceId:\n$first_out"
[ -n "$first_status" ] || fail "first /api/seed-demo missing status:\n$first_out"
pass "first  POST → workspaceId=${workspace_id} status=${first_status}"

# Second call — must be idempotent. Same workspaceId, status must be
# "existing", and must NOT return 500 (which would indicate the IntegrityError
# regression the code review flagged).
second_out=$(seed_call "second")
second_id=$(extract_field "$second_out" "workspaceId")
second_status=$(extract_field "$second_out" "status")
[ "$second_id" = "$workspace_id" ] \
    || fail "second /api/seed-demo returned a different workspaceId ('$second_id' vs '$workspace_id') — not idempotent"
[ "$second_status" = "existing" ] \
    || fail "second /api/seed-demo status should be 'existing', got '$second_status' — not idempotent"
pass "second POST → same workspaceId, status=existing (idempotent)"

# The seeded workspace must contain the full knowledge graph, not just raw
# SourceDocument rows. Probe GET /api/models?workspace_id=... to confirm.
models_out=$(curl -fsS --max-time 15 \
    "${BASE_URL}/api/models?workspace_id=${workspace_id}") \
    || fail "GET /api/models for seeded workspace failed"
printf "%s" "$models_out" | grep -q '"id"' \
    || fail "seeded workspace has zero knowledge models — the seed path is not eval-ready:\n$models_out"
pass "seeded workspace has knowledge models (eval-ready seed)"

# ── 4. QUERY ────────────────────────────────────────────────────
step "4/9 QUERY — source-backed answer"
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

# ── 5. GRAPH ───────────────────────────────────────────────────
step "5/9 GRAPH — workspace knowledge graph"
graph_out=$(curl -fsS --max-time 15 \
    "${BASE_URL}/api/graph?workspace_id=${workspace_id}") \
    || fail "GET /api/graph failed — is the api container running? Check: docker compose logs api"
printf "%s" "$graph_out" | grep -q '"nodes"' \
    || fail "graph response missing 'nodes' field. Response: $graph_out"
# The demo seed creates 20 components across 5 models. Count nodes by
# counting "model_id" occurrences inside the nodes array (avoids double-
# counting edge ids).
node_count=$(printf "%s" "$graph_out" | grep -o '"model_id"' | wc -l | tr -d ' ')
[ "$node_count" -ge 15 ] \
    || fail "workspace graph returned only ${node_count} nodes — expected 15+ from the 20 seeded components. Check: docker compose exec api python -c 'from app.evals.demo_seed import _SEEDS; print(len(_SEEDS))'"
# Verify provenance: every node should have source_count >= 1.
zero_source_nodes=$(printf "%s" "$graph_out" | grep -o '"source_count"[[:space:]]*:[[:space:]]*0' | wc -l | tr -d ' ')
[ "$zero_source_nodes" -eq 0 ] \
    || fail "${zero_source_nodes} graph node(s) have source_count=0 — demo seed should attach sources to every component. Check ComponentSource links in demo_seed.py."
# Verify graph is not all-nulls: at least one node should have a non-empty name.
printf "%s" "$graph_out" | grep -q '"name"[[:space:]]*:[[:space:]]*"[^"]' \
    || fail "graph nodes have empty names — the graph is structurally valid but useless for display"
pass "workspace graph has ${node_count} nodes, all with provenance"

# ── 6. MODELS ──────────────────────────────────────────────────
step "6/9 MODELS — knowledge models"
models_list=$(curl -fsS --max-time 15 \
    "${BASE_URL}/api/models?workspace_id=${workspace_id}") \
    || fail "GET /api/models failed — check that the workspace was seeded correctly"
printf "%s" "$models_list" | grep -q '"name"' \
    || fail "models list is empty or malformed. Response: $models_list"
# The demo seed creates 5 models: Decisions, GitHub Insights, Pricing,
# Roadmap, Zoom Insights. Count them.
model_count=$(printf "%s" "$models_list" | grep -o '"name"' | wc -l | tr -d ' ')
[ "$model_count" -ge 4 ] \
    || fail "expected 4+ knowledge models from demo seed, got ${model_count}. Check _SEEDS in demo_seed.py for model_name entries."
# Extract first model id for downstream checks.
first_model_id=$(printf "%s" "$models_list" \
    | sed -n 's/.*"id"[^"]*"\([^"]*\)".*/\1/p' | head -n1)
[ -n "$first_model_id" ] || fail "could not extract a model id from models list"
pass "models list returned ${model_count} models (first: ${first_model_id})"

# Model-scoped graph must work and return at least one component.
model_graph=$(curl -fsS --max-time 15 \
    "${BASE_URL}/api/graph/models/${first_model_id}") \
    || fail "GET /api/graph/models/${first_model_id} failed — model graph endpoint may be broken"
printf "%s" "$model_graph" | grep -q '"nodes"' \
    || fail "model graph response missing 'nodes' field. Response: $model_graph"
model_node_count=$(printf "%s" "$model_graph" | grep -o '"model_id"' | wc -l | tr -d ' ')
[ "$model_node_count" -ge 1 ] \
    || fail "model graph returned 0 nodes — the model has no components in the graph"
pass "model graph for ${first_model_id} returned ${model_node_count} nodes"

# ── 7. BRIEF ──────────────────────────────────────────────────
step "7/9 BRIEF — founder brief"
brief_out=$(curl -fsS --max-time 30 \
    "${BASE_URL}/api/founder-brief?workspace_id=${workspace_id}") \
    || fail "GET /api/founder-brief failed — this endpoint aggregates across models; check logs for internal errors: docker compose logs api"
# The founder brief must contain structured content, not just an id.
printf "%s" "$brief_out" | grep -q '"workspace_id"' \
    || fail "founder brief missing workspace_id. Response: $brief_out"
# Brief should contain at least one section with content from the seeded data.
# Check for known fields that should be populated.
printf "%s" "$brief_out" | grep -q '"workspace_name"' \
    || fail "founder brief missing workspace_name — the brief is structurally empty"
pass "founder brief returned with structured content"

# ── 8. DECISIONS ──────────────────────────────────────────────
step "8/9 DECISIONS — decision register"
decisions_out=$(curl -fsS --max-time 15 \
    "${BASE_URL}/api/decisions?workspace_id=${workspace_id}") \
    || fail "GET /api/decisions failed — check that the 'Decisions' model exists in the seeded workspace"
# The demo seed creates 3 components in the "Decisions" model.
printf "%s" "$decisions_out" | grep -q '"name"' \
    || fail "decisions list is empty or malformed. Response: $decisions_out"
# Decisions should have meaningful content — check for value field.
printf "%s" "$decisions_out" | grep -q '"value"' \
    || fail "decisions returned but missing 'value' field — entries are shaped incorrectly"
decision_count=$(printf "%s" "$decisions_out" | grep -o '"name"' | wc -l | tr -d ' ')
[ "$decision_count" -ge 1 ] \
    || fail "expected at least 1 decision from the 3 seeded in the Decisions model, got 0"
pass "decisions list returned ${decision_count} entries with names and values"

# ── 9. SOURCES ─────────────────────────────────────────────────
step "9/9 SOURCES — source documents with provenance"
sources_out=$(curl -fsS --max-time 15 \
    "${BASE_URL}/api/source-documents?workspace_id=${workspace_id}&limit=10") \
    || fail "GET /api/source-documents failed — check that SourceDocument rows were created by the seed"
printf "%s" "$sources_out" | grep -q '"items"' \
    || fail "source documents response missing 'items' field. Response: $sources_out"
# Verify there are actual documents, not just an empty list.
source_count=$(printf "%s" "$sources_out" | grep -o '"connector_type"' | wc -l | tr -d ' ')
[ "$source_count" -ge 3 ] \
    || fail "expected 3+ source documents, got ${source_count}. The demo seed creates ~25 source documents across multiple connector types."
# Verify documents have been processed (processed_at is set by the seed).
printf "%s" "$sources_out" | grep -q '"processed_at"' \
    || fail "source documents missing 'processed_at' — documents appear unprocessed"
# Verify content is present, not just metadata stubs.
printf "%s" "$sources_out" | grep -q '"content"' \
    || fail "source documents missing 'content' field — provenance without content is useless for attribution"
pass "source documents returned ${source_count} entries with content and provenance"

cat <<EOF

==> SMOKE PASSED.

    Boot:      postgres + redis + api running
    Health:    /health ok, /health/ready ok (db + redis)
    Seed:      workspace ${workspace_id} via POST /api/seed-demo
               first=${first_status}, second=existing (idempotent)
               knowledge models present
    Query:     "${SMOKE_QUESTION}" → source-backed answer
    Graph:     ${node_count} nodes, all with provenance (no empty names)
    Models:    ${model_count} models, model graph → ${model_node_count} nodes
    Brief:     structured founder brief returned
    Decisions: ${decision_count} decision(s) with names and values
    Sources:   ${source_count} source documents with content + provenance

    Context Engine is up, healthy, seeded, and answering queries
    across the main OSS v1 workflows.

EOF
