#!/usr/bin/env bash
#
# scripts/smoke.sh — backend-only self-hosted smoke verification.
#
# Used by `ctxe verify` as the backend half of the release gate.
#
# Proves these things against a running Context Engine stack:
#   1. BOOT       — docker compose reports api+postgres+redis+worker running
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
#  10. IMPORTS    — POST /api/imports round-trips a real document through
#                   the zero-auth ingest rail used by `ctxe ingest`, then
#                   confirms the LOCAL connector is visible
#
# Exit code 0 on success, non-zero (with a descriptive failure) otherwise.
# This script intentionally focuses on live backend founder workflows; use
# `ctxe verify` for the full release gate including tests and frontend build.
#
# Usage:
#   bash scripts/smoke.sh
#
# Optional env:
#   BASE_URL               default http://localhost:8000
#   SMOKE_QUESTION         default "What is the Starter Plan?"
#   SMOKE_EXPECT           default "$29"  (substring that must appear in answer)
#   SMOKE_SKIP_WORKER      set to 1 to allow smoke to pass without a running
#                          Celery worker (minimal deployments only)
#   SMOKE_SKIP_DIAGNOSTICS set to 1 to silence the diagnostic snapshot that
#                          is emitted on failure (useful in tests/CI)

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

# ── Diagnostic trap ─────────────────────────────────────────────
#
# On any non-zero exit, dump the state a user would otherwise have to
# collect by hand: container status, tail of api/worker/postgres logs,
# and the hint for a deeper dive. Every smoke failure should be
# immediately diagnosable from the terminal output with no follow-up
# commands required.
#
# Set SMOKE_SKIP_DIAGNOSTICS=1 to silence this (useful in CI or tests).
emit_failure_diagnostics() {
    local exit_code=$?
    if [ "$exit_code" -eq 0 ]; then
        return 0
    fi
    if [ "${SMOKE_SKIP_DIAGNOSTICS:-0}" = "1" ]; then
        return 0
    fi
    # Avoid calling docker if it is not installed — fail() may have been
    # triggered by `require docker` itself.
    command -v docker >/dev/null 2>&1 || return 0
    docker compose version >/dev/null 2>&1 || return 0

    {
        printf "\n==> DIAGNOSTIC SNAPSHOT (smoke failed with exit %d)\n" "$exit_code"
        printf "\n--- docker compose ps ---\n"
        docker compose ps 2>&1 | head -40 || true
        printf "\n--- docker compose logs api (last 40 lines) ---\n"
        docker compose logs --tail 40 api 2>&1 || true
        printf "\n--- docker compose logs worker (last 20 lines) ---\n"
        docker compose logs --tail 20 worker 2>&1 || true
        printf "\n--- docker compose logs postgres (last 15 lines) ---\n"
        docker compose logs --tail 15 postgres 2>&1 || true
        printf "\n--- docker compose logs redis (last 10 lines) ---\n"
        docker compose logs --tail 10 redis 2>&1 || true
        printf "\nFor deeper investigation:\n"
        printf "  docker compose logs --tail 200 api\n"
        printf "  docker compose exec postgres psql -U postgres -d context_engine\n"
        printf "  docker compose exec api alembic current\n"
    } >&2
}
trap emit_failure_diagnostics EXIT

require curl
require docker

# ── 1. BOOT ─────────────────────────────────────────────────────
step "1/10 BOOT — docker compose containers"
docker compose version >/dev/null 2>&1 || fail "docker compose v2 not available"
running=$(docker compose ps --services --filter "status=running" 2>/dev/null || true)
# The worker is checked separately below because some minimal self-host
# deployments intentionally skip it — fail loudly but with a dedicated
# message so the cause is obvious.
for svc in postgres redis api; do
    printf "%s\n" "$running" | grep -qx "$svc" \
        || fail "service '$svc' is not running — expected docker compose ps to report it as 'running'. Check: docker compose ps (the DIAGNOSTIC SNAPSHOT below has the output)"
