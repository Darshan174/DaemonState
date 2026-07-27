#!/usr/bin/env bash
# Reject mutable or incomplete image references before a production pull/up.
set -Eeuo pipefail
umask 077

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
environment_file="${1:-}"
compose_file="${repo_root}/docker-compose.production.yml"

if [[ -z "${environment_file}" || ! -r "${environment_file}" ]]; then
  echo "Usage: $0 /path/to/production.env" >&2
  exit 2
fi
command -v docker >/dev/null 2>&1 || {
  echo "Docker is required." >&2
  exit 1
}
command -v python3 >/dev/null 2>&1 || {
  echo "Python 3 is required." >&2
  exit 1
}
docker compose version >/dev/null 2>&1 || {
  echo "Docker Compose v2 is required." >&2
  exit 1
}

rendered_config="$(mktemp "${TMPDIR:-/tmp}/daemonstate-production-config.XXXXXX")"
cleanup() {
  rm -f "${rendered_config}"
}
trap cleanup EXIT

docker compose \
  --project-directory "${repo_root}" \
  --env-file "${environment_file}" \
  --file "${compose_file}" \
  config --format json >"${rendered_config}"

python3 - "${rendered_config}" <<'PY'
import json
from pathlib import Path
import re
import sys

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
services = config.get("services")
if not isinstance(services, dict) or not services:
    raise SystemExit("Rendered production Compose configuration has no services.")

immutable = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
errors = []
for name, service in sorted(services.items()):
    if service.get("build"):
        errors.append(f"{name}: production services must not build from local source")
    image = service.get("image")
    if not isinstance(image, str) or not immutable.fullmatch(image):
        errors.append(
            f"{name}: image must be digest-pinned as "
            "repository[:tag]@sha256:<64 lowercase hex characters>"
        )

if errors:
    raise SystemExit("Production image preflight failed:\n- " + "\n- ".join(errors))
print(f"ok: {len(services)} production service images are digest-pinned")
PY
