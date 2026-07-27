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
   substantive request from an in-scope session.
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

`POST /api/continuations/run` and `daemonstate continue --into ...` continue that
sequence by starting a local provider CLI, observing repository changes, and
running the pack's verification contract after the provider exits. The HTTP run
endpoint is local-only. The browser exposes Codex, Claude Code, and OpenCode as
separate targets with live installation and authentication readiness. An
explicit target never falls back to another provider. `auto` considers only
ready providers in a stable order; it does not switch providers merely because
one produced the source session. Readiness is checked again immediately before
launch.

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
current non-provider checkpoint blockers fail closed. Historical provider-auth
failures remain scoped evidence; live provider readiness is authoritative for a
new run.

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

- `verified`: the provider completed and at least one required check ran and
  passed;
- `completed_unverified`: the provider completed, but no executable checks were
  available;
- `blocked`: authentication or another actionable prerequisite prevented the
  selected provider from running;
- `failed`: the provider or a required check failed.

These are observed workflow outcomes. Product acceptance still requires a
paired real-task test showing that a different agent continued correctly with
no re-explanation, less discovery, and no stale-context mistake.

## Browser Surface

The Continue page calls the local-only composite run endpoint and exposes one
card for each supported target provider. Each card reports local execution
readiness. Selecting a ready card resolves the task, refreshes evidence,
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
