# Context Engine Project Brain

Last audited: 2026-06-18

This file is the durable project context for future AI agents. Its job is to
replace repeated full-repo rediscovery. Read `instructions.md` first because the
user intends that file to be the universal agent entry point. As of this audit
`instructions.md` is empty, so `AGENTS.md` is the active repository rule file.

## 2026-06-17 Implementation Update

Observed after this run:

- Phase 1 Board graph work is present: Board is the default URL state, Explore
  is available through `?graph=explore`, Board groups components by source
  family, cards are uniform, edges are quiet by default, labels reveal on
  hover/select, Refine drawer and lens presets exist, Cmd+K focuses graph
  search, and the minimap is implemented.
- Phase 3 Explore is no longer a placeholder: it renders connected components
  as source-logo circle nodes in a force layout, hides orphans by default,
  freezes after the initial physics pass, dims non-matches during search, and
  includes a 1-hop/2-hop local graph panel with Open in Board.
- The graph inspector is implemented as a right rail with component value,
  provenance, source links, trust metadata, connected relationships, and edge
  approve/reject actions.
- Query now has a versioned `query.v1` response with `top_k`,
  `min_confidence`, optional hybrid lexical scoring, relationship expansion,
  and a facts-used trace.
- Query UI and Graph Ask render `trace.facts_used` and relationship expansion
  counts.
- Context packs can be generated from the full graph or from a selected graph
  component plus 1-hop neighbors.
- MCP exposes `query_context`, which uses the same `query.v1` facts-used trace
  and relationship evidence contract as `/api/query`.
- Dashboard includes an I/O card that distinguishes source feeds from the
  graph/query/MCP/context-pack outputs agents consume.
- `/api/seed-demo` creates an idempotent, source-backed demo workspace from
  launch-available sources only: GitHub, Slack, Gmail, Google Drive, and Codex.
- Generic regex/LLM extracted facts now inherit document-level provenance when
  source-specific extractors did not already provide it.
- Query returns a deterministic source-backed answer summary when no AI answer
  model is configured, so the default self-hosted demo does not show a blank
  answer.
- Query status/confidence filtering now happens in SQL before semantic/lexical
  ranking, so the new compound component index is used by the shared HTTP/MCP
  query path.
- SQLAlchemy model metadata and startup migrations now create idempotent
  compound indexes for source-document sync lookup, pending extraction,
  component filtering, and relationship traversal.
- Source Manager now uses the shared frontend API client instead of raw fetch
  calls, separates unsupported/historical provider records from supported
  document imports, and has component smoke coverage.
- Landing and mock fixture copy now use launch-available sources only; dormant
  Notion/Zoom manual-connect actions were removed from the Connectors page, and
  landing smoke coverage now guards those launch-source claims.
- AgentsView ingestion-agent copy now uses launch-available source families
  only, with smoke coverage preventing stale Zoom/Notion overclaims.
- Frontend smoke tests now guard connector honesty so coming-soon providers stay
  disabled and launch connectors expose only backend-backed actions.
- Community health files now include `SECURITY.md`, bug/feature issue forms,
  and a pull request template tied to provenance, relationship evidence, and
  connector honesty.
- `scripts/smoke.sh` now runs the repeatable local launch gate; `--docker`
  adds container health, demo seed, stats, and query API smoke checks.
- Bare-metal setup now creates `.venv`, validates Python versions with
  `sys.version_info`, uses `npm ci`, and the start/dev/smoke scripts reuse
  `.venv/bin/python` when present.
- CLI ingest now carries `--sync` through to both single-source and bulk-source
  HTTP paths; bulk source creation processes documents synchronously when
  requested.
- README quick-start clone commands now use the real GitHub remote and clone
  into a stable lowercase `context-engine` directory.
- Package metadata now advertises the MIT license, repository/issues URLs,
  relevant keywords, and PyPI classifiers; metadata preparation is verified by
  a no-dependency pip dry run.
- Dockerfile now copies `LICENSE` alongside `pyproject.toml` and `README.md`
  before `pip install .`, so license-file metadata works in container builds.
- CI runs backend tests, Ruff, frontend tests, frontend build, Docker image
  build, and smoke-compose config validation.
- Launch-facing docs now exist for architecture, connectors, AI Context, Board
  vs Explore, and MCP, linked from the README.
- MCP examples now provide installed-CLI and local-checkout config snippets plus
  an agent grounding prompt for source-backed `query_context` usage.
- README now has a visual Product Tour with screenshots captured from the
  seeded Board inspector and Ask facts-used trace; `docs/demo.md` provides the
  credential-free demo walkthrough.
- `scripts/doctor.sh` now provides read-only first-run diagnostics for Docker
  and bare-metal setup paths, and README/demo docs point new users to it before
  setup or the seeded demo.
- Board default now opens at a readable card zoom when the full graph would
  otherwise collapse into unlabeled dots; the minimap still shows whole-graph
  orientation and the explicit fit button remains a true overview.
- OSS basics now include `LICENSE` and `CONTRIBUTING.md`.
- README launch copy now treats Slack, GitHub, Gmail, Google Drive, local
  upload, and AI session imports as launch-available paths; Discord, Zoom, and
  Wispr Flow remain `coming_soon`; Notion is not catalogued.

Latest verification on 2026-06-18:

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

## One-Screen Summary

Context Engine is an open-source developer/founder context system for turning
scattered project knowledge into a source-backed knowledge graph. It ingests raw
sources such as local files, AI coding sessions, GitHub issues/PRs, Slack,
Gmail, and Google Drive; stores every raw item as a `SourceDocument`; extracts
atomic facts into `Component` rows grouped by `Model`; links components through
typed `Relationship` edges; and exposes the result through a FastAPI backend,
React graph UI, query API, CLI, and MCP server.

The durable product thesis is:

- Raw source context should be preserved before any extraction happens.
- Facts should be atomic, typed, temporal, and source-backed.
- Relationships should be evidence-backed and visually distinguish trust level.
- AI agents should consume a compact, provenance-rich project memory instead of
  rereading Slack, GitHub, local docs, and prior AI sessions every time.
- The product is self-host-first: single FastAPI process, SQLite by default,
  optional PostgreSQL, Docker-supported, and external AI/provider keys optional.

