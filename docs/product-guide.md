# Product guide

DaemonState is a continuity and evidence layer between a software project and
the coding agents that work on it. Its primary job is to let a new agent session
start from a current, reviewable handoff without asking the user to reconstruct
the task from memory.

The product is deliberately not an agent. It does not decide which product to
build, submit browser handoffs, turn a provider's self-report into proof, or
silently promote one session's claims into project-wide truth.

## Current product surface

| Area | Browser state | Purpose |
|---|---|---|
| Continue | Available | Carry the newest eligible local session into a fresh, user-reviewed desktop composer. |
| Library | Available | Discover, search, group, and inspect local sessions and recovery checkpoints within one project boundary. |
| Execute | Available | Compile Workspace Context and compare or copy up to three explicitly selected historical Session Contexts. |
| Workspaces | Available through workspace management | Create one project boundary per repository, rename/archive it, and permanently delete an archived workspace with exact-name confirmation. |
| Evidence | Under construction | Backend graph, digest, scrutiny, timeline, source-diff, and focused context behavior exists; the top-level browser route is intentionally gated. |
| Sources | Under construction | Source creation, upload, bulk ingestion, revision, listing, and detail APIs exist; the top-level browser route is intentionally gated. |
| Integrations | Under construction | Connector catalog, setup, sync, job, and disconnect APIs exist; the top-level browser route is intentionally gated. |

Hidden content beneath an under-construction overlay is not a supported user
workflow. Use the CLI or HTTP API for those backend capabilities until the
browser gate is removed.

## Core vocabulary

### Workspace

A workspace is the hard project boundary. It owns source revisions, extracted
facts, repository observations, local sessions, checkpoints, context packs,
runs, connectors, and goals. A real workspace should point at one Git
repository. Demo and sandbox workspaces are visibly separated from real
projects.

Workspace access is enforced before source evidence can affect retrieval,
memory, or generated context. A restricted API principal sees only its allowed
workspace IDs. The current production profile remains single-tenant because
not every mutation has action-level tenant authorization.

### Source document and revision

Every provider, upload, local session, repository intake, or runtime observation
enters through a raw `SourceDocument`. Updates create append-only revisions
instead of overwriting the earlier evidence. Extracted facts and relationships
refer back to exact source records and, where available, exact evidence spans.

### Workspace Context

Workspace Context is the user-facing name for the project-wide parent context.
Some internal types and older prose call the durable portion Project Context.
It is objective-independent: the compiler receives no task-ranking keywords,
selected session, current prompt, or file-overlap hint when building it.

The current compiler emits a strict, hash-bound `workspace_foundation.v2`
inside a persisted `context_pack.v2` manifest. Its populated lanes describe:

- repository-stated product identity, audience, maturity, deployment model,
  boundaries, and claims;
- domain concepts and documented system flows;
- declared capabilities and the exact code surfaces that may implement them;
- repository architecture components, structural edges, and implementation
  traces with evidence and derivation type;
- repository-declared commands and required-check policy;
- snapshot-bound verification status on declared commands when a compatible
  local-harness observation exists;
- current Git state, typed file changes, and semantic deltas;
- repository-scoped engineering notes that remain documentation claims; and
- durable project knowledge compiled through the existing evidence-gated
  foundation lane.

The v2 schema also defines first-class `production_flows`,
`verification_runs`, `change_intents`, and `durable_facts` collections. In this
checkout the default compiler leaves those four collections empty and the
default renderer does not project them. Their admission and projection rules
are completion contracts, not claims about current non-empty output; see the
[Workspace Foundation Compiler](workspace-foundation-compiler.md).

Compilation does not execute repository commands. A command declaration remains
unverified until a compatible persisted observation matches the exact current
repository snapshot.

### Session Context

Session Context is the task-specific child for one local coding-agent session.
It captures the current goal, state, next action, decisions, failed attempts,
changed files, checks, blockers, scope, and done conditions at an immutable
session boundary.

The default visible renderer is `compact_v2` and has five sections:

1. Goal
2. State now
3. Start here
4. Do not repeat
5. Done when

The renderer preserves the exact user lead and hash while keeping audit-only
IDs, ranking values, and large inventories out of the model-facing brief.
`legacy_v1` remains an emergency rollback through
`SESSION_HANDOFF_BRIEF_VARIANT`.

### Checkpoint

A `WorkCheckpoint` is an immutable captured session boundary. DaemonState can
capture the current session tip and pre-compaction recovery boundaries. A
checkpoint records structured state and binds it to the available repository,
session, source revision, event, attachment, and verification evidence.

Imported commands are historical evidence. Verifying a checkpoint compares its
claims with current evidence; it never replays those imported commands.

### Context pack, execution contract, and run

These artifacts serve different purposes:

| Artifact | Role |
|---|---|
| `context_pack.v2` | Complete audit record for selection, exclusions, provenance, risks, repository state, rendering, and persistence. |
| `workspace_foundation.v2` | Objective-independent, typed Workspace Context payload embedded in a project-snapshot context pack. |
| `session_handoff.v1` | Structured contract behind a visible Session Context. |
| `continuation_execution.v1` | Provider-neutral typed execution contract with request lineage, requirements, authority, artifacts, repository protection, and verifiers. |
| `continuation_staging_context.v1` | Compact context used for the user-controlled browser staging boundary. |
| `continuation_execution_prompt.v1` | Worker instruction used only when a runtime actually starts and observes a provider process. |
| `AgentRun` and `RunObservation` | Durable record of a measured worker invocation and bounded observations. |

The audit pack is never sent directly as the automatic worker instruction.

## The main product loop

```text
connect repository
       |
       v
discover in-project local sessions
       |
       v
capture + reconcile checkpoint
       |
       +----------------------+
       |                      |
       v                      v
Workspace Context       Session Context
project-wide parent     task-specific child
       |                      |
       +-----------+----------+
                   v
      user-reviewed browser handoff
      or observed CLI/provider execution
                   |
                   v
       ingest result for the next loop
```

## Continue

Continue is intentionally single-purpose. It carries the newest eligible
in-project session forward.

### Selection

The page asks the local session resolver for the latest eligible root session,
newest first. Project scope is determined from the workspace repository and
session metadata such as current working directory, project path, and repository
identity. Internal sessions and sessions from another project are excluded.

Continue does not use:

- a historical Library selection;
- an Execute selection;
- an arbitrary session ID in the URL;
- a saved recovery point as a silent replacement; or
- an older indexed session when latest-session discovery failed.

If no eligible latest session exists, the action remains disabled. Historical
work belongs in Library and Execute.

### Preparation

Before handoff, DaemonState:

1. carries the exact selected provider/session/source identity through the
   request;
2. captures the current session tip when a compatible checkpoint is missing;
3. resolves the authoritative current lead from the visible session or a
   deliberate user edit;
4. compares the checkpoint with the current repository and session boundary;
5. compiles the audit context pack and typed continuation contract;
6. produces the bounded Session Context;
7. checks quality, integrity, required artifacts, repository preservation, and
   provider capabilities; and
8. copies the complete hash-verified handoff before desktop dispatch.

A selected session can inherit an incomplete Workspace Context only as warned,
reviewable background in a visible handoff. An empty or corrupted parent is not
silently treated as ready.

### Browser dispatch

The browser uses local-only staging and does not start a provider CLI. On macOS
it requests a fresh composer through the installed application's registered
URL scheme:

- `codex://threads/new`
- `claude://code/new`
- `opencode://new-session`

When the complete context fits the bounded native link, a prefill is requested.
The clipboard always remains the complete fallback. A successful Launch
Services request proves neither that the destination rendered nor that the
user submitted it. The response therefore reports a handoff, hash, and dispatch
state—not a provider session ID or agent run.

Staging is idempotent. Reloads and same-key retries do not dispatch twice.
Because dispatch remains unverified, the user can deliberately choose
**Request again**, which creates a new key after checking the target app.

### Provider readiness

Browser readiness has a narrow scope: desktop application installation and a
registered URL handler are the hard dispatch gates. Codex account, model, and
rate-limit evidence is read-only and reported separately when the local app
server supports it. Inconclusive account evidence does not become a fabricated
manual attestation requirement.

The automatic CLI path applies stricter task-specific capability gates, such
as command execution, permission modes, file context, filesystem writes, or
native image support.

## Library

Library incrementally discovers and imports local history for Codex, Claude
Code, and OpenCode. It keeps raw session content as source evidence, derives a
display-safe topic/summary, and records compaction checkpoint descriptors.

Users can:

- search by title, topic, harness, or summary;
- filter and group sessions by harness or topic;
- inspect root/fork relationships where the provider exposes them;
- manually sync local history;
- prepare an older session without changing Continue's source; and
- restore a captured pre-compaction recovery point.

A session ID identifies and deduplicates a session; it is not enough to fetch a
conversation from a provider. DaemonState must be given the content through
local discovery or an import path.

## Execute

Execute presents two separate kinds of context without merging their truth
boundaries.

### Workspace Context card

The page calls `POST /api/context/prepare` with:

```json
{
  "workspace_id": "<uuid>",
  "repo_path": "/absolute/repository/path",
  "mode": "project_snapshot",
  "objective_origin": "project_snapshot"
}
```

The compiler returns `context_pack.v2` Markdown and a manifest containing the
typed Workspace Foundation. The browser verifies the schema, workspace,
repository binding, content hash, artifact hashes, and quality report. A copy
forces a fresh compilation so repository drift cannot make a cached preview
silently stale.

The quality report separates:

- copy safety and artifact integrity;
- semantic engineering coverage; and
- repository health.

Coverage is not health. A fully evidenced failed check can improve evidence
coverage while health remains failing. A passing ad hoc command cannot prove
whole-repository health when required-check discovery is incomplete.

### Selected Session Context cards

Execute can show at most three sessions selected explicitly in Library. It
captures or refreshes the exact selected session checkpoint and produces a
separate, hash-checked handoff for each card. It never merges three task
histories into one synthetic session.

