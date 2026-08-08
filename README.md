<p align="center">
  <img src="frontend/public/favicon.svg" width="88" height="88" alt="DaemonState logo">
</p>

<h1 align="center">DaemonState</h1>

<p align="center">
  Continue the work. Not the explanation.
</p>

<p align="center">
  <a href="https://github.com/Darshan174/DaemonState/releases"><img alt="Version 0.3.0" src="https://img.shields.io/badge/version-0.3.0-171713"></a>
  <a href="https://github.com/Darshan174/DaemonState/blob/main/LICENSE"><img alt="SUL 1.0 license" src="https://img.shields.io/badge/license-SUL--1.0-d9ff68"></a>
  <img alt="Python 3.12 or newer" src="https://img.shields.io/badge/python-%E2%89%A53.12-3776AB">
  <img alt="Active alpha" src="https://img.shields.io/badge/status-active%20alpha-f59e0b">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="docs/README.md">Documentation</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="SECURITY.md">Security</a>
</p>

DaemonState is a local, source-backed continuity layer for AI coding agents. It
discovers project-scoped Codex, Claude Code, and OpenCode sessions, reconciles
their working state with the repository, and produces verified context for the
next session.

It is built for developers, founders, and small teams that use more than one
coding agent and are tired of rebuilding the project story in every new chat.
DaemonState is not another coding agent, a generic RAG product, or an autonomous
project manager. It prepares and delivers context to tools you already use.

> **Active alpha.** The complete product is self-hosted. Core local workflows
> work today, but several browser inspection/setup surfaces are still under
> construction. DaemonState 0.3.0 is source-available under SUL-1.0; it is not
> an OSI-approved open-source release.

## What works today

| Surface | Status | Current behavior |
|---|---|---|
| Continue | Available in the dashboard | Selects the newest eligible in-project local session, captures its current tip, verifies the checkpoint against the repository, copies a Session Context, and requests a new composer in Codex, Claude, or OpenCode on macOS. The user reviews and submits it. |
| Library | Available in the dashboard | Discovers local Codex, Claude Code, and OpenCode history; filters it to the workspace; groups sessions by harness and topic; and exposes captured recovery checkpoints. Historical choices never replace Continue's newest-session rule. |
| Execute | Available in the dashboard | Compiles and previews an objective-independent Workspace Context, then lets the user choose up to three eligible Session Contexts from Library for side-by-side review or copying. |
| Workspace Context | Available through Execute and `POST /api/context/prepare` | Deterministically indexes the repository and combines product claims, capabilities, architecture, implementation traces, declared commands, current repository state, and eligible durable knowledge in a hash-bound `workspace_foundation.v2` artifact. Compilation does not run repository commands. |
| Memory | Available through the Execute inspector and API | Separates active, review-needed, historical, superseded, and conflicting project facts. Only mechanically verified, human-confirmed, or independently corroborated facts can enter the durable Project Context foundation. |
| Evidence, Sources, Integrations | Backend available; dashboard under construction | The source, graph, query, memory, connector, and revision APIs are implemented. Explain and agent brief actions can compile source-backed output. The API preserves revisions and enforces access scopes, but these three top-level browser routes are intentionally covered by a work-in-progress gate. |
| CLI and MCP | Available | Compile task context, continue work in a local provider CLI, index/watch repositories, ingest/query evidence, run measured harnesses, or expose a local stdio MCP server. They expose the core runtime rather than every UI view. |
| macOS floating control | Optional | Verifies, copies, and can paste Workspace or Session Context into the editor that previously had focus. It never presses Return or submits a message. |

Founders and non-technical users can inspect the plain-language context and
evidence summaries; Developers can audit the exact repository state,
provenance, exclusions, checks, and next action.

Better context may help older, cheaper, or open models do more useful work. We
have not proven that yet. The included harness records comparisons, but it does
not turn observed runs into a causal model-equivalence claim.

## The context model

DaemonState keeps project-wide truth separate from one session's working state.
The durable Project Context foundation is delivered in the product as
**Workspace Context**.

| Context | Contains | Deliberately excludes |
|---|---|---|
| Workspace Context | Product purpose, supported capabilities, architecture, workflows, commands, repository state, durable decisions, conventions, constraints, and evidence-backed risks. | The selected prompt, task ranking, one session's failed attempts, transient blockers, and unverified session claims. |
| Session Context | One session's goal, acceptance criteria, progress, decisions, failed attempts, changed files, verification, blockers, scope, and exact next action. | Unrelated sessions and unsupported claims about project-wide truth. |

Continue automatically captures the selected session tip as an immutable
checkpoint before handoff. It compares that checkpoint with the current
repository and never replays commands imported from the session. A direct copy
must pass its context-specific quality and integrity gates.

## Quick start

Choose the workstation install for local session discovery and coding-agent
handoff. Choose Docker for the dashboard, API, demo, and read-only repository
inspection.

### Workstation install

Requirements: Git, Python 3.12+, npm, and Node.js 20.19+ on the 20.x line,
22.13+ on the 22.x line, or 24+. Browser-to-desktop Continue currently requires
macOS plus an installed Codex, Claude, or OpenCode desktop app.

```bash
git clone https://github.com/Darshan174/DaemonState.git daemonstate
cd daemonstate
bash scripts/doctor.sh --bare-metal
bash scripts/setup.sh
bash scripts/start.sh
```

Open <http://localhost:8000>, then:

1. Connect one local Git repository as a workspace.
2. Open **Library** and confirm that in-project local sessions were discovered.
3. Use **Continue** for the newest eligible session, or **Execute** to compile
   Workspace Context and select historical Session Contexts.
