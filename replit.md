# Context Engine

## Overview

Context Engine is an open-source structured context infrastructure for AI systems. It extracts structured facts from documents, organizes them into semantic models, and surfaces relationships as a living knowledge graph.

## Architecture

- **Backend**: FastAPI (async Python 3.12+) with SQLAlchemy 2.0, served by Uvicorn on port 8000
- **Frontend**: React 18 + Vite + Tailwind CSS, served on port 5000
- **Database**: PostgreSQL (Replit managed) via asyncpg driver
- **LLM**: LiteLLM gateway (OpenAI, Anthropic, etc.) — optional

## Project Structure

```
app/
  api/          FastAPI routes (sources, graph, query, repo, connectors)
  agents/       GraphBuilderAgent (2-phase: ingest + cross-doc relationship inference)
  cli/          CLI commands (ingest, query, graph, mcp, serve)
  extract/      basic.py — regex extractor with temporal detection (used for Slack sync)
  models.py     4 SQLAlchemy models (SourceDocument, Model, Component, Relationship)
  processing/   extractor.py (LLM/regex unified), embedder
  services/     IngestionService (extract + embed + upsert), QueryService
  sync/         ai_session.py, slack.py
  mcp/          MCP server implementation
  config.py     Settings via pydantic-settings (.env + env vars)
  database.py   SQLAlchemy async engine setup
frontend/       React app (Graph Explorer, Ask, Source Manager, Connectors)
tests/          Backend pytest tests
```

## Workflows

- **Start application**: `cd frontend && npm run dev` — Vite dev server on port 5000 (webview)
- **Backend API**: `uvicorn app.main:app --host localhost --port 8000 --reload` — FastAPI on port 8000 (console)

## Key Configuration

- Database URL: Replit PostgreSQL injected via `DATABASE_URL` env var (auto-converted to asyncpg async URL)
- `.env` file for local development overrides (SQLite fallback)
- Optional: `LITELLM_API_KEY`, `EXTRACTION_MODEL`, `EMBEDDING_MODEL` for AI features

## Deployment

- **Target**: autoscale
- **Build**: `cd frontend && npm install && npm run build`
- **Run**: `uvicorn app.main:app --host 0.0.0.0 --port 5000` (serves pre-built frontend as static files)

## Self-Hosting

The project ships with everything needed to self-host:

- `Dockerfile` — Multi-stage build: Node 20 builds the frontend, Python 3.12 slim serves backend + static files. Single container, no nginx needed.
- `docker-compose.yml` — SQLite by default (zero external deps). Uncomment the Postgres variant at the bottom for production.
- `.env.example` — Full variable reference with comments. Copy to `.env` before starting.
- `.dockerignore` — Keeps image lean (~200 MB).
- `scripts/setup.sh` — One-command bare-metal setup (installs Python deps + builds frontend).
- `scripts/start.sh` — Production start (`uvicorn` with configurable PORT + WORKERS env vars).
- `scripts/dev.sh` — Dev mode: starts both backend (port 8000, --reload) and frontend (port 5000) concurrently.

### Self-hosted Slack redirect URI
`Connectors.jsx` uses `window.location.origin` to build the default Slack redirect URI so it works on any hostname/port automatically.

## Database Notes

- The `DATABASE_URL` Replit secret is a sync PostgreSQL URL; `app/database.py` automatically converts it to `postgresql+asyncpg://` for async SQLAlchemy
- Tables are auto-created on startup via `Base.metadata.create_all`
- `temporal` column added to `components` via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in `main.py` lifespan (safe to run on existing DBs)
- All datetime writes use `datetime.utcnow()` (naive) — DB columns are `TIMESTAMP WITHOUT TIME ZONE`

## Component Model — Temporal Dimension

Each `Component` has a `temporal` field (`VARCHAR(20) DEFAULT 'unknown'`):

| Value | Meaning | Node color |
|-------|---------|------------|
| `current` | Present state — what is true/active right now | `#0ea5e9` (sky blue) |
| `past` | Completed work, historical decisions | `#94a3b8` (slate) |
| `future` | Planned/roadmap items | `#a78bfa` (violet) |
| `unknown` | Cannot be determined from context | `#64748b` (dark slate) |

In **GraphView** node styling: `bgColor = temporal color`, `borderColor = model color`. The toolbar has a temporal filter dropdown ("All time / Current / Future / Past / Unknown"). Side panel shows a coloured temporal pill, a Timeline row, and a legend.

## Extraction Pipeline

### AI Session Ingest (`POST /api/connectors/ai-session/ingest`)
1. `app/sync/ai_session.py` — parses and persists 1 `SourceDocument`
2. `app/services/ingest.py` `IngestionService.process_document()` — calls `Extractor`, upserts `Component`s with `temporal`, embeds
3. LLM extraction uses `LITELLM_API_KEY` + `EXTRACTION_MODEL`; falls back to regex in `extractor.py._regex_extract`

### Slack Sync
- `app/sync/slack.py` syncs messages → `SourceDocument`s
- `app/extract/basic.py` `extract_from_source_documents()` runs regex patterns with `_infer_temporal` to classify components

### Graph Build Agent (`POST /api/graph/build`)
- `app/agents/graph_builder.py` `GraphBuilderAgent`:
  - **Phase 1**: batch `IngestionService.process_document` on all unprocessed docs
  - **Phase 2**: cross-doc relationship inference via LLM (if enabled)
- Status polling: `GET /api/graph/agent-status`

## Frontend Views

1. **Landing** — Marketing page at `/`
2. **Dashboard** — Main app workspace
3. **Graph Explorer** — Cytoscape.js graph with temporal colors, 4 filter dropdowns (model / source / status / time), "Build Graph" button, side panel with temporal badge + legend
4. **Ask (Query)** — Natural language query with cited components
5. **Source Manager** — Upload, browse, inspect source documents
6. **Connectors** — Manage data source integrations

## Connectors

Full connector catalog (7 types):

| Type | Category | Notes |
|------|----------|-------|
| `slack` | Communication | OAuth; syncs channels/DMs/threads |
| `zoom` | Communication | Official API |
| `gdrive` | Documents | Google Drive |
| `gmail` | Email | Gmail |
| `codex` | AI Session | Paste/import OpenAI Codex session exports |
| `claude` | AI Session | Paste/import Claude conversation exports |
| `opencode` | AI Session | Paste/import OpenCode session exports |

AI session connectors accept pasted content (JSON OpenAI export format, `Human:/Assistant:` markdown, or plain text). Endpoint: `POST /api/connectors/ai-session/ingest`.

### Key files
- `app/api/connectors.py` — router, `CONNECTOR_CATALOG`, `AI_SESSION_CONNECTORS`, ingest endpoint (uses `IngestionService`)
- `app/sync/ai_session.py` — session parser + ingestor
- `app/sync/slack.py` — Slack OAuth sync pipeline
- `frontend/src/pages/Connectors.jsx` — UI cards, icons, AI session form
- `frontend/src/api/hooks.js` — `CONNECTOR_CATALOG`, `useConnectors`, `useIngestAISession`

### SourceDocument model (no connector_id)
Fields: `id`, `source_type`, `external_id`, `content`, `author`, `source_url`, `metadata_json` (Text, use `json.dumps`), `ingested_at`, `processed_at`. Dedup by `external_id` only.

## Connector Icons
- Gmail: multicolor M on white badge (`color="#ffffff"`, `boxShadow: "inset 0 0 0 1px #e5e7eb"`)
- Google Drive: white badge, color triangle SVG
- OpenCode: terminal window SVG
- `ConnectorIconBadge` uses `inset` box-shadow border when `color === "#ffffff"`
