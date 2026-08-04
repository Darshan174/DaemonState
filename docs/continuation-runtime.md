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
contains the task-local child state, while Project / Workspace Context contains
the workspace-wide parent. “Workspace Context” is the delivery-surface label
for the same Project Context, not a third context product.

**Session Context is the child.** It captures the latest individual session's
task-level working memory: the current goal and acceptance criteria, completed
and in-progress state, exact next step, active decisions and reasoning,
failed or rejected attempts and their evidence, changes and discoveries,
meaningful commands and results, verification state, blockers and risks,
assumptions and open questions, fixes and confirmation, scope and non-goals,
and current repository state.

| Artifact | Scope and purpose | Behavior |
|---|---|---|
| **Session Context** | The task-specific child captured from one session's latest immutable tip. It records that session's current working state and its relationship to the Project Context parent. Repository freshness is checked at handoff time and the current snapshot is used when available. | Continue always selects the newest available session, renders the canonical `session_handoff.v1` artifact, copies it, requests a visible composer in the selected desktop app, and waits for the user to submit. Historical Library sessions and recovery points route through Prepare or Execute and never override Continue. |
| **Project / Workspace Context** | The durable parent foundation shared by every session in the workspace. It is compiled from all current workspace evidence without using the current prompt, objective, file overlap, selected session, or task ranking. Durable project facts and syntax-level repository observations remain separate. | Mechanically verified, human-confirmed, and corroborated durable facts may enter the current parent. Provisional claims stay outside it; superseded or conflicting facts remain historical. Its separate rendering remains `continuation_staging_context.v1`. |
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
contains the latest task state and an explicit parent-child boundary, plus only
the task-relevant evidence-backed workspace facts it inherits. Project /
Workspace Context remains the separately rendered objective-independent parent.
Event numbers, capture timestamps, selection scores, full dirty-file
inventories, and other audit metadata remain in the structured contract or
Audit ContextPack. A generic “continue the current request” record cannot
reopen a requirement with a newer scoped completion claim. Prior-agent
interpretations that make a deictic request self-contained are retained only as
explicitly unverified historical scope.

### Compact Session Context experiment

The visible Continue handoff has two render variants behind
`SESSION_HANDOFF_BRIEF_VARIANT`:

- `compact_v2` is the default with exactly five sections: Goal, State now,
  Start here, Do not repeat, and Done when.
- `legacy_v1` remains available only as an immediate rollback.

Both variants use the same `session_handoff.v1` structured contract, repository
freshness checks, attachment hashes, copy gate, and protected-baseline policy.
Only the model-facing projection changes; automatic execution prompts remain on
their existing renderer so the experiment is not confounded across two paths.
Every staged response records `context_render_variant`, `context_char_count`,
and `context_estimated_tokens` alongside the context hash.

The paired replay justified promoting the compact projection as the reversible
default. Retain it only with zero critical-state omissions or
authority/preservation regressions, at least 80% correct first actions, at least
a 15-point gain over the control, 30% fewer rediscovery steps, and fewer than
10% repeated failed approaches across at least 30 comparable submitted tasks.
Desktop staging creates no `AgentRun` before the user submits, so delivery and
prompt-size telemetry alone cannot prove product success; the submitted
provider session must be linked to observed outcomes before those behavioral
gates can be evaluated. Set the variant to `legacy_v1` immediately if a safety
or action-selection regression appears.

The initial read-only paired replay and its limitations are recorded in
`docs/experiments/session-handoff-brief-v2-2026-08-03.md`. Re-run the same
comparison with `scripts/compare_session_handoff_variants.py`; it uses identical
saved checkpoints and contracts for both renderers and does not stage or launch
a provider session.

Repository evidence uses fixed, non-prose item shapes for symbol declarations,
exact test links, and parsed manifest dependencies. Every item is bound to the
repository snapshot and live file SHA-256; stale items are omitted. These
observations help the receiving model orient itself, but they do not claim code
behavior or architectural intent.

The browser actions are literal: **Preview** displays rendered context, **Copy**
writes user-controlled context to the clipboard, and **Continue** copies the
latest Session Context and opens a new, visible composer in the selected desktop
app. When the native deep link is within its bounded size, the composer is also
prefilled. Otherwise the app opens with the complete context still on the
clipboard and an explicit paste instruction. Nothing presses Enter or submits a
user turn.

The optional [macOS floating context control](floating-context-control.md) is a
separate native delivery surface. It can copy and synthesize Command-V into the
editor that retained focus, but it never presses Enter and does not weaken the
same context identity, quality, or hash checks.

Direct copy paths fail closed. Session Context requires
`quality_report.copy_ready=true`; Project Context requires
`project_context.copy_ready=true`. Superseded session boundaries, unresolved
referenced conversations, incomplete repository snapshots, missing required
artifacts, contradictory authority, and malformed handoff sections remain
previewable with explicit issues but cannot be copied. Automatic execution has
the stricter `automatic_execution_ready`/`launchable` gates.

Project Context direct copy and automatic execution also fail closed when its core purpose, workflow,
architecture, or repository sections are empty; a statement lacks hash-bound
provenance; current facts conflict; generic inventory dominates; or its
foundation fingerprint is stale relative to the repository. Headings alone do
not satisfy this gate. Visible desktop Continue may carry an incomplete-core
Workspace Context only as inherited background inside an explicitly warned,
user-reviewed Session Context draft; it still cannot submit or begin execution.
Every integrity, freshness, provenance, and conflict failure remains blocking.
An entirely empty parent is explicitly **not ready** and is never inherited or
staged.

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
`POST /api/continuations/stage` endpoint for the lossless user lead resolved
from the newest source session, but starts no provider turn. URL objective,
source-session, and recovery-point parameters cannot replace that selection.
Historical or manually chosen work is routed through Prepare or Execute.

