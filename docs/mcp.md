# MCP

Context Engine ships a Model Context Protocol server so AI coding agents can ask
for source-backed project memory without scraping the UI.

Observed current behavior: MCP runs over stdio through `ctxe mcp` and reads the
same database as the FastAPI app.

Implemented in this branch: MCP acts as the runtime observation bridge for the
Context Compiler v2 loop: let the agent work, observe the run, ingest
observations as source evidence, and improve later context.

Current checkout: `prepare_task` is registered and calls the shared
`ContextCompiler` service. Its import guard still returns a structured
`compiler_unavailable` error if a partial integration checkout omits that
service instead of inventing compiler logic inside MCP.

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
| `record_agent_run_finish` | Finish a linked run and preserve the supplied repository outcome and verification results as append-only source evidence. |
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

The returned manifest follows the implemented `context_pack.v2` contract:

- use `context_pack_id`, not `pack_id`;
- use `created_at`, not `generated_at`;
- use selected/excluded item `item_type`, not `type`;
- include `rendering.markdown_sha256`, `rendering.estimated_tokens`,
  `rendering.estimation_method`, and `persistence`;
- include exact citation audit fields such as `source_document_id`,
  `source_revision_number`, `source_content_sha256`, `evidence_span_id`,
  source ranges, `text_sha256`, and `trust_zone`;
- set `persistence.mode = "database"` for durable HTTP/MCP output;
- persist applicable `ContextPackItem` claim, component, evidence-span, and
  source-document identifiers.

The broader [Context Pack v2 design reference](context-pack-v2.md) contains
additional historical hardening proposals. For current behavior, the compiler
manifest and its focused tests are authoritative.

Repeated `prepare_task` calls with the same deterministic replay key reuse the
existing durable pack row. The replay key has a database uniqueness constraint;
the stored manifest and markdown are returned unchanged.

## Runtime Observation Contract

Implemented in this branch:

- `record_agent_run_start` creates `AgentRun`.
- `record_agent_run_finish` writes terminal run state plus an append-only
  `agent_run_outcome` source and linked `RunObservation`; this is observational
  evidence, not proof that the pack caused the result.
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
    "focus_component_id": {"type": ["string", "null"]},
    "objective_origin": {
      "type": ["string", "null"],
      "enum": ["trusted_human", "source_component", "project_snapshot", null]
    }
  },
  "required": ["workspace_id", "repo_path", "target_model", "token_budget"]
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
  "health_score": 0.87,
  "focus": {}
}
```

Side effects:

- Source document: none. A `trusted_human` objective stays an explicitly labelled
  pack input; a `source_component` objective is derived from that component's
  exact source revision.
- Claim/component: none directly. The compiler reads claims/components and
  persists `ContextPack` plus `ContextPackItem` rows.
- Trust zone: generated instructions are `trusted_system`; user objective is
  `trusted_human`; quoted evidence keeps original trust.
- Manifest: must use the final `context_pack.v2` field names and persistence
  metadata from `docs/context-pack-v2.md`.
- Idempotency: the compiler derives its replay identity from the normalized
  objective, explicit focus, workspace, profile, and repository state.

Errors:

- `invalid_input` for empty goal or invalid token budget.
- `compiler_unavailable` when the compiler service cannot be imported.
- `schema_missing` when v2 persistence tables are unavailable.
- `internal_error` for compiler failures.

### record_agent_run_start

Starts a run against a durable context pack. Required inputs are `tool`, `model`,
`branch`, `base_commit`, `objective`, `context_pack_id`, and stable `run_key`.
The same `(context_pack_id, run_key)` returns the original `run_id`; reuse with a
different payload returns `run_identity_conflict`. This write creates `AgentRun`
metadata only and does not claim that any work occurred.

### record_agent_run_finish

Records a terminal `completed`, `failed`, `blocked`, or `cancelled` outcome.
Required inputs are `run_id`, stable `event_key`, `status`, `head_commit`,
`summary`, `changed_files`, and `verification_results`. Optional
`completed_context_item_ids` and `addresses_context_item_ids` bind the outcome
to exact pack items.

The outcome is stored as a `RunObservation` backed by an immutable
`SourceDocument(source_type = "agent_run_observation")`. Structured
`verification_results` are evaluated and shown in the founder timeline, but
Context Engine does not execute those commands. An identical retry returns the
original observation; a changed payload under the same key returns
`event_identity_conflict`.

### record_agent_event

Appends an observed event using required `run_id`, `event_key`, `event_type`,
and `content`. Optional factual fields include `files`, `command`, `exit_code`,
`observed_at`, `requirement_id`, `addresses_context_item_ids`, and
`resolves_event_key`. Every event first becomes an immutable
`agent_run_observation` source revision. Durable types (`verification`,
`blocker`, `blocker_resolution`, `patch_summary`, `outcome`, and `decision`) are
then conservatively projected; generic logs and notes remain raw evidence.

### record_decision

Requires `run_id`, `event_key`, `decision`, `rationale`, `files`, and `evidence`.
It writes unified runtime source evidence before the conservative decision
claim/component projection. Output includes the source, observation, claim, and
component IDs plus `projection_status`.

### record_blocker

Requires `run_id`, `event_key`, `blocker`, `severity`, `attempted_fix`, and
`evidence`. It preserves the source observation before the conservative blocker
projection. Resolve a blocker with a later `record_agent_event` whose
`event_type` is `blocker_resolution` and whose `resolves_event_key` names the
original blocker event.

### record_patch_summary

Requires `run_id`, `event_key`, `changed_files`, `summary`, and the observed
`tests_run` command strings. `addresses_context_item_ids` may cite exact pack
items. The tool records evidence only; it never creates or applies a patch.

For all runtime tools, `event_key` is scoped to one run. Identical retries return
the original source/observation. Reusing the key for changed content returns
`event_identity_conflict`. All runtime evidence uses `semi_trusted_tool` and the
canonical external ID `agent_runtime:{run_id}:{event_key}`.

### verify_context_item

Records verification evidence for a direct `component_id`, `claim_id`, or both.
`verdict` and `evidence` are required. The tool writes an
`mcp_context_verification` source, appends a claim revision when a claim is
available, and updates the referenced component status. It does not verify an
entire context pack by implication.

### close_task

Marks a direct task `task_component_id`, `task_claim_id`, or both resolved using
required `resolution` and `commit` evidence. It writes an `mcp_task_close`
source and appends a resolve revision when a claim is available. This tool does
not run git or push the supplied commit.

## MCP Acceptance Tests

Implemented in this branch:

- `tests/test_mcp.py::test_mcp_lists_runtime_bridge_tools_with_trust_warning`
- `tests/test_mcp.py::test_prepare_task_reports_compiler_unavailable`
- `tests/test_mcp.py::test_prepare_task_calls_compiler_and_persists_pack`
- `tests/test_mcp.py::test_mcp_write_tool_errors_are_structured`
- `tests/test_mcp.py::test_mcp_runtime_write_tools_persist_source_backed_loop`
- `tests/test_mcp.py::test_idempotent_runtime_retry_retries_failed_projection`
- `tests/test_founder_oversight.py::test_focused_compile_mcp_run_and_scrutiny_full_loop`

Proposed hardening tests still needed:

- blocker influence on a subsequent prepared pack;
- failed-test patch summaries appearing as risk in the next pack.
