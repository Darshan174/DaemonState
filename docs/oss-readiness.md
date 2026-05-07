# OSS Readiness Review

Last updated: 2026-05-01
Reviewed: 2026-05-01 by Xiaomi MiMo V2.5 Pro

## Score

Current OSS readiness: 8/10

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

- `pytest -q`: 107 passed
- `npm run build`: passed

## Remaining Launch Blockers

### P0

- No `LICENSE` file. Without a license, this is not safely reusable as OSS.

### P1

- **Slack availability is misleading.** Backend sets `"availability": "available"` but `"supported": False` for Slack. The connect endpoint returns 400, but the UI shows Slack as "available" rather than "coming_soon". Discord correctly uses `"availability": "coming_soon"` with `"supported": False`. Slack should use the same pattern to avoid user confusion.
- **Frontend hooks for unavailable provider setup paths.** `hooks.js` defines `useConnectNotion` (POST `/connectors/notion/connect`), `useConnectZoom` (POST `/connectors/zoom/connect`), `useConnectGitHub` (POST `/connectors/github/connect`), and `useSaveSlackOAuthSettings` (POST `/connectors/slack/oauth-settings`). Zoom is a catalogued coming-soon connector and returns 400 through the generic connect route. Notion and GitHub are not catalogued backend connector types, and Slack OAuth settings has no backend route. If these hooks are reachable from the UI, they will fail until provider setup paths are implemented or hidden.

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

### Backend Catalog (app/api/connectors.py lines 19-124)

| Type | availability | supported | Notes |
|------|-------------|-----------|-------|
| slack | available | False | Misleading: shows "available" but connect returns 400 |
| discord | coming_soon | False | Honest: shows as coming soon |
| ai_context | available | True | Working: import endpoint tested |
| local | available | True | Working: sources upload |
| zoom | coming_soon | False | Honest: shows as coming soon |
| gdrive | coming_soon | False | Honest: shows as coming soon |
| gmail | coming_soon | False | Honest: shows as coming soon |
| wispr_flow | coming_soon | False | Honest: shows as coming soon |

### Frontend Catalog (hooks.js lines 73-154)

| Type | availability | In Backend? |
|------|-------------|-------------|
| slack | available | Yes |
| discord | coming_soon | Yes |
| ai_context | available | Yes |
| local | available | Yes |
| zoom | coming_soon | Yes |
| gdrive | coming_soon | Yes |
| gmail | coming_soon | Yes |
| wispr_flow | coming_soon | Yes |

### Frontend Hooks Without Working Backend Paths

| Hook | Endpoint | Status |
|------|----------|--------|
| useConnectNotion | POST /connectors/notion/connect | Generic connect route returns 404 unknown connector type |
| useConnectZoom | POST /connectors/zoom/connect | Catalogued coming-soon connector; generic connect route returns 400 |
| useConnectGitHub | POST /connectors/github/connect | Generic connect route returns 404 unknown connector type |
| useSaveSlackOAuthSettings | POST /connectors/slack/oauth-settings | No backend route |

### Implemented

- Local source upload through Sources.
- AI Context import through `/api/connectors/ai-context/import`.
- Connector catalog/status/sync-job contract.
- Slack connect rejection (returns 400 because `supported: False`).

### Not Implemented Yet

- Slack OAuth and Slack sync.
- Discord sync.
- Gmail OAuth and sync.
- Zoom, Google Drive, Gmail, and Wispr provider backends (catalog entries exist, no sync logic).
- Notion and GitHub catalog entries/provider backends (hooks exist in frontend, backend returns unknown connector type).
- Zoom sync/provider backend (catalogued as coming soon; connect route exists only as an unsupported stub).
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
