# Workspace Foundation Compiler

The Workspace Foundation Compiler builds the objective- and session-independent
parent used by Workspace Context. It stores a strict `workspace_foundation.v2`
artifact in `context_pack.v2.manifest.workspace_foundation` and renders a
bounded, self-contained Markdown handoff. The artifact remains available for
audit and replay, but the copied handoff never requires access to it in order to
understand a displayed claim or an explicit unknown.

## v2 first-class record contract

`workspace_foundation.v2` is the current schema and its integrity validators
include the first-class fields described below. The default compiler and
renderer in this checkout do not yet populate or project these four new lanes;
they continue to emit the existing typed command, implementation-trace,
repository-change, and durable-knowledge lanes. The records in this section are
therefore normative admission requirements for completing v2 population, not a
claim that a non-empty `verification_runs`, `production_flows`,
`change_intents`, or `durable_facts` collection is already produced. A command
result, implementation trace, changed-file annotation, or durable-knowledge
item does not become its first-class counterpart merely because the fields look
similar; it must pass the admission rules below.

### `verification_run`

The minimum semantic record is:

```yaml
verification_run:
  command: string
  snapshot: repository_snapshot_fingerprint
  exit_code: integer | null
  result: passed | failed | blocked | timed_out
  failures: [bounded_structured_failure]
```

`command` is the exact executed command, including its normalized working
directory as part of the record identity. `snapshot` is the canonical
repository fingerprint for the execution state; its evidence retains the
root, branch or detached-HEAD state, HEAD commit, dirty flag, complete Git
status entries, changed paths, and content digests used to establish that
fingerprint. The run is admitted only when an individual persisted
verification observation agrees with a complete local-harness outcome and that
repository-after state exactly matches the frame being compiled. A caller may
not bypass this boundary by constructing a result-shaped object.

`result` is derived from the persisted timeout state and exit result, never
copied from prose. `passed` requires a completed command with exit code zero
and no reported failures. A non-zero exit, timeout, or missing process result
cannot be represented as `passed`. `exit_code` is null only when the process did
not produce one. `failures` contains bounded, structured failure identifiers or
safe summaries supplied by the execution contract; raw stdout and stderr are
not copied into Workspace Context. An empty `failures` list on a failed or
blocked run means that no safe structured detail was available, not that the
command succeeded. Output and payload digests remain available for audit.

Root, branch, HEAD, dirty-state, status-entry, path, content-digest, outcome,
row, or observation-index disagreement rejects the run. Truncated scans,
oversized payloads, duplicate or ambiguous outcomes, malformed results, and
overflow in any bounded lane fail closed. A stale run may be retained only as
explicitly stale diagnostic evidence; it cannot satisfy current verification
coverage.

A run proves only what its command exercised. A broad passing suite is not
capability proof, and no set of ad hoc passes establishes whole-repository
health. `repository_health=passing` still requires complete required-check
policy discovery and a current passing `verification_run` for every exact
required `(command, working_directory)` key. Current failures remain useful
evidence and set health to `failing` rather than disappearing from the record.

### `production_flow`

The minimum semantic record exposes the critical request-to-output stages
directly:

```yaml
production_flow:
  entrypoint: typed_endpoint
  service: typed_endpoint
  persistence: typed_endpoint
  compiler: typed_endpoint
  output: typed_endpoint
  proof: static | execution_verified
```

Each stage names an exact repository path and symbol, route, datastore
operation, compiler invocation, or output boundary and carries hop-level
evidence. Directory names, file proximity, lexical similarity, imports alone,
and generic component membership cannot populate a stage. A complete static
flow requires a contiguous, unambiguous path from the request entrypoint
through service orchestration, a proved persistence read or write, the exact
compiler call, and the returned or rendered output. Calling a function and
discarding its value does not establish request-to-output continuity.

