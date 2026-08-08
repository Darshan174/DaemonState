# Connectors

DaemonState uses connectors to create immutable, workspace-scoped source
revisions. Connector status must stay honest: an entry is available only when a
tested backend path can preserve provider content as `SourceDocument` rows.

> The top-level **Integrations** browser route is currently under construction.
> The backend endpoints and worker paths described here are available, but the
> covered UI is not a supported onboarding workflow yet. Configure connectors
> through environment/API paths until that gate is removed.

## Current matrix

| Source | Backend status | Setup and ingestion | Current boundary |
|---|---|---|---|
| Local repository | Available | `POST /api/repo/index`, CLI `repo index`, optional watcher | Reads a bounded project root; Docker mount is read-only. Indexing does not run project commands. |
| Local files/uploads | Available | `POST /api/sources`, `/sources/bulk`, `/sources/upload`, CLI `ingest` | Text-decodable content is preserved before extraction. |
| Codex | Available | Automatic workstation discovery, session ingest/import APIs | Project-scoped local history; not fetched from a session ID alone. |
| Claude Code | Available | Automatic workstation discovery, session ingest/import APIs | Normalized to provider `claude`; not fetched from an ID alone. |
| OpenCode | Available | Automatic workstation discovery, session ingest/import APIs | Project-scoped local history; no MCP support in the execution adapter. |
| Generic AI Context | Available | `POST /api/connectors/ai-context/import` | Plans, diffs, reviews, or unsupported agent exports remain generic evidence. |
| GitHub | Available | Personal access token plus explicit `owner/repo` targets | Syncs issues and pull requests through the worker; live retrieval also requires configured access. |
| Slack | Available | Self-hosted Slack OAuth tuple or managed install URL | Syncs channels, DMs, and thread history permitted by the installed app scopes. |
| Gmail | Available | Google OAuth with Gmail read-only scope | Syncs authorized email content through the worker. |
| Google Drive | Available | Google OAuth with Drive read-only scope | Syncs authorized Docs/Sheets/Slides/folder content through the worker. |
| Discord | Coming soon | No supported sync path | Catalog entry only. |
| Zoom | Coming soon | Setup/sync routes reject availability | Reserved OAuth settings do not enable transcript ingestion. |
| Wispr Flow | Coming soon | No supported sync path | Catalog entry only. |
| Notion | Not catalogued | Compatibility setup route rejects the request | Do not present Notion as a current or coming-soon connector. |

“Available” does not mean credentials are configured, a workspace connector is
connected, or the browser onboarding flow is finished.

## State meanings

| State | Meaning |
|---|---|
| `available` | Catalog capability: a tested backend path exists. This is not a live connection state. |
| `coming_soon` | No supported ingestion path exists. Actions must remain disabled or return an explicit unsupported error. |
| `disconnected` | No usable workspace credential/configuration is active. |
| `connected` | Credentials/configuration exist for that workspace. It does not imply the last sync succeeded. |
| `pending` / `retrying` | A sync job is waiting for a worker or its next retry. |
| `syncing` / `running` | A worker holds the current lease. |
| `failed` | The last attempt failed but has not necessarily exhausted retries. |
| `dead_letter` | Retry policy was exhausted or the job needs explicit operator redrive. |

Demo content never changes a connector to `connected`.

## Source-first contract

Every connector must:

1. authenticate/configure without storing plaintext display data;
2. create or update one stable source identity;
3. append an immutable source revision when provider content changes;
4. commit raw source content before projection;
5. attach workspace, external/provider identity, source URL when available,
   timestamps, and display-safe metadata;
6. process the current revision through deterministic or bounded extraction;
7. create only evidence-backed facts/relationships; and
8. remain idempotent under at-least-once job delivery.

Provider snapshots are not live provider state. An imported “open” issue or
message timestamp remains a source observation unless item-level freshness is
proved.

## Worker behavior

`POST /api/connectors/{connector_id}/sync` queues a database job. The sync
worker:

- claims jobs with a lease and unique claim token;
- heartbeats during long work;
- applies bounded per-job timeouts;
- retries with bounded backoff;
- conditionally completes only while it still owns the lease; and
- keeps source ingestion recoverable when projection is interrupted.

