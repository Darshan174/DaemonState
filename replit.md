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
  api/          FastAPI routes (sources, graph, query, repo)
  cli/          CLI commands (ingest, query, graph, mcp, serve)
  models.py     4 SQLAlchemy models (SourceDocument, Model, Component, Relationship)
  processing/   Extraction, embeddings
  services/     Ingest, query services
  mcp/          MCP server implementation
  config.py     Settings via pydantic-settings (.env + env vars)
  database.py   SQLAlchemy async engine setup
frontend/       React 3-view app (Graph Explorer, Ask, Source Manager)
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

## Database Notes

- The `DATABASE_URL` Replit secret is a sync PostgreSQL URL; `app/database.py` automatically converts it to `postgresql+asyncpg://` for async SQLAlchemy
- Tables are auto-created on startup via `Base.metadata.create_all`

## Frontend Views

1. **Landing** — Marketing page at `/`
2. **Dashboard** — Main app workspace
3. **Graph Explorer** — Visual knowledge graph with Cytoscape.js
4. **Ask (Query)** — Natural language query with cited components
5. **Source Manager** — Upload, browse, inspect source documents
