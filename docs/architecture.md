# Architecture

Context Engine is a self-hosted context compiler for AI-native builders.
Its job is to reconstruct the current project state from AI coding sessions,
code-host activity, conversations, documents, and repo state, then prepare
trustworthy context for the next human or agent action.

The graph is implementation infrastructure. The product output is a project
brief: what happened, what matters, what is blocked, what drifted, and what to
do next.

The core contract is source-backed: every extracted fact starts as a raw
`SourceDocument`, and graph nodes keep enough provenance for users and agents to
audit where a claim came from.

The intended v2 runtime loop is:

```text
prepare context -> agent works -> observe result -> ingest result -> improve next context
```

Observed current behavior in this checkout: the v2 runtime persistence tables,
compiler service, `POST /api/context/prepare`, CLI prepare path, and MCP
observation write tools are present. MCP `prepare_task` calls the compiler
service when importable and reports `compiler_unavailable` only on integration
branches where the service is absent.

`context_pack.v2` is the compiler artifact: markdown for an agent/human plus a
manifest for auditing selected context, excluded context, risks, verification
commands, stop conditions, and rendering metadata.

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
  - legacy context pack generation
  - v2 compiler service, when Agent 3 lands
  - agent run observation bridge
  - connector sync/import jobs
        |
        v
SQLite for bare-metal dev, PostgreSQL/pgvector by default in Docker Compose
```

The app is intentionally deployable as one process for bare-metal development.
SQLite remains the zero-setup local path; Docker Compose and production
deployments use PostgreSQL with pgvector so indexed vector and full-text search
are available.

## Data Model

Observed legacy graph tables:

| Table | Purpose |
|---|---|
| `workspaces` | User-visible workspace/project containers. |
| `connectors` | Workspace-scoped connector state and config. |
| `sync_jobs` | Connector sync attempts, status, and errors. |
| `source_documents` | Raw source evidence from files, providers, and agent sessions. |
| `models` | Semantic buckets such as Decision, Task, Issue, PR, Document. |
| `components` | Atomic extracted facts with status, temporal state, confidence, and provenance. |
| `relationships` | Typed edges with confidence, origin, status, and evidence. |

Observed current behavior: `SourceDocument`, `Component`, and related v2 tables
have direct nullable `workspace_id` columns. Some legacy rows may still carry
workspace hints in metadata, so shared workspace-scope helpers remain the safest
path for mixed data.

Implemented in this branch, v2 adds source-backed runtime and compiler tables:

- `evidence_spans`, `claims`, and `claim_revisions`;
- `context_packs` and `context_pack_items`;
- `agent_runs` and `run_observations`;
- `code_files`, `code_symbols`, `code_edges`, and `repo_events`.

Trust zones separate generated instructions from source evidence. Slack, email,
Drive, web, uploads, and agent-observation text are treated as evidence, not as
instructions to execute.

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
`trace.facts_used`, relationship expansion evidence, and deterministic reranker
features such as exact-match score and query-token coverage. When no embedding
provider is configured, retrieval is explicitly lexical-only rather than
non-semantic hash-vector ranking.

Observed legacy context packs can still be generated from either the full graph
or a selected component plus one-hop neighbors. The v2 path is available through
`POST /api/context/prepare`, `ctxe prepare`, and MCP `prepare_task`, with
remaining hardening focused on final manifest consistency and idempotency.

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
