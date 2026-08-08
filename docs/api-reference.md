# HTTP API reference

DaemonState exposes a FastAPI service under `/api`. When API documentation is
enabled, the exact schema for the running build is available at:

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI JSON: `/openapi.json`

The production profile disables all three. This document describes the stable
endpoint families and safety boundaries; use the generated OpenAPI document for
complete request/response field schemas.

## Base URL

Local workstation and personal Docker installs default to:

```text
http://127.0.0.1:8000
```

API paths below are relative to that origin. The hardened profile serves an
HTTPS hostname through Caddy and does not serve the browser dashboard.

## Authentication

When neither `SERVER_API_KEY` nor `PRINCIPAL_API_KEYS` is configured, requests
run in trusted local/unrestricted scope. Keep that mode loopback-only.

When authentication is enabled, send one of:

```http
Authorization: Bearer <token>
```

```http
X-DaemonState-API-Key: <token>
```

```http
X-API-Key: <token>
```

`SERVER_API_KEY` receives unrestricted administrator scope. A token from
`PRINCIPAL_API_KEYS` receives its server-configured `principal_id` and
workspace membership. Restricted sources also require a read grant whose
permission snapshot still matches the current source revision.

The current production profile deliberately rejects `PRINCIPAL_API_KEYS`; it is
a single-tenant API until action-level authorization covers every mutation.

### Public exceptions

The following requests bypass normal API-key authentication so their specific
flows can complete:

- `POST /api/waitlist`
- registered OAuth callback paths for Slack and Google connectors

OAuth state is still connector-bound, short-lived, encrypted, and single-use.

## Request controls

- Request bodies are limited by `MAX_REQUEST_BODY_BYTES` (16 MiB by default).
- Host headers are checked against `ALLOWED_HOSTS` when an explicit allowlist is
  configured.
- CORS is disabled unless origins are listed in `CORS_ALLOWED_ORIGINS`.
- General and failed-authentication rate limits are applied when configured.
- Every response receives `X-Request-ID`. A caller-supplied ID is accepted only
  when it matches `[A-Za-z0-9._-]{1,128}`; otherwise the server creates one.
- Security headers include `nosniff`, no-referrer, a restrictive permissions
  policy, and a frame/object/base CSP. Production also sends HSTS.
- Naive database timestamp fields ending in `_at`/`At` are serialized with a
  trailing `Z` to make their UTC meaning explicit.

## Errors

Endpoint validation errors normally use FastAPI's `422` response. Domain
errors may return a string detail or a structured detail:

```json
{
  "detail": {
    "code": "context_budget_too_small",
    "message": "minimum required context cannot fit the rendered token budget",
    "minimum_required_tokens": 712
  }
}
```

Common status codes:

| Status | Meaning |
|---:|---|
| `400` | Unsupported connector/action or malformed domain request. |
| `401` | Missing or invalid API key. |
| `403` | Authenticated principal lacks an operation boundary, especially a local-only action. |
| `404` | Record not found or intentionally hidden outside the caller's workspace/source scope. |
| `409` | Current state conflicts with the requested transition, such as deleting an active workspace or using an unavailable checkpoint. |
| `422` | Schema, path, budget, focus, or continuation validation failed. |
| `429` | Rate limit exceeded; inspect `Retry-After` and rate-limit headers. |
| `503` | Readiness or fail-closed distributed request controls are unavailable. |
| `504` | A bounded desktop handoff timed out with an explicitly uncertain dispatch outcome. |

Unhandled errors use a non-sensitive shape and include the request ID:

```json
{
  "error": {
    "code": "internal_error",
    "message": "An internal error occurred.",
    "request_id": "..."
  }
}
```

## Health and metrics

These routes are outside `/api`:

| Method and path | Purpose |
|---|---|
| `GET /health` | Liveness; returns `{"status":"ok"}` once the process can serve HTTP. |
| `GET /health/startup` | Startup state; returns `503` with `starting` until lifespan initialization completes. |
| `GET /health/ready` | Database connectivity/schema, rate-limit backend, and production credential-store readiness. Returns `503` when any required dependency is not ready. |
| `GET /metrics` | Prometheus metrics when enabled. Uses its own `METRICS_BEARER_TOKEN`, not the API key. Not included in OpenAPI. |

## First workspace example

Create a workspace:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/workspaces \
  -H 'content-type: application/json' \
  -d '{"name":"My Project","kind":"project"}'
```

Then index one repository into the returned workspace ID:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/repo/index \
  -H 'content-type: application/json' \
  -d '{
    "workspace_id":"<workspace-uuid>",
    "repo_path":"/absolute/path/to/project"
  }'
```

