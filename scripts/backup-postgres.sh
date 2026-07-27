#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

usage() {
  cat >&2 <<'EOF'
Usage: scripts/backup-postgres.sh BACKUP_DIRECTORY [PRODUCTION_ENV_FILE]

Creates an atomic PostgreSQL custom-format dump and SHA-256 checksum by using
the running production Compose database service. BACKUP_DIRECTORY must not be
the filesystem root. PRODUCTION_ENV_FILE defaults to
/etc/daemonstate/production.env.
EOF
}

if (( $# < 1 || $# > 2 )); then
  usage
  exit 64
fi

backup_directory="$1"
production_env_file="${2:-${PRODUCTION_ENV_FILE:-/etc/daemonstate/production.env}}"
script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repository_root="$(cd -- "$script_directory/.." && pwd -P)"
compose_file="$repository_root/docker-compose.production.yml"

if [[ "$backup_directory" != /* ]]; then
  echo "BACKUP_DIRECTORY must be an absolute path" >&2
  exit 64
fi
if [[ "$backup_directory" == "/" ]]; then
  echo "Refusing to use the filesystem root as BACKUP_DIRECTORY" >&2
  exit 64
fi
if [[ -L "$backup_directory" ]]; then
  echo "Refusing to use a symbolic link as BACKUP_DIRECTORY" >&2
  exit 64
fi
if [[ ! -r "$production_env_file" ]]; then
  echo "Production environment file is not readable: $production_env_file" >&2
  exit 66
fi

install -d -m 0700 -- "$backup_directory"
backup_directory="$(cd -- "$backup_directory" && pwd -P)"

compose=(
  docker compose
  --env-file "$production_env_file"
  --file "$compose_file"
)
database_name="$("${compose[@]}" exec -T db printenv POSTGRES_DB | tr -d '\r\n')"
database_user="$("${compose[@]}" exec -T db printenv POSTGRES_USER | tr -d '\r\n')"

if [[ ! "$database_name" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]]; then
  echo "The running db service has an invalid POSTGRES_DB value" >&2
  exit 65
fi
if [[ ! "$database_user" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]]; then
  echo "The running db service has an invalid POSTGRES_USER value" >&2
  exit 65
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive_name="${database_name}-${timestamp}.dump"
archive_path="$backup_directory/$archive_name"
checksum_path="${archive_path}.sha256"
temporary_archive="$(mktemp "$backup_directory/.${archive_name}.XXXXXX")"
temporary_checksum="$(mktemp "$backup_directory/.${archive_name}.sha256.XXXXXX")"

cleanup() {
  rm -f -- "$temporary_archive" "$temporary_checksum"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ -e "$archive_path" || -e "$checksum_path" ]]; then
  echo "Refusing to overwrite an existing backup: $archive_path" >&2
  exit 73
fi

"${compose[@]}" exec -T db \
  pg_dump \
    --username "$database_user" \
    --dbname "$database_name" \
    --format custom \
    --compress 9 \
    --no-owner \
    --no-acl \
    --verbose \
  >"$temporary_archive"

if [[ ! -s "$temporary_archive" ]]; then
  echo "PostgreSQL produced an empty backup" >&2
  exit 74
fi

"${compose[@]}" exec -T db pg_restore --list <"$temporary_archive" >/dev/null

if command -v sha256sum >/dev/null 2>&1; then
  checksum="$(sha256sum "$temporary_archive" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  checksum="$(shasum -a 256 "$temporary_archive" | awk '{print $1}')"
else
  echo "sha256sum or shasum is required" >&2
  exit 69
fi

printf '%s  %s\n' "$checksum" "$archive_name" >"$temporary_checksum"
chmod 0600 "$temporary_archive" "$temporary_checksum"
mv -- "$temporary_archive" "$archive_path"
mv -- "$temporary_checksum" "$checksum_path"
trap - EXIT HUP INT TERM

echo "Backup created: $archive_path"
echo "Checksum: $checksum_path"
