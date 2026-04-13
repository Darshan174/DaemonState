#!/usr/bin/env bash
#
# scripts/upgrade.sh — supported upgrade path for a self-hosted
# Context Engine stack.
#
# Runs the upgrade as a sequence of well-defined stages and, on any
# failure, prints the EXACT rollback commands the operator needs —
# with the real backup path and the pre-upgrade git SHA baked in so
# recovery is copy-paste, not creative.
#
# Stages:
#   1. Preflight       — docker/git/curl installed, clean tree, pg up
#   2. Record state    — current git SHA + alembic revision
#   3. Safety backup   — scripts/backup.sh --output ./backups/pre-upgrade
#   4. git pull        — fast-forward only; refuses diverged branches
#   5. Rebuild         — docker compose up -d --build
#   6. Readiness       — wait for /health/ready
#   7. Migrate         — alembic upgrade head
#   8. Smoke           — scripts/smoke.sh
#
# Success disarms the rollback trap and prints a summary including
# the backup path (which you should keep until the new code has
# shown itself safe in production).
#
# This is the documented, supported upgrade path. The equivalent raw
# commands are in docs/runbook.md under "Upgrade / rollback" for
# reference, but running this script is always safer than running
# them by hand — it captures the pre-upgrade state before it can
# change.
#
# ──────────────────────────────────────────────────────────────────────
# DANGER
# ──────────────────────────────────────────────────────────────────────
# This script rebuilds images, restarts containers, and migrates the
# schema in place. There is a moment, between stages 5 and 7, where
# the stack is running the NEW code against the OLD schema. This is
# normal and brief, but clients will see request errors during that
# window. Run upgrades in a maintenance window unless your deployment
# is designed to tolerate request errors during rollout.
#
# ──────────────────────────────────────────────────────────────────────
# Usage
# ──────────────────────────────────────────────────────────────────────
#   bash scripts/upgrade.sh --yes
#   bash scripts/upgrade.sh --yes --branch main
#   bash scripts/upgrade.sh --yes --skip-smoke
#   bash scripts/upgrade.sh --yes --no-backup       # NOT recommended
#
# Environment overrides:
#   BASE_URL          default http://localhost:8000
#   HEALTH_TIMEOUT_S  default 120  (seconds to wait for /health/ready after rebuild)
#   CTXE_UPGRADE_YES  set to 1 to skip the --yes confirmation check
#
# ──────────────────────────────────────────────────────────────────────
# Exit codes
# ──────────────────────────────────────────────────────────────────────
#   0  upgrade completed and smoke passed (or already up-to-date)
#   1  upgrade failed — rollback commands printed to stderr
#   2  bad arguments or preflight refused

set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

BASE_URL=${BASE_URL:-http://localhost:8000}
HEALTH_TIMEOUT_S=${HEALTH_TIMEOUT_S:-120}

CONFIRMED=${CTXE_UPGRADE_YES:-0}
SKIP_SMOKE=0
NO_BACKUP=0
TARGET_BRANCH=""

# Initialize state variables up front so the EXIT trap can reference
# them safely even if the failure happens before they get set.
CURRENT_BRANCH=""
CURRENT_SHA=""
CURRENT_SHORT_SHA=""
CURRENT_ALEMBIC=""
BACKUP_PATH=""
NEW_SHA=""
NEW_SHORT_SHA=""
NEW_ALEMBIC=""

while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y)
            CONFIRMED=1; shift ;;
        --skip-smoke)
            SKIP_SMOKE=1; shift ;;
        --no-backup)
            NO_BACKUP=1; shift ;;
        --branch|-b)
            TARGET_BRANCH=$2; shift 2 ;;
        -h|--help)
            grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            printf "upgrade.sh: unknown argument '%s' (try --help)\n" "$1" >&2
            exit 2
            ;;
    esac
done

log()  { printf "\n==> %s\n" "$*"; }
ok()   { printf "    [OK]   %s\n" "$*"; }
info() { printf "    [info] %s\n" "$*"; }
warn() { printf "    [warn] %s\n" "$*" >&2; }
die()  { printf "    [FAIL] %s\n" "$*" >&2; exit 1; }

# ── Confirmation gate ───────────────────────────────────────────
if [ "$CONFIRMED" != 1 ]; then
    cat >&2 <<EOF
