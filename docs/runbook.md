# Context Engine — Operations Runbook

Practical, copy-pasteable steps for the routine ops you need after a
self-hosted Context Engine is up and running. Each section is written
as a short playbook: when to run it, what to expect, and how to verify
you are back to normal.

For the initial install flow, see [self-hosting.md](self-hosting.md).
This runbook assumes the stack is already running via `docker compose`.

---

## Quick index

| Situation | Jump to |
|---|---|
| Nightly / weekly backup | [Backups](#backups) |
| Restoring from backup | [Restore](#restore) |
| Upgrading to a new release | [Upgrade](#upgrade) |
| Upgrade broke something | [Rollback](#rollback) |
| Disk filling up | [Disk pressure](#disk-pressure) |
| Celery queue growing | [Queue backlog](#queue-backlog) |
| Something broke, not sure what | [What broke? — triage](#what-broke--triage) |
| Reset the whole stack | [Nuclear reset](#nuclear-reset) |

---

## Backups

All stateful data lives in **one place**: the `postgres_data` Docker
volume. Redis holds only the Celery queue + transient caches — it is
not a backup target because losing it only delays pending async work.

### Manual `pg_dump`

```bash
cd /path/to/context-engine

docker compose exec -T postgres \
    pg_dump -U postgres -d context_engine \
    --no-owner --format=custom \
    > "context_engine-$(date -u +%Y%m%dT%H%M%SZ).dump"
```

- `--no-owner` keeps the dump portable across hosts with different
  role names.
- `--format=custom` is portable across Postgres minor versions and
  lets `pg_restore` run in parallel on restore.
- The `>` redirect on the host side captures `pg_dump`'s stdout.

A fresh self-hosted instance with the demo workspace produces a
~500 KB dump. Real workloads grow roughly linearly with source
document count.

### Automated nightly backup

Add to root's crontab (`sudo crontab -e`) on the VPS:

```
0 3 * * * cd /path/to/context-engine && \
  docker compose exec -T postgres \
    pg_dump -U postgres -d context_engine --no-owner --format=custom \
    > /backups/context_engine-$(date -u +\%Y\%m\%d).dump 2>>/backups/backup.log
```

Verify in the morning that the dump file actually exists and is
non-trivial in size:

```bash
ls -lh /backups/context_engine-*.dump | tail -5
```

### Rotation

Delete backups older than 14 days:

```bash
find /backups -name 'context_engine-*.dump' -mtime +14 -delete
```

### Off-host copies

The `pg_dump` on the VPS protects you from application bugs but not
from the VPS vanishing. Add a nightly rsync / rclone job to ship the
dump file to S3, B2, or another host:

```bash
# /etc/cron.daily/ctxe-backup-offsite
#!/bin/sh
set -e
latest=$(ls -t /backups/context_engine-*.dump | head -1)
[ -n "$latest" ] && rclone copy "$latest" remote:ctxe-backups/
```

### Sanity-check a backup without overwriting production

```bash
# Spin up a throwaway Postgres, restore into it, run a smoke query.
docker run --rm -d --name ctxe-verify \
    -e POSTGRES_PASSWORD=postgres \
    pgvector/pgvector:pg16
sleep 5
docker exec -i ctxe-verify createdb -U postgres context_engine_verify
docker exec -i ctxe-verify pg_restore -U postgres -d context_engine_verify --no-owner \
    < /backups/context_engine-YYYYMMDD.dump
docker exec -it ctxe-verify psql -U postgres -d context_engine_verify -c \
    "SELECT count(*) FROM components;"
docker rm -f ctxe-verify
```

---

## Restore

**Read this entire section before running any command.** A restore
overwrites data. If you are not sure whether to restore, take a fresh
backup of the current state first with `pg_dump` above, so you can
roll back the restore.

### Restore into the running container

```bash
cd /path/to/context-engine

# 1. Stop the API and worker so nothing writes during restore.
docker compose stop api worker

# 2. Restore. --clean --if-exists drops tables before restoring so you
#    get a clean state.
docker compose exec -T postgres \
    pg_restore -U postgres -d context_engine \
    --clean --if-exists --no-owner \
    < /backups/context_engine-YYYYMMDD.dump

# 3. Restart the stack.
docker compose start api worker

# 4. Verify.
bash scripts/smoke.sh
```

If the smoke fails after a restore, the dump was probably created
against a **different schema revision** than the currently-deployed
code. Check:

```bash
docker compose exec -T api alembic current
```

If that revision does not match the one the dump was created from,
either upgrade the code to match (preferred) or downgrade Alembic:

```bash
docker compose exec -T api alembic downgrade <revision>
```

### Restore into a fresh stack (e.g., rebuilding a VPS)

```bash
# 1. Bring up Postgres only.
docker compose up -d postgres

# 2. Wait for it to be healthy.
until docker compose exec -T postgres pg_isready -U postgres -d context_engine; do sleep 1; done

# 3. Restore.
docker compose exec -T postgres \
    pg_restore -U postgres -d context_engine \
    --clean --if-exists --no-owner \
    < /backups/context_engine-YYYYMMDD.dump

# 4. Bring up the rest of the stack.
docker compose up -d

# 5. Run smoke.
bash scripts/smoke.sh
```

---

## Upgrade

### Standard upgrade

```bash
cd /path/to/context-engine

# 1. Take a backup BEFORE upgrading. You will want this if step 5 fails.
docker compose exec -T postgres pg_dump -U postgres -d context_engine \
    --no-owner --format=custom \
    > "/backups/context_engine-pre-upgrade-$(date -u +%Y%m%dT%H%M%SZ).dump"

# 2. Pull the new code.
git pull origin main

# 3. Rebuild and restart. Named volumes persist across this command.
docker compose up -d --build

# 4. Apply any new migrations.
docker compose exec -T api alembic upgrade head

# 5. Verify — smoke.sh is the supported self-host verification path.
bash scripts/smoke.sh
```

If smoke passes, the upgrade is done. If it fails, jump to
[Rollback](#rollback).

### Zero-downtime caveat

Context Engine does not yet support zero-downtime upgrades. The API
is briefly unavailable during step 3 and again during step 4 if a
migration holds an exclusive lock. Plan upgrades for a quiet window
or schedule a maintenance banner at your reverse proxy.

---

## Rollback

Run this when an upgrade fails smoke. Decide first: is the failure in
**new code** (most common) or in **migrated data** (much rarer)?

### Code rollback

Read the smoke output. If every failing step is shaped like
`/api/X returned a 500` or `field missing from response`, the new code
is at fault. Roll back the code, keep the data:

```bash
# 1. Find the last known-good commit — the one you were on before `git pull`.
git log --oneline -10

# 2. Check out that commit. The working copy now matches the old release.
git checkout <good-commit>

# 3. Rebuild.
docker compose up -d --build

# 4. If the bad release ran `alembic upgrade head`, the DB schema is now
#    AHEAD of the checked-out code. Check:
docker compose exec -T api alembic current
# If the current revision is not in the checked-out alembic/versions
# directory, downgrade:
docker compose exec -T api alembic downgrade -1

# 5. Verify.
bash scripts/smoke.sh
```

### Data rollback (migration corrupted data)

**Only run this if a migration clearly mangled data** — for example,
a column got truncated or a table was dropped. Restoring from backup
loses any writes since the backup, so confirm first.

```bash
# 1. Stop writes.
docker compose stop api worker

# 2. Restore the pre-upgrade backup you made in step 1 of the Upgrade
#    playbook.
docker compose exec -T postgres \
    pg_restore -U postgres -d context_engine \
    --clean --if-exists --no-owner \
    < /backups/context_engine-pre-upgrade-YYYYMMDD.dump

# 3. Check out the code version that matches the backup's schema.
git checkout <pre-upgrade-commit>
docker compose up -d --build

# 4. Verify.
bash scripts/smoke.sh
```

---

## Disk pressure

Postgres is the top disk consumer. Growth is roughly proportional to
source-document count, plus pgvector indexes.

### Diagnose

```bash
# How much is docker actually using?
docker system df -v

# How big is the database?
docker compose exec -T postgres psql -U postgres -d context_engine -c \
    "SELECT pg_size_pretty(pg_database_size('context_engine'));"

# Which tables are fattest?
docker compose exec -T postgres psql -U postgres -d context_engine -c "
    SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) AS size
    FROM pg_stat_user_tables
    ORDER BY pg_total_relation_size(relid) DESC LIMIT 10;"
```

### Free space

```bash
# Unused images / stopped containers / dangling networks.
docker system prune -f

# Postgres full vacuum — reclaims disk from deleted rows.
# Safe but can take minutes and briefly holds exclusive locks.
docker compose exec -T postgres psql -U postgres -d context_engine -c \
    "VACUUM FULL;"

# Postgres analyze — updates query planner stats after big deletes.
docker compose exec -T postgres psql -U postgres -d context_engine -c \
    "ANALYZE;"
```

If disk is still full after the above, the data genuinely outgrew the
host. Either expand the volume (provider-specific) or archive old
source documents out of Postgres before deleting them.

---

## Queue backlog

The Celery worker processes ingestion and embedding jobs
asynchronously. A healthy stack has a near-zero default queue depth.
A growing queue means the worker is stuck, crashed, or overloaded.

### Diagnose

```bash
# How many jobs are waiting?
docker compose exec -T redis redis-cli LLEN celery

# Is the worker actually processing?
docker compose logs --tail 40 worker

# Is the worker container even running?
docker compose ps worker
```

### Common causes

| Symptom | Likely cause | Fix |
|---|---|---|
| `LLEN celery` > 50 and growing | Worker crashed / stopped | `docker compose restart worker` |
| Worker logs show repeated tracebacks | Bad payload — one document is poison-pilling the queue | Isolate the document (search logs for `external_id`), delete or fix it |
| Worker is up but queue still grows | Worker is CPU-bound, new jobs arrive faster than it drains | Bump `--concurrency` in `docker-compose.yml` or split the workload |
| `LLEN celery` is 0 but ingestion still slow | Not a queue issue — check the API side (`docker compose logs api`) |

### Reset a stuck queue (destructive)

This drops all pending Celery jobs. Only do this if the queue is
poisoned and you accept re-running the affected imports:

```bash
docker compose exec -T redis redis-cli DEL celery
docker compose restart worker
```

---

## What broke? — triage

Start here when something is clearly wrong but you don't know what.

### Step 1: take a snapshot

```bash
bash scripts/diagnose.sh --tar
```

This writes a timestamped tarball under `diagnostics/` containing
container status, logs, API health, DB table sizes, Redis state, and
a redacted `.env`. Everything you need to triage without running
follow-up commands.

### Step 2: read the snapshot in order

1. **`README.txt`** — orientation.
2. **`logs-api.txt`** — the cause is usually in the last 50 lines.
   Tracebacks have the filename and line number of the failure.
3. **`compose.txt`** — is the expected set of services running? If a
   service is in `Restarting (N)`, it is crash-looping. Jump to its
   log file.
4. **`postgres.txt`** — are the canonical row counts what you expect?
   Zero components in a workspace you thought was seeded is a seed
   regression; jump to the `[SEED]` playbook below.
5. **`redis.txt`** — is the queue backed up? If so, jump to
   [Queue backlog](#queue-backlog).
6. **`health.txt`** — did `/health/ready` report specific
   sub-components failing?

### Step 3: match symptoms to playbooks

| Symptom in snapshot | Playbook |
|---|---|
| `logs-api.txt` has `ConnectionRefused` to postgres | Postgres not healthy — check `logs-postgres.txt`, then **Disk pressure** or compose restart policy |
| `logs-api.txt` has `alembic` errors | Run `docker compose exec api alembic upgrade head`; if it fails, check migration / code version mismatch, see **Rollback** |
| `postgres.txt` shows zero rows in `components` | Seed regression — run `curl -X POST http://localhost:8000/api/seed-demo -H 'Content-Type: application/json' -d '{}'` and check response |
| `redis.txt` shows `LLEN celery` > 50 | **Queue backlog** |
| `stats.txt` shows a container at 100% CPU for minutes | Either legitimate workload or a runaway query — check `postgres.txt` longest-running queries |
| `host.txt` shows disk > 90% full | **Disk pressure** |
| All logs look fine but health is failing | Port conflict or proxy misconfig — check the reverse proxy logs, then `host.txt` for `docker info` network warnings |

### Step 4: re-run smoke after the fix

```bash
bash scripts/smoke.sh
```

Smoke automatically dumps a diagnostic snapshot to stderr on failure
(set `SMOKE_SKIP_DIAGNOSTICS=1` to silence). If smoke passes, the
incident is resolved.

---

## Nuclear reset

Destroys all data. Only for when the stack is so broken it is faster
to start fresh than debug — and after you've taken a final backup if
there's anything you want to keep:

```bash
# 1. Last-chance backup. Skip only if you are SURE you want data loss.
docker compose exec -T postgres pg_dump -U postgres -d context_engine \
    --no-owner --format=custom \
    > "/backups/context_engine-final-$(date -u +%Y%m%dT%H%M%SZ).dump" \
    || echo "(backup failed — proceeding with reset)"

# 2. Bring everything down and delete the volumes.
docker compose down -v

# 3. Bootstrap from scratch.
bash scripts/bootstrap.sh

# 4. Verify.
bash scripts/smoke.sh
```

---

## Appendix: useful one-liners

```bash
# Tail all logs at once.
docker compose logs -f

# Follow just the API.
docker compose logs -f api

# Show container memory/CPU right now.
docker stats --no-stream

# Open a psql shell inside the postgres container.
docker compose exec postgres psql -U postgres -d context_engine

# Show current Alembic revision.
docker compose exec -T api alembic current

# Force a fresh rebuild of just the api image after a code change.
docker compose up -d --build api

# Restart a single service (does NOT drop volumes).
docker compose restart api

# Count source documents in a workspace.
docker compose exec -T postgres psql -U postgres -d context_engine -c \
    "SELECT workspace_id, count(*) FROM source_documents GROUP BY workspace_id;"
```