The repository path must exist, be inside `ALLOWED_REPO_ROOTS` when configured,
look like a project root (`.git` or a supported manifest), and contain supported
files. Successful indexing persists code structure and a source-first project
inventory.

## Workspaces and goals

| Method and path | Purpose |
|---|---|
| `GET /api/workspaces?include_archived=false` | List visible workspaces with counts and indexed repository roots. |
| `POST /api/workspaces` | Create a `project`, `demo`, or `sandbox` workspace. Restricted principals cannot create workspaces. |
| `PATCH /api/workspaces/{workspace_id}` | Rename, archive/restore, or change workspace kind. Archiving is blocked while a run is active. |
| `DELETE /api/workspaces/{workspace_id}?confirm_name=...` | Permanently delete an already archived workspace and its graph. Exact name confirmation and no active run are required. |
| `PUT /api/workspaces/{workspace_id}/current-goal` | Create/replace the explicit current workspace goal. |
| `DELETE /api/workspaces/{workspace_id}/current-goal` | Clear the explicit current goal. |

Workspace deletion is destructive. The UI requires archive first and shows
source/fact/run counts before exact-name confirmation.

## Repository, query, and context compilation

| Method and path | Purpose |
|---|---|
| `POST /api/repo/index` | Validate and persist a bounded repository index and source inventory. |
| `POST /api/query` | Return a `query.v1` answer, components, sources, confidence, retrieval trace, and optional live lanes. |
| `POST /api/context/prepare` | Compile and persist `context_pack.v2` for a task or objective-independent project snapshot. |
| `GET /api/context/claims/{claim_id}/timeline` | Read bi-temporal claim revisions, current status, evidence, and conflict state. |
| `GET /api/context/open-loops` | List unresolved work for a workspace. |
| `PATCH /api/context/open-loops/{loop_id}` | Dismiss, resolve, reopen, or assign an open loop with a reason. |
| `GET /api/context/playbooks` | List derived playbook candidates/current playbooks. |
| `PATCH /api/context/playbooks/{playbook_id}` | Approve or disable a playbook with a reason. |
| `GET /api/context/run-timeline` | Read source-authorized run and observation history. |
| `GET /api/context/run-outcomes` | Summarize measured run outcomes. |
| `GET /api/context/digest` | Return the selected workspace's current goal, activity, memory, attention, scope, and recent session projection. |
| `GET /api/context/memory` | Read project-memory sections and trust states. |
| `PATCH /api/context/memory/{component_id}` | Apply a supported memory review/lifecycle action. |

### Task context example

```bash
curl -sS -X POST http://127.0.0.1:8000/api/context/prepare \
  -H 'content-type: application/json' \
  -d '{
    "workspace_id":"<workspace-uuid>",
    "repo_path":"/absolute/path/to/project",
    "objective":"fix the failing import flow",
    "mode":"task",
    "objective_origin":"trusted_human",
    "target_model":"general-coder",
    "token_budget":6000
  }'
```

The response includes the context pack ID, schema, Markdown, full manifest,
health score, selected/excluded context, and focus metadata.

### Workspace Context example

```bash
curl -sS -X POST http://127.0.0.1:8000/api/context/prepare \
  -H 'content-type: application/json' \
  -d '{
    "workspace_id":"<workspace-uuid>",
    "repo_path":"/absolute/path/to/project",
    "mode":"project_snapshot",
    "objective_origin":"project_snapshot"
  }'
```

Project-snapshot mode accepts no selected task/session continuation state. The
manifest contains `workspace_foundation` with the typed
`workspace_foundation.v2` payload, semantic/artifact hashes, repository binding,
and quality report. Compilation reads bounded evidence and never executes
repository commands.

### Query example

```bash
curl -sS -X POST http://127.0.0.1:8000/api/query \
  -H 'content-type: application/json' \
  -d '{
    "workspace_id":"<workspace-uuid>",
    "question":"What is blocking the release?",
    "retrieval_mode":"combined",
    "live_sources":["local_repo"],
    "repo_path":"/absolute/path/to/project"
  }'
```

Live lanes are bounded and never hide whether a fact came from indexed or live
retrieval.

## Checkpoints and Session Context

