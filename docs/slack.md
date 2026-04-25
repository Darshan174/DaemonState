# Slack Setup

Context Engine supports three practical Slack paths:

1. **Slack OAuth app** — best for real self-hosted use and recurring sync.
2. **Slack export ZIP import** — easiest first-time path when you do not want OAuth yet.
3. **Manual bot token** — useful for local experiments, but not the main product path yet.

Use OAuth for production-like installs. Use export ZIPs for quick evaluation.

## Option 1: Slack OAuth App

Slack OAuth needs three environment variables:

```bash
SLACK_CLIENT_ID=
SLACK_CLIENT_SECRET=
SLACK_REDIRECT_URI=http://localhost:8000/api/connectors/slack/callback
```

For a deployed host, replace `localhost:8000` with your public HTTPS origin:

```bash
SLACK_REDIRECT_URI=https://context.example.com/api/connectors/slack/callback
```

### Create The Slack App From A Manifest

1. Open [Slack API Apps](https://api.slack.com/apps).
2. Click **Create New App**.
3. Choose **From an app manifest**.
4. Pick the Slack workspace you want to connect.
5. Paste this manifest.
6. Change the `redirect_urls` value to match your `SLACK_REDIRECT_URI`.
7. Create the app.
8. Open **Basic Information** and copy:
   - **Client ID** -> `SLACK_CLIENT_ID`
   - **Client Secret** -> `SLACK_CLIENT_SECRET`
9. Save the values in `.env`.
10. Restart Context Engine.
11. Go to **Connectors** and click **Connect Slack**.

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

## Option 2: Slack Export ZIP Import

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

## Option 3: Manual Bot Token

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
