#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

usage() {
  cat >&2 <<'EOF'
Usage: scripts/restore-postgres.sh ARCHIVE TARGET_DATABASE [PRODUCTION_ENV_FILE]

Restores a custom-format dump into TARGET_DATABASE through the running
production Compose database service. A missing target database is created
without touching the active database.

Replacing an existing database is destructive and requires:
  RESTORE_CONFIRM=replace:TARGET_DATABASE

The app and worker services must be stopped before an existing database can be
replaced. PRODUCTION_ENV_FILE defaults to /etc/context-engine/production.env.
EOF
}

if (( $# < 2 || $# > 3 )); then
  usage
  exit 64
fi

archive_path="$1"
target_database="$2"
production_env_file="${3:-${PRODUCTION_ENV_FILE:-/etc/context-engine/production.env}}"
script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repository_root="$(cd -- "$script_directory/.." && pwd -P)"
compose_file="$repository_root/docker-compose.production.yml"

if [[ ! -f "$archive_path" || ! -r "$archive_path" ]]; then
  echo "Backup archive is not a readable regular file: $archive_path" >&2
  exit 66
fi
if [[ -L "$archive_path" ]]; then
  echo "Refusing to restore from a symbolic link" >&2
  exit 64
fi
if [[ ! -s "$archive_path" ]]; then
  echo "Backup archive is empty" >&2
  exit 65
fi
if [[ ! "$target_database" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]]; then
  echo "TARGET_DATABASE must be a valid PostgreSQL identifier" >&2
  exit 64
fi
if [[ ! -r "$production_env_file" ]]; then
  echo "Production environment file is not readable: $production_env_file" >&2
  exit 66
fi

archive_directory="$(cd -- "$(dirname -- "$archive_path")" && pwd -P)"
archive_path="$archive_directory/$(basename -- "$archive_path")"
checksum_path="${archive_path}.sha256"

calculate_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "sha256sum or shasum is required" >&2
    return 69
  fi
}

if [[ -f "$checksum_path" ]]; then
  read -r expected_checksum _ <"$checksum_path"
  if [[ ! "$expected_checksum" =~ ^[0-9a-fA-F]{64}$ ]]; then
    echo "Checksum file is malformed: $checksum_path" >&2
    exit 65
  fi
  actual_checksum="$(calculate_sha256 "$archive_path")"
  if [[ "${actual_checksum,,}" != "${expected_checksum,,}" ]]; then
    echo "Backup checksum verification failed" >&2
    exit 65
  fi
else
  echo "Warning: no checksum file found at $checksum_path" >&2
fi

compose=(
  docker compose
  --env-file "$production_env_file"
  --file "$compose_file"
)
admin_user="$("${compose[@]}" exec -T db printenv POSTGRES_USER | tr -d '\r\n')"
app_user="$("${compose[@]}" exec -T db printenv POSTGRES_APP_USER | tr -d '\r\n')"

if [[ ! "$admin_user" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]]; then
  echo "The running db service has an invalid POSTGRES_USER value" >&2
  exit 65
fi
if [[ ! "$app_user" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]]; then
  echo "The running db service has an invalid POSTGRES_APP_USER value" >&2
  exit 65
fi

"${compose[@]}" exec -T db pg_restore --list <"$archive_path" >/dev/null

database_exists="$(
  "${compose[@]}" exec -T db \
    psql \
      --username "$admin_user" \
      --dbname postgres \
      --tuples-only \
      --no-align \
      --set ON_ERROR_STOP=1 \
      --command "SELECT 1 FROM pg_database WHERE datname = '$target_database';" \
    | tr -d '[:space:]'
)"

if [[ "$database_exists" == "1" ]]; then
  expected_confirmation="replace:$target_database"
  if [[ "${RESTORE_CONFIRM:-}" != "$expected_confirmation" ]]; then
    echo "Target database already exists; no changes were made." >&2
    echo "To replace it, set RESTORE_CONFIRM=$expected_confirmation" >&2
    exit 77
  fi

  running_services="$("${compose[@]}" ps --status running --services)"
  while IFS= read -r service; do
    if [[ "$service" == "app" || "$service" == "worker" ]]; then
      echo "Stop the app and worker services before replacing a database" >&2
      exit 77
    fi
  done <<<"$running_services"

  "${compose[@]}" exec -T db \
    dropdb \
      --username "$admin_user" \
      --force \
      --if-exists \
      "$target_database"
elif [[ -n "$database_exists" ]]; then
  echo "Unexpected response while checking the target database" >&2
  exit 74
fi

"${compose[@]}" exec -T db \
  createdb \
    --username "$admin_user" \
    --owner "$app_user" \
    --template template0 \
    --encoding UTF8 \
    "$target_database"

"${compose[@]}" exec -T db \
  psql \
    --username "$admin_user" \
    --dbname "$target_database" \
    --set ON_ERROR_STOP=1 \
    --command "CREATE EXTENSION IF NOT EXISTS vector;"

"${compose[@]}" exec -T db \
  pg_restore \
    --username "$admin_user" \
    --dbname "$target_database" \
    --role "$app_user" \
    --no-owner \
    --no-acl \
    --no-comments \
    --exit-on-error \
    --single-transaction \
  <"$archive_path"

"${compose[@]}" exec -T db \
  psql \
    --username "$admin_user" \
    --dbname "$target_database" \
    --set ON_ERROR_STOP=1 \
    --set target_database="$target_database" \
    --set app_role="$app_user" <<'SQL'
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'target_database')
\gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('ALTER DATABASE %I OWNER TO %I', :'target_database', :'app_role')
\gexec
SELECT format('ALTER SCHEMA public OWNER TO %I', :'app_role')
\gexec
SELECT format(
  'GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I',
  :'target_database',
  :'app_role'
)
\gexec
SELECT format('GRANT USAGE, CREATE ON SCHEMA public TO %I', :'app_role')
\gexec
SQL

"${compose[@]}" exec -T db \
  vacuumdb \
    --username "$app_user" \
    --dbname "$target_database" \
    --analyze-in-stages

table_count="$(
  "${compose[@]}" exec -T db \
    psql \
      --username "$app_user" \
      --dbname "$target_database" \
      --tuples-only \
      --no-align \
      --set ON_ERROR_STOP=1 \
      --command "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';" \
    | tr -d '[:space:]'
)"

if [[ ! "$table_count" =~ ^[1-9][0-9]*$ ]]; then
  echo "Restore completed but public schema verification found no tables" >&2
  exit 74
fi

echo "Restore completed: $target_database ($table_count public tables)"
