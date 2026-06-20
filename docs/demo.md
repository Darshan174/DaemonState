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

Open `http://localhost:8000`, then click **Run Demo Workspace** in onboarding.
You can also seed directly:

```bash
curl -X POST http://localhost:8000/api/seed-demo \
  -H 'content-type: application/json' \
  -d '{}'
```

The seed creates raw `SourceDocument` rows from launch-available source families
only: GitHub issue, GitHub pull request, Slack thread, Gmail thread, Google
Drive document, and Codex session. It does not mark any provider connector as
authenticated or connected.

## What To Inspect

1. Open **Graph**. Board is the default view and groups facts by source family.
2. Select any node or edge. The right inspector shows value, source metadata,
   provenance, confidence, evidence, and relationship review state.
3. Switch to **Explore** for an Obsidian-style local graph. Orphans are hidden by
   default, and the local graph panel can expand one or two hops.
4. Open **Ask** and run `What is blocking our launch?`. The answer includes
   retrieval controls, a stable `query.v1` response shape, facts used, and
   relationship expansion evidence.
5. Open **Connectors**. Launch connectors expose backend-backed actions;
   coming-soon providers stay disabled instead of creating fake connected state.

## Screenshots

Board keeps the canvas quiet and puts trust detail in the inspector:

![Board graph with relationship inspector](assets/board-inspector-demo.jpg)

Ask shows the retrieval trace agents can audit:

![Ask UI with facts-used trace](assets/query-trace-demo.jpg)

## Verification

Before cutting a public release from this demo path, run:

```bash
bash scripts/smoke.sh --docker
```

The Docker smoke builds the image, starts the app on an alternate port, waits for
health, seeds demo data, verifies graph stats, checks `/api/query`, and confirms
Zoom and Notion setup guardrails cannot create fake connected state.
