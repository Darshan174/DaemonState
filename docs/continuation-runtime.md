# Continuation Runtime

The continuation runtime is the primary product path. It composes existing
session ingestion, durable checkpoints, repository verification, the context
compiler, and local run evidence into one operation.

## Project / Workspace Context and Session Context

DaemonState exposes two user-facing context products and keeps both separate
from its audit and automatic-execution artifacts:

**Project Context is the parent.** It is the durable, provenance-backed
foundation for a workspace: what the project is, how it works, its architecture
and domain model, repository and technology map, persistent decisions and
invariants, engineering conventions and canonical commands, supported and
unsupported capabilities, long-term constraints and risks, and current product
direction and quality requirements. Every session inherits this foundation as
its logical parent. The two copy artifacts remain separate: Session Context
contains the task-local child state, while Project Context staging renders the
workspace-wide parent together with the active task child. “Workspace
Context” is the delivery-surface label for the same Project Context, not a
third context product.

**Session Context is the child.** It captures the latest individual session's
task-level working memory: the current goal and acceptance criteria, completed
and in-progress state, exact next step, active decisions and reasoning,
failed or rejected attempts and their evidence, changes and discoveries,
meaningful commands and results, verification state, blockers and risks,
assumptions and open questions, fixes and confirmation, scope and non-goals,
and current repository state.

| Artifact | Scope and purpose | Behavior |
|---|---|---|
| **Session Context** | The task-specific child captured from one session's latest immutable tip. It records that session's current working state and its relationship to the Project Context parent; it does not duplicate the parent facts. Repository freshness is checked at handoff time and the current snapshot is used when available. | Use it to refresh a long session or start a new session in the same harness. Failed attempts, rejected approaches, temporary blockers, and other task-local details remain here. The user reviews or copies it, then writes the immediate lead. |
| **Project / Workspace Context** | The durable parent foundation shared by every session in the workspace. It is compiled from all current workspace evidence without using the current prompt, objective, file overlap, selected session, or task ranking. Durable project facts and syntax-level repository observations remain separate. | Mechanically verified, human-confirmed, and corroborated durable facts may enter the current parent. Provisional claims stay outside it; superseded or conflicting facts remain historical. The staging rendering, `continuation_staging_context.v1`, combines the parent with the active task child, loads it into a fresh supported harness thread, and waits. |
| **Execution Prompt** | The provider-neutral worker command rendered as `continuation_execution_prompt.v1` from the typed `continuation_execution.v1` contract. | Used only by an automatic run path that starts the worker, observes it, and applies requirement-linked verification. |
| **Audit ContextPack** | `context_pack.v2`, with complete selection, exclusion, provenance, citation, risk, and reconciliation records. | Durable audit and advanced inspection only. Its Markdown is never the continuation worker instruction. |

Promotion is one-way and evidence-gated. A session outcome may enter Project
Context only when it describes a durable architectural, workflow, product,
constraint, repository, command, or convention change. Mechanically verified
repository facts and human-confirmed intent are directly eligible. Repeated
session claims may become corroborated when they agree across distinct sessions
and do not conflict with repository evidence. Failed or
rejected attempts, temporary blockers, unverified claims, noisy command output,
and other task-specific details remain in the Session Context. The current
runtime does not turn a copied Session Context into a new foundation revision,
and it never rewrites the source session or its immutable checkpoint.

The model-facing Session and Project renderings remain bounded. Session Context
contains the latest task state and an explicit parent-child boundary without
duplicating the parent facts. Project Context staging contains the
objective-independent durable parent plus the active task child.
Event numbers, capture timestamps, selection scores, full dirty-file
inventories, and other audit metadata remain in the structured contract or
Audit ContextPack. A generic “continue the current request” record cannot
reopen a requirement with a newer scoped completion claim. Prior-agent
interpretations that make a deictic request self-contained are retained only as
explicitly unverified historical scope.

Repository evidence uses fixed, non-prose item shapes for symbol declarations,
exact test links, and parsed manifest dependencies. Every item is bound to the
repository snapshot and live file SHA-256; stale items are omitted. These
observations help the receiving model orient itself, but they do not claim code
behavior or architectural intent.

The browser actions are literal: **Preview** displays rendered context, **Copy**
writes user-controlled context to the clipboard, and **Stage** loads Project
Context into a supported waiting harness thread. None of these actions performs
an operating-system-level paste into another app's focused field, presses Enter,
or submits a user turn.

The optional [macOS floating context control](floating-context-control.md) is a
separate native delivery surface. It can copy and synthesize Command-V into the
editor that retained focus, but it never presses Enter and does not weaken the
same context identity, quality, or hash checks.

