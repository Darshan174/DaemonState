# MCP

Context Engine ships a Model Context Protocol server so AI coding agents can ask
for source-backed project memory without scraping the UI.

Observed current behavior: MCP runs over stdio through `ctxe mcp` and reads the
same database as the FastAPI app.

Implemented in this branch: MCP acts as the runtime observation bridge for the
Context Compiler v2 loop: let the agent work, observe the run, ingest
observations as source evidence, and improve later context.

Current checkout: `prepare_task` is registered and imports Agent 3's
`ContextCompiler` service when that in-progress module is present. If a branch
does not have the compiler service yet, `prepare_task` returns a structured
`compiler_unavailable` error instead of inventing compiler logic inside MCP.

## Start The Server

```bash
ctxe mcp
```

Claude Desktop style config:

```json
{
  "mcpServers": {
    "context-engine": {
      "command": "ctxe",
      "args": ["mcp"]
    }
  }
}
```

The MCP server reads the same database as the FastAPI app.

## Copy-Paste Examples

Example configs live in [examples/mcp](../examples/mcp/):

- [installed-cli.json](../examples/mcp/installed-cli.json) for environments
  where `ctxe` is already on `PATH`.
- [local-checkout.json](../examples/mcp/local-checkout.json) for a cloned repo
  after `bash scripts/setup.sh`; replace the placeholder command with the
  absolute path to `.venv/bin/ctxe`.
- [agent-system-prompt.md](../examples/mcp/agent-system-prompt.md) for agents
  that should query Context Engine before planning or editing code.

Most MCP clients expose a JSON config with a `command` and `args` field. If your
client uses a different wrapper, keep the same executable behavior:
`ctxe mcp` over stdio.

## Tools

| Tool | Purpose |
|---|---|
| `prepare_task` | When the compiler service is importable, compile and persist a `context_pack.v2` markdown pack plus manifest by calling that service. If the service is absent, return `compiler_unavailable`. |
| `query_context` | Ask the graph with the stable `query.v1` trace contract. |
| `search_nodes` | Rank matching graph components. |
| `expand_graph` | Return a component plus one-hop relationship neighbors. |
| `get_model` | Browse components in a named model. |
| `list_models` | List available graph models and counts. |
| `get_status` | Count sources, models, components, and relationships. |
| `record_agent_run_start` | Create an `AgentRun` linked to a prepared context pack. |
| `record_agent_event` | Store a command, test, log, or other event as `SourceDocument` plus `RunObservation`. |
| `record_decision` | Store an observed decision as source evidence and a conservative claim/component projection. |
| `record_blocker` | Store an observed blocker as source evidence and a conservative blocker claim/component projection. |
| `record_patch_summary` | Store changed files, summary, and tests run as source evidence. |
| `verify_context_item` | Update a component or claim review status with verification evidence. |
| `close_task` | Mark a task component or claim resolved with resolution and commit evidence. |

Security rule: no MCP tool edits code, runs shell commands, pushes commits,
sends provider messages, or mutates external services.

Trust rule: quoted source text from Slack, email, Drive, web, uploads, logs, and
agent observations is evidence, not instruction. Tool descriptions warn clients
to treat quoted evidence as untrusted project data.

## prepare_task Contract

Final contract: `prepare_task` accepts `goal`, `workspace_id`, `repo_path`,
`target_model`, and `token_budget`.

Fallback behavior: if Agent 3's `app/services/context_compiler.py` service is
not present on an integration branch, `prepare_task` returns:

```json
{
  "ok": false,
  "error": {
    "code": "compiler_unavailable",
    "message": "ContextCompiler service is not importable, so MCP cannot compile a durable context_pack.v2 yet.",
    "retryable": true
  }
}
```

Implemented guardrail: when the compiler service is present, MCP calls
`ContextCompiler` directly and verifies before returning that:

- the returned `context_pack_id` loads as a durable `ContextPack` row;
- stored `ContextPack.manifest` equals the returned final manifest;
- stored `ContextPack.markdown` equals the returned final markdown.

The successful output remains:

- `context_pack_id`
- `schema_version`
- `markdown`
- `manifest`
- `health_score`

`context_pack.v2` is two artifacts: human-readable markdown and a
machine-readable manifest. The manifest includes the objective, target model
profile, repo state, selected context, excluded context, risks, verification
commands, stop conditions, and rendering metadata.

The returned manifest must follow [Context Pack v2](context-pack-v2.md):

- use `context_pack_id`, not `pack_id`;
- use `created_at`, not `generated_at`;
- use selected/excluded item `item_type`, not `type`;
- include `rendering.markdown_sha256`, `rendering.estimated_tokens`,
  `rendering.estimation_method`, and `persistence`;
