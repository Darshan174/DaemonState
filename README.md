# Context Engine

Structured context infrastructure for AI systems and fast-moving teams.

Context Engine turns scattered company knowledge into source-backed, reviewable
context. It ingests documents and operational data, extracts structured facts,
tracks provenance, flags conflicts, and exposes the result through an API and an
operator UI.

It is designed for teams that need answers with evidence, not generic retrieval.

## What It Does

- Ingests company context from local files and connector-backed sources.
- Extracts structured facts, decisions, blockers, relationships, and timelines.
- Stores every fact with provenance back to source documents.
- Serves source-backed answers through `POST /api/query`.
- Provides workflow views for founder briefs, decisions, changes, launch checks,
  engineering context, review items, sources, models, and graph exploration.
- Runs self-hosted with Postgres, pgvector, Redis, Celery, FastAPI, and React.

## Why It Exists

Company knowledge usually lives across Slack threads, Notion pages, Zoom
transcripts, GitHub issues, meeting notes, support tickets, and local documents.
Those sources often disagree, age out, or lose the rationale behind decisions.

Context Engine is built around a stricter model:

- facts should be structured
- answers should cite sources
- stale or conflicting information should be visible
- operators should be able to inspect and correct the system
- self-hosting should be possible without a managed SaaS dependency

## Architecture

![Context Engine Architecture](./assets/context-engine-architecture.svg)

### Backend

- FastAPI
- SQLAlchemy async ORM
- PostgreSQL with `pgvector`
- Redis
- Celery
- Alembic migrations

### Frontend

- React
- Vite
- React Query
- React Router

### Runtime Services

The default Docker Compose stack runs:

- `postgres`: durable source documents, facts, relationships, reviews, evals
- `redis`: Celery broker and transient queue state
- `api`: FastAPI backend and production frontend assets
- `worker`: background ingestion and processing tasks

## Quick Start

Prerequisites:

- Docker Engine with Compose v2
- Docker daemon running
- `curl`

On macOS or Windows, start Docker Desktop first. On Linux, start the Docker
service if it is not already running:

```bash
sudo systemctl start docker
```

Then bootstrap the full stack:

```bash
git clone <repo-url> context-engine
cd context-engine
bash scripts/bootstrap.sh
```

The bootstrap script is idempotent. It will:

1. check for Docker, Docker Compose v2, and `curl`
2. create `.env` from `.env.example` if needed
3. generate `ENCRYPTION_KEY` if missing
4. build the frontend into the Docker image
5. start Postgres, Redis, the API, and the Celery worker
6. run database migrations
7. seed the demo workspace through `POST /api/seed-demo`

Open the app:

```text
http://localhost:8000
```

Useful local URLs:

- App UI: `http://localhost:8000`
- System health: `http://localhost:8000/app/status`
- API docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`
- Readiness: `http://localhost:8000/health/ready`

Verify the running stack:

```bash
bash scripts/smoke.sh
```

Stop the stack:

```bash
docker compose down
```

Restart it later:

```bash
docker compose up -d
```

## Default Self-Hosted Mode

No external API keys are required for the default OSS path. If model provider
settings are blank, Context Engine uses local deterministic embeddings and a
rule-based extraction fallback.

This keeps the first-run path simple:

- no hosted database
- no managed queue
- no Node.js required on the host for normal self-hosting
- no Python virtualenv required for normal self-hosting
- frontend is served by the API container at `http://localhost:8000`

For production or VPS deployment notes, see
[docs/self-hosting.md](./docs/self-hosting.md).

## Product Workflows

The app includes:

- **Founder Brief**: recent changes, blockers, conflicts, and risk signals
- **Ask**: source-backed question answering over a selected workspace
- **Decision Register**: current and historical decisions with rationale
- **Changes**: timeline of updates, ingests, reviews, and failures
- **Launch Guard**: check outbound claims against current known truth
- **Sources**: source documents and imported evidence
- **Models**: extracted knowledge models and their components
- **Knowledge Graph**: model and component graph exploration
- **Review Queue**: low-confidence, stale, or conflicting facts
- **System Health**: read-only operator status for self-hosted deployments

## Stable API Surface

Founder-workflow routes:

| Workflow | Endpoint |
| --- | --- |
| Workspaces | `GET /api/workspaces`, `POST /api/workspaces` |
| Demo seed | `POST /api/seed-demo` |
| Local import | `POST /api/imports` |
| Query | `POST /api/query` |
| Founder brief | `GET /api/founder-brief` |
| Decisions | `GET /api/decisions` |
| Sources | `GET /api/source-documents` |
| System health | `GET /api/operator/status` |

