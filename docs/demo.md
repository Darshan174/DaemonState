# Demo Walkthrough

This demo proves the core promise without provider credentials: source-backed
project memory for AI agents, not a workflow canvas or a vector-only knowledge
base.

## Start

```bash
git clone https://github.com/Darshan174/Context-Engine.git context-engine
cd context-engine
cp .env.example .env
bash scripts/doctor.sh --docker
docker compose up --build
```

Seed the demo workspace directly:

```bash
curl -X POST http://localhost:8000/api/seed-demo \
  -H 'content-type: application/json' \
  -d '{}'
```

Then open `http://localhost:8000/app` and select **Context Engine Demo** when
the workspace chooser appears.

The seed creates raw `SourceDocument` rows from launch-available source families:
GitHub issue, GitHub pull request, Slack thread, Gmail thread, Google Drive
document, and Codex session. It also records `your-org/context-engine` as the
demo project boundary through a disconnected GitHub configuration, so the map
opens immediately. It does not store credentials or mark any provider connected.

When running in Docker, the local-path importer sees container paths. Compose
mounts the current checkout read-only at `/workspace` by default. To inspect a
different host project, start with
`CONTEXT_ENGINE_PROJECT_PATH=/absolute/host/path docker compose up --build`,
then enter `/workspace` when connecting the project.

## What To Inspect

1. Open **Explain**. The map places sessions, direction, delivery, and risks in
   one selected-workspace view.
2. Select a node. The inspector shows value, source metadata, provenance,
   confidence, evidence, relationship state, and session relevance reasons.
3. Only source-backed relationships are drawn. Unknown or different-project
   sessions remain visually subdued instead of driving the project story.
4. Open **Memory** to review active, needs-review, and historical project facts.
5. Open `/app/query` and run `What is blocking our launch?`. The answer includes
   retrieval controls, a stable `query.v1` response shape, facts used, and
   relationship expansion evidence.
6. Open **Connectors**. Launch connectors expose backend-backed actions;
   coming-soon providers stay disabled instead of creating fake connected state.

## Verification

Before cutting a public release from this demo path, run:

```bash
bash scripts/smoke.sh --docker
```

The Docker smoke builds the image, starts the app on an alternate port, waits for
health, seeds demo data, verifies graph stats, checks `/api/query`, and confirms
Zoom and Notion setup guardrails cannot create fake connected state.
