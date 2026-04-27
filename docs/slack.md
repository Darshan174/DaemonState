# Slack Setup

Context Engine supports three practical Slack paths:

1. **Managed Slack app** — Codex-style UX: click Connect, review permissions, continue to Slack.
2. **Self-hosted Slack OAuth app** — best for OSS installs without a hosted broker.
3. **Slack export ZIP import** — easiest first-time path when you do not want OAuth yet.
4. **Manual bot token** — useful for local experiments, but not the main product path yet.

Use OAuth for production-like installs. Use export ZIPs for quick evaluation.

## Option 1: Managed Slack App

This is the same product shape as Codex:

1. User clicks **Connect Slack**.
2. Context Engine shows a short permission review modal.
3. User continues to Slack and signs into a workspace.

This requires a hosted Context Engine Slack app because the Slack app client
secret cannot be shipped in an open-source repo or browser bundle. Configure the
self-hosted app to use your hosted connector broker:

```bash
SLACK_MANAGED_INSTALL_URL=https://connect.context.example/slack/install
```

When this is set, the Connectors page uses the managed install path first. The
self-hosted Client ID / Client Secret form remains available only as an
advanced fallback.

## Option 2: Self-hosted Slack OAuth App

Slack OAuth needs one Slack app and three values from that app:

```bash
SLACK_CLIENT_ID=
SLACK_CLIENT_SECRET=
SLACK_REDIRECT_URI=http://localhost:8000/api/connectors/slack/callback
```

For a deployed host, replace `localhost:8000` with your public HTTPS origin:

```bash
SLACK_REDIRECT_URI=https://context.example.com/api/connectors/slack/callback
```

### Recommended: Save Credentials In The Dashboard

This is the closest self-hosted flow to a one-click Slack connector.

1. Create the Slack app from the manifest below.
2. Open **Basic Information** in Slack and copy the **Client ID** and
   **Client Secret**.
3. Open Context Engine -> **Connectors**.
4. Click **Set up Slack OAuth**.
5. Paste the Client ID, Client Secret, and Redirect URL.
6. Click **Save Slack settings**.
7. Click **Connect Slack**.

Context Engine stores the Slack app secret encrypted in the database. This
requires `ENCRYPTION_KEY` to be configured on the backend. Workspace install
tokens are still created through Slack OAuth and stored separately per
workspace.

### Operator Alternative: Environment Variables

Operators can still set the same values in `.env` instead of saving them from
the dashboard:

```bash
SLACK_CLIENT_ID=
SLACK_CLIENT_SECRET=
SLACK_REDIRECT_URI=http://localhost:8000/api/connectors/slack/callback
```

Restart Context Engine after editing `.env`.

### Create The Slack App From A Manifest

1. Open [Slack API Apps](https://api.slack.com/apps).
2. Click **Create New App**.
3. Choose **From an app manifest**.
4. Pick the Slack workspace you want to connect.
5. Paste this manifest.
6. Change the `redirect_urls` value to match your `SLACK_REDIRECT_URI`.
7. Create the app.
8. Open **Basic Information** and copy:
   - **Client ID**
   - **Client Secret**
9. Save the values in the Context Engine dashboard or `.env`.
10. Go to **Connectors** and click **Connect Slack**.

```yaml
display_information:
  name: Context Engine
  description: Source-backed company memory for AI systems
  background_color: "#111827"
features:
  bot_user:
    display_name: Context Engine
    always_online: false
oauth_config:
  redirect_urls:
    - http://localhost:8000/api/connectors/slack/callback
  scopes:
    bot:
      - channels:history
      - channels:read
      - groups:history
      - groups:read
      - users:read
settings:
  org_deploy_enabled: false
  socket_mode_enabled: false
  token_rotation_enabled: false
```

### What The Scopes Are For

| Scope | Purpose |
| --- | --- |
| `channels:read` | List public channels the bot can access |
| `channels:history` | Read public channel messages |
| `groups:read` | List private channels the bot has been invited to |
| `groups:history` | Read private channel messages where the bot is present |
| `users:read` | Resolve Slack user IDs into readable authors |

Private channels only sync after the bot is invited to those channels.

### Restart

With Docker Compose:

```bash
docker compose up -d --build api worker
```

Then open:

```text
http://localhost:8000/app/connectors
```

## Option 3: Slack Export ZIP Import

Use this when you want to evaluate Context Engine without creating a Slack app.

1. Export Slack data from Slack.
2. Keep the export as a `.zip`.
3. Put the file somewhere the backend can read.
4. Trigger a local import with import type `slack_export`.

The backend importer understands Slack export ZIPs and stores messages as source
documents. This path is good for demos, migration testing, and offline review.

Limitations:

- It is not continuous sync.
- Export availability depends on Slack workspace plan and admin permissions.
- It will not refresh automatically after new Slack messages appear.

## Option 4: Manual Bot Token

Manual bot token setup is useful for local connector experiments, but OAuth is
the recommended app path because it gives each workspace a proper install flow.

If you are experimenting locally, create a Slack app, install it to your
workspace, copy the bot token (`xoxb-...`), and use it in code paths that accept
a connector token. The user-facing Connectors page currently expects OAuth for
Slack workspace connection.

## Troubleshooting

### Connect Slack says OAuth is not configured

Check `.env` has all three values:

```bash
SLACK_CLIENT_ID=
SLACK_CLIENT_SECRET=
SLACK_REDIRECT_URI=
```

Restart the API and worker after editing `.env`.

### Slack says redirect_uri did not match

The URL in Slack's app manifest must exactly match `SLACK_REDIRECT_URI`.

These are different:

```text
http://localhost:8000/api/connectors/slack/callback
https://localhost:8000/api/connectors/slack/callback
```

### Sync returns missing_scope

Add the scopes from the manifest, reinstall the Slack app, then reconnect Slack
from Context Engine.

### Private channels are missing

Invite the Slack bot to the private channel, then run another sync.

### The app connects but no source documents appear

Run a sync from the Slack connector card, then inspect **Sources**.
