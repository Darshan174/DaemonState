<p align="center">
  <img src="frontend/public/favicon.svg" width="88" height="88" alt="DaemonState logo">
</p>

<h1 align="center">DaemonState</h1>

<p align="center">
  Verified project history in. Minimum task-ready context out.
</p>

> **Active alpha.** Core workflows are implemented and tested locally. A hardened, single-host production profile is
> included for self-hosting; it is not a hosted service, multi-tenant control plane, or high-availability deployment.

## What it is

DaemonState is an open-source context and evidence layer for coding agents. It compiles verified project history
into the task-sized brief an agent needs to continue real work on a long-running codebase.

DaemonState is not another coding agent or a generic knowledge graph. The verified continuation runtime is the core
product. The compiler, checkpoints, Library, and graph support that handoff and explain what was selected and why.

## The problem

AI coding feels fast until the next session starts.

The agent has forgotten yesterday's decision. It reads stale files, repeats an abandoned approach, or says the work is
done without seeing the failed check. You spend the first part of each session rebuilding context the project has.

A larger context window does not fix this. More text can mean more old plans, duplicated facts, and irrelevant history.

## Who it is for

DaemonState is built first for solo founders and tiny teams using coding agents every day. Developers get the exact
sources, files, constraints, checks, and run evidence for the next task. Founders and non-technical users get a readable
view of the same project state without living in terminal logs.

## The bet

You should not need the newest, most expensive model for every task just because
an older or cheaper model was given poor context.

DaemonState does not make a weak model magically smarter. It removes an
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
| Capture a checkpoint | Continue automatically captures the selected session tip; supported compaction boundaries also preserve exact pre-compaction state. Both retain source-backed goals, progress, decisions, failures, files, blockers, checks, and next actions. |
| Verify the checkpoint | Continue automatically checks structure, event evidence, repository fingerprint, relevant files, and recorded command evidence without replaying imported commands. |
| Resume the work | Selecting a ready Codex, Claude Code, or OpenCode card resolves the task, compiles its evidence-linked pack, starts a fresh target agent, runs available checks, and reports the observed outcome. |
| Explain what matters | Uses the graph to show the relationships behind the current project state and compiled context. |

Extracted facts retain their source and provenance; explicit user choices are
labeled separately. Missing evidence stays missing instead of being replaced
with a confident guess.

## What works today

| Surface | Actual job |
|---|---|
| Continue | Resolves the current repository-scoped task, verifies its latest compatible checkpoint, starts a fresh installed target agent, runs available checks, and reports the outcome. |
| History | Shows task/session history, checkpoints, event evidence, repository freshness, checks, and one route back to Continue. |
| Library | Scans local Codex, Claude Code, and OpenCode history, lets the user select an exact session/topic, and routes that identity to Continue. |
| Memory | Organizes active, needs-review, and historical project facts with their evidence. |
| Explain and agent brief | Uses the project graph to explain evidence and relationships; eligible task records can compile and copy a source-backed brief. |
| Sources and connectors | Shows raw source previews, extracted components, connection state, and sync results. The API preserves revisions and enforces access scopes. |
| Local harness | Wraps one user-supplied worker command and records bounded output, Git changes, checks, and outcome evidence. |

The React app uses the FastAPI API. The `daemonstate` CLI and MCP server expose the
agent-native continuation runtime, context preparation, query, repository, and
run-evidence workflows rather than every UI view. Local development
uses SQLite; Docker can use PostgreSQL/pgvector.

## Continue without the dashboard

Resolve the active task, refresh local agent history, verify the latest
compatible checkpoint, compile the pack, and run it directly in another
installed coding harness:

```bash
daemonstate continue \
  --workspace-id <workspace-uuid> \
  --repo . \
  --into codex
```

Use `--into claude` or `--into opencode` for another harness. Continue always
starts a fresh target session; it never silently resumes the source task.
Provider CLIs run non-interactively through direct argv execution. Context is
delivered through bounded stdin or a permission-restricted temporary file, and
the local harness records Git state and outcome evidence. `ready` and
`review_required` evidence continue automatically; only blocked or unknown
states fail closed. Historical failed commands remain continuation context and
do not become launch blockers. Intermediate blocker language extracted from an
agent update is advisory unless it is explicitly typed and independently
observed as a hard continuation blocker.

Continue always runs its compiled verification contract. For arbitrary worker
commands and explicitly authorized verification, see
[Local Agent Harness](docs/agent-harness.md).

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

- The browser UI calls a local-only run service. It shows separate
  readiness-checked Codex, Claude Code, and OpenCode targets, refreshes evidence,
  starts a fresh explicitly selected provider CLI, observes the repository, and
  runs available checks; it is unavailable to remote principals. Explicit
  choices never silently fall back. `daemonstate continue --into ...` launches an
  explicitly selected provider CLI. MCP `resume_task` returns the pack to its
  calling agent without starting another process.
