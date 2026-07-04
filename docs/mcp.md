# MCP

Context Engine ships a Model Context Protocol server so AI coding agents can ask
for source-backed project memory without scraping the UI.

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
| `query_context` | Ask the graph with the stable `query.v1` trace contract. |
| `search_nodes` | Rank matching graph components. |
| `expand_graph` | Return a component plus one-hop relationship neighbors. |
| `get_model` | Browse components in a named model. |
| `list_models` | List available graph models and counts. |
| `get_status` | Count sources, models, components, and relationships. |

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

Agents should cite facts from the trace instead of inventing missing context.

## Current Limits

- Retrieval is local/in-process and scans active components, which is acceptable
  for self-hosted and small-team installs.
- Larger public deployments will need indexed retrieval and pagination around
  graph expansion.
- MCP should remain an output surface over the structured graph, not a separate
  memory store.

## Context Compiler v2 MCP Contract

Status: proposed. Current MCP code does not implement these tools yet.

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
    "objective": {"type": "string"},
    "repo_path": {"type": ["string", "null"]},
    "target_model": {"type": "string"},
    "token_budget": {"type": ["integer", "null"]},
    "branch": {"type": ["string", "null"]},
    "base_commit": {"type": ["string", "null"]},
    "idempotency_key": {"type": ["string", "null"]}
  },
  "required": ["objective", "target_model"]
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
- Idempotency: if `idempotency_key` and repo state match an existing pack,
  return the existing pack.

Errors:

- `invalid_input` for empty objective or invalid token budget.
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
- Claim/component: appends a `verify`, `reject`, or `mark_stale` revision when
  the item maps to a claim; updates component status only through the projection
  contract.
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

Agent 4 must add:

- `tests/test_mcp_context_bridge.py::test_list_tools_includes_v2_agent_runtime_tools`
- `tests/test_mcp_context_bridge.py::test_prepare_task_returns_context_pack_v2_manifest`
- `tests/test_mcp_context_bridge.py::test_prepare_task_is_idempotent_with_key`
- `tests/test_mcp_context_bridge.py::test_record_agent_run_start_creates_source_and_agent_run`
- `tests/test_mcp_context_bridge.py::test_record_agent_event_creates_run_observation_source`
- `tests/test_mcp_context_bridge.py::test_record_decision_creates_claim_when_evidence_validates`
- `tests/test_mcp_context_bridge.py::test_record_blocker_affects_next_prepare_task`
- `tests/test_mcp_context_bridge.py::test_record_patch_summary_records_failed_tests_as_risk`
- `tests/test_mcp_context_bridge.py::test_verify_context_item_appends_revision`
- `tests/test_mcp_context_bridge.py::test_close_task_resolves_claim_or_legacy_component`
- `tests/test_mcp_context_bridge.py::test_v2_mcp_exposes_no_dangerous_tools`
