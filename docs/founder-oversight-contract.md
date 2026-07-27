# Founder Oversight Vertical-Slice Contract

Status: Implemented P0 contract for the 2026-07-14 founder-oversight milestone.
The final section still separates follow-on proposals from this shipped slice.

## Scope and product boundary

Implement one loop inside the existing Project map:

`select evidenced Component -> prepare context_pack.v2 -> observe one agent run -> show factual timeline -> compute evidence-backed attention findings`

This slice does not introduce a universal `WorkItem`, a new route, a readiness
score, raw terminal playback, autonomous code review, or free-form criticism.

## Observed baseline

- `Component` is the existing atomic project fact and already carries
  `workspace_id`, `fact_type`, `status`, `source_document_id`, optional `claim_id`,
  provenance, and excerpt (`app/models.py`, `Component`). It is the focus anchor;
  there is no need for another task abstraction.
- `ContextPack` persists objective, manifest, markdown, repository state, and a
  unique compiler idempotency key. `ContextPackItem` already links selected
  Components, claims, evidence spans, and source documents (`app/models.py`,
  `ContextPack`, `ContextPackItem`). A pack does not currently identify its focus
  or objective origin.
- `ContextCompiler.compile_context_pack()` accepts free text and
  `objective_kind` of `observed` or `project_snapshot`, then uses the same compiler
  for HTTP and MCP (`app/services/context_compiler.py`). It does not pin a selected
  Component as mandatory context.
- `POST /api/context/prepare` requires `objective`/`goal`; its Pydantic models live
  in `app/api/context.py`. The task brief's `app/schemas.py` path is stale: that
  file does not exist.
- MCP exposes `record_agent_run_start`, `record_agent_event`,
  `record_patch_summary`, `record_blocker`, and `record_agent_run_finish`
  (`app/mcp/server.py`, `list_tools`). `AgentRun` links to a pack.
  `RunObservation` links to source evidence but has no stable event key or
  structured payload (`app/models.py`).
- Terminal finish uses `ingest_source_document_revision()` with stable external ID
  `agent_run_outcome:{run_id}` and a one-outcome index. General observations use a
  random external ID in `_record_observation()`, so identical retries duplicate
  evidence. A second finish returns `agent_run_already_finished` rather than the
  original successful result (`app/mcp/server.py`, `_record_agent_run_finish`,
  `_record_observation`; `tests/test_mcp.py`).
- `ingest_source_document_revision()` already provides immutable revisions and
  identical-content reuse. `IngestionService.process_document()` is the normal
  source-to-claim/component projection path (`app/services/source_revisions.py`,
  `app/services/ingest.py`). Runtime helpers currently bypass that path for some
  projections.
- `GET /api/context/digest` returns cards, objective, health, and recommendations.
  `_digest_objective()` derives the latest running objective or non-snapshot pack;
  `_digest_health()` exposes an opaque `agent_ready_score` (`app/api/context_digest.py`).
- The Project map has one modal inspector. The toolbar compiles a generic snapshot
  and labels it `Copy handoff`; the inspector displays summary, source evidence,
  and relationships but has no prepare action or run timeline
  (`frontend/src/pages/ContextMapPage.jsx`, `DigestBoard.jsx`,
  `ContextInspector.jsx`). Existing tests cover these current states.

## Exact persistence changes

Add only the following nullable/backward-compatible columns. New writes must
populate them; old rows remain readable.

### `context_packs`

| Column | Type | Contract |
| --- | --- | --- |
| `focus_component_id` | UUID FK `components.id`, nullable, indexed | Exact selected Component; null for project snapshots and legacy packs. |
| `objective_origin` | varchar(32), nullable, indexed | New values: `trusted_human`, `source_component`, `project_snapshot`; null means legacy/unknown and must not be relabelled. |
| `objective_source_document_id` | UUID FK `source_documents.id`, nullable | Required for `source_component`; exact source revision used at prepare time. |
| `objective_evidence_span_id` | UUID FK `evidence_spans.id`, nullable | Best exact supporting span when one exists; null is honest when the selected Component only has source-document provenance. |

Application validation, not a database check, enforces:

- `source_component` requires all of `focus_component_id` and
  `objective_source_document_id`;
