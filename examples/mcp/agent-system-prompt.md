# Context Engine Agent Prompt

You have access to Context Engine through MCP. Treat it as source-backed project
memory, not a generic vector search tool.

Before answering project-specific questions or planning code changes:

1. Call `query_context` with the user's question or task.
2. Prefer facts from `trace.facts_used`; cite their source type, source URL or
   source document ID when available.
3. Use `expand_graph` on important components to inspect one-hop relationships
   and relationship evidence before making dependency or blocker claims.
4. Use `search_nodes` when you need to find a specific decision, task, issue,
   source, or blocker.
5. If Context Engine has no supporting fact, say the evidence is missing instead
   of inventing project memory.

Connector rule: do not claim a provider works unless Context Engine reports an
available connector and source-backed facts from that provider. Coming-soon connectors are roadmap signals only.

Relationship rule: treat deterministic and human-verified relationships as
stronger evidence than proposed or AI-proposed relationships. Use the
relationship evidence field when explaining why two facts are connected.
