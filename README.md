<p align="center">
  <img src="frontend/public/favicon.svg" width="88" height="88" alt="Context Engine logo">
</p>

<h1 align="center">Context Engine</h1>

<p align="center">
  Make every coding agent start with the project, not a blank chat.
</p>

> **Active alpha.** The local app, API, CLI, MCP server, context compiler, and
> optional run harness are implemented and tested. There is no hosted service,
> and the public clean-clone setup path is still being finished.

## What Context Engine is

Context Engine is an open-source, self-hosted project-continuity layer for people
building software with coding agents.

It preserves repository state, issues, pull requests, coding sessions, decisions,
documents, blockers, and verification results as source-backed project evidence.
It keeps the current goal explicit, compiles a focused brief for one task, and
can record what an agent run actually changed and verified.

Context Engine is not another coding agent. The browser app does not choose a
provider or dispatch a run. You copy the prepared brief into the agent you
already use, or explicitly wrap your own local worker command with the optional
CLI harness.

The knowledge graph is an explanation surface: it shows why project evidence is
connected. It is not a generic company graph, and it is not the handoff sent to
the next agent.

## Who it is for

Context Engine is built first for solo founders and tiny teams using coding
agents every day. Founders and non-technical users get a readable view of current
work and its evidence. Developers get exact sources, revisions, relevant files,
checks, exclusions, and observed run results.

## The product loop

| Surface | What it actually does |
|---|---|
| Sources and Connectors | Preserve raw project evidence, revisions, provenance, and access boundaries. |
| Now | Show active or latest coding work, the newest agent update and stated reason, verified outcomes, and genuine blockers or risks. |
| Prepare | Compile a bounded `context_pack.v2` brief with relevant evidence, files, constraints, checks, citations, and explicit exclusions. |
| Your coding agent | Receive the copied brief and do the work; this remains outside the browser product. |
| Runs | Show repository changes, commands, checks, and outcomes captured by the optional local harness. |
| Explain | Visualize the evidence and relationships behind the current project state. |

```text
source evidence → explicit goal → focused brief → your agent
       ↑                                      ↓
       └──────── observed result + checks ────┘
```

Every important fact keeps its source. Missing evidence stays missing instead of
being replaced with a confident guess.

## What works today

- **Source-backed project state:** immutable source revisions, evidence spans,
  workspace boundaries, and permission-aware retrieval.
- **Current focus:** selected goals and active runs remain distinct from suggested
  backlog and unassigned coding sessions.
- **Context compilation:** `context_pack.v2` is produced as readable Markdown and
  an auditable manifest under a task and token budget. The agent receives a
  task-sized brief, not an unfiltered history dump.
- **Observed outcomes:** the local harness can capture bounded command output,
  Git changes, required checks, and a terminal outcome.
- **Deterministic oversight:** open loops flag supported blockers, stale evidence,
  conflicting claims, and verification gaps without pretending to perform an
  autonomous code review.
- **Explanation and query:** the graph and `query.v1` trace show which evidence
  supports an answer or project relationship.
- **Multiple interfaces:** the same project state is available through the React
  app, FastAPI API, `ctxe` CLI, and MCP server.
- **Local-first storage:** SQLite is used for local development; the Docker stack
  is configured for PostgreSQL/pgvector.

## Local agent harness

You choose the model, provider, and worker command. Context Engine prepares the
brief, exposes it to that command, observes the repository, and stores factual
run evidence.

```bash
ctxe harness run "fix the selected task" \
  --workspace-id <workspace-uuid> \
  --target-model qwen2.5-coder-7b \
  --verify \
  -- your-worker --context {context_file}
```

`--verify` is explicit permission to run the required checks in the compiled
brief. Without it, those checks are not executed. The harness never chooses or
launches a provider on its own.

The harness and reports can help test whether better context improves results
from an older, smaller, or open model. This repository does **not** yet prove
model parity or model lift from real-project comparisons. We have not proven that yet.

See [Local Agent Harness](docs/agent-harness.md) for the contract and limits.

## Connectors

“Available” means the backend has a tested path that can create source documents
when configured. It does not mean hosted or zero-configuration onboarding.

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

Local Codex, Claude Code, and OpenCode sessions that were already imported refresh
while Now is open. This does not discover unrelated sessions or launch an agent.

## Honest boundaries

- The browser app prepares and copies an agent brief; it sends nothing to an
  agent automatically.
- The CLI harness runs only the explicit local command supplied after `--`.
- There are no built-in Codex, Claude Code, Hermes, or OpenCode launch adapters.
- The graph explains project evidence; it is not the product by itself.
- Scrutiny uses deterministic evidence rules, not autonomous AI code review.
- Live retrieval is limited to the local repository and configured manual-token
  GitHub access.
- Captured command output and repository inspection are deliberately bounded.
- Model comparison reports describe observed runs; they do not establish that
  Context Engine caused a model-quality improvement.
- A public hosted service and a verified clean-clone setup guide are not yet
  available.

## Developer surface

The backend is FastAPI with async SQLAlchemy. The frontend is React, Vite, and
React Query.

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
ctxe ingest
ctxe prepare
ctxe query
ctxe repo index
ctxe repo watch
ctxe harness run
ctxe harness report
ctxe eval harness
ctxe mcp
```

The MCP server can prepare or query context and record run evidence. It cannot
edit code, run shell commands, push commits, or write to external providers. See
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