upgrade.sh: refusing to run without explicit confirmation.

Upgrading will, in order:

  1. Take a safety backup of the current database
  2. git pull (fast-forward your checkout)
  3. docker compose up -d --build (rebuild container images)
  4. alembic upgrade head (migrate schema)
  5. Run scripts/smoke.sh to verify

Any stage can fail. On failure, upgrade.sh prints the EXACT rollback
commands — including the backup path it just wrote and the pre-upgrade
git SHA — so recovery is mechanical.

To proceed, re-run with --yes:

    bash scripts/upgrade.sh --yes

EOF
    exit 2
fi

# ── Preflight ────────────────────────────────────────────────────
log "Preflight"
command -v docker >/dev/null 2>&1 || die "docker not installed"
command -v git >/dev/null 2>&1 || die "git not installed"
command -v curl >/dev/null 2>&1 || die "curl not installed"
docker compose version >/dev/null 2>&1 || die "docker compose v2 not available"

# Must be a git clone, not a tarball extract — upgrade.sh uses git pull.
if [ ! -d .git ]; then
    die "$(pwd) is not a git checkout — upgrade.sh requires 'git pull'. If you deployed from a tarball or zip, rebuild manually: docker compose pull && docker compose up -d --build"
fi
ok "git checkout detected"

# Working tree must be clean. Uncommitted changes make the rollback
# path ambiguous: we cannot restore to a pre-upgrade state that has
# local edits layered on top.
if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
    die "working tree has uncommitted changes — refusing to run. Stash or commit them first. Run 'git status' to see what's dirty."
fi
ok "working tree is clean"

# Postgres must be running so we can take a safety backup. If the
# operator opted out of the safety backup, we skip this check.
if [ "$NO_BACKUP" != 1 ]; then
    pg_state=$(docker compose ps --services --filter "status=running" 2>/dev/null | grep -x postgres || true)
    if [ -z "$pg_state" ]; then
        die "postgres container is not running. Start the stack with 'docker compose up -d' before upgrading, or pass --no-backup to skip the safety backup (NOT recommended — rollback will be DB-impossible)."
    fi
    ok "postgres container is running"
fi

# ── Record pre-upgrade state ────────────────────────────────────
log "Recording pre-upgrade state"

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
CURRENT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
CURRENT_SHORT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "")

if [ -z "$CURRENT_SHA" ]; then
    die "could not read current git SHA — the repository may be corrupted"
fi

# Default target branch = whatever we're currently on.
if [ -z "$TARGET_BRANCH" ]; then
    TARGET_BRANCH="$CURRENT_BRANCH"
fi

info "pre-upgrade branch: ${CURRENT_BRANCH:-<detached>}"
info "pre-upgrade SHA:    ${CURRENT_SHORT_SHA} (${CURRENT_SHA})"

# Try to read the current alembic revision. Non-fatal if it fails —
# the api may be down, or this may be a fresh install. The EXIT trap
# prints the rollback commands either way.
CURRENT_ALEMBIC=$(docker compose exec -T api alembic current 2>/dev/null \
    | awk '/^[a-f0-9]+/ {print $1; exit}' || true)
if [ -n "$CURRENT_ALEMBIC" ]; then
    info "pre-upgrade alembic revision: ${CURRENT_ALEMBIC}"
else
    info "pre-upgrade alembic revision: <unknown> (api container may be down)"
fi

# ── Safety backup ───────────────────────────────────────────────
if [ "$NO_BACKUP" = 1 ]; then
    log "Skipping pre-upgrade backup (--no-backup)"
    warn "you are running without a safety backup. DB rollback will NOT be available from this script."
else
    log "Pre-upgrade safety backup"
    # backup.sh --quiet prints only the final dump path on success,
    # so we capture stdout and use the last line as the artifact path.
    if ! BACKUP_OUT=$(bash "${ROOT_DIR}/scripts/backup.sh" \
            --output "./backups/pre-upgrade" \
            --retention 10 \
            --quiet 2>&1); then
        printf "%s\n" "$BACKUP_OUT" >&2
        die "pre-upgrade backup failed — refusing to proceed. See output above. To force-upgrade anyway (NOT recommended), re-run with --no-backup."
    fi
    BACKUP_PATH=$(printf "%s" "$BACKUP_OUT" | tail -n1 | tr -d '\r')
    if [ -z "$BACKUP_PATH" ] || [ ! -f "$BACKUP_PATH" ]; then
        die "backup.sh reported success but the written dump path is missing (got: '${BACKUP_PATH}'). Refusing to proceed."
    fi
    ok "safety backup: ${BACKUP_PATH}"
