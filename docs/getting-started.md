# Getting started

This guide takes a new checkout from prerequisites to a verified first product
loop. The workstation profile is the complete local experience. The Docker
profile is useful for the dashboard, API, demo, and read-only repository
inspection, but it cannot reach coding-agent history or desktop applications
installed only on the host.

## Choose a profile

| Profile | Choose it when | Includes | Important boundary |
|---|---|---|---|
| Workstation | DaemonState and your coding agents run on the same development machine. | Dashboard/API, SQLite, sync worker, local session discovery, CLI adapters, and optional macOS floating control. | Intended for loopback access on one user workstation. |
| Personal Docker | You want an isolated local service or a quick demo. | Dashboard/API, PostgreSQL/pgvector, migrations, sync worker, and one read-only repository mount. | Cannot discover host-only sessions, open desktop apps, or write to the mounted repository. |
| Hardened single-host | You need an authenticated internet-facing API. | TLS proxy, API, PostgreSQL/pgvector, Redis, worker, Prometheus, migration gate, and guarded backup/restore tooling. | No browser dashboard; single tenant and single host. Follow the production runbook. |

## Workstation install

### Prerequisites

- Git
- Python 3.12 or newer
- npm
- Node.js 20.19+ on the 20.x line, 22.13+ on the 22.x line, or 24+
- Optional: installed and authenticated Codex, Claude Code, or OpenCode tools
- For browser desktop handoff: macOS and the corresponding desktop app
- For the floating control: macOS plus the Swift toolchain

Run the read-only prerequisite check before installing anything:

```bash
git clone https://github.com/Darshan174/DaemonState.git daemonstate
cd daemonstate
bash scripts/doctor.sh --bare-metal
```

The doctor checks the checkout, Python and Node versions, npm, the local virtual
environment, frontend dependencies, and the built dashboard. It reports
missing setup without installing packages or changing the machine.

### Install

```bash
bash scripts/setup.sh
```

The setup script:

1. creates a permission-restricted `.env` from `.env.example` when needed;
2. generates local PostgreSQL and Fernet encryption secrets;
3. creates `.venv` unless `DAEMONSTATE_USE_SYSTEM_PYTHON=1` is explicitly set;
4. installs the Python package and development dependencies in editable mode;
5. runs `npm ci` in `frontend/`; and
6. builds the production browser bundle.

Provider credentials and model keys are optional for local repository/session
work and for the demo. Keep secrets in the untracked `.env` file.

### Start

```bash
bash scripts/start.sh
```

The supervisor starts the FastAPI service, waits for
`http://127.0.0.1:8000/health/ready`, then starts the connector sync worker. It
uses `.venv/bin/python` automatically when present. Stop it with `Ctrl-C`.

Open <http://localhost:8000>. The default workstation service binds to
`127.0.0.1`; `scripts/start.sh` rejects a remote bind unless the explicit
advanced override is set. Use the production profile for a remote API.

To run only the API because a separate service manager owns the worker:

```bash
DAEMONSTATE_START_WORKER=0 bash scripts/start.sh
```

## Connect the first project

1. Open the product at `/app`.
2. Choose **Connect your first real project**.
3. Enter an absolute local Git repository path visible to the DaemonState
   process. The suggested workspace name comes from the directory name.
4. Select **Connect project**.

DaemonState creates a workspace, validates and indexes the repository, and only
keeps the workspace if indexing succeeds. One workspace should represent one
real project. That boundary scopes sessions, sources, claims, context packs,
and runs so information from different repositories does not bleed together.

The initial index records bounded repository structure, files, symbols,
routes, manifests, and current Git state. It does not run project commands.

## Complete the first product loop

### 1. Inspect Library

Open **Library** and select **Sync now**. The workstation service discovers
local Codex, Claude Code, and OpenCode history from the configured or default
locations, excludes internal sessions, and keeps only sessions whose metadata
matches the workspace repository scope.