Main product workflow:

```text
workspace/topic
  -> connect or import sources
  -> create raw SourceDocument rows
  -> extract deterministic facts for GitHub/AI sessions when possible
  -> fall back to LLM extraction or regex extraction
  -> upsert Models and Components
  -> embed Components
  -> create evidence-backed or proposed Relationships
  -> inspect graph, source diff, work lens, timeline, query results, and context packs
  -> review/accept/reject proposed relationships
  -> repeat on future sync/imports
```

## Truth Policy

Use these labels when describing the project:

- Observed: confirmed in code, tests, scripts, or docs during this audit.
- User-stated: stated by the user or repo-local task plans, not independently
  proven as market/customer traction.
- Not proven: frontend hook, doc claim, or planned workflow without a matching
  backend route/test/full sync path.

Do not claim a connector or workflow is production-ready just because a route
exists. For connectors, separate these states:

- catalogued in UI/backend
- has auth/connect route
- can create `SourceDocument` rows
- has sync worker
- has tested behavior
- has frontend state that honestly reflects the backend

## Vision And Direction

User-stated direction:

- The project has been built heavily with Codex and other AI-agent passes.
- `project.md` should function as the compressed project brain for future AI
  agents, not as a task tracker.
- The audience is mainly AI agents.
- Include stated vision/claims, but distinguish them from implemented reality.

Repo-local direction from `AGENTS.md` and `TASK_PLAN.md`:

- Build Context Engine into an OSS-grade developer context system.
- Focus on local files, AI-agent sessions, GitHub, Slack, Gmail, Google Drive,
  and future communication/document connectors.
- Preserve provenance and temporal state so agents can tell current truth,
  historical decisions, and proposed/future work apart.
- Keep unsupported providers honest. Do not mark provider integrations working
  without tested auth, sync, ingestion, and graph behavior.
- Treat evidence-backed relationships and anti-hallucination as core product
  quality, not polish.

Observed engineering traction:

- FastAPI backend with a broad route surface for sources, graph, query,
  connectors, workspaces, agents, repo graph, and timeline.
- React app with landing, dashboard, graph explorer, ask/query, source manager,
  connector manager, and changes timeline.
- Seven persisted SQLAlchemy tables: `workspaces`, `connectors`, `sync_jobs`,
  `source_documents`, `models`, `components`, `relationships`.
- Dedicated deterministic extractors for GitHub issues/PRs and AI-agent
  sessions, plus generic LLM/regex extraction.
- Sync code exists for Slack, GitHub, Gmail, and Google Drive.
- Large backend test suite covers connectors, graph APIs, ingestion, extractors,
  adversarial relationship behavior, migrations, agents, and MCP.
- Docker, compose, setup/start/dev scripts, CLI, and MCP server exist.

Not evidenced in this repo:

- External user/customer traction metrics.
- A public OSS release with license/readiness fully resolved.
- Production-grade OAuth validation for every provider under real deployments.
- Frontend test coverage.

## Mental Model

The project has four levels of knowledge:

1. SourceDocument: immutable-ish raw input. This is the evidence layer.
2. Model: semantic bucket/domain such as `Decision`, `Task`, `Risk`, `Issue`,
   `PR`, `Repo`, `Agent Session`, `Message`, `Email`, or `Document`.
3. Component: one atomic extracted fact inside one model.
4. Relationship: typed directed edge between two components.

Every important feature should respect that layering. New source integrations
should not create components directly without preserving the raw source first.

## Architecture

Backend:

- `app/main.py`: FastAPI app, startup table creation, startup migrations, API
  router under `/api`, built frontend serving when `frontend/dist` exists.
- `app/api/router.py`: includes sources, graph, query, repo, connectors, models,
  and agents routers.
- `app/models.py`: SQLAlchemy models.
- `app/database.py`: async SQLAlchemy engine/session. Converts
  `postgresql://` and `postgres://` URLs to `postgresql+asyncpg://` and strips
  `sslmode`.
- `app/migrations.py`: lightweight startup migrations for SQLite/legacy local
  DBs. There is no Alembic.
- `app/services/ingest.py`: source-to-graph ingestion service.
- `app/services/query.py`: graph semantic query service.
- `app/services/workspace_scope.py`: workspace scoping helper while
  `SourceDocument` has no direct workspace FK.
- `app/processing/extractor.py`: LiteLLM JSON extraction with regex fallback.
- `app/processing/source_extractors.py`: deterministic GitHub and agent-session
  extractors.
- `app/processing/embedder.py`: LiteLLM, optional local sentence-transformer,
  or deterministic hashing embedder.
- `app/agents/*`: graph builder, semantic linker, gap detector, relationship
  agent, context pack agent.
- `app/sync/*`: provider sync code for Slack, GitHub, Google/Gmail/Drive, and
  AI session ingest.
- `app/mcp/server.py`: MCP server over stdio.

Frontend:

- `frontend/src/main.jsx`: React root, QueryClient, ThemeProvider,
  BrowserRouter, WorkspaceProvider.
- `frontend/src/App.jsx`: routes `/`, `/app`, `/app/graph`, `/app/query`,
  `/app/sources`, `/app/connectors`, `/app/connectors/:connectorType/runs`,
  `/app/changes`.
- `frontend/src/api/client.js`: `/api` client wrapper.
- `frontend/src/api/hooks.js`: React Query hooks, connector catalog, workspace
  resolution, normalizers, several frontend-only or future workflow hooks.
- `frontend/src/pages/GraphView.jsx`: main graph command map.
- `frontend/src/pages/Connectors.jsx`: connector catalog, auth/connect forms,
  sync actions, OAuth windows, AI session import.
- `frontend/src/pages/SourceManager.jsx`: legacy/simple upload and source
  inspection using `/api/sources`.
- `frontend/src/pages/QueryView.jsx`: simple ask interface using `/api/query`.
- `frontend/src/pages/Changes.jsx`: timeline view.
- `frontend/src/pages/Dashboard.jsx`: overview and onboarding entry points.

Infrastructure:

- `Dockerfile`: Node 20 builds frontend, Python 3.12 slim runs backend and
  serves `frontend/dist`.
- `docker-compose.yml`: SQLite default in `/data/context.db`, optional commented
  PostgreSQL variant.