Browser Continue never invokes `codex exec`, `claude --print`, `opencode run`,
or any method that starts a provider turn. Its bounded readiness check may use
Codex app-server's read-only `account/read`, `model/list`, and
`account/rateLimits/read` methods; it never calls `thread/start` or
`turn/start`. The handoff copies the complete canonical `session_handoff.v1`
rendering for the latest session, then uses only the selected app's registered
macOS URL scheme:

- Codex: `codex://threads/new`
- Claude Desktop: `claude://code/new`
- OpenCode Desktop: `opencode://new-session`

The native link requests a new composer with the project directory and bounded
prompt. It does not create a provider session ID that DaemonState can truthfully
persist before submission. The API therefore returns a handoff ID, context
hash, `execution_started=false`, `context_loaded=false`, and
`navigation_verified=false`. It reports whether prefill was requested and
whether the complete context was copied; it never claims that the destination
rendered. The user checks the requested desktop composer, pastes the copied
context if necessary, reviews it, and submits it explicitly.

Submitting the unchanged Continue draft activates the carried current goal from
its exact next action; a newer user-authored instruction overrides that goal.

Stage requires an idempotency key. Before requesting the app open, it commits a
durable reservation keyed by workspace and that key. Repeated, concurrent, or
reloaded same-key requests replay the stored success or failure and never
dispatch a second desktop open request. This ledger is handoff state only: it
does not create an `AgentRun` or invent a provider session ID.
The browser keeps an unresolved request key in session storage across reloads
and provider switches. It clears that key only after a known terminal result,
or after showing the user an explicit unknown-outcome warning.

Because dispatch is not proof that the composer rendered, a successful request
does not permanently lock Continue. The selected card exposes an explicit
**Request again** action; that deliberate new action gets a new idempotency key,
while double-clicks and same-key retries remain deduplicated. A newer failed or
pending request also prevents an older successful request from being restored
as the current handoff. A pending reservation expires after 60 seconds so a
crash cannot lock Continue forever. The first retry after expiry reports the
earlier open outcome as uncertain and sends nothing; after the user checks the
desktop app, a second explicit **Request again** may create a new request.

Provider readiness for the browser has
`readiness_scope=desktop_dispatch_with_account_evidence`. Installation plus a
registered native URL handler is the hard gate because Continue only opens a
reviewable draft; it does not submit a request. Missing applications and URL
handlers remain blocking. Account evidence is reported separately and never
requires a user attestation before the desktop app can open.

For Codex, the product asks the local app-server for the signed-in account,
account-scoped model list, and explicit rate-limit status. These methods return
structured status without exposing tokens or requiring DaemonState to inspect
credential files directly. A signed-in account with a live model list is
recorded as
`account_access_state=verified`,
`account_access_basis=provider_desktop_bridge`, and
`account_access_verified=true`. Signed-out, rate-limited, or inconclusive
results are shown on the card but do not block loading the draft; Codex remains
the final authority when the user sends.

Claude Desktop and OpenCode currently verify their own account or provider
access when the user sends. OpenCode may use Go, Zen credits, another connected
provider, or a local model, so installation alone is never relabelled as
verified account access. Neither card asks the user to attest to access before
opening.

Each local readiness probe is bounded to three seconds, and the browser aborts
the readiness request after ten seconds rather than leaving cards in an
indefinite Checking state. If the live Codex model probe is unavailable, model
and reasoning-effort controls may fall back to its fresh, non-secret desktop
model cache. Cached selector metadata is not relabelled as account proof. The
chosen values remain delivery metadata and visible card state; they are never
prepended or injected into the model-visible Session Context. Because the
native desktop deep link cannot apply them, the card asks the user to review
the requested settings in Codex Desktop before submitting.

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
one card for each target provider. Each card reports the selected desktop app's
installation and visible-handoff readiness. Continue carries the exact newest
session identity through preparation; URL state, a Library selection, or a
saved recovery point cannot replace it. Library routes historical session and
topic choices to Prepare, while Execute owns explicit multi-session context.
Provider readiness starts immediately. In parallel, Continue uses
`POST /api/session-library/latest` to enumerate local history metadata,
resolve newest-first, and ingest only the newest eligible root session. The
filesystem work runs off the API event loop, the response omits the historical
library, and checkpoint/component backfills remain outside the page-load path.
Continue becomes runnable from that exact session identity without waiting for
the broader digest or evidence views. If latest-session discovery fails—or
returns no eligible session—Continue stays disabled instead of falling back to
an older indexed session.
Selecting a ready card resolves the latest session task, refreshes evidence,
compiles the audit pack and execution contract, applies task-specific quality
gates, copies the canonical Session Context, and requests the selected Codex,
Claude, or OpenCode desktop app's native new-composer route. A bounded native prefill is
requested; the clipboard remains the complete, non-truncated fallback. Scheme
registration and Launch Services dispatch do not prove route rendering. It
does not submit a task, claim agent activity, run verifiers, or report changed
files before the user submits the draft. Library, Memory, and Evidence remain
optional inspection surfaces.

## Surface Differences

- HTTP prepare is non-executing: repository path is optional, local session sync
  defaults off, and `execute_commands=true` is rejected. HTTP run is local-only,
  refreshes sessions, selects a fresh installed target, and executes checks.
- Browser Continue uses local-only HTTP stage: it compiles without scanning
  provider session stores, copies the complete context, requests the selected
  desktop app and new-composer route, and starts no provider process or turn.
- CLI requires a workspace, defaults the repository to `.`, syncs by default,
  launches a selected provider only with `--into`, and verifies automatically.
- MCP requires workspace and repository, syncs by default, and returns the audit
  pack plus canonical execution contract to its calling agent without starting
  another provider process.
