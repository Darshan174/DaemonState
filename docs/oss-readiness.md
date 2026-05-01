# OSS Readiness Review

> **Branch:** `agent/xiaomi-repo-review-docs`
> **Owner:** Xiaomi MiMo V2.5 Pro (long-context repo reader, consistency reviewer, documentation and UX reviewer)
> **Date:** 2026-05-01

---

## OSS Readiness Score: 6/10

### Reasons

| Area | Score | Notes |
|------|-------|-------|
| Core architecture | 8/10 | Clean 4-table model, single-process FastAPI+SQLite, well-structured |
| README / onboarding | 6/10 | Good quick-start but CLI commands untested, data model diagram misleading |
| API surface | 7/10 | Sources, graph, query endpoints work; connector endpoints missing |
| Frontend UX | 5/10 | Connector cards polished but depend on unimplemented backend; GraphView has filter bugs |
| Test coverage | 3/10 | Only `conftest.py` exists in `tests/`; no actual test files |
| Documentation | 4/10 | Kimi contract doc is strong; no contributor guide, no connector dev guide |
| CI/CD | 2/10 | No GitHub Actions workflows found |
| License | 0/10 | No LICENSE file |
| .env.example | 5/10 | Exists but not verified against all required vars |

---

## Top Findings (Ordered by Severity)

### P0 — Blocking for OSS launch

1. **No LICENSE file.** OSS projects require an explicit license. Without one, the code is "all rights reserved" by default.

2. **No test files.** `tests/` contains only `conftest.py` (96 lines of fixtures). Zero actual test functions exist. The `pyproject.toml` configures pytest but there is nothing to run.

3. **No CI pipeline.** `.github/` directory is empty or absent. No GitHub Actions for lint, test, or build verification.

### P1 — High priority

4. **Connector backend does not exist.** `app/api/router.py:5` imports `sources, graph, query, repo` — no `connectors` module. The frontend `Connectors.jsx` (1155 lines) renders connector cards, OAuth flows, sync job UI, and manual token forms, but all API calls to `/api/connectors/*` will 404. The `useConnectors` hook falls back to mock data only when `VITE_USE_MOCKS=true`.

5. **Frontend `source_type` filter is broken.** `GraphView.jsx:74` filters components by `c.source_type`, but `ComponentRead` in `graph.py:28-40` does not include `source_type`. The filter dropdown renders but never matches anything.

6. **`project.md` has a typo.** Line 82: `cdxe ingest ./docs/` should be `ctxe ingest ./docs/`.

7. **README data model diagram is misleading.** Lines 87-92 show `Model ──► Component ──► Relationship` with `SourceDocument` pointing up to both, but the actual FK is `Component.source_document_id → SourceDocument` and `Component.model_id → Model`. The diagram implies `SourceDocument` has FKs to `Model` and `Component`, which is backwards.

8. **No workspace scoping in backend.** The frontend hooks (`hooks.js:151-167`) resolve a `workspace_id` and pass it to API calls, but no backend model has a `workspace_id` column. Every API call with `?workspace_id=X` will ignore the parameter.

### P2 — Medium priority

9. **`GraphView.jsx` fetches `/api/repo/graph` for repo view mode** (line 50), but `app/api/repo.py` is imported in `router.py` without being read. The repo graph endpoint may not return the shape the frontend expects (`nodes` and `edges` arrays vs `models`, `components`, `relationships`).

10. **Frontend camelCase/snake_case drift.** `hooks.js` destructures `resultMetadata`, `jobId`, `createdAt` (camelCase) from sync job responses, but the backend uses snake_case. The `normalizeSyncJob` function is referenced but its implementation is deep in the hooks file and may not cover all fields.

11. **`SourceManager.jsx` uses raw `fetch` instead of the API client.** Lines 18-21 call `fetch("/api/sources")` directly rather than using `api.get()` from `frontend/src/api/client.js`. This bypasses error handling, auth headers, and base URL configuration.

12. **MCP server loads all active components into memory.** `app/mcp/server.py:146-151` — `_search_nodes` fetches every active component with `select(Component).where(Component.status == "active")` then scores them in Python. This will not scale past a few thousand components.