- `trusted_human` requires non-empty request objective;
- `project_snapshot` requires `mode=project_snapshot` and no focus;
- a focused pack and its Component/source evidence share one workspace.

### `agent_runs`

Add `run_key varchar(255) nullable`. Add a partial unique index on
`(context_pack_id, run_key)` where `run_key IS NOT NULL`. New MCP start calls
require `run_key`; legacy rows remain null.

The start identity payload is compact, key-sorted JSON of `context_pack_id`,
`tool`, `model`, `branch`, `base_commit`, and `objective`. A retry under the same
key compares every field; a key match alone is not sufficient.

### `context_pack_items`

Add `manifest_item_id varchar(255) nullable` with a partial unique index on
`(context_pack_id, manifest_item_id)` where it is non-null. New packs persist the
existing `context_pack.v2` candidate `id` here so runtime completion evidence can
reference an exact pack item. Legacy rows remain null and use the stored manifest
for audit only.

### `run_observations`

| Column | Type | Contract |
| --- | --- | --- |
| `event_key` | varchar(255), nullable | Harness-supplied stable identity within one run. Required for new writes. |
| `payload_json` | text, non-null, default `'{}'` | Canonical JSON object containing the factual structured payload used by timeline/scrutiny. |
| `observed_at` | datetime, nullable, indexed | Harness occurrence time, defaulting to server receipt time. `created_at` remains transaction time. |

Add a partial unique index on `(agent_run_id, event_key)` where
`event_key IS NOT NULL`. Keep the current one-terminal-outcome index.

Runtime observations are immutable. The same key and byte-equivalent canonical
payload is an idempotent retry and returns the original IDs. The same key with a
different payload returns `event_identity_conflict` and writes nothing. A genuine
correction uses a new event key and may include `corrects_event_key` in
`payload_json`; both source records remain durable.

## Focused preparation contract

### Supported focus

A Component is eligible only when:

- its `fact_type` is one of `task`, `requirement`, `decision`, `blocker`;
- it belongs to the requested workspace;
- it is backed by the current immutable `SourceDocument` revision;
- its status is not `rejected`, `resolved`, or `superseded`.

`source_component` is an explicit user choice, not an inference. The server uses
the normalized selected `Component.value` as the objective and stores the exact
Component and source revision. It must not promote a neighboring or arbitrary
card into an objective.

### HTTP request

Extend `ContextPrepareRequest` in `app/api/context.py`:

```json
{
  "workspace_id": "2a5d9188-2fcb-4d49-a997-b13042eed79b",
  "repo_path": "/repo/daemonstate",
  "mode": "task",
  "focus_component_id": "0d08db3d-a187-48ee-9d42-c2196db1ab5f",
  "objective_origin": "source_component",
  "objective": null,
  "target_model": "gpt-5",
  "token_budget": 4000
}
```

`ContextDigest` also gains a compact `oversight` object for the existing Project
bar. It is derived from the latest non-snapshot focused pack in the workspace:

```json
"oversight": {
  "current_focus": {
    "component_id": "0d08db3d-a187-48ee-9d42-c2196db1ab5f",
    "title": "Make runtime writes retry-safe",
    "context_pack_id": "92402856-a49f-429d-917d-e7fc41ab56ad"
  },
  "state": "verification_missing",
  "latest_outcome": null,
  "attention": {"blocked": 0, "unverified": 1, "stale": 0}
}
```

With no focused pack, focus/state/outcome are null and counts are zero. This is
the only bar summary; the opaque digest readiness score is neither reused nor
rendered. The focused timeline endpoint still requires workspace and focus.

Fields:

- `objective_origin`: `trusted_human | source_component | project_snapshot`;
- `focus_component_id`: optional UUID;
- existing `objective`/`goal`, workspace, repository, model, budget, and mode remain.

Validation matrix:

| Mode/origin | Objective | Focus | Result |
| --- | --- | --- | --- |
| `task/source_component` | must be omitted | required eligible Component | Server uses selected value. |
| `task/trusted_human` | required | optional eligible Component | Human text is authoritative; focus scopes retrieval when supplied. |
| `project_snapshot/project_snapshot` | optional | forbidden | Use canonical read-only snapshot wording when omitted. |
| Any other combination | — | — | HTTP 422 `invalid_objective_origin`. |