- `scripts/setup.sh`: installs backend editable package, installs frontend deps,
  builds frontend.
- `scripts/start.sh`: production-ish Uvicorn start on `PORT` default 8000.
- `scripts/dev.sh`: backend reload on 8000 plus Vite dev server on 5000.

## Data Model

`Workspace`

- Table: `workspaces`
- Fields: `id`, `name`, `slug`, `created_at`
- Purpose: user-facing workspace/topic scope. Connectors belong to workspaces.

`Connector`

- Table: `connectors`
- Fields: `id`, `workspace_id`, `connector_type`, `status`, `config_json`,
  `credentials_json`, `last_sync_at`, timestamps.
- `items_synced` is a property stored inside `config_json`.
- Credentials are stored as JSON text. There is no separate secret manager.

`SyncJob`

- Table: `sync_jobs`
- Fields: `id`, `connector_id`, `status`, `error_type`, `error_message`,
  `result_metadata_json`, timestamps.
- Sync jobs are created by `/api/connectors/{connector_id}/sync`.

`SourceDocument`

- Table: `source_documents`
- Fields: `id`, `source_type`, `external_id`, `content`, `author`,
  `source_url`, `metadata_json` mapped to SQL column `metadata`,
  `ingested_at`, `processed_at`.
- Important: no `workspace_id` FK. Workspace matching uses metadata plus
  connector types in `workspace_scope.py`.
- Dedup behavior varies by importer/sync path, usually via `external_id`.

`Model`

- Table: `models`
- Fields: `id`, `name`, `description`, `created_at`.
- `name` is unique.

`Component`

- Table: `components`
- Fields: `id`, `model_id`, `source_document_id`, `name`, `value`,
  `fact_type`, `temporal`, `confidence`, `authority_weight`, `embedding`,
  `status`, `valid_from`, `valid_to`, `superseded_by_id`, `provenance`,
  `excerpt`, `created_at`.
- Status rules in ingestion:
  - confidence `< 0.6` -> `needs_review`
  - temporal `future` -> `proposed`
  - temporal `past` -> `needs_review`
  - otherwise high-confidence/current facts -> `active`

`Relationship`

- Table: `relationships`
- Fields: `id`, `source_component_id`, `target_component_id`,
  `relationship_type`, `confidence`, `evidence`, `status`, `origin`,
  `created_at`.
- Default `status` is `active`; default `origin` is `proposed`.
- Valid origins are `deterministic`, `extracted`, `ai_proposed`,
  `human_verified`, and `proposed`.
- Do not infer trust from `status` alone. Use `origin`, `confidence`, and
  `evidence` together.

## Taxonomy Contracts

Defined in `app/taxonomy.py`.

Canonical model names include:

`Agent Session`, `Company`, `Context Pack`, `Customer`, `Decision`,
`Document`, `Email`, `Feature`, `GitHub`, `Issue`, `Meeting`, `Message`,
`Metric`, `Person`, `PR`, `Product`, `Repo`, `Risk`, `Task`, `Team`, `User`.

Important source types:

`local`, `local_folder`, `browser_upload`, `paste`, `github_issue`,
`github_pr`, `agent_session`, `slack`, `discord`, `gmail`, `gdrive`, `zoom`,
`notion`, plus compatibility aliases such as `github`, `codex`, `claude`,
`opencode`, `ai_context`, `ai_context_codex`, `ai_context_claude_code`,
`ai_context_opencode`.

Important fact types:

`decision`, `task`, `blocker`, `risk`, `metric`, `feature`, `meeting_note`,
`ai_step`, `fact`, `issue`, `pr`, `github_issue`, `github_pr`,
`pr_review_finding`, `commit_reference`, `changed_file`, `ai_session`,
`ai_task`, `ai_decision`, `ai_blocker`, `open_question`, `session_root`,
`review_finding`.

Relationship types include:

`assigned_to`, `blocked_by`, `blocks`, `caused_by`, `co_occurs`, `confirms`,
`conflicts_with`, `contains`, `contradicts`, `created_from`, `decides`,
`depends_on`, `discussed_in`, `duplicates`, `enables`, `fixes`,
`generated_by_agent`, `implemented_in`, `implements`, `mentions`, `owned_by`,
`part_of`, `related_to`, `resolved_by`, `solves`, `supersedes`,
`touches_file`, `verified_by_human`.

Relationship aliases exist. Examples:

- `closes`, `resolves`, `fix` -> `fixes`
- `touch`, `touches` -> `touches_file`
- `conflicts` -> `conflicts_with`
- `generated_by` -> `generated_by_agent`
- There is an alias conflict in spirit: `implements` appears in aliases and
  valid types. Verify `canonical_relationship_type()` before changing this.

## Ingestion Workflow

The central ingestion path is `IngestionService.process_document(doc_id)`.

Observed behavior:

1. Load `SourceDocument`; return 0 if missing or already processed.
2. Parse `metadata_json`, adding source type, external ID, author, source URL.
3. Try deterministic source extractors first:
   - GitHub source resolution via `resolve_github_item_type()`.
   - `github_pr` -> `extract_github_pr()`.
   - `github_issue` -> `extract_github_issue()`.
   - AI/agent session source -> `extract_agent_session()`.
4. If no deterministic facts, call generic `Extractor.extract()`.
   - If `EXTRACTION_MODEL` and key/model are configured, use LiteLLM JSON
     extraction.
   - If LiteLLM fails or is not configured, use regex fallback.
5. Create/get canonical `Model` rows.
6. Upsert `Component` rows by model/name/value over statuses
   `active`, `needs_review`, `proposed`.
7. Generate embeddings for components without embeddings.
8. Create relationships from extracted relationships.
9. Set `SourceDocument.processed_at`.

Relationship creation behavior in ingestion:

- Confidence is clamped to 0.0-1.0.
- Relationships below 0.6 are skipped.
- Empty target names are skipped.
- Self-loops are skipped.
- Target resolution prefers same model by exact component name, then falls
  back to any model by exact component name.
- Targets must be `active`, `needs_review`, or `proposed`; stale targets are
  excluded.
