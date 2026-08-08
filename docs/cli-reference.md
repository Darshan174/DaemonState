# CLI reference

The `daemonstate` CLI is installed by `bash scripts/setup.sh` and by the Python
package. In a repository checkout, either activate the virtual environment or
call the entry point directly:

```bash
source .venv/bin/activate
daemonstate --help
```

```bash
.venv/bin/daemonstate --help
```

## Command map

| Command | Purpose | Talks to running API? |
|---|---|---|
| `ingest` | Scan local files and create source documents. | Yes |
| `query` | Ask a source-backed question with indexed/live retrieval controls. | Yes |
| `graph` | Fetch the knowledge graph summary. | Yes |
| `prepare` | Compile a task-scoped `context_pack.v2`. | No; uses local services/database |
| `continue` | Resolve, compile, and optionally execute the current continuation. | No; uses local services/database and provider CLI |
| `repo index` | Inspect and optionally persist repository files/symbols. | No |
| `repo watch` | Persist bounded repository change events. | No |
| `harness run` | Run one explicit worker argv with a compiled contract and measured evidence. | No |
| `harness report` | Summarize observed local-harness outcomes. | No |
| `eval` | Run extraction or offline paired-harness evaluations. | No |
| `worker sync` | Drain or watch connector/source sync jobs. | No |
| `db` | Deploy, inspect, or change the database schema revision. | No |
| `credentials rotate` | Re-encrypt stored connector credentials. | No |
| `mcp` | Start the trusted local MCP server over stdio. | No network listener |

Commands that call the API default to `http://localhost:8000`. Pass
`--base-url` and `--api-key`, or set `DAEMONSTATE_API_KEY`, for a protected
server. Local-service commands use `DATABASE_URL` and the other settings from
the current process/`.env`; they do not proxy through the running API.

## Exit behavior

- `0` means the command's own operation succeeded.
- `1` means validation, API, compilation, execution, verification, or worker
  processing failed. For `continue --into`, a completed provider process still
  returns `1` when the observed outcome is not verified.
- `130` means an interactive continuation/harness/watch was interrupted.

Use `--json` where available for automation. Treat the schema/version fields in
JSON as the compatibility boundary instead of scraping human output.

## `daemonstate ingest`

Scan one file or directory with the generic local importer and send the
resulting documents to `/api/sources` or `/api/sources/bulk`.

```bash
daemonstate ingest ./notes --sync --json
```

Options:

| Option | Meaning |
|---|---|
| `path` | Required file or directory. The scanner rejects unreadable/unsupported input and reports when no documents were found. |
| `--base-url URL` | API base; default `http://localhost:8000`. |
| `--api-key KEY` | Bearer key for a protected API. Prefer `DAEMONSTATE_API_KEY` to avoid shell history. |
| `--sync` | Ask the API to process extraction synchronously before returning. Without it, normal source processing may be queued. |
| `--json` | Print the API response. |

The CLI preserves source content first. It does not write extracted graph facts
without a `SourceDocument`.

## `daemonstate query`

Ask a question through the stable `query.v1` API.

```bash
daemonstate query "What is blocking the release?" \
  --workspace-id <workspace-uuid> \
  --retrieval-mode combined \
  --live-source local_repo \
  --repo . \
  --json
```

| Option | Meaning |
|---|---|
| `question` | Required question. |
| `--workspace-id UUID` | Restrict evidence to one workspace. Strongly recommended. |
| `--retrieval-mode indexed` | Query persisted indexed evidence only; the default. |
| `--retrieval-mode live` | Query only requested supported live sources. |
| `--retrieval-mode combined` | Combine indexed and requested live results with provenance. |
| `--live-source local_repo` | Add the current local repository. Repeat the flag to add multiple supported types. |
| `--live-source github` | Add configured GitHub retrieval. |
| `--repo PATH` | Active indexed local repository path used by live local retrieval. |
| `--base-url`, `--api-key` | API connection/authentication controls. |
| `--json` | Print the full response, including trace and facts used. |

Live retrieval is bounded. A local path must match the workspace's indexed
repository and the configured allowed roots.

## `daemonstate graph`

Fetch `/api/graph` and print model/component/relationship counts, or the full
response with `--json`.

```bash
daemonstate graph --json
```

This is a compact API convenience command. Use the HTTP graph endpoints when
you need explicit workspace, filter, slice, inspector, or review controls.

## `daemonstate prepare`

Compile task-scoped context without starting a worker.

```bash
daemonstate prepare "fix the failing import flow" \
  --workspace-id <workspace-uuid> \
  --repo . \
  --target-model general-coder \
  --budget 6000 \
  --out .daemonstate/context.md \
  --manifest-out .daemonstate/context.json
```

