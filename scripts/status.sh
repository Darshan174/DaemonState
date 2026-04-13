#!/usr/bin/env bash
#
# scripts/status.sh — operator health summary for a running Context
# Engine stack. Read-only. Answers four questions explicitly:
#
#   1. Is the Celery worker healthy?
#   2. Is the queue stuck?
#   3. Is the DB schema current?
#   4. Is the demo / import data usable?
#
# Each question gets a one-line PASS / WARN / FAIL verdict. Exit 0
# if every question passes (or warns), 1 if anything fails. Wire it
# into a monitoring cron or run it by hand after any admin action.
#
# This is NOT a replacement for scripts/smoke.sh — smoke runs real
# workloads end-to-end; status is a fast snapshot check. Use smoke
# before/after deploys and releases; use status for continuous
# health visibility.
#
# ──────────────────────────────────────────────────────────────────────
# Usage
# ──────────────────────────────────────────────────────────────────────
#   bash scripts/status.sh
#   bash scripts/status.sh --workspace <uuid>    # probe a specific workspace
#   bash scripts/status.sh --quiet               # exit code only, no output
#
# Optional env:
#   BASE_URL        default http://localhost:8000
#   STATUS_WORKSPACE_ID
#                   default: first workspace returned by /api/workspaces
#   QUEUE_SOFT_LIMIT
#                   default 10  (WARN above this)
#   QUEUE_HARD_LIMIT
#                   default 50  (FAIL above this)
#
# ──────────────────────────────────────────────────────────────────────
# Exit codes
# ──────────────────────────────────────────────────────────────────────
#   0  all checks passed or warned only
#   1  at least one check failed
#   2  bad arguments / stack unreachable

set -u

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

BASE_URL=${BASE_URL:-http://localhost:8000}
STATUS_WORKSPACE_ID=${STATUS_WORKSPACE_ID:-}
QUEUE_SOFT_LIMIT=${QUEUE_SOFT_LIMIT:-10}
QUEUE_HARD_LIMIT=${QUEUE_HARD_LIMIT:-50}
QUIET=0

while [ $# -gt 0 ]; do
    case "$1" in
        --workspace|-w)
            STATUS_WORKSPACE_ID=$2; shift 2 ;;
        --quiet|-q)
            QUIET=1; shift ;;
        -h|--help)
            grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            printf "status.sh: unknown argument '%s' (try --help)\n" "$1" >&2
            exit 2
            ;;
    esac
done

FAIL_COUNT=0
WARN_COUNT=0
PASS_COUNT=0

out() { [ "$QUIET" = 1 ] || printf "%s\n" "$*"; }
hdr() { out ""; out "── $* ──"; }

pass() {
    PASS_COUNT=$(( PASS_COUNT + 1 ))
    out "  [PASS] $*"
}
warn() {
    WARN_COUNT=$(( WARN_COUNT + 1 ))
    out "  [WARN] $*"
}
fail() {
    FAIL_COUNT=$(( FAIL_COUNT + 1 ))
    out "  [FAIL] $*"
}

# ── Preflight ────────────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || { out "docker not installed"; exit 2; }
command -v curl >/dev/null 2>&1 || { out "curl not installed"; exit 2; }
docker compose version >/dev/null 2>&1 || { out "docker compose v2 not available"; exit 2; }

out "Context Engine status — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
out "Base URL: ${BASE_URL}"

# ── Question 1: is the Celery worker healthy? ───────────────────
hdr "1. Worker health"

# 1a. The container must exist and report as running.
running_services=$(docker compose ps --services --filter "status=running" 2>/dev/null || true)
if ! printf "%s\n" "$running_services" | grep -qx worker; then
    fail "worker container is not in 'running' state (check: docker compose ps worker)"