- `related_to` below 0.7 is skipped.
- Duplicate source/target/type edges are skipped.
- Missing evidence is filled with template evidence. This is useful for
  persistence safety, but future agents should still prefer real source quotes
  or deterministic evidence.
- Origin is determined by relationship type and source type:
  deterministic types such as `fixes`, `created_from`, `part_of`,
  `generated_by_agent`, `implemented_in`, `duplicates`, `supersedes`,
  `touches_file`, `resolved_by` -> `deterministic`; GitHub/agent-session
  non-deterministic links -> `extracted`; local generic links -> `proposed`.

## Extraction Details

Generic extractor: `app/processing/extractor.py`

- Prompt asks for canonical entity types and relationship types.
- LLM extraction truncates content to 12,000 chars and returns max 20 facts.
- Regex fallback extracts decisions, tasks/action items, risks/blockers,
  features, metrics, meeting outcomes, and AI steps from simple patterns.
- If no patterns match, fallback facts are created for generic documents and
  connector-specific Gmail/Slack/GDrive summaries.
- Regex fallback generally does not create relationships.

Deterministic GitHub extractor: `app/processing/source_extractors.py`

- Handles JSON and text fallbacks.
- Issues create an Issue root component; labels can create bug/risk or feature
  request components; body patterns can create decisions/tasks/risks.
- PRs create a PR root component, linked issue references, changed file
  components, review finding risks, and body facts.
- `Fixes #N`, `Closes #N`, `Resolves #N` are treated as deterministic fix/solve
  evidence. Plain issue-number mentions should not imply resolution.
- Changed files are capped in current extractor code at 10.
- Current relationship direction for changed files is fact-source dependent:
  file components currently carry `touches_file` relationships targeting the PR
  root. Verify direction before building UI semantics around it.

Deterministic AI session extractor:

- `extract_agent_session()` creates a session root component.
- It extracts future tasks from action-like bullets and "next step/todo/action"
  patterns.
- It extracts decisions from explicit decision/recommendation/verdict language
  and final/summary/conclusion sections.
- It extracts risks/blockers from explicit risk/blocker/open-question/failed
  language.
- It extracts code/file references into `Repo` components.
- Extracted tasks/decisions/risks get `generated_by_agent` relationships to the
  session root; file refs get `part_of` relationships to the session root.

## Embeddings And Query

Embedders are in `app/processing/embedder.py`.

Resolution order:

1. `EMBEDDING_MODEL` set -> LiteLLM embedding provider.
2. `ENABLE_LOCAL_EMBEDDER=true` -> local sentence-transformers if installed.
3. Fallback -> deterministic `HashingEmbedder`.

The hashing embedder is deterministic and good for tests/offline operation, but
is not semantic retrieval.

`QueryService.query()` behavior:

- Embeds the question.
- Loads components with status `active` or `needs_review`.
- Applies workspace filtering if `workspace_id` is provided.
- Scores components as semantic similarity * 2.0 + confidence * 0.5 +
  authority_weight * 0.3.
- Returns top 8 plus 1-hop related components.
- Builds source citations from top component source documents.
- If per-request `api_key` and `model` are provided, synthesizes a 1-3 sentence
  answer through LiteLLM using only provided facts.
- Without key/model, answer is an empty string and the UI should show cited facts.
- Error messages special-case quota, invalid model, and auth failures.

Frontend note:

- `QueryView.jsx` posts to `/api/query` without workspace ID.
- `frontend/src/api/hooks.js` has `useContextQuery()` that does pass the active
  workspace ID.
- `GraphView.jsx` has its own ask panel and AI extraction settings.

## Graph Build And Relationship Inference

`GraphBuilderAgent` in `app/agents/graph_builder.py` powers
`POST /api/graph/build`.

Run behavior:

1. Select pending source documents, optionally scoped by workspace.
2. Process each through `IngestionService`.
3. Commit extraction results.
4. Infer deterministic GitHub issue/PR identity links.
5. Run `SemanticRelationshipLinker` with threshold 0.84, cross-source-type
   required, max candidates 250, create up to 100 `related_to` edges.
6. Run cross-document name-mention inference.
7. Return build stats and extraction warnings.

Semantic relationship linker:

- Reads embedded components with status `active`, `needs_review`, or `proposed`.
- Skips same source document.
- Can require cross-source-type.
- Creates `related_to` relationships with `status="proposed"`,
  `origin="ai_proposed"`, confidence equal to similarity capped at 0.95, and
  evidence explaining the similarity candidate.

Cross-document name-mention inference:

- Scans active component values for exact lowercased names of other components
  from different source documents.
- Creates `related_to` relationships with confidence 0.5, evidence containing
  the matched name, and `origin="ai_proposed"`.
- It does not explicitly set `status`, so model default `active` applies unless
  code changes. Future UI/agents must treat low-confidence `ai_proposed` edges as
  review candidates even if status says active.

Relationship review:

- `PATCH /api/relationships/{relationship_id}/review` with action
  `accept`, `verify`, or `approve` sets `status="active"` and
  `origin="human_verified"`.
- Action `reject` or `dismiss` sets `status="rejected"`.
- `GET /api/graph` excludes rejected relationships.

## Workspace Scoping

Workspaces are first-class for connectors but not directly on source documents.

Observed rules in `app/services/workspace_scope.py`:

- A document matches a workspace if metadata has matching `workspace_id`.
- Otherwise it can match if its `source_type` is one of that workspace's
  connector types.
- `github_issue` and `github_pr` match a workspace with `github` connector.
- `ai_context*` and `agent_session` match AI context/session connectors.
- Legacy unscoped local uploads remain visible in active workspace for source
  types `local`, `local_folder`, `browser_upload`, `paste`.

Routes that support workspace filtering include:

- `/api/graph`
- `/api/stats`
- `/api/graph/build`
- `/api/work-lens`
- `/api/connectors`
- `/api/connectors/processing-summary`
- `/api/query`
- `/api/source-documents` partially through frontend query params, but backend
  currently only applies connector/processed/cursor/limit filters in
  `models_api.py`. Verify before relying on source-document workspace filtering.

Frontend workspace selection:

- Local storage key: `ce:selectedWorkspaceId`.
- `WorkspaceProvider` stores selected workspace.
- `useWorkspaces()` and `useCreateWorkspace()` call `/api/workspaces`.
- `WorkspaceTopicGate.jsx` exists to force choosing a real graph topic when
  only the default workspace exists. GraphView uses workspace state heavily.

