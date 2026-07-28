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

DaemonState is a source-available, self-hosted context and evidence layer for coding agents. It continuously compiles workspace evidence into a durable Project Context foundation and combines that parent with task-specific Session Context when an agent continues real work on a long-running codebase.

DaemonState is not another coding agent or a generic knowledge graph. The verified continuation runtime is the core product. The compiler, checkpoints, Library, and graph support that handoff and explain what was selected and why.

## Context hierarchy

Project / Workspace Context is the durable, objective-independent parent foundation: project identity, workflows, architecture, domain model, repository and technology map, persistent decisions and conventions, canonical commands, capabilities, long-term constraints and risks, and product direction. It is compiled workspace-wide and never selected by the current prompt, objective, file overlap, session lead, or task ranking.

Session Context is the latest individual session's task-specific child: goal, acceptance criteria, state, next step, decisions, attempts, changes, discoveries, verification, open items, scope, and repository state. Failures and transient blockers stay session-only. A durable session outcome enters the parent only when it is human-confirmed or independently corroborated and consistent with current workspace evidence.

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
| Capture Session Context | Continue automatically captures the selected session tip as the latest task child; supported compaction boundaries also preserve exact pre-compaction state. Both retain source-backed goals, progress, decisions, failures, files, blockers, checks, and next actions. |
| Verify the checkpoint | Continue automatically checks structure, event evidence, repository fingerprint, relevant files, and recorded command evidence without replaying imported commands. |
| Resume the work | Continue defaults to the newest available session, copies its Session Context, and requests a reviewable composer in the selected desktop harness. Nothing is submitted until the user reviews and sends it. |
| Explain what matters | Uses the graph to show the relationships behind the current project state and compiled context. |

Extracted facts retain their source and provenance; explicit user choices are
labeled separately. Missing evidence stays missing instead of being replaced
with a confident guess.

## What works today

| Surface | Actual job |
|---|---|
| Continue | Resolves the current repository-scoped task, verifies its latest compatible checkpoint, copies the complete handoff, and requests a reviewable composer in the selected Codex, Claude, or OpenCode desktop app without submitting it. |
| Library | Scans local Codex, Claude Code, and OpenCode history, lets the user inspect checkpoints and select an exact session/topic, and routes that identity to Continue. |
| Memory | Shows the durable Project / Workspace Context parent and the latest task-specific Session Context child, with evidence and review state. |
| Explain and agent brief | Uses the project graph to explain evidence and relationships; eligible task records can compile and copy a source-backed brief. |
| Sources and connectors | Shows raw source previews, extracted components, connection state, and sync results. The API preserves revisions and enforces access scopes. |
| Local harness | Wraps one user-supplied worker command and records bounded output, Git changes, checks, and outcome evidence. |
| macOS floating control | Turn the logo on or off from Continue; click it to verify, copy, and paste the Session Context child without submitting, or triple-click for the workspace-wide Project / Workspace Context parent. See the [guide](docs/floating-context-control.md). |

The React app uses the FastAPI API. The `daemonstate` CLI and MCP server expose the agent-native continuation runtime,
context preparation, query, repository, and run-evidence workflows rather than every UI view. Local development uses SQLite; Docker can use PostgreSQL/pgvector.

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

Use `--into claude` or `--into opencode` for another harness. Continue starts a fresh target session and never silently
resumes the source task. Provider CLIs run non-interactively through direct argv execution. Context uses bounded stdin or
a permission-restricted temporary file, and the local harness records Git state and outcomes. `ready` and `review_required`
evidence continue automatically; blocked or unknown states fail closed. Historical failures stay in Session Context and do
not block launch or become Project Context facts unless independently observed and durable beyond the task.

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

- The browser UI calls the local-only `/api/continuations/stage` service. It
  checks the selected Codex, Claude, or OpenCode desktop app and registered URL
  scheme, copies the complete context, and requests a visible composer without
  invoking a provider CLI or submitting a task. Explicit choices never silently
  fall back. Separately, `daemonstate continue --into ...` launches an explicitly selected provider
  CLI through the typed execution contract.
  MCP `resume_task` returns the audit pack and canonical execution contract to
  its calling agent without starting another process.
- There is no system-wide agent monitor. Library scans while its page is open;
  Continue refreshes linked local histories; other integrations must report events.
