# OSS Readiness Review

Last updated: 2026-06-18
Reviewed: 2026-05-01 by Xiaomi MiMo V2.5 Pro; refreshed 2026-06-18 after connector honesty, demo seed, Docker smoke, and OSS-basics updates.

## Score

Current OSS readiness: 9.1/10

## What Is Working

- FastAPI backend runs as a single process with SQLite by default.
- Source ingestion, extraction, graph reads, query, connectors, and AI-context import have tests.
- Knowledge graph responses include source provenance and proposed future context.
- SQLite startup migration covers the new relationship confidence/evidence fields.
- SQLite/SQLAlchemy schemas now create compound indexes for source-document
  sync lookup, pending extraction, component filtering, and relationship
  traversal.
- Connector API now avoids marking Slack as connected when no tested sync path exists.
- AI-context subtype documents are counted together in connector processing summary.
- Demo seed endpoint creates source-backed GitHub, Slack, Gmail, Google Drive, and Codex documents without faking connector auth state.
- Frontend smoke coverage now guards the onboarding demo copy, landing-page
  launch-source claims, agent-page source claims, and seed action.
- Launch-facing docs now cover architecture, connectors, AI Context, Board vs
  Explore, MCP, and the seeded demo walkthrough.
- MCP examples now include copy-paste installed/local checkout configs and an
  agent grounding prompt tied to `query_context` and `trace.facts_used`.
- README now includes real screenshots captured from the seeded Board inspector
  and Ask facts-used trace.
- Board default now opens at a card-readable viewport when a full fit would
  collapse source cards into unlabeled dots; the minimap still provides whole
  graph orientation and the explicit fit button preserves overview behavior.
- Query returns a deterministic source-backed answer summary when no AI answer model is configured.
- Query status/confidence filtering now runs in SQL before semantic/lexical ranking.
- Source Manager now uses the shared frontend API client instead of raw fetch
  calls, and separates unsupported/historical provider records from supported
  document imports.
- Landing/mock frontend copy now uses launch-available source families only,
  and unsupported Notion/Zoom manual-connect UI paths are removed.
- Frontend smoke coverage now guards connector honesty: coming-soon providers
  stay disabled and launch connectors expose only backend-backed actions.
- Community health files now include a security policy, bug and feature issue
  forms, and a PR template tied to provenance, evidence, and connector honesty.
- `scripts/smoke.sh` now gives maintainers a repeatable local launch gate and
  optional Docker API smoke before release tags.
- `scripts/doctor.sh` gives first-time users and contributors a read-only
  checkout/prerequisite diagnosis for Docker and bare-metal setup before they
  commit to setup, demo, or smoke commands.
- Bare-metal setup now creates `.venv`, validates Python versions with
  `sys.version_info`, uses `npm ci`, and the start/dev/smoke scripts reuse that
  interpreter automatically.
- CLI ingest now carries `--sync` through to both single-source and bulk-source
  HTTP paths, and the bulk source API processes synchronously when requested.
- README quick-start clone commands use the real GitHub remote with an explicit
  `context-engine` checkout directory, and docs coverage guards against
  placeholder clone URLs.
- Package metadata now advertises the MIT license, repository/issues URLs,
  relevant keywords, and PyPI classifiers; the package metadata dry run passes,
  and Docker copies `LICENSE` before `pip install .` prepares metadata.
- CI runs backend tests, Ruff, frontend tests, frontend build, Docker image build,
  and smoke-compose config validation.
- Connector tests now describe Slack as OAuth/setup-backed and direct-connect
  rejected, instead of carrying stale unsupported-connector wording.
- Frontend build passes.

## Verification

```bash
pytest -q
cd frontend && npm run build
```

Latest verified result:

- `python3 -m pytest tests/ -q`: 326 passed
- `python3 -m pytest tests/test_docs.py -q`: 6 passed
- `python3 -m pytest tests/test_graph_api.py -q`: 29 passed
- `python3 -m pytest tests/test_migrations.py -q`: 8 passed
- `bash -n scripts/doctor.sh`: passed
- Shell script syntax check for setup/start/dev/doctor/smoke scripts: passed
- `bash scripts/doctor.sh --bare-metal`: passed with one expected checkout
  warning because `.venv` is not present in this workspace.
