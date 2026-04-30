# Context Engine

Open-source structured context infrastructure for AI systems. A graph-first knowledge engine that extracts, stores, and retrieves structured facts with provenance.

## Quick Start

```bash
# Install
pip install -e .

# Start (SQLite, no external dependencies)
uvicorn app.main:app --reload

# Ingest files
ctxe ingest ./docs/

# Query
ctxe query "What is our pricing?"

# Start MCP server (for Claude Desktop / Cursor)
ctxe mcp
```

## Docker

```bash
docker compose up --build
# App runs on http://localhost:8000
```

## Architecture

- **4 tables**: SourceDocument, Model, Component, Relationship
- **Single process**: FastAPI + SQLite (default), optional PostgreSQL
- **Extraction**: LLM-backed (LiteLLM) or regex fallback
- **Query**: Semantic search + graph traversal + multi-factor scoring
- **MCP**: Built-in Model Context Protocol server

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |
| POST | /api/sources | Ingest a document |
| POST | /api/sources/bulk | Bulk ingest |
| POST | /api/sources/upload | File upload |
| GET | /api/sources | List sources |
| GET | /api/graph | Knowledge graph |
| POST | /api/query | Natural language query |
| GET | /api/briefing | Recent changes + review items |
| PATCH | /api/components/:id | Update component status |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| DATABASE_URL | sqlite+aiosqlite:///data/context.db | Database connection |
| EXTRACTION_MODEL | (none) | LiteLLM model for extraction |
| EMBEDDING_MODEL | (none) | LiteLLM model for embeddings |
| LITELLM_API_KEY | (none) | API key for LLM providers |

## Frontend

3 views: Graph Explorer, Query Interface, Source Manager.

```bash
cd frontend && npm install && npm run dev
```