- HTTP and MCP run records contain observations supplied by their caller. The
  local harness is the path that independently inspects Git state and commands.
- `daemonstate harness run` still runs only the explicit local command supplied by the
  user. `daemonstate continue --into ...` selects one of three audited built-in
  provider adapters and never adds permission-bypass flags.
- On macOS, browser Continue requests a new composer through the selected
  desktop app's registered native URL scheme and copies the complete context.
  Launch Services dispatch is reported as requested, not as a verified open or exact provider session; other platforms are unsupported.
- Scrutiny uses deterministic evidence rules. It is not an autonomous code review.
- Live retrieval is limited to the local repository and configured GitHub access.
- Captured command output and repository inspection are deliberately bounded.
- A provider exit or worker-authored success summary is never proof. Only requirement-linked evidence can produce
  `verified_complete`; other outcomes
  remain explicitly unproven, failed, or blocked. Product acceptance also requires a paired real-task test showing
  that another agent continued correctly without re-explanation,
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
| `POST /api/continuations/stage` | From the local app, copy the complete handoff and request a visible new composer in the selected Codex, Claude, or OpenCode desktop app without submitting a turn. |
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

The Docker profile needs Git, Docker, and current Compose v2 with `up --wait`. The workstation profile also needs Python 3.12+, npm, and
Node.js 20.19+ on the 20.x line, 22.13+ on the 22.x line, or 24+. Provider credentials are optional for local
exploration and the seeded demo.

### Docker

```bash
git clone https://github.com/Darshan174/DaemonState.git daemonstate
cd daemonstate
bash scripts/self-host.sh
```

Open <http://127.0.0.1:8000>. This loopback-only path runs the dashboard, migration gate, sync worker, PostgreSQL,
and pgvector. Containers can inspect the configured read-only project, but cannot launch coding-agent tools installed
only on the host. See [Self-hosting](docs/self-hosting.md) for remote access, persistence, backups, and upgrades.

### Bare metal

```bash
git clone https://github.com/Darshan174/DaemonState.git daemonstate
cd daemonstate
bash scripts/doctor.sh --bare-metal
bash scripts/setup.sh
bash scripts/start.sh
```

Open <http://localhost:8000>. For backend and frontend hot reload, use
`bash scripts/dev.sh`; the frontend dev server runs at <http://localhost:5000>.
See the [demo walkthrough](docs/demo.md) to seed a workspace without provider
credentials.

## Deployment

`docker-compose.yml` is the supported personal PostgreSQL/pgvector deployment path. It is not a production hardening guide.

For a hardened single-host deployment, use `docker-compose.production.yml` and follow the
[production runbook](docs/production-runbook.md). It fails closed on invalid settings, gates startup on migrations,
exposes only a TLS proxy, keeps PostgreSQL/pgvector and Redis internal, drops runtime privileges, bounds requests and
resources, and includes backup and guarded restore tooling.

The production profile requires immutable image references, file-backed
secrets, an explicit read-only repository root, and `daemonstate db deploy` before API
startup. Validate it in staging and complete the runbook's load, restore, and
security checks against your own SLO/RPO/RTO before serving real traffic.

## Contributing

Outside code and documentation submissions are paused pending a contributor agreement; see [CONTRIBUTING.md](CONTRIBUTING.md). Maintainers can run the local CI-equivalent checks with:

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
- [Continuation Runtime](docs/continuation-runtime.md) and [OpenTelemetry tracing](docs/opentelemetry.md)
- [Local Agent Harness](docs/agent-harness.md)
- [MCP](docs/mcp.md)
- [AI session imports](docs/ai-context.md)
- [Demo walkthrough](docs/demo.md)
- [Self-hosting](docs/self-hosting.md)
- [Production runbook](docs/production-runbook.md)
- [Release readiness](docs/release-readiness.md)
- [Licensing](docs/licensing.md)

Some documents are implementation contracts rather than public guides. The code and tests are the authority for current behavior.

## License

DaemonState 0.3.0 and later use the source-available Sustainable Use License 1.0 (`SUL-1.0`): personal,
noncommercial, and internal business self-hosting are allowed; paid product/service use is not. The final MIT source
is commit `45b7a6e653a1762bf91b99fae4c7adf3dafc55ce`. See [LICENSE](LICENSE) and [Licensing](docs/licensing.md).
