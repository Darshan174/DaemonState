#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

app_role="${POSTGRES_APP_USER:-daemonstate_app}"
app_password_file="/run/daemonstate-secrets/postgres_app_password"

if [[ ! "$app_role" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]]; then
  echo "POSTGRES_APP_USER must be a valid PostgreSQL identifier" >&2
  exit 78
fi
if [[ ! -r "$app_password_file" ]]; then
  echo "PostgreSQL application password secret is not readable" >&2
  exit 78
fi

app_password="$(<"$app_password_file")"
if (( ${#app_password} < 20 )); then
  echo "PostgreSQL application password must be at least 20 characters" >&2
  exit 78
fi
unset app_password

psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set ON_ERROR_STOP=1 \
  --set app_role="$app_role" <<'SQL'
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT 80',
  :'app_role',
  rtrim(pg_read_file('/run/daemonstate-secrets/postgres_app_password'), E'\r\n')
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_role')
\gexec

CREATE EXTENSION IF NOT EXISTS vector;
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database())
\gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('ALTER DATABASE %I OWNER TO %I', current_database(), :'app_role')
\gexec
SELECT format('ALTER SCHEMA public OWNER TO %I', :'app_role')
\gexec
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I', current_database(), :'app_role')
\gexec
SELECT format('GRANT USAGE, CREATE ON SCHEMA public TO %I', :'app_role')
\gexec
SQL