The current UI requires at least two detected provider compactions for direct
Session Context copy. This gate is explicit on the session card. It does not
promote recovery evidence into current project truth.

## Memory and evidence

The backend stores current, provisional, stale, superseded, rejected,
historical, and contested states rather than deleting inconvenient history.
Durable Workspace Context admission is stricter than display admission:

- current mechanically verified repository/system evidence may be promoted;
- current authorized human confirmation may be promoted;
- agreeing claims from at least two genuinely independent sources may be
  promoted when they do not conflict with stronger evidence;
- a single agent session, repeated rows from the same source, or a confidence
  score alone cannot promote a fact; and
- superseded, stale, inaccessible, rejected, or conflicting evidence stays out.

The graph and query APIs expose provenance, evidence, confidence, temporal
state, relationship origin, source revision, and retrieval trace. Frontend
Evidence is still under construction, so these are currently API/MCP contracts
rather than a supported top-level browser workflow.

## Sources and connectors

All ingestion is source-first. Available source paths include local files,
uploads, repository intake, local/imported AI sessions, GitHub, Slack, Gmail,
and Google Drive. Discord, Zoom, and Wispr Flow are catalogued as coming soon;
Notion is not catalogued.

“Available” means the backend can create source documents through a tested path
when correctly configured. It does not mean the under-construction Integrations
page is supported for onboarding. Demo evidence never marks a provider
connected.

Connector sync jobs are leased, heartbeat-aware, retryable, and conditionally
completed so a stale worker cannot finalize a reclaimed job. Delivery is
at-least-once, so provider ingestion remains idempotent.

## CLI continuation and the local harness

`daemonstate continue` without `--into` prepares the current continuation.
With `--into codex`, `--into claude`, or `--into opencode`, it starts a new local
provider process non-interactively, records bounded output and repository
state, and evaluates the typed verification contract after the provider exits.

`daemonstate harness run` wraps an arbitrary explicit argv instead of a built-in
provider adapter. It executes exactly the supplied argv without shell
interpolation. Verification commands run only with its explicit `--verify`
flag.

Neither path adds bypass, danger, or auto-approval flags. Codex is constrained
to its workspace-write sandbox; Claude receives task-mode-specific permission
settings; OpenCode retains its installed permission policy where DaemonState
cannot prove a stronger task-specific boundary.

## Outcome language

DaemonState separates process completion from verified task completion:

| Outcome | Meaning |
|---|---|
| `verified_complete` | The worker completed, every MUST requirement has passing required evidence, the repository preservation gate passed, and the runtime bundle remained intact. |
| `requirements_unproven` | The worker completed, but mandatory evidence is missing, failed, skipped, malformed, or unsupported. |
| `execution_failed` | The provider process or an ordinary execution step failed. |
| `blocked_external` | Authentication, billing, provider service, CLI version, credentials, permissions, or other external infrastructure blocked the run. |
| `blocked_ambiguity` | The runtime needs explicit user intent before it can proceed safely. |

A provider's exit code, text summary, or claim of success is not sufficient
proof. Verification must be linked to the exact requirement and current
repository state.

## Safety and privacy boundaries

- Personal profiles bind to loopback by default and have no browser login.
- Local repository roots are canonicalized and can be restricted by
  `ALLOWED_REPO_ROOTS`.
- Docker repository mounts are read-only.
- Source evidence is data, not executable instruction. Prompt-injection risk is
  scored and untrusted content is quoted in model-facing output.
- Clipboard content, attachments, and typed artifacts are SHA-256 checked at
  delivery boundaries.
- Pre-existing Git changes form a protected baseline. Automatic execution may
  not silently revert, unstage, overwrite, or broadly reformat them.
- Captured stdout/stderr, file scans, repository paths, and artifacts are
  bounded; output is not a terminal recording.
- OpenTelemetry is metadata-only. Content capture is unsupported.
- MCP is a trusted local stdio interface, not a network listener.

## Known limitations

- Browser desktop handoff and the floating control are macOS-specific.
- Evidence, Sources, and Integrations are not yet supported browser workflows.
- There is no system-wide agent monitor or live provider-state stream.
- Session discovery depends on local provider formats and reliable project
  metadata; ambiguous sessions remain excluded or unknown.
- Workspace Context is deterministic but bounded. Unsupported languages may
  provide structural/line evidence without full semantic deltas.
- Execute rejects an unknown Workspace Foundation schema and leaves the
  clipboard untouched, but its outer copy control currently remains enabled as
  a retry action after that terminal validation error instead of becoming
  disabled. The focused UI regression test records this alpha gap.
- Static edges do not prove runtime branch selection, external effects, or
  successful persistence.
- The production profile is single-tenant, single-host, API-only, and not
  highly available.
- Model-lift reports are descriptive and do not prove causal or general model
  parity.

For the exact continuation state machine, see
[Continuation runtime](continuation-runtime.md). For the objective-independent
compiler contract, see
[Workspace Foundation Compiler](workspace-foundation-compiler.md).
