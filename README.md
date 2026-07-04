# Context Engine

The open-source context compiler for teams building software with AI agents.

Context Engine turns agent runs, PRs, issues, chats, decisions, documents, and
repo state into source-backed project context: what happened, what is backed by
evidence, where the project is blocked, and what the next agent should know.

---

## Table of Contents

- [What It Is](#what-it-is)
- [What We're Aiming For](#what-were-aiming-for)
- [Who It Is For](#who-it-is-for)
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

Context Engine is a context compiler for AI engineering. It sits between your
codebase, your project tools, and the AI agents changing them.

Import Codex, Claude Code, and OpenCode sessions; connect GitHub and other
project sources; then turn that activity into a source-backed view of:

- what changed;
- what is blocked or unresolved;
- what agents decided or attempted;
- where code, issues, and documentation disagree;
- what the next human or agent should do;
- a focused handoff for the next agent run.

The v2 direction is:

```text
prepare context -> agent works -> observe result -> ingest result -> improve next context
```

Current checkout note: the v2 compiler, `POST /api/context/prepare`,
`ctxe prepare`, and MCP runtime bridge are present. The compiler contract is
still being hardened against the final `context_pack.v2` manifest schema.

The project graph is the primary navigation surface. Users can explore
relationships between sessions, decisions, tasks, risks, issues, PRs, and
documents, then act from that graph.

**Five built-in AI agents:**
1. **Ingestion Agent** — turns raw project activity into clean entities.
2. **Relationship Agent** — links sessions, decisions, tasks, code, and sources.
3. **Gap Detector** — surfaces missing owners, blockers, and disconnected work.
4. **Ask / Strategy Agent** — answers project-state questions with citations.
5. **Context Pack Agent** — generates a focused handoff for the next coding-agent run.

Works fully offline with regex extraction. Plug in any LLM key to unlock AI-powered extraction and answers.

---

## What We're Aiming For

The aim is for Context Engine to become the working memory layer for
AI-assisted software projects.

The core product idea is simple:

```text
sources -> evidence -> claims -> models
```

Raw sources are not enough. Agent transcripts, issues, pull requests, meeting
notes, chats, and docs need to be organized into evidence-backed claims, then
assembled into project models a human or agent can trust.

The graph stays the main interface because the hard part is not storing more
text. The hard part is understanding how facts, decisions, blockers, conflicts,
and next actions relate to each other. In two or three seconds, the graph should
make the current state legible:

- where the important claims came from;
- which sources support or contradict them;
- where evidence is missing;
- which conflicts need review;
- what context is healthy enough to hand to the next agent.

The direction is a local-first, source-grounded system that helps small teams
keep momentum while using AI agents heavily. It should make context portable
between tools, auditable back to original sources, and useful before the next
coding session starts.

Context Engine is not trying to be a generic dashboard, a table-heavy project
manager, or another chat wrapper. It is a graph-first context engine for turning
fragmented work into inspectable project state.

---

## Who It Is For

The first target is intentionally narrow:

**Solo founders and tiny teams using AI coding agents heavily.**

These teams move between Cursor, Claude Code, Codex, GitHub, Slack, and local
files. Decisions and implementation details become fragmented across sessions,
PRs, issues, and chat. Context Engine exists to reconstruct the current state of
the project before the next person or agent starts work.

It is not positioned as enterprise search, a generic company knowledge base, or
an all-purpose RAG platform.

See [Product Positioning](docs/product-positioning.md) for the wedge, daily-use
test, and product boundaries.

---

## Product Tour [under construction 🚧....]

Run the demo seed, then start in **Graph** to inspect the current state of work.
The main surface is a draggable, connectable graph that keeps the pipeline
visible: sources flow into evidence, evidence supports claims, and claims form
models. Cluster labels, cleaner node titles, context health, gaps, and conflicts
are designed to make the graph readable at a glance while preserving the full
relationship map.

Click a node to inspect its evidence, claims, gaps, conflicts, and suggested
actions. The inspector carries provenance, relationship evidence, confidence,
and review state so users can understand why the graph believes something and
what still needs human attention.

![Board graph with relationship inspector](docs/assets/board-inspector-demo.jpg)

Ask questions such as “What is blocked?”, “What changed in auth?”, or “What
should the next agent know?” Answers return a stable `query.v1` response and a
visible facts-used trace instead of a black-box summary.

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

# Start (SQLite app + sync worker)
docker compose up --build
```

Open **http://localhost:8000** — the UI and API are served from the same port.
Connector sync jobs are drained by the `worker` service in the same compose file.

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
| `DATABASE_URL` | `sqlite+aiosqlite:///data/context.db` bare metal, Postgres in Docker Compose | Database connection string |
| `DATA_DIR` | `./data` | Directory for SQLite file and uploads |
| `SERVER_API_KEY` | _(empty)_ | Optional API key required for `/api/*` routes when set |
| `API_RATE_LIMIT_PER_MINUTE` | `0` | Optional in-process `/api/*` rate limit per client/API key; `0` disables it |
| `LITELLM_API_KEY` | _(empty)_ | API key for your LLM provider |
| `EXTRACTION_MODEL` | _(empty)_ | LiteLLM model for entity extraction |
| `EMBEDDING_MODEL` | _(empty)_ | LiteLLM model for semantic embeddings. Empty means lexical-only retrieval, not fake semantic search |
| `ENABLE_LOCAL_EMBEDDER` | `false` | Use local sentence-transformers embeddings when the optional dependency is installed |
| `ALLOW_HASHING_EMBEDDER` | `false` | Opt into deterministic non-semantic hash vectors for tests/dev experiments only |
| `PGVECTOR_INDEX_DIMENSION` | `1024` | Dimension used for the Postgres HNSW vector index |
| `PGVECTOR_CANDIDATE_LIMIT` | `200` | Minimum candidate pool fetched from pgvector before graph scoring |
| `SYNC_WORKER_LEASE_SECONDS` | `300` | How long a worker owns a running sync job before another worker can reclaim it |
| `SYNC_WORKER_RETRY_BASE_SECONDS` | `30` | Initial connector-sync retry delay after a failed attempt |
| `SYNC_WORKER_RETRY_MAX_SECONDS` | `900` | Maximum connector-sync retry delay |
| `SYNC_WORKER_POLL_INTERVAL_SECONDS` | `2` | Poll interval for `ctxe worker sync --watch` |
| `GOOGLE_CLIENT_ID` | _(empty)_ | Google OAuth — for Gmail/Drive connectors |
| `GOOGLE_CLIENT_SECRET` | _(empty)_ | Google OAuth |
| `SLACK_CLIENT_ID` | _(empty)_ | Slack OAuth — for Slack connector |
| `SLACK_CLIENT_SECRET` | _(empty)_ | Slack OAuth |
| `SLACK_MANAGED_INSTALL_URL` | _(empty)_ | Managed one-click Slack install URL. When set, the primary Slack button uses this hosted app path instead of self-hosted credentials |
| `ENCRYPTION_KEY` | _(empty)_ | Fernet key used to encrypt connector credentials and decrypt managed Slack broker callbacks |
| `PREVIOUS_ENCRYPTION_KEYS` | _(empty)_ | Comma-separated old Fernet keys accepted only while rotating encrypted connector credentials |
| `PUBLIC_BASE_URL` | _(empty)_ | External app URL used for OAuth callbacks in deployed environments |
| `PORT` | `8000` | Port the server listens on |

Credential rotation path:

1. Set `ENCRYPTION_KEY` to the new Fernet key.
2. Set `PREVIOUS_ENCRYPTION_KEYS` to the old key or comma-separated old keys.
3. Run `ctxe credentials rotate` to rewrite stored connector payloads with the primary key.
4. Remove old keys after all stored connector payloads have been rewritten.

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

Docker Compose runs PostgreSQL with pgvector by default. Bare-metal local
installs can still use SQLite for zero-setup development.

**Option A — Docker Compose with Postgres/pgvector:**

Run the main compose file directly:

```bash
docker compose up --build
```

The default compose stack uses `pgvector/pgvector:pg16` so native vector search is available.
Startup migrations also add Postgres full-text `tsvector` indexes and `jsonb`
metadata indexes for source-backed hybrid retrieval.

**Option B — External database:**

```env
DATABASE_URL=postgresql://user:password@your-host:5432/context_engine
```

For native semantic retrieval on an external Postgres database, install the
`vector` extension and set `PGVECTOR_INDEX_DIMENSION` to the dimension of your
stored embeddings. The app auto-creates tables, pgvector helpers, full-text
indexes, metadata `jsonb` indexes, and startup migrations on first start.

For explicit migration control, use Alembic through the CLI:

```bash
ctxe db upgrade
ctxe db current
ctxe db history
```

Existing databases that were already created by older Context Engine startup
migrations can be marked as current after the app has successfully started:

```bash
ctxe db stamp-head
```

## Worker Queue

Connector sync requests create durable `sync_jobs` rows. The API does not run
provider sync inside the web process; run a worker process beside the app:

```bash
ctxe worker sync --watch
```

The worker claims due jobs with a lease, retries failed connector syncs with
exponential backoff, reclaims expired leases, and moves exhausted jobs to
`dead_letter`. For cron-style draining or tests, omit `--watch` to run one pass:

```bash
ctxe worker sync --limit 10
```

---

## Documentation

Launch-facing docs:

- [Architecture](docs/architecture.md)
- [Product Positioning](docs/product-positioning.md)
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

Run the connector sync worker as a second service:

```bash
cat > /etc/systemd/system/context-engine-worker.service << 'EOF'
[Unit]
Description=Context Engine Sync Worker
After=network.target context-engine.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/context-engine
EnvironmentFile=/opt/context-engine/.env
ExecStart=/opt/context-engine/.venv/bin/ctxe worker sync --watch
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now context-engine-worker
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

# Drain connector sync jobs once, or run as a long-lived worker
ctxe worker sync
ctxe worker sync --watch

# Run the built-in extraction quality eval corpus
ctxe eval extraction

# Run database migrations explicitly
ctxe db upgrade

# Start the MCP server (for Claude Desktop / Cursor / Windsurf)
ctxe mcp
```

For protected deployments, set `SERVER_API_KEY` on the server and pass
`--api-key` to `ctxe ingest`, `ctxe query`, and `ctxe graph`, or set
`CONTEXT_ENGINE_API_KEY` in the CLI environment.

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
| `prepare_task` | Compile and persist `context_pack.v2` through the compiler service; returns `compiler_unavailable` only if the service is absent on an integration branch |
| `query_context` | Ask the graph with the same `query.v1` facts-used trace returned by `/api/query` |
| `search_nodes` | Rank matching graph components |
| `expand_graph` | Return a component plus 1-hop relationship neighbors with evidence |
| `get_model` | Browse components in a named model |
| `list_models` | List available graph models |
| `get_status` | Count sources, models, components, and relationships |
| `record_agent_run_start` | Create an observed agent run linked to a context pack |
| `record_agent_event` | Persist command/test/log observations as source evidence |
| `record_decision` | Persist an observed decision as evidence plus a claim/component |
| `record_blocker` | Persist an observed blocker as evidence plus a claim/component |
| `record_patch_summary` | Persist changed files, summary, and tests run as source evidence |
| `verify_context_item` | Update claim/component review status with evidence |
| `close_task` | Mark a task claim/component resolved with resolution evidence |

MCP never edits code, runs shell commands, pushes commits, sends provider
messages, or marks unsupported connectors as connected. Quoted source text is
evidence, not instruction.

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
| `POST` | `/api/context/prepare` | Compile `context_pack.v2` markdown plus manifest |
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