`proof=static` means the current hash-bound source proves the call, data, and
return relationships. It does not mean the path ran, a branch was selected, or
an external effect succeeded. `proof=execution_verified` additionally requires
a current snapshot-bound integration or runtime observation tied to the same
flow endpoints. Test-file presence, a test edge, a unit-test pass, or an
unscoped broad-suite pass cannot perform that upgrade.

If persistence, compiler, output, or any connecting hop is absent, ambiguous,
unsupported, or truncated, the record remains partial and names the exact gap;
it cannot be labeled complete. Existing route/handler/local-call chains remain
useful static implementation traces, but they are not silently promoted into a
complete `production_flow`.

### `change_intent`

The minimum semantic record groups the current changed paths by capability:

```yaml
change_intent:
  capability: capability_id
  before_behavior: statement | unknown
  after_behavior: statement | unknown
  completed: true | false | unknown
  remaining: [statement]
  affected_tests: [exact_test_reference]
```

`capability` must resolve to an exact capability in the same foundation.
`before_behavior`, `after_behavior`, `completed`, and every `remaining` item
require their own explicit documentation-stated or human-confirmed evidence.
Acceptable evidence may be a current hash-matched repository plan, an
authorized human confirmation, or a separately promoted source artifact that
is bound to the compiled change scope. A selected session, task objective,
commit shape, file name, Git status, semantic diff, added test, or model guess
is not intent evidence.

The fields are independent and fail closed. For example, an explicit new
behavior does not prove the previous behavior or completion. `completed=true`
cannot be inferred from a clean diff or passing test. An unreconciled claim of
completion together with remaining work for the same scope becomes a conflict,
not a completed record. Stale, cross-workspace, hash-mismatched, or
capability-ambiguous source material is excluded.

`affected_tests` contains only deterministic path or symbol links for the
changed capability, sorted and deduplicated. It records impact, not execution;
a linked test's result comes from a matching `verification_run`. Generic test
graph edges never populate intent or completion. Per-file Git and semantic
deltas remain available as lower-level change evidence, separate from the
capability-level record.

### `durable_fact`

The minimum semantic record is:

```yaml
durable_fact:
  statement: string
  evidence: [exact_evidence_reference]
  confidence: number_between_0_and_1
  promotion_reason: promotion_reason_enum
```

`statement` is one atomic current fact. `evidence` contains exact, hash-bound
source references rather than a source label or generated summary alone.
`confidence` is bounded from zero through one and preserves the qualifying
truth assessment; it is not increased because the renderer has spare space or
because many dependent records repeat the same source. `promotion_reason` is a
closed, auditable gate result and must agree with the evidence tier:

- trusted repository and system promotion require current, mechanically
  verified source and lifecycle state;
- human promotion requires an authorized, current human confirmation;
- independent corroboration requires at least two genuinely independent
  sources supporting the same identity and value.

Provisional, stale, historical, rejected, superseded, conflicting,
single-source-corroborated, inaccessible, or prompt-selected material cannot be
promoted. Exact repository engineering notes remain source-scoped until they
pass one of these promotion gates; documentation placement by itself does not
make a durable workspace fact. Exclusions retain bounded reason counts so an
empty durable lane is distinguishable from an unattempted scan.

## Planned v2 projection policy

The machine-readable artifact may retain generic imports, import-only
dependency traces, generic module relationships, test-path edges, and
test-symbol edges for audit and diagnostics. The default Workspace Context
projection suppresses those records, their representative names, and their
omission counts. It also suppresses generic top-level components that add no
stage or capability information. This suppression applies to graph noise, not
to a first-class `verification_run`, `change_intent.affected_tests`, or an exact
test result needed to explain a critical capability.

Architecture selection ranks complete production-flow participation first,
then exact entrypoint, call, persistence, compiler, and output relationships,
then distinct production layers. Chain length, generic imports, directory
proximity, and test-edge volume never outrank a shorter critical flow. If no
important flow is established, the default projection states that gap once
instead of filling the context window with generic relationships.

