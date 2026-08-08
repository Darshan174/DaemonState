# Demo walkthrough

The demo proves the source-first evidence and workspace-isolation paths without
provider credentials. It does not simulate local desktop continuation, create a
fake connected state, or turn sample records into a real repository checkout.

## Start

Use the personal Docker profile:

```bash
git clone https://github.com/Darshan174/DaemonState.git daemonstate
cd daemonstate
bash scripts/self-host.sh
```

Or use the [workstation setup](getting-started.md#workstation-install). Then
seed the sample workspace:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/seed-demo \
  -H 'content-type: application/json' \
  -d '{}'
```

The response includes both `workspaceId` and `workspace_id`. Save that UUID for
the API examples below. Repeating the request is safe: unchanged seed documents
are reused and the response status becomes `ready`.

Example response shape:

```json
{
  "status": "created",
  "workspace_id": "<demo-workspace-uuid>",
  "workspaceName": "DaemonState Demo",
  "createdDocuments": 6,
  "existingDocuments": 0,
  "sourceTypes": [
    "ai_context_codex",
    "github_issue",
    "github_pr",
    "gmail",
    "google_drive",
    "slack"
  ],
  "projectBoundaryCreated": true
}
```

Counts can differ after an earlier seed, but the source identities remain
idempotent.

## What the seed creates

The seed preserves one raw `SourceDocument` for each sample family before
processing it:

- GitHub issue
- GitHub pull request
- Slack thread
- Gmail thread
- Google Drive document
- Codex session

Every record is scoped to the demo workspace and tagged as demo evidence. The
GitHub project boundary is a disconnected connector configuration for
`your-org/daemonstate`; it stores no token and is never reported as connected.
No external provider is contacted.

## Browser tour

1. Open <http://127.0.0.1:8000/app>.
2. Choose **DaemonState Demo** under **Samples**. It is visibly separate from
   real project workspaces.
3. Open workspace management to inspect source, fact, run, and input counts.
4. Open **Library** to see the sample session without confusing it with local
   automatic discovery. Local sync is deliberately skipped for a demo
   workspace.
5. Open **Execute** to observe the explicit boundary: the sample has provider
   evidence but no local repository checkout. Workspace Context must represent
   missing repository proof honestly rather than invent code architecture or a
   passing quality state.

**Evidence**, **Sources**, and **Integrations** are currently covered by an
under-construction overlay. Their backend data exists, but those browser routes
are not part of the supported demo walkthrough yet. Use the APIs below.

Continue is also not a meaningful demo action: it is designed for the newest
eligible local session of a real connected repository and a local desktop app.

## Inspect sources through the API

Replace `<demo-workspace-uuid>` with the ID returned by the seed:

```bash
curl -sS \
  'http://127.0.0.1:8000/api/sources?workspace_id=<demo-workspace-uuid>'
```

Choose one returned source ID to inspect its raw content, metadata, revision,
and extracted components:

```bash
curl -sS \
  'http://127.0.0.1:8000/api/sources/<source-document-uuid>'
```

The detail response demonstrates the core provenance boundary: extracted facts
do not replace the original source.

## Query the demo

```bash
curl -sS -X POST http://127.0.0.1:8000/api/query \
  -H 'content-type: application/json' \
  -d '{
    "workspace_id":"<demo-workspace-uuid>",
    "question":"What is blocking the launch?",
    "retrieval_mode":"indexed"
  }'
```

The response uses the stable `query.v1` shape and includes:

- a bounded answer;
- calibrated confidence;
- ranked components;
- source metadata;
- `trace.facts_used`;
- relationship expansion evidence; and
- the declared retrieval/ranking strategy.

When no answer model or embedder is configured, DaemonState remains explicit
about deterministic/lexical behavior rather than pretending a hashing fallback
is semantic reasoning.

## Inspect graph and stats

```bash
curl -sS \
  'http://127.0.0.1:8000/api/graph?workspace_id=<demo-workspace-uuid>'
```

```bash
curl -sS \
  'http://127.0.0.1:8000/api/stats?workspace_id=<demo-workspace-uuid>'
```

Only relationships returned by the backend are factual. Display zones,
proximity, shared words, and the order of sample records are not inferred
edges.

## Connector honesty checks

```bash
curl -sS \
  'http://127.0.0.1:8000/api/connectors?workspace_id=<demo-workspace-uuid>'
```

Verify that:

- GitHub remains `disconnected` despite seeded issue/PR evidence;
- Slack, Gmail, and Google Drive do not become connected;
- Discord, Zoom, and Wispr Flow remain `coming_soon`; and
- Notion is not present in the catalog.

The demo separates source evidence from provider authentication on purpose.

## Docker repository mount

The default Compose profile mounts this checkout at `/workspace`, read-only.
To inspect a different real host project after the demo, set:

```dotenv
DAEMONSTATE_PROJECT_PATH=/absolute/path/to/project
```

Then rerun:

```bash
bash scripts/self-host.sh
```

Create a separate real workspace and enter `/workspace` as its repository path.
Do not convert the sample workspace into a real project boundary.

## Verification

Before a release, maintainers should run:

```bash
bash scripts/smoke.sh --docker
```

The Docker smoke builds the image, starts a separate Compose project on an
alternate port, waits for migration/API/worker health, seeds the demo, verifies
graph and `query.v1` behavior, and checks that unsupported connector routes
cannot create fake connected state.
