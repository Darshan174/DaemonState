# Configuration

DaemonState reads application settings from environment variables and, for
workstation installs, from the repository-root `.env` file. Variable names are
case-insensitive in the Python settings layer. Empty optional values are
ignored, which is why `.env.example` can list every integration without
enabling it.

Start from the tracked example:

```bash
cp .env.example .env
chmod 0600 .env
```

`scripts/setup.sh` and `scripts/self-host.sh` perform this step safely and
generate local secrets when `.env` does not exist. Do not commit `.env` or place
provider tokens in documentation, command output, or browser screenshots.

## Profile behavior

| Profile | Configuration source | Storage | Repository path |
|---|---|---|---|
| Workstation | `.env` plus process environment | SQLite and artifacts under `DATA_DIR` by default | Absolute local path selected in the UI/CLI; optionally restricted by `ALLOWED_REPO_ROOTS` |
| Personal Docker | `.env` interpolated by `docker-compose.yml` | PostgreSQL/pgvector plus named upload volume | Host `DAEMONSTATE_PROJECT_PATH`, mounted read-only as `/workspace` |
| Hardened production | Host-only production env file plus file-backed Docker secrets | PostgreSQL/pgvector, Redis, and named data volumes | Host path mounted read-only as `/workspace` |

Process environment values take precedence over `.env`. Compose interpolation
also applies the defaults written in the Compose file.

## Minimum local configuration

The generated local file is sufficient for repository indexing, local session
discovery, deterministic extraction, Workspace/Session Context, the demo, and
the browser product loop. No model provider is required for those paths.

```dotenv
ENVIRONMENT=development
DATABASE_URL=sqlite+aiosqlite:///data/context.db
DATA_DIR=./data
BIND_ADDRESS=127.0.0.1
PORT=8000
AUTO_MIGRATE=true
SERVE_FRONTEND=true
DEMO_ENDPOINTS_ENABLED=true
API_DOCS_ENABLED=true
```

## Application and storage

