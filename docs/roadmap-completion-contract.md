# Remaining Roadmap Completion Contract

Status: implemented and verified for the 2026-07-15 roadmap milestone.

This contract completes the remaining useful DaemonState loop without turning
the product into enterprise search, an agent harness, or a generic memory store.

## 1. Bi-temporal claim revisions

`ClaimRevision` adds:

- `revision_key`: deterministic, unique identity;
- `valid_from`, `valid_to`: nullable half-open validity interval `[from, to)`;
- `observed_at`: when the source says or the harness observed the fact;
- `transaction_to`: nullable close of the database transaction interval;
- `validity_basis`: `source_time`, `observation_time`, or `unknown`.

Existing `created_at` is transaction start. Unknown real-world validity stays
null; ingestion time must not be presented as event time.

Rules:

- `confirm` inherits the prior validity interval and closes only its transaction
  interval;
- a different-value update closes prior validity only when the incoming evidence
  has an explicit source/observation time;
- without an effective time, both revisions remain open and the claim is
  `contested`;
- `contradict` closes neither side;
- `supersede` closes the target only with an evidence-backed effective time;
- late historical evidence never becomes the current pointer;
- `current_revision_id` is non-null only when one resolved current revision exists.

The API exposes a claim timeline and an as-of query using both `valid_at` and
`known_at`. Every returned revision includes its evidence span and source revision.

## 2. Permission provenance

Permissions are enforced before candidate generation. A client-supplied principal
ID is never trusted.

Authentication supports:

- local single-user mode: principal `local`, unrestricted within selected local
  workspaces;
- server admin API key: principal `admin`;
- configured principal API keys bound server-side to principal IDs and workspace
  memberships.

`SourceDocument` and `EvidenceSpan` store immutable permission snapshots:

- `visibility_scope`: `workspace` or `restricted`;
- `permission_source`;
- `permission_observed_at`;
- `permission_snapshot_sha256`.

Restricted reads use normalized `SourceReadGrant` rows with deterministic unique
keys. A permission change creates a new `SourceDocument` revision even when content
is unchanged. Evidence copies the exact source permission snapshot.

Access rule:

`same workspace AND (workspace-visible membership OR matching restricted grant)`

Missing principals fail closed for restricted evidence. The rule applies to vector
and text candidate SQL, component fetches, relationship expansion, context packs,
focused preparation, digest, graph/source APIs, and MCP search. Counts and traces
must already be permission-filtered.

## 3. Exact test-to-symbol edges

`test_symbol_match.v1` runs only after one unique `test_path_match.v1` pair.

- Python: a test function must contain a static direct call/reference whose import
  or namespace binding resolves to exactly one symbol in the paired code module;
- JavaScript/TypeScript: a static imported/namespace binding used inside a static
  `test`/`it` callback must resolve to exactly one symbol in the paired module;
- strings, comments, test-name prose, wildcard/dynamic imports, duplicate targets,
  and global name searches never create an edge.

The edge is test symbol to production symbol and stores the pairing edge, binding
line, reference line, qualified names, file hashes, rule version and snapshot.

Repository indexing is serialized by `(workspace_id, repo_root)`: a PostgreSQL
transaction advisory lock and a process lock for SQLite/local execution.

## 4. Durable unresolved work (`OpenLoop` internally)

Only supported deterministic founder-oversight findings become `OpenLoop` rows.
The natural key is the finding key derived from rule, pack/run and sorted trigger
IDs. Repeated reconciliation updates `last_seen_at`; it does not duplicate rows.

States: `open`, `dismissed`, `resolved`, `superseded`.

Manual dismiss/resolve requires a reason and creates immutable human source
evidence. Passing verification or blocker-resolution evidence may resolve a loop
automatically. Unsupported/free-form findings are never persisted.

API:

- `GET /api/context/open-loops?workspace_id=...`;
- `PATCH /api/context/open-loops/{id}` with workspace-scoped
  `dismiss|resolve|reopen|assign` actions.

