# Production runbook

This runbook operates the hardened, single-host deployment in
`docker-compose.production.yml`. It provides TLS, startup configuration
validation, isolated database networking, separate PostgreSQL admin and
application roles, non-root application containers, health checks, resource
limits, bounded logs, Redis-backed request controls, durable volumes, and
verified backup/restore scripts.

It is a production baseline, not a high-availability control plane. A single
Docker host remains one failure domain. Workloads that require automated
failover, multi-region recovery, or horizontal API scaling should use a managed
PostgreSQL/pgvector service, an external load balancer, centralized rate
limiting, and an orchestrator.

## Service topology

- `proxy` is the only public service. Caddy binds TCP 80/443 and UDP 443,
  obtains and renews certificates, adds security headers, and proxies to `app`.
- `app` and `worker` use a dedicated, non-superuser PostgreSQL role. They run
  as UID/GID 10001 with a read-only root filesystem. Their minimal launcher
  starts with only `DAC_READ_SEARCH`/`SETUID`/`SETGID` long enough to read
  operator-owned `0600` Compose file secrets, then irreversibly drops identity
  and verifies that no capabilities remain before it imports or executes
  application code.
- `db` is reachable only on the internal backend network. Its admin password
  is not given to application containers. A minimal root bootstrap copies the
  two operator-owned database secrets into a postgres-owned in-memory filesystem
  before the upstream image drops to its `postgres` user.
- `redis` is internal-only and stores short-lived distributed rate-limit and
  single-use OAuth-state keys. Project data never lives there; the API fails
  closed if request controls are unavailable.
- `migrate` is a one-shot schema migration gate. `data-init` is a one-shot
  volume permission gate.
- `app_data`, `postgres_data`, `caddy_data`, and `caddy_config` are durable
  Docker volumes. Only the database and app-data volumes contain business data.

## Host prerequisites

Use a supported Linux host with Docker Engine and Docker Compose v2, time
synchronization, disk monitoring, and a firewall that allows inbound TCP
80/443 and UDP 443. DNS for `DAEMONSTATE_DOMAIN` must resolve to the host.
Allow outbound HTTPS for ACME, model providers, and connectors.

Run Compose from a dedicated operations account with access to the Docker
daemon. That access is effectively host-root authority, so do not share the
account. Keep the deployment checkout, environment file, secret files, and
backup directory owned by that account on storage with restricted
administrative access. Send backups to a different failure domain. Size the
host only after load testing; the example limits assume at least four CPU cores
and 8 GiB RAM.

## First deployment

### 1. Publish an immutable application image

Build the existing `Dockerfile` in CI, scan it, generate an SBOM, push it to a
private registry, and record its digest. Set `DAEMONSTATE_IMAGE` to the
digest-qualified reference:

```text
registry.example.com/daemonstate@sha256:<64-hex-character-digest>
```

Pin the Caddy, pgvector, Redis, and Prometheus images by digest as well. Do not
deploy mutable tags.

### 2. Create host secrets

The following example creates only the mandatory secrets. It intentionally
writes outside the repository.

```bash
sudo install -d -o "$(id -un)" -g "$(id -gn)" -m 0750 /etc/daemonstate
sudo install -d -o "$(id -un)" -g "$(id -gn)" -m 0700 /etc/daemonstate/secrets
sudo sh -c 'umask 077; openssl rand -hex 32 > /etc/daemonstate/secrets/postgres_admin_password'
sudo sh -c 'umask 077; openssl rand -hex 32 > /etc/daemonstate/secrets/postgres_app_password'
sudo sh -c 'umask 077; openssl rand -hex 32 > /etc/daemonstate/secrets/server_api_key'
sudo sh -c 'umask 077; openssl rand -hex 32 > /etc/daemonstate/secrets/metrics_bearer_token'
sudo sh -c 'umask 077; python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())" > /etc/daemonstate/secrets/encryption_key'
sudo chown "$(id -un):$(id -gn)" /etc/daemonstate/secrets/*
sudo chmod 0600 /etc/daemonstate/secrets/*
```

The encryption key is a Fernet key. Losing it makes encrypted connector
credentials unrecoverable. Store a copy in the organization secret manager,
not in source control or an ordinary host backup.

Use the optional secret-file variables for model-provider keys, connector
client secrets, and previous encryption keys. `PRINCIPAL_API_KEYS` is disabled
in this single-tenant profile until action-level authorization covers every
HTTP and MCP operation. Keep optional secret files owned by the dedicated
operations account and mode `0600`. Never put secret values directly in the
Compose environment file.

Create `DAEMONSTATE_PROJECT_PATH` as a dedicated host directory containing
only repositories this service may inspect. It is mounted read-only at
`/workspace`; canonical-path checks reject traversal and symlink escapes.

### 3. Configure and validate