Both copy paths fail closed. Session Context requires
`quality_report.copy_ready=true`; Project Context requires
`project_context.copy_ready=true`. Superseded session boundaries, unresolved
referenced conversations, incomplete repository snapshots, missing required
artifacts, contradictory authority, and malformed handoff sections remain
previewable with explicit issues but cannot be copied. Automatic execution has
the stricter `automatic_execution_ready`/`launchable` gates.

Project Context also fails closed when its core purpose, workflow,
architecture, or repository sections are empty; a statement lacks hash-bound
provenance; current facts conflict; generic inventory dominates; or its
foundation fingerprint is stale relative to the repository. Headings alone do
not satisfy this gate. An empty foundation is explicitly **not ready** and is
never copyable.

Clipboard delivery is integrity-checked in the browser: the rendered content
must match its server-provided SHA-256, and Session Context must also match the
selected provider, session, checkpoint, and immutable boundary. Copy performs
a fresh handoff/repository check rather than trusting a cached preview. Project
Context is likewise recompiled immediately before copy.

## Runtime Contract

`POST /api/continuations/prepare`, MCP `resume_task`, and the preparation phase
of `daemonstate continue` share the same sequence:

1. Refresh repository-scoped local Codex, Claude Code, and OpenCode sessions
   when local sync is enabled.
2. Resolve an explicit objective, the active workspace goal, or the latest
   substantive request from an in-scope session. A caller may pin
   `source_provider` and `source_session_id` together; the runtime then uses
   that exact session or fails explicitly instead of substituting another one.
3. Without an exact request, capture the compatible session tip as an immutable
   `WorkCheckpoint` and select the latest goal/repository/branch-compatible one.
4. For an exact durable UUID, load that checkpoint directly and authorize every
   evidence source. For a legacy provider-compaction ID, require its source
   document, restore the exact transcript boundary, and mark it for review
   because it has no durable repository fingerprint.
5. Compare and verify durable checkpoints against the current repository.
   Imported session commands remain evidence and are never replayed.
6. Compile `context_pack.v2` as the durable audit record. It retains selection,
   exclusion, provenance, citations, and reconciliation details, but is never
   used directly as a worker instruction.
7. Compile and persist `continuation_execution.v1`, including the full
   byte-preserved request and SHA-256, task mode, source-span-to-requirement
   lineage, structured handoff, artifact hashes, repository preservation
   baseline, read plan, and requirement-specific verifiers. If the request
   adopts a referenced prompt or conversation, its exact relevant turns are
   hash-bound into the contract and rendered as historical data; compilation
   fails closed when that dependency cannot be resolved.
8. Render the provider-neutral `continuation_execution_prompt.v1` from that
   typed contract. Historical agent content is line-by-line blockquoted and
   labeled as data rather than authority.
9. Run the preflight quality gate. Launch fails closed if the full request or a
   MUST requirement is missing, a required artifact is unresolved, the
   repository baseline is incomplete, or the chosen provider cannot enforce
   the task's capabilities and permissions. A declared browser, screenshot,
   event verifier without executable proof blocks automatic launch. Model or
   human-only proof cannot make a mandatory requirement launchable:
   `automatic_execution_ready=false` and `launchable=false`. The Project
   Context may still be copied for manual continuation, with verification
   explicitly labeled unproven until executable or external evidence is added.

`POST /api/continuations` and `daemonstate continue --into ...` continue that
sequence by starting a local provider CLI, observing repository changes, and
running the pack's verification contract after the provider exits. The HTTP run
endpoint is local-only. `POST /api/continuations/run` remains a compatibility
alias.

The browser Continue path is intentionally different. It calls the local-only
`POST /api/continuations/stage` endpoint, which compiles the same evidence and
contract for an explicit immediate lead, or for the lossless user lead resolved
from an exact source session/checkpoint, but starts no provider turn. Requests
with neither a substantive lead nor an exact source boundary fail closed before
compilation. For Codex, DaemonState uses app-server
`thread/start`, supplies a short waiting control through
`developerInstructions`, injects a model-visible
`continuation_staging_context.v1` item containing **Context**, **Direction**,
and **Execution loop**, and verifies the thread is idle with an empty user
preview. It never calls `turn/start`. The injected Direction already contains
the lead used for task-relevant retrieval; the user's next message authorizes,
clarifies, or narrows that same task. A materially different task requires a
fresh Project Context compile.

The staged thread is persisted and opened through
`codex://threads/<thread-id>`. The Continue screen reports
`awaiting_user`, says that nothing has been submitted, and instructs the user
to confirm or narrow the compiled lead and press Enter. Reloading restores that
durable waiting handoff. Once local session ingestion observes the first user
message in the exact thread, the stored lifecycle advances to `handed_off`. A successful
macOS `open` call records that navigation was requested; it is not mislabeled
as proof that the destination rendered.