## Connector Reality

Backend catalog in `app/api/connectors.py` currently includes:

| Type | Catalog availability | Current reality |
|---|---:|---|
| `slack` | available | OAuth settings/install/callback routes exist; `sync_slack()` fetches public channels/messages with token; tests cover queue/skip behavior with mocked Slack. |
| `github` | available | Token connect route exists; `sync_github()` fetches issues and pulls for configured repos; tests cover duplicate skips with mocked GitHub. |
| `discord` | coming_soon | Catalog only; sync fails as unsupported. |
| `ai_context` | available | `/connectors/ai-context/import` creates source documents; processing summary groups subtypes. |
| `local` | available | Source upload and direct connect for default workspace exist. |
| `zoom` | coming_soon | OAuth/manual token setup routes are disabled; sync endpoint treats `zoom` as unsupported and returns failed job. |
| `gdrive` | available | Google OAuth route and `sync_gdrive()` exist; tests cover mocked exported files. |
| `gmail` | available | Google OAuth route and `sync_gmail()` exist; tests cover mocked messages. |
| `codex` | available | AI session paste/import through `/connectors/ai-session/ingest`. |
| `claude` | available | AI session paste/import through `/connectors/ai-session/ingest`. |
| `opencode` | available | AI session paste/import through `/connectors/ai-session/ingest`. |
| `wispr_flow` | coming_soon | Catalog only; sync unsupported. |

Notion:

- `notion` is not in `CONNECTOR_CATALOG`.
- `POST /api/connectors/notion/connect` is guarded and returns a not-catalogued
  error instead of storing credentials.
- There is no Notion sync worker path in `_run_sync_job`.
- Do not describe Notion as a catalogued working connector.

Sync worker behavior:

- `POST /api/connectors/{connector_id}/sync` creates a `SyncJob`.
- `discord`, `zoom`, and `wispr_flow` are immediately failed as
  `unsupported_connector`.
- Pending jobs for non-local/non-ai_context connectors run `_run_sync_job()`.
- Worker paths:
  - Slack -> `sync_slack()` then `extract_from_source_documents("slack")`
  - GitHub -> `sync_github()` then `extract_from_source_documents("github")`
  - Gmail -> `sync_gmail()` then `extract_from_source_documents("gmail")`
  - GDrive -> `sync_gdrive()` then `extract_from_source_documents("gdrive")`
  - Codex/Claude/OpenCode -> extraction only
- Worker updates `items_synced`, `total_processed_count`, `last_sync_at`, and
  job `result_metadata_json`.

Google OAuth details:

- `GOOGLE_CLIENT_ID` is sanitized to strip accidental `http://` wrappers.
- `GOOGLE_REDIRECT_URI` overrides generated callback URI for both Gmail and
  GDrive.
- Without override, callback is built from `PUBLIC_BASE_URL` or request base URL.
- Exact host matters: `localhost` and `127.0.0.1` are different redirect URIs.

Slack OAuth details:

- Supports self-hosted Slack app credentials and optional managed install URL.
- `SLACK_MANAGED_INSTALL_URL` plus `ENCRYPTION_KEY` enables managed callback
  token decryption.
- Disconnect revokes Slack token through Slack API when possible.

## API Surface

All routes below are mounted under `/api` except `/health`.

Core:

- `GET /health`: app health.
- `POST /sources`: create source document. `sync=true` processes immediately;
  otherwise schedules background ingestion.
- `POST /sources/bulk`: create many source docs and schedule ingestion.
- `POST /sources/upload`: multipart upload as `local`.
- `GET /sources`: legacy list, newest 100.
- `GET /sources/{source_id}`: source detail with extracted components.
- `POST /seed-demo`: idempotently seed a workspace with launch-available demo
  source documents, then synchronously process them into graph facts.
- `POST /query`: query graph.
- `GET /repo/graph`: static-ish repo architecture graph for frontend repo view.

Graph:

- `GET /graph`: models, components, relationships. Filters include
  `model_id`, `source_type`, `confidence_min`, `temporal`, `status`,
  `relationship_origin`, `workspace_id`.
- `GET /graph/source-diff/{source_id}`: source plus components and outgoing
  relationships from that source.
- `PATCH /components/{component_id}`: update component status by query param
  `status`.
- `GET /stats`: counts, optional `workspace_id`.
- `POST /graph/build`: run graph builder, optional limit/api_key/model/workspace.
- `GET /graph/agent-status`: reports extraction model configured state.
- `GET /timeline`: source ingest and component created events.
- `POST /graph/slice`: filtered graph slice.
- `GET /components/{component_id}`: component detail with inbound/outbound rels.
- `GET /relationships/{relationship_id}`: relationship detail.
- `PATCH /relationships/{relationship_id}/review`: accept/reject relationship.
- `GET /source-documents/{source_id}/diff`: richer source-to-knowledge diff.
- `GET /work-lens`: buckets blockers, open decisions, active tasks, unresolved
  questions, proposed items, stale items.

Models/source documents:

- `GET /models`: list models and component counts.
- `GET /models/{model_id}`: model detail with active/needs_review components.
- `GET /models/{model_id}/relationships`: relationships within a model.
- `GET /source-documents`: paginated source documents with connector/processed
  filters.

Connectors/workspaces:

- `GET /workspaces`
- `POST /workspaces`
- `GET /connectors`
- `GET /connectors/setup-status`
- `GET /connectors/processing-summary`
- `POST /connectors/slack/oauth-settings`
- `GET /connectors/slack/install`
- `GET /connectors/slack/managed/install`
- `GET /connectors/slack/callback`
- `GET /connectors/zoom/install` disabled while Zoom is coming soon.
- `GET /connectors/zoom/callback` returns an OAuth failure page while Zoom is coming soon.
- `POST /connectors/zoom/connect` disabled while Zoom is coming soon.
- `GET /connectors/{connector_type}/install` for Google connectors only
- `GET /connectors/{connector_type}/callback` for Google connectors only
- `POST /connectors/notion/connect` disabled because Notion is not catalogued.
- `POST /connectors/github/connect`
- `POST /connectors/{connector_type}/connect` generic catalog direct connect
  for `ai_context` and `local`; other catalog types return 400.
