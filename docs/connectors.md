# Connectors

Connector status must be honest. A connector is launch-available only when the
backend can create `SourceDocument` rows from that provider path and tests cover
the route or sync behavior with mocked provider calls.

## Current Launch Matrix

| Source | Launch status | How data enters | Notes |
|---|---|---|---|
| Local files | Available | `/api/sources/upload`, `/api/sources`, CLI ingest | No credentials required. |
| AI sessions | Available | `/api/connectors/ai-context/import`, `/api/connectors/ai-session/ingest` | Supports Codex, Claude, OpenCode, and generic session text. |
| Slack | Available | OAuth/setup plus sync worker | Requires a Slack app and channel history scopes. |
| GitHub | Available | Personal access token plus issue/PR sync | Deterministic issue/PR extraction creates evidenced graph edges. |
| Gmail | Available | Google OAuth plus mocked sync coverage | Requires Google Cloud OAuth setup. |
| Google Drive | Available | Google OAuth plus mocked sync coverage | Docs become source documents. |
| Discord | Coming soon | No working sync path | Catalog stub only. |
| Zoom | Coming soon | Unsupported sync path | OAuth and manual token setup are disabled until transcript sync is implemented. |
| Wispr Flow | Coming soon | No working sync path | Catalog stub only. |
| Notion | Not catalogued | None | Do not describe as a launch connector. |

See [AI Context](ai-context.md) for the session import schema, metadata
contract, extraction behavior, and current limits.

## State Meanings

| State | Meaning |
|---|---|
| `available` | The connector is a launch path and can create source documents when configured. |
| `coming_soon` | The connector is visible as roadmap/stub only. Actions should not imply sync works. |
| `disconnected` | No workspace connector is currently configured. |
| `connected` | Credentials/config exist for that workspace. This should never be used for demo data alone. |
| `syncing` | A sync job is running or queued. |
| `failed` | The last setup or sync attempt failed with an error payload. |

## Implementation Rules

- Never mark a connector as connected because demo data was seeded.
- Never bypass `SourceDocument`; connector sync must preserve raw source content.
- Connector metadata should include workspace ID, source URL or external ID,
  provider identifiers, and enough display-safe fields for graph inspectors.
- Coming-soon connectors should return honest errors, not placeholder success.
- Keep frontend connector copy aligned with `app/api/connectors.py` and README.

## Demo Seed

`POST /api/seed-demo` is a product demo path, not connector authentication. It
creates source-backed example documents tagged with `demo_seed=true` and a
workspace ID, then processes them synchronously so the Project map, Ask, and MCP
have useful graph data immediately.

Seeded source families:

- GitHub issue
- GitHub pull request
- Slack thread
- Gmail thread
- Google Drive document
- Codex session
