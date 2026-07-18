<p align="center">
  <img src="frontend/public/favicon.svg" width="88" height="88" alt="Context Engine logo">
</p>

<h1 align="center">Context Engine</h1>

<p align="center">
  Verified project history in. Minimum task-ready context out.
</p>

> **Active alpha.** Core workflows are implemented and tested locally, but public
> setup, hosting, and production deployment guides are not ready yet.

## What it is

Context Engine is an open-source context and evidence layer for coding agents.
It compiles verified project history into the minimum task-ready context an
agent needs to continue real work on a long-running codebase.

It is not another coding agent and it is not a generic knowledge graph. The
context compiler is the core product. The graph is the human-readable
explanation and navigation surface that shows where facts came from, how work is
connected, and why specific context was selected.

## The problem

AI coding feels fast until the next session starts.

The agent has forgotten the decision you made yesterday. It cannot tell which
issue is actually current. It reads stale files, repeats an abandoned approach,
or says the work is done without seeing the failed check. You spend the first
part of every session rebuilding context the project already has.

A larger context window does not fix this by itself. More text can mean more old
plans, duplicated facts, and irrelevant history.

## Who it is for

Context Engine is built first for solo founders and tiny teams using coding
agents every day. Developers get the exact sources, files, constraints, checks,
and run evidence needed for the next task. Founders and collaborators get a
readable view of the same project state without living in terminal logs.

## What Context Engine changes

Context Engine turns repository state, issues, pull requests, imported agent
sessions, decisions, blockers, documents, patches, and test results into durable
project memory.

It lets the user choose the current goal, compiles a focused source-backed brief
for that task and target model, and records what actually changed after the run.
Repository changes, checks, blockers, and outcomes become evidence for the next
session instead of disappearing inside one chat history.

The result is simple: coding-agent sessions stop behaving like disconnected
chats and start behaving like continuous work on one project.

## The bet

You should not need the newest, most expensive model for every task just because
an older or cheaper model was given poor context.

Context Engine does not make a weak model magically smarter. It removes an
avoidable handicap: unclear goals, missing project history, irrelevant context,
and no execution discipline. The local harness and outcome reports are built to
measure whether that lets less capable models complete more useful work.

We have not proven that yet. The harness can run and record the comparison; now
we need results from real projects, not demos.

## The product loop

| Step | What it does for the user |
|---|---|
| Connect a project | Creates a clean boundary around one real repository and its evidence. |
| Capture the work | Preserves code state, issues, decisions, AI sessions, changes, and checks. |
| Choose the current goal | Keeps the user in control. Open issues stay backlog until selected. |
| Prepare the next run | Compiles only the files, facts, constraints, risks, exclusions, and checks relevant to that task. |
| Inspect the brief | Shows what was selected, why it was selected, and which sources support it. |
| Observe the result | Records repository changes and verification evidence instead of trusting a completion claim. |
| Explain what matters | Uses the graph to show the relationships behind the current project state and compiled context. |

Every important fact keeps its source. Missing evidence stays missing instead of
being replaced with a confident guess.

## What this gives you

- **Continuity:** start the next session from the last recorded project state and
  its verified results.
- **Control:** choose the current goal instead of letting an old issue or context
  pack choose it for you.
- **Less noise:** give the agent a task-sized brief, not a dump of everything the
  project has ever seen.
- **Proof:** see the changed files, checks, blockers, and evidence behind a run.
- **Model freedom:** carry project memory across agents and providers instead of
  locking it inside one chat history.
- **A path to lower cost:** test where better context lets an older, smaller, or
  open model do work that otherwise required a frontier model.

## What works today

| Surface | Actual job |
|---|---|
| Now | Shows the explicit current goal, latest observed result, genuine blockers and risks, and backlog. |
| Prepare | Builds a readable `context_pack.v2` brief and auditable manifest for one task and target-model profile. |
| Runs | Shows recorded commands, changed files, checks, outcomes, and honest comparison readiness. |
| Explain | Uses the project graph to show why evidence and relationships matter without making the graph a separate product. |
| Sources and connectors | Keeps raw evidence, revision history, access boundaries, and provenance inspectable. |
| Local harness | Wraps one user-supplied worker command and records bounded output, Git changes, checks, and outcome evidence. |

The product is available through the React app, FastAPI API, `ctxe` CLI, and MCP
server. Local development uses SQLite; Docker deployments can use
PostgreSQL/pgvector.

## Local agent harness

You choose the model, provider, and worker command. Context Engine prepares the
brief, exposes it to the worker, observes the repository, and stores factual run
evidence.

```bash
ctxe harness run "fix the selected task" \
  --workspace-id <workspace-uuid> \
  --target-model qwen2.5-coder-7b \
  --verify \
  -- your-worker --context {context_file}
```

`--verify` is explicit permission to run the required checks in the compiled
brief. Without it, those checks are not executed.

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

## Honest limits

- The product UI prepares and copies an agent brief; it does not send it
  automatically.
- The CLI harness runs only the explicit local command supplied by the user.
- There are no built-in Codex, Claude Code, Hermes, or OpenCode launch adapters.
- Scrutiny uses deterministic evidence rules. It is not an autonomous code review.
- Live retrieval is limited to the local repository and configured manual-token
  GitHub access.
- Captured command output and repository inspection are deliberately bounded.
- Model-lift reports describe observed runs. They do not yet prove that an older
  model matches a newer one because of Context Engine.
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
