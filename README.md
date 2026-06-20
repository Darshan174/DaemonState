# Context Engine

Open-source structured context infrastructure for AI systems. Turns scattered product knowledge into a living semantic graph — extract facts, explore relationships, detect gaps, and feed AI agents grounded context.

---

## Table of Contents

- [What It Is](#what-it-is)
- [Product Tour](#product-tour)
- [Quick Start — Docker](#quick-start--docker)
- [Quick Start — Bare Metal](#quick-start--bare-metal)
- [Configuration](#configuration)
- [AI / LLM Setup](#ai--llm-setup)
- [PostgreSQL Setup](#postgresql-setup)
- [Documentation](#documentation)
- [Testing And Release Smoke](#testing-and-release-smoke)
- [Community](#community)
- [Deployment](#deployment)
- [Connectors](#connectors)
- [CLI](#cli)
- [API Reference](#api-reference)
- [Architecture](#architecture)

---

## What It Is

Context Engine ingests documents from local files, AI coding sessions, Slack, GitHub, Gmail, and Google Drive. It extracts structured facts (decisions, risks, features, tasks, blockers) into a source-backed knowledge graph you can query, visualize, and feed directly to AI agents.

**Five built-in AI agents:**
1. **Ingestion Agent** — reads raw sources → clean entities
2. **Relationship Agent** — finds hidden links across sources
3. **Gap Detector** — surfaces missing owners, blocked items, isolated nodes
4. **Ask / Strategy Agent** — answers questions over the full graph with citations
5. **Context Pack Agent** — generates ready-to-paste handoff prompts for coding agents

Works fully offline with regex extraction. Plug in any LLM key to unlock AI-powered extraction and answers.

---

## Product Tour

Run the demo seed, then start in **Board**. Context is grouped by source family,
while the inspector carries provenance, relationship evidence, confidence, and
review state.

![Board graph with relationship inspector](docs/assets/board-inspector-demo.jpg)

Ask questions with retrieval controls. Answers return a stable `query.v1`
response and a visible facts-used trace instead of a black-box summary.

![Ask UI with facts-used trace](docs/assets/query-trace-demo.jpg)

For a click-by-click walkthrough of the seeded GitHub, Slack, Gmail, Google
Drive, and Codex demo workspace, see [Demo Walkthrough](docs/demo.md).

---

## Quick Start — Docker

The fastest path. No Python or Node.js required on the host.

```bash
git clone https://github.com/Darshan174/Context-Engine.git context-engine
cd context-engine

# Copy and optionally edit the config
cp .env.example .env

# Optional read-only Docker path check
bash scripts/doctor.sh --docker

# Start (SQLite, single container)
docker compose up --build
```

Open **http://localhost:8000** — the UI and API are served from the same port.

To explore without configuring provider credentials, click **Run Demo Workspace**
in the onboarding flow or seed it from the API:

```bash
curl -X POST http://localhost:8000/api/seed-demo -H 'content-type: application/json' -d '{}'
```

To stop: `docker compose down`
To wipe data: `docker compose down -v`

Docker smoke test on an alternate port, useful before tagging a release:

```bash
bash scripts/smoke.sh --docker
```

---

## Quick Start — Bare Metal

Requires **Python 3.12+** and **Node.js 18+**.

```bash
git clone https://github.com/Darshan174/Context-Engine.git context-engine
cd context-engine

# Optional read-only prerequisite check
bash scripts/doctor.sh --bare-metal

# One-command setup (installs deps, builds frontend)
bash scripts/setup.sh

# Start
bash scripts/start.sh
```

Open **http://localhost:8000**

`scripts/setup.sh` creates a local `.venv`, installs backend development
dependencies there, installs frontend dependencies with `npm ci`, and builds the
frontend bundle. `scripts/start.sh`, `scripts/dev.sh`, and `scripts/smoke.sh`
automatically use `.venv/bin/python` when it exists. Set `PYTHON_BIN=/path/to/python`
to override the interpreter, or `CONTEXT_ENGINE_USE_SYSTEM_PYTHON=1` during
setup if you intentionally want to install into the active system environment.

For a credential-free demo workspace:

```bash
curl -X POST http://localhost:8000/api/seed-demo -H 'content-type: application/json' -d '{}'
```

For development with hot reload on both frontend and backend:

```bash
bash scripts/dev.sh
# Backend:  http://localhost:8000
# Frontend: http://localhost:5000
```

---

## Configuration

Copy `.env.example` to `.env` and set your values:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/context.db` | Database connection string |
| `DATA_DIR` | `./data` | Directory for SQLite file and uploads |
| `LITELLM_API_KEY` | _(empty)_ | API key for your LLM provider |
| `EXTRACTION_MODEL` | _(empty)_ | LiteLLM model for entity extraction |
| `EMBEDDING_MODEL` | _(empty)_ | LiteLLM model for embeddings (optional) |
| `GOOGLE_CLIENT_ID` | _(empty)_ | Google OAuth — for Gmail/Drive connectors |
| `GOOGLE_CLIENT_SECRET` | _(empty)_ | Google OAuth |
| `SLACK_CLIENT_ID` | _(empty)_ | Slack OAuth — for Slack connector |
| `SLACK_CLIENT_SECRET` | _(empty)_ | Slack OAuth |
| `SLACK_MANAGED_INSTALL_URL` | _(empty)_ | Managed one-click Slack install URL. When set, the primary Slack button uses this hosted app path instead of self-hosted credentials |
| `ENCRYPTION_KEY` | _(empty)_ | Fernet key used to decrypt managed Slack broker callbacks |
| `PUBLIC_BASE_URL` | _(empty)_ | External app URL used for OAuth callbacks in deployed environments |
| `PORT` | `8000` | Port the server listens on |

---

## AI / LLM Setup

Context Engine works without any AI key — it uses a built-in regex extractor as fallback.

To enable AI-powered extraction and answers, add your API key to `.env`:

**Google Gemini (recommended — generous free tier):**
```env
LITELLM_API_KEY=AIza...         # from https://aistudio.google.com
EXTRACTION_MODEL=gemini/gemini-2.5-flash
```

**Anthropic Claude:**
```env
LITELLM_API_KEY=sk-ant-...
EXTRACTION_MODEL=claude-3-5-haiku-20241022
```

**OpenAI:**
```env
LITELLM_API_KEY=sk-...
EXTRACTION_MODEL=gpt-4o-mini
```

You can also set the key per-session directly in the UI (Graph → Configure AI) — it stays in your browser and is never sent to the server.

---

## PostgreSQL Setup

For production or multi-user deployments, use PostgreSQL instead of SQLite.

**Option A — Docker Compose with Postgres:**

Edit `docker-compose.yml` and uncomment the Postgres variant at the bottom of the file (instructions are inline).

**Option B — External database:**

```env
DATABASE_URL=postgresql://user:password@your-host:5432/context_engine
```

The app auto-creates all tables on first start. No migration tool needed for a fresh install.

---

## Documentation

Launch-facing docs:

- [Architecture](docs/architecture.md)
- [Connectors](docs/connectors.md)
- [AI Context](docs/ai-context.md)
- [Board vs Explore](docs/board-vs-explore.md)
- [MCP](docs/mcp.md)
- [Demo Walkthrough](docs/demo.md)
- [MCP examples](examples/mcp/)

Historical contract reviews remain in `docs/` for audit context, but the files
above plus this README are the current launch copy.

## Testing And Release Smoke

Run the local launch gates:

```bash
bash scripts/smoke.sh
```

This runs backend tests, Ruff, frontend tests, frontend build, and Docker
compose config validation when Docker is available.

For a faster read-only checkout and prerequisite diagnosis before setup or a
demo, run:

```bash
bash scripts/doctor.sh
```

Before a public release tag, run the full container smoke:

```bash
bash scripts/smoke.sh --docker
```

The Docker smoke builds the image, starts the app on `SMOKE_PORT` (default
`18080`), waits for `/health`, seeds the demo workspace, checks graph stats, and
verifies `/api/query` returns a non-empty `query.v1` answer. It also checks that
coming-soon or not-catalogued connector setup paths such as Zoom and Notion
cannot create fake connected state.

## Community

- [Contributing guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- GitHub issue templates cover bugs and feature requests with source,
  provenance, and connector-honesty prompts.
- The pull request template asks contributors to verify provenance,
  evidence-backed relationships, connector state, and core test gates.

---

## Deployment

### Fly.io

```bash
fly launch --name context-engine
fly secrets set LITELLM_API_KEY=your-key
fly volumes create ce_data --size 5
fly deploy
```

### Railway

1. Connect your GitHub repo
2. Set environment variables in the Railway dashboard
3. Railway auto-detects the `Dockerfile` and deploys

### Render

1. New → Web Service → connect repo
2. Runtime: Docker
3. Add environment variables
4. Add a Disk mounted at `/data` (for SQLite)

### DigitalOcean App Platform

1. Create app → choose repo
2. Select "Dockerfile" as build method
3. Add environment variables
4. Mount a volume at `/data`

### VPS / bare metal

```bash
# Install
bash scripts/setup.sh

# Run with systemd
cat > /etc/systemd/system/context-engine.service << 'EOF'
[Unit]
Description=Context Engine
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/context-engine
EnvironmentFile=/opt/context-engine/.env
ExecStart=/opt/context-engine/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now context-engine
```

### nginx reverse proxy (optional)

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## Connectors

Connector states are intentionally conservative. A provider is listed as
available only when the backend can create raw `SourceDocument` rows from it.

| Connector | Status | Auth method | Notes |
|---|---|---|---|
| **File upload** | Available | None | Drop MD, TXT, JSON, CSV, HTML, PDF |
| **AI sessions** | Available | None | Import Codex, Claude Code, OpenCode, and generic AI session text |
| **Slack** | Available | OAuth or self-hosted token | Requires Slack app with channel history scopes |
| **GitHub** | Available | Personal access token | Ingests issues and pull requests |
| **Gmail** | Available | Google OAuth | Requires Google Cloud project |
| **Google Drive** | Available | Google OAuth | Requires Google Cloud project |
| **Discord** | Coming soon | Not wired | Catalog stub only |
| **Zoom** | Coming soon | Not wired | Setup is guarded; sync is intentionally unsupported |
| **Wispr Flow** | Coming soon | Not wired | Catalog stub only |

Notion is not a catalogued connector in the current release.

For OAuth connectors (Slack, Google), set the client ID/secret in `.env` and configure the redirect URI to point to your deployment:
- Slack: `https://your-domain.com/api/connectors/slack/callback`
- Google Drive: `https://your-domain.com/api/connectors/gdrive/callback`
- Gmail: `https://your-domain.com/api/connectors/gmail/callback`

---

## CLI

```bash
# Ingest a folder of files
ctxe ingest ./docs/

# Run a natural language query
ctxe query "What is blocking the launch?"

# Open the graph explorer in terminal
ctxe graph

# Start the MCP server (for Claude Desktop / Cursor / Windsurf)
ctxe mcp
```

**MCP (Model Context Protocol) config for Claude Desktop:**

```json
{
  "mcpServers": {
    "context-engine": {
      "command": "ctxe",
      "args": ["mcp"]
    }
  }
}
```

More copy-paste MCP configs and a grounding prompt for coding agents are in
[examples/mcp](examples/mcp/).

MCP tools:

| Tool | Purpose |
|---|---|
| `query_context` | Ask the graph with the same `query.v1` facts-used trace returned by `/api/query` |
| `search_nodes` | Rank matching graph components |
| `expand_graph` | Return a component plus 1-hop relationship neighbors with evidence |
| `get_model` | Browse components in a named model |
| `list_models` | List available graph models |
| `get_status` | Count sources, models, components, and relationships |

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/api/sources` | Ingest a document |
| `POST` | `/api/sources/bulk` | Bulk ingest |
| `POST` | `/api/sources/upload` | File upload (multipart) |
| `GET` | `/api/sources` | List source documents |
| `GET` | `/api/graph` | Full knowledge graph |
| `POST` | `/api/graph/build` | Build/rebuild the graph |
| `POST` | `/api/query` | Natural language query with `top_k`, `min_confidence`, `hybrid`, and a versioned `trace` |
| `GET` | `/api/models` | List domain models |
| `GET` | `/api/connectors` | List connectors and status |
| `POST` | `/api/agents/gaps` | Run Gap Detector agent |
| `POST` | `/api/agents/relationships` | Run Relationship agent |
| `POST` | `/api/agents/context-pack` | Generate Context Pack |

Full interactive docs at **http://localhost:8000/docs**

---

## Architecture

```
┌─────────────────────────────────────────┐
│            Browser / CLI / MCP          │
└───────────────┬─────────────────────────┘
                │ HTTP / stdio
┌───────────────▼─────────────────────────┐
│         FastAPI (app/main.py)           │
│  ┌──────────┐  ┌───────────────────┐    │
│  │ REST API │  │ Static (frontend) │    │
│  └────┬─────┘  └───────────────────┘    │
│       │                                 │
│  ┌────▼────────────────────────────┐    │
│  │  Agents  │  Services  │ Connectors│  │
│  └────┬─────────────────────────────┘   │
└───────┼─────────────────────────────────┘
        │
┌───────▼──────────────────────────────────┐
│  SQLAlchemy async  →  SQLite / PostgreSQL │
│                                           │
│  SourceDocument → Model → Component      │
│                              ↕            │
│                         Relationship     │
└──────────────────────────────────────────┘
```

**Stack:**
- **Backend**: FastAPI, SQLAlchemy async, Pydantic, LiteLLM
- **Database**: SQLite (default) or PostgreSQL
- **Frontend**: React 18, Vite, TanStack Query, Tailwind CSS, Cytoscape.js
- **Extraction**: LiteLLM (any provider) or built-in regex fallback
- **MCP**: Built-in Model Context Protocol server

**Resource requirements**: 1 vCPU, 512 MB RAM minimum (SQLite). 1 vCPU, 1 GB RAM for PostgreSQL setup.