Provider readiness now reports `context_staging_supported` separately from CLI
and authentication readiness. Codex is enabled only when an exact desktop
thread can be created and opened without starting a turn. Claude Code and
OpenCode remain visible but disabled for browser Continue until they can offer
the same waiting-thread guarantee. No-turn staging requires Project Context
copy/safety readiness and verifies the rendered content hash; it does not
require automatic verifier readiness. Automatic runs remain blocked until the
stricter execution gate passes. Provider readiness is checked again immediately
before staging.

Codex model and reasoning-effort controls are populated only from a successfully
observed installed Codex model catalog. A failed catalog probe exposes no
invented choices; the CLI default remains usable without an override. Selected
model and reasoning effort are persisted as thread configuration so they apply
when the user submits the first turn.

Continuation turns have a four-hour default execution window so substantive
desktop-visible work is not killed at the former one-hour boundary. Operators
can override it with `CONTINUATION_COMMAND_TIMEOUT_SECONDS`.

The execution contract is provider-neutral. Switching from Codex to Claude Code
or OpenCode carries the same full request, atomic requirements, structured
handoff, artifacts, repository state, and proof obligations into a fresh target
session. Provider adapters translate only transport and capabilities; they do
not change task semantics or invent provider-native conversation history that
never happened. The larger context pack remains available for audit.

Agent-reported progress and decisions remain reported evidence. Matching
repository state proves freshness of the observed snapshot, not the truth of
every statement made by an earlier agent.

Reconciliation is chronological as well as semantic. An older next-action
fallback derived from the original goal is superseded by later scoped
completion evidence; a genuine unresolved completion/continuation conflict is
instead labeled contradicted and blocks automatic execution.

## Task and Dependency Workflow

Continuation resolves both the user-selected intent and the immediate task that
can safely execute. Trusted current task components and dependency edges produce
a bounded queue:

- `now`: the single executable prerequisite or selected task;
- `blocked`: unfinished tasks waiting on that prerequisite, with the exact
  blocker and affected task names;
- `next`: tasks that become actionable after `now`;
- `paused`: deliberately paused or dropped work that Continue must not revive.

Ambiguous prerequisites, cycles, inaccessible evidence, a missing goal, and
explicit observation-backed hard blockers fail closed. A blocker sentence
extracted from agent commentary is advisory context, not launch authority; later
reported progress also marks earlier reported blockers historical. Historical
command/test failures remain failed-attempt and verification context; they do
not prevent a new agent from starting. Historical provider-auth failures also
remain scoped evidence; live provider readiness is authoritative for a new run.

A `verified_complete` run advances only the exact source-backed task that
executed.
Completion is written only when the source revision is still current and the
task remains accessible. The workflow is then recomputed, so a dependent task
can move from `blocked` to `now`. Failed or unverified runs never advance the
queue.

## CLI

Prepare without running another agent:

```bash
daemonstate continue \
  --workspace-id <workspace-uuid> \
  --repo .
```

Deliver directly to an installed provider CLI:

```bash
daemonstate continue \
  --workspace-id <workspace-uuid> \
  --repo . \
  --into codex
```

Supported targets are `codex`, `claude`, and `opencode`. Continue always starts
a fresh target session, even when the target provider matches the source. It
always runs the execution contract's requirement-linked verifiers after the
provider exits and has no manual verification switch.

Use `--checkpoint-id <work-checkpoint-uuid>` to continue an exact durable
recovery point. The runtime never silently substitutes a newer checkpoint.

For a legacy checkpoint shown by Library, pass both identities:

```bash
daemonstate continue \
  --workspace-id <workspace-uuid> \
  --repo . \
  --checkpoint-id checkpoint-abc123def456 \
  --checkpoint-source-id <source-document-uuid>
```

Legacy checkpoints are bound to their recorded session repository and prepared
as `review_required`; their pre-compaction transcript is reported context, not
a repository-verified durable snapshot.

Provider execution accepts `ready` and `review_required` preparation results
automatically. `review_required` describes evidence confidence; it is not a
request for the user to finish the workflow. Execution still fails closed when
readiness is `blocked` or unknown.

Provider commands are direct argv invocations. Task mode determines authority:
`change` receives workspace-write access; `diagnose`, `review`, `report`,
`plan`, and `test_only` are read-only or inspection-scoped as defined by the
contract. A provider is unavailable for a task when its adapter cannot enforce
that boundary. No adapter adds bypass, danger, or automatic approval flags.
Execution-prompt delivery is bounded to 1 MiB and uses stdin for Codex/Claude
Code or a permission-restricted temporary file for OpenCode.

Each run also receives a temporary immutable sidecar bundle containing
`execution.md`, `contract.json`, `handoff.json`, `artifacts.json`,
`verification.json`, hashed attachments, and a bundle manifest. Inputs are
read-only and verified before and after provider execution. Required attachment
paths must resolve directly to regular local files whose hashes still match;
symbolic links are rejected before resolution.

