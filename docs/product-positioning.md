# Product positioning

## One-line position

DaemonState is the source-backed handoff layer that lets a coding agent continue
real project work without reconstructing the task from scratch.

## Category

DaemonState is a self-hosted continuity and evidence layer for coding agents.
It sits between project evidence and the agent tools a developer already uses.
It is not itself a coding agent, a generic knowledge graph, enterprise search,
an all-purpose RAG platform, or an autonomous project manager.

The repository is source-available under SUL-1.0 from version 0.3.0. “OSS
product” conventions describe its transparent repository, self-hosting,
documentation, issue workflow, and local operation; they do not change the
license into an OSI-approved open-source license.

## First audience

The first audience is solo founders, developers, and tiny product teams that
use Codex, Claude Code, or OpenCode across repeated sessions on the same
codebase.

Their context is fragmented across:

- local agent sessions and compaction boundaries;
- the current Git working tree;
- issues and pull requests;
- documents and team conversations;
- decisions and failed approaches; and
- checks whose actual result may disagree with an agent's summary.

The cost is not merely repeated prompting. A new agent can choose the wrong
task, repeat a known failure, overwrite pre-existing work, rely on stale state,
or declare completion without requirement-linked evidence.

## Product promise

**Continue the work, not the explanation.**

DaemonState should let a new session receive:

- the correct current lead;
- a bounded project-wide Workspace Context;
- the previous session's exact task-local state;
- current repository and preservation boundaries;
- decisions, failures, blockers, files, and checks with evidence;
- an ordered first action; and
- observable done conditions.

The user should be able to inspect why each important claim was included and
what was excluded as stale, conflicting, unsafe, inaccessible, or irrelevant.

## The wedge

The product wedge is reliable continuity between coding-agent sessions on real
repositories.

The initial proof is not that DaemonState makes a weak model magically equal a
frontier model. It is that correct task selection, verified history, bounded
project context, preserved user changes, and explicit verification can reduce
rediscovery and stale-context mistakes compared with a blank session or an
undirected context dump.

The included harness can record old-alone, old-with-DaemonState, and new-alone
runs. Those reports remain descriptive until enough paired real tasks support a
directional result; they never establish general causal model parity.

## Product loop

1. Connect one repository to one workspace.
2. Discover project-scoped local Codex, Claude Code, and OpenCode sessions.
3. Select the newest eligible session for Continue, or explicitly choose
   historical sessions in Library/Execute.
4. Capture an immutable checkpoint and reconcile it with the repository.
5. Compile Workspace Context independently from the task and Session Context
   specifically for that session.
6. Deliver a reviewable browser handoff, a measured CLI execution, or context
   to an MCP caller.
7. Observe repository changes, requirement-linked checks, blockers, and the
   terminal outcome where an execution runtime exists.
8. Preserve the evidence for the next continuation without automatically
   promoting task-local narration into project truth.

## Current product reality

### Available browser loop

- **Continue** carries only the newest eligible in-project session. On macOS it
  copies the complete Session Context and requests a new desktop composer. It
  does not submit a turn or claim that the target rendered.
- **Library** discovers and groups local session history and exposes recovery
  checkpoints without changing Continue's source.
- **Execute** compiles objective-independent Workspace Context and displays up
  to three explicitly selected historical Session Contexts.
- **Workspaces** provides project isolation, repository indexing, archive, and
  guarded permanent deletion.

### Backend available, browser gated

Evidence, Sources, and Integrations have implemented APIs and data models, but
their top-level browser routes are intentionally marked **Under construction**.
They are not current onboarding or inspection promises.

### CLI and MCP

- `daemonstate prepare` compiles task context without starting a worker.
- `daemonstate continue --into ...` starts an audited local Codex, Claude, or
  OpenCode CLI, observes it, and evaluates requirement-linked evidence.
- `daemonstate harness run` wraps one explicit argv and runs verification only
  with `--verify`.
- MCP prepares/queries context and records runtime evidence over trusted local
  stdio. It does not edit code, execute shell commands, push commits, or write
  to providers.

## Daily-use test

A successful daily-use product loop should answer:

- Which task is current, and why was it selected?
- What project-wide facts are safe to inherit?
- What did this session complete, attempt, or leave unresolved?
- What changed in the repository, including pre-existing user work?
- Which checks actually ran against which snapshot?
- What should the receiving agent do first?
- What observable evidence would prove the task done?

A green context-preparation score is not task success. Product acceptance
requires a different agent to continue the real task correctly without
re-explanation, with less discovery than a blank-session baseline, without
repeating a known failure, and without using stale context.

## Truth contract

- Raw source revisions exist before extracted facts.
- Repository structure, documentation claims, human confirmation, runtime
  proof, and agent narration remain distinct evidence tiers.
- A session fact enters durable Workspace Context only through current
  mechanical evidence, authorized human confirmation, or independent
  corroboration without a stronger conflict.
- An import or static edge does not prove a runtime call.
- A linked test does not prove execution.
- A provider exit or success message does not prove a MUST requirement.
- Unknown stays unknown instead of being filled with plausible product copy.

## Non-goals

DaemonState is not currently positioned as:

- a hosted multi-tenant service;
- a system-wide monitor for every agent process;
- a public browser dashboard;
- an autonomous code reviewer;
- a live provider-state stream;
- a replacement for Git, tests, issues, or agent permissions;
- an all-provider connector directory;
- a high-availability or multi-region platform; or
- proof that older models match newer models.

## Current honest boundary

DaemonState is an active alpha. Workstation and personal Docker installs are
single-user/local. Browser desktop delivery is macOS-specific. The hardened
profile is a single-tenant, single-host authenticated API without the browser
frontend. Repository and output observation is intentionally bounded.

Available connector backends include local files/repositories, local or
imported AI sessions, GitHub, Slack, Gmail, and Google Drive. Discord, Zoom, and
Wispr Flow are coming soon; Notion is not catalogued. Available does not mean
the under-construction Integrations browser route is finished.

For the operational product behavior, use the [Product guide](product-guide.md).