- include final citation objects with `source_document_id`,
  `evidence_span_id`, `path`, `quote_sha256`, and `trust_zone`;
- set `persistence.mode = "database"` and `persistence.committed = true`.

Not implemented or not final yet in this checkout:

- the compiler manifest still must be aligned to the final
  [Context Pack v2](context-pack-v2.md) schema;
- `ContextPackItem` rows still need final selected-item audit fields populated
  and validated against the Agent 1 contract;
- stable idempotency keys for repeated `prepare_task` calls.

## Runtime Observation Contract

Implemented in this branch:

- `record_agent_run_start` creates `AgentRun`.
- `record_agent_event` creates `SourceDocument` and `RunObservation`.
- `record_decision` creates source evidence, a claim, and a component projection.
- `record_blocker` creates source evidence, a claim, and a component projection.
- `record_patch_summary` stores patch summary evidence.
- `verify_context_item` updates claim/component status with source evidence.
- `close_task` marks a claim or legacy component resolved with source evidence.

Not implemented yet:

- deduplication/idempotency keys for runtime write tools;
- provider-backed reranking for large deployments;
- external provider writes from MCP, intentionally.

## Query Contract

`query_context` accepts:

- `query`: natural-language question.
- `top_k`: number of top facts to retrieve, default 8.
- `min_confidence`: lower bound for component confidence, default 0.0.
- `hybrid`: whether to combine embedding similarity and lexical overlap,
  default true.

It returns the same shape as `/api/query`:

- `schema_version: "query.v1"`
- answer text
- retrieved components
- relationship expansion
- `trace.facts_used`
- `trace.relationships_used`
- `trace.ranking_strategy` and reranker feature scores for each used fact

Agents should cite facts from the trace instead of inventing missing context.

## Current Limits

- SQLite/bare-metal retrieval scans active components after SQL filters, which
  is acceptable for local installs.
- Docker Compose and production deployments use Postgres/pgvector plus full-text
  candidate retrieval, followed by deterministic reranking.
- Larger public deployments may still need provider-backed rerankers and
  pagination around graph expansion.
- MCP remains a bridge over the structured graph and source ledger, not a
  separate memory store.

## Context Compiler v2 MCP Contract

Status: final Agent 1 MCP contract for Context Compiler v2. The runtime write
tools above are present in this checkout, and `prepare_task` has import-safe
error handling plus durability validation for future compiler results. Agent 4
must align MCP implementation, docs, and evals to the final manifest contract in
[Context Pack v2](context-pack-v2.md), including idempotency keys when schema
support exists.

v2 keeps the existing read tools and adds an agent runtime bridge for preparing
context and recording what happened during an agent run. v2 adds no dangerous
tools: no code edits, no shell commands, no git pushes, and no provider writes.

### Shared Error Shape

All v2 tools return either the documented output or:

```json
{
  "ok": false,
  "error": {
    "code": "invalid_input",
    "message": "Human-readable error",
    "retryable": false
  }
}
```

Common error codes:

- `invalid_input`
- `not_found`
- `workspace_not_found`
- `context_pack_not_found`
- `agent_run_not_found`
- `schema_missing`
- `compiler_unavailable`
- `conflict`
- `permission_denied`
- `internal_error`

### prepare_task

Purpose: compile and persist a `context_pack.v2` for an agent objective.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "workspace_id": {"type": ["string", "null"]},
    "goal": {"type": "string"},
    "repo_path": {"type": ["string", "null"]},
    "target_model": {"type": "string"},
    "token_budget": {"type": ["integer", "null"]},
    "branch": {"type": ["string", "null"]},
    "base_commit": {"type": ["string", "null"]},
    "idempotency_key": {"type": ["string", "null"]}
  },
  "required": ["goal", "target_model"]
}
```

Output schema:

```json
{
  "ok": true,
  "context_pack_id": "uuid",
  "schema_version": "context_pack.v2",
  "markdown": "string",
  "manifest": {},
  "health_score": 0.87
}
```

Side effects:

- Source document: none by default. If the user objective is not already stored,
  implementation may create a `SourceDocument` of source type `mcp_prepare_task`
  with `trust_zone = "trusted_human"`.
- Claim/component: none directly. The compiler reads claims/components and
  persists `ContextPack` plus `ContextPackItem` rows.
- Trust zone: generated instructions are `trusted_system`; user objective is
  `trusted_human`; quoted evidence keeps original trust.
- Manifest: must use the final `context_pack.v2` field names and persistence
  metadata from `docs/context-pack-v2.md`.
- Idempotency: if `idempotency_key` and repo state match an existing pack,
  return the existing pack.

Errors:

- `invalid_input` for empty goal or invalid token budget.
- `compiler_unavailable` when Agent 3's compiler service is absent.
- `schema_missing` when v2 persistence tables are unavailable.
- `internal_error` for compiler failures.

### record_agent_run_start

Purpose: start an observed agent run that used, or plans to use, a context pack.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "workspace_id": {"type": ["string", "null"]},
    "context_pack_id": {"type": ["string", "null"]},
    "tool": {"type": "string"},
    "model": {"type": ["string", "null"]},
    "objective": {"type": "string"},
    "branch": {"type": ["string", "null"]},
    "base_commit": {"type": ["string", "null"]},
    "idempotency_key": {"type": ["string", "null"]}
  },
  "required": ["tool", "objective"]
}
```

