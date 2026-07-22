<p align="center">
  <img src="frontend/public/favicon.svg" width="88" height="88" alt="Context Engine logo">
</p>

<h1 align="center">Context Engine</h1>

<p align="center">
  Verified project history in. Minimum task-ready context out.
</p>

> **Active alpha.** Core workflows are implemented and tested locally. Bare-metal
> and Docker setup tooling is included; hosted operation and production
> deployment guidance are not ready yet.

## What it is

Context Engine is an open-source context and evidence layer for coding agents.
It compiles verified project history into the minimum task-ready context an
agent needs to continue real work on a long-running codebase.

Context Engine is not another coding agent or a generic knowledge graph. The
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
and run evidence needed for the next task. Founders and non-technical users get a
readable view of the same project state without living in terminal logs.

## What Context Engine changes

Context Engine can turn repository state, issues, pull requests, imported agent
sessions, decisions, blockers, documents, patches, and test results into durable
project memory after those sources are imported, connected, or reported by an
integration.

It lets the user choose the current goal, compiles a focused source-backed brief
for that task and target model, and stores run evidence reported through HTTP or
MCP. The local harness also observes repository changes and command results
directly. Those records can become evidence for the next session instead of
disappearing inside one chat history.

The intended result is that supported coding-agent sessions behave less like
disconnected chats and more like continuous work on one project.

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
| Capture the work | Imports or syncs code state, issues, decisions, AI sessions, changes, and checks from supported sources. |
| Choose the current goal | Keeps the user in control. Open issues stay backlog until selected. |
| Capture a checkpoint | When a supported local session is synced and exposes a compaction boundary, preserves its pre-compaction goal, progress, decisions, failures, files, blockers, checks, and next action. A session-tip checkpoint can also be saved manually. |
| Verify the checkpoint | On request, checks its structure, event evidence, repository fingerprint, relevant files, and captured test commands. |
| Resume the work | Copies one deterministic, evidence-linked continuation bundle and, from the local macOS app, attempts to open the linked desktop agent. |
| Explain what matters | Uses the graph to show the relationships behind the current project state and compiled context. |

Extracted facts retain their source and provenance; explicit user choices are
labeled separately. Missing evidence stays missing instead of being replaced
with a confident guess.

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
| Now | Shows current work plus the latest structured checkpoint, verification state, and exact next action. |
| Runs | Shows real session checkpoints, event evidence, repository freshness, checks, blockers, and resume actions. |
| Library | Scans local Codex, Claude Code, and OpenCode history while the page is open or when requested, then keeps sessions, topics, and project selection inspectable. |
| Memory | Organizes active, needs-review, and historical project facts with their evidence. |
| Explain and agent brief | Uses the project graph to explain evidence and relationships; eligible task records can compile and copy a source-backed brief. |
| Sources and connectors | Shows raw source previews, extracted components, connection state, and sync results. The API preserves revisions and enforces access scopes. |
| Local harness | Wraps one user-supplied worker command and records bounded output, Git changes, checks, and outcome evidence. |

The React app uses the FastAPI API. The `ctxe` CLI and MCP server expose core
prepare, query, repository, and run-evidence workflows rather than every UI
view. Local development uses SQLite; Docker can use PostgreSQL/pgvector.

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

- The product UI prepares and copies agent and resume briefs; it never sends or
  pastes them automatically.
- There is no system-wide agent monitor. Library scans while its page is open;
  Now refreshes linked local histories; other integrations must report events.
- HTTP and MCP run records contain observations supplied by their caller. The
  local harness is the path that independently inspects Git state and commands.
- The CLI harness runs only the explicit local command supplied by the user.
- On macOS, checkpoint resume can reopen an exact Codex task; Claude opens its
  desktop app, and OpenCode opens the project when its path is available. Exact
  Claude/OpenCode session reopening, Hermes, and other platforms are unsupported.
- Scrutiny uses deterministic evidence rules. It is not an autonomous code review.
- Live retrieval is limited to the local repository and configured manual-token
  GitHub access.
- Captured command output and repository inspection are deliberately bounded.
- Model-lift reports describe observed runs. They do not yet prove that an older
  model matches a newer one because of Context Engine.
- Hosted operation and production deployment guidance are unfinished.

## Developer surface

The backend is FastAPI with async SQLAlchemy. The frontend is React, Vite, and
React Query. HTTP is the full service surface; CLI and MCP expose the core
prepare, query, repository, and run-evidence workflows.

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

Prerequisites: Git, Python 3.12+, npm, and Node.js 20.19+ on the 20.x line,
22.13+ on the 22.x line, or 24+. Provider credentials are optional for local
exploration and the seeded demo.

### Docker

```bash
git clone https://github.com/Darshan174/Context-Engine.git context-engine
cd context-engine
cp .env.example .env
bash scripts/doctor.sh --docker
docker compose up --build
```

Open <http://localhost:8000>. This path runs the app, sync worker, PostgreSQL,
and pgvector.

### Bare metal

```bash
git clone https://github.com/Darshan174/Context-Engine.git context-engine
cd context-engine
cp .env.example .env
bash scripts/doctor.sh --bare-metal
bash scripts/setup.sh
bash scripts/start.sh
```

Open <http://localhost:8000>. For backend and frontend hot reload, use
`bash scripts/dev.sh`; the frontend dev server runs at <http://localhost:5000>.
See the [demo walkthrough](docs/demo.md) to seed a workspace without provider
credentials.

## Deployment

`docker-compose.yml` is the supported local PostgreSQL/pgvector deployment path.
It is not a production hardening guide. Before any non-local deployment, replace
the default database password, configure API and credential encryption keys,
terminate TLS, plan backups, and validate migrations and provider callback URLs.
Hosted-service, high-availability, and upgrade procedures are still unfinished.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Run the local CI-equivalent checks with:

```bash
bash scripts/smoke.sh
```

Maintainers should also run `bash scripts/smoke.sh --docker` before release tags.

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
- [OSS readiness](docs/oss-readiness.md)

Some documents are implementation contracts rather than public guides. The code
and tests are the authority for current behavior.

## License
MIT. See [LICENSE](LICENSE).