| Method and path | Purpose |
|---|---|
| `GET /api/checkpoints` | List authorized checkpoints, optionally filtered by provider/session and bounded by `limit` (1-100). |
| `GET /api/checkpoints/latest` | Read the latest compatible checkpoint globally or for one provider/session. |
| `GET /api/checkpoints/session-context-eligibility` | Report whether a session satisfies the current direct Session Context gate. |
| `GET /api/checkpoints/{checkpoint_id}` | Read one authorized checkpoint. |
| `POST /api/checkpoints/capture` | Capture an exact provider/session boundary or current tip. |
| `POST /api/checkpoints/{checkpoint_id}/verify` | Reconcile a checkpoint with current evidence. `execute_commands=true` is not permission to replay imported commands. |
| `GET /api/checkpoints/{checkpoint_id}/compare` | Compare two/current checkpoint views as supported by query parameters. |
| `POST /api/checkpoints/{checkpoint_id}/resume` | Prepare a checkpoint resume contract and optionally request a supported launch. |
| `POST /api/checkpoints/{checkpoint_id}/handoff` | Produce the visible, hash-bound `session_handoff.v1` artifact for copy/preview. |
| `GET /api/session-continuity` | Read normalized session ledgers, optionally filtered by provider/session. |
| `POST /api/session-continuity/continue` | Build recovered context for an exact source document. |

Direct Session Context copy applies source authorization, exact session and
boundary identity, repository freshness, attachment, schema, integrity, and
quality gates.

## Session Library

| Method and path | Purpose |
|---|---|
| `GET /api/session-library` | List/search current project-scoped imported sessions and topics. |
| `POST /api/session-library/sync` | Discover and incrementally ingest local Codex/Claude/OpenCode history. Workstation/local scope only in practice. |
| `POST /api/session-library/latest` | Narrow newest-session discovery used by Continue; omits the historical library. |
| `POST /api/session-library/open` | Request opening an exact supported local provider session. |
| `POST /api/session-library/checkpoints/restore` | Restore an exact captured provider-compaction boundary. |
| `PUT /api/session-library/selection` | Store an explicit historical selection for supported preparation workflows. |
| `DELETE /api/session-library/selection` | Clear that selection. It never changes Continue's latest-session rule. |

The full library and latest-session endpoint have different latency and product
contracts. Continue does not wait for a full historical sync.

## Continuation

| Method and path | Scope | Purpose |
|---|---|---|
| `GET /api/continuations/providers` | Loopback + local principal | Read desktop/provider readiness, active run, staged handoff, and latest outcome. |
| `POST /api/continuations/prepare` | Remote-safe only when local sync/artifacts are off | Resolve task/checkpoint and compile the audit pack plus canonical execution contract without starting a provider. |
| `POST /api/continuations/stage` | Loopback | Compile/copy Session Context and request a visible desktop composer without submitting a turn. |
| `POST /api/continuations` | Loopback | Start and observe a local provider CLI continuation. |
| `POST /api/continuations/run` | Loopback | Compatibility alias of `POST /api/continuations`. |
| `POST /api/continuations/{run_id}/open` | Loopback + local principal | Open the provider session reported by an existing continuation run. |

`prepare` rejects `execute_commands=true`: commands imported from a session are
evidence, not trusted instructions. `stage` and `run` accept an idempotency key.
Stage never creates a provider turn or `AgentRun`; run does.

Local-only endpoints validate the peer address instead of trusting forwarded
headers. Do not expose them through a public reverse proxy.

## Sources and revisions

| Method and path | Purpose |
|---|---|
| `POST /api/sources?sync=false` | Create or deduplicate one immutable source revision. |
| `POST /api/sources/bulk?sync=false` | Create/deduplicate multiple revisions. |
| `POST /api/sources/upload?workspace_id=...` | Upload one text-decodable file as a local source. |
| `GET /api/sources?workspace_id=...` | List authorized current source records. |
| `GET /api/sources/{source_id}` | Read authorized raw content, metadata, and extracted components. |
| `GET /api/source-documents` | Paginated source-document projection used by model/inspection views. |
| `GET /api/graph/source-diff/{source_id}` | Compare raw source and extracted knowledge. |
| `GET /api/source-documents/{source_id}/diff` | Read source revision differences. |

In production, ingestion remains durable/worker-driven even when a caller asks
for synchronous processing. Local development may process inline or in a
background task.

Example:

```bash
curl -sS -X POST 'http://127.0.0.1:8000/api/sources?sync=true' \
  -H 'content-type: application/json' \
  -d '{
    "workspace_id":"<workspace-uuid>",
    "source_type":"local",
    "external_id":"architecture-notes",
    "content":"Decision: keep ingestion source-first.",
    "metadata":{"title":"Architecture notes"}
  }'
```

## Graph, models, and agents

