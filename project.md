# Context Engine

## What It Is

Context Engine is an open-source structured context infrastructure for AI systems. It extracts structured facts from documents, organizes them into semantic models, and surfaces relationships as a living knowledge graph.

## Core Problem

Company knowledge is scattered across Slack, Notion, Zoom transcripts, GitHub issues, meeting notes, and local documents. Traditional RAG gives you retrieval, but it doesn't answer:

- Where did this answer come from?
- Is this still true?
- What changed?
- How does pricing relate to features?

Context Engine's philosophy: facts should be structured, answers should cite sources, and relationships should be visible—not silently averaged away.

## Architecture

### Backend

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI (async Python 3.12+) |
| ORM | SQLAlchemy 2.0 |
| Database | SQLite (default), optional PostgreSQL + pgvector |
| LLM Gateway | LiteLLM (OpenAI, Anthropic, etc.) |
| Embeddings | LiteLLM or local HashingEmbedder (tests/offline) |
| Build | Hatchling |
| CLI | ctxe |

### Frontend

| Layer | Technology |
|-------|-----------|
| Framework | React 18 |
| Build Tool | Vite |
| Styling | Tailwind CSS |
| Graph Viz | Cytoscape.js |
| Routing | React Router DOM v6 |

### Infrastructure

- Single Docker container (Python 3.12 slim + pre-built frontend)
- SQLite default, PostgreSQL optional
- No Redis, no Celery, no worker processes
- Memory footprint: ~150MB RAM idle

## Data Model

4 tables:

- **SourceDocument** — Raw ingested content with metadata
- **Model** — Product domain (Pricing, Features, Roadmap, Decisions)
- **Component** — Atomic structured fact with confidence, status, embedding
- **Relationship** — Typed edge between components

## Processing Pipeline

1. Ingest document via API or CLI
2. Extract structured facts (LLM or regex fallback)
3. Create/update Model and Component records
4. Batch embed new components
5. Create Relationship edges from extracted links
6. Query via semantic search + graph traversal

## Product Workflows

3 frontend views:

- **Graph Explorer** — Visual knowledge graph with models, components, and relationships
- **Ask (Query)** — Natural language query with cited components and sources
- **Source Manager** — Upload, browse, and inspect source documents

## Operations

```bash
# One-command start
ctxe serve

# Ingest
ctxe ingest ./docs/

# Query
ctxe query "What is our pricing?"

# MCP server
ctxe mcp
```

## Design Philosophy

- **Graph-first** — Relationships are first-class, not afterthoughts
- **Self-host first** — Single container, zero external dependencies by default
- **Minimal but impactful** — 4 tables, 3 views, 1 process
- **Source-backed** — Every fact links to its origin document
- **MCP-native** — Built-in Model Context Protocol server for AI assistants

## Current Status

Stable:
- Docker-based self-hosting
- Local document import
- Source-backed query API
- Knowledge graph visualization
- MCP server mode

## Repository Layout

```
app/
  api/          FastAPI routes (sources, graph, query)
  cli/          CLI commands (ingest, query, graph, mcp)
  models.py     4 SQLAlchemy models
  processing/   Extraction, embeddings
  services/     Ingest, query
  mcp/          MCP server implementation
frontend/       React 3-view app
tests/          Backend tests
```