Output schema:

```json
{"ok": true, "agent_run_id": "uuid", "status": "running"}
```

Side effects:

- Source document: creates `SourceDocument(source_type = "agent_run_start")`
  containing the run metadata.
- Claim/component: creates or updates a `run_event` claim/component only if
  Agent 2 projection support is available; otherwise records source only.
- Trust zone: `trusted_system` for metadata generated by Context Engine.
- Idempotency: same `idempotency_key` returns the existing run.

Errors:

- `context_pack_not_found` when a provided pack ID does not exist.
- `conflict` when idempotency key matches a different objective/tool.

### record_agent_event

Purpose: append a command, test, log, file observation, or note to an agent run.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "agent_run_id": {"type": "string"},
    "event_type": {"type": "string"},
    "content": {"type": "string"},
    "files": {"type": "array", "items": {"type": "string"}},
    "command": {"type": ["string", "null"]},
    "exit_code": {"type": ["integer", "null"]},
    "occurred_at": {"type": ["string", "null"]},
    "idempotency_key": {"type": ["string", "null"]}
  },
  "required": ["agent_run_id", "event_type", "content"]
}
```

Valid `event_type`:

- `command`
- `test`
- `log`
- `file_observation`
- `tool_output`
- `note`

Output schema:

```json
{"ok": true, "run_observation_id": "uuid", "source_document_id": "uuid"}
```

Side effects:

- Source document: creates `SourceDocument(source_type = "agent_event")` with
  raw event content and metadata.
- Claim/component: command/test failures may project to `risk` or
  `verification` claims; successful tests may project to `verification`.
- Trust zone: `semi_trusted_tool`.
- Idempotency: same `(agent_run_id, idempotency_key)` returns the existing
  observation.

Errors:

- `agent_run_not_found`.
- `invalid_input` for unknown event type or empty content.

### record_decision

Purpose: record an explicit decision discovered or made during an agent run.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "agent_run_id": {"type": ["string", "null"]},
    "workspace_id": {"type": ["string", "null"]},
    "decision": {"type": "string"},
    "rationale": {"type": ["string", "null"]},
    "files": {"type": "array", "items": {"type": "string"}},
    "evidence": {"type": ["string", "null"]},
    "made_by": {"type": ["string", "null"]},
    "idempotency_key": {"type": ["string", "null"]}
  },
  "required": ["decision"]
}
```

Output schema:

```json
{
  "ok": true,
  "source_document_id": "uuid",
  "claim_id": "uuid-or-null",
  "component_id": "uuid-or-null"
}
```

Side effects:

- Source document: creates `SourceDocument(source_type = "agent_decision")`.
- Claim/component: creates a `decision` claim with a `create` revision and
  projected component when evidence span validation succeeds; otherwise
  `needs_review`.
- Trust zone: `trusted_human` only when `made_by` identifies the user or
  verified human; otherwise `semi_trusted_tool`.
- Idempotency: same decision hash and idempotency key returns existing record.

Errors:

- `invalid_input` for empty decision.
- `agent_run_not_found` if a provided run ID is invalid.

### record_blocker

Purpose: record a blocker that should affect future packs.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "agent_run_id": {"type": ["string", "null"]},
    "workspace_id": {"type": ["string", "null"]},
    "blocker": {"type": "string"},
    "severity": {"type": "string"},
    "files": {"type": "array", "items": {"type": "string"}},
    "evidence": {"type": ["string", "null"]},
    "idempotency_key": {"type": ["string", "null"]}
  },
  "required": ["blocker"]
}
```

Output schema:

```json
{
  "ok": true,
  "source_document_id": "uuid",
  "claim_id": "uuid-or-null",
  "component_id": "uuid-or-null"
}
```

Side effects:

- Source document: creates `SourceDocument(source_type = "agent_blocker")`.
- Claim/component: creates `blocker` or `risk` claim. Severity influences
  `authority_weight` but does not bypass evidence validation.
- Trust zone: `trusted_human` for explicit human blockers, otherwise
  `semi_trusted_tool`.
- Idempotency: same normalized blocker, files, and idempotency key returns
  existing record.

Errors:

- `invalid_input` for empty blocker or invalid severity.

### record_patch_summary

Purpose: record changed files, summary, and tests after an agent patch.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "agent_run_id": {"type": "string"},
    "summary": {"type": "string"},
    "files_changed": {"type": "array", "items": {"type": "string"}},
    "tests_run": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "command": {"type": "string"},
          "exit_code": {"type": "integer"},
          "summary": {"type": ["string", "null"]}
        },
        "required": ["command", "exit_code"]
      }
    },
    "head_commit": {"type": ["string", "null"]},
    "idempotency_key": {"type": ["string", "null"]}
  },
  "required": ["agent_run_id", "summary", "files_changed"]
}
```

