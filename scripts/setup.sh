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
command -v node    >/dev/null 2>&1 || error "Node.js 18+ is required. Install from https://nodejs.org"
command -v npm     >/dev/null 2>&1 || error "npm is required (comes with Node.js)"

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
NODE_VERSION=$(node --version | sed 's/v//' | cut -d. -f1)

[[ "${PYTHON_VERSION}" < "3.12" ]] && error "Python 3.12+ required (got ${PYTHON_VERSION})"
[[ "${NODE_VERSION}" -lt 18 ]]     && error "Node.js 18+ required (got ${NODE_VERSION})"

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

# ── Backend ───────────────────────────────────────────────────────────────────
info "Installing Python backend…"
pip install --quiet -e .
success "Backend installed"

# ── Frontend ──────────────────────────────────────────────────────────────────
info "Installing frontend dependencies…"
(cd frontend && npm install --silent)
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
echo -e "    ${BOLD}uvicorn app.main:app --host 0.0.0.0 --port 8000${RESET}"
echo ""
echo "  App will be available at: http://localhost:8000"
echo ""
