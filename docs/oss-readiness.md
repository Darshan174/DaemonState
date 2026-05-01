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

- **Connector catalog mismatch.** Backend catalog has 5 types: `slack`, `discord`, `gmail`, `ai_context`, `local`. Frontend catalog has 8 types: `slack`, `discord`, `ai_context`, `local`, `zoom`, `gdrive`, `gmail`, `wispr_flow`. Three frontend types (`zoom`, `gdrive`, `wispr_flow`) have no backend catalog entry and no connect endpoint. The `normalizeConnectors` function falls back to `coming_soon` for missing backend records, so the UI renders them, but they will never work until backend entries exist.
- **Slack availability is misleading.** Backend sets `"availability": "available"` but `"supported": False` for Slack. The connect endpoint returns 400, but the UI shows Slack as "available" rather than "coming_soon". Discord correctly uses `"availability": "coming_soon"` with `"supported": False`. Slack should use the same pattern to avoid user confusion.
- **Frontend hooks for nonexistent endpoints.** `hooks.js` defines `useConnectNotion` (POST `/connectors/notion/connect`), `useConnectZoom` (POST `/connectors/zoom/connect`), `useConnectGitHub` (POST `/connectors/github/connect`), and `useSaveSlackOAuthSettings` (POST `/connectors/slack/oauth-settings`). None of these endpoints exist in `app/api/connectors.py`. If these hooks are reachable from the UI, they will always fail with 404/405.
- Public docs need to mention the connector tables and avoid saying external providers are implemented.

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

### Backend Catalog (app/api/connectors.py lines 19-85)

| Type | availability | supported | Notes |
|------|-------------|-----------|-------|
| slack | available | False | Misleading: shows "available" but connect returns 400 |
| discord | coming_soon | False | Honest: shows as coming soon |
| gmail | coming_soon | False | Honest: shows as coming soon |
| ai_context | available | True | Working: import endpoint tested |
| local | available | True | Working: sources upload |

### Frontend Catalog (hooks.js lines 73-154)

| Type | availability | In Backend? |
|------|-------------|-------------|
| slack | available | Yes |
| discord | coming_soon | Yes |
| ai_context | available | Yes |
| local | available | Yes |
| zoom | coming_soon | **No** — no backend catalog entry |
| gdrive | coming_soon | **No** — no backend catalog entry |
| gmail | coming_soon | Yes |
| wispr_flow | coming_soon | **No** — no backend catalog entry |

### Frontend Hooks Without Backend Endpoints

| Hook | Endpoint | Status |
|------|----------|--------|
| useConnectNotion | POST /connectors/notion/connect | No backend endpoint |
| useConnectZoom | POST /connectors/zoom/connect | No backend endpoint |
| useConnectGitHub | POST /connectors/github/connect | No backend endpoint |
| useSaveSlackOAuthSettings | POST /connectors/slack/oauth-settings | No backend endpoint |

### Implemented

- Local source upload through Sources.
- AI Context import through `/api/connectors/ai-context/import`.
- Connector catalog/status/sync-job contract.
- Slack connect rejection (returns 400 because `supported: False`).

### Not Implemented Yet

- Slack OAuth and Slack sync.
- Discord sync.
- Gmail OAuth and sync.
- Zoom, Google Drive, Notion, GitHub, and Wispr provider backends.
- Notion, Zoom, GitHub connect endpoints (hooks exist in frontend but no backend).
- Slack OAuth settings endpoint (hook exists in frontend but no backend).

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