A stale worker cannot finalize a job that another worker reclaimed. The worker
is still at-least-once, so provider adapters must deduplicate using stable
external IDs and source revision hashes.

Run once:

```bash
daemonstate worker sync --limit 10 --json
```

Run continuously:

```bash
daemonstate worker sync --watch
```

Explicitly redrive unfinished source-ingestion dead letters:

```bash
daemonstate worker sync --redrive-dead-letter --json
```

## Local AI sessions

Library discovers local Codex, Claude Code, and OpenCode histories from their
default locations or `CODEX_HOME`, `CLAUDE_HOME`, and `OPENCODE_HOME`.

Discovery:

- runs as the DaemonState workstation user;
- excludes internal/system sessions;
- derives display-safe session summaries and compaction descriptors;
- filters sessions against the workspace's repository scope;
- creates or revises `agent_session` source documents; and
- processes newly changed sessions into source-backed facts.

Continue uses a narrower latest-session endpoint so it can resolve the newest
eligible session without waiting for the entire Library. Docker cannot see
host-only history under the supported personal profile.

Manual session ingest:

```bash
curl -X POST http://127.0.0.1:8000/api/connectors/ai-session/ingest \
  -H 'content-type: application/json' \
  -d '{
    "workspace_id":"<workspace-uuid>",
    "connector_type":"codex",
    "session_id":"session-001",
    "content":"Decision: keep ingestion source-first."
  }'
```

The session content is required. An ID is only identity/deduplication unless a
local provider adapter can resolve the actual history.

## GitHub

Connect with a personal access token and explicit repository targets:

```http
POST /api/connectors/github/connect
```

The token is encrypted at rest. Sync imports issue and pull-request content,
metadata, comments/review context supported by the adapter, and deterministic
issue/PR relationships. Use the least privilege that supports read access to
the selected repositories. Repository code itself still comes from local
indexing or live GitHub retrieval; issue/PR ingestion does not create a writable
checkout.

## Slack

Self-hosted OAuth requires:

```dotenv
SLACK_CLIENT_ID=...
SLACK_CLIENT_SECRET=...
SLACK_REDIRECT_URI=http://127.0.0.1:8000/api/connectors/slack/callback
```

Alternatively configure an absolute HTTPS `SLACK_MANAGED_INSTALL_URL`. OAuth
state is encrypted, short-lived, single-use, and connector-bound. Disconnect
attempts token revocation before removing the local connector record.

The exact Slack scopes depend on the app manifest and content you intend to
sync. Do not broaden them beyond the workspace's required channel/DM history.

## Gmail and Google Drive

Both use the same Google OAuth client:

```dotenv
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/api/connectors/google/callback
```

The selected install route requests the corresponding read-only Gmail or Drive
scope. Configure the full client ID/secret/redirect tuple. Production redirects
must be absolute HTTPS URLs.

## Credential storage and rotation

Connector secrets are encrypted with `ENCRYPTION_KEY`. Rotate by placing older
keys in `PREVIOUS_ENCRYPTION_KEYS`, setting the new primary key, then running:

```bash
daemonstate credentials rotate
```

Keep prior keys until rotation and restore verification succeed. The production
profile loads secrets from mounted files and validates every stored connector
credential before reporting readiness.

## Demo seed

`POST /api/seed-demo` creates source-backed GitHub, Slack, Gmail, Google Drive,
and Codex examples tagged as demo data. It does not store credentials, call a
provider, or mark any connector connected. The endpoint is disabled in
production.

## Implementation rules

- Never skip `SourceDocument` and write provider-derived graph facts directly.
- Never mark a connector connected because demo rows exist.
- Never turn `coming_soon` into placeholder success.
- Never treat a provider snapshot as current without freshness evidence.
- Never expose decrypted credentials in API responses, logs, traces, or job
  errors.
- Apply workspace/source authorization before projection or retrieval.
- Keep the backend catalog, frontend catalog, README, and this matrix aligned.

For session-specific metadata and extraction, see [AI Context](ai-context.md).
For all connector environment settings, see [Configuration](configuration.md).
