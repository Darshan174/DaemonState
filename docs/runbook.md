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
| Celery queue growing | [Queue backlog](#queue-backlog) |
| Worker up but not processing | [Worker health](#worker-health) |
| Schema doesn't match code | [Schema drift](#schema-drift) |
| Seed / import left DB in bad state | [Bad seed / import state](#bad-seed--import-state) |
| Container keeps restarting | [Container and compose failures](#container-and-compose-failures) |
| Disk filling up | [Disk pressure](#disk-pressure) |
| Something broke, not sure what | [What broke? — triage](#what-broke--triage) |
| Reset the whole stack | [Nuclear reset](#nuclear-reset) |

> **Backups vs. diagnostics — do not confuse them.** `scripts/backup.sh`
> is the only supported backup tool: it writes a validated `pg_dump`
> you can restore from. `scripts/diagnose.sh` is a **read-only
> snapshot** for post-failure triage — it contains logs, health, and
> redacted config, but **no application data** and cannot be restored
> from. If all you have after a disaster is a diagnose tarball, you
> have no backup.

---

## Backups

All stateful data lives in **one place**: the `postgres_data` Docker
volume. Redis holds only the Celery queue + transient caches — it is
not a backup target because losing it only delays pending async work.

### The supported path: `scripts/backup.sh`

```bash
cd /path/to/context-engine
bash scripts/backup.sh
```

`backup.sh` is the one-command supported backup path. It:

1. Confirms the `postgres` container is running.
2. Runs `pg_dump --no-owner --format=custom` into a timestamped
   `context_engine-YYYYMMDDTHHMMSSZ.dump` file under `./backups/`
   (override with `--output /path`).
3. Writes to a `.partial` file first and atomically renames on
   success, so a crashed dump never leaves a half-written file with
   the final name.
4. **Validates the dump** via `pg_restore --list` before keeping it —
   a corrupt archive fails loudly here rather than 6 months later
   during a disaster.
5. Rotates older dumps so only the N most recent are kept
   (`--retention 14` by default).

A fresh self-hosted instance with the demo workspace produces a
~500 KB dump. Real workloads grow roughly linearly with source
document count.

Useful flags:

```bash
bash scripts/backup.sh --output /srv/ctxe-backups  # write elsewhere
bash scripts/backup.sh --retention 30              # keep 30 dumps
bash scripts/backup.sh --quiet                     # only print the final path
```

### Automated nightly backup

`backup.sh --quiet` is designed for cron. Add to root's crontab
(`sudo crontab -e`) on the VPS:

```
0 3 * * * cd /srv/context-engine && \
  bash scripts/backup.sh --output /backups --retention 30 --quiet \
  >> /var/log/ctxe-backup.log 2>&1
```

Verify in the morning that the dump file actually exists and is
non-trivial in size:

```bash
ls -lh /backups/context_engine-*.dump | tail -5
tail -20 /var/log/ctxe-backup.log
```

The script exits non-zero on any failure (postgres down, pg_dump
error, validation failure, disk < 100 MB free), so cron will surface
failures in the system mail spool or wherever your log shipper looks.

### Off-host copies

`backup.sh` on the VPS protects you from application bugs but not
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

Never assume a backup is restorable without proving it. `backup.sh`
already validates the archive's TOC, but the safest proof is an
actual restore into a throwaway database:

```bash
# Spin up a throwaway Postgres, restore into it, check canonical counts.
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

### Fallback: raw `pg_dump`

Only when `scripts/backup.sh` is unavailable (partial checkout, or you
need to dump from a host where the script isn't shipped):

```bash
docker compose exec -T postgres \
    pg_dump -U postgres -d context_engine \
    --no-owner --format=custom \
    > "context_engine-$(date -u +%Y%m%dT%H%M%SZ).dump"
```

This produces the same artifact shape `backup.sh` writes, but **does
not validate the dump, does not rotate, and does not do a disk-space
sanity check**. Prefer the script.

---

## Restore

**Read this entire section before running any command.** A restore
overwrites data. The supported path (`scripts/restore.sh`) takes a
safety snapshot of the CURRENT database before touching anything, so
a restore of the wrong dump is itself reversible — use it.

### The supported path: `scripts/restore.sh`

```bash
cd /path/to/context-engine
bash scripts/restore.sh backups/context_engine-YYYYMMDDTHHMMSSZ.dump --yes --safety-backup
```

`restore.sh` is the one-command supported restore path. It:

1. Refuses to run without `--yes` (or `CTXE_RESTORE_YES=1`) — you
   cannot trigger a destructive restore by accident.
2. Validates the dump's TOC with `pg_restore --list` before dropping
   anything — a corrupt archive fails loudly before any damage.
3. With `--safety-backup`, snapshots the current DB into
   `backups/pre-restore/` so you can roll back the restore itself.
4. Stops the API and worker so nothing writes mid-restore.
5. Runs `pg_restore --clean --if-exists --no-owner --exit-on-error`.
6. Starts the API and worker, waits for `/health/ready`.
7. Runs a **post-restore sanity check** against `/api/workspaces` and
   `/api/models` — proves the restored data is actually queryable,
   not just structurally valid.
8. Compares `alembic current` vs `alembic heads` and warns loudly if
   the backup was taken against an older schema (see
   [Schema drift](#schema-drift)).

After it finishes, run `bash scripts/smoke.sh` for the full
verification of the restored stack.

### Restore into a fresh stack (rebuilding a VPS)

```bash
# 1. Bring up Postgres only so restore.sh has a target.
docker compose up -d postgres

# 2. Wait for it to be healthy.
until docker compose exec -T postgres pg_isready -U postgres -d context_engine; do sleep 1; done

# 3. Bring up the rest of the stack so restore.sh can stop/start api+worker
#    and run its post-restore API probes.
docker compose up -d

# 4. Restore. --safety-backup is pointless here (the DB is empty) so skip it.
bash scripts/restore.sh /backups/context_engine-YYYYMMDD.dump --yes

# 5. Run smoke.
bash scripts/smoke.sh
```

### Fallback: raw `pg_restore`

Only when `scripts/restore.sh` is unavailable. This skips every
safety rail the script provides — no safety snapshot, no dump
validation, no post-restore probe, no alembic drift check:

```bash
docker compose stop api worker
docker compose exec -T postgres \
    pg_restore -U postgres -d context_engine \
    --clean --if-exists --no-owner --exit-on-error \
    < /backups/context_engine-YYYYMMDD.dump
docker compose start api worker
bash scripts/smoke.sh
```

If smoke fails after a manual restore, see [Schema drift](#schema-drift).

---

## Upgrade

### Recommended: `scripts/upgrade.sh`

The `upgrade.sh` script automates the standard upgrade path. It captures the pre-upgrade state (git SHA and database) **before** it changes, so it can print exact copy-paste rollback hints if anything fails.

```bash
cd /path/to/context-engine
bash scripts/upgrade.sh --yes
```

The script runs these stages in order:
1.  **Preflight** — confirms `docker`, `git`, and `curl` are present.
2.  **Safety backup** — runs `scripts/backup.sh` to a timestamped file.
3.  **`git pull`** — updates your local checkout (fast-forward only).
4.  **Rebuild** — `docker compose up -d --build`.
5.  **Migrate** — `alembic upgrade head`.
6.  **Smoke** — runs `scripts/smoke.sh` to confirm health.

`upgrade.sh` captures the pre-upgrade git SHA and backup path **before**
it changes anything, so on any failure it prints copy-paste rollback
commands with real paths (not a generic template). It refuses to run
on a dirty working tree and refuses non-fast-forward pulls — both
would make rollback ambiguous.

### Manual upgrade (fallback)

Use these raw commands only if `upgrade.sh` is unavailable or you need
a non-standard update (e.g., merging diverged branches). This path
has no rollback-hint printing — write down the pre-upgrade SHA and
backup path yourself.

```bash
cd /path/to/context-engine

# 1. Take a safety backup BEFORE upgrading.
bash scripts/backup.sh --output ./backups/pre-upgrade

# 2. Record the pre-upgrade SHA — you need this for rollback.
git rev-parse HEAD

# 3. Pull the new code.
git pull --ff-only origin main

# 4. Rebuild and restart.
docker compose up -d --build

# 5. Apply any new migrations.
docker compose exec -T api alembic upgrade head

# 6. Verify.
bash scripts/smoke.sh
```

If any step fails, jump to [Rollback](#rollback).

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

# 2. Restore the pre-upgrade backup via the supported restore path.
#    --safety-backup snapshots the current (bad) DB first, so even
#    this rollback is reversible.
bash scripts/restore.sh \
    backups/pre-upgrade/context_engine-YYYYMMDDTHHMMSSZ.dump \
    --yes --safety-backup

# 3. Check out the code version that matches the backup's schema.
git checkout <pre-upgrade-commit>
docker compose up -d --build

# 4. Verify.
bash scripts/smoke.sh
```

If `restore.sh` is not available (e.g., you rolled the checkout back
to a commit that predates the script), fall back to the raw
`pg_restore` recipe in [Restore → fallback](#fallback-raw-pg_restore).

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

## Worker health

A worker that is *running* is not necessarily *healthy*. Queue
backlog is the most obvious signal, but the worker can also be
silently idle, stuck on a single slow task, or crash-looping fast
enough that `docker compose ps` still reports it as running.

### Is the worker alive at all?

```bash
# 1. Container state (Up / Restarting / Exit).
docker compose ps worker

# 2. Recent log activity. A healthy worker logs celery task
#    lifecycle lines; a dead worker is silent.
docker compose logs --tail 40 worker

# 3. Restart count — a worker that has restarted many times in a
#    short window is crash-looping. Note the "RestartCount".
docker inspect --format '{{.RestartCount}} {{.State.Status}}' \
    "$(docker compose ps -q worker)"
```

### Is the worker actually processing?

```bash
# Watch queue depth over ~10 seconds. A draining worker should
# reduce it; a stuck worker holds it steady.
for i in 1 2 3 4 5; do
    docker compose exec -T redis redis-cli LLEN celery
    sleep 2
done

# Force a probe task and watch it land in the worker logs.
docker compose exec -T redis redis-cli LPUSH celery '{"probe": true}' >/dev/null
docker compose logs --tail 10 worker
```

### Common failure modes

| Signal | Cause | Fix |
|---|---|---|
| `RestartCount` growing every minute | Worker crashes at import time — bad dependency, missing env var | Read the first 20 lines of `docker compose logs worker`; the traceback is at startup, not mid-run |
| Worker silent for > 1 min with jobs in queue | Stuck on a poison-pill task | `docker compose restart worker`; if it reoccurs, see [Queue backlog → Common causes](#common-causes) |
| Worker logs `ConnectionError` to redis | Redis restarted or Redis memory limit tripped | `docker compose logs redis`; restart both: `docker compose restart redis worker` |
| Worker up but extraction always times out | Provider-backed extraction stalling on `LITELLM_API_KEY` calls | Temporarily disable: unset `EXTRACTION_MODEL` in `.env`, restart; falls back to rule-based |

After any worker fix, confirm with `bash scripts/smoke.sh` — the BOOT
step now checks `LLEN celery` and will fail if the queue is still
backed up over `SMOKE_QUEUE_BACKLOG_LIMIT` (default 25).

---

## Schema drift

The database schema is tracked by Alembic. Drift means the code
running in the `api` container expects a different revision than what
the DB reports. Common causes: a manual `alembic stamp` that lied
about the revision; a backup restored from an older schema; an
upgrade that ran new code but failed before `alembic upgrade head`;
a rollback that reverted code but left the newer schema in place.

### Diagnose

```bash
# What revision is the DB currently on?
docker compose exec -T api alembic current

# What revision does the code expect?
docker compose exec -T api alembic heads

# Full migration history.
docker compose exec -T api alembic history --verbose | tail -30
```

Compare `current` and `heads`:

- **`current == heads`** — schema is up to date. Drift is not the
  problem; look elsewhere.
- **`current` is an ancestor of `heads`** — the DB is behind the
  code. Run `alembic upgrade head`.
- **`current` is a descendant of `heads`** — the DB is AHEAD of the
  code (you rolled back code but not schema). Either upgrade the
  code to match, or `alembic downgrade <heads>`.
- **`current` is not in the code's migration tree at all** — the DB
  was stamped to a revision that no longer exists, or restored from
  a fork. This is unsafe; restore from a known-good backup.

### Fix: DB behind the code

```bash
docker compose exec -T api alembic upgrade head
```

If this fails with *"target database is not up to date"* but
`current` says otherwise, the alembic_version table disagrees with
the actual schema. Inspect:

```bash
docker compose exec -T postgres psql -U postgres -d context_engine -c \
    "SELECT * FROM alembic_version;"
```

If the value is stale, stamp it to match the actual schema state and
re-run upgrade. Only do this if you are certain what the actual
schema state is:

```bash
docker compose exec -T api alembic stamp <actual-revision>
docker compose exec -T api alembic upgrade head
```

### Fix: DB ahead of the code (after a code rollback)

```bash
docker compose exec -T api alembic downgrade <code-heads-revision>
```

Downgrades can be destructive — a migration that dropped a column on
upgrade will drop the re-added column on downgrade. Take a backup
first:

```bash
bash scripts/backup.sh
docker compose exec -T api alembic downgrade <revision>
bash scripts/smoke.sh
```

`bootstrap.sh` already checks `current == heads` after running
migrations and fails loudly on drift. `restore.sh` also warns on
drift after a restore completes. If you're seeing drift *outside*
those moments, someone (or some script) did a manual stamp/downgrade.

---

## Bad seed / import state

Symptoms: the stack is up and healthy, but one or more workspaces
contain partial or nonsensical data — empty graphs, orphaned source
documents, half-ingested imports, duplicate workspaces from repeated
seed calls.

### Diagnose

```bash
# Canonical row counts — what actually landed?
docker compose exec -T postgres psql -U postgres -d context_engine -c "
    SELECT 'workspaces'       AS t, count(*) FROM workspaces
    UNION ALL SELECT 'knowledge_models',    count(*) FROM knowledge_models
    UNION ALL SELECT 'components',          count(*) FROM components
    UNION ALL SELECT 'source_documents',    count(*) FROM source_documents
    UNION ALL SELECT 'component_sources',   count(*) FROM component_sources
    UNION ALL SELECT 'connectors',          count(*) FROM connectors;"

# Per-workspace breakdown — which workspace is broken?
docker compose exec -T postgres psql -U postgres -d context_engine -c "
    SELECT w.id, w.name,
           (SELECT count(*) FROM knowledge_models WHERE workspace_id = w.id) AS models,
           (SELECT count(*) FROM components c JOIN knowledge_models m ON c.model_id = m.id WHERE m.workspace_id = w.id) AS components,
           (SELECT count(*) FROM source_documents WHERE workspace_id = w.id) AS sources
    FROM workspaces w ORDER BY w.created_at;"
```

### Common states and fixes

| Symptom | Cause | Fix |
|---|---|---|
| `workspaces > 0`, `components = 0` in the demo workspace | Seed returned 200 but `_populate_demo_workspace` silently failed | Re-seed: `curl -X POST http://localhost:8000/api/seed-demo -H 'Content-Type: application/json' -d '{}'`. If it re-fails, check `docker compose logs api` for the traceback |
| Multiple rows in `workspaces` with the same name | Historical bug where seed was not idempotent | Keep the newest, delete the duplicates: `DELETE FROM workspaces WHERE id NOT IN (SELECT id FROM workspaces ORDER BY created_at DESC LIMIT 1) AND name = 'Demo Workspace';` |
| `source_documents > 0` but `components = 0` in a real workspace | Ingestion ran but extraction pipeline crashed; documents were accepted but never processed | Re-run extraction: `POST /api/imports` with the same payload; it is idempotent on `external_id`. Check `docker compose logs api` for extraction errors |
| `component_sources = 0` with non-zero `components` | Provenance link step was skipped — every node will have `source_count=0` in the graph | Re-run the seed or import; if the regression is in seeded data specifically, the post-seed self-check in `bootstrap.sh` catches it on re-run |
| `/api/imports` returns `failed_documents > 0` | Ingestion pipeline (rule-based or provider-backed) crashed on a specific doc | Response includes per-document status; find the failing `external_id`, inspect it, fix or delete the source document |

The safest way to recover from a genuinely corrupted seed/import state
is to restore from a pre-corruption backup. If you don't have one,
a nuclear reset (`docker compose down -v && bash scripts/bootstrap.sh`)
at least gets back to a known-good demo state — but loses anything
you've imported.

---

## Container and compose failures

When `docker compose ps` shows a service as `Exit`, `Restarting`, or
missing, start here.

### A service won't start at all

```bash
# 1. What state is every service in?
docker compose ps --all

# 2. Full log for the failing service (first lines usually hold the
#    cause — import errors, missing env var, config parse failure).
docker compose logs --no-color "<service>" | head -60

# 3. Was the image actually built? A stale image will reproduce a
#    bug you already fixed in the source tree.
docker compose images "<service>"
```

### A service keeps restarting (crash loop)

```bash
# How many restarts, how recently?
docker inspect --format \
    '{{.Name}}: restarts={{.RestartCount}} state={{.State.Status}} started={{.State.StartedAt}}' \
    $(docker compose ps -q)

# Force-rebuild the image. Cached layers can hold bugs that are
# already fixed in the tree.
docker compose up -d --build --force-recreate "<service>"
```

Service-specific crash causes:

| Service | Most common cause | First check |
|---|---|---|
| `api` | Missing `ENCRYPTION_KEY` in `.env`, or stale build missing a new dep | `grep ENCRYPTION_KEY .env`; `docker compose up -d --build api` |
| `worker` | Same image as api — usually the same bug | Fix `api` first; worker typically recovers |
| `postgres` | Port conflict (5432 already taken on host), or corrupted volume after an unclean shutdown | `lsof -i :5432`; `docker compose logs postgres \| head -30` |
| `redis` | Port conflict, or out-of-memory kill when `--maxmemory` is hit by a backed-up queue | `docker compose logs redis \| tail -20`; see [Queue backlog](#queue-backlog) |

### Port conflict

```bash
# Who else is using the port?
sudo lsof -iTCP:8000 -sTCP:LISTEN   # (or 5432 / 6379)

# Override in .env and restart.
echo 'HOST_API_PORT=9000' >> .env
docker compose up -d
```

### Compose config itself is broken

```bash
# Validate the compose file without starting anything.
docker compose config

# Show what `docker compose` is resolving after .env substitution.
docker compose config --services
docker compose config | head -40
```

A silent `VARIABLE is not set. Defaulting to a blank string.` warning
from `docker compose config` is almost always the root cause when a
service behaves as if a config value was missing.

### Recover a container that is hard-stuck

```bash
# Force-stop, force-recreate. Safe for api/worker/redis. For postgres,
# only do this if you are sure the DB is not mid-transaction — a
# forced kill on postgres can leave pg_xlog in a state that needs
# recovery on next start.
docker compose kill "<service>"
docker compose up -d --force-recreate "<service>"
```

After any compose-level fix, re-run smoke:

```bash
bash scripts/smoke.sh
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

> Reminder: the diagnose tarball is **not a backup**. It contains
> logs, health, and redacted config only — no application data. If
> you need to restore from a backup, you need a `backup.sh` dump, not
> a diagnose snapshot.

### Step 2: read the snapshot in order

1. **`README.txt`** — orientation.
2. **`logs-api.txt`** — the cause is usually in the last 50 lines.
   Tracebacks have the filename and line number of the failure.
3. **`compose.txt`** — is the expected set of services running? If a
   service is in `Restarting (N)`, it is crash-looping. Jump to
   [Container and compose failures](#container-and-compose-failures).
4. **`alembic.txt`** — does `current` match `heads`? If not, jump to
   [Schema drift](#schema-drift).
5. **`postgres.txt`** — are the canonical row counts what you expect?
   Zero components in a workspace you thought was seeded is a seed
   regression; jump to [Bad seed / import state](#bad-seed--import-state).
6. **`redis.txt`** — is the queue backed up? If so, jump to
   [Queue backlog](#queue-backlog). If the worker container is up
   but nothing is moving, jump to [Worker health](#worker-health).
7. **`health.txt`** — did `/health/ready` report specific
   sub-components failing?

### Step 3: match symptoms to playbooks

| Symptom in snapshot | Playbook |
|---|---|
| `compose.txt` shows a service in `Restarting` or `Exit` | [Container and compose failures](#container-and-compose-failures) |
| `logs-api.txt` has `ConnectionRefused` to postgres | `logs-postgres.txt` first → [Container and compose failures](#container-and-compose-failures) or [Disk pressure](#disk-pressure) |
| `logs-api.txt` has `alembic` errors | [Schema drift](#schema-drift); if an upgrade failed mid-run, [Rollback](#rollback) |
| `alembic.txt` shows `current` ≠ `heads` | [Schema drift](#schema-drift) |
| `postgres.txt` shows zero rows in `components` or missing `component_sources` | [Bad seed / import state](#bad-seed--import-state) |
| `redis.txt` shows `LLEN celery` > 50 | [Queue backlog](#queue-backlog) |
| `redis.txt` shows `LLEN celery` is small but worker logs are silent | [Worker health](#worker-health) |
| `stats.txt` shows worker with high restart count | [Worker health](#worker-health) |
| `stats.txt` shows a container at 100% CPU for minutes | Either legitimate workload or a runaway query — check `postgres.txt` longest-running queries |
| `host.txt` shows disk > 90% full | [Disk pressure](#disk-pressure) |
| All logs look fine but health is failing | Port conflict or proxy misconfig — check the reverse proxy logs, then `host.txt` for `docker info` network warnings, and [Container and compose failures → Port conflict](#port-conflict) |

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
# 1. Last-chance backup via the supported path. Skip only if you are
#    SURE you want data loss. backup.sh validates the dump before
#    returning, so a "backup complete" line means it is restorable.
bash scripts/backup.sh --output ./backups/pre-reset \
    || echo "(backup failed — proceeding with reset anyway)"

# 2. Bring everything down and delete the volumes.
docker compose down -v

# 3. Bootstrap from scratch.
bash scripts/bootstrap.sh

# 4. Verify.
bash scripts/smoke.sh
```

If you decide the reset was a mistake, the dump in
`./backups/pre-reset/` restores with `bash scripts/restore.sh <path> --yes`.

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
