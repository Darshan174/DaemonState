# Local Agent Harness

The harness wraps one local worker command. It gives the worker a task brief and
records what happened; it does not decide or perform the work itself.

## What It Does

`ctxe harness run`:

1. compiles and persists `context_pack.v2` for the selected workspace, repo,
   objective, target model, and token budget;
2. creates a linked `AgentRun`;
3. writes the brief to a permission-restricted temporary file;
4. runs exactly the argv supplied after `--`, without shell interpolation;
5. captures bounded, redacted stdout/stderr and Git state before and after;
6. records the observed command, changed paths, verification results, and
   terminal outcome as durable source-backed run evidence;
7. updates unresolved work and creates playbook candidates from the recorded run.

The worker receives:

- `CONTEXT_ENGINE_PACK_PATH`
- `CONTEXT_ENGINE_PACK_ID`
- `CONTEXT_ENGINE_RUN_ID`
- `CONTEXT_ENGINE_MODEL_PROFILE`

An exact `{context_file}` argv element is replaced with the temporary brief path.

## Usage

```bash
ctxe harness run "fix the selected task and add focused tests" \
  --repo . \
  --workspace-id <workspace-uuid> \
  --target-model qwen2.5-coder-7b \
  --budget 4000 \
  --verify \
  -- your-worker --context {context_file}
```

`--verify` is explicit authorization to execute required verification commands
from the compiled pack. Without it, the worker still runs and the outcome is
recorded, but deterministic scrutiny can mark the finish unverified. Verification
uses direct argv execution, stops on the first required failure, honors only
working directories inside the repository, and records real exit codes.

The model profile also adds an `agent_execution_policy.v1` section to the
manifest and brief. Smaller-model profiles require a short plan, fewer files per
step, final diff review, verification evidence, fewer retries, and context refresh
before retry. These are explicit worker instructions and audit policy; a generic
wrapper cannot prove that a provider internally followed its planning instruction.

## Outcome Reporting

```bash
ctxe harness report --workspace-id <workspace-uuid> --json
```

The report groups local-harness runs by their recorded model and model profile.
Verified success requires a harness-recorded successful outcome, passing evidence
for every required check, and no unresolved recorded blocker. The report is
descriptive evidence, not proof that Context Engine caused the result.

## Paired Evaluation

```bash
ctxe eval harness --input experiment.json --json
```

Each task must contain one row for `old_alone`, `old_with_context_engine`, and
`new_alone`. Every row must carry structured completion, verification, blocker,
and evidence identifiers. The evaluator reports solve-rate, cost/time summaries,
and paired wins/losses. Fewer than ten complete task triplets are labelled
`insufficient_evidence`; ten or more are only `directional`. Evidence identifiers
are caller-supplied and are not resolved against stored runs by this offline
command. It never produces an automatic model-parity or causal claim.

Example row:

```json
{
  "task_id": "auth-fix-01",
  "label": "old_with_context_engine",
  "cost_usd": 0.08,
  "duration_seconds": 94,
  "outcome_evidence": {
    "completed": true,
    "verification_passed": true,
    "unresolved_blockers": 0,
    "evidence_ids": ["run-observation-id", "verification-source-id"]
  }
}
```

## Current Limits

- The user still chooses and configures the worker command.
- There are no built-in Codex, Claude Code, Hermes, or OpenCode launch adapters.
- Captured output is deliberately bounded; it is not terminal playback.
- On POSIX systems the runner kills the worker process group on timeout or
  cancellation. Process-tree cleanup is best effort on other platforms.
- Repository observation is bounded to 500 paths and hashes at most 1 MiB per
  file.
- Automatic experiment assignment and policy optimization are not implemented.