- `POST /connectors/ai-context/import`
- `POST /connectors/ai-session/ingest`
- `POST /connectors/{connector_id}/sync`
- `GET /connectors/{connector_id}/sync-status`
- `GET /connectors/{connector_id}/sync-jobs`
- `DELETE /connectors/{connector_id}`

Agents:

- `POST /agents/gaps`
- `POST /agents/context-pack`
- `POST /agents/relationships`

Frontend hooks reference these not-implemented or not-currently-backed routes:

- `/operator/status`, `/admin/status`
- `/imports`
- `/founder-brief`
- `/decisions` and `/decisions/{id}/history`
- `/review-items` and review approve/reject/supersede routes
- `/evals/summary`, `/evals/cases`, `/evals/run`
- `/launch-guard/check`
- `POST /models`, `POST /models/{id}/components`
- `DELETE /components/{id}`
- `POST /relationships`
- `/source-documents/{id}` detail, `/components`, `/reprocess`, `DELETE`,
  `/restore`
- `/graph/models/{id}` and `/graph/components/{id}` used by hook variants

Some hooks fall back to fixtures only when `VITE_USE_MOCKS=true` or for specific
404/501 paths. Do not assume these routes exist just because hooks mention them.

## Frontend Product Surface

Landing:

- `frontend/src/pages/Landing.jsx`.
- Marketing-style first page at `/`.

Dashboard:

- `Dashboard.jsx` uses `useDashboard()`.
- Shows onboarding when source count is 0.
- Stats are built from `/stats`, `/models`, `/connectors`, and
  `/source-documents` where possible.
- Recent activity/alerts can still use fixtures.

Graph:

- `GraphView.jsx` is the command-map surface.
- View modes include knowledge graph and repository graph.
- Default knowledge `ceoView` is `workLens`.
- CEO views include `all`, `birdsEye`, `gaps`, `decisions`, `aiSessions`,
  `workLens`, `github`, and `repo`.
- Fetches `/api/graph?workspace_id=...` for knowledge graph and
  `/api/repo/graph` for repository graph.
- Fetches `/api/work-lens` for work lens panel.
- Can run `/api/graph/build`.
- Can call `/api/query` from an Ask AI panel.
- Can call `/api/agents/gaps`, `/api/agents/relationships`,
  `/api/agents/context-pack`.
- Supports filters for model, source type, status, temporal, confidence, and
  relationship origin.
- Cytoscape renders model compound nodes and component nodes. Edge style
  distinguishes origins: deterministic, extracted, ai_proposed, human_verified,
  proposed.
- Selected node inspector shows provenance/source fields, confidence/status,
  connected nodes, relationship count, and warnings such as isolated node.
- Selected edge inspector shows origin/status/confidence/evidence and review
  actions for proposed/AI-proposed edges.

Query:

- `QueryView.jsx` is a simple direct `/api/query` interface.
- Shows answer if present, cited components, sources, and local question history.
- Does not currently use the workspace selection context.

Sources:

- `SourceManager.jsx` uses the shared frontend API client for `/api/sources`.
- Upload maps extensions to source types like markdown/text/json/csv/html/pdf,
  but backend stores whatever `source_type` is sent.
- Clicking a source fetches `/api/sources/{id}` and shows extracted components.

Connectors:

- `Connectors.jsx` uses `useConnectors()`, `useConnectorProcessingSummary()`,
  sync status/jobs hooks, and workspace selection.
- Supports Slack OAuth, Google OAuth, GitHub token form, AI session
  paste/import, sync, disconnect, and sync-job inspection links.
- Coming-soon providers such as Zoom render disabled actions and do not expose a
  manual token form in the launch UI.
- UI derives availability/configuration from backend catalog/setup status plus
  frontend normalizers.

Changes:

- `Changes.jsx` uses `useTimeline()` and displays source/component timeline
  events.
- Filters include all, decision, review, source, connector, but backend
  timeline currently emits `source_ingest` and `component_created`; frontend
  normalizers map where possible.

Agents page:

- `AgentsView.jsx` exists, but `/app/agents` currently redirects to
  `/app/graph`. Agent controls are primarily inside GraphView.

## AI Agent Surfaces

GraphBuilderAgent:

- Processes pending docs, creates components/relationships, infers relationship
  candidates, returns stats.
- Callable through `/api/graph/build`.

GapDetectorAgent:

- Rule-based without AI key; optional LiteLLM analysis with key/model.
- Finds missing owners, unimplemented decisions, blocked items, orphaned nodes,
  ready-to-ship and blocked lists.
- Output depends heavily on relationship quality.

RelationshipAgent:

- Requires AI key/model for discovery.
- Uses semantic candidates, asks LLM to validate hidden relationships, persists
  suggestions with confidence >= 0.6 as `status="proposed"`,
  `origin="ai_proposed"`.
- Evidence is AI reasoning unless strengthened by future code.

ContextPackAgent:

- Rule-based fallback works without AI key.
- Optional AI generation.
- Current API generates whole-graph context packs, not selected graph slices.
- Useful directionally for AI-agent handoff, but verify output quality before
  treating it as canonical.

## MCP Surface

Launch:

```bash
ctxe mcp
```

Tools in `app/mcp/server.py`:

- `search_nodes`: hash-embed/lexical search over active components.
- `expand_graph`: 1-hop neighbors and edges for a component UUID.
- `get_model`: model lookup by partial name with components.
- `list_models`: all models with active component counts.
- `get_status`: counts of active components, relationships, sources, models.

MCP search currently uses `HashingEmbedder` directly, not the configured default
embedder. It is useful but not a scalable semantic retrieval implementation.

## CLI Surface

Package script in `pyproject.toml`:

```bash
ctxe = "app.cli.main:main"
```

Commands:

```bash
ctxe ingest PATH [--base-url http://localhost:8000] [--sync] [--json]
ctxe query "question" [--base-url http://localhost:8000] [--json]
ctxe graph [--base-url http://localhost:8000] [--json]
ctxe mcp
```

Important CLI detail:

- `ctxe ingest --sync` appends `sync=true` for both single-file and directory
  ingest. `POST /api/sources/bulk?sync=true` processes each document before
  returning.