Workspace mismatch/not found returns 404 without revealing cross-workspace data;
unsupported type/status returns 422 `focus_not_eligible`; a superseded source
revision returns 409 `focus_source_stale` with the current Component/source IDs.

### Compiler and manifest

Add keyword arguments to `ContextCompiler.compile_context_pack()`:
`focus_component_id`, `objective_origin`, `objective_source_document_id`, and
`objective_evidence_span_id`. All callers still use this compiler.

The focused Component is a mandatory selected candidate and a
`ContextPackItem`. Safety exclusions still win: if it fails workspace, current
revision, prompt-risk, or evidence-integrity checks, compilation fails with
`focus_not_eligible`; it must never silently produce an unfocused pack.

Add this required manifest object to new persisted packs:

```json
"focus": {
  "kind": "component",
  "component_id": "0d08db3d-a187-48ee-9d42-c2196db1ab5f",
  "fact_type": "task",
  "objective_origin": "source_component",
  "source_document_id": "6032b3de-f950-42c4-a458-e16f35777246",
  "source_revision_number": 3,
  "evidence_span_id": null
}
```

For project snapshots all ID fields are null and `kind` is `project_snapshot`.
The compiler replay/idempotency key includes this complete focus object.

Extend `ContextPrepareResponse` with the same `focus` object. Existing response
fields are unchanged.

### MCP prepare

Extend `prepare_task` with the same `focus_component_id` and
`objective_origin`. `goal` is optional only for `source_component`; the MCP path
passes the resolved fields to the shared compiler and returns `focus`.

## Runtime write contract

### Stable identities

- `record_agent_run_start` adds required `run_key` (1–255 characters). Identical
  retries return the original `run_id` with `deduplicated: true`; a changed payload
  under the key returns `run_identity_conflict`.
- Every observation-producing tool adds required `event_key` (1–255 characters).
  Terminal finish conventionally uses `event_key="outcome"`.
- Source external IDs are deterministic:
  `agent_runtime:{run_id}:{event_key}`. All tools call
  `ingest_source_document_revision()` before creating/projecting a
  `RunObservation`.
- New runtime rows use one canonical `source_type`, `agent_run_observation`; the
  semantic kind remains in `event_type`. Code checks `(agent_run_id, event_key)`
  before source ingestion, then relies on the unique index only as a concurrency
  backstop.
- Canonical payload JSON uses sorted keys and compact separators. It includes
  `schema_version: "run_observation.v1"`, event type, supplied timestamp when
  present, content, files, command, exit code, and type-specific fields.

Example verification event:

```json
{
  "run_id": "88985673-67ad-41a9-909f-25a43eb369c5",
  "event_key": "pytest-focused-1",
  "event_type": "verification",
  "content": "Focused MCP tests passed.",
  "files": ["tests/test_mcp.py"],
  "command": "pytest -q tests/test_mcp.py",
  "exit_code": 0,
  "observed_at": "2026-07-14T12:10:00Z"
}
```

Success responses include `run_observation_id`, `source_document_id`,
`source_revision_number`, and `deduplicated`.

Structured references use IDs, never similarity: verification may carry a
manifest `requirement_id`; patch/outcome may carry
`addresses_context_item_ids`; outcome may carry
`completed_context_item_ids`; blocker resolution requires
`resolves_event_key`. Item IDs must exist in the run's pack and the resolved key
must identify an earlier blocker in that run, otherwise the write is rejected.

### What enters extraction

After the raw source row and observation exist, call the normal deterministic
processing path for only:

| Observation | Structured requirement | Projection behavior |
| --- | --- | --- |
| `verification` | command and integer exit code | Durable verification fact; pass/fail comes only from exit code or explicit structured status. |
| `blocker` | blocker text and explicit severity | Durable blocker claim/component. |
| `patch_summary` | summary and changed file list | Durable observed-change summary. |
| `outcome` | terminal status, summary, changed files, verification results | Durable run-outcome fact. |
| `decision` | decision, rationale, evidence | Existing durable decision through normal ingestion. |
| `blocker_resolution` | resolution text and `resolves_event_key` | Durable resolution linked to one earlier blocker; the blocker source remains. |

