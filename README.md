<p align="center">
  <img src="frontend/public/favicon.svg" width="88" height="88" alt="DaemonState logo">
</p>

<h1 align="center">DaemonState</h1>

<p align="center">
  Continue the work. Not the explanation.
</p>

> **Active alpha.** DaemonState is source-available and self-hosted. The core
> workflows run locally today, but the product is still evolving. It is not a
> hosted service, a multi-tenant control plane, or a high-availability platform.

## Why DaemonState

AI coding agents are useful until a new session starts with none of the history
that made the previous session productive. The next agent may miss a decision,
repeat a failed approach, read stale files, or claim success without seeing the
failed check.

DaemonState turns project history into a small, source-backed handoff for the
next session. It keeps long-lived project knowledge separate from temporary task
details, checks both against the current repository, and shows where every
important claim came from.

DaemonState is not another coding agent or a generic knowledge graph. It is the
continuity and evidence layer between your projects and the agents you already
use.

## Who it is for

- **Developers** get the relevant files, decisions, constraints, failed
  attempts, checks, and exact next step for the task in front of them.
- **Founders and non-technical users** get a readable view of project progress,
  risks, decisions, and evidence without digging through terminal logs.
- **Small teams** can move work between Codex, Claude Code, and OpenCode without
  rebuilding the project story in every chat.

DaemonState may also help older, cheaper, or open models do more useful work by
giving them better context. We have not proven that yet. The evaluation harness
can record comparisons, but real-project results are still needed.

## What you can do today

| Feature | What it helps you do |
|---|---|
| Continue | Finds the newest in-project agent session, verifies its latest compatible checkpoint, and opens its Session Context in a new Codex, Claude, or OpenCode desktop composer. You review the draft and submit it yourself. |
| Execute | Previews or copies the workspace-wide Project Context together with up to three Session Contexts chosen from Library. Each context keeps its own boundary and quality gate. |
| Library | Discovers local Codex, Claude Code, and OpenCode history, searches it by harness or topic, and lets you prepare an older session without replacing Continue's current-session choice. It also exposes recovery checkpoints captured before supported compactions. |
| Evidence | Shows goals, decisions, sources, conflicts, files, open loops, and the relationships between them. Explain and agent brief actions can compile a focused, source-backed brief for eligible records. |
| Memory | Lets you inspect durable project knowledge, review uncertain claims, compare conflicts, and preserve superseded or dismissed history without treating it as current truth. |
| Sources | Shows raw source previews, extracted records, and revision history. The API preserves revisions and enforces access scopes. |
| Integrations | Shows exactly what is connected, ready to configure, or coming soon. Demo data never pretends that a provider is authenticated. |
| macOS floating control | Optionally verifies, copies, and pastes Session or Workspace Context into the editor that had focus. It never presses Return or submits a message. |

The React dashboard uses the FastAPI service. The `daemonstate` CLI and MCP
server expose continuation, context preparation, querying, repository indexing,
and run evidence rather than every UI view.

## How continuation works

1. **Find the task.** DaemonState uses the newest eligible in-project session,
   an explicit request, or the active workspace goal. Backlog items do not
   silently become the current task.
2. **Capture the state.**
   Continue automatically captures the selected session tip as an immutable
   checkpoint with the goal, progress, decisions, attempts, changed files,
   checks, blockers, and next action.
3. **Verify it.** The checkpoint is compared with the current repository,
   relevant files, recorded events, and command evidence. Imported commands are
   evidence only and are never replayed automatically.
4. **Build the handoff.** DaemonState combines the task-specific Session Context
   with relevant facts from the durable Project Context foundation.
5. **Put you in control.** Browser Continue requests a new composer in the
   desktop app you choose. It copies or prefills the verified handoff, then
   waits for you to review and send it.

## The two context types

| Context | What belongs in it |
|---|---|
| **Project Context** | Project identity, architecture, workflows, commands, conventions, durable decisions, capabilities, constraints, risks, and direction. It is the objective-independent parent shared by every session. |
| **Session Context** | One session's goal, acceptance criteria, progress, decisions, attempts, changes, discoveries, verification, blockers, scope, and exact next action. It is the task-specific child. |

Failed attempts and temporary blockers stay in Session Context. A session claim
can enter Project Context only when it is durable and mechanically verified,
human-confirmed, or independently corroborated. Missing evidence remains
missing instead of being replaced with a confident guess.

## Quick start

Choose the workstation install for the complete local experience, including
local agent history and coding-agent tools. Choose Docker when you mainly want
the dashboard, API, integrations, or demo.

### Full local experience

You need Git, Python 3.12+, npm, and Node.js 20.19+ on the 20.x line,
22.13+ on the 22.x line, or 24+. Browser-to-desktop Continue currently requires
macOS and an installed Codex, Claude, or OpenCode desktop app.

```bash
git clone https://github.com/Darshan174/DaemonState.git daemonstate
cd daemonstate
bash scripts/doctor.sh --bare-metal
bash scripts/setup.sh
bash scripts/start.sh
```

Open <http://localhost:8000>, then:

1. Add a workspace and point it at your repository.
2. Open **Library** to confirm that your local agent sessions were discovered.
3. Open **Continue**, choose a ready desktop harness, and review the generated
   draft before sending it.
4. Use **Execute** for explicitly chosen historical contexts and **Evidence** to
   inspect why a claim was included.