| Variable | Example/default | Meaning |
|---|---|---|
| `COMPOSE_PROJECT_NAME` | `daemonstate` | Docker Compose project/volume namespace. It is not read by the application. |
| `ENVIRONMENT` | `development` | Runtime mode. The value `production` activates fail-closed configuration validation and production security headers. |
| `RELEASE_SHA` | `dev` | Release/build identifier included in logs and health metadata. Use the deployed Git SHA in production. |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/context.db` | SQLAlchemy database URL for workstation use. Compose supplies PostgreSQL URLs internally. |
| `DATA_DIR` | `./data` | Workstation artifact/upload directory. Back up the whole directory together with the encryption key. |
| `AUTO_MIGRATE` | `true` locally | Creates/updates the local schema at startup. Compose sets this to `false` and runs `daemonstate db deploy` as a separate gate. Production must be `false`. |
| `PORT` | `8000` | Host port used by `scripts/start.sh` and personal Compose. |
| `BIND_ADDRESS` | `127.0.0.1` | Host bind for personal profiles. Keep loopback-only; remote workstation binds require an explicit script override. |
| `WORKERS` | `1` | Uvicorn worker count used by `scripts/start.sh`. |
| `APP_WORKERS` | `1` | Worker count supplied by Compose/production validation. Production currently requires one because Prometheus multiprocess collection is not configured. |
| `DAEMONSTATE_PROJECT_PATH` | `.` | Host project directory mounted read-only by Docker at `/workspace`. The wrapper rejects missing, root, or whole-home paths. |

## Database controls

| Variable | Local default | Meaning |
|---|---:|---|
| `DATABASE_POOL_SIZE` | `5` | Base SQLAlchemy connection pool size for pooled databases. |
| `DATABASE_MAX_OVERFLOW` | `10` | Temporary connections allowed above the base pool. |
| `DATABASE_POOL_TIMEOUT_SECONDS` | `30` | Time to wait for a pooled connection. |
| `DATABASE_POOL_RECYCLE_SECONDS` | `1800` | Maximum pooled connection age before recycle. |
| `DATABASE_CONNECT_TIMEOUT_SECONDS` | `10` | Database connection timeout. |
| `DATABASE_STATEMENT_TIMEOUT_MS` | `30000` | Application statement timeout. Production requires a positive value. |
| `MIGRATION_STATEMENT_TIMEOUT_MS` | `0` | Migration statement timeout; `0` permits long migrations. Negative values are invalid. |
| `MIGRATION_LOCK_TIMEOUT_MS` | `30000` | Time to obtain the migration advisory lock. Production requires a positive value. |
| `POSTGRES_PASSWORD` | `daemonstate` in the example | Personal Compose database password. The startup wrapper replaces the example value on a fresh setup. Do not reuse the example outside a disposable local install. |

The production profile uses separate file-backed administrator and application
role passwords. See [Production runbook](production-runbook.md); do not copy the
personal `POSTGRES_PASSWORD` pattern into production.

## Models and retrieval

Model settings are optional. Deterministic extractors and lexical retrieval
remain available without them.

| Variable | Default | Meaning |
|---|---|---|
| `LITELLM_API_KEY` | empty | Credential passed to configured LiteLLM-backed extraction or answer models. The exact provider may also require its standard environment variables. |
| `EXTRACTION_MODEL` | empty | LiteLLM model identifier used for sources without a deterministic extractor. Failures fall back to deterministic/regex behavior where supported. |
| `EMBEDDING_MODEL` | empty | Embedding model identifier for semantic retrieval. Without it, retrieval reports lexical-only behavior. |
| `EMBEDDING_DIMENSION` | empty | Explicit embedding vector dimension when the provider cannot be inferred safely. |
| `ALLOW_HASHING_EMBEDDER` | `false` | Enables the non-semantic hashing fallback when deliberately requested. Keep false when lexical-only behavior is preferable to pseudo-semantic ranking. |
| `PGVECTOR_INDEX_DIMENSION` | `1024` | Dimension used for the configured pgvector index. Keep aligned with stored vectors. |
| `PGVECTOR_CANDIDATE_LIMIT` | `200` | Maximum pgvector candidate set considered before application ranking. |

Changing vector dimensions after data exists requires an explicit migration or
reindex plan. Do not treat the hashing embedder as equivalent to a semantic
model.

## API authentication and workspace scope

| Variable | Default | Meaning |
|---|---|---|
| `SERVER_API_KEY` | empty | Enables a single bearer/API key for `/api` routes. Leave empty in the loopback dashboard profile because the bundled browser has no login flow. Production requires at least 32 characters. |
| `PRINCIPAL_API_KEYS` | empty | JSON map from token to a stable `principal_id` and allowed `workspace_ids`. Useful for scoped development/testing; intentionally rejected in the current production profile until action-level authorization covers every mutation. |
| `DAEMONSTATE_API_KEY` | empty | CLI-only environment fallback for commands that call an authenticated HTTP API. It is not a server setting. |
| `API_RATE_LIMIT_PER_MINUTE` | `0` locally | Per-key/API request limit. `0` disables the general limiter locally. Production requires a positive value. |
| `AUTH_FAILURE_RATE_LIMIT_PER_MINUTE` | `20` | Rate limit applied to invalid authentication attempts, keyed by client IP. |
| `REDIS_URL` | empty | Distributed rate-limit and OAuth nonce backend. Required in production. |
| `RATE_LIMIT_FAIL_OPEN` | `true` locally | Whether API requests proceed when the limiter backend is unavailable. Production requires `false`. |

Clients may send either:

```http
Authorization: Bearer <key>
```

or:

```http
X-API-Key: <key>
```

`X-DaemonState-API-Key` is accepted as an explicit product-specific alias.

The response includes `X-Request-ID`; clients can provide a bounded
alphanumeric/dot/underscore/hyphen request ID to correlate logs.

## Credential encryption

| Variable | Default | Meaning |
|---|---|---|
| `ENCRYPTION_KEY` | generated locally | Primary URL-safe Fernet key used for stored connector credentials and OAuth state. Production requires a valid key. |
| `PREVIOUS_ENCRYPTION_KEYS` | empty | Comma-separated older Fernet keys accepted during rotation. New writes use the primary key. |

Rotate safely by setting the new primary key, retaining the old key in
`PREVIOUS_ENCRYPTION_KEYS`, and running:

```bash
daemonstate credentials rotate
```

Verify the result before removing the previous key. Database backups without an
escrowed encryption key are not a complete recovery set.

## HTTP and repository security

| Variable | Example/default | Meaning |
|---|---|---|
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated Host header allowlist. Production must explicitly list its public hostname and cannot use `*`. |
| `CORS_ALLOWED_ORIGINS` | empty | Comma-separated origins allowed by CORS. The same-origin local dashboard needs no extra entry. Production cannot use `*`. |
| `TRUST_PROXY_HEADERS` | `false` | Trust forwarded client/protocol headers from a known reverse proxy. The production Compose profile enables this behind Caddy. |
| `ALLOWED_REPO_ROOTS` | empty locally | Comma-separated canonical directory roots from which API/CLI repository reads are allowed. Compose fixes this to `/workspace`. Production requires at least one root. |
| `MAX_REQUEST_BODY_BYTES` | `16777216` | Maximum accepted HTTP request body size (16 MiB by default). |
| `API_DOCS_ENABLED` | `true` locally | Enables `/docs`, `/redoc`, and `/openapi.json`. Production requires false. |
| `DEMO_ENDPOINTS_ENABLED` | `true` locally | Enables `POST /api/seed-demo`. Production requires false. |
| `SERVE_FRONTEND` | `true` locally | Serves the built dashboard from FastAPI. Production requires false until browser session authentication and CSRF protection exist. |

Local action endpoints, including desktop handoff and local provider execution,
must not be exposed as a remote public API. The hardened profile is API-only.

## Logging and metrics

| Variable | Default | Meaning |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Application log threshold. |
| `LOG_FORMAT` | `console` locally | `console` or structured `json`; production requires `json`. |
| `METRICS_ENABLED` | `true` | Enables the Prometheus `/metrics` endpoint. |
| `METRICS_BEARER_TOKEN` | empty | Optional bearer token for `/metrics`; production requires at least 32 characters. |

Metrics labels avoid source and prompt content. The production profile binds
Prometheus to loopback by default.

## OpenTelemetry

Tracing is disabled by default and is metadata-only.

| Variable | Default | Meaning |
|---|---|---|
| `OTEL_ENABLED` | `false` | Enables OTLP/HTTP trace export. |
| `OTEL_CONTENT_CAPTURE` | `false` | Must remain false; content capture is unsupported and startup rejects it. |
| `OTEL_SERVICE_NAME` | `daemonstate-api` | Bounded service identifier used on spans. |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | `http://localhost:4318/v1/traces` | Absolute OTLP/HTTP trace endpoint. Production requires HTTPS and rejects credentials, query strings, and fragments in the URL. |
| `OTEL_EXPORT_TIMEOUT_SECONDS` | `5` | Positive export timeout. |
| `OTEL_SAMPLE_RATIO` | `1.0` | Sampling ratio from `0.0` through `1.0`. |
| `OTEL_BATCH_MAX_QUEUE_SIZE` | `2048` | Maximum queued spans. |
| `OTEL_BATCH_MAX_EXPORT_BATCH_SIZE` | `512` | Maximum export batch; cannot exceed queue size. |
| `OTEL_BATCH_SCHEDULE_DELAY_MS` | `5000` | Positive batch flush delay. |