If nothing appears, see [Session discovery troubleshooting](#session-discovery-troubleshooting).

### 2. Use Continue

Continue is intentionally opinionated: it uses the newest eligible root session
for the selected project. A Library selection, URL parameter, or old recovery
point cannot silently replace it.

1. Review the detected session, current lead, repository freshness, and provider
   readiness.
2. Edit the current lead only when the visible historical wording is no longer
   the instruction you want to carry forward.
3. Select a ready Codex, Claude, or OpenCode card.
4. DaemonState captures the session tip, compiles and verifies the handoff,
   copies the complete Session Context, and requests a new composer through the
   app's macOS URL scheme.
5. Confirm the destination, paste if the bounded native prefill was not used,
   review the draft, and submit it yourself.

Dispatch does not prove the target app rendered a composer. DaemonState does
not create an agent run, press Enter, or report work before the user submits.

### 3. Use Execute

Execute compiles Workspace Context for the repository independently of a task
or selected session. It also shows up to three historical Session Contexts
explicitly chosen in Library.

1. Open **Execute** and wait for Workspace Context compilation.
2. Preview the product contract, architecture, capabilities, commands,
   repository state, durable facts, evidence, and known gaps.
3. Copy only when the compiler's integrity and quality gate is ready. Copy
   recompiles against the live repository rather than trusting a cached preview.
4. Choose **Session Library**, enter Execute selection mode, and select up to
   three sessions to compare or copy beside the workspace-wide parent.

The current browser eligibility rule requires two detected provider compactions
before an individual historical Session Context can be copied. Recovery
checkpoints can still be inspected before that gate.

### 4. Know which routes are not ready

Evidence, Sources, and Integrations appear in navigation but are intentionally
covered by an **Under construction** overlay. Their backend routes and data
models exist; the overlay means those browser workflows are not supported yet.
Do not use the hidden UI beneath the overlay as a product guarantee. Use the
documented API or CLI when you need those capabilities now.

## Development mode

After running setup:

```bash
bash scripts/dev.sh
```

- API: <http://localhost:8000>
- Vite frontend: <http://localhost:5000>

The backend does not reload by default, which keeps open product pages stable
during frontend work. Opt in when needed:

```bash
DAEMONSTATE_BACKEND_RELOAD=1 bash scripts/dev.sh
```

## Personal Docker install

Run the Docker-specific doctor, then start the wrapper:

```bash
bash scripts/doctor.sh --docker
bash scripts/self-host.sh
```

On first run, the wrapper creates `.env` with mode `0600`, generates local
secrets, validates the repository mount, builds the image, runs the one-shot
migration service, and waits for the API and worker to become healthy.

Open <http://127.0.0.1:8000>. To inspect another repository, set its absolute
host path in `.env` and recreate the services:

```dotenv
DAEMONSTATE_PROJECT_PATH=/absolute/path/to/project
```

```bash
bash scripts/self-host.sh
```

The wrapper rejects the filesystem root, the whole home directory, missing
paths, and remote binds without an explicit override. Inside the container,
enter `/workspace` when the UI asks for the repository path.

Useful Docker operations:

```bash
docker compose ps
docker compose logs --follow app worker
docker compose restart app worker
docker compose down
```

`docker compose down` preserves named volumes. Adding `--volumes` permanently
deletes the Compose database and uploaded artifacts. Read the backup section in
[Self-hosting](self-hosting.md) before destructive maintenance.

## Seed a credential-free demo

With either profile running:

```bash
curl -X POST http://localhost:8000/api/seed-demo \
  -H 'content-type: application/json' \
  -d '{}'
```

Select **DaemonState Demo**. The seed is idempotent and creates clearly marked
GitHub, Slack, Gmail, Google Drive, and Codex source evidence. It stores no
provider credentials and does not mark a connector connected. Continue and
local-session discovery are not meaningful for the sample workspace; use it to
inspect workspace separation, counts, APIs, and source-backed outputs. Follow
the [Demo walkthrough](demo.md).

## Verify the installation

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/health/ready
```

`/health` is a liveness probe. `/health/ready` verifies startup, the current
database schema, the configured rate-limit backend, and production credential
readiness where applicable.

Maintainers can run the CI-equivalent local checks:

```bash
bash scripts/smoke.sh
```

Use `bash scripts/smoke.sh --docker` before a release tag.

## Troubleshooting

### Session discovery troubleshooting

- Confirm DaemonState runs as the same OS user that owns the local agent history.
- Confirm the session metadata contains a working directory or project path
  that resolves to the connected repository.
- Set `CODEX_HOME`, `CLAUDE_HOME`, or `OPENCODE_HOME` only when the tool uses a
  non-default data directory, then restart the API.
- Open Library and use **Sync now**. Continue performs a narrower latest-session
  discovery and does not wait for a full historical library refresh.
- Docker cannot see agent histories outside its mounts; use the workstation
  profile for automatic local discovery.

### Workspace Context is not copy-ready

Open the preview and read the quality issues. Common causes are an unavailable
repository, an incomplete repository snapshot, missing repository-stated
product/architecture evidence, hash mismatches, conflicting current facts, or
an integrity failure. A dirty worktree is represented as evidence; it is not by
itself permission to infer the intent or completion state of those changes.

Compilation never runs project checks. Current test/runtime evidence enters
Workspace Context only from a matching, complete local-harness observation.

### A provider card is unavailable

- Install the matching desktop app for browser handoff and confirm macOS has a
  registered URL handler.
- For CLI execution, confirm the provider CLI is installed and authenticated.
- Codex account/model/rate-limit checks are read-only and may be inconclusive;
  the dashboard reports that separately from the hard desktop-dispatch gate.
- A task can still be blocked when the provider cannot enforce its required
  image, permission, filesystem, or execution capability.

### The dashboard returns 401

The bundled local browser does not yet implement a login/session flow. Setting
`SERVER_API_KEY` protects API clients but prevents the browser from calling the
API. Leave it unset in the loopback personal profiles. The production profile
sets `SERVE_FRONTEND=false` and requires API authentication.

### The API does not become ready

Run:

```bash
bash scripts/doctor.sh --bare-metal
```

Then inspect the API output. For a Docker install, use:

```bash
docker compose ps --all
docker compose logs app migrate db worker
```

Schema errors require `daemonstate db deploy`; production configuration errors
are fail-closed and identify the missing or unsafe setting in the startup log.

## Next steps

- Learn the product model in the [Product guide](product-guide.md).
- Configure models, OAuth, storage, or security in [Configuration](configuration.md).
- Automate local workflows with the [CLI](cli-reference.md).
- Integrate an API client with the [HTTP API](api-reference.md).
- Configure an agent client with [MCP](mcp.md).