Generic `command`, `log`, `tool`, and `note` events remain in SourceDocument and
RunObservation only. No semantic fact is extracted from ambiguous prose. A failed
projection does not roll back the raw source/observation; it records processing
failure and is retryable.

This requires two transaction phases: commit SourceDocument plus RunObservation,
then invoke deterministic processing. A projection exception returns the durable
ledger IDs with `projection_status: "failed"`; successful and intentionally raw
events return `processed` and `not_applicable` respectively.

## Timeline and scrutiny API

Add one read endpoint in `app/api/context.py`:

`GET /api/context/run-timeline?workspace_id={uuid}&focus_component_id={uuid}`

It returns focused packs newest first and at most 10 runs/100 visible events. Raw
routine events are omitted. All queries require both workspace and focus and must
scope before joining.

```json
{
  "schema_version": "run_timeline.v1",
  "workspace_id": "2a5d9188-2fcb-4d49-a997-b13042eed79b",
  "focus": {
    "component_id": "0d08db3d-a187-48ee-9d42-c2196db1ab5f",
    "title": "Make runtime writes retry-safe",
    "source_document_id": "6032b3de-f950-42c4-a458-e16f35777246",
    "source_revision_number": 3
  },
  "state": "verified",
  "latest_outcome": {
    "run_id": "88985673-67ad-41a9-909f-25a43eb369c5",
    "summary": "Idempotent runtime observations implemented.",
    "observed_at": "2026-07-14T12:14:00Z",
    "source_document_id": "ab7b1e61-d6d4-43dc-985a-3e3534597823"
  },
  "attention": {"blocked": 0, "unverified": 0, "stale": 0},
  "findings": [],
  "runs": [{
    "run_id": "88985673-67ad-41a9-909f-25a43eb369c5",
    "context_pack_id": "92402856-a49f-429d-917d-e7fc41ab56ad",
    "status": "completed",
    "state": "verified",
    "tool": "codex",
    "model": "gpt-5",
    "branch": "codex/founder-oversight",
    "base_commit": "abc123",
    "head_commit": "def456",
    "started_at": "2026-07-14T12:00:00Z",
    "ended_at": "2026-07-14T12:14:00Z",
    "events": [{
      "event_key": "pytest-focused-1",
      "event_type": "verification",
      "state": "verified",
      "observed_at": "2026-07-14T12:10:00Z",
      "summary": "Focused MCP tests passed.",
      "files": ["tests/test_mcp.py"],
      "command": "pytest -q tests/test_mcp.py",
      "exit_code": 0,
      "source_document_id": "3aa4b4ee-d24c-4654-a611-7c1d8235793e",
      "source_url": null
    }]
  }]
}
```

### Factual state vocabulary

Only these states may describe the focus/run:

`not_attempted`, `no_completion_evidence`, `verification_missing`,
`verification_failed`, `blocked`, `completed_unverified`, `verified`,
`stale_source`, `conflicting_evidence`.

Deterministic precedence is:

1. `conflicting_evidence`: a completed/success outcome and a failed required check;
2. `stale_source`: focus source is no longer the current revision;
3. `blocked`: latest unretracted blocker has no later explicit resolution;
4. `verification_failed`: any required check failed and outcome does not claim success;
5. `verification_missing`: terminal outcome exists but a required pack check has no result;
6. `verified`: successful terminal outcome and all required pack checks passed;
7. `completed_unverified`: completion evidence exists and no required check failed,
   but there is no complete verification set;
8. `no_completion_evidence`: run exists without durable outcome/patch/check/blocker;
9. `not_attempted`: no run exists for a focused pack.

A `cancelled` outcome is `no_completion_evidence` unless it carries explicit
completion evidence. A `failed` outcome without a failed required check is
`completed_unverified`. A terminal `blocked` string alone cannot create a blocker:
`blocked` requires a blocker observation or an outcome that cites its blocker.

### Computed scrutiny findings

Findings are computed from `ContextPack.manifest`, `ContextPackItem`,
`RunObservation.payload_json`, and their SourceDocuments. Do not add a findings
table in this slice. The source and observation ledger preserves history; only
currently active findings are returned. Manual dismiss/assignment is not supported.

Each finding has:

