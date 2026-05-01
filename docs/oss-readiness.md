# OSS Readiness Review

Last updated: 2026-05-01

## Score

Current OSS readiness: 7/10

## What Is Working

- FastAPI backend runs as a single process with SQLite by default.
- Source ingestion, extraction, graph reads, query, connectors, and AI-context import have tests.
- Knowledge graph responses include source provenance and proposed future context.
- SQLite startup migration covers the new relationship confidence/evidence fields.
- Connector API now avoids marking Slack as connected when no tested sync path exists.
- AI-context subtype documents are counted together in connector processing summary.
- Frontend build passes.

## Verification

```bash
pytest -q
cd frontend && npm run build
```

Latest verified result:

- `pytest -q`: 99 passed
- `npm run build`: passed

## Remaining Launch Blockers

### P0

- No `LICENSE` file. Without a license, this is not safely reusable as OSS.
- No CI workflow that runs backend tests and frontend build on pull requests.

### P1

- Connector catalog must stay aligned across backend and frontend. Current frontend now includes the implemented `ai_context`, `local`, and `discord` types, and marks Zoom as coming soon, but this needs ongoing review whenever connector types change.
- Public docs need to mention the connector tables and avoid saying external providers are implemented.
- Frontend still has hook functions for future providers such as Notion, Zoom, GitHub, and Slack OAuth settings. Those should remain unreachable or disabled until backend support exists.

### P2

- `SourceManager.jsx` still uses raw `fetch` instead of the shared API client.
- MCP semantic search loads active components into memory and will need a scalable retrieval path later.
- Extractor silently falls back to regex on LLM errors; logging would improve operator visibility.
- Docker build should be tested from a clean checkout before public launch.

## Current Data Model

Six SQLAlchemy tables are currently defined:

- `source_documents`
- `models`
- `components`
- `relationships`
- `connectors`
- `sync_jobs`

## Connector Status

Implemented:

- Local source upload through Sources.
- AI Context import through `/api/connectors/ai-context/import`.
- Connector catalog/status/sync-job contract.

Not implemented yet:

- Slack OAuth and Slack sync.
- Discord sync.
- Gmail OAuth and sync.
- Zoom, Google Drive, Notion, GitHub, and Wispr provider backends.

## Evidence Files

- `app/api/connectors.py`
- `app/api/graph.py`
- `app/migrations.py`
- `app/models.py`
- `frontend/src/api/hooks.js`
- `tests/test_connectors.py`
- `tests/test_graph_api.py`
- `tests/test_migrations.py`
- `docs/connectors-graph-contract.md`

