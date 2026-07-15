# Context Engine

Context Engine is an open-source project oversight and context layer for people
building software with coding agents.

It gives a founder or small team one source-backed view of the project: what the
system contains, what agents changed, which decisions still apply, what is
blocked or unverified, and what the next agent needs before touching the code.

Then it compiles that state into a focused agent brief with relevant files,
constraints, risks, verification commands, citations, and explicit exclusions.

```text
repo + issues + PRs + agent runs + documents
                    ↓
        source-backed project state
                    ↓
      oversight, gaps, and open loops
                    ↓
          focused agent brief
                    ↓
       observed work and verification
```

Context Engine is not another chat interface over company documents. The product
is the project view, the scrutiny trail, and the clean handoff into the next run.

## Contents

- [Status](#status)
- [Why It Exists](#why-it-exists)
- [What You Can Do Today](#what-you-can-do-today)
- [How the Product Loop Works](#how-the-product-loop-works)
- [Honest Limits](#honest-limits)
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

Context Engine is an active alpha. The project has a working FastAPI backend,
React application, CLI, MCP server, repository compiler, evidence ledger,
retrieval system, agent-run observation loop, and automated test suite.

The product workflow is implemented; public onboarding and self-hosting guidance
are not finished. The [Setup](#setup) and [Deployment](#deployment) sections are
therefore intentionally brief instead of presenting an unverified install path.

## Why It Exists

Coding agents often fail for reasons unrelated to model intelligence:

- the current repo state is unclear;
- prior decisions are buried in chat logs;
- a blocker was found in one run and forgotten in the next;
- an issue, PR, doc, and agent transcript disagree;
- the next agent starts without knowing which files, tests, and constraints
  matter;
- stale context is treated as current truth;
- an agent claims completion while a required check failed or was never run;
- a non-technical founder cannot tell whether progress is real or merely plausible.

Context Engine owns this missing control layer. It reconstructs current project
state from source evidence, makes gaps and contradictions visible, and prepares a
narrower task environment for the next agent.

The goal is not to replace the coding agent. It is to give the user eyes across
agents and give every new run the context earned by the previous one.

## What You Can Do Today

### See the project from above

Open a local repository and inspect a project map organized around the questions
a founder actually has:

- **System:** what the repository contains;
- **Direction:** current, source-backed decisions;
- **Delivery:** observed pull requests;
- **Risks:** issues and blockers;
- **Next:** explicit verified tasks;
- **Docs and evidence:** supporting records and confirmed document gaps.

Cards retain their source, revision, confidence, freshness, and relationships.
Empty lanes say what evidence is missing instead of fabricating a complete view.

### Scrutinize agent work

For a prepared task, the inspector reconstructs the agent run from recorded
events: decisions, blockers, patches, verification results, and the claimed
outcome. Deterministic scrutiny rules currently surface:

- required verification that is missing or failed;
- unresolved recorded blockers;
- required context with no completion evidence;
- a claimed outcome that conflicts with a recorded check;
- a task prepared from an older source revision.

Every finding links back to evidence. Context Engine does not ask another model to
invent criticism and present it as fact.

### Keep unfinished work visible

Supported scrutiny findings become durable **open loops**. A user can inspect the
evidence, assign the loop, resolve it, or dismiss it. Every state change requires a
reason so silent dismissal does not erase the audit trail. The API also supports
audited reopening when a resolved finding becomes relevant again.

### Prepare the next agent

Select an eligible issue, task, decision, requirement, or blocker and choose
**Prepare for agent**. Context Engine creates `context_pack.v2` as:

- readable Markdown for the human or agent;
- a machine-readable manifest for replay, audit, and evaluation.

The inspector shows how many source-backed items were selected, lets the user view
the full brief, and copies it to the clipboard. It also shows evidence-backed
affected files, linked tests, known blockers, required checks, and any compatible
approved playbook.

Nothing is sent to an agent automatically. The user reviews the brief and pastes
it into the coding agent they choose.

### Reuse only verified agent procedures

When a completed run passes every required verification, Context Engine can
extract reusable steps as a reviewable playbook. A playbook must be approved and
compatible with the current repository snapshot before it can guide a later
agent. One successful transcript never becomes trusted procedure automatically.

## How the Product Loop Works

```text
1. Capture evidence
   repository state, issues, PRs, agent sessions, documents, run events

2. Compile project state
   source revisions -> evidence spans -> claims -> conservative graph projection

3. Prepare a task
   objective -> relevant context -> affected code -> checks -> agent brief

4. Observe execution
   run start -> decisions/blockers/patch -> verification -> outcome

5. Scrutinize and learn
   findings -> open loops -> approved verified playbooks -> better next brief
```

Each run should leave inspectable evidence that makes the next run less ambiguous.

## Honest Limits

- Context Engine does not currently launch, control, or grant code-editing access
  to a coding agent. It prepares context and observes explicitly recorded work.
- “Prepare for agent” creates and copies a brief; it does not send the brief.
- Scrutiny is limited to deterministic, evidence-backed rules. It is not a generic
  “slop score” or an autonomous code reviewer.
- Live retrieval is currently bounded to the local repository and configured
  manual-token GitHub access. Unsupported live providers fail explicitly.
- The graph is an internal evidence projection and inspection tool, not the
  primary user workflow.
- Public setup, hosted operation, and production deployment guidance are not ready.

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
   authority weight. Indexed, live, and combined modes report each requested live
   lane honestly; live failures do not silently fall back to saved context.

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
| Evidence ledger | `content_sha256`, workspace-scoped source identity, append-only source revisions, trust zones, exact `EvidenceSpan` validation, prompt-injection scoring, `Claim`, and `ClaimRevision` are present in the current codebase. |
| Temporal truth and access | Claim revisions carry validity and transaction/observation time with as-of reads. Source/evidence permission snapshots and server-bound principal scopes filter evidence before retrieval and context compilation. |
| Graph | `Model`, `Component`, `Relationship`, `UnresolvedRelationship`, provenance, confidence, authority weight, temporal state, and review status are exposed through graph APIs. |
| Query | `POST /api/query` returns `query.v1` with lexical/vector candidate retrieval, deterministic reranking, entity diversification, facts-used traces, relationship expansion, and explicit `indexed`, `live`, or `combined` retrieval. Initial live adapters are bounded local-repository search and configured manual-token GitHub search. |
| Retrieval | Postgres/pgvector and text-search paths exist for indexed retrieval; unconfigured installs fall back to lexical-only behavior instead of pretending hash vectors are semantic search. Live provider results enter immutable source revisions before use. |
| Context compiler | `ContextCompiler`, model profiles, incremental file/symbol indexing, exact import/route/test-path/test-symbol edges, focused affected-code output, approved compatible playbooks, rendered-budget enforcement, the replay lockfile, `POST /api/context/prepare`, `ctxe prepare`, `ContextPack`, and `ContextPackItem` are implemented in the active tree. |
| Learning loop | Deterministic founder-scrutiny findings persist as source-backed open loops. Completed runs with every required verification passing can create reviewable playbooks; they are never auto-used from one unreviewed run. |
| Passive capture | `ctxe repo watch` records bounded, redacted repository-change events and triggers incremental indexing without capturing raw terminal streams or file contents. |
| MCP | `ctxe mcp` exposes graph read tools, `prepare_task`, indexed/live/combined `query_context`, run start/finish outcome capture, and runtime observation write tools for decisions, blockers, patch summaries, verification, and task closure. |
| Frontend | React app with a project-first visual map at `/app`, plus Sources and Connectors as primary destinations. The selected-task inspector exposes evidence, run scrutiny, open loops, affected code, compatible playbooks, and a viewable/copyable agent brief with explicit delivery state. |
| Tests | Backend pytest coverage, frontend Vitest coverage, migration tests, connector honesty tests, query/reranker tests, context compiler tests, MCP tests, extraction evals, and smoke scripts are present. |

This is enough to show the project has a real technical spine. It is not enough
to claim general availability.

## Product Tour

The application has three primary destinations:

1. **Project** — the bird's-eye view, evidence map, scrutiny rail, open loops, and
   task preparation workflow.
2. **Sources** — the immutable source records behind claims, findings, and briefs.
3. **Connectors** — honest provider setup and sync state.

### Project map

Opening a local repository establishes the workspace boundary and creates a
deterministic inventory of its root, top-level code areas, files, symbols,
imports, routes, manifests, and exact test links. Refreshing the map first updates
that repository inventory, then updates the evidence projection.

Imported sessions are matched to the project only through repository, path, or
commit evidence. Uncertain or different-project sessions are visually subdued and
cannot silently drive project health or recommendations.

### Selected-card inspector

PR, issue, session, decision, blocker, and other evidence cards open one inspector
with the current status, confidence, source revision, exact excerpt, imported
content, and factual relationships.

Only actionable component types expose **Prepare for agent**. Pull requests remain
delivery evidence, so the UI directs the user to a linked issue or task instead of
letting an invalid preparation call fail later.

After preparation, the inspector says **Agent brief ready**, reports clipboard
success or failure, states that nothing was sent automatically, and offers **View
brief** and **Copy again**. Affected code and known playbooks remain collapsed until
the user wants the detail.

### Scrutiny and open loops

The same inspector shows the recorded agent timeline and evidence-backed findings.
Project-wide unresolved findings and pending playbook reviews share one compact
attention entry point rather than adding more dashboard panels or graph nodes.

### Grounded query

The compatibility Ask route remains available at `/app/query`. It returns a
source-backed answer with the exact facts-used trace rather than a black-box
response, but it is not a primary navigation destination.

For the current seeded walkthrough, see [Demo Walkthrough](docs/demo.md).

## Developer Surface

The public setup guide is not ready, but the codebase already has the surfaces
that matter for implementation review.

### HTTP API

Important API families:

| Surface | Purpose |
|---|---|
| `/api/sources` | Create, bulk ingest, upload, list, inspect, and reprocess source documents. |
| `/api/repo/index` | Compile a local repository snapshot, symbols, structural edges, and source-backed project inventory. |
| `/api/graph` | Read models, components, relationships, unresolved edges, stats, and source diffs. |
| `/api/query` | Ask grounded project-state questions with `query.v1` traces. |
| `/api/context/digest` | Build the workspace-scoped Project map projection and attention summary. |
| `/api/context/prepare` | Compile and persist a `context_pack.v2` for a coding-agent objective. |
| `/api/context/run-timeline` | Reconstruct recorded agent execution and deterministic scrutiny findings for a prepared task. |
| `/api/context/claims/{id}/timeline` | Inspect current or bi-temporal claim history with evidence. |
| `/api/context/open-loops` | List and audit founder-facing unresolved findings. |
| `/api/context/playbooks` | Review verified reusable agent steps. |
| `/api/connectors` | List connector catalog/status, setup state, sync jobs, and guarded provider actions. |
| `/api/seed-demo` | Create a source-backed demo workspace without faking connector authentication. |

### CLI

The `ctxe` command currently contains subcommands for ingest, indexed/live/combined
query, context preparation, one-shot repository indexing, bounded repository
watching, worker sync, extraction evals, database migrations, credential rotation,
graph reads, and MCP server startup.

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
- `record_agent_run_finish`
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
| Local repository | Available | Deterministic indexing and bounded watch mode compile files, symbols, structure, and change events. |
| Local files | Available | Upload and ingest paths create source documents. |
| AI sessions | Available | Codex, Claude Code, OpenCode, and generic session imports are supported. |
| GitHub | Available | Personal access token setup syncs issues, pull requests, and review discussions into source documents. |
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
| `app/services/` | Ingestion, query, evidence, claims, compiler, repository indexing/watch, permissions, scrutiny, open loops, playbooks, sync, auth, and workspace scope logic. |
| `app/processing/` | Extraction and embedding implementations. |
| `app/sync/` | Provider sync clients for Slack, GitHub, Google, and AI session import helpers. |
| `app/mcp/server.py` | Model Context Protocol server and agent runtime bridge. |
| `app/cli/main.py` | `ctxe` command-line entrypoint. |
| `frontend/src/` | React Project map, task inspector, open-loop/playbook review, source and connector surfaces, API hooks, workspace context, and tests. |
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
