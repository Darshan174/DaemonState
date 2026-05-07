# Context Engine

Open-source structured context infrastructure for AI systems. Turns scattered product knowledge into a living semantic graph — extract facts, explore relationships, detect gaps, and feed AI agents grounded context.

---

## Table of Contents

- [What It Is](#what-it-is)
- [Quick Start — Docker](#quick-start--docker)
- [Quick Start — Bare Metal](#quick-start--bare-metal)
- [Configuration](#configuration)
- [AI / LLM Setup](#ai--llm-setup)
- [PostgreSQL Setup](#postgresql-setup)
- [Deployment](#deployment)
- [Connectors](#connectors)
- [CLI](#cli)
- [API Reference](#api-reference)
- [Architecture](#architecture)

---

## What It Is

Context Engine ingests documents from Slack, GitHub, Gmail, Zoom, Notion, and local files. It extracts structured facts (decisions, risks, features, tasks, blockers) into a knowledge graph you can query, visualize, and feed directly to AI agents.

**Five built-in AI agents:**
1. **Ingestion Agent** — reads raw sources → clean entities
2. **Relationship Agent** — finds hidden links across sources
3. **Gap Detector** — surfaces missing owners, blocked items, isolated nodes
4. **Ask / Strategy Agent** — answers questions over the full graph with citations
5. **Context Pack Agent** — generates ready-to-paste handoff prompts for coding agents

Works fully offline with regex extraction. Plug in any LLM key to unlock AI-powered extraction and answers.

---

## Quick Start — Docker

The fastest path. No Python or Node.js required on the host.

```bash
git clone https://github.com/your-org/context-engine.git
cd context-engine

# Copy and optionally edit the config
cp .env.example .env

# Start (SQLite, single container)
docker compose up --build
```

Open **http://localhost:8000** — the UI and API are served from the same port.

To stop: `docker compose down`
To wipe data: `docker compose down -v`

---

## Quick Start — Bare Metal

Requires **Python 3.12+** and **Node.js 18+**.

```bash
git clone https://github.com/your-org/context-engine.git
cd context-engine

# One-command setup (installs deps, builds frontend)
bash scripts/setup.sh

# Start
bash scripts/start.sh
```

Open **http://localhost:8000**

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
ExecStart=/usr/local/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
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

| Connector | Auth method | Notes |
|---|---|---|
| **File upload** | None | Drop MD, TXT, JSON, CSV, HTML, PDF |
| **Slack** | OAuth or self-hosted token | Requires Slack app with `channels:history` scope |
| **GitHub** | Personal access token | Ingests issues, PRs, reviews |
| **Notion** | Integration token | Reads pages you share with the integration |
| **Zoom** | Manual token | Reads meeting transcripts |
| **Gmail** | Google OAuth | Requires Google Cloud project |
| **Google Drive** | Google OAuth | Requires Google Cloud project |

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
| `POST` | `/api/query` | Natural language query |
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
