# Self-hosting DaemonState

DaemonState has three supported operating profiles. Choose the profile by where
the browser and coding-agent tools run; do not expose the personal profiles
directly to the public internet.

| Profile | Includes | Intended access |
|---|---|---|
| Personal Docker | Dashboard, API, PostgreSQL/pgvector, migrations, and sync worker | Browser on the same machine, or through an SSH tunnel |
| Workstation | Dashboard/API with SQLite plus the sync worker; can reach locally installed Codex, Claude Code, and OpenCode tools | Browser on the same machine |
| Hardened single-host | TLS proxy, authenticated API, PostgreSQL/pgvector, Redis, worker, and metrics | Internet-facing API clients; no browser dashboard |

## Personal Docker

Install Git, Docker Engine or Docker Desktop, and a current Docker Compose v2
with `up --wait` support. Then:

```bash
git clone https://github.com/Darshan174/DaemonState.git daemonstate
cd daemonstate
bash scripts/self-host.sh
```

The first run creates `.env` with mode `0600`, generates a PostgreSQL password
and a Fernet key for connector credential encryption, builds the application,
runs the database migration gate, and waits for the API and worker to become
healthy. Open <http://127.0.0.1:8000>.

Before connecting another repository, set `DAEMONSTATE_PROJECT_PATH` in `.env`
to its absolute host path and recreate the services:

```bash
bash scripts/self-host.sh
```

The wrapper refuses nonexistent paths and broad root/home mounts. The validated
path is mounted read-only at `/workspace`. Docker can index and query it,
but the container cannot use coding-agent CLIs or session histories installed
only on the host, and it cannot write agent changes back to that mount. Use the
workstation profile when the Continue workflow must launch those local tools.

Useful operations:

```bash
docker compose ps
docker compose logs --follow app worker
docker compose restart app worker
docker compose down
```

`docker compose down` keeps named volumes. `docker compose down --volumes`
permanently deletes the local database and uploaded artifacts.

### Access from another computer

The dashboard has no browser login yet. Its supported Docker profile therefore
binds to `127.0.0.1`, even on a remote server. Reach it with an SSH tunnel:

```bash
ssh -L 8000:127.0.0.1:8000 user@your-server
```

Then open <http://127.0.0.1:8000> on your computer. Do not change
`BIND_ADDRESS` to `0.0.0.0` or forward port 8000 through a router. Setting
`SERVER_API_KEY` protects API clients but currently prevents the bundled
browser dashboard from making requests; it is not a browser-authentication
substitute.

## Workstation installation

This profile is the full local-product path for a machine that has the coding
agent CLIs and their session histories:

```bash
git clone https://github.com/Darshan174/DaemonState.git daemonstate
cd daemonstate
bash scripts/doctor.sh --bare-metal
bash scripts/setup.sh
bash scripts/start.sh
```

`setup.sh` creates a permission-restricted `.env` with generated local secrets,
installs the backend and frontend, and builds the dashboard. `start.sh` waits
for the API to become ready and then supervises the connector sync worker.
Set `DAEMONSTATE_START_WORKER=0` only when a separate service manager runs the
worker.

## Persistence and backups

Personal Docker stores relational data in the `pg_data` Compose volume and request/upload
artifacts in `daemonstate_uploads`. Back up both before upgrades. A local
database dump can be captured without exposing PostgreSQL:

```bash
umask 077
install -d -m 0700 backups
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
database_dump="backups/daemonstate-${stamp}.dump"
uploads_archive="backups/daemonstate-uploads-${stamp}.tar.gz"
docker compose exec -T db \
  pg_dump --username daemonstate --dbname daemonstate --format custom \
  > "${database_dump}"
docker compose exec -T app python -c \
  "import sys,tarfile; archive=tarfile.open(fileobj=sys.stdout.buffer, mode='w|gz'); archive.add('/data', arcname='data'); archive.close()" \
  > "${uploads_archive}"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "${database_dump}" "${uploads_archive}"
else
  shasum -a 256 "${database_dump}" "${uploads_archive}"
fi > "backups/daemonstate-${stamp}.sha256"
```

Store the permission-restricted `.env` encryption key separately from these
files. A database dump alone is not a complete recovery set. Test the dump,
uploads archive, and checksums on a disposable Compose project before relying
on them.

The workstation profile stores its SQLite database and artifacts under
`DATA_DIR` (the default is `./data`). Stop the API and worker, then take a
filesystem snapshot or copy that entire directory together with an escrowed
copy of the encryption key.

## Upgrades

Back up first, review the release notes and license, then update and recreate:

```bash
docker compose stop worker app
git pull --ff-only
docker compose build migrate app worker
docker compose run --rm migrate
docker compose up --build --detach --wait --wait-timeout 300
```

Stopping writers first makes the maintenance boundary explicit. If the
migration fails, leave the API and worker stopped, restore from the tested
backup if needed, and investigate the migration logs. The one-shot `migrate`
service must exit successfully before the API starts.
Verify `docker compose ps --all` and <http://127.0.0.1:8000/health/ready>.
Never change `POSTGRES_PASSWORD` after the PostgreSQL volume has been
initialized unless you also rotate the database role password.

## Internet-facing API deployment

For a public hostname, follow the
[production runbook](production-runbook.md). That profile uses TLS,
file-backed secrets, explicit migrations, internal PostgreSQL and Redis,
resource limits, authenticated API requests, metrics, and guarded
backup/restore tooling.

The hardened profile intentionally sets `SERVE_FRONTEND=false`: until
DaemonState has browser session authentication and CSRF protection, it is an
API deployment rather than a public dashboard deployment.
