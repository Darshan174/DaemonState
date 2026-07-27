# Contributing

DaemonState is source-backed project memory for AI agents. Contributions
should preserve the core contract: raw `SourceDocument` rows first, extracted
facts second, relationships only with evidence, and honest connector states.

The project is temporarily not accepting outside code or documentation
contributions because it does not yet have a contributor license agreement.
Bug reports and product feedback are welcome, but please do not attach patches
or other copyrighted implementation material unless a maintainer confirms that
a lawyer-reviewed contributor agreement is in place.

The workflow below is for maintainers and contributors already covered by a
separate written agreement.

## Local Setup

Prerequisites: Python 3.12+, npm, and Node.js 20.19+ on the 20.x line,
22.13+ on the 22.x line, or 24+.

```bash
bash scripts/doctor.sh --bare-metal
bash scripts/setup.sh
bash scripts/dev.sh
```

Backend: <http://localhost:8000>
Frontend: <http://localhost:5000>

`scripts/setup.sh` creates `.venv`, installs backend dev dependencies there,
uses `npm ci` for the frontend, and builds the production frontend bundle.
`scripts/dev.sh` and `scripts/smoke.sh` automatically use `.venv/bin/python`
when it exists.

For the PostgreSQL/pgvector path, run `bash scripts/self-host.sh`. Provider
credentials are optional for the seeded demo and should stay in the untracked,
permission-restricted `.env` file.

## Before Opening A PR

Run the same checks as CI:

```bash
bash scripts/smoke.sh
```

Maintainers should also run `bash scripts/smoke.sh --docker` before public
release tags.

If a check cannot be run locally, call that out in the PR.

## Product Rules

- Keep the knowledge graph source-backed. Do not add workflow-pipeline nodes
  such as Input, LLM, KB, or Output to the graph.
- Do not claim a connector works unless auth, sync, `SourceDocument` ingestion,
  and tested behavior are present.
- Keep unsupported connectors as `coming_soon`, `disconnected`, or explicit
  unsupported errors.
- Put confidence, temporal status, provenance, and trust metadata in inspectors
  and traces rather than as noisy default canvas styling.
- Prefer deterministic extraction and relationship evidence over broad LLM
  inference.

## Code Style

- Backend: FastAPI, async SQLAlchemy, Pydantic, and the existing service/router
  split.
- Frontend: React, TanStack Query patterns, Tailwind utility classes, and
  existing project-map helpers in `frontend/src/context-map`.
- Tests should be focused and close to the behavior changed.
