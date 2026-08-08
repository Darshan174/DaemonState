# Changelog

## 0.3.0 - Unreleased

### Added

- Added the workstation product loop: Continue for the newest eligible local
  session, Library for project-scoped Codex/Claude Code/OpenCode history and
  recovery checkpoints, and Execute for objective-independent Workspace
  Context plus up to three explicitly selected historical Session Contexts.
- Added immutable work checkpoints, compact hash-bound Session Context,
  repository reconciliation, attachment/preservation gates, and distinct
  browser-staging versus observed provider-execution contracts.
- Added the deterministic `workspace_foundation.v2` compiler and renderer for
  objective-independent Workspace Context, with repository/evidence binding,
  copy-safety and coverage reports, semantic/artifact hashes, and immediate
  recompilation before copy.
- Added repository indexing/watch support for bounded files, symbols, routes,
  manifests, Git state, deterministic structural edges, and exact test links.
- Added `daemonstate prepare`, `continue`, `repo`, `harness`, `eval`, `worker`,
  `db`, `credentials`, and `mcp` command families, including audited local
  Codex, Claude Code, and OpenCode execution adapters.
- Added source revision, claim/evidence, memory, checkpoint, continuation,
  context, graph, connector, prompt-snippet, and desktop-control API families
  with workspace/source authorization.
- Added the optional macOS floating control for verified Workspace/Session
  Context copy and focus-preserving paste without automatic submission.
- Added a hardened single-host, authenticated API-only deployment profile with
  Caddy, PostgreSQL/pgvector, Redis, worker health, metrics, explicit migrations,
  file-backed secrets, and backup/restore tooling.
- Added detailed getting-started, product, architecture, configuration, CLI,
  API, connector, continuation, compiler, deployment, and operator documentation.

### Changed

- Changed the project license from MIT to the source-available Sustainable Use
  License 1.0 (`SUL-1.0`). The exact final MIT-licensed source is commit
  `45b7a6e653a1762bf91b99fae4c7adf3dafc55ce`.
- Added a supported, loopback-only personal Docker self-hosting flow with
  generated local secrets, an explicit database migration gate, readiness
  checks, PostgreSQL/pgvector, and the sync worker.
- Added self-hosting, backup, upgrade, security, and licensing guidance.
- The bare-metal start command now supervises both the API and sync worker.

### Current alpha boundaries

- Evidence, Sources, and Integrations have implemented backend contracts but
  their top-level browser routes remain intentionally under construction.
- Browser desktop handoff and the floating control are macOS-specific; Docker
  cannot discover host-only session history or open local coding apps.
- The hardened deployment is single-tenant, single-host, and API-only.
- The `workspace_foundation.v2` schema defines first-class production-flow,
  verification-run, change-intent, and durable-fact collections; the default
  compiler does not yet populate or render those four collections.