An explicitly requested diagnostic projection may show the suppressed records
and bounded truncation metadata. Diagnostic records keep their evidence labels
and cannot be read as runtime order, capability completion, or test execution.
The diagnostic option changes presentation only; it does not promote evidence
or alter quality and health results. This v2 policy supersedes v1's generic
edge and omission-detail behavior for the v2 default projection.

## Planned v2 score gates and noise invariance

Semantic coverage continues to measure evidence coverage, not whether the
repository is healthy. A fully evidenced failing check may improve coverage
while repository health correctly remains `failing`. Conversely, a passing ad
hoc command cannot compensate for missing required-check policy, production
flow, change intent, or durable knowledge.

A v2 foundation is eligible for a semantic coverage score of 95 or higher only
when all applicable gates pass:

- artifact integrity, repository binding, and essential bounded scans are
  complete, with no blocking evidence conflict;
- required-check discovery is complete, at least one current
  `verification_run` exists, and every required command has a current
  snapshot-bound run, whether passing or failing;
- at least one critical `production_flow` is complete and has execution proof;
- the repository is clean, or every material changed capability has a
  source-backed `change_intent` with before behavior, after behavior,
  completion, and remaining work resolved; every unresolved or conflicting
  field is rendered explicitly and blocks this gate;
- at least one current `durable_fact` passes a promotion gate, and every
  discovered eligible durable candidate is either promoted or has an explicit
  exclusion reason.

An evidence-backed not-applicable state may satisfy an inapplicable gate; an
empty or undiscovered lane may not silently count as complete. Failure of any
applicable gate caps semantic coverage below 95. Repository health is still
computed separately: only complete policy coverage with all required runs
passing may report `passing`.

Generic import count, test-edge count, dependency-chain length, scanner noise,
and suppressed-edge omission counts contribute zero score. Adding, removing,
or reordering only those records must leave the score, 95-point eligibility,
critical-flow selection, and substantive default non-diagnostic content
unchanged. Snapshot identity and artifact hashes may still change when
repository bytes change.

## Pipeline

1. `RepoIndexer` performs one bounded, Git-aware scan. It records manifests,
   languages, syntax observations, routes, tests, repository state, and file
   hashes. Per-file syntax hints and global edge candidates have hard caps.
   Unsupported languages still contribute structural and line-diff evidence,
   but semantic deltas are marked `line_only` and incomplete.
2. Deterministic adapters extract field-located product claims, ordered
   capability workflows, explicit system/data flows, architecture roles, stack
   declarations, and repository-declared commands from the captured
   `RepoFrame`. Architecture/design documents are read only from a small,
   hash-matched candidate set already present in that frame.
3. The edge observer derives exact local-import, route-owner, binding-resolved
   local-call, static HTTP-route, test-path, and test-symbol links. Unknown,
   shadowed, reassigned, or ambiguous bindings produce no edge; route prefixes
   are never guessed. Test edges remain a verification lane and never stand in
   for production architecture.
4. The compiler constructs distinct mental models:

   - repository-stated system and user flows, which remain documentation claims;
   - entrypoint-backed production call flows requiring exact
     `routes_to -> owns -> calls` or `owns -> calls` prefixes;
   - internal call chains, which are useful structure but not user workflows;
   - import-only structural dependencies, which are never presented as calls.

   Runtime execution, branch selection, persistence, network behavior, and
   external-system effects remain explicit gaps unless separately evidenced.

5. Capabilities receive orthogonal assessments:

   - declaration: `declared` or `undeclared`;
   - implementation: `none`, `candidate_only`, `entrypoint_only`,
     `partial_trace`, or `multi_layer_trace`;
   - verification: `absent`, `test_present`, `passed`, `failed`, `stale`, or
     `runtime_verified`.

   A route, file, import, test file, and passing command are therefore never
   collapsed into one ambiguous “implemented” status.

   Every mapped surface also records its derivation (`exact_route`,
   `symbol_match`, `exact_edge`, or `path_heuristic`). A name/path-only match is
   rendered as a candidate and cannot satisfy implementation or copy-safety
   coverage.
