# Architecture

DaemonState is a self-hosted context compiler and continuation runtime for AI
coding agents. It reconstructs project state from repository observations,
local agent sessions, configured providers, documents, and measured run
evidence, then produces two deliberately separate outputs:

- **Workspace Context**, the objective-independent project-wide parent; and
- **Session Context**, the task-specific child captured from one agent session.

The source-backed graph and revision ledger support this work. They are not the
primary product output and are never allowed to invent an instruction from
topology, confidence, or display placement.

## Runtime profiles

### Workstation

```text
Browser on loopback
       |
       v
FastAPI + built React bundle ---- local-only desktop dispatch
       |                                  |
       |                                  +--> Codex / Claude / OpenCode app
       |
       +--> SQLite
       +--> local sync worker
       +--> repository indexer / watcher
       +--> local agent-session resolvers
       +--> optional provider CLI adapters
       +--> optional MCP stdio process
       +--> optional macOS floating control
```

This is the full product profile. The API, repository, local agent histories,
and coding tools run as the same workstation user. Browser staging can request a
new desktop composer on macOS; CLI continuation can start a non-interactive
provider process and measure its result.

### Personal Docker

```text
Browser on loopback
       |
       v
FastAPI + React ---- PostgreSQL/pgvector
       |                    ^
       +---- sync worker ---+
       |
       +---- /workspace (read-only host repository mount)
```

The one-shot migration service must complete before the API starts, and the API
must become healthy before the worker starts. Docker cannot see host-only agent
history or desktop applications and cannot write to the mounted repository.

### Hardened single-host API

```text
API client
    |
    v
Caddy TLS proxy
    |
    v
FastAPI app ---- PostgreSQL/pgvector
    |                     ^
    +---- Redis           |
    +---- sync worker ----+
    +---- read-only repository mount
    +---- Prometheus metrics
```

The production profile uses immutable images, file-backed secrets, explicit
migrations under an advisory lock, a separate application database role,
distributed request limiting, bounded resources, JSON logs, and guarded
backup/restore tools. It is API-only (`SERVE_FRONTEND=false`), single-tenant,
single-host, and not highly available.

## Main data flow

```text
local repository       local agent history       configured providers/uploads
       |                        |                            |
       +------------------------+----------------------------+
                                v
                    immutable SourceDocument revision
                                |
                                v
                 deterministic / bounded model extraction
                                |
                 +--------------+--------------+
                 |                             |
                 v                             v
       claims, components, facts       evidenced relationships
                 |                             |
                 +--------------+--------------+
                                |
            +-------------------+-------------------+
            |                                       |
            v                                       v
Workspace Foundation Compiler             checkpoint/handoff compiler
            |                                       |
            v                                       v
    Workspace Context                         Session Context
            |                                       |
            +-------------------+-------------------+
                                v
                    browser, CLI, or MCP delivery
                                |
                                v
                optional measured AgentRun observations
                                |
                                +----> next compilation cycle
```

Raw content is durable before projection. If extraction or a worker is
interrupted, unprocessed source revisions remain recoverable.

## Persistence model

The SQLAlchemy model is shared by SQLite and PostgreSQL, with pgvector-specific
retrieval available in the PostgreSQL profile.

### Project boundary and sources

| Record | Purpose |
|---|---|
| `workspaces` | User-visible project/demo/sandbox boundary, lifecycle, and current selection scope. |
| `workspace_goals` | Explicit active goal for task resolution. |
| `source_documents` | Immutable raw content revisions with source identity, hashes, workspace, visibility, metadata, and supersession. |
| `source_read_grants` | Principal-specific access to restricted source revisions, bound to a permission snapshot. |
| `connectors` | Workspace-scoped encrypted provider configuration and current connection state. |
| `sync_jobs` | Leased connector/source work, retries, heartbeats, claim tokens, terminal state, and errors. |

### Knowledge and provenance

| Record | Purpose |
|---|---|
| `evidence_spans` | Exact source-backed text spans and hashes. |
| `claims` / `claim_revisions` | Stable claim identity plus append-only valid-time/transaction-time lifecycle. |
| `models` / `components` | Legacy semantic buckets and atomic source-backed facts used by current graph/query/memory projections. |
| `entities`, `facts`, `mentions`, `entity_aliases` | Normalized identity/fact projection for richer source-backed reasoning. |
| `relationships` | Typed graph edges with evidence, origin, confidence, lifecycle, and review state. |
| `unresolved_relationships` | Relationship candidates whose target cannot be resolved safely. |

### Repository observations

| Record | Purpose |
|---|---|
| `code_files` | Workspace/repository-scoped file identity, hashes, syntax metadata, and snapshot state. |
| `code_symbols` | Bounded declarations/definitions with file/line identity. |
| `code_edges` | Deterministically observed imports, route ownership, local calls, and test links. |
| `repo_events` | Bounded watcher snapshots and change evidence. |

