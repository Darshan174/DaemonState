# Context Engine

Context Engine is an open-source context layer for startups and AI systems.

It is a self-hostable knowledge platform for startups. It solves a specific problem: company knowledge is scattered across Slack messages, Notion docs, Zoom meeting transcripts, and GitHub issues. When someone asks "what's the current pricing?" or "who decided to delay the launch?", the answer might be buried in a Slack thread from two weeks ago — and it might contradict what's written in Notion.
Context Engine ingests all of that raw data, extracts structured facts from it using LLMs, tracks where each fact came from (provenance), flags conflicts, and serves source-backed answers through a query API and operator dashboard.

## Architecture:

![Context Engine Architecture](./assets/context-engine-architecture.svg)

## Who It Is For

- startups that want a source-backed internal context layer
- founders and operators who need trustworthy answers, not vague retrieval
- engineering and product teams that want decisions, blockers, and changes made explicit
- agent builders who want auditable context instead of generic RAG

### Sources

Current connector surface includes:

- Slack
- Notion
- Zoom transcripts
- GitHub issues and pull requests

### Core Data Model

The backend stores:

- `source_documents`: raw ingested evidence
- `components`: extracted facts
- `relationships`: links between facts
- `component_sources`: provenance from fact back to source
- `review_items`: conflicts, low-confidence facts, superseded facts
- `sync_jobs`: background sync and reprocess tracking

### Product Workflows

The app currently includes:

- **Founder Brief**: summarize what changed, what is risky, and what needs attention
- **Decision Register**: view current and historical decisions with rationale and blockers
- **What Changed**: timeline across decision changes, reviews, ingests, and failures
- **Launch Guard**: check outbound copy against current truth, review state, and evidence
- **Meetings**: inspect transcript-backed decisions and blockers
- **Engineering**: inspect GitHub-backed engineering context
- **Accuracy**: review eval results, domains, cases, and benchmark queries
- **Review Queue**: resolve conflicts and low-confidence facts
- **Connectors / Sources / Models / Query / Graph**: operate the underlying system

## Product Principles

Context Engine is intentionally opinionated:

- **source-backed over similarity-only**
- **reviewable over opaque**
- **current truth by default**
- **historical truth when requested**
- **structured facts over free-form memory**
- **self-hostable by default**

## Architecture

### Backend

- FastAPI
- SQLAlchemy async ORM
- PostgreSQL + `pgvector`
- Redis
- Celery
- Alembic migrations

### Frontend

- React
- Vite
- React Query
- React Router

### Retrieval / Accuracy

The current architecture supports:

- schema-constrained extraction with rule fallback
- structured fact storage in Postgres
- provenance-aware query responses
- temporal fact visibility
- hybrid lexical + semantic scoring groundwork
- eval summaries and case-level regressions

## Quick Start

The OSS v1 release candidate has two primary rails:

1. demo data for immediate time-to-value
2. real local text import for your own notes, docs, and exports

Prerequisites:

- Docker Engine with Compose v2
- `python3`
- `curl`
- `npm` only if you plan to run the full release gate with `ctxe verify`
- PostgreSQL client tools (`dropdb`, `createdb`, `psql`) only if you plan to run the contract-test phase in `ctxe verify`

Install the CLI once in a local virtualenv:

```bash
git clone <this-repo> context-engine
cd context-engine
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Leave `LITELLM_API_KEY`, `EXTRACTION_MODEL`, and `EMBEDDING_MODEL` blank for a fully offline OSS run using the local deterministic embedder and rule-based extraction fallback.

### Rail 1: Demo

Boot the stack, apply migrations, and seed the canonical demo workspace:

```bash
ctxe demo
ctxe query --workspace "Acme Accuracy Demo" "What is the Starter Plan?"
```

This rail uses the stable public contracts:

- `POST /api/seed-demo`
- `POST /api/query`

### Rail 2: Real Local Import

Boot the stack, import local files, then query the imported workspace:

```bash
ctxe up
ctxe ingest ./notes
ctxe query --workspace "Local Workspace" "What changed?"
```

Import semantics:

- `ctxe ingest <path>` uses `POST /api/imports`
- if no workspace exists, the CLI creates `Local Workspace`
- if exactly one workspace exists, the CLI uses it
- if multiple workspaces exist, pass `--workspace NAME_OR_UUID`

### Release Gate

Run the OSS v1 release gate:

```bash
ctxe verify
```

`ctxe verify` is the primary maintainer command before release. It boots the stack, runs the backend smoke flow, executes the contract tests against a dedicated disposable test database, and runs the frontend test/build checks. Use `ctxe verify --skip-frontend` for a backend-only pass.

`ctxe verify` uses the demo rail internally. It validates boot, readiness, and a canonical `POST /api/seed-demo` before handing off to the broader smoke and test matrix. The CLI also creates `.env` from `.env.example` and generates `ENCRYPTION_KEY` automatically when they are missing, so the CLI boot path and shell bootstrap path behave the same on a fresh checkout.

Maintainer flow:

1. bootstrap a local stack with `ctxe demo` or `bash scripts/bootstrap.sh`
2. confirm founder workflows with `bash scripts/smoke.sh`
3. run the full release gate with `ctxe verify --json`
4. release only when local `ctxe verify` and the PR `Release Gate` workflow are green

### Shell Wrappers (reference)

If you prefer shell-only flows, the lower-level wrappers are still available:

```bash
bash scripts/bootstrap.sh
bash scripts/smoke.sh
```

They exercise the same public HTTP contracts (`/api/seed-demo`, `/api/imports`, `/api/query`, `/api/founder-brief`, `/api/decisions`, `/api/source-documents`) but are wrapper/reference surfaces, not the primary OSS operator interface.

For the full self-hosting walkthrough (TLS, port security, backups, troubleshooting), see [docs/self-hosting.md](./docs/self-hosting.md). For exact release-candidate steps, expected green checks, and rollback notes, see [docs/release.md](./docs/release.md).

Once the API is up:

- API:          `http://localhost:8000`
- Health:       `http://localhost:8000/health`
- Readiness:    `http://localhost:8000/health/ready`
- OpenAPI docs: `http://localhost:8000/docs`