- There is no system-wide agent monitor. Library scans while its page is open;
  Continue refreshes linked local histories; other integrations must report events.
- HTTP and MCP run records contain observations supplied by their caller. The
  local harness is the path that independently inspects Git state and commands.
- `daemonstate harness run` still runs only the explicit local command supplied by the
  user. `daemonstate continue --into ...` selects one of three audited built-in
  provider adapters and never adds permission-bypass flags.
- On macOS, browser Continue uses Codex's persistent app-server to reopen an exact Codex task
  after it is renderable. Providers without an exact-session
  surface are unavailable rather than invisible; other platforms are unsupported.
- Scrutiny uses deterministic evidence rules. It is not an autonomous code review.
- Live retrieval is limited to the local repository and configured manual-token
  GitHub access.
- Captured command output and repository inspection are deliberately bounded.
- A provider exit without both an observed agent repository change and a
  passing executable check is `completed_unverified`, not a verified handoff.
  Product acceptance additionally requires a paired real-task
  test showing that another agent continued correctly without re-explanation,
  with less discovery and no stale-context mistake.
- Model-lift reports describe observed runs. They do not yet prove that an older
  model matches a newer one because of DaemonState.
- The production profile is deliberately single-tenant. Per-principal API keys are rejected until action-level
  authorization covers every HTTP and MCP operation.
- MCP is a trusted local stdio surface; expose the authenticated HTTP API, not the MCP process, across a network.
- The production deployment has one Docker host as its failure domain. Multi-host failover, managed storage, and
  multi-region recovery remain operator responsibilities.

## Developer surface

The backend is FastAPI with async SQLAlchemy. The frontend is React, Vite, and
React Query. HTTP is the full service surface; CLI and MCP expose the core
prepare, query, repository, and run-evidence workflows.

Main API routes:

| Route | Purpose |
|---|---|
| `POST /api/context/prepare` | Compile and persist a task brief. |
| `POST /api/continuations/prepare` | Resolve current task state, verify its compatible checkpoint, and compile a continuation pack. |
| `POST /api/continuations` | From the local app, prepare a continuation, start a fresh installed target agent, run available checks, and record the outcome. `/api/continuations/run` remains a compatibility alias. |
| `POST /api/query` | Query project context with a source trace. |
| `POST /api/repo/index` | Index repository files, symbols, and exact structural links. |
| `GET /api/context/run-timeline` | Read observed agent work and scrutiny findings. |
| `GET /api/context/open-loops` | List evidence-backed unresolved work. |
| `GET /api/context/playbooks` | Review reusable steps from verified runs. |

Useful CLI commands:

```text
daemonstate prepare
daemonstate continue
daemonstate query
daemonstate repo index
daemonstate repo watch
daemonstate harness run
daemonstate harness report
daemonstate eval harness
daemonstate mcp
daemonstate db deploy
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
git clone https://github.com/Darshan174/DaemonState.git daemonstate
cd daemonstate
cp .env.example .env
bash scripts/doctor.sh --docker
docker compose up --build
```

Open <http://localhost:8000>. This path runs the app, sync worker, PostgreSQL,
and pgvector.

### Bare metal

```bash
git clone https://github.com/Darshan174/DaemonState.git daemonstate
cd daemonstate
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

`docker-compose.yml` is the supported local PostgreSQL/pgvector deployment path. It is not a production hardening guide.

For a hardened single-host deployment, use `docker-compose.production.yml` and follow the
[production runbook](docs/production-runbook.md). It fails closed on invalid settings, gates startup on migrations,
exposes only a TLS proxy, keeps PostgreSQL/pgvector and Redis internal, drops runtime privileges, bounds requests and
resources, and includes backup and guarded restore tooling.

The production profile requires immutable image references, file-backed
secrets, an explicit read-only repository root, and `daemonstate db deploy` before API
startup. Validate it in staging and complete the runbook's load, restore, and
security checks against your own SLO/RPO/RTO before serving real traffic.

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
- [Continuation Runtime](docs/continuation-runtime.md)
- [Local Agent Harness](docs/agent-harness.md)
- [MCP](docs/mcp.md)
- [AI session imports](docs/ai-context.md)
- [Demo walkthrough](docs/demo.md)
- [Production runbook](docs/production-runbook.md)
- [OSS readiness](docs/oss-readiness.md)

Some documents are implementation contracts rather than public guides. The code
and tests are the authority for current behavior.

## License
MIT. See [LICENSE](LICENSE).