else
    pass "worker container is running"

    # 1b. The worker must respond to a celery inspect ping. This
    # proves the Celery process is alive AND registered with the
    # broker AND responsive to control commands.
    ping_out=$(docker compose exec -T worker \
        celery -A app.tasks.celery_app inspect ping --timeout 5 2>&1 || true)
    if printf "%s" "$ping_out" | grep -q "pong"; then
        pass "celery inspect ping returned pong"
    else
        ping_short=$(printf "%s" "$ping_out" | tr -d '\n' | cut -c1-120)
        fail "celery inspect ping did not return pong: ${ping_short}"
    fi

    # 1c. The worker must have actually claimed at least one queue
    # on the broker. Otherwise it is "running" but not consuming.
    active_out=$(docker compose exec -T worker \
        celery -A app.tasks.celery_app inspect active_queues --timeout 5 2>&1 || true)
    if printf "%s" "$active_out" | grep -q '"name"'; then
        pass "worker has claimed at least one queue"
    else
        warn "could not confirm worker has an active queue (this is sometimes a transient check failure)"
    fi
fi

# ── Question 2: is the queue stuck? ─────────────────────────────
hdr "2. Queue depth"

queue_depth=$(docker compose exec -T redis redis-cli LLEN celery 2>/dev/null | tr -d '\r\n ')
if [ -z "$queue_depth" ] || ! printf "%s" "$queue_depth" | grep -qE '^[0-9]+$'; then
    fail "could not read queue depth from redis (LLEN celery returned: '${queue_depth:-<empty>}')"
elif [ "$queue_depth" -gt "$QUEUE_HARD_LIMIT" ]; then
    fail "celery default queue depth = ${queue_depth} (hard limit: ${QUEUE_HARD_LIMIT}). Worker is stuck, crashed, or overloaded. See docs/runbook.md → Queue backlog."
elif [ "$queue_depth" -gt "$QUEUE_SOFT_LIMIT" ]; then
    warn "celery default queue depth = ${queue_depth} (soft limit: ${QUEUE_SOFT_LIMIT}). Not yet critical but trending worse."
else
    pass "celery default queue depth = ${queue_depth} (healthy)"
fi

# Also check if there are any scheduled/reserved tasks that might
# indicate a stuck task.
reserved_out=$(docker compose exec -T worker \
    celery -A app.tasks.celery_app inspect reserved --timeout 5 2>&1 || true)
reserved_count=$(printf "%s" "$reserved_out" | grep -o '"id"' | wc -l | tr -d ' ')
if [ "$reserved_count" -gt 0 ]; then
    if [ "$reserved_count" -gt 20 ]; then
        warn "${reserved_count} reserved task(s) on the worker — may indicate slow processing"
    else
        pass "${reserved_count} reserved task(s) (normal backpressure)"
    fi
else
    pass "no reserved tasks (worker is idle or keeping up)"
fi

# ── Question 3: is the DB schema current? ───────────────────────
hdr "3. Database schema"

current_rev=$(docker compose exec -T api alembic current 2>/dev/null \
    | awk '/^[a-f0-9]+/ {print $1; exit}' || true)
head_rev=$(docker compose exec -T api alembic heads 2>/dev/null \
    | awk '/^[a-f0-9]+/ {print $1; exit}' || true)

if [ -z "$current_rev" ] || [ -z "$head_rev" ]; then
    fail "could not read alembic current/heads (current='${current_rev:-?}' heads='${head_rev:-?}'). Check: docker compose exec api alembic current"
elif [ "$current_rev" != "$head_rev" ]; then
    fail "alembic current=${current_rev} does not match heads=${head_rev}. Run: docker compose exec api alembic upgrade head"
else
    pass "alembic current=${current_rev} matches heads (schema up to date)"
fi

# ── Question 4: is the demo / import data usable? ───────────────
hdr "4. Workspace data usability"

# Pick a workspace to probe. Either the explicit one, or the first
# one from /api/workspaces.
workspaces_out=$(curl -fsS --max-time 10 "${BASE_URL}/api/workspaces" 2>&1)
ws_rc=$?
if [ $ws_rc -ne 0 ]; then
    fail "GET /api/workspaces failed — API may be down or unreachable from ${BASE_URL}"