4. Preview every handoff before copying or opening another coding app.

For frontend hot reload, run `bash scripts/dev.sh`; Vite serves the development
UI at <http://localhost:5000> and the API remains at port 8000.

### Personal Docker

Requirements: Git, Docker, and Docker Compose v2 with `up --wait` support.

```bash
git clone https://github.com/Darshan174/DaemonState.git daemonstate
cd daemonstate
bash scripts/self-host.sh
```

Open <http://127.0.0.1:8000>. Docker includes PostgreSQL/pgvector, migrations,
the API/dashboard, and the connector worker. The selected project is mounted
read-only at `/workspace`; the container cannot discover host-only agent
history, open desktop apps, or edit the repository. This personal profile is
loopback-only. It is not a production hardening guide; see
[Self-hosting](docs/self-hosting.md).

### Seed the demo

```bash
curl -X POST http://localhost:8000/api/seed-demo \
  -H 'content-type: application/json' \
  -d '{}'
```

Select **DaemonState Demo** in the workspace chooser. Demo records are clearly
marked and never create fake connector authentication. See the
[Demo walkthrough](docs/demo.md).

## CLI

The CLI is installed into `.venv/bin/daemonstate` by `scripts/setup.sh`. Activate
the environment or call that path directly.

Compile a task pack without starting an agent:

```bash
daemonstate prepare "fix the failing import flow" \
  --workspace-id <workspace-uuid> \
  --repo . \
  --out context.md \
  --manifest-out context.json
```

Resolve the current task and run a fresh local provider session:

```bash
daemonstate continue \
  --workspace-id <workspace-uuid> \
  --repo . \
  --into codex
```

Use `--into claude` or `--into opencode` for another provider. Unlike the
browser's reviewable composer handoff, this path runs the provider CLI
non-interactively, observes bounded repository/output evidence, and evaluates
requirement-linked checks. It never adds permission-bypass flags. A provider
exit code or success message is not proof that the task is complete.

Other entry points include `ingest`, `query`, `repo index`, `repo watch`,
`harness run`, `harness report`, `eval`, `worker sync`, `db`, `credentials`, and
`mcp`. See the [CLI reference](docs/cli-reference.md) and
[MCP examples](examples/mcp/).

## Architecture

```text
Local sessions + repository + configured sources
                         |
                         v
        source revisions and repository observations
                         |
             +-----------+-----------+
             |                       |
             v                       v
    Workspace Context          Session Context
  (project-wide parent)       (task-specific child)
             \                       /
              +----------+----------+
                         v
       browser handoff, CLI execution, or MCP
```

The backend is FastAPI with async SQLAlchemy. Workstation installs default to
SQLite; Docker uses PostgreSQL with pgvector. The dashboard is React, Vite, and
TanStack Query. Provider ingestion is source-first: raw content is preserved
before facts or relationships are extracted.

## Supported sources

“Available” means a tested backend path can create source documents when it is
configured; it does not mean its dashboard onboarding is finished.

| Source | Status |
|---|---|
| Local repositories, uploads, and direct file ingestion | Available |
| Local/imported Codex, Claude Code, OpenCode, and generic AI context | Available |
| GitHub issues and pull requests | Available with a personal access token |
| Slack | Available with a Slack app or managed OAuth URL |
| Gmail and Google Drive | Available with Google OAuth |
| Discord, Zoom, and Wispr Flow | Coming soon |
| Notion | Not catalogued in this release |

## Honest boundaries

- Browser Continue dispatches a local macOS URL and copies the complete
  context. The launch is reported as requested, not as a verified open or a
  started provider turn. Nothing is submitted automatically.
- There is no system-wide agent monitor. Library scans when requested, Continue
  discovers the latest local session, and configured integrations report their
  own events.
- Session Context copy in Execute currently requires at least two detected
  provider compactions. Recovery checkpoints remain visible before that gate.
- The local harness is the path that independently inspects Git state and
  commands. HTTP and MCP observation records may include caller-supplied facts.
- Scrutiny is deterministic evidence checking, not autonomous code review.
- The hardened deployment is single-tenant and single-host. It provides no
  browser login, multi-host failover, or multi-region recovery.

## Documentation

Start with the [documentation home](docs/README.md).

- [Getting started](docs/getting-started.md)
- [Product guide](docs/product-guide.md)
- [Configuration](docs/configuration.md)
- [CLI reference](docs/cli-reference.md)
- [HTTP API](docs/api-reference.md)
- [Architecture](docs/architecture.md)
- [Continuation runtime](docs/continuation-runtime.md)
- [Workspace Foundation Compiler](docs/workspace-foundation-compiler.md)
- [Connectors](docs/connectors.md)
- [Self-hosting](docs/self-hosting.md)
- [Production runbook](docs/production-runbook.md)
- [Changelog](CHANGELOG.md)

## Contributing and security

Bug reports and product feedback are welcome. Outside code and documentation
submissions are temporarily paused until a contributor agreement is available;
read [CONTRIBUTING.md](CONTRIBUTING.md) before sending implementation material.
Report vulnerabilities through the process in [SECURITY.md](SECURITY.md), not a
public issue.

Maintainers can run the local CI-equivalent checks with:

```bash
bash scripts/smoke.sh
```

## License

DaemonState 0.3.0 and later use the source-available Sustainable Use License 1.0
(`SUL-1.0`). Personal, noncommercial, and internal business self-hosting are
allowed; paid product or service use is not. The final MIT-licensed source is
commit `45b7a6e653a1762bf91b99fae4c7adf3dafc55ce`. See [LICENSE](LICENSE) and
[Licensing](docs/licensing.md).
