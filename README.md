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

## Quick Start (5-minute self-hosted)

The fastest path. Requires Docker Engine with Compose v2 and `curl`.

```bash
git clone <this-repo> context-engine
cd context-engine
bash scripts/bootstrap.sh
bash scripts/smoke.sh
```

`scripts/bootstrap.sh` will:

1. Verify `docker`, `docker compose`, and `curl` are installed.
2. Create `.env` from `.env.example` if missing, and auto-generate an `ENCRYPTION_KEY`.
3. `docker compose up -d --build` for Postgres (pgvector), Redis, the API, and the Celery worker.
4. Wait for `/health/ready` to report both database and Redis as ok.
5. Run `alembic upgrade head` and seed the deterministic demo workspace.

`scripts/smoke.sh` then verifies boot, health, seed, and a source-backed query end-to-end — use it as the one-shot credibility check after every deploy.

Once the API is up:

- API:          `http://localhost:8000`
- Health:       `http://localhost:8000/health`
- Readiness:    `http://localhost:8000/health/ready`
- OpenAPI docs: `http://localhost:8000/docs`

To run the operator/admin UI against this backend, see [Run the Frontend](#run-the-frontend) below.

### Manual Quick Start (reference)

If you prefer to run the steps yourself or need to customize the flow:

```bash
cp .env.example .env
# Generate an encryption key and paste it into .env as ENCRYPTION_KEY=...
openssl rand -base64 32

docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose exec api python scripts/seed_demo.py --json
curl http://localhost:8000/health/ready
```

Leave `LITELLM_API_KEY`, `EXTRACTION_MODEL`, and `EMBEDDING_MODEL` blank for a fully offline OSS run using the local deterministic embedder and rule-based extraction fallback.

## Smoke Verification

`scripts/smoke.sh` is the one-command "is this deploy credible?" check:

```bash
bash scripts/smoke.sh
```

It proves:

| Step    | What it checks                                                      |
| ------- | ------------------------------------------------------------------- |
| BOOT    | `postgres`, `redis`, and `api` are running under docker compose     |
| HEALTH  | `/health` returns `ok` and `/health/ready` reports db + redis ok     |
| SEED    | The deterministic demo workspace exists (idempotently re-seedable)  |
| QUERY   | `POST /api/query` returns a source-backed answer with provenance    |

Exit code is `0` on full pass, non-zero with a descriptive failure otherwise — safe to wire into CI or a post-deploy hook. Override `BASE_URL`, `SMOKE_QUESTION`, or `SMOKE_EXPECT` via env if needed.

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
python scripts/seed_demo.py --json --replace-existing
uvicorn app.main:app --reload
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

Backend smoke test (boot + health + seed + query):

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

Main API groups:

- `/api/connectors`
- `/api/source-documents`
- `/api/review-items`
- `/api/decisions`
- `/api/founder-brief`
- `/api/timeline`
- `/api/launch-guard`
- `/api/query`
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
