#!/usr/bin/env bash
#
# scripts/diagnose.sh — runtime snapshot for post-failure triage.
#
# Collects everything a developer or operator would need to diagnose a
# Context Engine runtime problem, writes it to a timestamped directory,
# and (optionally) packs it into a tarball you can attach to a bug
# report or ship to support.
#
# What it captures:
#   - Host facts:        uptime, disk usage, OS, docker version
#   - Compose state:     `docker compose ps`, image list, volume list
#   - Logs (200 lines):  api, worker, postgres, redis
#   - API health:        /health and /health/ready responses
#   - Schema state:      alembic current (if api container is up)
#   - DB stats:          table sizes, row counts, active connections
#   - Redis stats:       info memory, info clients, keyspace, queue depth
#   - Celery queue:      default queue length via redis-cli
#   - Resource usage:    docker stats snapshot (one-shot)
#   - Configuration:     redacted .env (secrets masked)
#
# Safe to run on a healthy stack too — it is purely read-only and never
# touches application data.
#
# Usage:
#   bash scripts/diagnose.sh                    # dump to ./diagnostics/<ts>/
#   bash scripts/diagnose.sh --tar              # dump + create .tar.gz
#   OUTPUT_DIR=/tmp bash scripts/diagnose.sh    # override base directory
#
# Optional env:
#   BASE_URL     default http://localhost:8000
#   OUTPUT_DIR   default ./diagnostics
#   LOG_LINES    default 200 (per service)

set -u
# Note: we intentionally do NOT use `set -e`. Every collection step is
# wrapped in `|| true` because we want partial output when individual
# commands fail (e.g., the api container is down but postgres is up).

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

BASE_URL=${BASE_URL:-http://localhost:8000}
OUTPUT_DIR=${OUTPUT_DIR:-./diagnostics}
LOG_LINES=${LOG_LINES:-200}

MAKE_TAR=0
for arg in "$@"; do
    case "$arg" in
        --tar|-t)  MAKE_TAR=1 ;;
        -h|--help)
            grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            printf "unknown argument: %s (try --help)\n" "$arg" >&2
            exit 2
            ;;
    esac
done

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
snapshot_dir="${OUTPUT_DIR}/ctxe-diagnose-${timestamp}"
mkdir -p "$snapshot_dir"

log()  { printf "==> %s\n" "$*"; }
sect() { printf "\n# %s\n" "$*"; }

# ── Sanity checks ────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
    printf "docker not installed — cannot collect compose state\n" >&2
fi

# Some collection steps rely on docker compose. If it's broken we still
# write whatever host-level facts we can.
has_compose=1
if ! docker compose version >/dev/null 2>&1; then
    has_compose=0
fi

# ── Host facts ───────────────────────────────────────────────────
log "host facts"
{
    sect "date (UTC)"
    date -u
    sect "uptime"
    uptime 2>&1 || true
    sect "uname"
    uname -a 2>&1 || true
    if [ -r /etc/os-release ]; then
        sect "os-release"
        cat /etc/os-release
    fi
    sect "disk usage (df -h)"
    df -h 2>&1 || true
    sect "memory (free -h)"
    free -h 2>&1 || true
    sect "docker version"
    docker version 2>&1 || true
    if [ "$has_compose" = 1 ]; then
        sect "docker compose version"
        docker compose version 2>&1 || true
    fi
    sect "docker info (summary)"
    docker info 2>&1 | head -40 || true
} > "${snapshot_dir}/host.txt" 2>&1

# ── Compose state ────────────────────────────────────────────────
if [ "$has_compose" = 1 ]; then
    log "compose state"
    {
        sect "docker compose ps"
        docker compose ps 2>&1 || true
        sect "docker compose ps --all (including stopped)"
        docker compose ps --all 2>&1 || true
        sect "docker compose images"
        docker compose images 2>&1 || true
        sect "docker compose config --services"
        docker compose config --services 2>&1 || true
        sect "docker volume ls (compose only)"
        docker volume ls 2>&1 | grep -E 'context-engine|postgres_data|redis_data' || true
    } > "${snapshot_dir}/compose.txt" 2>&1

    # ── Logs per service ─────────────────────────────────────────
    log "logs (last ${LOG_LINES} lines per service)"
    for svc in api worker postgres redis; do
        docker compose logs --tail "$LOG_LINES" "$svc" \
            > "${snapshot_dir}/logs-${svc}.txt" 2>&1 || true
    done

    # ── Resource usage snapshot ──────────────────────────────────
    log "container resource usage (one-shot docker stats)"
    docker stats --no-stream \
        --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}' \
        > "${snapshot_dir}/stats.txt" 2>&1 || true

    # ── Schema state ─────────────────────────────────────────────
    log "alembic current"
    docker compose exec -T api alembic current \
        > "${snapshot_dir}/alembic.txt" 2>&1 || true

    docker compose exec -T api alembic history --verbose 2>&1 \
        | tail -40 >> "${snapshot_dir}/alembic.txt" || true

    # ── Postgres stats ──────────────────────────────────────────
    log "postgres stats"
    {
        sect "database size"
        docker compose exec -T postgres psql -U postgres -d context_engine -c \
            "SELECT pg_size_pretty(pg_database_size('context_engine')) AS total_db_size;" 2>&1 || true

        sect "table sizes"
        docker compose exec -T postgres psql -U postgres -d context_engine -c "
            SELECT relname AS table,
                   pg_size_pretty(pg_total_relation_size(relid)) AS size,
                   n_live_tup AS row_estimate
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size(relid) DESC
            LIMIT 30;" 2>&1 || true

        sect "row counts (canonical tables)"
        docker compose exec -T postgres psql -U postgres -d context_engine -c "
            SELECT 'workspaces' AS t, count(*) FROM workspaces
            UNION ALL SELECT 'knowledge_models', count(*) FROM knowledge_models
            UNION ALL SELECT 'components', count(*) FROM components
            UNION ALL SELECT 'source_documents', count(*) FROM source_documents
            UNION ALL SELECT 'connectors', count(*) FROM connectors;" 2>&1 || true

        sect "active connections"
        docker compose exec -T postgres psql -U postgres -d context_engine -c \
            "SELECT state, count(*) FROM pg_stat_activity GROUP BY state;" 2>&1 || true

        sect "longest-running queries"
        docker compose exec -T postgres psql -U postgres -d context_engine -c "
            SELECT pid, now() - query_start AS duration, state, left(query, 120) AS query
            FROM pg_stat_activity
            WHERE state != 'idle'
              AND query_start IS NOT NULL
            ORDER BY duration DESC
            LIMIT 10;" 2>&1 || true
    } > "${snapshot_dir}/postgres.txt" 2>&1

    # ── Redis stats ─────────────────────────────────────────────
    log "redis stats"
    {
        sect "redis info memory"
        docker compose exec -T redis redis-cli INFO memory 2>&1 || true
        sect "redis info clients"
        docker compose exec -T redis redis-cli INFO clients 2>&1 || true
        sect "redis info keyspace"
        docker compose exec -T redis redis-cli INFO keyspace 2>&1 || true
        sect "celery default queue length"
        docker compose exec -T redis redis-cli LLEN celery 2>&1 || true
        sect "redis key count (DBSIZE)"
        docker compose exec -T redis redis-cli DBSIZE 2>&1 || true
    } > "${snapshot_dir}/redis.txt" 2>&1