fi

# ── Rollback trap ───────────────────────────────────────────────
# From here on, any non-zero exit needs to walk the operator through
# recovery. The commands below are tailored to the state we captured
# above (pre-upgrade SHA + backup path), so they are copy-paste ready
# — not a generic template.
print_rollback_hints() {
    local exit_code=$?
    if [ "$exit_code" -eq 0 ]; then
        return 0
    fi
    {
        printf "\n==> UPGRADE FAILED (exit %d)\n" "$exit_code"
        printf "\n    Recovery commands — run these in order. Stop as soon as\n"
        printf "    smoke.sh passes again.\n"
        printf "\n    1. Restore the pre-upgrade code:\n"
        printf "\n         git checkout %s\n" "$CURRENT_SHA"
        printf "\n    2. Rebuild with the old code:\n"
        printf "\n         docker compose up -d --build\n"
        if [ -n "$BACKUP_PATH" ]; then
            printf "\n    3. Restore the pre-upgrade database. Only required if\n"
            printf "       alembic upgrade head ran (stage 7). If the failure\n"
            printf "       was before then, the DB is untouched and you can\n"
            printf "       skip this step.\n"
            printf "\n         bash scripts/restore.sh %s --yes\n" "$BACKUP_PATH"
            printf "\n    4. Verify the rollback:\n"
            printf "\n         bash scripts/smoke.sh\n"
        else
            printf "\n    3. You ran with --no-backup. DB rollback is NOT available\n"
            printf "       from this script. Restore from the nearest known-good\n"
            printf "       backup manually.\n"
            printf "\n    4. Verify the rollback:\n"
            printf "\n         bash scripts/smoke.sh\n"
        fi
        printf "\n    If the failure was in the smoke stage, the stack is up on\n"
        printf "    the NEW code but something does not work. You can either:\n"
        printf "      (a) Roll back using the commands above (safe default)\n"
        printf "      (b) Debug in place:\n"
        printf "            bash scripts/status.sh\n"
        printf "            bash scripts/diagnose.sh --tar\n"
        printf "            docker compose logs --tail 100 api\n"
        printf "\n    See docs/runbook.md → 'Upgrade / rollback' for the full playbook.\n\n"
    } >&2
}
trap print_rollback_hints EXIT

# ── git pull ────────────────────────────────────────────────────
log "git pull (branch: ${TARGET_BRANCH:-<detached>})"
git fetch --all --prune 2>&1 | sed 's/^/    /' \
    || die "git fetch failed"

# If the caller specified a different branch, switch to it first.
if [ -n "$TARGET_BRANCH" ] && [ "$TARGET_BRANCH" != "$CURRENT_BRANCH" ]; then
    git checkout "$TARGET_BRANCH" 2>&1 | sed 's/^/    /' \
        || die "git checkout ${TARGET_BRANCH} failed"
fi

# --ff-only: refuse to merge. If origin has diverged from local,
# upgrade.sh bails out and leaves the working tree untouched. The
# operator resolves the divergence manually and re-runs.
git pull --ff-only origin "$TARGET_BRANCH" 2>&1 | sed 's/^/    /' \
    || die "git pull --ff-only failed. Your branch has diverged from origin/${TARGET_BRANCH}. Resolve the divergence manually; upgrade.sh only supports fast-forward updates."

NEW_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
NEW_SHORT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "")

if [ "$NEW_SHA" = "$CURRENT_SHA" ]; then
    # Nothing to do. Disarm the rollback trap and exit cleanly — no
    # rebuild, no restart, no schema migration, no smoke.
    trap - EXIT
    cat <<EOF

==> Already up to date.

    Branch:   ${TARGET_BRANCH:-<detached>}
    SHA:      ${CURRENT_SHORT_SHA}
    No rebuild or restart performed — nothing to do.

EOF
    exit 0
fi
ok "advanced from ${CURRENT_SHORT_SHA} to ${NEW_SHORT_SHA}"

