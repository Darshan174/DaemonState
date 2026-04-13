#!/usr/bin/env bash
#
# scripts/restore.sh — restore a Context Engine backup produced by
# scripts/backup.sh.
#
# Safely restores the `context_engine` database from a pg_dump custom
# format file. Stops the API and worker first so nothing writes during
# the restore, runs pg_restore --clean --if-exists so the target is
# rebuilt from scratch, starts the stack back up, waits for health,
# and runs a sanity check against the API to prove the restored data
# is actually queryable.
#
# ──────────────────────────────────────────────────────────────────────
# DANGER
# ──────────────────────────────────────────────────────────────────────
# This is a destructive operation — pg_restore --clean drops every
# existing table and recreates it. Anything written since the backup
# will be permanently lost. The script requires --yes (or the CTXE_
# RESTORE_YES=1 env var) to actually run, so you cannot trigger a
# restore by accident. For extra safety, pass --safety-backup and
# the script will snapshot the CURRENT DB before doing anything —
# that way a restore of the wrong dump is itself reversible.
#
# ──────────────────────────────────────────────────────────────────────
# Usage
# ──────────────────────────────────────────────────────────────────────
#   bash scripts/restore.sh <dump-path> --yes
#   bash scripts/restore.sh <dump-path> --yes --safety-backup
#
# Examples:
#   bash scripts/restore.sh backups/context_engine-20260101T030000Z.dump --yes
#   CTXE_RESTORE_YES=1 bash scripts/restore.sh /backups/latest.dump --safety-backup
#
# Optional env:
#   BASE_URL         default http://localhost:8000
#   HEALTH_TIMEOUT_S default 60  (seconds to wait for /health/ready after restore)
#   CTXE_RESTORE_YES set to 1 to skip the --yes argument check (useful in cron)
#
# ──────────────────────────────────────────────────────────────────────
# Exit codes
# ──────────────────────────────────────────────────────────────────────
#   0  restore completed + post-restore sanity check passed
#   1  restore failed at some stage (see output for details)
#   2  bad arguments or safety check refused

set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

BASE_URL=${BASE_URL:-http://localhost:8000}
HEALTH_TIMEOUT_S=${HEALTH_TIMEOUT_S:-60}

DUMP_PATH=""
CONFIRMED=${CTXE_RESTORE_YES:-0}
SAFETY_BACKUP=0

while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y)
            CONFIRMED=1; shift ;;
        --safety-backup|-s)
            SAFETY_BACKUP=1; shift ;;
        -h|--help)
            grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        --*)
            printf "restore.sh: unknown argument '%s' (try --help)\n" "$1" >&2
            exit 2
            ;;
        *)
            if [ -z "$DUMP_PATH" ]; then
                DUMP_PATH=$1
                shift
            else
                printf "restore.sh: unexpected positional argument '%s'\n" "$1" >&2
                exit 2
            fi
            ;;
    esac
done

log()  { printf "\n==> %s\n" "$*"; }
ok()   { printf "    [OK]   %s\n" "$*"; }
info() { printf "    [info] %s\n" "$*"; }
warn() { printf "    [warn] %s\n" "$*" >&2; }
die()  { printf "    [FAIL] %s\n" "$*" >&2; exit 1; }

# ── Argument validation ─────────────────────────────────────────
if [ -z "$DUMP_PATH" ]; then
    printf "restore.sh: missing dump path. Usage: bash scripts/restore.sh <dump-path> --yes\n" >&2
    exit 2
fi
if [ ! -f "$DUMP_PATH" ]; then
    printf "restore.sh: dump file not found: %s\n" "$DUMP_PATH" >&2
    exit 2
fi

if [ "$CONFIRMED" != 1 ]; then
    cat >&2 <<EOF
restore.sh: refusing to run without explicit confirmation.

Restoring will DROP every existing table in the context_engine
database and replace it with the contents of:

    ${DUMP_PATH}

Any data written since that backup will be permanently lost.

To proceed, re-run with --yes:

    bash scripts/restore.sh ${DUMP_PATH} --yes

Or pre-create a safety snapshot of the CURRENT DB first:

    bash scripts/restore.sh ${DUMP_PATH} --yes --safety-backup

EOF
    exit 2
fi

log "Preflight"
command -v docker >/dev/null 2>&1 || die "docker not installed"
command -v curl >/dev/null 2>&1 || die "curl not installed"
docker compose version >/dev/null 2>&1 || die "docker compose v2 not available"

# Postgres must be up. The other services should be up too so we can
# stop/start them cleanly — but this is not strictly required.
pg_state=$(docker compose ps --services --filter "status=running" 2>/dev/null | grep -x postgres || true)
if [ -z "$pg_state" ]; then
    die "postgres container is not running. Start it with 'docker compose up -d postgres' first."
fi
ok "postgres container is running"

# Validate the dump before we start touching things.
dump_bytes=$(wc -c < "$DUMP_PATH" | tr -d ' ')
if [ "$dump_bytes" -lt 1024 ]; then
    die "dump file is suspiciously small (${dump_bytes} bytes) — refusing to restore"
fi
ok "dump file: $DUMP_PATH ($(du -h "$DUMP_PATH" | awk '{print $1}'))"

# Copy the dump into the postgres container and validate its TOC
# before we drop anything. If this fails, the dump is corrupt and
# we must not proceed.
container_dump="/tmp/ctxe-restore.$$.dump"
docker compose cp "$DUMP_PATH" "postgres:${container_dump}" >/dev/null \
    || die "failed to copy dump into postgres container"