| Option | Default | Meaning |
|---|---|---|
| `objective` | required | Trusted task objective. |
| `--repo PATH` | `.` | Repository to inspect. |
| `--workspace-id UUID` | none | Workspace evidence and persistence scope. |
| `--target-model NAME` | `general-coder` | Model/profile used for budget and execution-policy rendering. |
| `--budget TOKENS` | profile default | Maximum estimated rendered tokens. Compilation fails when mandatory context cannot fit. |
| `--out PATH` | stdout | Write Markdown context. Parent directories are created. |
| `--manifest-out PATH` | none | Write sorted, indented manifest JSON. |
| `--file-output-only` | false | Compile without a database session or persistence; manifest records `persistence.available=false`. Workspace database evidence is unavailable in this mode. |
| `--json` | false | Print metadata and the manifest instead of the human output. |

`prepare` emits task context, not objective-independent Workspace Context. The
Execute UI/API requests Workspace Context with `mode=project_snapshot`.

## `daemonstate continue`

Resolve the current task/session, restore or capture a compatible checkpoint,
compile the audit pack and typed execution contract, and optionally invoke a
built-in local provider adapter.

Prepare only:

```bash
daemonstate continue \
  --workspace-id <workspace-uuid> \
  --repo . \
  --out continuation.md
```

Execute in a new provider process:

```bash
daemonstate continue "finish the current fix and verify it" \
  --workspace-id <workspace-uuid> \
  --repo . \
  --into codex \
  --task-mode change \
  --provider-effort high \
  --json
```

| Option | Default | Meaning |
|---|---|---|
| `objective` | inferred | Optional new trusted objective. When omitted, resolve the active goal or latest substantive in-scope session request. |
| `--workspace-id UUID` | required | Workspace boundary. |
| `--repo PATH` | `.` | Git repository to reconcile and observe. |
| `--checkpoint-id ID` | latest compatible | Pin an exact durable checkpoint. |
| `--checkpoint-source-id UUID` | none | Required with a legacy provider-compaction checkpoint ID so its source revision can be authorized. |
| `--into PROVIDER` | none | Run `codex`, `claude`, or `opencode`. Without it, print/write the canonical execution prompt. |
| `--target-model NAME` | `general-coder` | Context compiler target/profile. |
| `--provider-model NAME` | provider default | Model passed to the provider CLI where supported. |
| `--provider-effort LEVEL` | none | Codex reasoning effort: `low`, `medium`, `high`, `xhigh`, `max`, or `ultra`. |
| `--task-mode MODE` | inferred | `change`, `diagnose`, `review`, `report`, `plan`, or `test_only`; controls execution authority. |
| `--budget TOKENS` | profile default | Context budget. |
| `--no-sync` | false | Skip the initial refresh of local Codex/Claude/OpenCode histories. |
| `--out PATH` | stdout for prepare-only | Write the canonical execution prompt. |
| `--output-limit-bytes` | `32768` | Bounded captured provider output. |
| `--command-timeout` | `3600` | Provider command timeout in seconds for this invocation. |
| `--verification-timeout` | `900` | Per verification phase/command timeout as applied by the runtime. |
| `--json` | false | Print preparation, delivery, run, outcome, and attention records. |

The built-in adapters execute argv directly, never through a shell, and never
add permission-bypass flags. The runtime protects pre-existing Git state,
captures bounded output, links verifiers to requirements, and distinguishes
verified completion from a provider's exit or self-report.

## `daemonstate repo index`

Inspect a repository with the bounded, Git-aware indexer.

```bash
daemonstate repo index . --workspace-id <workspace-uuid> --json
```

| Option | Meaning |
|---|---|
| `path` | Repository path; default `.`. |
| `--workspace-id UUID` | Persistence scope for code files, symbols, edges, and repository evidence. |
| `--no-persist` | Return a frame without database writes. |
| `--json` | Print the repository manifest plus indexed file/symbol counts. |

Indexing reads files within configured bounds and derives syntax/structure. It
does not run the repository's scripts or tests.

## `daemonstate repo watch`

Poll one repository and persist bounded change events.

```bash
daemonstate repo watch . \
  --workspace-id <workspace-uuid> \
  --poll-interval 2 \
  --debounce 0.5
```

| Option | Meaning |
|---|---|
| `--workspace-id UUID` | Required persistence scope. |
| `--poll-interval SECONDS` | Delay between snapshots. |
| `--debounce SECONDS` | Quiet period used to coalesce a burst. |
| `--once` | Perform one poll cycle and stop. |
| `--max-cycles N` | Stop after a bounded number of cycles; useful for tests and automation. |
| `--json` | Emit one JSON repository-event record per observed change plus the final result. |