The Project bar shows a project-wide open count. Selected-focus loops appear as
`Unresolved work` after Summary and before Files to inspect. Closed history is
collapsed. Loops never become graph-map nodes.

## 5. Verified playbooks

A playbook candidate is extracted deterministically only when:

- the run has a completed terminal outcome;
- every required verification command has a later passing result;
- no unresolved blocker remains;
- at least one patch summary or decision exists;
- tool/file/command values are secret-redacted;
- source run, observation and source-document evidence are retained.

One successful run creates `pending_review`. It becomes `approved` only after a
human approval or a second independent verified matching run. `stale` playbooks
are not inserted into packs.

Compatibility requires the same workspace, objective fingerprint overlap and a
compatible repository snapshot. The context-pack manifest may include one bounded
`known_playbook` with citations. The inspector shows a collapsed `Verified
playbook` after Affected code; no top-level Procedures page or map nodes are added.

API:

- `GET /api/context/playbooks?workspace_id=...`;
- `PATCH /api/context/playbooks/{id}` with `approve|disable` and a reason.

## 6. Indexed, live and combined retrieval

`retrieval_mode` is distinct from the existing vector/lexical `hybrid` flag.

- `indexed`: existing persisted retrieval only;
- `live`: configured live adapters only; any adapter failure returns an explicit
  error and never falls back;
- `combined`: indexed results plus successful requested live lanes, deduplicated by
  source identity/revision. Requested live-lane failures remain visible.

Initial live adapters:

- local repository: the workspace's already indexed active repo root, bounded
  current-file lexical search with path/hash/line evidence;
- GitHub: a connected manual-token connector, configured repositories and provider
  API search. Results enter immutable source revisions before extraction/use.

Slack, Google and other providers are `live_source_unsupported`.

Trace/manifest records requested/actual mode, lane status, observed/provider time,
refreshed source IDs and errors. The main UI has no mode selector; evidence wording
states whether a source was checked live, used from a saved snapshot, or failed a
live check.

## 7. Repository watcher

`daemonstate repo watch PATH --workspace-id ...` polls a bounded fingerprint, debounces
bursts and invokes incremental indexing only on change. Test-only `--once` and
`--max-cycles` are supported.

Each change writes one normalized, source-first repository event identified by
workspace, resolved-root hash and snapshot fingerprint. Payload contains only
branch/HEAD/dirty state and added/changed/deleted paths/counts. It contains no file
contents, terminal output, commands, environment values or secret-file paths.

The watcher stops cleanly on cancellation/SIGINT. The UI exposes only honest
monitoring freshness in the existing Project header/menu; it gets no watcher page.

## 8. Migration and acceptance gate

Alembic `0004` and runtime migrations must have matching fields, constraints and
indexes. Backfills keep unknown validity unknown and legacy sources workspace
visible, never public. Duplicate natural keys fail with actionable errors.

Required tests cover temporal as-of answers, ACL prefilter/count leakage, focus and
MCP isolation, exact edge positive/negative cases, concurrent claim/repo writes,
open-loop and playbook idempotency/state transitions, live adapter errors/no
fallback, watcher debounce/idempotency/cleanup, SQLite upgrade/downgrade, PostgreSQL
DDL shape, frontend stale-state clearing, mobile overflow and production build.

## Not supported

- inferred permissions or caller-asserted principals;
- arbitrary provider live search;
- free-form AI quality verdicts;
- playbooks from failed/unverified runs;
- raw terminal/session capture by the watcher;
- graph-node or primary-navigation exposure for loops, playbooks, retrieval modes,
  permissions or watcher internals.

## Verified result

The contract is implemented through Alembic revisions `0004` and `0005`, runtime
migration parity, focused API/CLI/MCP services, and the existing Project-map UI.
Verification completed with Ruff, 524 backend tests, 71 frontend tests, migration
upgrade/downgrade coverage, a production frontend build, and a rendered Project-map
and scrutiny-rail check. The unsupported list above remains intentionally excluded.