6. Current Git changes are classified as implementation, schema, test,
   migration, configuration, documentation, or operations signals and linked
   to exact capabilities, components, and test paths where supported. Bounded
   HEAD-versus-current deltas report line, symbol, route, import, and heading
   changes with parser coverage. Role diversity and evidence density determine
   the bounded projection. Each change has independent typed fields for intended
   behavior, completion status, and remaining work. They fail closed to
   `unknown`; non-unknown values require field-level documentation-stated or
   human-confirmed evidence. Git status and syntax differences never populate
   those fields or supply authorship or behavioral effect. Session-dependent
   facts belong in Session Context unless separately sourced.
7. Exact statements under bounded repository headings for decisions,
   invariants, conventions, current limitations, known failures, and lessons
   form a separate source-scoped engineering-notes lane. Their currentness and
   workspace-wide authority remain unverified. They retain documentation
   evidence and never become implementation proof or promoted memory. Project
   Foundation facts appear in the durable lane only after their existing
   currentness, trust, lifecycle, and corroboration gates.
8. A snapshot-bound policy adapter reads GitHub Actions workflow files only
   when their current bytes exactly match the indexed path, size, and SHA-256.
   It records unconditional verification `run` steps as exact
   `(command, working_directory)` keys. Install, checkout, setup, deploy,
   publish, and release steps are never health checks. Conditional and
   `continue-on-error` checks are not required; dynamic commands, reusable
   verification workflows/actions, YAML aliases, malformed YAML, missing
   parser support, size/line caps, and snapshot mismatches make discovery
   incomplete. Safely discovered checks remain visible, but an incomplete
   policy can never establish passing repository health. This is a
   repository-declared workflow policy, not evidence of remote branch
   protection configuration.
9. A separate read-only loader may admit local-harness verification results.
   It never runs a command. It accepts only individual verification rows that
   agree with a complete harness outcome and whose repository-after root,
   branch, HEAD, dirty state, status entries, paths, and content digests match
   the current `RepoFrame`. Stale, truncated, malformed, or internally
   inconsistent observations are ignored.
10. The quality pass reports three different signals:

   - copy safety: artifact integrity and minimum evidence needed for a safe
     handoff;
   - semantic engineering coverage: evidenced product, flow, capability,
     architecture, change, command, and durable-knowledge coverage;
   - repository health: `failing` when a current snapshot-bound command failed,
     `stale` when only stale execution evidence exists, and otherwise `unknown`.
     Individual passing commands remain visible but cannot establish whole-repository
     health until an explicit required-check policy defines complete coverage.

11. The renderer orders information as product contract, system mental model,
   capability-to-code map, production architecture, verification, current
   changes, source-scoped notes, promoted durable knowledge, known gaps, and
   snapshot identity. Production edge endpoints are retained first; remaining
   architecture slots prefer distinct layers and non-overlapping paths. Bounded
   omissions name representative omitted records and explicitly prohibit
   inferred completeness.

Compilation never accepts a task objective, selected session, or prompt-ranking
term as Workspace Foundation evidence, and it never executes repository
commands.

## Verification admission

Command declarations and executions are separate records. A declaration stays
`unverified` unless an exact command and working-directory observation is
admitted for the current snapshot. An admitted result retains observation time,
exit code, output digest, and execution evidence; raw output is not copied into
the foundation.

A broad suite result remains an individual command result: without an explicit
required-check policy it establishes neither whole-repository health nor which
capability the suite covered. Capability-level `passed` or `failed` promotion
requires the executed command to name an exact linked test file.

For repository-declared GitHub Actions checks, both policy discovery and every
required command observation must be complete, current, and exact before a
passing health state is possible. A failed observation for a safely discovered
required check remains useful even when policy discovery is incomplete, but a
set of passes never fills an unknown portion of the policy.

