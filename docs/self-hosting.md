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

## Step 3: Verify with Smoke

```bash
bash scripts/smoke.sh
```

The smoke script exercises 9 checks against the running stack:

| Step | What it proves |
|---|---|
| BOOT | postgres, redis, api containers are running |
| HEALTH | `/health` ok, `/health/ready` reports db + redis ok |
| SEED | `POST /api/seed-demo` is idempotent (same workspace on repeat) |
| QUERY | `POST /api/query` returns a source-backed answer with provenance |
| GRAPH | `GET /api/graph` returns the workspace knowledge graph with nodes |
| MODELS | `GET /api/models` lists knowledge models; model graph works |
| BRIEF | `GET /api/founder-brief` returns a structured brief |
| DECISIONS | `GET /api/decisions` returns the decision register |
| SOURCES | `GET /api/source-documents` returns source documents |

Exit code `0` means the full stack is working. Wire it into CI or run it after every deploy.

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

### TLS with a Reverse Proxy

Never expose the raw API port to the public internet. Put a TLS-terminating reverse proxy in front of it.

**Caddy** (easiest — auto-TLS with Let's Encrypt):

```
# /etc/caddy/Caddyfile
your-domain.example.com {
    reverse_proxy localhost:8000
}
```

```bash
sudo apt install caddy
sudo systemctl enable caddy
sudo systemctl start caddy
```

**nginx** (manual cert management):

```nginx
server {
    listen 443 ssl;
    server_name your-domain.example.com;
    ssl_certificate     /etc/letsencrypt/live/your-domain.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Lock Down Ports

Postgres and Redis must never be reachable from the public internet.

In `.env`:

```bash
HOST_POSTGRES_PORT=127.0.0.1:5432
HOST_REDIS_PORT=127.0.0.1:6379
```

Or remove their `ports:` entries entirely from `docker-compose.yml` — the containers communicate over the Docker network without published ports.

If your VPS has a firewall (e.g., `ufw`):

```bash
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP (redirect to HTTPS)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

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

### SQL Backup

```bash
# Dump — portable across Postgres minor versions
docker compose exec -T postgres \
    pg_dump -U postgres -d context_engine --no-owner --format=custom \
    > "context_engine-$(date +%Y%m%d-%H%M%S).dump"
```

### Restore

```bash
docker compose exec -T postgres \
    pg_restore -U postgres -d context_engine --clean --if-exists \
    < context_engine-YYYYMMDD-HHMMSS.dump
```

### Automated Nightly Backup

Add to crontab (`crontab -e`):

```
0 3 * * * cd /path/to/context-engine && docker compose exec -T postgres pg_dump -U postgres -d context_engine --no-owner --format=custom > /backups/context_engine-$(date +\%Y\%m\%d).dump 2>&1
```

Rotate old backups with `find /backups -name '*.dump' -mtime +14 -delete`.

For volume-level backups, snapshot the Docker volume directory (typically `/var/lib/docker/volumes/`) while the stack is stopped, or use your provider's block-storage snapshots.

---

## Upgrading

```bash
cd context-engine
git pull origin main

# Rebuild and restart — named volumes persist.
docker compose up -d --build

# Apply any new migrations.
docker compose exec -T api alembic upgrade head

# Re-run smoke to confirm.
bash scripts/smoke.sh
```

If the smoke fails after an upgrade, check `docker compose logs -f api` for startup errors. Most migration issues are resolved by running `alembic upgrade head` explicitly.

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

### API won't start

```bash
docker compose logs -f api
```

Common causes:
- **`python-multipart` missing**: Should be fixed in current builds. If you see this error, rebuild: `docker compose up -d --build api`
- **Database not ready**: The API waits for Postgres via `depends_on: service_healthy`. If Postgres is slow to start, increase `HEALTH_TIMEOUT_S` in bootstrap.
- **Port conflict**: Another process is using 8000/5432/6379. Override in `.env`: `HOST_API_PORT=9000`

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

### Postgres disk full

```bash
docker system df -v
docker volume ls
```

Prune unused images/containers: `docker system prune -f`. For Postgres specifically, vacuum: `docker compose exec postgres psql -U postgres -d context_engine -c "VACUUM FULL"`.

### Reset everything

```bash
docker compose down -v   # Destroys all data!
bash scripts/bootstrap.sh
bash scripts/smoke.sh
```

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