13. **Extractor silently swallows LLM errors.** `app/processing/extractor.py:57-59` — the `except Exception: pass` in `extract()` means any LLM failure (auth, rate limit, malformed JSON) silently falls back to regex extraction with no logging.

### P3 — Low priority / polish

14. **`Connectors.jsx` imports `useConnectGitHub`, `useConnectZoom`, `useConnectNotion`, `useSaveSlackOAuthSettings`** (lines 3-7) but these hooks are not visible in the read portion of `hooks.js`. They may exist further in the file (which was capped at 1551 lines) or may be missing.

15. **`mockData.js` references `gong` connector** (line 378) but `CONNECTOR_CATALOG` in `hooks.js` does not include Gong. Mock data and catalog are out of sync.

16. **`pyproject.toml` version is `0.2.0`** but README has no version badge or changelog. Consider adding a `CHANGELOG.md` or at least a version reference in README.

17. **Docker setup unverified.** `Dockerfile` and `docker-compose.yml` exist but their contents were not reviewed in this pass. A fresh `docker compose up --build` test is recommended before OSS launch.

---

## Evidence Files Reviewed

| File | Lines | Key Observations |
|------|-------|-----------------|
| `AGENTS.md` | 72 | Agent roles, anti-hallucination rules, review standard |
| `TASK_PLAN.md` | 182 | Feature scope, branch assignments, acceptance criteria |
| `.agent-runs/xiaomi-task.md` | 120 | This agent's task definition |
| `README.md` | 110 | Quick start, API table, data model, deployment |
| `project.md` | 120 | Architecture, tech stack, current status |
| `app/models.py` | 131 | 4 SQLAlchemy models: SourceDocument, Model, Component, Relationship |
| `app/api/graph.py` | 205 | Graph read, stats, timeline, component patch |
| `app/api/sources.py` | 151 | Source CRUD, bulk upload, file upload |
| `app/api/query.py` | 59 | Query endpoint |
| `app/api/router.py` | 11 | Wires sources, graph, query, repo — no connectors |
| `app/services/ingest.py` | 131 | IngestionService: extract, embed, create relationships |
| `app/processing/extractor.py` | 145 | LLM + regex extraction, ExtractedFact dataclass |
| `app/mcp/server.py` | 408 | MCP server: 5 tools (search, expand, get_model, list_models, get_status) |
| `frontend/src/api/hooks.js` | 1551+ | React Query hooks, connector catalog, mock fallbacks |
| `frontend/src/pages/Connectors.jsx` | 1259+ | Connector cards, OAuth flow, sync job UI |
| `frontend/src/pages/GraphView.jsx` | 522 | Cytoscape graph, knowledge/repo view modes, filters |
| `frontend/src/pages/SourceManager.jsx` | 288 | Source upload, list, detail panel |
| `frontend/src/fixtures/mockData.js` | 901 | Dashboard stats, connectors, sources, review queue, eval cases |
| `docs/connectors-graph-contract.md` | 486 | Kimi's connector/graph API contract |
| `tests/conftest.py` | 96 | Test fixtures (no actual tests) |
| `pyproject.toml` | 43 | Build config, dependencies, pytest config |

---

## Kimi Contract Review

`docs/connectors-graph-contract.md` is thorough and well-structured. Key observations:

- **Section 1.1** correctly identifies that `Connectors.jsx` destructures ~25 fields from each connector object. The proposed backend schema matches.
- **Section 2.4** (AI Context) proposes `POST /api/connectors/ai-context/import`. This is a clean design that reuses `SourceDocument` + `IngestionService`. **Recommended.**
- **Section 7.1 item 4** correctly identifies that `_create_relationship` in `ingest.py:98-102` restricts target lookup to the same `model_id`. Cross-model relationships should be allowed.
- **Section 9.1** correctly identifies that `ComponentRead` lacks `source_type` while `GraphView.jsx` filters on it.
- **Section 13** implementation order is reasonable: GLM connectors first, then DeepSeek graph fixes, then Xiaomi review.
- **Risk 1** (workspace scoping) is the biggest unresolved question. Adding `workspace_id` to models is a schema migration that affects every query.

