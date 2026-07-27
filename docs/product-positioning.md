# Product Positioning

## One-line position

DaemonState is the verified handoff layer that lets a coding agent continue
real work without reconstructing the project from scratch.

## What the product is

DaemonState is an open-source context and evidence layer for coding agents.
It collects project history from repositories, issues, pull requests, imported
agent sessions, decisions, documents, and verification output, then prepares a
focused, source-backed brief for one current task.

The product does two connected jobs:

1. **Primary runtime:** resolve the current repository-scoped task, restore its
   latest compatible durable checkpoint, verify it against the repository,
   compile the minimum task-ready context, and deliver it to another coding
   harness.
2. **Inspection:** show the sessions, evidence, relationships, and conflicts
   behind that handoff when a person needs to audit it.

The continuation runtime and context compiler are the core product. Library,
Memory, History, and the graph are supporting inspection surfaces; they are not
the workflow a developer must maintain before continuing work.

## First audience

Solo founders and tiny teams using coding agents every day.

Their work is split across Codex, Claude Code, OpenCode, GitHub, local files,
and team tools. One agent proposes a change, another edits the code, a pull
request carries a partial implementation, and the next session starts without
the decisions or failed checks that led there.

## Product loop

1. Connect a repository once and ingest local coding-agent sessions.
2. Resolve the current objective from an explicit request, active workspace
   goal, or latest substantive in-scope session.
3. Capture and verify the latest compatible checkpoint against the current
   repository.
4. Compile only the context relevant to that task and target model.
5. From the local app, choose a readiness-checked Codex, Claude Code, or
   OpenCode card and start a fresh target session. Explicit choices never
   silently fall back; MCP returns the pack to its calling agent.
6. Record repository changes, checks, blockers, and outcome evidence for the
   next continuation.
7. Report `verified`, `completed_unverified`, `blocked`, or `failed` from
   observed execution instead of turning evidence confidence into user
   homework.

## Daily-use test

A user should be able to run one continuation command and have the next agent
start from the right task state. If they inspect the product, they should be
able to learn:

- what the current goal is;
- where the project stands;
- what changed in recent agent runs and code;
- which blockers, risks, and failed checks are real;
- why a fact is believed and where it came from;
- what context the next agent will receive;
- what remains unresolved after the last run.

A green preparation score is not success. Product acceptance requires a
different agent to continue the real task correctly without re-explanation,
with less discovery than a blank-session baseline, and without using stale
context. A completed process with no executable checks remains
`completed_unverified`, not a verified handoff.

## Product wedge

The wedge is:

**Reliable continuity between coding-agent sessions on real codebases.**

The initial proof is not that DaemonState makes a weak model magically
smarter. It is that better task selection, verified history, less irrelevant
context, and explicit verification can help cheaper, older, or open models
complete more useful work than they would with a blank chat or an undirected
context dump.

## Not the product

DaemonState is not positioned as:

- another autonomous coding agent;
- a generic company knowledge graph;
- enterprise search;
- an all-in-one RAG platform;
- a connector directory;
- a dashboard that merely lists project activity;
- proof that smaller models already match frontier models.

## Current honest boundary

DaemonState currently provides a shared continuation service through FastAPI,
`daemonstate continue`, and MCP `resume_task`; audited CLI adapters for Codex, Claude
Code, and OpenCode; a context compiler; durable checkpoints; source-backed
inspection views; and a local harness that records bounded execution evidence.

The browser UI calls a local-only run service, which starts a fresh installed
provider process and returns observed repository and check results. It cannot do
that through a remote principal. `daemonstate continue --into ...` performs direct
non-interactive delivery without permission-bypass flags. Neither surface
claims a verified handoff when no executable check ran. Model-lift reports
describe observed runs and do not yet prove general model equivalence.

Local repository and session imports are available. GitHub, Slack, Gmail, and
Google Drive have configured backend paths, but public onboarding is unfinished.
Unsupported and coming-soon connectors must remain clearly labelled.