See [OpenTelemetry tracing](opentelemetry.md) for span boundaries and privacy
rules.

## Connector worker

| Variable | Default | Meaning |
|---|---:|---|
| `SYNC_WORKER_LEASE_SECONDS` | `300` | Database lease duration for one claimed connector job. |
| `SYNC_WORKER_RETRY_BASE_SECONDS` | `30` | Initial retry backoff for retryable sync failures. |
| `SYNC_WORKER_RETRY_MAX_SECONDS` | `900` | Maximum retry backoff. |
| `SYNC_WORKER_POLL_INTERVAL_SECONDS` | `2` | Delay between worker polling cycles. |
| `SYNC_WORKER_JOB_TIMEOUT_SECONDS` | `1800` | Maximum wall time for one sync job. |
| `SYNC_WORKER_METRICS_PORT` | `0` locally | Dedicated worker metrics port; `0` disables it. Production uses `9101` by default. |
| `SYNC_WORKER_HEALTH_FILE` | `/tmp/daemonstate-sync-worker.ready` | Heartbeat file checked by Compose health probes. |
| `SYNC_WORKER_HEALTH_INTERVAL_SECONDS` | `15` | Database/schema-aware heartbeat interval. |
| `SOURCE_INGESTION_SWEEP_LIMIT` | `10` | Maximum pending source-ingestion jobs claimed per sweep. |
| `SOURCE_INGESTION_TIMEOUT_SECONDS` | `300` | Timeout for one source-ingestion job. |
| `SOURCE_INGESTION_MAX_ATTEMPTS` | `5` | Attempts before a source-ingestion job becomes dead-lettered. |

The worker can redrive unfinished dead letters explicitly:

```bash
daemonstate worker sync --redrive-dead-letter --json
```

## Context and continuation controls

| Variable | Default | Meaning |
|---|---:|---|
| `CONTEXT_DIGEST_CACHE_TTL_SECONDS` | `30` | In-process cache lifetime for Now-page context digests. |
| `CONTEXT_DIGEST_CACHE_MAX_ENTRIES` | `32` locally | Maximum digest cache entries. Production Compose uses `128` unless overridden. |
| `CONTINUATION_COMMAND_TIMEOUT_SECONDS` | `14400` | Maximum time for one visible continuation agent turn (four hours by default). Must be positive. |
| `SESSION_HANDOFF_BRIEF_VARIANT` | `compact_v2` | Visible Session Context renderer: `compact_v2` or emergency rollback `legacy_v1`. Automatic execution prompts are unaffected. |