Copy `deploy/production/production.env.example` to
`/etc/daemonstate/production.env`, replace every example value, then protect
it:

```bash
sudo install \
  -o "$(id -un)" \
  -g "$(id -gn)" \
  -m 0600 \
  deploy/production/production.env.example \
  /etc/daemonstate/production.env
sudoedit /etc/daemonstate/production.env
```

Configure an OAuth provider only when its client ID, secret file, and HTTPS
redirect URI are all available. The container entrypoint rejects partial
provider configuration, weak mandatory secrets, invalid Fernet keys, plaintext
public URLs, and a disabled API rate limit.

Production API and worker processes also audit every populated connector
credential row at startup and during readiness checks. A plaintext, malformed,
or undecryptable row keeps the service unready; repair it through the migration
job rather than bypassing the check.

Validate interpolation and render the effective configuration before pulling:

```bash
scripts/validate-production-images.sh /etc/daemonstate/production.env
docker compose \
  --env-file /etc/daemonstate/production.env \
  --file docker-compose.production.yml \
  config --quiet
```

Review `docker compose ... config` in a protected terminal if needed. It
contains no secret values, but it does reveal host secret-file paths.

### 4. Start and verify

```bash
docker compose \
  --env-file /etc/daemonstate/production.env \
  --file docker-compose.production.yml \
  pull

docker compose \
  --env-file /etc/daemonstate/production.env \
  --file docker-compose.production.yml \
  up --detach
```

Wait for `db` and `app` to become healthy and for `data-init` and `migrate` to
exit with status zero:

```bash
docker compose \
  --env-file /etc/daemonstate/production.env \
  --file docker-compose.production.yml \
  ps --all

curl --fail --silent --show-error \
  "https://daemonstate.example.com/health/ready"
```

The readiness response must report PostgreSQL, API authentication enabled,
credential encryption enabled, and a positive rate limit. Exercise one
authenticated API request through the public hostname. Confirm that host ports
do not expose PostgreSQL or port 8000.

## Routine operations

Use Compose with the same environment and file arguments for every command:

```bash
docker compose \
  --env-file /etc/daemonstate/production.env \
  --file docker-compose.production.yml \
  ps
```

Inspect bounded JSON logs with `logs --since`, and ship Docker logs to the
central log platform:

```bash
docker compose \
  --env-file /etc/daemonstate/production.env \
  --file docker-compose.production.yml \
  logs --since 30m app worker db redis proxy
```

Alert on:

- public readiness failure or TLS expiry;
- container restarts and unhealthy status;
- worker failures, retries, dead-lettered jobs, or a growing sync backlog;
- database connections, long transactions, locks, disk saturation, and volume
  free space;
- p95/p99 latency and elevated 4xx/5xx responses;
- backup age, backup upload failure, and restore-drill failure.

The API limiter and OAuth nonce store use Redis atomically across workers.
This profile enforces `APP_WORKERS=1` because its Prometheus registry is
process-local. Scale beyond one API process only after adding multiprocess or
per-replica metrics collection, an external load balancer, and an aggregate
database-pool budget below `POSTGRES_MAX_CONNECTIONS`.

Source revisions are committed before semantic projection. Production API
requests project synchronously, and the sync worker recovers up to
`SOURCE_INGESTION_SWEEP_LIMIT` unfinished revisions per poll after an
interrupted request or restart.

Projection is performed by leased `source_ingestion_jobs` with heartbeats,
bounded retries, claim-token fencing, and dead-letter state. A worker poll does
not hold a database lock while waiting on extraction or embedding providers.
After correcting a provider/configuration fault, operators can run
`daemonstate worker sync --redrive-dead-letter --limit 10` to safely requeue unfinished
dead letters; inspect the JSON worker result before declaring recovery complete.

The hardened profile is API-only: it sets `SERVE_FRONTEND=false` because the
bundled development UI does not yet implement browser session authentication.
Agents and operators authenticate every API request with the server API key;
do not embed that key in browser code.

## PostgreSQL backups

`scripts/backup-postgres.sh` creates an atomic custom-format dump, verifies that
`pg_restore` can read its catalog, and writes a SHA-256 sidecar. Run it from the
deployment checkout:

```bash
scripts/backup-postgres.sh \
  /srv/daemonstate/backups \
  /etc/daemonstate/production.env
```

Schedule it with a service manager and a single-instance lock. Upload both the
`.dump` and `.sha256` files to encrypted, versioned, immutable off-host
storage. Apply retention in the backup store rather than deleting files from
the backup script. Monitor the newest successful off-host object.

A logical dump's recovery-point objective is the interval since the previous
successful dump. For a lower RPO, use managed continuous backup or tested WAL
archiving. Logical dumps do not protect `app_data`; snapshot or replicate that
volume on the same schedule. Preserve the encryption key separately. Caddy
state is replaceable but backing it up avoids certificate reissuance limits.