| Method and path | Purpose |
|---|---|
| `GET /api/graph` | Read the source-backed graph projection. |
| `POST /api/graph/slice` | Return a bounded filtered graph slice. |
| `POST /api/graph/build` | Process/rebuild supported current sources. It does not sync external providers. |
| `GET /api/graph/agent-status` | Read graph-build agent status. |
| `GET /api/stats` | Aggregate model/component/relationship stats. |
| `GET /api/timeline` | Read graph timeline projection. |
| `GET /api/components/{component_id}` | Component inspector with source/provenance. |
| `PATCH /api/components/{component_id}` | Apply supported component review edits. |
| `GET /api/relationships/{relationship_id}` | Relationship inspector with evidence and origin. |
| `PATCH /api/relationships/{relationship_id}/review` | Review/accept/reject a relationship under the schema contract. |
| `GET /api/work-lens` | Read work-focused graph projection. |
| `GET /api/models` | List semantic model buckets. |
| `GET /api/models/{model_id}` | Read one model and its components. |
| `GET /api/models/{model_id}/relationships` | Read relationships for one model. |
| `POST /api/agents/gaps` | Generate deterministic/model-assisted gap output under prompt quality rules. |
| `POST /api/agents/context-pack` | Generate a legacy graph context pack. Prefer `/api/context/prepare` for the v2 compiler path. |
| `POST /api/agents/relationships` | Generate relationship suggestions/report under evidence rules. |

Graph-zone placement is presentation, not a factual edge. Clients must use the
relationship list and its evidence rather than infer links from layout.

## Connectors

| Method and path | Purpose |
|---|---|
| `GET /api/connectors` | Read the full catalog plus workspace connection state. |
| `GET /api/connectors/setup-status` | Read configuration readiness for every catalogued connector. |
| `GET /api/connectors/processing-summary` | Read per-source processed/unprocessed counts. |
| Slack/Google install and callback routes | Begin/complete configured OAuth with state and PKCE where applicable. |
| `POST /api/connectors/github/connect` | Store an encrypted personal access token and repository targets. |
| `POST /api/connectors/ai-context/import` | Import one or more raw AI-context documents. |
| `POST /api/connectors/ai-session/ingest` | Create/update and immediately process one supported agent session. |
| `POST /api/connectors/ai-session/import-by-id` | Import by provider ID only when the local adapter can resolve the actual content. |
| `POST /api/connectors/ai-session/refresh-linked` | Refresh linked local session revisions. |
| `POST /api/connectors/{connector_id}/sync` | Queue an available connector sync job. |
| `GET /api/connectors/{connector_id}/sync-status` | Read current/last job status. |
| `GET /api/connectors/{connector_id}/sync-jobs` | Read bounded job history. |
| `DELETE /api/connectors/{connector_id}` | Disconnect and delete stored credentials; Slack also attempts token revocation. |

Available backend connectors are GitHub, Slack, Gmail, Google Drive, local
files, AI Context, Codex, Claude, and OpenCode. Discord, Zoom, and Wispr Flow
return coming-soon/unsupported behavior. The Notion compatibility route rejects
setup because Notion is not catalogued.

## Prompt snippets, desktop control, demo, and waitlist

| Method and path | Purpose |
|---|---|
| `GET /api/workspaces/{workspace_id}/prompt-snippets` | List saved prompt snippets. |
| `POST /api/workspaces/{workspace_id}/prompt-snippets` | Create a bounded snippet. |
| `POST /api/workspaces/{workspace_id}/prompt-snippets/usage` | Record selected snippet usage. |
| `DELETE /api/workspaces/{workspace_id}/prompt-snippets/{snippet_id}` | Delete a snippet. |
| `GET /api/desktop/overlay` | Loopback/local status for the optional macOS floating control. |
| `PUT /api/desktop/overlay` | Show/hide the token-bound native control for a workspace. |
| `POST /api/seed-demo` | Idempotently create the credential-free sample workspace when demo endpoints are enabled. |
| `POST /api/waitlist` | Public waitlist form endpoint used by waitlist-only frontend builds. |

The overlay API verifies the native process PID, command line, control token,
state file, workspace, and loopback URL. It never accepts a caller-supplied
executable or arbitrary process ID.

## API compatibility guidance

- Check `schema_version` on query, context, handoff, foundation, and runtime
  artifacts.
- Treat new response fields as additive unless a versioned contract says
  otherwise.
- Do not infer current provider state from imported timestamps or graph status.
- Do not infer permissions from workspace IDs supplied in request JSON; scope
  comes from the authenticated server-side principal.
- Preserve `X-Request-ID` with bug reports and operator logs.
- For long-running production ingestion, poll sync/job state rather than
  assuming a `201` means extraction is already complete.
