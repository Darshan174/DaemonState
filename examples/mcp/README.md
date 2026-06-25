# MCP Examples

Use these snippets to connect Context Engine to an MCP-capable coding agent.
Both examples launch the same server: `ctxe mcp`.

## Installed CLI

Use this when `ctxe` is on your `PATH`, for example after installing the
package or activating the `.venv` created by `bash scripts/setup.sh`.

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

Config file: [installed-cli.json](installed-cli.json)

## Local Checkout

Use this when you cloned the repo and ran `bash scripts/setup.sh`, but your MCP
client does not inherit the repo's virtualenv path. Replace the command with the
absolute path to your checkout.

```json
{
  "mcpServers": {
    "context-engine": {
      "command": "/absolute/path/to/context-engine/.venv/bin/ctxe",
      "args": ["mcp"]
    }
  }
}
```

Config file: [local-checkout.json](local-checkout.json)

## Agent Prompt

Use [agent-system-prompt.md](agent-system-prompt.md) as the first instruction in
agents that can call MCP tools. It keeps the agent grounded in
`query_context`, `expand_graph`, and `trace.facts_used` instead of treating
Context Engine as a black-box vector store.