- `ruff check app tests`: passed
- `npm test`: 29 passed
- `npm run build`: passed
- `python3 -m pip install . --no-deps --dry-run`: passed
- `bash scripts/smoke.sh`: passed
- `bash scripts/smoke.sh --docker`: passed
- `docker compose config --quiet`: passed
- `docker compose -f docker-compose.smoke.yml -p context-engine-smoke config --quiet`: passed
- Docker build/start/health smoke on port 18080: passed
- Container API smoke: `/api/seed-demo` created 6 documents and 27 components;
  `/api/stats` returned 10 models, 27 components, 19 relationships, and 6
  sources; `/api/query` returned a non-empty `query.v1` source-backed answer;
  Zoom and Notion setup guardrails returned the expected unavailable errors.

## Remaining Launch Blockers

### P0

- Resolved 2026-06-17: `LICENSE` and `CONTRIBUTING.md` now exist.

### P1

- Keep connector documentation synchronized with the backend catalog. Current README status is authoritative for launch copy.
- Run `bash scripts/smoke.sh --docker` from a fresh clone before a public
  release tag.

### P2

- MCP `query_context` uses the indexed query filter path, but semantic scoring
  still ranks candidate components in process. Larger installs will still need
  indexed semantic retrieval.
- Extractor logs LLM extraction failures and falls back to regex; richer operator surfacing would still help in the UI.
- Dependency freshness and image size should be reviewed before public launch.

## Current Data Model

Seven SQLAlchemy tables are currently defined:

- `workspaces`
- `source_documents`
- `models`
- `components`
- `relationships`
- `connectors`
- `sync_jobs`

## Connector Status

### Backend Catalog

| Type | availability | Current behavior |
|------|-------------|------------------|
| slack | available | OAuth/setup routes and sync worker exist; tests cover mocked sync behavior. |
| github | available | PAT connect route and issue/PR sync worker exist; tests cover mocked sync behavior. |
| ai_context | available | Import endpoint creates source documents. |
| local | available | Source upload/direct connect paths create source documents. |
| gmail | available | Google OAuth route and mocked sync tests exist. |
| gdrive | available | Google OAuth route and mocked sync tests exist. |
| codex / claude / opencode | available | AI session paste/import paths create source documents. |
| discord | coming_soon | Catalog stub only. |
| zoom | coming_soon | OAuth/manual setup routes are disabled until transcript sync exists. |
| wispr_flow | coming_soon | Catalog stub only. |

### Frontend Catalog (hooks.js lines 73-154)

| Type | availability | In Backend? |
|------|-------------|-------------|
| slack | available | Yes |
| discord | coming_soon | Yes |
| ai_context | available | Yes |
| local | available | Yes |
| zoom | coming_soon | Yes |
| gdrive | available | Yes |
| gmail | available | Yes |
| wispr_flow | coming_soon | Yes |

### Frontend Hooks Without Working Backend Paths

No launch-facing frontend hook now calls Notion or Zoom manual-connect routes.
Coming-soon connectors render disabled actions, while GitHub, Slack, Gmail, and
Google Drive use backend-backed setup paths.
Backend setup routes also reject direct Zoom OAuth/manual-token and Notion
token attempts so they cannot create fake connected provider state.

### Implemented

- Local source upload through Sources.
- AI Context import through `/api/connectors/ai-context/import`.
- Connector catalog/status/sync-job contract.
- Query API has a versioned `query.v1` response with retrieval controls and facts-used trace.
- Context packs can be generated from a selected graph component plus 1-hop neighbors.
- `/api/seed-demo` creates an idempotent source-backed demo workspace using launch-available source families only.

### Not Implemented Yet

- Discord sync.
- Zoom and Wispr provider sync.
- Notion catalog/provider backend.

## Evidence Files

- `app/api/connectors.py`
- `app/api/graph.py`
- `app/migrations.py`
- `app/models.py`
- `frontend/src/api/hooks.js`
- `tests/test_connectors.py`
- `tests/test_cli.py`
- `tests/test_docs.py`
- `tests/test_graph_api.py`
- `tests/test_migrations.py`
- `tests/test_sources_api.py`
- `Dockerfile`
- `pyproject.toml`
- `docs/connectors-graph-contract.md`
- `docs/architecture.md`
- `docs/connectors.md`
- `docs/ai-context.md`
- `docs/board-vs-explore.md`
- `docs/mcp.md`
- `docs/demo.md`
- `examples/mcp/README.md`
- `examples/mcp/installed-cli.json`
- `examples/mcp/local-checkout.json`
- `examples/mcp/agent-system-prompt.md`
- `docs/assets/board-inspector-demo.jpg`
- `docs/assets/query-trace-demo.jpg`
- `SECURITY.md`
- `scripts/doctor.sh`
- `scripts/smoke.sh`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/ISSUE_TEMPLATE/bug_report.yml`
- `.github/ISSUE_TEMPLATE/feature_request.yml`
