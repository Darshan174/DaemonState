# Context Engine

Open-source structured context infrastructure for AI systems. A graph-first knowledge engine that extracts, stores, and retrieves structured facts with provenance.

## What It Is

Context Engine turns scattered product knowledge into a living semantic graph. Ingest documents, extract structured facts, and explore how they connect across product domains like Pricing, Features, Roadmap, and Decisions.

## Quick Start

```bash
# Clone
git clone <repo-url> context-engine
cd context-engine

# Install backend
pip install -e .

# Install frontend dependencies
cd frontend && npm install && cd ..

# Start (SQLite, no external dependencies)
uvicorn app.main:app --reload

# Or use Docker
docker compose up --build

# App runs on http://localhost:8000
```

## CLI

```bash
# Ingest files
ctxe ingest ./docs/

# Query
ctxe query "What is our pricing?"

# Explore graph
ctxe graph

# Start MCP server (for Claude Desktop / Cursor)
ctxe mcp
```

## Architecture

- **4 tables**: SourceDocument, Model, Component, Relationship
- **Single process**: FastAPI + SQLite (default), optional PostgreSQL
- **Extraction**: LLM-backed (LiteLLM) or regex fallback
- **Query**: Semantic search + graph traversal
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
cd frontend && npm run dev
```

## Data Model

```
SourceDocument ──► Component ◄── Model
                       │
                       ▼
                  Relationship
                  (source → target)
```

- **SourceDocument**: Raw ingested content with provenance (source type, author, URL)
- **Model**: Product domain (Pricing, Features, Roadmap, Decisions)
- **Component**: Atomic fact with name, value, confidence, status; linked to one Model and one SourceDocument
- **Relationship**: Typed edge between two Components (e.g., `depends_on`, `blocked_by`, `enables`)

## Deployment

```bash
# Docker (single container, SQLite)
docker compose up --build

# Or build image
docker build -t context-engine .
docker run -p 8000:8000 -v $(pwd)/data:/data context-engine
```

Resource requirements: 1 vCPU, 512MB RAM minimum.
