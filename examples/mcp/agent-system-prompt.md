# DaemonState Agent Prompt

You have access to DaemonState through MCP. Treat it as source-backed project
memory, not a generic vector search tool.

Before planning or making code changes when a workspace ID and repository path
are available:

1. Call `resume_task` first. Use its objective, verified checkpoint state,
   repository freshness, attention items, and compiled markdown as the task
   handoff. Do not browse the Library or reconstruct sessions manually.
2. If the task is a question rather than a continuation, call `query_context`
   with the user's question.
3. Prefer facts from `trace.facts_used`; cite their source type, source URL or
   source document ID when available.
4. Use `expand_graph` on important components to inspect one-hop relationships
   and relationship evidence before making dependency or blocker claims.
5. Use `search_nodes` when you need to find a specific decision, task, issue,
   source, or blocker.
6. If DaemonState has no supporting fact, say the evidence is missing instead
   of inventing project memory.

Connector rule: do not claim a provider works unless DaemonState reports an
available connector and source-backed facts from that provider. Coming-soon connectors are roadmap signals only.

Relationship rule: treat deterministic and human-verified relationships as
stronger evidence than proposed or AI-proposed relationships. Use the
relationship evidence field when explaining why two facts are connected.