The broader operator and system API also includes graph, models, connectors,
trust/review, launch guard, timeline, and eval routes. The router entrypoint is
[app/api/router.py](./app/api/router.py).

## CLI

The `ctxe` CLI is available for maintainers and local development after
installing the Python package. It is not required for the one-command Docker
self-host flow.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Common commands:

```bash
ctxe up
ctxe demo
ctxe ingest ./notes
ctxe query --workspace "Local Workspace" "What changed?"
ctxe verify
```

Workspace selection rules are explicit:

- `--workspace UUID` targets that exact workspace
- `--workspace NAME` matches an exact workspace name case-insensitively
- ambiguous names fail
- API calls always remain workspace-scoped

## Local Development

Run the backend with local Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Run the worker:

```bash
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2
```

Run the frontend with hot reload:

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies API requests to `http://localhost:8000`.

For normal self-hosting, skip the dev server. The Docker image already includes
the production frontend build.

## Configuration

The default `.env.example` is enough for local self-hosting. Important optional
settings:

```bash
# Provider-backed extraction and embeddings
LITELLM_API_KEY=...
EXTRACTION_MODEL=openai/gpt-4.1-mini
EMBEDDING_MODEL=openai/text-embedding-3-large
EMBEDDING_DIMENSIONS=1024

# Port binding
HOST_API_BIND=127.0.0.1
HOST_API_PORT=8000
HOST_POSTGRES_BIND=127.0.0.1
HOST_REDIS_BIND=127.0.0.1
```

By default, compose-published ports bind to `127.0.0.1`. This is intentional:
Postgres, Redis, and the raw API should not be exposed directly to the public
internet.

For an internet-facing deployment, put a TLS-terminating reverse proxy in front
of the API. Ready-made examples live in [deploy/](./deploy/).

## Verification

Self-host smoke test:

```bash
bash scripts/smoke.sh
```

Backend tests:

```bash
python3 -m pytest tests/
```

Frontend tests:

```bash
cd frontend
npm test
```

Frontend production build:

```bash
cd frontend
npm run build
```

Full maintainer release gate:

```bash
ctxe verify
```

Backend-only release gate:

```bash
ctxe verify --skip-frontend
```

## Operations

State lives in Docker volumes:

- `postgres_data`: source documents, facts, relationships, reviews, evals
- `redis_data`: Celery queue and transient cache state

`docker compose down` preserves volumes. `docker compose down -v` deletes them.

Supported backup and restore scripts:

```bash
bash scripts/backup.sh
bash scripts/restore.sh backups/context_engine-YYYYMMDDTHHMMSSZ.dump --yes --safety-backup
```

Diagnostics:

```bash
bash scripts/diagnose.sh --tar
```

`diagnose.sh` is for troubleshooting only. It collects logs, health checks, and
redacted runtime state. It is not a backup.

For backup, restore, upgrade, rollback, queue backlog, worker health, and schema
drift procedures, see [docs/runbook.md](./docs/runbook.md).

## Resource Requirements

| Tier | vCPU | RAM | Disk | Suitable for |
| --- | ---: | ---: | ---: | --- |
| Minimum | 2 | 2 GB | 10 GB | local bootstrap and demo |
| Recommended | 2 | 4 GB | 20 GB | everyday self-hosted use |
| Comfortable | 4 | 8 GB | 40 GB | larger imports, more workers, provider-backed extraction |

Postgres with `pgvector` is the main memory consumer. Disk usage grows with
source documents, embeddings, and indexes.

## Repository Layout

```text
app/
  api/          FastAPI route groups
  connectors/   Connector implementations and metadata
  models/       SQLAlchemy models
  processing/   Extraction, embeddings, reranking
  services/     Core application logic
  tasks/        Celery tasks
alembic/        Database migrations
assets/         Architecture and project assets
deploy/         Reverse proxy examples
docs/           Self-hosting, runbooks, release notes
frontend/       React operator UI
scripts/        Bootstrap, smoke, backup, restore, diagnostics
tests/          Backend tests
```

## Current Status

Context Engine is in OSS v1 hardening.

Stable today:

- Docker-based self-hosting
- demo workspace bootstrap
- local document import
- source-backed query API
- founder workflow views
- operator health endpoint and UI
- smoke test and release verification path

Still hardening:

- production authentication and access control
- broader connector coverage
- long-running sync reliability at larger scale
- hosted deployment packaging

If you expose this outside a trusted local network, put it behind a reverse
proxy with authentication or an access-control layer such as Tailscale,
Cloudflare Access, or basic auth until first-class app auth is available.

## Documentation

- [Self-hosting guide](./docs/self-hosting.md)
- [Operations runbook](./docs/runbook.md)
- [Release notes and verification](./docs/release.md)
- [Reverse proxy examples](./deploy/)