The watcher observes; it does not stage, commit, revert, or execute changes.

## `daemonstate harness run`

Compile context, create a durable run, and execute one explicit worker argv.

```bash
daemonstate harness run "fix the task and add focused tests" \
  --workspace-id <workspace-uuid> \
  --repo . \
  --target-model qwen2.5-coder-7b \
  --task-mode change \
  --budget 4000 \
  --verify \
  -- your-worker --context {context_file}
```

Everything after `--` is passed as argv without shell interpolation. An exact
`{context_file}` element becomes the path to the permission-restricted generated
brief.

| Option | Meaning |
|---|---|
| `objective` | Required trusted task objective. |
| `--workspace-id UUID` | Required workspace/run scope. |
| `--repo PATH` | Git repository; default `.`. |
| `--target-model NAME` | Worker model/profile label and compiler profile. |
| `--task-mode MODE` | Explicit authority mode. |
| `--budget TOKENS` | Context budget. |
| `--run-key KEY` | Optional workspace-level duplicate guard. A new key is generated when omitted. |
| `--tool LABEL` | Stored worker/tool name; default `local-harness`. |
| `--verify` | Explicitly authorize required verification commands from the pack. Without it, the worker still runs but checks are not executed. |
| `--output-limit-bytes`, `--command-timeout`, `--verification-timeout` | Bounded execution controls. |
| `--json` | Print the full measured result. |

The worker receives `DAEMONSTATE_PACK_PATH`, `DAEMONSTATE_PACK_ID`,
`DAEMONSTATE_RUN_ID`, `DAEMONSTATE_MODEL_PROFILE`, and the linked execution ID.
See [Local Agent Harness](agent-harness.md) for the outcome/evidence contract.

## `daemonstate harness report`

```bash
daemonstate harness report --workspace-id <workspace-uuid> --json
```

Groups observed local-harness runs by recorded model and model profile. A
verified-success count requires observed completion, required passing evidence,
and no unresolved recorded blocker. It is descriptive, not causal.

## `daemonstate eval`

Run deterministic extraction fixtures:

```bash
daemonstate eval extraction --json
```

Evaluate offline paired harness rows:

```bash
daemonstate eval harness \
  --input experiment.json \
  --minimum-directional-tasks 10 \
  --json
```

The paired evaluator expects each task to contain `old_alone`,
`old_with_daemonstate`, and `new_alone` rows with structured outcome evidence.
Below the configured complete-triplet threshold it reports
`insufficient_evidence`; reaching the threshold produces only a directional
claim. It does not resolve caller-supplied evidence IDs against stored runs.

## `daemonstate worker sync`

Drain once:

```bash
daemonstate worker sync --limit 10 --json
```

Run continuously:

```bash
daemonstate worker sync --watch
```

Options control the poll interval, lease, retry bounds, worker ID, batch limit,
and dead-letter redrive. Before work, the command verifies the database schema
when automatic migration is disabled; production also validates encrypted
connector credentials. Watch mode maintains the configured health heartbeat
and optional worker metrics port.

## `daemonstate db`

| Subcommand | Purpose |
|---|---|
| `db deploy [--database-url URL]` | Supported deployment gate: obtain the migration lock, reconcile an unversioned legacy install once, run immutable Alembic revisions, and rotate/populate credentials as required. |
| `db upgrade [revision]` | Run Alembic upgrade, defaulting to `head`. |
| `db current` | Print current Alembic revision. |
| `db history` | Print revision history. |
| `db stamp-head` | Mark a database at head without running migrations. Use only when an operator has independently proved the physical schema already matches; misuse can corrupt the migration contract. |

Use `db deploy` for Compose and production startup. Back up data and stop
writers before manual schema operations.

## `daemonstate credentials rotate`

```bash
daemonstate credentials rotate --database-url <optional-url>
```

Re-encrypt connector credentials with the primary `ENCRYPTION_KEY`, accepting
keys listed in `PREVIOUS_ENCRYPTION_KEYS` for reads. The command reports scanned,
updated, and encrypted counts. Retain old keys until rotation and restore tests
succeed.

## `daemonstate mcp`

Start the MCP server over process stdio:

```bash
daemonstate mcp
```

This command is intended to be launched by an MCP client. Do not run it behind
an HTTP listener. It can prepare/query context and record evidence through
application services; it cannot edit code, run shell commands, push commits, or
write to external providers. See [MCP](mcp.md) and
[examples/mcp](../examples/mcp/).
