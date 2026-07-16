<p align="center">
  <img src="frontend/public/favicon.svg" width="88" height="88" alt="Context Engine logo">
</p>

<h1 align="center">Context Engine</h1>

<p align="center">
  Source-backed project memory and oversight for people building software with coding agents.
</p>

> **Active alpha.** Core workflows are implemented and tested locally, but public
> setup, hosting, and production deployment guides are not ready yet.

## What it is

Coding agents are good at writing code. They are less reliable at carrying a
project's history from one run to the next.

Context Engine keeps that history in one place: repository state, issues, pull
requests, agent sessions, decisions, blockers, documents, patch summaries, and
test results. It uses that evidence to show where the project stands and prepare
a focused brief for the next agent.

It is not a chat app over company documents, a generic RAG product, or another
autonomous coding agent.

## Who it is for

**Founders and non-technical users** get a readable project view:

- what changed;
- what is blocked or still unverified;
- which decisions are current;
- what the agent actually did;
- what needs attention next.

**Developers** get an auditable context layer:

- exact source and revision links;
- task-specific files to inspect, constraints, risks, and checks;
- CLI, HTTP, and MCP access;
- recorded commands, changed-file summaries, verification results, and outcomes;
- reusable playbooks admitted only from verified runs.

## How it works

```text
repo + issues + PRs + agent sessions + documents
                         ↓
                source-backed project state
                         ↓
              focused context for one task
                         ↓
             observed work and verification
                         ↓
              better context for the next run
```

Every important fact keeps its source. Missing evidence stays missing instead of
being filled in with a guess.

## What works today

| Area | Current behavior |
|---|---|
| Project view | Shows system structure, decisions, delivery, risks, next work, and supporting evidence. |
| Context compiler | Produces `context_pack.v2` as readable Markdown plus an auditable manifest. |
| Agent scrutiny | Flags missing or failed checks, unresolved blockers, stale task context, and completion claims that conflict with recorded evidence. |
| Local harness | Wraps one user-supplied worker command and records bounded output, Git changes, checks, and outcome evidence. |
| Learning loop | Keeps unresolved work visible and extracts reviewable playbooks from verified runs. |
| Query | Returns source-backed answers with a `query.v1` facts-used trace. |
| Interfaces | React app, FastAPI API, `ctxe` CLI, and MCP server. |
| Storage | SQLite for local development; PostgreSQL/pgvector in Docker deployments. |

## Local agent harness

The harness does not choose an agent or provider. You supply the command. Context
Engine prepares the brief, exposes it to the worker, observes the repository, and
stores factual run evidence.

```bash
ctxe harness run "fix the selected task" \
  --workspace-id <workspace-uuid> \
  --target-model qwen2.5-coder-7b \
  --verify \
  -- your-worker --context {context_file}
```

`--verify` is explicit permission to run the required checks in the compiled
brief. Without it, the run is recorded but may remain unverified.

The broader goal is to test whether better context and stricter execution help an
older or cheaper model perform closer to a newer model on an existing project.
The measurement tools now exist; this repository does **not** yet contain evidence
of model parity.

See [Local Agent Harness](docs/agent-harness.md) for the contract and limits.

## Connectors

"Available" means the backend has a tested path that can create source documents
when configured. It does not mean public onboarding is finished.

| Source | Status |
|---|---|
| Local repository and files | Available |
| Codex, Claude Code, OpenCode, and generic session imports | Available |
| GitHub | Available with a personal access token |
| Slack | Available with app/OAuth setup |
| Gmail and Google Drive | Available with Google OAuth setup |
| Discord, Zoom, Wispr Flow | Coming soon |
| Notion | Not catalogued |

Demo data never marks a connector as authenticated or connected.

## Current limits

- The product UI prepares and copies an agent brief; it does not send it
  automatically.
- The CLI harness runs only the explicit local command supplied by the user.
- There are no built-in Codex, Claude Code, Hermes, or OpenCode launch adapters.
- Scrutiny uses deterministic evidence rules. It is not an autonomous code review.
- Live retrieval is limited to the local repository and configured manual-token
  GitHub access.
- Captured command output and repository inspection are deliberately bounded.
- Public setup, hosted operation, and production deployment guidance are unfinished.

## Developer surface

The backend is FastAPI with async SQLAlchemy. The frontend is React, Vite, and
React Query. The same project state is available through HTTP, CLI, and MCP.

Main API routes:

| Route | Purpose |
|---|---|
| `POST /api/context/prepare` | Compile and persist a task brief. |
| `POST /api/query` | Query project context with a source trace. |
| `POST /api/repo/index` | Index repository files, symbols, and exact structural links. |
| `GET /api/context/run-timeline` | Read observed agent work and scrutiny findings. |
| `GET /api/context/open-loops` | List evidence-backed unresolved work. |
| `GET /api/context/playbooks` | Review reusable steps from verified runs. |

Useful CLI commands:

```text
ctxe prepare
ctxe query
ctxe repo index
ctxe repo watch
ctxe harness run
ctxe harness report
ctxe eval harness
ctxe mcp
```

The MCP server can prepare/query context and record run evidence. It cannot edit
code, run shell commands, push commits, or write to external providers. See
[MCP](docs/mcp.md) and [MCP examples](examples/mcp/).

## Setup

Coming soon.

The repository contains development scripts, Docker files, environment templates,
and smoke checks, but the public setup path will be published only after it is
verified from a clean clone.

## Deployment

Coming soon.

## Contributing

Coming soon.

## Documentation

- [Architecture](docs/architecture.md)
- [Product positioning](docs/product-positioning.md)
- [Connectors](docs/connectors.md)
- [Context Pack v2](docs/context-pack-v2.md)
- [Context Compiler v2](docs/context-compiler-v2.md)
- [Local Agent Harness](docs/agent-harness.md)
- [MCP](docs/mcp.md)
- [AI session imports](docs/ai-context.md)
- [Demo walkthrough](docs/demo.md)

Some documents are implementation contracts rather than public guides. The code
and tests are the authority for current behavior.

## License

MIT. See [LICENSE](LICENSE).