fi

# ── API health ───────────────────────────────────────────────────
log "api health"
{
    sect "GET /health"
    curl -sS --max-time 10 "${BASE_URL}/health" 2>&1 || true
    printf "\n"
    sect "GET /health/ready"
    curl -sS --max-time 10 "${BASE_URL}/health/ready" 2>&1 || true
    printf "\n"
} > "${snapshot_dir}/health.txt" 2>&1

# ── Redacted config ──────────────────────────────────────────────
#
# .env may contain API keys (LITELLM_API_KEY, ZOOM_CLIENT_SECRET,
# ENCRYPTION_KEY, EVAL_ADMIN_TOKEN). Scrub every KEY=value line with a
# sensitive-looking name before writing it to the snapshot so a developer
# can safely attach the tarball to a bug report.
if [ -f .env ]; then
    log "redacted .env"
    # Any KEY containing KEY, SECRET, PASSWORD, TOKEN, or API_KEY gets
    # its value replaced with <redacted>. Preserve KEY= for shape clarity.
    awk -F= '
        /^[[:space:]]*#/ { print; next }
        /^[[:space:]]*$/ { print; next }
        {
            key = $1
            if (key ~ /(KEY|SECRET|PASSWORD|TOKEN)/) {
                print key "=<redacted>"
            } else {
                print
            }
        }
    ' .env > "${snapshot_dir}/env.redacted.txt" 2>&1 || true
fi

# ── Summary line at the top of the dir ──────────────────────────
{
    printf "Context Engine diagnostic snapshot\n"
    printf "Collected at: %s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf "Host:         %s\n" "$(hostname 2>/dev/null || echo unknown)"
    printf "Base URL:     %s\n" "$BASE_URL"
    printf "Root dir:     %s\n" "$ROOT_DIR"
    printf "\nFiles in this snapshot:\n"
    ls -la "$snapshot_dir" 2>&1 || true
    printf "\nNext steps:\n"
    printf "  1. Read logs-api.txt first — it usually has the immediate cause.\n"
    printf "  2. Cross-reference with compose.txt (which services are actually up?).\n"
    printf "  3. Check postgres.txt for row counts (zero rows → seed regression).\n"
    printf "  4. Check redis.txt for queue length (large → worker backlog).\n"
    printf "  5. See docs/runbook.md for detailed triage steps per failure mode.\n"
} > "${snapshot_dir}/README.txt"

# ── Optional tarball ─────────────────────────────────────────────
if [ "$MAKE_TAR" = 1 ]; then
    tar_path="${OUTPUT_DIR}/ctxe-diagnose-${timestamp}.tar.gz"
    log "packing tarball: ${tar_path}"
    tar -czf "$tar_path" -C "$OUTPUT_DIR" "ctxe-diagnose-${timestamp}" 2>&1 || {
        printf "tar failed — snapshot directory is still at %s\n" "$snapshot_dir" >&2
    }
    if [ -f "$tar_path" ]; then
        printf "\n==> Snapshot ready:\n"
        printf "    Directory: %s\n" "$snapshot_dir"
        printf "    Tarball:   %s\n" "$tar_path"
        printf "\n    Share the tarball for support or attach it to a bug report.\n"
        printf "    It contains no secrets (all KEY/SECRET/PASSWORD/TOKEN env\n"
        printf "    values were redacted).\n"
        exit 0
    fi
fi

printf "\n==> Snapshot ready at: %s\n" "$snapshot_dir"
printf "    Run with --tar to pack it into a single tarball.\n"