else
    workspace_count=$(printf "%s" "$workspaces_out" | grep -o '"id"' | wc -l | tr -d ' ')
    if [ "$workspace_count" -eq 0 ]; then
        warn "zero workspaces on this instance — run bash scripts/bootstrap.sh or POST /api/seed-demo to seed the demo"
    else
        pass "${workspace_count} workspace(s) registered"
    fi

    # Probe workspace. If the caller passed --workspace, use that;
    # otherwise pick the first id from the list.
    probe_ws="$STATUS_WORKSPACE_ID"
    if [ -z "$probe_ws" ]; then
        probe_ws=$(printf "%s" "$workspaces_out" \
            | sed -n 's/.*"id"[^"]*"\([^"]*\)".*/\1/p' | head -n1)
    fi

    if [ -z "$probe_ws" ]; then
        warn "no workspace available to probe graph usability"
    else
        # 4a. The workspace graph must return nodes with provenance.
        graph_out=$(curl -fsS --max-time 10 "${BASE_URL}/api/graph?workspace_id=${probe_ws}" 2>&1)
        g_rc=$?
        if [ $g_rc -ne 0 ]; then
            fail "GET /api/graph?workspace_id=${probe_ws} failed — knowledge graph API is broken"
        else
            node_count=$(printf "%s" "$graph_out" | grep -o '"model_id"' | wc -l | tr -d ' ')
            if [ "$node_count" -lt 1 ]; then
                warn "workspace ${probe_ws} has 0 graph nodes — is this a fresh workspace that has not been seeded yet?"
            else
                # Check that at least some nodes have names (not structurally empty)
                named_check=$(printf "%s" "$graph_out" | grep -q '"name"[[:space:]]*:[[:space:]]*"[^"]' && echo 1 || echo 0)
                if [ "$named_check" = "1" ]; then
                    pass "workspace ${probe_ws} graph: ${node_count} node(s) with names"
                else
                    fail "workspace ${probe_ws} graph has ${node_count} nodes but none have non-empty names — graph is structurally valid but useless"
                fi

                # Check provenance — every node should have source_count >= 1
                zero_source=$(printf "%s" "$graph_out" \
                    | grep -o '"source_count"[[:space:]]*:[[:space:]]*0' | wc -l | tr -d ' ')
                if [ "$zero_source" -eq 0 ]; then
                    pass "every node in the probed graph has at least one source (provenance intact)"
                else
                    warn "${zero_source} node(s) in the probed graph have source_count=0 — provenance incomplete"
                fi
            fi
        fi

        # 4b. /api/models scoped to this workspace must return at
        # least one model (if any components exist).
        models_out=$(curl -fsS --max-time 10 "${BASE_URL}/api/models?workspace_id=${probe_ws}" 2>&1)
        m_rc=$?
        if [ $m_rc -ne 0 ]; then
            warn "GET /api/models?workspace_id=${probe_ws} failed — models endpoint may be broken"
        else
            model_count=$(printf "%s" "$models_out" | grep -o '"id"' | wc -l | tr -d ' ')
            if [ "$model_count" -ge 1 ]; then
                pass "workspace has ${model_count} knowledge model(s)"
            fi
        fi
    fi
fi

# ── Summary ──────────────────────────────────────────────────────
out ""
out "── Summary ──"
out "  pass:  ${PASS_COUNT}"
out "  warn:  ${WARN_COUNT}"
out "  fail:  ${FAIL_COUNT}"
out ""
if [ "$FAIL_COUNT" -gt 0 ]; then
    out "Status: FAIL (${FAIL_COUNT} check(s) failed)"
    out "Run 'bash scripts/diagnose.sh --tar' to collect a snapshot for triage."
    out "See docs/runbook.md → 'What broke? — triage' for the playbook."
    exit 1
fi
if [ "$WARN_COUNT" -gt 0 ]; then
    out "Status: PASS (with ${WARN_COUNT} warning(s))"
    exit 0
fi
out "Status: PASS (all ${PASS_COUNT} checks green)"
exit 0