### Continuation and execution

| Record | Purpose |
|---|---|
| `session_events` | Normalized provider session ledger with sequence and event identity. |
| `work_checkpoints` | Immutable session boundary and repository fingerprint. |
| `checkpoint_items`, `checkpoint_evidence`, `checkpoint_verifications` | Structured checkpoint state, sources, and reconciliation results. |
| `context_packs`, `context_pack_items` | Persisted `context_pack.v2` audit manifest/Markdown and selected/excluded items. |
| `continuation_executions`, requirements/observations | Typed provider-neutral request, authority, requirement, verifier, prompt, and idempotency contract. |
| `agent_runs`, `run_observations` | Measured worker/provider execution and bounded Git/check/output evidence. |
| `open_loops` | Durable unresolved work derived from current evidence. |
| `verified_playbooks` | Human-reviewed reusable workflow candidates. |

Schema changes are applied through Alembic. `daemonstate db deploy` reconciles
an unversioned legacy database once and then uses immutable revisions. Compose
starts no long-running process until the migration gate succeeds.

## Source ingestion

1. A connector, upload, CLI import, local session resolver, repository indexer,
   demo seed, or runtime recorder proposes a source revision.
2. `ingest_source_document_revision` computes stable source identity and content
   hashes, deduplicates unchanged input, and appends a revision when content
   changed.
3. The transaction commits the raw revision before projection.
4. Local development can process inline/background; production queues durable
   worker ingestion.
5. `IngestionService` chooses a deterministic extractor where available.
6. GitHub issues/PRs and supported agent sessions use typed deterministic
   extractors. Other sources can use a configured LiteLLM extraction model and
   fall back to bounded regex behavior.
7. Facts and relationships are upserted only with the required evidence and
   resolvable identity. Unknown targets remain unresolved instead of becoming a
   guessed edge.
8. The source revision is marked processed.

Provider delivery is at-least-once. External IDs, source hashes, conditional
job completion, and revision deduplication make retries safe.

## Repository indexer

`RepoIndexer` performs one bounded, Git-aware scan. It records repository root,
branch/detached state, HEAD, dirty status entries, changed paths, supported
files, manifests, languages, declarations, routes, imports, tests, and hashes.

It does not execute project commands. Deterministic follow-on adapters derive:

- project-root and top-level-area source evidence;
- exact local-module imports;
- route-to-handler ownership;
- binding-resolved local calls where the parser can prove them;
- static HTTP route references; and
- deterministic test-path/test-symbol links.

An import is structural evidence, not proof that a call happened. A test link
is impact evidence, not proof that the test ran. Unsupported languages can
still contribute file and line-level state while semantic coverage remains
explicitly incomplete.

Repository paths are canonicalized. `ALLOWED_REPO_ROOTS` constrains all local
reads when set. Docker fixes the allowed root to the read-only `/workspace`
mount.

## Workspace Foundation Compiler

Project-snapshot mode calls `ContextCompiler` with no user objective or session
continuation. It produces a repository inventory, compiles durable project
facts from authorized sources, loads compatible verification observations, and
passes those inputs to `WorkspaceFoundationCompiler`.

The resulting `workspace_foundation.v2` payload contains typed records and a
central evidence registry. Records refer to evidence IDs; file-bound evidence
includes current SHA-256, optional line/symbol/heading identity, derivation rule,
and evidence tier.

### Evidence tiers

Runtime/test verification, code observation, system verification,
documentation statements, human confirmation, and independent corroboration
remain distinct. Historical/provisional and conflicting/superseded evidence is
retained for audit but cannot support a current foundation record.

### Compiler lanes

1. Read bounded repository-stated product claims and system flows.
2. Observe stack, architecture, commands, and required-check policy.
3. Map capabilities to candidate/exact routes, symbols, files, and edges.
4. Construct implementation traces without turning imports or proximity into
   runtime calls.
5. Classify current repository state and attach bounded semantic deltas without
   inferring intent or completion.
6. Attach verification state to declared commands only when a persisted
   local-harness observation and exact repository-after snapshot match the
   current frame.
7. Compile repository engineering knowledge separately from evidence-gated
   durable project knowledge.
8. Compute copy safety, semantic coverage, and repository health separately.
9. Bind the semantic payload and complete artifact to SHA-256 hashes and render
   a bounded Workspace Context.

The v2 artifact schema already reserves first-class `production_flows`,
`verification_runs`, `change_intents`, and `durable_facts` collections. The
default compiler currently leaves those four collections empty, and the
default renderer does not project them. Their stricter admission rules are
documented as the completion contract rather than presented as shipped output.

The browser validates schema, workspace/repository identity, quality, content
hash, semantic hash, and artifact hash. Copy recompiles immediately so a valid
but stale preview cannot cross the clipboard boundary.

See [Workspace Foundation Compiler](workspace-foundation-compiler.md) for the
record and quality contract.