```json
{
  "id": "sha256(rule_version|pack_id|run_id|trigger_ids)",
  "rule_id": "verification.failed",
  "rule_version": 1,
  "state": "verification_failed",
  "severity": "critical",
  "title": "Required verification failed",
  "explanation": "pytest -q tests/test_mcp.py exited with code 1.",
  "next_action": "Inspect the failed check and rerun the required command.",
  "context_pack_id": "uuid",
  "run_id": "uuid",
  "focus_component_id": "uuid",
  "trigger_ids": ["run-observation-uuid"],
  "sources": [{
    "source_document_id": "uuid",
    "source_url": null,
    "excerpt": "Observed exit code: 1",
    "observed_at": "2026-07-14T12:10:00Z"
  }],
  "evaluated_at": "2026-07-14T12:15:00Z",
  "resolution_state": "open"
}
```

Initial rules and fixed severities:

| Rule | Trigger | Severity | Required wording |
| --- | --- | --- | --- |
| `verification.missing.v1` | Required manifest command has no matching result by terminal time. | warning | `Required verification has no recorded result.` |
| `verification.failed.v1` | Matching required check has exit code non-zero or structured `failed`. | critical | `Required verification failed.` |
| `blocker.unresolved.v1` | Blocker observation has no later explicit resolution referencing its event key. | critical for explicit `critical/high`, otherwise warning | `A recorded blocker is unresolved.` |
| `completion.evidence_missing.v1` | Required pack item has no cited patch, outcome, resolution, or verification evidence. | warning | `This required item has no completion evidence.` |
| `outcome.check_conflict.v1` | Outcome claims completed/success while a required check failed. | critical | `The claimed outcome conflicts with a recorded check.` |
| `source.stale.v1` | Focus source revision is not current at evaluation. | warning | `The prepared focus is based on an older source revision.` |

Matching a verification result to a requirement requires exact normalized command
equality or an explicit `requirement_id`; token/text similarity is insufficient.
No rule may emit `ignored`, `slop`, `bad code`, or infer intent.

`Challenge agent` is a frontend-only formatter over returned findings. It produces
one question per finding using its title, next action, and source citation. It does
not persist questions or create Components.

The deterministic copied template is:
`{title}. {explanation} {next_action} Show the supporting result or correct the completion claim. Sources: {source IDs or URLs}.`
No LLM expands or intensifies it.

## UI placement and states

No new route is added.

- `DigestBoard` renames the generic action to `Copy project brief`. It continues
  to compile `project_snapshot/project_snapshot` only.
- `ContextInspector` shows `Prepare for agent` only for eligible focus cards. It
  posts `source_component`, copies returned markdown, and exposes idle, preparing,
  copied, and error states. Ineligible cards show no disabled pseudo-action.
- `ContextMapPage` owns prepare/timeline queries and invalidates the digest and
  focused timeline after preparation or new observation.
- `ProjectBar` shows `Focus · {title}` and the latest factual outcome when present.
  Missing outcome text is `No observed outcome yet`; never fabricate a status.
- A compact `Attention` disclosure shows only non-zero Blocked, Unverified, and
  Stale counts. A healthy/empty project does not get a permanent green panel.
- The inspector timeline is newest run first and events chronological within a
  run. Each assertion has an `Open source` action (provider URL when present,
  otherwise existing source-detail API). Generic logs/raw streams stay hidden.
- `Challenge agent` appears beside a finding only; copied questions include the
  source label/ID.
- At widths below the existing inspector breakpoint, the inspector remains a
  full-width modal; timeline rows stack files/check details under the timestamp.
  Keyboard close, focus return, link labels, and live mutation status remain
  accessible.

Explicit UI states: loading skeleton; no focused pack; focused/not attempted;
running/no completion evidence; blocked; verification missing; failed;
completed-unverified; verified; stale source; conflicting evidence; endpoint
error with Retry. Unknown data is rendered `Unknown`, not omitted in a way that
implies success.

## Migration, rollback, and ownership

1. Backend/model owner: add the columns and indexes above to `app/models.py`,
   `app/migrations.py`, and a new Alembic revision. Backfill nothing except
   `payload_json='{}'`; legacy provenance remains unknown/null.
2. Compiler/API owner: implement focus validation/persistence/manifest changes.
   Put state derivation, findings, and timeline assembly in
   `app/services/founder_oversight.py`; API modules remain transport owners.