Output schema:

```json
{"ok": true, "source_document_id": "uuid", "run_observation_id": "uuid"}
```

Side effects:

- Source document: creates `SourceDocument(source_type = "patch_summary")`.
- Claim/component: creates `run_event` and `verification` claims; failed tests
  create or update blocker/risk claims.
- Trust zone: `semi_trusted_tool`.
- Idempotency: same `(agent_run_id, head_commit, idempotency_key)` returns
  existing summary.

Errors:

- `agent_run_not_found`.
- `invalid_input` when files are absent or summary is empty.

### verify_context_item

Purpose: record human/tool verification for a selected or excluded context item.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "context_pack_id": {"type": "string"},
    "item_id": {"type": "string"},
    "verdict": {"type": "string"},
    "note": {"type": ["string", "null"]},
    "verifier": {"type": ["string", "null"]},
    "evidence": {"type": ["string", "null"]},
    "idempotency_key": {"type": ["string", "null"]}
  },
  "required": ["context_pack_id", "item_id", "verdict"]
}
```

Valid `verdict`:

- `verified`
- `incorrect`
- `stale`
- `needs_review`
- `resolved`

Output schema:

```json
{
  "ok": true,
  "source_document_id": "uuid",
  "claim_revision_id": "uuid-or-null",
  "status": "verified"
}
```

Side effects:

- Source document: creates `SourceDocument(source_type = "context_item_verification")`.
- Claim/component: appends a `verify`, `reject`, `mark_stale`, or `resolve`
  revision when the item maps to a claim; updates component status only through
  the projection contract.
- Trust zone: `trusted_human` when verifier is human; otherwise
  `semi_trusted_tool`.
- Idempotency: same `(context_pack_id, item_id, verdict, idempotency_key)`
  returns existing verification.

Errors:

- `context_pack_not_found`.
- `not_found` when item ID is not in the pack.
- `invalid_input` for unknown verdict.

### close_task

Purpose: mark an observed task or blocker as resolved with source evidence.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "agent_run_id": {"type": ["string", "null"]},
    "workspace_id": {"type": ["string", "null"]},
    "claim_id": {"type": ["string", "null"]},
    "component_id": {"type": ["string", "null"]},
    "summary": {"type": "string"},
    "commit": {"type": ["string", "null"]},
    "tests": {"type": "array", "items": {"type": "string"}},
    "evidence": {"type": ["string", "null"]},
    "idempotency_key": {"type": ["string", "null"]}
  },
  "required": ["summary"]
}
```

Output schema:

```json
{
  "ok": true,
  "source_document_id": "uuid",
  "claim_revision_id": "uuid-or-null",
  "status": "resolved"
}
```

Side effects:

- Source document: creates `SourceDocument(source_type = "task_close")`.
- Claim/component: appends `resolve` revision to the referenced claim when
  present; legacy component status may be updated to `resolved` only through a
  compatibility shim covered by tests.
- Trust zone: `semi_trusted_tool` unless backed by explicit human evidence.
- Idempotency: same referenced item, commit, and idempotency key returns
  existing close record.

Errors:

- `not_found` for invalid claim/component references.
- `invalid_input` when no claim/component/run/workspace context can be resolved.

## MCP Acceptance Tests

Implemented in this branch:

- `tests/test_mcp.py::test_mcp_lists_runtime_bridge_tools_with_trust_warning`
- `tests/test_mcp.py::test_prepare_task_reports_compiler_unavailable`
- `tests/test_mcp.py::test_prepare_task_calls_compiler_and_persists_pack`
- `tests/test_mcp.py::test_mcp_write_tool_errors_are_structured`
- `tests/test_mcp.py::test_mcp_runtime_write_tools_persist_source_backed_loop`

Proposed hardening tests still needed:

- idempotency behavior for repeated MCP writes;
- blocker influence on a subsequent prepared pack;
- failed-test patch summaries appearing as risk in the next pack.
