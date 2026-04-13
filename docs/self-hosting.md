# Self-Hosting Context Engine

From a clean machine to a working demo in under 10 minutes.

This guide targets a solo founder or small team deploying on a cheap Linux VPS (DigitalOcean, Hetzner, Railway, Fly, etc.). The same steps work on any machine with Docker.

---

## Prerequisites

| Requirement | Minimum | Notes |
|---|---|---|
| OS | Ubuntu 22.04+ / Debian 12+ | Any Linux with Docker works |
| Docker Engine | 24.0+ | With Compose v2 (`docker compose`) |
| curl | any | Used by bootstrap and smoke scripts |
| RAM | 2 GB | 4 GB recommended for everyday use |
| Disk | 10 GB | 20 GB recommended |
| vCPU | 2 | Sufficient for demo + small workloads |

No external API keys are required. The default path runs fully offline using a deterministic local embedder and rule-based extractor.

Looking for ops playbooks (backup, upgrade, rollback, triage)? See [runbook.md](runbook.md). Looking for ready-made reverse-proxy configs? See [`deploy/`](../deploy/).

---

## Step 1: Install Docker

If Docker is not already installed:

```bash
# Ubuntu / Debian — official convenience script
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group membership to take effect.
```

Verify:

```bash
docker compose version
# Should print "Docker Compose version v2.x.x"
```

---

## Step 2: Clone and Bootstrap

```bash
git clone <repo-url> context-engine
cd context-engine
bash scripts/bootstrap.sh
```

`bootstrap.sh` is idempotent and safe to re-run. It will:

1. Check that `docker`, `docker compose`, and `curl` are installed.
2. Create `.env` from `.env.example` if missing, and auto-generate an `ENCRYPTION_KEY`.
3. Build and start four containers: Postgres (pgvector), Redis, the API, and a Celery worker.
4. Wait for the API to report healthy at `/health/ready`.
5. Run Alembic migrations and seed the deterministic demo workspace via `POST /api/seed-demo`.

When it finishes you will see:

```
==> Bootstrap complete.
    API:           http://localhost:8000
    Health:        http://localhost:8000/health
    OpenAPI docs:  http://localhost:8000/docs
    Workspace id:  <uuid>
```

---

## Step 3: Verify

Run the backend smoke suite — this is the verification path designed for self-hosted deployments and needs nothing beyond what Step 1 already installed (Docker + `curl`). No Python virtualenv, no Node.js, no extra build tooling:

```bash
bash scripts/smoke.sh
```

The smoke script exercises 10 checks against the running stack:

| Step | What it proves |
|---|---|
| BOOT | postgres, redis, api, **and Celery worker** containers are running |
| HEALTH | `/health` ok, `/health/ready` reports db + redis ok |
| SEED | `POST /api/seed-demo` is idempotent (same workspace on repeat) |
| QUERY | `POST /api/query` returns a source-backed answer with provenance |
| GRAPH | `GET /api/graph` returns 15+ nodes, all with provenance |
| MODELS | `GET /api/models` returns 4+ models; model graph has nodes |
| BRIEF | `GET /api/founder-brief` returns structured content |
| DECISIONS | `GET /api/decisions` returns entries with names + values |
| SOURCES | `GET /api/source-documents` returns processed docs with content |
| IMPORTS | `POST /api/imports` round-trips a real document through the zero-auth ingest rail (same contract `ctxe ingest` uses), then reads it back via `GET /api/source-documents` to confirm persistence |

Exit code `0` means the full stack is working. Wire it into CI or run it after every deploy. Every failure message includes a diagnostic hint, and **on any failure the script automatically dumps a diagnostic snapshot** (container status + tail of api/worker/postgres/redis logs) so the root cause is visible without running follow-up commands. Set `SMOKE_SKIP_DIAGNOSTICS=1` to silence the snapshot if you're driving smoke from a tool that prefers a quieter output. Set `SMOKE_SKIP_WORKER=1` if you have intentionally removed the Celery worker from your compose stack.

### Optional: full maintainer release gate (`ctxe verify`)

The `ctxe` CLI wraps the smoke script in a broader release gate that also runs the Python contract test suite and (by default) builds the frontend. It is the command maintainers run before cutting a release. **It is not installed by `bootstrap.sh`** — it requires extra tooling that most self-hosters do not need:

```bash
# One-time install in a local Python virtualenv:
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Backend-only release gate — no Node.js required:
ctxe verify --skip-frontend

# Full release gate — requires Node.js AND `cd frontend && npm install`:
ctxe verify
```

Skip this unless you are validating a full-stack contract change or cutting a release. `bash scripts/smoke.sh` is the supported day-to-day verification path for self-hosted deployments.