3. MCP owner: add run/event keys, canonical payloads, idempotent responses, stable
   source identities, and normal projection calls.
4. Frontend owner: add hooks and the minimal Project bar/inspector/Attention UI.
5. Integration owner: run migrations, focused suites, full suites/build, and
   desktop/narrow light/dark checks in that order.

Rollback code before schema. The added nullable columns/indexes can remain safely
unused. A database downgrade drops new indexes before columns; it must not delete
SourceDocuments, existing observations, packs, or runs. Downgrading loses focus
lookup and structured payload convenience but not raw evidence.

## Fixtures and acceptance tests

Add one reproducible workspace fixture containing:

- one current task Component with source revision 2 and explicit evidence;
- one unsupported generic fact;
- one focused pack with one required verification command and required item;
- one run with patch summary, passing/failing verification variants, blocker and
  resolution variants, and terminal outcome;
- one newer source revision for stale-focus testing;
- a second workspace with similarly shaped IDs/text for isolation tests.

Focused backend tests:

- `tests/test_context_compiler.py`: eligible focus is mandatory/persisted; manifest
  provenance is exact; source-derived objective cannot accept caller text;
  unsupported, stale, prompt-risk, and cross-workspace focus fail; replay key
  changes with focus.
- `tests/test_mcp.py`: start and every write are idempotent; conflicting payload
  writes nothing; deterministic external IDs; source-before-observation; only
  durable types project; failed projection retains raw evidence; terminal retry
  returns original success; invalid item references and blocker resolutions fail.
- new `tests/test_founder_oversight.py`: every state and rule positive/negative,
  command mismatch, ambiguous prose, stale revision, conflict, resolved blocker,
  duplicate evaluation, chronological ordering, caps, citations, and workspace
  isolation; digest oversight uses only the latest focused pack.
- migration tests: clean upgrade, legacy-row upgrade, indexes/columns, downgrade,
  and re-upgrade on SQLite; PostgreSQL partial-index SQL is inspected/covered by
  the existing migration pattern.

Focused frontend tests:

- `DigestBoard.test.jsx`: `Copy project brief`, compact current focus/outcome,
  non-zero Attention only, no readiness percentage.
- `ContextInspector.test.jsx`: eligible prepare states, ineligible absence,
  timeline state wording, source links, Challenge citations, empty/error/retry,
  keyboard and narrow stacked layout.

Acceptance gates:

- selecting an evidenced supported card produces a persisted pack whose focus and
  objective source can be traced to one immutable source revision;
- repeating start/event/finish writes creates no duplicate source or observation;
- terminal outcome, checks, blockers, and patch summary appear after normal
  processing, while routine logs do not become Components;
- all six rules emit only on deterministic structured evidence and every finding
  opens the exact source;
- no cross-workspace data appears;
- focused tests, full backend tests, full frontend tests, production build, and
  desktop/narrow visual checks pass.

## Implemented in this slice

The additive schema, focused compiler/API, idempotent MCP observations, computed
scrutiny/timeline, and existing-route frontend are implemented and verified. The
items below remain explicitly outside this P0 contract.

## Not implemented yet

- A universal WorkItem/task database model.
- Persisted scrutiny findings, dismissal, assignment, or manual resolution.
- Bi-temporal claim transactions beyond existing source revisions.
- Autonomous agent execution, command execution, repository writes, or provider
  writes.
- General code-quality scoring, missing-test judgement, agent-intent inference, or
  free-form LLM criticism.
- Raw terminal replay, a new Prepare/Attention route, self-modifying ranking, or a
  generic readiness score.
- Procedures/playbooks, shared-workspace ACL provenance, expanded connectors, and
  production `CodeEdge` generation.

## Risks and remaining gaps

- Existing clients must adopt required `run_key`/`event_key`; legacy null rows are
  readable but cannot be retroactively deduplicated.
- Exact command matching favors precision and may miss wrapper-equivalent commands;
  broaden only with measured fixtures.
- Source-derived objectives can be verbose; normalization may collapse whitespace
  but must not paraphrase or infer intent.
- Computed findings preserve evidence history but not user workflow state. Add a
  finding table only when dismiss/assign/audit requirements are real.
- Runtime source types need deterministic extractors before calling the normal
  ingestion service; generic LLM extraction must not interpret runtime prose.
