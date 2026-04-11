# Context Engine

Context Engine is an open-source context layer for startups and AI systems.

It is a self-hostable knowledge platform for startups. It solves a specific problem: company knowledge is scattered across Slack messages, Notion docs, Zoom meeting transcripts, and GitHub issues. When someone asks "what's the current pricing?" or "who decided to delay the launch?", the answer might be buried in a Slack thread from two weeks ago — and it might contradict what's written in Notion.
Context Engine ingests all of that raw data, extracts structured facts from it using LLMs, tracks where each fact came from (provenance), flags conflicts, and serves source-backed answers through a query API and operator dashboard.

Context Engine is built to solve that problem with:

- raw source retention
- structured fact storage
- provenance for every fact
- review and conflict handling
- current-vs-historical truth
- measurable accuracy

## Architecture:






## Who It Is For

- startups that want a source-backed internal context layer
- founders and operators who need trustworthy answers, not vague retrieval
- engineering and product teams that want decisions, blockers, and changes made explicit
- agent builders who want auditable context instead of generic RAG

## What The Product Does

Context Engine takes data from connected systems and turns it into an operator-friendly context graph.

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

### 1. Configure the environment

Copy the example env file:

```bash
cp .env.example .env
```

Generate an encryption key:

```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

Put that value into `.env` as `ENCRYPTION_KEY=...`.

For an offline/local OSS run, leave these blank:

- `LITELLM_API_KEY`
- `EXTRACTION_MODEL`
- `EMBEDDING_MODEL`

### 2. Start the backend stack

```bash
docker compose up -d postgres redis api worker
```

Apply migrations:

```bash
docker compose exec api alembic upgrade head
```

Seed the demo workspace:

```bash
docker compose exec api python scripts/seed_demo.py --json --replace-existing
```

Check health:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/ready
```

### 3. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite app will proxy API requests to the backend.

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

Backend smoke test:

```bash
python scripts/smoke_phase1.py
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