## Restore drill

Run a restore drill at least monthly and before risky upgrades. The safe default
is a new database name:

```bash
scripts/restore-postgres.sh \
  /srv/daemonstate/backups/daemonstate-YYYYMMDDTHHMMSSZ.dump \
  daemonstate_restore_test \
  /etc/daemonstate/production.env
```

The script verifies the sidecar checksum when present, validates the archive,
creates the target database, restores in one transaction, and verifies that
public tables exist. It also refreshes planner statistics after the restore.
Test representative queries against the restored database from an isolated
application instance, then have an administrator remove the drill database
after evidence is recorded.

Replacing an existing database is deliberately gated. First enter maintenance,
stop traffic and writers, record a fresh backup, and verify the selected
archive. Then:

```bash
docker compose \
  --env-file /etc/daemonstate/production.env \
  --file docker-compose.production.yml \
  stop proxy app worker

RESTORE_CONFIRM=replace:daemonstate \
  scripts/restore-postgres.sh \
    /srv/daemonstate/backups/daemonstate-YYYYMMDDTHHMMSSZ.dump \
    daemonstate \
    /etc/daemonstate/production.env

docker compose \
  --env-file /etc/daemonstate/production.env \
  --file docker-compose.production.yml \
  up --detach app worker proxy
```

Verify readiness, authentication, workspace counts, connector credentials, and
one context query before ending maintenance. Restoring the database does not
restore files in `app_data`; restore the matching volume snapshot when those
files are required.

## Upgrade and rollback

Test every target image and migration against a recent restored backup in
staging. Read the release notes, confirm database compatibility, and record the
current image digests.

1. Create and upload a fresh database dump and app-data snapshot.
2. Change only the digest-qualified application image in the protected
   environment file.
3. Run `scripts/validate-production-images.sh
   /etc/daemonstate/production.env`, then pull the new images.
4. Enter maintenance and stop `proxy`, `app`, and `worker`. Current schema
   revisions may build indexes non-concurrently, so do not run them beside
   production writers.
5. Run `docker compose ... run --rm migrate`. The migrator takes a PostgreSQL
   advisory lock, reconciles an unversioned legacy database once, and gates
   versioned installations on the current Alembic head. In the same
   transaction it rewrites every populated connector credential with the
   current `ENCRYPTION_KEY`; malformed or undecryptable rows abort the entire
   deployment without printing credential values.
6. Recreate `app`, `worker`, and `proxy`, then verify readiness and a smoke query.
7. Watch errors, latency, worker backlog, and database locks through the
   observation window.

The migration statement timeout defaults to disabled for the one-shot migrator;
`MIGRATION_LOCK_TIMEOUT_MS` still bounds lock acquisition. Set an explicit
statement timeout only after timing the migration against a restored
production-sized database. For zero-downtime upgrades on large tables, replace
the single-host migration step with reviewed online/concurrent index operations
and a separately tested orchestration plan.

A code rollback is safe only when the prior release supports the migrated
schema. Otherwise enter maintenance and restore the matched pre-upgrade
database and app-data snapshot before reverting the image digest. Never assume
down-migrations are lossless.

## Secrets and incident response

Treat a leaked server API key as an authentication incident: replace the secret
atomically, recreate `app` and `worker`, revoke the old key in every client, and
review access logs. Rotate PostgreSQL passwords in a maintenance window because
changing a secret file does not alter an already-initialized database role.

For encryption-key rotation:

1. Back up the database and old key.
2. Put the new Fernet key in `encryption_key` and the old key in
   `previous_encryption_keys`.
3. Enter maintenance and run `docker compose ... run --rm migrate`. The
   `daemonstate db deploy` command decrypts with the current/previous key set and
   transactionally re-encrypts populated rows with the new current key.
4. Recreate app and worker containers, then verify readiness and connector
   access.
5. Remove the old key only after verification and recreate containers again.

If database integrity, credential confidentiality, or host integrity is in
doubt, stop the proxy, preserve logs and volume snapshots, rotate external
provider credentials from a clean system, and recover onto a newly provisioned
host. Do not reuse a potentially compromised Docker host.

## Known scaling boundary

This deployment tolerates individual process crashes but not loss of its host,
Docker daemon, or storage. Before calling the service highly available:

- move PostgreSQL/pgvector to a replicated service with automated failover,
  point-in-time recovery, and tested upgrades;
- store uploaded artifacts in replicated object storage;
- use a centralized gateway rate limiter and multiple stateless app replicas;
- run workers under an orchestrator with queue-depth autoscaling;
- export metrics, traces, and audit logs to systems outside the failure domain;
- conduct load, failover, disaster-recovery, and security tests against explicit
  SLO, RPO, and RTO targets.