## Repo Map

Backend routes:

- `app/api/sources.py`: source ingest/list/detail.
- `app/api/graph.py`: graph read/build/slice/detail/review/work-lens/timeline.
- `app/api/query.py`: natural language query.
- `app/api/models_api.py`: model and source-document list APIs.
- `app/api/connectors.py`: workspaces, connector catalog/auth/sync/import.
- `app/api/agents_api.py`: gap/context-pack/relationship agents.
- `app/api/repo.py`: repository graph used by graph UI repo mode.

Core engine:

- `app/services/ingest.py`: central document processing path.
- `app/services/query.py`: retrieval/query path.
- `app/services/workspace_scope.py`: workspace filtering.
- `app/processing/extractor.py`: generic LLM/regex extraction.
- `app/processing/source_extractors.py`: deterministic GitHub/AI-session rules.
- `app/processing/embedder.py`: embeddings.
- `app/taxonomy.py`: canonical vocabularies and display helpers.

Connectors/sync:

- `app/sync/slack.py`: Slack channel history to source documents.
- `app/sync/github.py`: GitHub issues/pulls to source documents.
- `app/sync/google.py`: Gmail and Drive to source documents.
- `app/sync/ai_session.py`: parses pasted AI sessions into one source document.
- `app/extract/basic.py`: legacy/basic extractor wrapper for connector jobs,
  now delegates to `IngestionService` for source documents.

Frontend:

- `frontend/src/App.jsx`: top-level route shell.
- `frontend/src/api/hooks.js`: hooks, catalog, normalizers.
- `frontend/src/pages/GraphView.jsx`: main graph UI.
- `frontend/src/pages/Connectors.jsx`: connector UI.
- `frontend/src/pages/SourceManager.jsx`: source upload/list.
- `frontend/src/pages/QueryView.jsx`: ask UI.
- `frontend/src/pages/Changes.jsx`: timeline UI.
- `frontend/src/context/WorkspaceContext.jsx`: selected workspace.
- `frontend/src/components/WorkspaceTopicGate.jsx`: graph topic gate.

Docs and planning:

- `AGENTS.md`: permanent agent rules.
- `instructions.md`: intended first-read file; empty as of 2026-06-10 audit.
- `TASK_PLAN.md`: high-level product/agent plan. Useful as direction, not proof.
- `docs/architecture.md`: current launch architecture guide.
- `docs/connectors.md`: current launch connector truth and state semantics.
- `docs/ai-context.md`: current AI session import schema, metadata contract,
  extraction behavior, verification, and limits.
- `docs/board-vs-explore.md`: current graph UX mode guide.
- `docs/mcp.md`: current MCP usage and tool guide.
- `docs/demo.md`: current credential-free launch demo walkthrough with
  screenshots from the seeded demo workspace.
- `examples/mcp/*`: copy-paste MCP configs and an agent prompt for grounding
  coding agents in source-backed query traces.
- `SECURITY.md`: reporting process and security expectations for source docs,
  connector credentials, MCP/API access, and context packs.
- `scripts/smoke.sh`: local launch gate plus optional Docker/API smoke.
- `.github/PULL_REQUEST_TEMPLATE.md`: provenance/relationship/connector
  checklist plus verification gates.
- `.github/ISSUE_TEMPLATE/*`: bug and feature forms that keep reports tied to
  the source-backed graph contract.
- `docs/knowledge-graph-contract.md`: older graph contract plus acceptance
  criteria; many proposed items have since been partially implemented.
- `docs/knowledge-graph-display-strategy.md`: graph display contract.
- `docs/connectors-graph-contract.md`: historical connector/graph contract
  review; not authoritative for current launch copy.
- `docs/oss-readiness.md`: readiness review and remaining launch gaps.
- `.agent-runs/*`: repo-local multi-agent task reports and handoffs. Useful as
  historical leads, not current proof.

## Runbook

Install/setup:

```bash
cd /Users/darshann/Desktop/context-engine
bash scripts/setup.sh
```

Run production-style local server:

```bash
bash scripts/start.sh
# opens backend + built frontend at http://localhost:8000
```

Run development:

```bash
bash scripts/dev.sh
# backend:  http://localhost:8000
# frontend: http://localhost:5000
```

Direct backend:

```bash
.venv/bin/python -m uvicorn app.main:app --host localhost --port 8000 --reload
```

Frontend:

```bash
cd frontend
npm ci
npm run dev
npm run build
```

Docker:

```bash
docker compose up --build
docker compose down
docker compose down -v  # wipes named volume data
```

Tests:

```bash
python3 -m pytest -q
python3 -m pytest -q tests/test_connectors.py
python3 -m pytest -q tests/test_knowledge_graph.py tests/test_adversarial_graph.py tests/test_graph_api.py
cd frontend && npm run build
cd frontend && npm test
```

Frontend tests now cover focused smoke behavior for Source Manager, Connectors,
Landing and AgentsView launch copy, graph helpers, and query/context-pack
helpers.

Environment:

- `DATABASE_URL`: default `sqlite+aiosqlite:///data/context.db` in config and
  Docker. `.env.example` says local data dir is `./data`.
- `DATA_DIR`: default `./data`.
- `LITELLM_API_KEY`: optional.
- `EXTRACTION_MODEL`: optional LiteLLM extraction model.
- `EMBEDDING_MODEL`: optional LiteLLM embedding model.
- `ENABLE_LOCAL_EMBEDDER`: optional local sentence-transformers path.
- Google OAuth: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
  `GOOGLE_REDIRECT_URI`, `PUBLIC_BASE_URL`.
- Slack OAuth: `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`,
  `SLACK_REDIRECT_URI`, `SLACK_MANAGED_INSTALL_URL`, `ENCRYPTION_KEY`.
- Zoom config exists in `app/config.py`: `ZOOM_CLIENT_ID`,
  `ZOOM_CLIENT_SECRET`, `ZOOM_REDIRECT_URI`.

## Verification Map

Use this map instead of guessing which tests matter.