done
if [ "${SMOKE_SKIP_WORKER:-0}" = "1" ]; then
    pass "postgres, redis, api are running (worker check skipped via SMOKE_SKIP_WORKER=1)"
else
    printf "%s\n" "$running" | grep -qx worker \
        || fail "service 'worker' is not running — the Celery worker is part of the default docker compose stack and is required for async ingestion. If you intentionally removed it, set SMOKE_SKIP_WORKER=1 to allow this check to pass. Otherwise check: docker compose logs worker"
    pass "postgres, redis, api, worker are running"
fi

# ── 2. HEALTH ───────────────────────────────────────────────────
step "2/10 HEALTH — /health and /health/ready"
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
step "3/10 SEED — POST /api/seed-demo (idempotent)"

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
step "4/10 QUERY — source-backed answer"
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
step "5/10 GRAPH — workspace knowledge graph"
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
step "6/10 MODELS — knowledge models"
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
step "7/10 BRIEF — founder brief"
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
step "8/10 DECISIONS — decision register"
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
step "9/10 SOURCES — source documents with provenance"
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

# ── 10. IMPORTS ────────────────────────────────────────────────
step "10/10 IMPORTS — POST /api/imports (the ctxe ingest contract)"

# The real zero-auth import rail is POST /api/imports. `ctxe ingest` at
# app/cli/main.py:362 hits this endpoint with a {workspace_id, documents[]}
# payload and calls validate_import_response() on the reply. A rubber-stamp
# GET on /api/imports/connectors would not catch regressions in the
# ImportRequest schema, the ImportService pipeline, or the CLI contract,
# so send a real document and verify the full shape.
import_payload=$(cat <<JSON
{
  "workspace_id": "${workspace_id}",
  "documents": [
    {
      "external_id": "smoke-test-doc-1",
      "content": "Smoke test document from scripts/smoke.sh — exercises the POST /api/imports contract used by 'ctxe ingest'. Safe to keep across runs; idempotent by external_id.",
      "author": "smoke.sh",
      "source_url": "https://context-engine.local/smoke-test-doc-1"
    }
  ]
}
JSON
)

import_out=$(curl -fsS --max-time 60 \
    -X POST \
    -H 'Content-Type: application/json' \
    -d "$import_payload" \
    "${BASE_URL}/api/imports") \
    || fail "POST /api/imports failed — the import rail used by 'ctxe ingest' is broken. Check: docker compose logs api"

# Validate the response fields that validate_import_response() in
# app/cli/main.py:557 requires. A missing field means `ctxe ingest` will
# fail with a cryptic error even though this endpoint returned 200.
for key in workspace_id connector_id total_documents \
           created_documents updated_documents unchanged_documents \
           processed_documents failed_documents documents; do
    printf "%s" "$import_out" | grep -q "\"${key}\"" \
        || fail "POST /api/imports response missing required field '${key}' (required by app/cli/main.py validate_import_response). Response: $import_out"
done

# failed_documents MUST be zero. A failed document on the default self-host
# stack means the rule-based ingestion pipeline crashed — release-blocking.
import_failed=$(printf "%s" "$import_out" \
    | sed -n 's/.*"failed_documents"[^0-9]*\([0-9][0-9]*\).*/\1/p' | head -n1)
[ -n "$import_failed" ] \
    || fail "could not parse failed_documents from import response. Response: $import_out"
[ "$import_failed" = "0" ] \
    || fail "POST /api/imports reported failed_documents=${import_failed} — ingestion pipeline is broken. Check: docker compose logs api for extraction/embedding errors"

# total_documents must equal 1 (we sent exactly one). Proves the router
# parsed the payload and the service dispatched it.
import_total=$(printf "%s" "$import_out" \
    | sed -n 's/.*"total_documents"[^0-9]*\([0-9][0-9]*\).*/\1/p' | head -n1)