CLI flags such as `--command-timeout`, `--verification-timeout`, and `--budget`
override the corresponding operation for that invocation where supported.

## OAuth and connector setup

### Public callback base

| Variable | Default | Meaning |
|---|---|---|
| `PUBLIC_BASE_URL` | empty | Absolute public base used to form OAuth callback URLs. Production requires HTTPS. Local callbacks can derive the request origin. |

### Google (Gmail and Drive)

| Variable | Required together | Meaning |
|---|---|---|
| `GOOGLE_CLIENT_ID` | Yes | Google OAuth client ID. |
| `GOOGLE_CLIENT_SECRET` | Yes | Google OAuth client secret; use a file-backed secret in production. |
| `GOOGLE_REDIRECT_URI` | Yes in production | Callback URI. A configured production URI must be absolute HTTPS. |

The implementation requests read-only Drive or Gmail scopes for the selected
connector.

### Slack

| Variable | Meaning |
|---|---|
| `SLACK_CLIENT_ID` | Self-hosted Slack app client ID. |
| `SLACK_CLIENT_SECRET` | Self-hosted Slack app secret; use a file-backed secret in production. |
| `SLACK_REDIRECT_URI` | OAuth callback URI. Production requires absolute HTTPS when configured. |
| `SLACK_MANAGED_INSTALL_URL` | Optional absolute HTTPS managed OAuth entry point. It can enable a one-click path without local client credentials. |

Either configure the full self-hosted tuple or a managed install URL. Partial
provider tuples fail production validation.

### Zoom

`ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET`, and `ZOOM_REDIRECT_URI` are reserved in
the configuration contract, but Zoom ingestion remains `coming_soon`. Setting
them does not make the connector available.

## Local coding-session locations

| Variable | Meaning |
|---|---|
| `CODEX_HOME` | Override the Codex session/config home used by local discovery and adapter resolution. |
| `CLAUDE_HOME` | Override the Claude Code history home. |
| `OPENCODE_HOME` | Override the OpenCode history home. |
| `DAEMONSTATE_CODEX_EXECUTABLE` | Explicit Codex CLI executable path. When empty, the current desktop-bundled CLI is preferred over a stale npm-global wrapper. |
| `DAEMONSTATE_OPENCODE_MODEL` | Optional OpenCode model fallback used by the local adapter when no operation-specific model is passed. |

These paths are read by the workstation process. Personal Docker cannot see
host-only data unless explicitly mounted, which is not part of the supported
personal profile.

## Script-only advanced controls

These variables control local scripts rather than the FastAPI settings model:

| Variable | Default | Effect |
|---|---|---|
| `DAEMONSTATE_START_WORKER` | `1` | Set to `0` to make `scripts/start.sh` run only the API. |
| `DAEMONSTATE_BACKEND_RELOAD` | `0` | Set to `1` for Uvicorn reload in `scripts/dev.sh`. |
| `DAEMONSTATE_USE_SYSTEM_PYTHON` | `0` | Set to `1` before setup to skip `.venv` creation and use `python3`. |
| `VENV_DIR` | `.venv` | Alternate virtual-environment path used by setup. |
| `PYTHON_BIN` | auto-detected | Interpreter override for start/dev scripts. |
| `DAEMONSTATE_ALLOW_REMOTE_BIND` | `0` | Explicitly acknowledges a non-loopback personal bind. This does not add browser authentication and is not a substitute for the production profile. |
| `DAEMONSTATE_OVERLAY_RUNTIME_DIR` | system temp directory | Absolute directory for native overlay state/control files. |
| `DAEMONSTATE_OVERLAY_SWIFT_CACHE_ROOT` | package build directory | Swift build cache used by `scripts/overlay.sh`. |

Internal runtime bundle variables beginning with
`DAEMONSTATE_EXECUTION_`/`DAEMONSTATE_PACK_` are set by DaemonState for child
processes. They are runtime contracts, not user configuration.

## Production validation

When `ENVIRONMENT=production`, startup fails unless the configuration meets the
security boundary. Among other checks, production requires:

- PostgreSQL and explicit migrations (`AUTO_MIGRATE=false`);
- a 32+ character API key;
- a valid Fernet encryption key;
- positive API/auth rate limits backed by Redis with fail-open disabled;
- explicit hosts and repository roots;
- an HTTPS public base and complete HTTPS OAuth tuples;
- API docs and demo endpoints disabled;
- the browser frontend disabled;
- protected metrics;
- JSON logs; and
- valid database, worker, request-size, and telemetry limits.

Use `deploy/production/production.env.example` only with the pinned-image,
file-secret workflow in [Production runbook](production-runbook.md).