# ── Rebuild ─────────────────────────────────────────────────────
log "Rebuilding containers (docker compose up -d --build)"
# --build ensures image layers are refreshed against the new source
# tree. Without it, docker compose would happily reuse cached images
# built from the old SHA, defeating the purpose of the upgrade.
docker compose up -d --build 2>&1 | sed 's/^/    /' \
    || die "docker compose up -d --build failed. Check the build output above for the failing layer."
ok "containers rebuilt and up"

# ── Readiness ───────────────────────────────────────────────────
log "Waiting for /health/ready (up to ${HEALTH_TIMEOUT_S}s)"
deadline=$(( $(date +%s) + HEALTH_TIMEOUT_S ))
while true; do
    if curl -fsS --max-time 5 "${BASE_URL}/health/ready" >/dev/null 2>&1; then
        break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        warn "API did not become ready in ${HEALTH_TIMEOUT_S}s after rebuild."
        warn "Check logs:"
        warn "  docker compose logs --tail 60 api"
        warn "  docker compose logs --tail 40 worker"
        die "post-rebuild readiness check timed out"
    fi
    sleep 2
done
ok "/health/ready → ready"

# ── Migrate ─────────────────────────────────────────────────────
log "Migrating schema (alembic upgrade head)"
if ! migrate_out=$(docker compose exec -T api alembic upgrade head 2>&1); then
    printf "%s\n" "$migrate_out" >&2
    die "alembic upgrade head failed. The new image is running against a schema it does not understand. Rollback instructions below."
fi
printf "%s\n" "$migrate_out" | sed 's/^/    /'

NEW_ALEMBIC=$(docker compose exec -T api alembic current 2>/dev/null \
    | awk '/^[a-f0-9]+/ {print $1; exit}' || true)
if [ -n "$NEW_ALEMBIC" ]; then
    if [ "$NEW_ALEMBIC" = "$CURRENT_ALEMBIC" ]; then
        ok "alembic revision unchanged: ${NEW_ALEMBIC} (no new migrations in this upgrade)"
    else
        ok "alembic revision: ${CURRENT_ALEMBIC:-<unknown>} → ${NEW_ALEMBIC}"
    fi
else
    warn "could not confirm post-migration alembic revision"
fi

# ── Smoke ───────────────────────────────────────────────────────
if [ "$SKIP_SMOKE" = 1 ]; then
    log "Skipping smoke check (--skip-smoke)"
    warn "upgrade is NOT fully verified without smoke.sh. Run it manually when you can: bash scripts/smoke.sh"
    SMOKE_STATUS="skipped"
else
    log "Running scripts/smoke.sh"
    # smoke.sh has its own diagnostic trap that dumps logs on failure,
    # so we don't need to duplicate that here. Just propagate its
    # exit code and let our rollback trap kick in.
    if ! bash "${ROOT_DIR}/scripts/smoke.sh" 2>&1 | sed 's/^/    /'; then
        die "smoke.sh failed — the new code is broken somewhere. Rollback instructions below."
    fi
    ok "smoke.sh passed"
    SMOKE_STATUS="passed"
fi

# ── Success ─────────────────────────────────────────────────────
# Disarm the rollback trap so the success banner is not followed by
# the failure banner.
trap - EXIT

cat <<EOF

==> Upgrade complete.

    Branch:        ${TARGET_BRANCH:-<detached>}
    From:          ${CURRENT_SHORT_SHA}
    To:            ${NEW_SHORT_SHA}
    Alembic:       ${CURRENT_ALEMBIC:-<unknown>} → ${NEW_ALEMBIC:-<unknown>}
    Safety backup: ${BACKUP_PATH:-<skipped: --no-backup>}
    Smoke:         ${SMOKE_STATUS}

    Keep the safety backup until the new code has proven stable. If a
    regression surfaces later, the exact rollback commands are:

      git checkout ${CURRENT_SHA}
      docker compose up -d --build
EOF
if [ -n "$BACKUP_PATH" ]; then
    cat <<EOF
      bash scripts/restore.sh ${BACKUP_PATH} --yes
EOF
fi
cat <<EOF
      bash scripts/smoke.sh

    For continuous health visibility after the upgrade:
      bash scripts/status.sh

EOF
