# Continuation Runtime

The continuation runtime is the primary product path. It composes existing
session ingestion, durable checkpoints, repository verification, the context
compiler, and local run evidence into one operation.

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
6. Compile `context_pack.v2` with the selected checkpoint as source-backed
   restored context.
7. Persist stable task identity, checkpoint identity, verification state, and
   current repository fingerprint in the pack manifest and replay key.

`POST /api/continuations` and `daemonstate continue --into ...` continue that
sequence by starting a local provider CLI, observing repository changes, and
running the pack's verification contract after the provider exits. The HTTP run
endpoint is local-only. `POST /api/continuations/run` remains a compatibility
alias. The browser exposes Codex, Claude Code, and OpenCode as
separate targets with live installation, authentication, and visible-session
readiness. A provider is runnable only when Context Engine can show the exact
executing session in that provider's local harness. An explicit target never
falls back to another provider. `auto` considers only ready providers in a
stable order; it does not switch providers merely because one produced the
source session. Readiness is checked again immediately before launch.

For a browser-selected Codex run, Context Engine drives the documented Codex
app-server thread/turn protocol. The app-server persists the thread first,
accepts the turn, and then emits a visibility-ready event. Only after that
boundary does Context Engine request
`codex://threads/<thread-id>` navigation, avoiding the blank-screen race caused
by deep-linking an unindexed `codex exec` rollout. The Continue screen polls
that durable link and offers **Open Codex run** during and after execution, so
the user can inspect the real executing harness thread instead of watching an
anonymous spinner. A successful macOS `open` call records that navigation was
requested; it is not mislabeled as proof that the destination rendered.

Codex model and reasoning-effort controls are populated from the installed
Codex model catalog. Claude Code and OpenCode remain monochrome and disabled
unless both provider access and an exact visible-session route are available;
generic app or project navigation is not sufficient.

Continuation turns have a four-hour default execution window so substantive
desktop-visible work is not killed at the former one-hour boundary. Operators
can override it with `CONTINUATION_COMMAND_TIMEOUT_SECONDS`.

The context pack is provider-neutral. Switching from Codex to Claude Code or
OpenCode carries the same bounded goal, decisions, learnings, failed attempts,
blockers, repository state, verification plan, freshness, and provenance into a
fresh target session. It does not invent provider-native conversation history
that never happened.

Agent-reported progress and decisions remain reported evidence. Matching
repository state proves freshness of the observed snapshot, not the truth of
every statement made by an earlier agent.

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

A verified run advances only the exact source-backed task that executed.
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
always runs the pack's verification contract after the provider exits and has
no manual verification switch.

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

Provider commands are direct argv invocations. Codex uses a workspace-write
sandbox. Claude Code and OpenCode retain their installed permission settings;
no adapter adds bypass, danger, or automatic approval flags. Context delivery
is bounded to 1 MiB and uses stdin for Codex/Claude Code or a
permission-restricted temporary file for OpenCode.

Automatic continuations inherit the local harness's one-hour command safety
limit. They do not impose a shorter five-minute cutoff. If the safety limit is
reached, repository changes remain in place and the UI directs the user to
review that partial work before retrying. For Codex, the exact thread link is
preserved on both successful and failed runs so partial activity remains
inspectable.

OpenCode's `--file` flag consumes multiple values, so the continuation message
is placed before the final `--file <context-pack>` pair. Context Engine does
not infer an OpenCode subscription or inherit OpenCode's possibly stale
last-used model. Set `CONTEXT_ENGINE_OPENCODE_MODEL` to an explicit
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
replayed automatically. Continue runs only the compiler's structured
verification contract. The separate `daemonstate harness run` developer tool retains
an explicit `--verify` flag because it wraps arbitrary user-supplied commands.

An exited provider process is not automatically a proven handoff. Runtime
outcomes distinguish:

- `verified`: the provider produced an observed repository change and at least
  one required check ran and passed;
- `completed_unverified`: the provider completed, but no executable checks were
  available, checks failed, or passing checks did not accompany an agent
  repository change;
- `blocked`: authentication or another actionable prerequisite prevented the
  selected provider from running;
- `failed`: the provider or a required check failed.

These are observed workflow outcomes. Product acceptance still requires a
paired real-task test showing that a different agent continued correctly with
no re-explanation, less discovery, and no stale-context mistake.

## Browser Surface

The Continue page calls the canonical local-only composite run endpoint and exposes one
card for each supported target provider. Each card reports local execution
readiness. Continue carries the exact selected History/Library session identity
through preparation so an equally worded newer session cannot replace it.
History also binds a multi-request session card to its source-backed original
user request; the shortened card title is display-only and cannot silently
select a different request from the same session.
Selecting a ready card resolves the task, refreshes evidence,
compiles the pack, starts a fresh target agent, runs available checks, and shows
the observed outcome. Verified results also show the recomputed `Now`,
`Blocked`, `Next`, and `Paused` queue. There is no clipboard fallback or manual
checkpoint-review step in this primary workflow. Library, History, Memory, and
Evidence remain optional inspection surfaces.

## Surface Differences

- HTTP prepare is non-executing: repository path is optional, local session sync
  defaults off, and `execute_commands=true` is rejected. HTTP run is local-only,
  refreshes sessions, selects a fresh installed target, and executes checks.
- CLI requires a workspace, defaults the repository to `.`, syncs by default,
  launches a selected provider only with `--into`, and verifies automatically.
- MCP requires workspace and repository, syncs by default, and returns the pack
  to its calling agent without starting another provider process.