---

## UX Review

### Connectors Page

**Observed:** `Connectors.jsx` is a mature, well-structured component with:
- Status pills for `connected`, `disconnected`, `warning`, `error`, `coming_soon`
- Provider badges (`native`, `dlt`, `unstructured`, `official_api`)
- Self-hosted quick-path guide (3 steps)
- Manual token forms for Notion, Zoom, GitHub
- Slack OAuth popup polling
- Sync job status with polling
- Processing summary per connector

**Issues:**
- All connector actions are disabled in demo mode (`isMock`), which is correct, but the transition from demo to live is not clearly communicated when the backend lands.
- The `SlackOAuthSettingsForm` component (referenced but not fully visible) requires `client_id`, `client_secret`, `redirect_uri` — good for self-hosted, but the form UX should validate before submit.
- Error/notice banners at lines 276-285 are simple `<div>` elements. They should be `role="alert"` for accessibility.

### Graph Page

**Observed:** `GraphView.jsx` uses Cytoscape.js with:
- Knowledge view (models → components → relationships)
- Repository view (repo → areas → files → technologies)
- Filter dropdowns for model, source_type, status
- Node detail panel with confidence, status, connected nodes

**Issues:**
- The `source_type` filter will never match because `ComponentRead` doesn't include the field. This is a known bug (Finding #5).
- Empty graph state (line 383-392) shows a loading spinner, but if the graph loads with zero nodes, the user sees a blank canvas with no guidance.
- The repo view mode calls `/api/repo/graph` which may return a different shape than `/api/graph`. The `filteredData` function (line 63-86) handles `viewMode === "repo"` by returning `graphData` directly, but the Cytoscape rendering (lines 102-134) expects `viewData.nodes` and `viewData.edges` arrays, while the knowledge view expects `viewData.models`, `viewData.components`, `viewDatarelationships`.

### Source Manager

**Observed:** `SourceManager.jsx` is simpler and uses raw `fetch`. It supports:
- File upload via drag-and-drop or file picker
- Source list with type badges and processed/pending status
- Source detail panel with content preview and extracted components

**Issues:**
- Uses raw `fetch` instead of the shared API client (Finding #11).
- No error retry or loading states beyond a simple spinner.
- The file accept list (line 136) includes `.pdf` but the backend `SourceCreate` expects string content — PDFs will fail to parse as UTF-8.

---

## Recommendations for Codex

1. **Add a LICENSE file** (MIT or Apache 2.0) before any public release.
2. **Write at least 5 integration tests** covering: source creation, ingestion, graph query, MCP tools, and component status update. The `conftest.py` fixtures are ready.
3. **Add a GitHub Actions workflow** for `ruff check` + `pytest` on push/PR.
4. **Decide on workspace scoping** before GLM builds connectors. If single-tenant is OK for v0.2, document it clearly.
5. **Fix the `source_type` gap** — either add `source_type` to `ComponentRead` (derive from `SourceDocument.source_type` at query time) or remove the filter from `GraphView.jsx`.
6. **Fix `project.md` typo** (`cdxe` → `ctxe`).
7. **Fix README data model diagram** to match actual FK directions.
8. **Verify Docker build** with a clean `docker compose up --build`.

---

## Files Changed

- `docs/oss-readiness.md` — this file (new)

## Tests Run

No tests were run because no test files exist. The `conftest.py` fixture infrastructure was reviewed and is correct.

## Assumptions

- The GLM and DeepSeek branches have not been merged yet; this review covers the current state of the main/feature branches.
- The `hooks.js` file extends beyond line 1551 (output was capped); some hooks may exist but were not visible.
- The `Dockerfile` and `docker-compose.yml` were not read in this pass.

## Risks

- Connector UI is production-quality but has no backend — OSS users will hit 404s immediately.
- No tests means regressions from GLM/DeepSeek changes will not be caught.
- Workspace scoping decision blocks connector implementation.
