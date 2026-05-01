# Agent Rules

Permanent repository rules for Codex and OpenCode agents working on Context Engine.

## Mission

Context Engine is an open source developer tool for turning scattered product, startup, and AI-agent context into a precise, source-backed knowledge graph.

The main product value is:

- seamless ingestion from local files, AI-agent sessions, and future work surfaces such as Slack, Discord, Gmail, meeting transcripts, and docs;
- durable extraction into source documents, models, components, and optional relationships;
- provenance for every extracted component;
- clear current, past, and future context for product and engineering decisions.

## Agent Roles

- Codex: architect, task splitter, final reviewer, integration owner.
- Kimi K2.6: task planner, contract writer, multi-agent coordinator.
- GLM 5.1: primary implementation agent.
- Qwen: graph reasoning checker, schema/data model reviewer, hard bug solver.
- Xiaomi MiMo V2.5 Pro: long-context repo reader, docs/UX/OSS readiness reviewer.

## Collaboration Workflow

1. Codex writes or updates `TASK_PLAN.md` and `.agent-runs/*-task.md`.
2. Kimi writes or refreshes the contract before implementation when the scope is ambiguous.
3. GLM and Qwen work on separate implementation/reasoning slices.
4. Xiaomi reviews the resulting code and docs for OSS clarity and hallucinated claims.
5. Codex reviews all diffs, resolves conflicts, verifies tests/builds, and decides what merges.

## Anti-Hallucination Rules

- Separate `Observed`, `Implemented`, `Proposed`, and `Not implemented yet` claims.
- Cite files, functions, endpoints, or tests for current behavior.
- Do not claim a connector works unless there is a tested endpoint and source-document ingestion path.
- Do not claim external provider support without a named authentication mode and tested API behavior.
- Relationships are optional. Create them only from explicit source evidence or a deterministic rule.
- Every final report must include changed files, tests run, evidence, risks, and remaining gaps.

## Repository Rules

- Do not revert unrelated user changes.
- Keep edits scoped to the current task file.
- Prefer existing FastAPI, SQLAlchemy, React Query, and frontend patterns.
- Keep connector ingestion source-first: raw `SourceDocument` rows come before extraction.
- Preserve provenance in metadata and graph responses.
- Keep unsupported providers honest: use `coming_soon`, `disconnected`, or explicit unsupported errors.
- Add focused tests for backend behavior and run the relevant suite before reporting done.

## Knowledge Graph Vocabulary

- SourceDocument: raw ingested content with source type, external ID, content, author, URL, metadata, and timestamps.
- Model: a domain bucket such as `Pricing`, `Roadmap`, `Connectors`, `AI Context`, or `Security`.
- Component: one atomic fact inside a model, with value, confidence, status, provenance, and optional embedding.
- Relationship: optional typed edge between two components, such as `depends_on`, `blocked_by`, `enables`, `contradicts`, `supersedes`, `confirms`, or `related_to`.
- Connector: a configured or catalogued ingestion surface.
- SyncJob: a connector sync attempt or status record.