For backend and frontend hot reload, run `bash scripts/dev.sh`; the Vite
development server is available at <http://localhost:5000>.

### Docker dashboard

You need Git, Docker, and a current Docker Compose v2 with `up --wait` support.

```bash
git clone https://github.com/Darshan174/DaemonState.git daemonstate
cd daemonstate
bash scripts/self-host.sh
```

Open <http://127.0.0.1:8000>. This loopback-only profile includes the dashboard,
API, migration gate, sync worker, PostgreSQL, and pgvector.

Docker mounts the configured project read-only and cannot access coding-agent
apps or histories installed only on the host. Use the workstation install when
you want desktop continuation or agents to edit the repository. The personal
`docker-compose.yml` profile is the supported self-hosting path.
It is not a production hardening guide. See
[Self-hosting](docs/self-hosting.md) for project mounts, remote access,
persistence, backups, and upgrades.

### Try the demo

After either install is running:

```bash
curl -X POST http://localhost:8000/api/seed-demo \
  -H 'content-type: application/json' \
  -d '{}'
```

Select **DaemonState Demo** in the workspace chooser. The seed adds example
GitHub, Slack, Gmail, Google Drive, and Codex evidence without storing
credentials or marking any connector connected. Follow the
[Demo walkthrough](docs/demo.md).

## Continue from the terminal

The CLI can prepare the current task and run it in a fresh local provider
session:

```bash
daemonstate continue \
  --workspace-id <workspace-uuid> \
  --repo . \
  --into codex
```

Use `--into claude` or `--into opencode` for another provider. Unlike the
browser's reviewable composer flow, this command runs the selected provider CLI
non-interactively, records bounded Git and check evidence, and never adds
permission-bypass flags. A provider's exit code or success message is not proof
that the task is complete.

Other useful commands:

```text
daemonstate prepare
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
edit code, run shell commands, push commits, or write to external providers.
See [MCP](docs/mcp.md) and [MCP examples](examples/mcp/).

## Supported sources

"Available" means there is a tested backend path that can create source
documents when configured. It does not mean onboarding is finished.

| Source | Current status |
|---|---|
| Local repositories, files, and browser uploads | Available |
| Codex, Claude Code, OpenCode, and generic session imports | Available |
| GitHub | Available with a personal access token |
| Slack | Available with Slack app or OAuth setup |
| Gmail and Google Drive | Available with Google OAuth setup |
| Discord, Zoom, and Wispr Flow | Coming soon |
| Notion | Not catalogued as a launch connector |

## Current limits and safety boundaries

- Browser Continue is a local macOS handoff. It checks desktop-app readiness,
  copies the context, and asks the selected app to open a visible composer. The
  macOS launch request is reported as requested, not as a verified open or
  exact provider session, and nothing is submitted automatically. Codex
  account, model, and explicit rate-limit status is checked automatically when
  its local app-server supports those read-only methods; an inconclusive check
  never requires a manual attestation before opening the draft.
- There is no system-wide agent monitor. Library scans while it is open,
  Continue refreshes linked local histories, and other integrations must report
  their own events.
- HTTP and MCP run records contain caller-supplied observations. The local
  harness is the path that independently inspects Git state and commands.
- Scrutiny is deterministic evidence checking, not autonomous code review.
  Only requirement-linked evidence can produce `verified_complete`.
- Live retrieval is currently limited to the local repository and configured
  GitHub access. Repository inspection and captured command output are bounded.
- The hardened deployment is single-tenant and single-host. Multi-host
  failover, managed storage, and multi-region recovery are not included.
- Model-lift reports describe observed runs; they do not prove that a smaller
  or older model matches a frontier model because of DaemonState.

## Deployment and development

For an internet-facing API, use `docker-compose.production.yml` and follow the
[production runbook](docs/production-runbook.md). It provides TLS, authenticated
API access, internal PostgreSQL/pgvector and Redis, migration gates, resource
limits, metrics, backups, and guarded restore tooling. The public profile does
not serve the browser dashboard.

The backend is FastAPI with async SQLAlchemy. The frontend is React, Vite, and
React Query. Local development uses SQLite; Docker uses PostgreSQL/pgvector.

Maintainers can run the local CI-equivalent checks with:

```bash
bash scripts/smoke.sh
```

Run `bash scripts/smoke.sh --docker` before release tags.

## Documentation

- [Architecture](docs/architecture.md)
- [Continuation runtime](docs/continuation-runtime.md)
- [Context Pack v2](docs/context-pack-v2.md)
- [Connectors](docs/connectors.md)
- [Local agent harness](docs/agent-harness.md)
- [AI session imports](docs/ai-context.md)
- [Floating context control](docs/floating-context-control.md)
- [OpenTelemetry tracing](docs/opentelemetry.md)
- [Self-hosting](docs/self-hosting.md)
- [Production runbook](docs/production-runbook.md)
- [Release readiness](docs/release-readiness.md)
- [Licensing](docs/licensing.md)

## Contributing

Outside code and documentation submissions are paused pending a contributor
agreement; see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

DaemonState 0.3.0 and later use the source-available Sustainable Use License 1.0
(`SUL-1.0`). Personal, noncommercial, and internal business self-hosting are
allowed; paid product or service use is not. The final MIT-licensed source is
commit `45b7a6e653a1762bf91b99fae4c7adf3dafc55ce`. See [LICENSE](LICENSE) and
[Licensing](docs/licensing.md).
