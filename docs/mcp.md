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