[ "$import_total" = "1" ] \
    || fail "POST /api/imports reported total_documents=${import_total} — expected 1. Response: $import_out"

# The document must settle. created + updated + unchanged >= 1 handles
# both first-run (created=1) and repeat-run (updated or unchanged = 1).
import_created=$(printf "%s" "$import_out" \
    | sed -n 's/.*"created_documents"[^0-9]*\([0-9][0-9]*\).*/\1/p' | head -n1)
import_updated=$(printf "%s" "$import_out" \
    | sed -n 's/.*"updated_documents"[^0-9]*\([0-9][0-9]*\).*/\1/p' | head -n1)
import_unchanged=$(printf "%s" "$import_out" \
    | sed -n 's/.*"unchanged_documents"[^0-9]*\([0-9][0-9]*\).*/\1/p' | head -n1)
import_settled=$(( ${import_created:-0} + ${import_updated:-0} + ${import_unchanged:-0} ))
[ "$import_settled" -ge 1 ] \
    || fail "POST /api/imports settled 0 documents (created=${import_created:-?}, updated=${import_updated:-?}, unchanged=${import_unchanged:-?}) — import was accepted but never persisted."
pass "POST /api/imports → total=${import_total} created=${import_created:-0} updated=${import_updated:-0} unchanged=${import_unchanged:-0} failed=0"

# Round-trip the imported document through GET /api/source-documents.
# This proves the import was actually persisted and is queryable — not just
# that the POST returned a shaped response. A regression where ImportService
# returns ok but never commits to the DB would be caught here.
roundtrip_out=$(curl -fsS --max-time 15 \
    "${BASE_URL}/api/source-documents?workspace_id=${workspace_id}&connector_type=local&limit=50") \
    || fail "GET /api/source-documents?connector_type=local failed during import round-trip check — the source documents listing endpoint is broken. Check: docker compose logs api"
printf "%s" "$roundtrip_out" | grep -q '"items"' \
    || fail "source-documents response missing 'items' field during round-trip check. Response: $roundtrip_out"
printf "%s" "$roundtrip_out" | grep -q '"smoke-test-doc-1"' \
    || fail "POST /api/imports returned success, but the imported document (external_id=smoke-test-doc-1) is NOT visible in GET /api/source-documents?connector_type=local. The endpoint returned 200 but the ImportService did not actually persist the row. Check ImportService.import_documents commit logic and LOCAL connector filtering."
pass "imported document visible in /api/source-documents (import round-trip OK)"

# After the import, the LOCAL connector must be visible in the connector
# list — this is the endpoint the frontend uses to show "what have I
# imported?" state. If the connector was not persisted, this returns [].
connectors_out=$(curl -fsS --max-time 15 \
    "${BASE_URL}/api/imports/connectors?workspace_id=${workspace_id}") \
    || fail "GET /api/imports/connectors failed — the import surface may not be registered in the router. Check app/api/router.py includes imports."
printf "%s" "$connectors_out" | grep -Eq '^\[' \
    || fail "imports/connectors did not return a JSON array. Response: $connectors_out"
import_connector_count=$(printf "%s" "$connectors_out" | grep -o '"connector_type"' | wc -l | tr -d ' ')
[ "$import_connector_count" -ge 1 ] \
    || fail "expected at least 1 import connector after POST /api/imports succeeded, got 0 — connector was not persisted. Check ImportService._get_or_create_local_connector."
pass "GET /api/imports/connectors → ${import_connector_count} connector(s) visible"

cat <<EOF

==> SMOKE PASSED.

    Boot:      postgres + redis + api + worker running
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
    Imports:   POST /api/imports round-tripped (failed=0, settled=${import_settled}),
               ${import_connector_count} connector(s) visible at /api/imports/connectors

    Context Engine is up, healthy, seeded, and answering queries
    across the main OSS v1 workflows — including the real zero-auth
    import rail used by 'ctxe ingest'.

EOF
