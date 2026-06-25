# AI Context

AI coding-session memory is the primary product wedge.

Context Engine preserves Codex, Claude Code, OpenCode, and generic agent
sessions as raw source evidence, then extracts decisions, tasks, blockers, and
file references. This lets the project carry useful memory from one agent run to
the next instead of starting from a blank prompt every time.

The session ID alone is not enough. Current imports require the session content.
Context Engine does not log in to Codex or Claude and scrape a conversation from
an ID.

## Current Paths

| Path | Current behavior | Use when |
|---|---|---|
| `POST /api/connectors/ai-session/ingest` | Creates or updates one `agent_session` source document, processes it immediately, and updates the selected Codex/Claude/OpenCode connector summary. | Importing from the Connectors UI or a script for a workspace. |
| `POST /api/connectors/ai-context/import` | Creates one or more raw `SourceDocument` rows with `ai_context_*` source types. Graph extraction happens later through normal processing/build paths. | Bulk-loading exported sessions, plans, reviews, or handoff notes. |

Both paths are source-first. They do not create graph facts without preserving
the raw session content.

## Supported Tools

| Tool value | Stored source type | Notes |
|---|---|---|
| `codex` | `ai_context_codex` | First-class in catalog and frontend session import. |
| `claude` / `claude_code` | `ai_context_claude_code` | First-class in catalog and frontend session import. |
| `opencode` / `open_code` | `ai_context_opencode` | First-class in catalog and frontend session import. |
| Any other value, including Cursor exports today | `ai_context` | Stored as generic AI context. Do not describe Cursor as first-class until it has catalog/test coverage. |

The frontend also exposes dedicated Codex, Claude, and OpenCode session cards.
`ai_context` remains the generic import bucket for plans, diffs, reviews, and
other agent notes.

## Import Examples

Immediate workspace session ingest:

```bash
curl -X POST http://localhost:8000/api/connectors/ai-session/ingest \
  -H 'content-type: application/json' \
  -d '{
    "workspace_id": "00000000-0000-0000-0000-000000000000",
    "connector_type": "codex",
    "session_id": "launch-polish-001",
    "content": "Decision: keep Board as default\nNext step: add smoke tests\nRisk: connector claims must stay honest"
  }'
```

Bulk raw AI-context import:

```bash
curl -X POST http://localhost:8000/api/connectors/ai-context/import \
  -H 'content-type: application/json' \
  -d '{
    "documents": [
      {
        "external_id": "codex-plan-2026-06-18",
        "tool": "codex",
        "session_type": "plan",
        "session_id": "launch-plan",
        "author": "darshan",
        "source_url": "https://example.com/session",
        "metadata": {
          "branch": "launch/oss-polish",
          "commit": "abc123"
        },
        "content": "Decision: use source-backed Board clusters\nTodo: verify frontend smoke coverage"
      }
    ]
  }'
```

## Metadata Contract

`/api/connectors/ai-context/import` preserves:

- `external_id`
- `author`
- `source_url`
- `tool`
- `session_type`
- `session_id`
- `started_at`
- `ended_at`
- custom `metadata` fields such as `branch`, `commit`, `model`,
  `source_path`, or `title`

It also adds `ingested_via: "ai_context_import"` to source metadata.

`/api/connectors/ai-session/ingest` stores:

- `session_id`
- `connector_type`
- `message_count`
- `workspace_id`
- ingestion timestamp

## Extracted Graph Facts

The deterministic agent-session extractor currently creates:

- an `Agent Session` root component for the imported session
- future `Task` facts from explicit next steps, todos, actions, and task bullets
- `Decision` facts from explicit decision/recommendation/verdict language and
  final/summary/conclusion sections
- `Risk` facts from blockers, concerns, open questions, and failures
- `Repo` file-reference facts for code/document paths mentioned in the session

Relationships are evidence-backed:

- tasks, decisions, and risks link back to the session with
  `generated_by_agent`
- file references link back to the session with `part_of`

Generic narration is intentionally not treated as a high-confidence fact.

## Verification

Relevant tests:

- `tests/test_connectors.py` covers AI-context import, subtype normalization,
  metadata preservation, unknown-tool normalization, processing summaries, and
  session ingest.
- `tests/test_ingestion.py` and `tests/test_adversarial_graph.py` cover
  source-first extraction, provenance, temporal state, and relationship safety.

Recommended local checks:

```bash
python3 -m pytest tests/test_connectors.py -q
python3 -m pytest tests/test_ingestion.py tests/test_adversarial_graph.py -q
```

## Current Limits

- A session ID identifies and deduplicates a session; it does not fetch content.
- Users must paste, upload, or otherwise provide the session content.
- Cursor is accepted only as generic AI context today.
- Imports do not fetch referenced files automatically.
- `/api/connectors/ai-context/import` creates raw source documents; run graph
  build or processing before expecting extracted components.
- Timestamps are stored from provided metadata but there is no dedicated session
  replay UI yet.