To run the operator/admin UI against this backend, see [Run the Frontend](#run-the-frontend) below.

## Developer CLI

`ctxe` is the canonical OSS operator entrypoint.

Core commands:

```bash
ctxe up
ctxe demo
ctxe ingest ./notes
ctxe query "What changed?"
ctxe verify
```

Contract and semantics:

- `ctxe up` builds the Docker services, applies migrations, and waits for `/health/ready`. It does not create or seed a workspace.
- `ctxe demo` uses `POST /api/seed-demo`, the same HTTP contract used by the frontend demo flow and the shell bootstrap/smoke scripts.
- `ctxe demo --workspace NAME_OR_UUID` seeds an existing workspace by passing `workspace_id` to `POST /api/seed-demo`.
- `ctxe ingest <path>` uses `POST /api/imports`. The API contract always requires `workspace_id`; the CLI resolves it from `--workspace`, a single existing workspace, or creates `Local Workspace` when none exists. It does not silently choose among multiple workspaces.
- `ctxe query "..."` uses `POST /api/query` and requires either `--workspace` or exactly one existing workspace.
- `ctxe verify` runs the release gate: boot, backend smoke, contract tests, and frontend test/build checks.
- `ctxe verify --phase ...` reruns only the selected slice of the release gate in canonical phase order.
- `ctxe verify --test-database-url ...` points the contract-tests phase at a disposable database; by default it uses `context_engine_verify` on local Postgres so the test reset does not collide with the live app database.
- Add `--json` to `ctxe demo`, `ctxe ingest`, `ctxe query`, or `ctxe verify` for machine-readable success and error payloads. `ctxe verify --json` includes the failing `phase`, actionable `next_step`, and `completed_steps` when the gate stops early.

Workspace selector rules are consistent across `ctxe demo`, `ctxe ingest`, and `ctxe query`:

- `--workspace UUID` targets that exact workspace or fails clearly if it does not exist
- `--workspace NAME` matches case-insensitively on exact name
- ambiguous names fail; they are never auto-resolved
- no selector means:
  `ctxe demo` seeds the canonical demo workspace
  `ctxe ingest` creates `Local Workspace` when none exists, uses the only workspace when exactly one exists, and fails when multiple exist
  `ctxe query` uses the only workspace when exactly one exists and fails otherwise
- frontend founder workflows use the selected workspace from the workspace switcher, auto-resolve only when exactly one workspace exists, and otherwise require an explicit selection

## Release Verification

`ctxe verify` is the primary "is this release candidate credible?" command:

```bash
ctxe verify
```

It proves:

| Step | What it checks |
| ---- | -------------- |
| BOOT | Docker services are up and migrations apply |
| READINESS | `GET /health` returns `ok` and `GET /health/ready` returns `ready` |
| SEED | `POST /api/seed-demo` returns the canonical demo workspace before smoke runs |
| SMOKE | `scripts/smoke.sh` verifies seed, query, graph, models, brief, decisions, sources, and imports against the live backend (10 checks) |
| CONTRACT TESTS | CLI + founder contract regression tests stay green |
| FRONTEND TESTS | `npm test` passes |
| FRONTEND BUILD | `npm run build` passes |

For a backend-only check, run `ctxe verify --skip-frontend`.

If a phase fails, `ctxe verify` reports the exact failing phase and the next command to run for diagnosis.

To rerun only part of the gate, pass `--phase` one or more times:

```bash
ctxe verify --phase boot --phase readiness --phase seed --phase smoke --skip-frontend
ctxe verify --phase contract-tests
ctxe verify --phase frontend-tests --phase frontend-build
```

The GitHub Actions workflow [`.github/workflows/release-gate.yml`](./.github/workflows/release-gate.yml) runs the same core checks as `ctxe verify` on pull requests.

`bash scripts/smoke.sh` remains the backend-only smoke path. It is useful for targeted debugging or post-deploy checks, but `ctxe verify` is the release gate maintainers should treat as canonical.

## Stability Notes

Stable now:

- `ctxe up`, `ctxe demo`, `ctxe ingest`, `ctxe query`, `ctxe verify`
- `GET /api/workspaces`, `POST /api/workspaces`, `GET /api/workspaces/{id}`
- `POST /api/seed-demo`
- `POST /api/imports`
- `GET /api/founder-brief`
- `POST /api/query`
- `GET /api/decisions`
- `GET /api/source-documents`

Compatibility-only:

- `GET /api/query` for older callers; founder workflows should use `POST /api/query`
- `POST /api/source-documents/upload`
- `POST /api/imports/trigger`

Not production-grade yet:

- internet-facing auth and access control
- enterprise auth/SSO
- broad connector breadth beyond the current OSS workflow set

## Founder Workflow Contract

These are the stable routes that founder-facing workflows should rely on:

| Workflow | Stable API contract | Frontend surface | CLI / smoke surface | Notes |
| ------- | ------------------- | ---------------- | ------------------- | ----- |
| Workspace bootstrap | `GET /api/workspaces`, `POST /api/workspaces` | `useWorkspaces`, `useCreateWorkspace` | `ctxe ingest`, `ctxe query` resolve workspaces before acting | Workspace selection is always explicit at the API layer. |
| Demo seed | `POST /api/seed-demo` | `useSeedDemoData` | `ctxe demo`, `scripts/bootstrap.sh`, `scripts/smoke.sh` | Omit `workspace_id` to seed the canonical `Acme Accuracy Demo`; include `workspace_id` to seed a specific existing workspace. |
| Local import | `POST /api/imports` | `useUploadSourceFile` | `ctxe ingest <path>` | This is the stable import path. The API contract requires `workspace_id` plus normalized `documents[]`. |
| Founder Brief | `GET /api/founder-brief` | `useFounderBrief` | direct API / browser | Reads structured facts + provenance for founder summary. |
| Query | `POST /api/query` | `useContextQuery` | `ctxe query "..."`, `scripts/smoke.sh` | Query answers are source-backed and workspace-scoped. |
| Decisions | `GET /api/decisions` | `useDecisionRegister` | direct API / browser | Decision history drilldown remains under `/api/decisions/{component_id}/history`. |
| Sources | `GET /api/source-documents` | `useSourceDocuments` | direct API / browser | Source visibility should reflect the same imported or seeded workspace. |

Compatibility-only routes may still exist for older admin flows, but founder workflows should not depend on `POST /api/source-documents/upload` or `/api/imports/trigger` as their primary contract.

## OSS v1 Release Checklist

Run this checklist for every release candidate:

1. Run the canonical release gate: `ctxe verify`
2. Confirm exactly one founder data rail for the release notes and docs:
   Demo rail: `ctxe demo`
   Real import rail: `ctxe ingest <path>`
3. Confirm workspace semantics are explicit and non-ambiguous:
   `ctxe demo --workspace NAME_OR_UUID` seeds the selected existing workspace.
   `ctxe ingest --workspace NAME_OR_UUID` imports into the selected workspace.
   `ctxe query --workspace NAME_OR_UUID "..."` queries that same workspace.
   `ctxe ingest` and `ctxe query` do not silently choose among multiple workspaces.
4. Spot-check the founder routes against the real backend:
   `GET /api/workspaces`
   `POST /api/seed-demo`
   `POST /api/imports`
   `GET /api/founder-brief?workspace_id=...`
   `POST /api/query`
   `GET /api/decisions?workspace_id=...`
   `GET /api/source-documents?workspace_id=...`
5. If you need to run the gate manually instead of `ctxe verify`, run:
   `bash scripts/smoke.sh`
   `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/context_engine_verify python3 -m pytest tests/test_cli/test_main.py tests/test_cli/test_http.py tests/test_api/test_imports.py tests/test_api/test_admin.py::TestSeedDemoAPI tests/test_api/test_connectors_upload.py tests/test_api/test_truth_regression.py tests/test_api/test_query.py tests/test_api/test_briefing.py -q`
   `cd frontend && npm test`
   `cd frontend && npm run build`

If Docker or Postgres access is sandbox-restricted, treat DB-backed backend suites and the live smoke script as environment-limited rather than product regressions, but keep the contract tests, frontend tests, and build green.

## Resource Requirements

Context Engine runs comfortably on a small VPS. The resource envelope below assumes the default offline OSS path (local embedder + rule extractor, no provider LLM calls):

| Tier        | vCPU | RAM   | Disk  | Suitable for                                                         |
| ----------- | ---- | ----- | ----- | -------------------------------------------------------------------- |
| Minimum     | 2    | 2 GB  | 10 GB | Bootstrap, smoke, small demo workspace                               |
| Recommended | 2    | 4 GB  | 20 GB | Everyday self-hosted use, a few thousand source documents            |
| Comfortable | 4    | 8 GB  | 40 GB | Many connectors + provider-backed extraction + denser embedding use  |

Notes:

- Postgres with `pgvector` is the main memory consumer — embeddings and ANN indexes benefit from page cache.
- Switching to provider-backed extraction/embeddings (`LITELLM_API_KEY` + `EXTRACTION_MODEL` + `EMBEDDING_MODEL`) does not meaningfully increase host RAM — the model runs remotely.
- The Celery worker is light by default (`--concurrency=2`). Scale it by raising the concurrency or running additional worker containers.
- Disk usage grows with `source_documents` + embeddings; budget ~1 GB per 50k average-sized documents, then add headroom for pgvector indexes.

## Persistent Storage and Backups

All stateful data lives in two named Docker volumes declared in `docker-compose.yml`:

- `postgres_data` — Postgres database (source documents, components, relationships, review items, evals, everything)
- `redis_data`    — Redis (Celery queue + transient caches)

`docker compose down` leaves these volumes intact; only `docker compose down -v` destroys them. Back them up before every upgrade.

Minimal backup recipe:

```bash
# SQL dump — portable across Postgres minor versions
docker compose exec -T postgres \
    pg_dump -U postgres -d context_engine --no-owner --format=custom \
    > "context_engine-$(date +%Y%m%d-%H%M%S).dump"

# Restore into a fresh stack
docker compose exec -T postgres \
    pg_restore -U postgres -d context_engine --clean --if-exists \
    < context_engine-YYYYMMDD-HHMMSS.dump
```

For volume-level backups on a cheap VPS, snapshot the entire docker volume directory (typically under `/var/lib/docker/volumes/`) while the stack is stopped, or rely on your provider's block-storage snapshots.

## Deploying on a Cheap VPS

Context Engine is designed to run on a single small VPS. A 2 vCPU / 4 GB RAM instance from any mainstream provider is enough for a real self-hosted deployment; the "minimum" tier above works for demos.

A reasonable shape for a cheap VPS deploy:

1. Provision a Linux host (Ubuntu 24.04 LTS or Debian 12 are the least-friction picks) with at least 4 GB RAM and 20 GB disk.
2. Install Docker Engine + Compose v2 (the official Docker convenience script or your distro's packages are both fine).
3. `git clone` this repo and run `bash scripts/bootstrap.sh`.
4. Put a TLS-terminating reverse proxy (Caddy, Traefik, or nginx) in front of `http://localhost:8000`. Block direct public access to the compose-published port if possible.
5. Set `HOST_POSTGRES_PORT` and `HOST_REDIS_PORT` in `.env` to `127.0.0.1:5432` / `127.0.0.1:6379` bindings — or remove the `ports:` entries entirely — so Postgres and Redis are never exposed to the public internet.
6. Enable automated snapshots on the host (provider-level) and a nightly `pg_dump` to object storage.
7. Run `bash scripts/smoke.sh` after every deploy.

> Auth note: Context Engine does not yet ship a production-grade auth layer. For a real internet-facing deploy, restrict access at the reverse proxy (basic auth, an allowlist, Tailscale, or a Cloudflare Access tunnel) until proper auth lands.

## Run the Frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server will proxy API requests to the backend at `http://localhost:8000`.

## Local Development Without Docker

If you already have PostgreSQL and Redis available locally:

```bash
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

In a second terminal, seed the demo workspace through the public HTTP contract:

```bash
curl -X POST http://localhost:8000/api/seed-demo \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Start the worker separately:

```bash
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2
```

Run the frontend:

```bash
cd frontend
npm install
npm run dev
```

## Accuracy / Eval Workflow

Run the eval regression harness against a workspace:

```bash
context-engine-eval-regression --workspace-id REPLACE_WITH_WORKSPACE_ID --json
```

The script wrapper also works:

```bash
python scripts/run_eval_regression.py --workspace-id REPLACE_WITH_WORKSPACE_ID --json
```

The current v1 accuracy gate is built around:

- `25` gold-set cases
- `5` domains: `pricing`, `blocker`, `roadmap`, `decision`, `meeting`
- `>= 0.80` pass rate
- `>= 0.80` retrieval quality
- `>= 0.80` extracted fact correctness
- `>= 0.75` final answer correctness
- `<= 0.25` confidence calibration error

## Optional Provider-Backed Models

If you want real extraction / embedding models instead of local fallbacks:

```bash
LITELLM_API_KEY=...
EXTRACTION_MODEL=openai/gpt-4.1-mini
EMBEDDING_MODEL=openai/text-embedding-3-large
EMBEDDING_DIMENSIONS=1024
```

## Connector Notes

### Zoom

For Zoom OAuth + webhooks:

```bash
ZOOM_CLIENT_ID=...
ZOOM_CLIENT_SECRET=...
ZOOM_REDIRECT_URI=https://your-api.example.com/api/connectors/zoom/callback
ZOOM_WEBHOOK_SECRET=...
```

The Zoom connector is transcript-first. Manual-token Zoom remains polling-based; OAuth-installed Zoom can support webhook-driven sync.

### GitHub

GitHub does not require app-level env vars for the first pass. Connect via the backend API with a manual token and repository list.

## Useful Commands

Backend founder-workflow smoke test (boot + health + seed + query + graph + models + brief + decisions + sources + imports):

```bash
bash scripts/smoke.sh
```

Backend tests:

```bash
python -m pytest tests/ -x --tb=short
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

## API Surface

Stable founder-workflow routes:

- `/api/workspaces`
- `/api/seed-demo`
- `/api/imports`
- `/api/founder-brief`
- `/api/query`
- `/api/decisions`
- `/api/source-documents`

Broader operator / system API groups:

- `/api/connectors`
- `/api/review-items`
- `/api/timeline`
- `/api/launch-guard`
- `/api/evals`

The router lives in [app/api/router.py](./app/api/router.py).

## Repository Layout

```text
app/
  api/           FastAPI route groups
  connectors/    Connector implementations and strategy metadata
  models/        SQLAlchemy models
  processing/    Extraction, embeddings, reranking
  services/      Core business logic
  tasks/         Celery tasks
alembic/         Database migrations
frontend/        Operator/admin UI
scripts/         Preflight, seeding, smoke, eval entrypoints
tests/           Backend tests
```

## Current Status

Context Engine is in late OSS v1 / hardening territory:

- core product workflows exist
- the operator UI is largely built
- accuracy, provenance, review, and timeline surfaces are present
- the remaining work is mostly runtime verification, hardening, and connector/workflow refinement

## Positioning

Context Engine is not trying to be generic enterprise search.

It is a self-hostable, source-backed context system for fast-moving teams that need:

- current truth
- historical truth
- explicit review state
- source paths for every answer
- startup-relevant workflows on top of raw company context
