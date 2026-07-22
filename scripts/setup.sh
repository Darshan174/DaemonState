#!/usr/bin/env bash
# Context Engine — bare-metal setup script
# Run once on a fresh machine: bash scripts/setup.sh
set -euo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

info()    { echo -e "${GREEN}▶${RESET} $*"; }
warn()    { echo -e "${YELLOW}⚠${RESET}  $*"; }
success() { echo -e "${GREEN}✔${RESET}  $*"; }
error()   { echo -e "${RED}✖${RESET}  $*" >&2; exit 1; }

echo -e "\n${BOLD}Context Engine — Setup${RESET}\n"

# ── Prerequisites check ───────────────────────────────────────────────────────
info "Checking prerequisites…"

command -v python3 >/dev/null 2>&1 || error "Python 3.12+ is required. Install from https://python.org"
command -v node    >/dev/null 2>&1 || error "Node.js 20.19+ (20.x), 22.13+ (22.x), or 24+ is required. Install from https://nodejs.org"
command -v npm     >/dev/null 2>&1 || error "npm is required (comes with Node.js)"

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
NODE_VERSION=$(node --version | sed 's/^v//')

python3 - <<'PY' >/dev/null || error "Python 3.12+ required (got ${PYTHON_VERSION})"
import sys

raise SystemExit(0 if sys.version_info >= (3, 12) else 1)
PY
if ! node -e '
const [major, minor] = process.versions.node.split(".").map(Number);
const supported = (major === 20 && minor >= 19) ||
  (major === 22 && minor >= 13) || major >= 24;
process.exit(supported ? 0 : 1);
' >/dev/null 2>&1; then
  error "Node.js 20.19+ (20.x), 22.13+ (22.x), or 24+ required (got ${NODE_VERSION})"
fi

success "Python ${PYTHON_VERSION}, Node.js $(node --version)"

# ── .env setup ────────────────────────────────────────────────────────────────
if [[ ! -f ".env" ]]; then
  info "Creating .env from .env.example…"
  cp .env.example .env
  success ".env created — edit it to add AI keys and connectors (optional)"
else
  warn ".env already exists — skipping"
fi

# ── Data directory ────────────────────────────────────────────────────────────
mkdir -p data
success "data/ directory ready"

# ── Virtual environment ───────────────────────────────────────────────────────
VENV_DIR="${VENV_DIR:-.venv}"
if [[ "${CONTEXT_ENGINE_USE_SYSTEM_PYTHON:-0}" == "1" ]]; then
  warn "Using system Python because CONTEXT_ENGINE_USE_SYSTEM_PYTHON=1"
  PYTHON_BIN="python3"
else
  info "Creating Python virtual environment at ${VENV_DIR}…"
  python3 -m venv "${VENV_DIR}" || error "Could not create virtual environment. Install the Python venv module and retry."
  PYTHON_BIN="${VENV_DIR}/bin/python"
  "${PYTHON_BIN}" -m pip install --quiet --upgrade pip
  success "Virtual environment ready"
fi

# ── Backend ───────────────────────────────────────────────────────────────────
info "Installing Python backend…"
"${PYTHON_BIN}" -m pip install --quiet -e ".[dev]"
success "Backend installed"

# ── Frontend ──────────────────────────────────────────────────────────────────
info "Installing frontend dependencies…"
(cd frontend && npm ci --silent)
success "Frontend dependencies installed"

info "Building frontend…"
(cd frontend && npm run build --silent)
success "Frontend built → frontend/dist/"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}Setup complete!${RESET}"
echo ""
echo "  Start the app:"
echo -e "    ${BOLD}bash scripts/start.sh${RESET}"
echo ""
echo "  Or run directly:"
echo -e "    ${BOLD}${PYTHON_BIN} -m uvicorn app.main:app --host 0.0.0.0 --port 8000${RESET}"
echo ""
echo "  App will be available at: http://localhost:8000"
echo ""
