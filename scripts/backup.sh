#!/usr/bin/env bash
#
# scripts/backup.sh — portable pg_dump backup for Context Engine.
#
# Produces a single custom-format dump file of the `context_engine`
# database, timestamped so multiple runs never overwrite each other,
# validates the dump is readable via `pg_restore --list`, and rotates
# older backups so disk growth is bounded.
#
# This is the supported, documented backup path. Wire it into cron
# for nightly backups; ship the output off-host for disaster recovery.
#
# NOTE: scripts/diagnose.sh is NOT a backup tool. It collects a
# read-only runtime snapshot and never touches application data.
# Use this script (backup.sh) for backups.
#
# ──────────────────────────────────────────────────────────────────────
# Usage
# ──────────────────────────────────────────────────────────────────────
#   bash scripts/backup.sh                    # default: ./backups/
#   bash scripts/backup.sh --output /srv/bkp  # override output dir
#   bash scripts/backup.sh --retention 30     # keep last N (default 14)
#   bash scripts/backup.sh --quiet            # only print the path
#
# Environment overrides:
#   BACKUP_DIR       default ./backups
#   BACKUP_RETENTION default 14  (keep the N most recent dumps)
#   BACKUP_QUIET     default 0   (set to 1 to suppress status output)
#
# ──────────────────────────────────────────────────────────────────────
# Exit codes
# ──────────────────────────────────────────────────────────────────────
#   0  success — dump written and validated
#   1  generic failure (pg_dump, validation, disk, etc.)
#   2  bad arguments
#
# ──────────────────────────────────────────────────────────────────────
# Cron example
# ──────────────────────────────────────────────────────────────────────
#   0 3 * * * cd /srv/context-engine && \
#       bash scripts/backup.sh --output /backups --retention 30 --quiet \
#       >> /var/log/ctxe-backup.log 2>&1

set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

BACKUP_DIR=${BACKUP_DIR:-./backups}
BACKUP_RETENTION=${BACKUP_RETENTION:-14}
BACKUP_QUIET=${BACKUP_QUIET:-0}

while [ $# -gt 0 ]; do
    case "$1" in
        --output|-o)
            BACKUP_DIR=$2; shift 2 ;;
        --retention|-r)
            BACKUP_RETENTION=$2; shift 2 ;;
        --quiet|-q)
            BACKUP_QUIET=1; shift ;;
        -h|--help)
            grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            printf "backup.sh: unknown argument '%s' (try --help)\n" "$1" >&2
            exit 2
            ;;
    esac
done

log()  { [ "$BACKUP_QUIET" = 1 ] || printf "==> %s\n" "$*"; }
ok()   { [ "$BACKUP_QUIET" = 1 ] || printf "    [OK]   %s\n" "$*"; }
info() { [ "$BACKUP_QUIET" = 1 ] || printf "    [info] %s\n" "$*"; }
die()  { printf "    [FAIL] %s\n" "$*" >&2; exit 1; }

# ── Preflight ────────────────────────────────────────────────────
log "Preflight"
command -v docker >/dev/null 2>&1 || die "docker not installed"
docker compose version >/dev/null 2>&1 || die "docker compose v2 not available"

# Postgres must actually be running — pg_dump needs a live server.
pg_state=$(docker compose ps --services --filter "status=running" 2>/dev/null | grep -x postgres || true)
if [ -z "$pg_state" ]; then
    die "postgres container is not running. Start the stack with 'docker compose up -d postgres' before running backup.sh"
fi
ok "postgres container is running"

# ── Output directory ─────────────────────────────────────────────
mkdir -p "$BACKUP_DIR" \
    || die "could not create backup directory: $BACKUP_DIR"

# Basic disk-space sanity check — bail if the target FS has less than
# 100 MB free. Most dumps are a few MB, but a loud failure beats a
# silently-truncated dump file.
if command -v df >/dev/null 2>&1; then
    free_kb=$(df -Pk "$BACKUP_DIR" 2>/dev/null | awk 'NR==2 {print $4}')
    if [ -n "${free_kb:-}" ] && [ "$free_kb" -lt 102400 ]; then
        die "backup target directory has less than 100 MB free ($free_kb KB). Free space or point --output elsewhere."
    fi
fi
ok "backup directory: $BACKUP_DIR"

# ── Dump ─────────────────────────────────────────────────────────
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
dump_name="context_engine-${timestamp}.dump"
dump_path="${BACKUP_DIR}/${dump_name}"
tmp_path="${dump_path}.partial"