| Area | Tests |
|---|---|
| Connector catalog/status/sync/import/OAuth metadata | `tests/test_connectors.py` |
| Graph API, stats, workspace scoping, query scoping, timeline, graph build | `tests/test_graph_api.py` |
| Taxonomy, deterministic GitHub/AI session extractors, origins, graph display fields | `tests/test_knowledge_graph.py` |
| Anti-hallucination, relationship evidence/origin, MCP behavior, adversarial cases | `tests/test_adversarial_graph.py` |
| Ingestion upsert/status/relationship behavior | `tests/test_ingestion.py` |
| Generic extractor and fallback extraction | `tests/test_extraction.py` |
| Agent behavior | `tests/test_agents.py` |
| Migration safety/idempotency | `tests/test_migrations.py` |
| Embedder selection | `tests/test_embedder.py` |

Previous repo-local verification reports mention:

- Full backend suite at one point: 263 passed.
- Connector suite at one point: 52 passed.
- Frontend build: passed with GraphView chunk-size warning.

Those are historical leads. Re-run relevant tests for any code changes.

## Implementation Boundaries Future Agents Must Preserve

These are durable project contracts, not a to-do list:

- Source-first ingestion: create/preserve `SourceDocument` before extraction.
- Preserve source provenance in graph responses.
- Do not invent owners, blockers, PR status, issue status, merge status, or
  connector coverage.
- Do not visually present `ai_proposed` or low-confidence edges as deterministic.
- Relationship display must expose evidence or explicitly say evidence is absent.
- Relationship promotion should go through review semantics.
- Connector UI/backend must agree on whether something is available,
  configured, connected, unsupported, or coming soon.
- SQLite local installs must keep migrating via `app/migrations.py` until a real
  migration framework is deliberately introduced.
- Avoid broad rewrites. The repo already has clear FastAPI, SQLAlchemy, React
  Query, Tailwind, Cytoscape, and LiteLLM patterns.
- Avoid stale docs overclaims. If a connector is only catalogued or only has an
  auth route, say that.

## Extension Guide

Adding a connector:

1. Add/adjust `CONNECTOR_CATALOG` in `app/api/connectors.py`.
2. Add setup status in `_connector_setup_status()`.
3. Add auth/connect/install/callback route if needed.
4. Ensure connector row is workspace-scoped.
5. Create sync worker in `app/sync/*` that writes `SourceDocument` rows with
   `metadata.workspace_id`.
6. Wire worker in `_run_sync_job()`.
7. Ensure processing summary groups source types correctly.
8. Add frontend catalog/normalizer/UI in `frontend/src/api/hooks.js` and
   `Connectors.jsx`.
9. Add connector tests with mocked provider APIs.

Adding a deterministic source extractor:

1. Add extraction logic in `app/processing/source_extractors.py` or a new module.
2. Add source-type routing in `IngestionService._extract_source_facts()`.
3. Update taxonomy if adding source/fact/relationship types.
4. Preserve provenance and excerpt.
5. Add tests in `tests/test_knowledge_graph.py` and adversarial tests if it can
   create relationships.

Adding graph API fields:

1. Add storage fields in `app/models.py` only if needed.
2. Add startup migration in `app/migrations.py`.
3. Update Pydantic response models and helper serializers in `app/api/graph.py`.
4. Add tests in `tests/test_graph_api.py` or `tests/test_knowledge_graph.py`.
5. Update frontend normalizers and display code.

Adding relationship types:

1. Update `VALID_RELATIONSHIP_TYPES` and aliases in `app/taxonomy.py`.
2. Decide origin semantics in `_determine_origin()`.
3. Update extractors/prompts if the type can be produced.
4. Add graph display label/style only if needed.
5. Add tests for canonicalization, creation, and UI/API serialization.

Adding frontend workflow:

1. Confirm backend route exists or implement it first.
2. Add a hook in `frontend/src/api/hooks.js` only after defining the backend
   contract.
3. Avoid fallback mocks unless the endpoint is intentionally optional and
   `VITE_USE_MOCKS=true` behavior is documented.
4. Verify with `npm run build`; use browser smoke if graph/layout behavior
   changes.

## Current Staleness Notes

These are not future tasks; they are context guards against bad assumptions:

- `instructions.md` is empty as of this audit.
- `README.md`, `replit.md`, and some docs contain older descriptions. Prefer
  code/tests over docs when there is conflict.
- Several docs still describe six tables; current code has seven including
  `Workspace`.
- Older docs said GitHub/Notion backend catalog entries were missing. Current
  code has GitHub in catalog and a guarded Notion connect route, but Notion is
  still not catalogued and has no sync worker.
- Older docs had stale Slack connector status. Current code has Slack OAuth and
  sync worker paths, but provider support should still be described by tested
  end-to-end behavior, not by route presence alone.
- Frontend hooks contain a broader founder workflow product shell than the
  backend currently implements.

## Source Audit

This project brain was built from these repo-local sources:

- `instructions.md`
- `AGENTS.md`
- `README.md`
- `TASK_PLAN.md`
- `replit.md`
- `docs/knowledge-graph-contract.md`
- `docs/knowledge-graph-display-strategy.md`
- `docs/connectors-graph-contract.md`
- `docs/oss-readiness.md`
- `.agent-runs/kimi-task.md`
- `.agent-runs/glm-task.md`
- `.agent-runs/glm-review-report.md`
- `.agent-runs/qwen-task.md`
- `.agent-runs/xiaomi-task.md`
- `.agent-runs/deepseek-task.md`
- `.agent-runs/ai-agents-function-report.md`
- `app/main.py`
- `app/api/*.py`
- `app/models.py`
- `app/config.py`
- `app/database.py`
- `app/migrations.py`
- `app/taxonomy.py`
- `app/services/*.py`
- `app/processing/*.py`
- `app/agents/*.py`
- `app/sync/*.py`
- `app/extract/basic.py`
- `app/importers/*.py`
- `app/cli/*.py`
- `app/mcp/server.py`
- `frontend/src/App.jsx`
- `frontend/src/main.jsx`
- `frontend/src/api/*.js`
- `frontend/src/context/*.jsx`
- `frontend/src/components/Workspace*.jsx`
- `frontend/src/pages/*.jsx`
- `pyproject.toml`
- `frontend/package.json`
- `Dockerfile`
- `docker-compose.yml`
- `scripts/*.sh`
- `tests/*`
