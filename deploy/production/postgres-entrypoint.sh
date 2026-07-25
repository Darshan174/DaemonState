#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

staging_directory="/run/context-engine-secrets"
postgres_uid="$(id -u postgres)"
postgres_gid="$(id -g postgres)"

install \
  -d \
  -o "$postgres_uid" \
  -g "$postgres_gid" \
  -m 0700 \
  "$staging_directory"

for secret_name in postgres_admin_password postgres_app_password; do
  source_path="/run/secrets/$secret_name"
  target_path="$staging_directory/$secret_name"
  if [[ ! -r "$source_path" ]]; then
    echo "Required PostgreSQL secret is not readable: $secret_name" >&2
    exit 78
  fi
  secret_value="$(<"$source_path")"
  if (( ${#secret_value} < 20 )); then
    echo "PostgreSQL secrets must be at least 20 characters" >&2
    exit 78
  fi
  unset secret_value
  install \
    -o "$postgres_uid" \
    -g "$postgres_gid" \
    -m 0600 \
    "$source_path" \
    "$target_path"
done

exec /usr/local/bin/docker-entrypoint.sh "$@"