Automatic continuations use the configured four-hour continuation command
safety limit. They do not impose a shorter five-minute cutoff. If the safety
limit is reached, repository changes remain in place and the UI directs the
user to review that partial work before retrying. For Codex, the exact thread
link is preserved on both successful and failed runs so partial activity
remains inspectable.

OpenCode's `--file` flag consumes multiple values, so the continuation message
is placed before the final `--file <execution.md>` pair. DaemonState does
not infer an OpenCode subscription or inherit OpenCode's possibly stale
last-used model. Set `DAEMONSTATE_OPENCODE_MODEL` to an explicit
`provider/model`, or pass a provider model in the continuation request. The
readiness check requires a matching connected provider before enabling the
run. Structured provider errors are treated as failed runs even when a
provider CLI exits with status zero.

For Codex, DaemonState prefers the current desktop-bundled executable when
the PATH candidate is an older npm-global wrapper. Set
`DAEMONSTATE_CODEX_EXECUTABLE` to an absolute executable path to override
that selection. A model/CLI incompatibility is reported as
`provider_cli_update_required`, including the provider's upgrade action,
instead of being collapsed into a generic exit-code failure.

Provider processes receive a minimal allowlisted environment plus only the
authentication variables required by that provider. Server secrets are not
forwarded. Local HTTP execution and provider-readiness endpoints require a
numeric loopback client, and the bundled start script binds to `127.0.0.1` by
default.

Commands imported from earlier sessions remain untrusted evidence and are never
replayed automatically. Continue runs only verifier argv compiled into the
typed execution contract. A command is linked to a requirement only through an
explicit requirement ID, exact path lineage, or an explicit request to run that
test; generic token overlap cannot create proof. Browser, screenshot, and event
verifiers can be command-backed and produce normal observed evidence. The
separate `daemonstate harness run` developer tool also compiles the canonical execution
contract and retains an explicit `--verify` flag because it wraps arbitrary
user-supplied commands.

For change tasks, a failed but recoverable verifier can trigger at most two
targeted repairs in the same provider session. Each repair prompt retains the
canonical request and includes only controller-observed unmet requirements and
evidence. The controller stops on a non-recoverable boundary, bundle or
preservation failure, provider loss, or an unchanged requirement/fingerprint
signature. Pre-existing text changes may receive additive work only while their
original changed lines remain; reverting or deleting that baseline fails the
preservation gate. Binary files, symlinks, and read-only tasks remain exact.

An exited provider process and its own success summary are not proof. Every MUST
requirement is assessed from observed verifier evidence. Runtime outcomes
distinguish:

- `verified_complete`: every MUST requirement has passing required evidence,
  the worker completed, the runtime bundle is intact, and the repository
  preservation policy passed;
- `requirements_unproven`: the worker completed, but one or more mandatory
  requirements are missing, failed, skipped, malformed, or unsupported;
- `execution_failed`: the worker process or an ordinary execution step failed;
- `blocked_external`: authentication, billing, provider service, CLI version,
  credentials, permissions, or other external infrastructure prevented the
  selected provider from completing;
- `blocked_ambiguity`: explicit user intent is required before execution can
  proceed.

These are observed workflow outcomes. Product acceptance still requires a
paired real-task test showing that a different agent continued correctly with
no re-explanation, less discovery, and no stale-context mistake.

## Browser Surface

The Continue page calls the canonical local-only staging endpoint and exposes
one card for each target provider. Each card distinguishes ordinary provider
readiness from safe context-staging support. Continue carries the exact
selected Library session identity through preparation so an equally
worded newer session cannot replace it.
Library also binds a multi-request session card to its source-backed original
user request; the shortened card title is display-only and cannot silently
select a different request from the same session.
Selecting a ready card resolves the task, refreshes evidence,
compiles the audit pack and execution contract, applies task-specific quality
and provider capability gates, loads Context + Direction + Execution loop into
a fresh Codex thread, opens that exact thread, and waits. It does not submit a
task, claim agent activity, run verifiers, or report changed files before the
user types the new lead. There is no clipboard fallback or manual
checkpoint-review step in this primary workflow. Library, Memory, and
Evidence remain optional inspection surfaces.

## Surface Differences

- HTTP prepare is non-executing: repository path is optional, local session sync
  defaults off, and `execute_commands=true` is rejected. HTTP run is local-only,
  refreshes sessions, selects a fresh installed target, and executes checks.
- Browser Continue uses local-only HTTP stage: it refreshes and compiles, creates
  a waiting Codex thread, injects context, and starts no turn.
- CLI requires a workspace, defaults the repository to `.`, syncs by default,
  launches a selected provider only with `--into`, and verifies automatically.
- MCP requires workspace and repository, syncs by default, and returns the audit
  pack plus canonical execution contract to its calling agent without starting
  another provider process.
