# Context Engine

Context Engine is an open-source context compiler for AI engineering.

It turns agent runs, pull requests, issues, chats, documents, decisions,
blockers, test output, and repo state into source-backed project context for the
next human or coding agent.

The point is not to chat with a pile of documents. The point is to make project
state explicit: what changed, what is true, what is stale, what is blocked, and
what the next agent must know before it edits code.

```text
messy project reality
  -> source evidence
  -> grounded claims
  -> project graph
  -> model-specific context pack
  -> agent run
  -> new evidence
```

Context Engine is being built for solo founders and small teams who use coding
agents heavily and cannot afford to lose decisions, constraints, failures, and
handoff context between sessions.

It is not enterprise search, a generic knowledge base, or an all-purpose RAG
platform.

## Contents

- [Status](#status)
- [Session References](#session-references)
- [Why It Exists](#why-it-exists)
- [What It Compiles](#what-it-compiles)
- [Technical Commitments](#technical-commitments)
- [Current Implementation](#current-implementation)
- [Product Tour](#product-tour)
- [Developer Surface](#developer-surface)
- [Connectors](#connectors)
- [Repository Map](#repository-map)
- [Setup](#setup)
- [Documentation](#documentation)
- [License](#license)

## Status

Context Engine is under active development. The repository contains real backend,
frontend, CLI, MCP, ingestion, graph, retrieval, compiler, and test code, but it
is not being presented as a polished public install yet.

Setup, deployment, provider configuration, hosted usage, and release packaging
are coming soon.

The README is intentionally describing the technical shape of the project, not
pretending the onboarding path is finished.

## Session References

This README update is grounded in the current codebase plus the maintainer
session references below:

- `019f23d0-0140-7291-aab1-5db5180e26f1`
- `019f2818-a451-7461-ab81-911ae5acf5d1`

The sessions are design and direction references. The source code and tests are
the authority for what is implemented now.

## Why It Exists

Coding agents fail for reasons that are often not raw model intelligence:

- the current repo state is unclear;
- prior decisions are buried in chat logs;
- a blocker was found in one run and forgotten in the next;
- an issue, PR, doc, and agent transcript disagree;
- the next agent starts without knowing which files, tests, and constraints
  matter;
- stale context is treated as current truth.

Context Engine owns that layer. It reconstructs the working state of a project
from source evidence and prepares a narrower, cited task environment for the
next agent.

The intended loop is simple:

```text
prepare context -> agent works -> observe result -> ingest result -> improve next context
```

Every run should leave evidence that makes the next run less ambiguous.

## What It Compiles

The core abstraction is:

```text
sources -> evidence -> claims -> models
```

Raw source material is preserved first. Extraction happens after that. Graph
state, query results, and context packs are projections over evidence, not a
replacement for it.

Context Engine is designed to compile:

- AI coding sessions from Codex, Claude Code, OpenCode, and generic agent logs;
- GitHub issues, pull requests, review discussions, and sync events;
- Slack, Gmail, Google Drive, uploaded files, and local project documents;
- decisions, requirements, tasks, blockers, risks, verification notes, and file
  references;
- current repo state, dirty files, symbols, manifests, tests, and recent commit
  context;
- source-backed context packs for specific coding-agent objectives.

The output is not just an answer. The useful output is a handoff:

- objective;
- current repo state;
- relevant files;
- active blockers;
- non-negotiable decisions;
- implementation constraints;
- verification commands;
- citations and excluded stale context;
- stop conditions for the next agent.

## Technical Commitments

These are the project rules that matter more than UI copy.

1. Source documents come first.
   Raw `SourceDocument` rows are created before extraction. Connectors and
   imports must preserve original content, source type, external ID, URL,
   author, metadata, timestamps, and workspace scope.

2. Evidence has to be inspectable.
   The v2 ledger adds `EvidenceSpan` rows with source ranges, hashes, authority
   weight, trust zone, extraction method, review status, and prompt-injection
   risk. A claim without grounded evidence should stay in `needs_review`, not
   become active truth.

3. Claims and graph nodes are separate ideas.
   `Claim` and `ClaimRevision` track normalized facts and how they changed.
   `Component` remains the graph/UI projection. This keeps legacy graph reads
   working while making the underlying belief history more auditable.

4. Relationships are optional and conservative.
   Edges such as `depends_on`, `blocked_by`, `supersedes`, `contradicts`,
   `implemented_in`, and `touches_file` should come from explicit source
   evidence or deterministic rules. No speculative graph decoration.

5. Retrieval must explain itself.
   `query.v1` includes retrieval strategy, candidate counts, reranker features,
   facts used, relationship evidence, source IDs, provenance, confidence, and
   authority weight. The system should make ranking debuggable.

6. Context packs are contracts, not summaries.
   `context_pack.v2` is designed as two artifacts: readable markdown for an
   agent or human, and a machine-readable manifest for tooling, audit, and
   evals.

7. Agent bridges must stay safe.
   MCP tools can read context and record observed run evidence. They do not edit
   code, run shell commands, push commits, send provider messages, or mark
   unsupported connectors as connected.

8. Unsupported providers stay honest.
   A connector is available only when the backend can create source documents
   from that provider path and tests cover the behavior. Otherwise it is
   `coming_soon`, `disconnected`, or explicitly unsupported.

## Current Implementation

Observed in this checkout:

| Area | State |
|---|---|
| Backend | FastAPI app with async SQLAlchemy models, startup migrations, API routers, static frontend serving, and health checks. |
| Source ingestion | Direct source APIs, bulk ingest, uploads, local file import, AI session import, demo seed, and provider sync paths create `SourceDocument` rows. |
| Extraction | Deterministic GitHub and AI-session extractors, LiteLLM extraction when configured, and regex fallback when no model is available. |
| Evidence ledger | `content_sha256`, trust zones, `EvidenceSpan`, prompt-injection scoring, `Claim`, and `ClaimRevision` are present in the current codebase. |
| Graph | `Model`, `Component`, `Relationship`, `UnresolvedRelationship`, provenance, confidence, authority weight, temporal state, and review status are exposed through graph APIs. |
| Query | `POST /api/query` returns `query.v1` with lexical/vector candidate retrieval, deterministic reranking, entity diversification, facts-used traces, and relationship expansion. |
| Retrieval | Postgres/pgvector and text-search paths exist for indexed retrieval; unconfigured installs fall back to lexical-only behavior instead of pretending hash vectors are semantic search. |
| Context compiler | `ContextCompiler`, model profiles, repo indexing, `POST /api/context/prepare`, `ctxe prepare`, `ContextPack`, and `ContextPackItem` are implemented in the active tree. The v2 manifest is still being hardened before public release. |
| MCP | `ctxe mcp` exposes graph read tools, `prepare_task`, and runtime observation write tools for agent runs, decisions, blockers, patch summaries, verification, and task closure. |
| Frontend | React app with Dashboard, Graph, Ask, Sources, Connectors, Changes, workspace switching, digest cards, graph inspection, connector status, and source review flows. |
| Tests | Backend pytest coverage, frontend Vitest coverage, migration tests, connector honesty tests, query/reranker tests, context compiler tests, MCP tests, extraction evals, and smoke scripts are present. |

This is enough to show the project has a real technical spine. It is not enough
to claim general availability.

## Product Tour

The current app is a working developer surface, not a marketing shell. The main
views are Dashboard, Graph, Ask, Sources, Connectors, and Changes.

The graph and digest surface show how sources feed evidence, evidence supports
claims, and claims assemble into models such as decisions, risks, work, repo
state, connectors, and agent sessions.

The inspector surfaces provenance, source evidence, confidence, relationships,
status, and review state so a developer can understand why the system believes
something.

The Ask surface returns source-backed answers with a visible facts-used trace
instead of a black-box response.

For the current seeded walkthrough, see [Demo Walkthrough](docs/demo.md).

## Developer Surface

The public setup guide is not ready, but the codebase already has the surfaces
that matter for implementation review.

### HTTP API

Important API families:

| Surface | Purpose |
|---|---|
| `/api/sources` | Create, upload, list, inspect, reprocess, and delete source documents. |
| `/api/graph` | Read models, components, relationships, unresolved edges, stats, and source diffs. |
| `/api/query` | Ask grounded project-state questions with `query.v1` traces. |
| `/api/context/prepare` | Compile and persist a `context_pack.v2` for a coding-agent objective. |
| `/api/connectors` | List connector catalog/status, setup state, sync jobs, and guarded provider actions. |
| `/api/seed-demo` | Create a source-backed demo workspace without faking connector authentication. |

### CLI

The `ctxe` command currently contains subcommands for ingest, query, context
preparation, repo indexing, worker sync, extraction evals, database migrations,
credential rotation, graph reads, and MCP server startup.

These commands are implementation surfaces for contributors right now. A stable
public CLI guide is coming soon.

### MCP

The MCP server gives coding agents a structured bridge into Context Engine.

Read tools:

- `prepare_task`
- `query_context`
- `search_nodes`
- `expand_graph`
- `get_model`
- `list_models`
- `get_status`

Runtime observation tools:

- `record_agent_run_start`
- `record_agent_event`
- `record_decision`
- `record_blocker`
- `record_patch_summary`
- `verify_context_item`
- `close_task`

MCP examples live in [examples/mcp](examples/mcp/).

## Connectors

Connector status is deliberately conservative. "Available" means there is a
backend path that can create `SourceDocument` rows from that source when it is
configured. It does not mean public setup documentation is finished.

| Source | Current status | Notes |
|---|---|---|
| Local files | Available | Upload and ingest paths create source documents. |
| AI sessions | Available | Codex, Claude Code, OpenCode, and generic session imports are supported. |
| GitHub | Available | Issues and pull requests sync into source documents. |
| Slack | Available | OAuth/setup-backed sync path exists. Direct fake connect is rejected. |
| Gmail | Available | Google OAuth-backed path exists with mocked sync coverage. |
| Google Drive | Available | Google OAuth-backed path exists with mocked sync coverage. |
| Discord | Coming soon | Catalog stub only. |
| Zoom | Coming soon | OAuth/manual setup routes are guarded until transcript sync exists. |
| Wispr Flow | Coming soon | Catalog stub only. |
| Notion | Not catalogued | Do not describe it as a working connector. |

Demo data is not connector authentication. The demo seed creates example source
documents; it does not mark providers as connected.

## Repository Map

| Path | Purpose |
|---|---|
| `app/main.py` | FastAPI app assembly, startup migration, static frontend serving. |
| `app/api/` | HTTP routers for sources, graph, query, context, repo, connectors, agents, models, and demo seed. |
| `app/models.py` | SQLAlchemy schema for workspaces, sources, evidence, claims, graph, retrieval events, context packs, agent runs, and repo index data. |
| `app/services/` | Ingestion, query, reranking, evidence, claims, compiler, repo indexing, sync worker, auth, credentials, and workspace scope logic. |
| `app/processing/` | Extraction and embedding implementations. |
| `app/sync/` | Provider sync clients for Slack, GitHub, Google, and AI session import helpers. |
| `app/mcp/server.py` | Model Context Protocol server and agent runtime bridge. |
| `app/cli/main.py` | `ctxe` command-line entrypoint. |
| `frontend/src/` | React UI, graph/digest surfaces, API hooks, workspace context, connector pages, and tests. |
| `tests/` | Backend, API, migration, graph, connector, MCP, CLI, compiler, ingestion, and eval coverage. |
| `docs/` | Architecture notes, connector contracts, context-pack contracts, MCP notes, demo walkthrough, and working design documents. |
| `examples/mcp/` | MCP client config examples and an agent grounding prompt. |

## Setup

Coming soon.

The repository has development scripts, Docker files, environment templates, and
smoke checks, but the project is still being built. The public setup path will
be documented after the v2 runtime, manifest contract, connector docs, and fresh
clone smoke path are stable.

Until then, treat Context Engine as source-available alpha software for review
and contribution, not as a finished installable tool.

## Deployment

Coming soon.

Deployment, hosted operation, production database guidance, OAuth provider
configuration, and upgrade procedures are intentionally not documented here yet.

## Contributing

Coming soon.

The contributor workflow will be published once setup and verification are
stable enough that a new contributor can run them from a clean checkout without
guesswork.

## Documentation

Current engineering notes:

- [Architecture](docs/architecture.md)
- [Product Positioning](docs/product-positioning.md)
- [Connectors](docs/connectors.md)
- [Context Pack v2](docs/context-pack-v2.md)
- [Context Compiler v2](docs/context-compiler-v2.md)
- [MCP](docs/mcp.md)
- [AI Context](docs/ai-context.md)
- [Demo Walkthrough](docs/demo.md)
- [MCP examples](examples/mcp/)

Some docs are active design and integration notes rather than final public
manuals. Source code and tests are the authority for implemented behavior.

## License

MIT. See [LICENSE](LICENSE).
