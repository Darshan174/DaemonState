# Architecture

Context Engine is a self-hosted state-of-work service for AI-native builders.
Its job is to reconstruct the current project state from AI coding sessions,
code-host activity, conversations, and documents, then prepare trustworthy
context for the next human or agent action.

The graph is implementation infrastructure. The product output is a project
brief: what happened, what matters, what is blocked, what drifted, and what to
do next.

The core contract is source-backed: every extracted fact starts as a raw
`SourceDocument`, and graph nodes keep enough provenance for users and agents to
audit where a claim came from.

## Runtime Shape

```text
Browser / CLI / MCP
        |
        | HTTP or stdio
        v
FastAPI app
  - API routers: sources, graph, query, connectors, agents, models, repo, demo
  - Static frontend when frontend/dist exists
        |
        v
Services
  - ingestion and extraction
  - query and retrieval trace
  - context pack generation
  - connector sync/import jobs
        |
        v
SQLite by default, PostgreSQL optional
```

The app is intentionally deployable as one process. SQLite is the default path
for local and small-team installs; PostgreSQL is available for larger or hosted
deployments.

## Data Model

The persistent graph has seven main tables:

| Table | Purpose |
|---|---|
| `workspaces` | User-visible workspace/project containers. |
| `connectors` | Workspace-scoped connector state and config. |
| `sync_jobs` | Connector sync attempts, status, and errors. |
| `source_documents` | Raw source evidence from files, providers, and agent sessions. |
| `models` | Semantic buckets such as Decision, Task, Issue, PR, Document. |
| `components` | Atomic extracted facts with status, temporal state, confidence, and provenance. |
| `relationships` | Typed edges with confidence, origin, status, and evidence. |

`SourceDocument` currently stores workspace scope in metadata rather than a
direct foreign key. Use `app/services/workspace_scope.py` for workspace filtering
instead of hand-rolled metadata checks.

## Ingestion Flow

1. A connector, upload, import, or demo seed creates a `SourceDocument`.
2. `IngestionService.process_document()` chooses a deterministic extractor when
   the source supports one.
3. GitHub issues/PRs and AI session sources use deterministic extractors.
4. Other source types use LiteLLM extraction when configured, then regex
   fallback.
5. Extracted facts are upserted as `Component` rows.
6. Relationships are created only when the extracted relationship has enough
   confidence and can resolve to a target component.
7. The source document is marked processed.

## Provenance Rules

- Preserve raw source content before extraction.
- Every important fact should expose `provenance`, `excerpt`, source type, and
  source document ID through graph/query APIs.
- Every relationship should expose `evidence`, `origin`, confidence, and review
  status.
- Do not create a parallel vector-only knowledge base beside the structured
  graph. Retrieval should return graph components and source-backed traces.

## Query And Agent Outputs

`POST /api/query` returns a stable `query.v1` response with retrieval knobs:
`top_k`, `min_confidence`, and optional `hybrid`. The response includes
`trace.facts_used` and relationship expansion evidence.

Context packs are generated from either the full graph or a selected component
plus one-hop neighbors. MCP exposes the same query trace through `query_context`
for AI-agent consumers.

The intended high-level outputs are:

- a current project-state brief;
- blockers, risks, and unresolved work;
- mismatches between agent-session intent and recorded project state;
- source-backed answers to project questions;
- a focused context packet for the next agent run.

## Launch Demo

`POST /api/seed-demo` creates an idempotent workspace seed from launch-available
source families only: GitHub, Slack, Gmail, Google Drive, and Codex. It does not
mark provider connectors as authenticated or connected.