### When smoke fails

Run `bash scripts/diagnose.sh --tar` to collect a runtime snapshot (container status, logs, DB stats, Redis state, API health, redacted `.env`) into a timestamped tarball under `diagnostics/`. Then consult [runbook.md](runbook.md) — specifically the [*What broke? — triage*](runbook.md#what-broke--triage) section — which maps symptoms in the snapshot to concrete fixes.

---

## Step 4: Run the Frontend (optional)

On your local machine (not the VPS), or on the VPS if you have Node.js:

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies API requests to `http://localhost:8000`. If the API is on a remote VPS, set `VITE_API_URL` in `frontend/.env` or update `vite.config.js`.

---

## Securing the Deployment

### Safer-by-default port binding

As of the latest compose file, **all published host ports bind to `127.0.0.1` by default**:

```yaml
# docker-compose.yml excerpt
ports:
  - "${HOST_POSTGRES_BIND:-127.0.0.1}:${HOST_POSTGRES_PORT:-5432}:5432"
  - "${HOST_REDIS_BIND:-127.0.0.1}:${HOST_REDIS_PORT:-6379}:6379"
  - "${HOST_API_BIND:-127.0.0.1}:${HOST_API_PORT:-8000}:8000"
```

This means Postgres, Redis, and the API are only reachable from the host itself. A reverse proxy running on the same host can still talk to them via loopback, but traffic from the internet cannot. **This is the correct default.**

If you need to reach the API from another device on your LAN (e.g., a local dev machine with no reverse proxy), override explicitly in `.env`:

```bash
HOST_API_BIND=0.0.0.0
```

Do **not** override `HOST_POSTGRES_BIND` or `HOST_REDIS_BIND` unless you understand the risk — a publicly-reachable Redis is equivalent to handing out your Celery queue.

### TLS with a Reverse Proxy

Never expose the raw API port to the public internet. Put a TLS-terminating reverse proxy in front of it. Ready-made configs live in [`deploy/`](../deploy/):

- [`deploy/caddy/Caddyfile`](../deploy/caddy/Caddyfile) — fastest path, auto-TLS via Let's Encrypt, zero cert management.
- [`deploy/nginx/context-engine.conf`](../deploy/nginx/context-engine.conf) — for hosts that already run nginx; cert via certbot.
- [`deploy/README.md`](../deploy/README.md) — which one to use when, plus the pre-expose checklist.

**Quickest path (Caddy):**

```bash
sudo apt install caddy
sudo cp deploy/caddy/Caddyfile /etc/caddy/Caddyfile
# Edit /etc/caddy/Caddyfile — replace context-engine.example.com with your domain.
sudo systemctl reload caddy

# Verify
curl -sS https://your-domain.example.com/health
```

The shipped configs include commented-out snippets for basic auth and IP allow-listing — the two quickest ways to lock down a demo while you figure out a real identity story.

### Lock Down Ports

With the default 127.0.0.1 bindings above, the only port that needs to be reachable from the internet is the reverse proxy (80/443). If your VPS has a firewall (e.g., `ufw`):

```bash
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP (redirect to HTTPS)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

Verify from a different host that Postgres, Redis, and the raw API are not reachable:

```bash
# From a machine that is NOT the VPS:
curl -sS --max-time 5 http://your-vps-ip:8000/health && echo "LEAKED" || echo "blocked (good)"
curl -sS --max-time 5 http://your-vps-ip:5432/         && echo "LEAKED" || echo "blocked (good)"
curl -sS --max-time 5 http://your-vps-ip:6379/         && echo "LEAKED" || echo "blocked (good)"
```

All three should report `blocked (good)`.

### Authentication

Context Engine does not yet ship a production auth layer. For an internet-facing deploy, restrict access at the reverse proxy:

- **Caddy**: `basicauth` directive
- **nginx**: `auth_basic` directive
- **Tailscale / Cloudflare Access / WireGuard**: zero-trust tunnel

---

## Persistent Storage and Backups

All stateful data lives in two named Docker volumes:

- `postgres_data` — the PostgreSQL database (source documents, facts, relationships, evals)
- `redis_data` — Redis (Celery queue + transient caches)

`docker compose down` preserves these volumes. Only `docker compose down -v` destroys them.

> **`scripts/diagnose.sh` is NOT a backup.** It produces a read-only
> runtime snapshot (logs, health, redacted config) for triage — it
> contains zero application data and cannot be restored from. Use
> `scripts/backup.sh` for anything you need to restore later.

**Quick backup (the supported path):**

```bash
bash scripts/backup.sh
```

Writes a validated, timestamped `pg_dump` custom-format file to
`./backups/`, rotates old dumps (default: keep 14), and refuses to
return success unless the archive is readable. The exact dump path is
printed at the end; pass `--quiet` in cron to get just the path on
stdout.

**Quick restore (the supported path):**

```bash
bash scripts/restore.sh backups/context_engine-YYYYMMDDTHHMMSSZ.dump --yes --safety-backup
```

`restore.sh` stops the API and worker, validates the dump's TOC,
snapshots the current DB (via `--safety-backup`), runs `pg_restore`,
restarts the stack, waits for `/health/ready`, and runs a live sanity
probe against `/api/workspaces` and `/api/models` to prove the
restored data is actually queryable — not just structurally valid.

For automated nightly backups via cron, rotation, off-host copies,
sanity-checking a backup without overwriting production, the
fresh-stack restore path, and the raw `pg_dump`/`pg_restore` fallback
for when the scripts are unavailable, see [runbook.md → Backups](runbook.md#backups)
and [runbook.md → Restore](runbook.md#restore).

---

## Upgrading

The recommended path for upgrading is using the `upgrade.sh` script, which automates the pre-upgrade backup, git update, image rebuild, and schema migration.

```bash
cd context-engine
bash scripts/upgrade.sh --yes
```

The script will:
1.  **Preflight** — refuses to run on a dirty working tree or without a live postgres container.
2.  **Safety backup** — runs `scripts/backup.sh` to `./backups/pre-upgrade/`.
3.  **`git pull --ff-only`** — refuses non-fast-forward pulls (diverged branches need manual intervention).
4.  **Rebuild** — `docker compose up -d --build` to refresh images, then waits for `/health/ready`.
5.  **Migrate** — `alembic upgrade head`, confirms `current` matches `heads`.
6.  **Smoke** — runs `scripts/smoke.sh` to verify the new stack.

If any stage fails, the script prints **the EXACT copy-paste rollback commands** — with the real backup path and pre-upgrade git SHA baked in, including a `bash scripts/restore.sh <path> --yes` line when a backup was taken — so recovery is mechanical, not creative.

For manual upgrade steps or deeper rollback strategy, see [runbook.md → Upgrade](runbook.md#upgrade).

---

## Optional: Provider-Backed Models

By default, Context Engine runs fully offline with a local embedder and rule-based extractor. To use real LLMs for extraction and embedding:

```bash
# In .env:
LITELLM_API_KEY=sk-...
EXTRACTION_MODEL=openai/gpt-4.1-mini
EMBEDDING_MODEL=openai/text-embedding-3-large
EMBEDDING_DIMENSIONS=1024
```

Then rebuild: `docker compose up -d --build`

This does not meaningfully increase host RAM — the models run remotely.

---

## Resource Guide

| Tier | vCPU | RAM | Disk | Good for |
|---|---|---|---|---|
| Minimum | 2 | 2 GB | 10 GB | Demo, bootstrap, smoke |
| Recommended | 2 | 4 GB | 20 GB | Everyday self-hosted use, a few thousand docs |
| Comfortable | 4 | 8 GB | 40 GB | Many connectors + provider-backed extraction |

Memory breakdown in `docker-compose.yml`:

| Service | Limit | Notes |
|---|---|---|
| postgres | 1536 MB | Main consumer — pgvector indexes benefit from page cache |
| redis | 256 MB | Capped at 128 MB data via `--maxmemory` |
| api | 512 MB | FastAPI + uvicorn |
| worker | 512 MB | Celery with `--concurrency=2` |

Disk grows with source documents + embeddings. Budget ~1 GB per 50k average-sized documents plus headroom for pgvector indexes.

---

## Troubleshooting

**Start here:** `bash scripts/diagnose.sh --tar` writes a timestamped snapshot to `diagnostics/` containing container status, logs (api/worker/postgres/redis, 200 lines each), API health, DB row counts and table sizes, Redis info, Celery queue depth, and a redacted `.env`. The tarball is safe to attach to a bug report (secrets are masked). For a symptom-driven triage walkthrough using the snapshot contents, see [runbook.md → *What broke? — triage*](runbook.md#what-broke--triage).

### API won't start

```bash
docker compose logs -f api
```

Common causes:
- **`python-multipart` missing**: Should be fixed in current builds. If you see this error, rebuild: `docker compose up -d --build api`
- **Database not ready**: The API waits for Postgres via `depends_on: service_healthy`. If Postgres is slow to start, increase `HEALTH_TIMEOUT_S` in bootstrap.
- **Port conflict**: Another process is using 8000/5432/6379. Override in `.env`: `HOST_API_PORT=9000`
- **`HOST_API_BIND=127.0.0.1` means curl from another host fails**: By design — the API is bound to loopback only and expected to live behind a reverse proxy. From the host itself, `curl http://localhost:8000/health` works. To expose directly on a LAN, set `HOST_API_BIND=0.0.0.0` in `.env` and restart.

### Migrations fail

```bash
docker compose exec -T api alembic upgrade head
```

If you see "target database is not up to date":

```bash
docker compose exec -T api alembic stamp head
docker compose exec -T api alembic upgrade head
```

### Smoke fails at SEED

```bash
curl -v http://localhost:8000/api/seed-demo -X POST -H 'Content-Type: application/json' -d '{}'
```

Check the response body. Common issues:
- 404: API container has stale code — rebuild with `docker compose up -d --build api`
- 500: Check `docker compose logs api` for the traceback

### Smoke fails at other steps

Every smoke failure emits a `DIAGNOSTIC SNAPSHOT` block to stderr containing `docker compose ps` output and the last 40 lines of api / worker / postgres / redis logs — read that first. Each failure message also carries an inline hint. For a deeper post-failure snapshot (DB row counts, Redis queue depth, alembic current, redacted config), run `bash scripts/diagnose.sh --tar` and cross-reference with the [runbook triage guide](runbook.md#what-broke--triage).

| Smoke step | First thing to check |
|---|---|
| BOOT | `docker compose ps` — is each of postgres/redis/api/worker running? The Celery worker is required; set `SMOKE_SKIP_WORKER=1` only if you have intentionally removed it. BOOT also checks Celery queue depth via `redis-cli LLEN celery`; a growing queue usually means the worker is stuck — see [runbook.md → Queue backlog](runbook.md#queue-backlog). |
| HEALTH | `docker compose logs postgres` and `docker compose logs redis` |
| SEED | Rebuild API: `docker compose up -d --build api`. If seed returns 200 but smoke still fails, the post-seed graph self-check in `bootstrap.sh` catches empty-graph regressions earlier |
| QUERY | `docker compose logs api` — look for extraction/embedding errors |
| GRAPH | Same as QUERY — graph uses the same seeded data |
| MODELS | Check that seed completed — re-run `POST /api/seed-demo` |
| BRIEF | `docker compose logs api` — briefing aggregates across models |
| DECISIONS | Check the `Decisions` model exists in the seeded workspace |
| SOURCES | Check `SourceDocument` rows: `docker compose exec postgres psql -U postgres -d context_engine -c "SELECT count(*) FROM source_documents"` |
| IMPORTS | Failure means the zero-auth import rail (`POST /api/imports`) is broken. The step POSTs a document and then GETs it back via `/api/source-documents?connector_type=local` — check `docker compose logs api` for the traceback and confirm the router registers imports: `grep imports app/api/router.py` |

### Postgres disk full

```bash
docker system df -v
docker volume ls
```

Prune unused images/containers: `docker system prune -f`. For Postgres specifically, vacuum: `docker compose exec postgres psql -U postgres -d context_engine -c "VACUUM FULL"`. For the fuller disk-pressure playbook (table size breakdown, analyze after big deletes, when to expand the volume), see [runbook.md → Disk pressure](runbook.md#disk-pressure).

### Reset everything

This destroys all data. **Take a backup first** if there's anything you want to keep:

```bash
bash scripts/backup.sh           # validated dump under ./backups/
docker compose down -v           # Destroys all data!
bash scripts/bootstrap.sh
bash scripts/smoke.sh
```

If you regret the reset, restore the dump with `bash scripts/restore.sh <path> --yes`. See [runbook.md → Backups](runbook.md#backups) for rotation, off-host copies, and the full restore playbook.

---

## Architecture Reference

```
                    ┌────────────────────┐
                    │   Reverse Proxy    │
                    │  (Caddy / nginx)   │
                    └────────┬───────────┘
                             │ :443 → :8000
                    ┌────────▼───────────┐
                    │    API (FastAPI)    │
                    │   uvicorn :8000    │
                    └──┬───────────┬─────┘
                       │           │
              ┌────────▼──┐  ┌─────▼─────┐
              │ PostgreSQL │  │   Redis   │
              │  pgvector  │  │  7-alpine │
              │   :5432    │  │   :6379   │
              └────────────┘  └─────┬─────┘
                                    │
                              ┌─────▼��────┐
                              │  Worker   │
                              │  (Celery) │
                              └────��──────┘
```

All four services run in Docker containers on the same host. Postgres and Redis should never be exposed to the public internet — only the API (behind a reverse proxy) should be reachable.