## Session checkpoints and handoffs

Local session adapters normalize provider events into a workspace-scoped
ledger. Capture selects a stable boundary—usually the current tip or an exact
pre-compaction event—and writes an immutable checkpoint with structured items
for goal, progress, decisions, attempts, files, verification, blockers, and next
action.

Handoff compilation:

1. authorizes every source before it can influence output;
2. verifies that provider, session, source revision, checkpoint, and sequence
   still match;
3. reconciles the captured repository state with the live repository;
4. verifies attachments and required portable references;
5. separates durable project facts from task-local session state;
6. emits `session_handoff.v1` plus a bounded `compact_v2` or rollback
   `legacy_v1` Markdown projection; and
7. blocks direct copy on integrity, freshness, contradiction, missing-artifact,
   or quality failures.

Session commands remain quoted historical evidence. No checkpoint endpoint
replays them automatically.

## Continuation execution

Continuation preparation resolves a task from an explicit user objective, the
active workspace goal, or the latest substantive request in an authorized
in-scope session. An explicitly pinned provider/session or checkpoint fails if
it cannot be loaded; the runtime does not substitute a different task.

It then persists:

- a complete audit `context_pack.v2`;
- a `continuation_execution.v1` typed contract with the byte-preserved request
  and SHA-256;
- source-span-to-requirement lineage and MUST/SHOULD priority;
- task-mode-specific authority;
- repository and pre-existing-change protection;
- required artifacts and receiver availability;
- a bounded read plan; and
- requirement-linked command, browser, screenshot, event, or external
  verification contracts.

Browser staging renders a reviewable context, copies it, and requests a macOS
desktop composer. It starts no provider process and creates no `AgentRun`.

CLI/HTTP run invokes an audited local adapter, captures bounded stdout/stderr and
Git state, applies preservation gates, executes only typed requirement-linked
verifiers, and records an outcome. Provider exit and self-report do not prove
completion.

## Query and retrieval

`POST /api/query` returns `query.v1` with the question, answer, confidence,
ranked components, sources, and a trace that names retrieval/ranking/calibration
strategies, facts used, and relationship evidence.

Modes:

- `indexed`: persisted authorized sources only;
- `live`: bounded local repository and/or configured GitHub retrieval; and
- `combined`: both, without obscuring the origin lane.

When no embedding model is configured, behavior is explicitly lexical-only.
The disabled-by-default hashing embedder is not represented as semantic search.
Authorization predicates are applied before source evidence becomes a
retrieval candidate.

## Access and trust boundaries

### API scopes

- With no keys configured, loopback personal installs use unrestricted local
  scope.
- `SERVER_API_KEY` maps to unrestricted administrator scope.
- configured principal tokens map server-side to allowed workspace IDs;
  request-authored workspace claims are ignored.
- restricted source revisions require a current matching read grant.
- inaccessible sources are filtered in SQL before retrieval, memory promotion,
  checkpoint compilation, or corroboration counts.

### Local actions

Provider readiness, desktop staging, automatic provider runs, recorded-session
open, and native overlay control validate a loopback peer. Forwarded headers do
not turn a remote request into a local action. Some routes also require the
trusted `local` principal.

### Untrusted content

Slack, email, Drive, uploads, web/provider text, and imported agent narration
are evidence, not instructions. Model-facing renderers keep sources in separate
trust zones, blockquote historical content, score common prompt-injection
patterns, and exclude high-risk/unsupported candidates under the compiler
contract.

### Secrets

Connector credentials are Fernet-encrypted at rest. OAuth state is encrypted,
short-lived, single-use, and connector-bound. API and metrics authentication
are separate. Production consumes secrets from mounted files, drops privileges
before importing the app, and does not expose secrets in the Compose
environment.

## Observability

- Structured request IDs appear in responses and logs.
- Prometheus covers request totals/duration/in-flight state, readiness, rate
  limiting, workers, and relevant runtime counters.
- Production JSON logs avoid raw request/source content by contract.
- Optional OpenTelemetry exports metadata-only spans. Content capture is
  rejected, and production endpoints must use HTTPS.
- Captured provider output and repository scans have size/count/time bounds.

## Failure and scaling boundaries

- SQLite is the zero-setup workstation store; it is not the production
  concurrency path.
- The production database, Redis, app, worker, proxy, and metrics services share
  one host/failure domain.
- Prometheus multiprocess collection is not configured, so production permits
  one API worker.
- Connector delivery is at-least-once and workers depend on idempotent ingestion.
- Static repository analysis does not prove runtime behavior or external
  provider effects.
- Browser dispatch proves only that a local open request was attempted.
- The dashboard has no login/session/CSRF boundary and therefore stays out of
  the public production profile.
- Multi-tenant policy, managed object storage, high availability, and
  multi-region recovery are not implemented.

For deployment procedures, see [Self-hosting](self-hosting.md) and the
[Production runbook](production-runbook.md).