log "Dumping to ${dump_path}"
# Use --format=custom for portability across minor versions and for
# --list support. Write to .partial then atomically move so a crashed
# dump never leaves a half-written file with the final name.
if ! docker compose exec -T postgres \
        pg_dump -U postgres -d context_engine \
        --no-owner --format=custom \
        > "$tmp_path" 2>/tmp/ctxe-backup-err.$$; then
    err=$(cat /tmp/ctxe-backup-err.$$ 2>/dev/null || true)
    rm -f /tmp/ctxe-backup-err.$$ "$tmp_path"
    die "pg_dump failed: ${err:-<no stderr captured>}"
fi
rm -f /tmp/ctxe-backup-err.$$

# Sanity check: dump file must be non-empty. A zero-byte file usually
# means pg_dump crashed before writing any data.
dump_bytes=$(wc -c < "$tmp_path" | tr -d ' ')
if [ "$dump_bytes" -lt 1024 ]; then
    rm -f "$tmp_path"
    die "pg_dump produced a suspiciously small file (${dump_bytes} bytes). Aborting."
fi

# Validate the dump is readable — pg_restore --list reads the TOC
# without restoring anything. An unreadable dump here is a bug in the
# archive format, a corrupt filesystem, or a truncated write. Run
# inside the postgres container so we don't need pg_restore on the
# host; bind-mount the .partial file via docker compose cp into a
# tmp path the container can read.
container_tmp="/tmp/ctxe-backup-validate.$$.dump"
docker compose cp "$tmp_path" "postgres:${container_tmp}" >/dev/null 2>&1 \
    || { rm -f "$tmp_path"; die "failed to copy dump into postgres container for validation"; }
if ! docker compose exec -T postgres pg_restore --list "$container_tmp" \
        >/dev/null 2>/tmp/ctxe-restore-err.$$; then
    err=$(cat /tmp/ctxe-restore-err.$$ 2>/dev/null || true)
    docker compose exec -T postgres rm -f "$container_tmp" >/dev/null 2>&1 || true
    rm -f /tmp/ctxe-restore-err.$$ "$tmp_path"
    die "dump validation failed — pg_restore --list could not read the archive: ${err:-<no stderr captured>}"
fi
docker compose exec -T postgres rm -f "$container_tmp" >/dev/null 2>&1 || true
rm -f /tmp/ctxe-restore-err.$$

# Atomic rename: everything above this point ran successfully.
mv "$tmp_path" "$dump_path"
dump_size=$(du -h "$dump_path" 2>/dev/null | awk '{print $1}')
ok "wrote ${dump_name} (${dump_size:-unknown size}, ${dump_bytes} bytes)"
ok "dump validated via pg_restore --list"

# ── Rotation ─────────────────────────────────────────────────────
# Keep the N most recent context_engine-*.dump files. "Most recent"
# by lexicographic order is safe because the timestamp in the name
# is ISO-8601-like (YYYYMMDDTHHMMSSZ) which sorts correctly.
log "Rotation (keep ${BACKUP_RETENTION} most recent)"
all_dumps=$(ls -1 "${BACKUP_DIR}"/context_engine-*.dump 2>/dev/null | sort || true)
total=$(printf "%s\n" "$all_dumps" | grep -c '.' || true)
if [ "$total" -le "$BACKUP_RETENTION" ]; then
    ok "no rotation needed (${total} dump(s), retention ${BACKUP_RETENTION})"
else
    to_delete=$(( total - BACKUP_RETENTION ))
    # Delete oldest first — head -N gives the N oldest after sort.
    printf "%s\n" "$all_dumps" | head -n "$to_delete" | while IFS= read -r old; do
        [ -n "$old" ] || continue
        rm -f "$old" && info "deleted old backup: $(basename "$old")"
    done
    ok "rotated ${to_delete} old dump(s), kept ${BACKUP_RETENTION} most recent"
fi

# ── Summary ──────────────────────────────────────────────────────
if [ "$BACKUP_QUIET" = 1 ]; then
    printf "%s\n" "$dump_path"
else
    cat <<EOF

==> Backup complete.

    File:       ${dump_path}
    Size:       ${dump_size:-unknown}
    Format:     pg_dump custom (--format=custom)
    Validated:  pg_restore --list succeeded

    Restore with:
      bash scripts/restore.sh ${dump_path}

    For off-host copies (strongly recommended for disaster recovery):
      rsync / rclone / aws s3 cp the dump file to another host.

EOF
fi