Outcome scans, verification-row scans, and the admitted unique-result lane are
bounded. If any cap is exceeded, the loader rejects the complete verification
set rather than publishing a partial result as if it were complete.

`RepoIndexer` currently records raw file SHA-256 values while the local harness
uses a size-prefixed preservation digest. For changed regular files up to 1 MiB,
the loader bridges those contracts only by re-reading the current bytes and
reproducing both digests. Larger files, symlinks, races, missing files, or any
digest mismatch fail closed.

## Evidence semantics

Evidence lanes are intentionally non-interchangeable:

- `runtime_verified` and `test_verified` mean an execution result was observed;
  they do not imply that the result passed.
- `code_observed` means current hash-bound repository structure or syntax.
- `documentation_stated` is an exact repository statement, not implementation
  or runtime proof.
- `system_verified`, `human_confirmed`, and `corroborated` preserve the source
  of promoted durable workspace facts.
- historical, provisional, conflicting, and superseded claims are counted for
  audit but cannot support current rendered facts.

Product purpose, audiences, maturity, deployment model, boundaries, capability
definitions, workflow steps, and system-flow steps retain field-level evidence
locations. Wrapped ordered-list items retain their complete line range.

## Integrity and delivery boundary

Each artifact has two hashes:

- `semantic_sha256` excludes capture timestamps and is stable for equivalent
  repository and knowledge state. Replay locks use this fingerprint.
- `artifact_sha256` covers the complete timestamped envelope, including the
  semantic fingerprint. Consumers verify it before copy.

The browser and macOS client require the typed artifact, verify its hashes and
repository-fingerprint binding, and require
`quality_report.copy_ready=true`. Incomplete artifacts remain previewable with
their blocking issues but cannot cross the clipboard boundary.

The legacy `workspace_repository_inventory.v2`, selected/excluded candidate
arrays, `project_snapshot` mode, `context_pack.v2`, and top-level Workspace
Context heading remain available for compatibility. Historical packs without a
typed foundation use the legacy renderer; a present but invalid typed artifact
fails closed.

## Evaluation contract

Current compiler fixtures cover a Python API plus frontend shape,
documentation-poor and adversarial repositories, Go/Rust/Swift fallback,
binding shadowing and reassignment, exact entrypoint flows versus
internal/import-only chains, test-only false positives, blank-line and wrapped
Markdown flows, dirty migration/schema/test/implementation changes, parsed
versus line-only deltas, unknown and source-backed
change-purpose/completion/remaining-work contracts, exact passed and failed
checks, broad-suite non-promotion, fail-closed scan overflow, hash-contract
bridging, bounded work and output, objective invariance, and hash tampering.

Required properties are deterministic semantic hashes, no task leakage, no test
presence presented as a pass, no lexical match presented as complete
implementation, no inferred change intent, production edges before test edges,
field-level provenance, explicit unsupported gaps, self-contained Markdown, and
fail-closed delivery.

Completing v2 population adds one end-to-end golden fixture and independent
negative fixtures. The golden fixture must exercise persisted harness outcome
through admission and rendering; an exact request-to-output production flow;
capability-grouped, source-backed change intent; and promoted durable facts
covering the eligible fact kinds present in the fixture. It must qualify for a
score of at least 95 only while every applicable gate above passes.

Negative fixtures mutate branch, HEAD, dirty state, changed content, evidence
hashes, flow continuity, output return use, intent source scope, fact lifecycle,
and source independence one at a time. Each mutation must remove or downgrade
only the affected record and must never be repaired by a lexical or structural
guess. A noise-invariance fixture adds and reorders large volumes of generic
imports and test edges; the score, score-gate result, critical-flow selection,
and substantive default projection must remain unchanged. A separate explicit
diagnostic projection test confirms that the same bounded noise remains
available for audit without changing evidence promotion, semantic coverage, or
repository health.
