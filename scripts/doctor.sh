#!/usr/bin/env bash
# Context Engine - read-only first-run diagnostics
# Usage:
#   bash scripts/doctor.sh
#   bash scripts/doctor.sh --docker
#   bash scripts/doctor.sh --bare-metal
set -u -o pipefail

MODE="all"
FAILURES=0
WARNINGS=0

for arg in "$@"; do
  case "$arg" in
    --docker)
      MODE="docker"
      ;;
    --bare-metal)
      MODE="bare-metal"
      ;;
    -h|--help)
      sed -n '1,8p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

section() { printf "\n==> %s\n" "$*"; }
ok() { printf "ok: %s\n" "$*"; }
warn() { printf "warn: %s\n" "$*" >&2; WARNINGS=$((WARNINGS + 1)); }
fail() { printf "fail: %s\n" "$*" >&2; FAILURES=$((FAILURES + 1)); }

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root" || exit 1

section "Checkout"
if [[ -f "pyproject.toml" && -f "app/main.py" && -d "frontend" ]]; then
  ok "running from Context Engine repo root"
else
  fail "run this from the Context Engine repository root"
fi

if [[ -f ".env.example" ]]; then
  ok ".env.example present"
else
  fail ".env.example is missing"
fi

if [[ -f ".env" ]]; then
  ok ".env present"
else
  warn ".env missing; run: cp .env.example .env"
fi

if [[ -f "docker-compose.yml" ]]; then
  ok "docker-compose.yml present"
else
  fail "docker-compose.yml is missing"
fi

if [[ -f "docker-compose.smoke.yml" ]]; then
  ok "docker-compose.smoke.yml present"
else
  warn "docker-compose.smoke.yml missing; release smoke cannot run"
fi

section "Docker path"
DOCKER_READY=0
if [[ "$MODE" == "bare-metal" ]]; then
  ok "skipped because --bare-metal was selected"
else
  DOCKER_READY=1
  if command -v docker >/dev/null 2>&1; then
    ok "docker CLI found"
  else
    warn "docker CLI not found; install Docker to use the Docker quick start"
    DOCKER_READY=0
  fi

  if [[ "$DOCKER_READY" -eq 1 ]]; then
    if docker compose version >/dev/null 2>&1; then
      ok "docker compose found"
    else
      warn "docker compose is unavailable; Docker quick start and release smoke need compose support"
      DOCKER_READY=0
    fi
  fi

  if [[ "$DOCKER_READY" -eq 1 ]]; then
    if docker info >/dev/null 2>&1; then
      ok "docker daemon reachable"
    else
      warn "docker CLI is installed, but the daemon is not reachable; start Docker before docker compose up --build"
      DOCKER_READY=0
    fi
  fi
fi

if [[ "$MODE" == "docker" && "$DOCKER_READY" -ne 1 ]]; then
  fail "Docker quick-start prerequisites are incomplete"
fi

section "Bare-metal path"
BARE_METAL_READY=0
if [[ "$MODE" == "docker" ]]; then
  ok "skipped because --docker was selected"
else
  BARE_METAL_READY=1
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_VERSION="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || true)"
    if python3 - <<'PY' >/dev/null 2>&1
import sys

raise SystemExit(0 if sys.version_info >= (3, 12) else 1)
PY
    then
      ok "Python ${PYTHON_VERSION} found"
    else
      warn "Python 3.12+ required for bare-metal setup; found ${PYTHON_VERSION:-unknown}"
      BARE_METAL_READY=0
    fi
  else
    warn "python3 not found; bare-metal setup requires Python 3.12+"
    BARE_METAL_READY=0
  fi

  if command -v node >/dev/null 2>&1; then
    NODE_VERSION="$(node --version 2>/dev/null || true)"
    if node -e '
const [major, minor] = process.versions.node.split(".").map(Number);
const supported = (major === 20 && minor >= 19) ||
  (major === 22 && minor >= 13) || major >= 24;
process.exit(supported ? 0 : 1);
' >/dev/null 2>&1; then
      ok "Node.js ${NODE_VERSION} found"
    else
      warn "Node.js 20.19+ (20.x), 22.13+ (22.x), or 24+ required for bare-metal setup; found ${NODE_VERSION:-unknown}"
      BARE_METAL_READY=0
    fi
  else
    warn "node not found; bare-metal setup requires Node.js 20.19+ (20.x), 22.13+ (22.x), or 24+"
    BARE_METAL_READY=0
  fi

  if command -v npm >/dev/null 2>&1; then
    ok "npm found"
  else
    warn "npm not found; install Node.js with npm for bare-metal setup"
    BARE_METAL_READY=0
  fi

  if [[ -x ".venv/bin/python" ]]; then
    ok ".venv Python present"
  else
    warn ".venv missing; run: bash scripts/setup.sh"
  fi

  if [[ -d "frontend/node_modules" ]]; then
    ok "frontend/node_modules present"
  else
    warn "frontend dependencies missing; run: bash scripts/setup.sh"
  fi

  if [[ -f "frontend/dist/index.html" ]]; then
    ok "frontend build present"
  else
    warn "frontend build missing; run: bash scripts/setup.sh or (cd frontend && npm run build)"
  fi
fi

if [[ "$MODE" == "bare-metal" && "$BARE_METAL_READY" -ne 1 ]]; then
  fail "Bare-metal prerequisites are incomplete"
fi

if [[ "$MODE" == "all" && "$DOCKER_READY" -ne 1 && "$BARE_METAL_READY" -ne 1 ]]; then
  fail "Neither Docker nor bare-metal prerequisites are currently ready"
fi

PORT="${PORT:-8000}"

section "Next commands"
printf "  Docker start:       docker compose up --build\n"
printf "  Bare-metal setup:   bash scripts/setup.sh\n"
printf "  Bare-metal start:   bash scripts/start.sh\n"
printf "  Demo seed:          curl -X POST http://localhost:%s/api/seed-demo -H 'content-type: application/json' -d '{}'\n" "$PORT"
printf "  Local verification: bash scripts/smoke.sh\n"
printf "  Release smoke:      bash scripts/smoke.sh --docker\n"

if [[ "$FAILURES" -gt 0 ]]; then
  printf "\nDoctor found %s failure(s) and %s warning(s).\n" "$FAILURES" "$WARNINGS" >&2
  exit 1
fi

if [[ "$WARNINGS" -gt 0 ]]; then
  printf "\nDoctor completed with %s warning(s).\n" "$WARNINGS" >&2
else
  printf "\nDoctor passed.\n"
fi