if ! docker compose exec -T postgres pg_restore --list "$container_dump" \
        >/dev/null 2>/tmp/ctxe-restore-validate.$$; then
    err=$(cat /tmp/ctxe-restore-validate.$$ 2>/dev/null || true)
    docker compose exec -T postgres rm -f "$container_dump" >/dev/null 2>&1 || true
    rm -f /tmp/ctxe-restore-validate.$$
    die "dump TOC check failed: ${err:-<no stderr captured>}. Refusing to restore from a corrupt archive."
fi
rm -f /tmp/ctxe-restore-validate.$$
ok "dump TOC validated — archive is readable"

# ── Safety backup (optional) ────────────────────────────────────
if [ "$SAFETY_BACKUP" = 1 ]; then
    log "Safety backup — snapshotting current DB before restore"
    if ! bash "${ROOT_DIR}/scripts/backup.sh" --output "./backups/pre-restore" --retention 5 --quiet; then
        die "safety backup failed. Refusing to run destructive restore without it. Remove --safety-backup to override (NOT recommended)."
    fi
    ok "safety backup written to backups/pre-restore/"
fi

# ── Stop writers ────────────────────────────────────────────────
log "Stopping api + worker (so nothing writes during restore)"
docker compose stop api worker 2>&1 | sed 's/^/    /' || true
ok "api + worker stopped"

# ── Restore ─────────────────────────────────────────────────────
log "Restoring ${DUMP_PATH} into context_engine"
# --clean --if-exists rebuilds the schema from scratch.
# --no-owner ignores role differences between source and target hosts.
# --exit-on-error fails fast on the first error instead of logging
#   the noise and returning 0.
if ! docker compose exec -T postgres \
        pg_restore -U postgres -d context_engine \
        --clean --if-exists --no-owner --exit-on-error \
        "$container_dump" 2>/tmp/ctxe-restore-err.$$; then
    err=$(cat /tmp/ctxe-restore-err.$$ 2>/dev/null || true)
    docker compose exec -T postgres rm -f "$container_dump" >/dev/null 2>&1 || true
    rm -f /tmp/ctxe-restore-err.$$
    warn "pg_restore failed: ${err:-<no stderr captured>}"
    warn ""
    warn "The database may be in an inconsistent state. To recover:"
    warn "  1. If you passed --safety-backup, restore from backups/pre-restore/"
    warn "  2. Otherwise, restore from the nearest known-good backup"
    warn "  3. Once recovered, restart the stack with: docker compose up -d api worker"
    die "restore failed — see warnings above"
fi
rm -f /tmp/ctxe-restore-err.$$
docker compose exec -T postgres rm -f "$container_dump" >/dev/null 2>&1 || true
ok "pg_restore completed"

# ── Restart stack ───────────────────────────────────────────────
log "Starting api + worker"
docker compose up -d api worker 2>&1 | sed 's/^/    /' || true

# ── Wait for readiness ──────────────────────────────────────────
log "Waiting for /health/ready (up to ${HEALTH_TIMEOUT_S}s)"
deadline=$(( $(date +%s) + HEALTH_TIMEOUT_S ))
while true; do
    if curl -fsS --max-time 5 "${BASE_URL}/health/ready" >/dev/null 2>&1; then
        break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        warn "API did not become ready in ${HEALTH_TIMEOUT_S}s after restore."
        warn "The restore itself may have succeeded — check:"
        warn "  docker compose logs --tail 40 api"
        warn "  docker compose exec api alembic current"
        die "post-restore readiness check timed out"
    fi
    sleep 2
done
ok "/health/ready → ready"

# ── Post-restore sanity check ───────────────────────────────────
# Prove the restored data is actually usable, not just structurally
# valid. /api/models returning at least one model means the restore
# landed real workspace data, not an empty schema.
log "Post-restore sanity check"
models_out=$(curl -fsS --max-time 10 "${BASE_URL}/api/models" 2>&1) \
    || die "GET /api/models failed after restore. The DB is readable (/health/ready passed) but the models endpoint errored. Check: docker compose logs --tail 40 api"

# Count models by counting "id" fields.
model_count=$(printf "%s" "$models_out" | grep -o '"id"' | wc -l | tr -d ' ')
if [ "$model_count" -lt 1 ]; then
    warn "restored DB contains 0 knowledge models — either the backup was from an empty workspace, or something is wrong."
    warn "Re-seed the demo workspace with: curl -X POST ${BASE_URL}/api/seed-demo -H 'Content-Type: application/json' -d '{}'"
    die "post-restore sanity check failed: 0 models"
fi
ok "restored workspace contains ${model_count} knowledge model(s)"

# Verify schema state matches deployed code.
current_rev=$(docker compose exec -T api alembic current 2>/dev/null \
    | awk '/^[a-f0-9]+/ {print $1; exit}' || true)
head_rev=$(docker compose exec -T api alembic heads 2>/dev/null \
    | awk '/^[a-f0-9]+/ {print $1; exit}' || true)
if [ -n "$current_rev" ] && [ -n "$head_rev" ]; then
    if [ "$current_rev" = "$head_rev" ]; then
        ok "alembic current=${current_rev} matches heads (schema up to date)"
    else
        warn "alembic reports current=${current_rev} but heads=${head_rev}"
        warn "The backup was taken against an older schema version. Run:"
        warn "  docker compose exec api alembic upgrade head"
        warn "to bring the schema forward. The restore itself succeeded."
    fi
fi

cat <<EOF

==> Restore complete.

    Source:     ${DUMP_PATH}
    Models:     ${model_count} knowledge model(s) restored
    API:        ${BASE_URL} (ready)

    Next steps:
      bash scripts/smoke.sh           # full verification of the restored stack
      bash scripts/status.sh          # quick operator health summary

EOF
