# Immediate DaemonState Strengthening Plan

## 2026-07-17 workspace navigation and state isolation — implementation complete

### Product outcome

Treat a workspace as a durable, directly enterable project boundary. Opening a
workspace lands on its own Now page; transient input from another workspace
cannot appear or be submitted there; saved configuration remains attached to
the workspace that owns it.

### Observed

- Workspace management cards expose rename/archive controls but no open/select
  action.
- Switching workspaces leaves the current route component mounted, so local
  goal drafts, query results, and compiler mutation state can survive the
  boundary change.
- The database did not clone the old goal into stock-radar. The stock-radar goal
  was written explicitly 46 seconds after workspace creation, consistent with
  stale frontend input being submitted after the switch.
- Repository scope, connectors, and explicit goals are already persisted with a
  workspace ID on the backend.

### Scope

1. Make each active workspace card an accessible open target that selects the
   workspace and navigates to `/app`.
2. Make workspace changes enter the selected workspace's Now page and remount
   workspace-scoped route state.
3. Reset transient Now/query/compiler output on boundary changes; persist only
   reusable compiler and retrieval settings under the owning workspace ID.
4. Prove a new workspace has no current goal while an existing workspace keeps
   its own goal and configuration.

### Release gates

- Clicking an active project or sample card selects it and opens Now.
- Rename/archive/delete controls never accidentally open a workspace.
- A newly created workspace shows no goal or prior query unless the user saves
  one in that workspace.
- Returning to an existing workspace restores its backend state and its own
  compiler/retrieval settings, never another workspace's.
- Focused/full backend and frontend tests, production build, Ruff, and diff
  checks pass; the live card-to-Now path is verified.

### Ownership

- Implementation and verification: Codex
  (`.agent-runs/2026-07-17-codex-workspace-state-isolation-task.md`).

### Implemented outcome

- Active workspace cards and switcher choices now select the workspace and land
  on its Now page.
- Workspace changes remount route content, so unsaved goals, questions,
  histories, results, and compiled output cannot cross project boundaries.
- Reusable Prepare and retrieval controls are stored under workspace-specific
  browser keys; new workspaces start from defaults and returning workspaces
  recover only their own settings.
- A backend regression proves newly created workspaces have no current goal,
  while an existing workspace keeps its own persisted goal.
- Live verification proved an unsaved stock-radar goal draft disappeared across
  a workspace round trip while the saved workspace goal remained. The accidental
  stock-radar goal was then cleared through the product UI.
- All 92 frontend tests, the frontend production build, all 565 backend tests,
  Ruff, and diff checks pass.

## 2026-07-17 repository ignore-aware indexing — implementation complete

### Product outcome

Index the source a user considers part of the project, not generated framework
output that Git already marks as ignored. Keep the existing file and byte safety
limits for genuine source candidates.

### Scope

1. Use Git's tracked and non-ignored untracked file set when the repository is a
   valid Git worktree.
2. Expand safe fallback exclusions for non-Git projects and incomplete test
   repositories, including `.next` and common build/cache directories.
3. Preserve per-file, aggregate-byte, symlink, and file-count limits.
4. Reproduce the stock-radar `.next` failure in a focused regression test.

### Release gates

- Tracked project files outside known generated directories remain eligible even
  if a later ignore rule matches them.
- Untracked ignored files and generated directories never consume the 50 MB cap.
- Untracked, non-ignored source remains indexable.
- Non-Git project roots retain deterministic hard-coded safety exclusions.
- Focused/full tests, Ruff, and `git diff --check` pass.

### Ownership

- Implementation and verification: Codex
  (`.agent-runs/2026-07-17-codex-repository-ignore-indexing-task.md`).

### Implemented outcome

- Valid Git worktrees are enumerated from tracked files plus non-ignored
  untracked files, so repository ignore rules define the candidate boundary.
- Generated directories remain excluded in Git and filesystem-fallback modes as
  defense in depth.
- The stock-radar repository now produces 210 candidates totaling 2,429,172
  bytes, with no `.next` files; the 50 MB cap remains unchanged.
- Focused indexer tests, the full 564-test backend suite, Ruff, and diff checks
  pass.
## 2026-07-17 product README story — completed

### Product outcome

Explain DaemonState in the language of the person using it: coding agents
lose project state between sessions, the user pays the context tax, and the
product turns scattered evidence into a clean handoff for whatever agent or
model works next.

### Scope

1. Lead with the user-visible change, not the storage architecture.
2. Make the model-efficiency thesis prominent without claiming proven parity.
3. Show the real product loop and current shipped surfaces in plain language.
4. Preserve Setup, Deployment, Contributing, Documentation, and License content.

### Release gates

- Every capability claim maps to implemented UI, API, CLI, or tests.
- Samples and unverified model-lift claims are not presented as proof.
- Copy is concise, specific, and avoids generic AI-marketing language.
- Existing setup and OSS-readiness sections remain unchanged.

### Ownership

- Copy, claim audit, and final verification: Codex
  (`.agent-runs/2026-07-17-codex-readme-product-story-task.md`).

### Implemented and verified

- The README now leads with the session-to-session context problem and the
  concrete change in daily agent usage.
- The older/cheaper-model thesis is prominent, while the absence of real
  external-project proof remains explicit.
- The product loop maps each surface to its actual user job and keeps the graph
  in an explanatory role.
- Setup, Deployment, Contributing, Documentation, and License remain unchanged.
- All local README links resolve and `git diff --check` passes.
## 2026-07-17 explicit-goal and realistic-project milestone — implementation complete; external validation pending

### Product outcome

Make current work a deliberate user choice, not an inference from whichever old
context pack happens to contain a focus component. Keep ordinary open issues in
the backlog, reserve Needs attention for genuinely urgent evidence, and prepare
the product to validate against a real external repository rather than demos.

### Ordered implementation

1. Persist one explicit active workspace goal with provenance and history;
   temporarily surface an actually running agent above that selection.
2. Let users choose, change, or clear current work from the Now page, including
   a custom objective or an eligible backlog card.
3. Split urgent attention from ordinary backlog in the digest contract and UI.
4. Add workspace rename/archive/delete behavior and a dedicated management UI.
5. Replace name-first setup with repository-first onboarding and visually
   separate samples from real projects and unassigned AI sessions.
6. Validate the complete loop on a real external project before treating demo
   behavior as product evidence.

### Implemented outcome

- Current goal is now either an actually active run or an explicit user
  selection with provenance; historical context packs cannot silently choose it.
- Needs attention contains blockers, conflicts, stale evidence, and genuine
  reviews. Ordinary issues remain selectable backlog and suggestions remain
  visibly non-binding.
- Workspaces now have explicit project/demo/sandbox identity plus active/archive
  lifecycle, rename, restore, guarded permanent deletion, impact counts, and a
  dedicated management surface.
- The native selector is replaced by a project picker that separates projects
  from samples and always exposes Add project and Manage actions.
- First-use setup is repository-first: DaemonState creates a real-project
  workspace only when local repository indexing succeeds, and rolls back a
  failed creation instead of leaving an empty workspace.
- Sessions with unknown repository relevance are called out on Now and remain
  excluded from health, suggestions, and compiled project truth.

### Remaining validation

- Run the complete capture -> goal -> prepare -> harness -> outcome -> explain
  loop on a user-supplied external project. The existing DaemonState and demo
  workspaces are smoke-test evidence only, not external product validation.

### Release gates

- Old context packs never silently become the current goal.
- Only an active run or explicit user selection can populate Current goal.
- Open issues remain backlog unless selected or independently blocked/conflicted.
- Goal mutations are workspace/access scoped and reject ineligible components.
- Schema upgrades work through both Alembic and runtime migrations.
- Archiving and deletion are blocked while an agent run is active; permanent
  deletion additionally requires archive state and exact-name confirmation.
- Focused and full backend/frontend tests, build, Ruff, and diff checks pass.

### Ownership

- Implementation and integration: Codex
  (`.agent-runs/2026-07-17-codex-explicit-goals-workspaces-task.md`).

### Stop conditions

Do not auto-select a suggested issue, use demo success as realistic-project
validation, delete workspace evidence without explicit confirmation, or expose
sessions with unknown repository relevance as project truth.

## 2026-07-17 product-loop UX milestone — completed

### Product outcome

Turn the implemented compiler, run evidence, and graph into one understandable
user journey: see the project now, prepare task-specific context, inspect verified
runs, and explain why evidence and relationships mattered. Internal terms such as
`harness` remain implementation details rather than primary navigation.

### Scope

1. Make `Now`, `Prepare`, `Runs`, and `Explain` the primary product surfaces.
2. Add a project-state home that surfaces current focus, recent outcome,
   evidence-backed attention, and a recommended next action without opening the
   full graph.
3. Add a task preparation page over the existing `context_pack.v2` API with
   model-aware pack summary, selected/excluded evidence, preview, and copy.
4. Expose local-harness-observed outcomes through an authenticated workspace API
   and render recent verified runs plus an honest model comparison/readiness view.
5. Make graph relationships visually semantic: containment, blocking,
   contradiction, supersession, dependency, and provenance must not all look the
   same.

### Release gates

- Existing evidence, access-scope, and context-pack contracts remain intact.
- The UI never claims a run was verified without harness-owned passing evidence.
- Comparison UI distinguishes observed DaemonState runs from a paired causal
  experiment and does not claim model parity.
- Empty states explain what evidence is missing and what action creates it.
- Focused backend/frontend tests, production build, diff checks, and live browser
  inspection pass without reverting unrelated user changes.

### Ownership

- Contract, implementation, integration, and final review: Codex
  (`.agent-runs/2026-07-17-codex-product-loop-ui-task.md`).

### Stop conditions

Do not build a new autonomous coding agent, fabricate baseline comparison data,
execute a model from the browser, expose raw terminal logs, or turn the full
knowledge graph into the default landing page.

### Implemented outcome

- Added a task-oriented `Now` home, an inspectable `Prepare` compiler surface,
  local-harness `Runs` evidence with honest comparison boundaries, and a
  task-scoped `Explain` graph.
- Exposed source-access-scoped local harness outcomes for the UI without
  presenting recorded model labels as verified provider identity.
- Made containment spatial and grouped by parent; blocking, contradiction,
  supersession, dependency, provenance, and generic associations now use
  distinct edge treatments.
- Kept model capability selection honest: the current profile is inferred from
  the supplied label or falls back conservatively; provider probing remains a
  future adapter capability.

### Verification

- Backend: `552 passed` (full Pytest suite); focused Ruff checks passed.
- Frontend: `79 passed` (full Vitest suite); production Vite build passed.
- `git diff --check` passed.
- Live browser validation passed for desktop and 390×844 mobile layouts,
  including real context compilation, weak-readiness messaging, graph
  inspection, semantic containment, and harness onboarding.

## 2026-07-16 model-lift harness milestone — completed

### Product outcome

Make DaemonState able to wrap one local coding-agent command, automatically
preserve what actually happened, enforce a small-model-friendly execution
contract, and report verified outcomes by model/profile. This is the first
measurable step toward the narrow claim that an older model can perform closer
to a newer model on an existing project when it receives better context and
execution discipline.

### Scope

1. Add a provider-neutral local harness runner that compiles `context_pack.v2`,
   exposes the brief to the child process, captures bounded/redacted output and
   deterministic repository state, optionally runs the pack's required checks,
   and persists the complete run through the existing `AgentRun` /
   `RunObservation` evidence contract.
2. Make the existing target-model profiles express execution policy as well as
   context size: required planning, diff review, verification, retry bounds, and
   context refresh behavior. Render that policy in the pack and lockfile.
3. Add deterministic outcome reporting grouped by model and model profile, plus
   an offline paired-result evaluator for `old_alone`, `old_with_daemonstate`,
   and `new_alone` experiments. Do not claim model lift from fixture quality.
4. Expose the runner and evaluator through the CLI and document the honest
   boundary: DaemonState wraps a user-selected worker; it is not a new
   autonomous coding agent.

### Release gates

- The wrapped command runs only when explicitly supplied by the user.
- Raw output is bounded before persistence; recognized secret patterns are
  redacted, and truncated stream content is omitted rather than partially stored.
- Git/repository evidence is observed directly, not accepted from the child
  process as a completion claim.
- Required checks are run only with explicit `--verify`; their real exit codes
  determine verification state.
- Small-model packs contain a stricter, machine-readable execution policy than
  frontier-model packs.
- Outcome reports separate observed counts from causal or model-parity claims.
- Focused backend tests, CLI tests, Ruff, and `git diff --check` pass without
  reverting unrelated user changes.

### Task ownership

- Contract review: Kimi role (`.agent-runs/2026-07-16-kimi-model-lift-harness-contract-task.md`)
- Integration owner: Codex (`.agent-runs/2026-07-16-codex-model-lift-harness-task.md`)
- Local runner slice: GLM role (`.agent-runs/2026-07-16-glm-local-harness-task.md`)
- Model-policy slice: Qwen role (`.agent-runs/2026-07-16-qwen-model-policy-task.md`)
- Outcome/eval slice: Xiaomi role (`.agent-runs/2026-07-16-xiaomi-harness-outcomes-task.md`)

### Stop conditions

Do not add a general-purpose autonomous agent, silently execute generated shell
commands, fine-tune a model, claim old/new model parity, store unbounded terminal
logs, or add provider-specific integrations in this milestone.

### Implemented outcome

- Added a direct-argv local harness with context-pack handoff, bounded evidence,
  Git snapshots, opt-in verification, cancellation handling, and durable outcomes.
- Added model-specific execution policy to compiled packs and lockfiles.
- Added harness-owned outcome reporting and an offline paired experiment evaluator.
- Rewrote the README around the product, current behavior, limits, and existing logo.

### Verification

- Backend tests, frontend tests/build, Ruff, and `git diff --check` are required
  before final handoff; final counts are reported in the task response.

## 2026-07-15 product README refresh — completed

### Outcome

- Explain the current product from a founder/user perspective before its internal
  architecture: project oversight, agent scrutiny, open loops, and agent briefs.
- Keep every capability statement tied to implemented UI, API, CLI, MCP, or tests.
- State important limits explicitly, especially that preparation copies a brief
  but does not launch an agent, and scrutiny is not a generic AI code-quality score.
- Leave Setup, Deployment, and public self-hosting guidance intentionally unfinished.

### Verification gates

- README links and heading anchors are internally consistent.
- No connector, agent action, or scrutiny behavior is overstated.
- Markdown formatting and repository diff checks pass.

### Implemented and verified

- README now leads with the founder-facing product: bird's-eye project state,
  deterministic scrutiny, durable open loops, source-backed agent briefs, and
  approved verified playbooks.
- The product loop, current UI behavior, HTTP/CLI/MCP surfaces, connector auth
  modes, and repository map reflect the active code paths.
- Honest limits explicitly cover agent delivery, bounded scrutiny, live retrieval,
  and unfinished public onboarding.
- Setup, Deployment, and Contributing remain intentionally unexpanded.
- All referenced local documentation paths exist; headings were checked;
  `git diff --check` passed. Tests were not rerun because this is documentation-only.

## 2026-07-15 agent-brief confirmation UX — completed

### Outcome

- After preparation, show what was created, whether it reached the clipboard, and
  explicitly state that nothing was sent to an agent automatically.
- Let the user view the generated brief and copy it again without regenerating it.
- Keep the confirmation inside the existing inspector; add no new page or modal.

### Verification gates

- Success, clipboard-failure, view, copy-again, and reset behavior have focused UI tests.
- Full frontend tests and production build pass.

### Implemented and verified

- The inspector now shows `Agent brief ready`, clipboard delivery state, an
  explicit `Nothing was sent automatically` statement, and the number of selected
  source-backed context items.
- `View brief` reveals the generated Markdown in-place; `Copy again` reuses the
  existing brief without another compilation request.
- Clipboard failure leaves the brief viewable and retryable.
- Focused inspector tests passed; full frontend `74 passed`; production build and
  `git diff --check` passed.

## 2026-07-15 project-map eligibility and empty-state repair — completed

### Outcome

- A pull request is shown as delivery evidence, never as an eligible task focus.
- API failures are rendered as human-readable messages instead of raw JSON.
- Refreshing the project map also refreshes the deterministic local-repository
  inventory, so the System lane cannot silently drift behind the indexed files.
- Empty lanes explain the verified absence they represent; document findings are
  labelled as Docs, not as generic Checks.

### Verification gates

- Focus policy is shared by compilation and digest presentation.
- PR and task eligibility have backend regression coverage.
- Inspector, structured API errors, and empty-lane copy have frontend coverage.
- Focused backend/frontend tests and the production frontend build pass.

### Implemented and verified

- Digest and compiler now use one focus policy. PR cards are explicitly marked
  ineligible and the inspector explains that they are delivery evidence.
- Structured API errors show their message instead of serialized JSON.
- Project-map refresh reindexes the active local repository before rebuilding the
  graph. The current DaemonState workspace was reindexed to 1 repository root,
  9 code areas, 267 files, and 4,423 symbols.
- Empty System, Direction, Next, and Docs lanes use compact truthful copy.
- Ruff passed; backend `525 passed`; frontend `74 passed`; production build passed;
  `git diff --check` passed.

## 2026-07-15 remaining roadmap completion — completed

### Product outcome

Finish the previously explicit follow-ons as one truthful learning loop:

`permissioned evidence -> current/historical truth -> indexed/live task context -> observed run -> open loop or verified playbook`

The UI remains the existing Project map and selected-card inspector. New backend
machinery is exposed only when it answers what changed, what remains open, what a
future agent should repeat, or why a fact/file is safe to use.

### Slice A — truth and access substrate

1. Add validity time and observation/transaction time to claim revisions; close
   superseded validity windows without deleting history.
2. Add source/evidence permission provenance and filter unauthorized evidence
   before it becomes a retrieval or context-pack candidate.
3. Add exact test-to-symbol edges only after one unique file pairing and exact
   symbol-name resolution.
4. Add migration, rollback, PostgreSQL-shape, workspace-isolation and concurrent
   indexing fixtures.

### Slice B — durable learning loop

1. Persist only deterministic founder-oversight findings as open loops, with
   active, dismissed and resolved state plus source evidence.
2. Extract a playbook only from a completed run whose required verification
   passed; preserve source run, files, commands and verification evidence.
3. Surface open-loop state beside existing findings and show a collapsed
   `Known playbook` only inside a relevant prepared-task inspector.

### Slice C — freshness and passive capture

1. Add honest `indexed`, `live`, and `combined` retrieval modes. Initial live
   support is bounded to the local repository and configured GitHub connector;
   unsupported providers return explicit unsupported errors.
2. Add `daemonstate repo watch` to incrementally index changed repository snapshots and
   record normalized, redacted repository events without uploading terminal logs.
3. Expose retrieval mode and freshness in manifests/traces, not as new primary UI
   navigation.

### Release gates

- No unauthorized evidence enters candidate generation, summaries, graph
  expansion or context packs.
- Historical and current claim queries return the correct revision and provenance.
- Open loops and playbooks are created only from supported deterministic rules.
- Live mode never falls back silently to indexed data.
- The watcher is idempotent, bounded and stops cleanly.
- Existing and new backend/frontend suites, migrations, production build and live
  desktop/narrow UI checks pass.

### Task ownership

- Contract/coordinator: `.agent-runs/2026-07-15-kimi-roadmap-contract-task.md`
- Truth/schema review: `.agent-runs/2026-07-15-qwen-truth-access-task.md`
- Runtime implementation: `.agent-runs/2026-07-15-glm-learning-freshness-task.md`
- OSS/UX review: `.agent-runs/2026-07-15-xiaomi-roadmap-review-task.md`

### Stop conditions

Do not add connector breadth, a graph database, free-form AI criticism, inferred
permissions, auto-approved procedures, raw terminal capture, or a new dashboard
page for internal infrastructure.

### Implemented outcome

- Claim revisions now support validity time and transaction/observation time,
  including source-backed timeline and as-of reads without deleting history.
- Permission snapshots and server-bound principals exclude unauthorized evidence
  before query, graph, digest, source, and context-pack candidacy.
- Repository indexing adds conservative exact test-symbol links and serializes
  concurrent indexing per workspace/repository.
- Deterministic scrutiny findings persist as auditable open loops. Verified agent
  work can become a reviewable playbook and is reused only after approval and an
  exact compatible repository snapshot.
- Query, CLI, and MCP support honest indexed/live/combined modes for bounded local
  repository and configured GitHub retrieval. Live results become immutable source
  evidence; failures remain explicit.
- `daemonstate repo watch` records bounded, redacted repository-change evidence and
  incrementally refreshes the deterministic repository index.
- The existing Project map exposes only the useful product surfaces: one compact
  open-loop/review trigger, the existing right rail for action and evidence,
  collapsed affected-code/playbook details, and honest local-activity freshness.

### Verification

- Backend: Ruff passed; `524 passed`.
- Frontend: `71 passed`; production Vite build passed.
- Alembic/runtime migration upgrade and downgrade coverage passed.
- `git diff --check` passed before final documentation edits.
- Browser: the real Project map and selected-focus scrutiny rail rendered without
  new navigation, graph-node clutter, or horizontal layout breakage.

## 2026-07-15 plain-language inspector and file-scope UX — completed

### Product outcome

The selected-item inspector must explain what DaemonState actually knows in
plain language. Provider state should replace internal review/confidence labels,
repository matches must be presented as suggestions rather than confirmed edit
targets, and empty/unknown states must tell the user what has or has not happened.

### Scope

1. Show issue/PR state such as `Open issue` instead of extraction workflow status.
2. Remove model confidence percentages from the primary inspector.
3. Rename affected code to `Files to inspect`, explain that suggestions are not
   confirmed edit targets, classify each match honestly, and show only three until
   the user asks for more.
4. Replace raw rule names, duplicated line ranges, freshness `unknown`, and empty
   agent-run language with plain product copy.
5. Keep the machine contract compatible while adding explicit match strength and
   match basis for the UI and generated agent brief.

### Implemented outcome

- Remote cards now show plain provider state such as `Open issue`; internal
  extraction confidence and review status no longer occupy the primary inspector.
- `Files to inspect` labels named files, deterministic matches, weaker word
  matches, and linked tests honestly while showing only three initially.
- Canonical filenames such as `README` become explicit file hints, suppressing
  weaker prose matches for named-file tasks.
- Product copy uses `Unresolved work` while preserving the internal `OpenLoop`
  persistence and API contracts.

### Verification

- Backend focused suite: `37 passed`; focused Ruff checks passed.
- Frontend: `76 passed`; production Vite build passed.
- `git diff --check` passed.

## 2026-07-14 deterministic project compiler P1 — completed

### Product outcome

When a founder prepares an evidence-backed task, DaemonState should identify
the likely implementation files and relevant tests from deterministic repository
structure, explain why each file is present, and keep that compiled structure
current without rebuilding unchanged file/symbol rows.

This slice is not autonomous code review, a complete call graph, or a symbol-heavy
map. It adds a factual project structure layer beneath task preparation:

`repository snapshot -> incremental file/symbol index -> deterministic edges -> affected code in task pack/inspector`

### Observed baseline

- `RepoIndexer` already scans supported Python and JavaScript/TypeScript files,
  hashes content, extracts symbols/imports/routes, and persists `CodeFile` and
  `CodeSymbol` rows.
- `_persist_frame()` deletes and recreates every file and symbol for a repository
  on every scan, so stable files lose identity and downstream structure cannot be
  incrementally maintained.
- `CodeEdge` exists but production indexing does not populate it and it carries no
  deterministic-rule evidence.
- Context-pack file ranking exposes internal reason codes and matched terms, but
  does not provide related-test paths or a concise user-facing `why this file`.
- The Project map should remain module-level. File/symbol impact belongs in the
  selected focus inspector and compiled pack, not as visible graph-node sprawl.

### P1 scope

1. Upsert `CodeFile` by workspace, repository root, and path.
2. Keep unchanged file/symbol rows when content hashes match; replace symbols only
   for changed files; remove rows for deleted files.
3. Generate conservative deterministic edges for supported exact cases:
   relative/local module imports, route-to-handler ownership, and exact
   test-to-code name/path matches.
4. Store edge type, deterministic rule/version, source location/evidence, and
   repository commit identity; do not create unresolved or guessed edges.
5. Enrich relevant-file results with concise `why`, edge-backed related tests, and
   bounded impact paths.
6. Include affected code in the focused pack manifest and existing inspector after
   preparation. Keep it collapsed/compact and absent when evidence is unavailable.

### Task ownership

- Contract: `.agent-runs/2026-07-14-kimi-project-compiler-contract-task.md`
- Schema/reasoning: `.agent-runs/2026-07-14-qwen-project-compiler-edges-task.md`
- Implementation: `.agent-runs/2026-07-14-glm-project-compiler-task.md`
- Product-truth review: `.agent-runs/2026-07-14-xiaomi-project-compiler-review-task.md`

### Release gates

- A repeated unchanged index preserves file and symbol IDs.
- A changed file replaces only its own symbols and invalidates affected edges.
- A deleted file and its edges disappear.
- Every stored edge names a supported deterministic rule and exact source evidence.
- Focused packs explain relevant files and exact linked tests without claiming a
  complete call graph.
- The inspector exposes affected code after preparation without adding a route or
  map nodes.
- Focused and full backend/frontend tests, migration tests, production build, and
  desktop/narrow visual checks pass.

### Stop conditions

Do not infer arbitrary calls with an LLM, index dependency packages, expose all
symbols on the Project map, add a graph database, or claim exhaustive codebase
understanding in this slice.

### Implemented outcome

- Repeated unchanged indexing preserves file and symbol identities; changed and
  deleted files invalidate only their own symbols and affected edges.
- Exact local-import, syntactic route-owner, and test-path rules store versioned
  evidence against a repository snapshot fingerprint.
- Focused packs expose bounded `affected_code.v1` output in the existing
  inspector, collapsed by default and omitted when unsupported.
- Objective ranking ignores unrelated dirty files and provider boilerplate. The
  live Issue #4 check narrowed the UI from eleven noisy paths to the single
  evidence-backed CI workflow.

### Remaining follow-ons

- Exact test-to-symbol links are not implemented; current test links are exact
  path/name rules at file-module level.
- PostgreSQL migration execution, rollback/concurrency fixtures, and broader
  adversarial parser coverage remain release-hardening work.

### Verification

- Backend: `500 passed`.
- Frontend: `59 passed`; production Vite build passed.
- Ruff and `git diff --check` passed.
- Browser: real Issue #4 preparation, desktop and 390px inspector, dark and
  light themes, and zero horizontal overflow verified.

## 2026-07-14 YC Fall 2026 founder-oversight milestone — completed

### End product

DaemonState is the source-backed project-state and scrutiny layer for AI-built
software. It gives a founder a bird's-eye view of what agents changed, left
incomplete, failed to verify, or supplied no completion evidence for; prepares the
next agent with exact project context; and updates that context from the observed
outcome.

This milestone is not a generic memory, agent harness, or code-review product.
It closes one useful loop around existing harnesses:

`Select evidenced work -> Prepare -> Run -> Observe -> Verify -> Challenge -> Update`

### Observed baseline

- `SourceDocument`, `EvidenceSpan`, `ClaimRevision`, `ContextPack`, `AgentRun`, and
  `RunObservation` already provide the evidence ledger and run-capture foundation.
- `/app` is already a calm Project map with one evidence inspector. Sources and
  Connectors remain supporting surfaces.
- The selected map card cannot yet become the explicit focus of a task pack.
  Without a supplied objective, `Copy handoff` produces a generic project snapshot.
- Runtime outcomes and observations are stored as source evidence, but the normal
  run-close path does not automatically reconcile every durable outcome into current
  project state. General runtime writes also lack stable idempotency keys.
- The repository index stores files and symbols, but it rebuilds stored rows and
  does not populate production `CodeEdge` relationships.
- Components have validity windows, but claim revisions are not fully bi-temporal.
- Digest health and recommended actions exist in backend data, but an opaque score
  is not adequate founder scrutiny and should not be promoted as truth.

### July 24 application/demo outcome

Optimize for one credible vertical slice, not feature count. A founder must be able
to:

1. open a project and see current focus, blockers, unverified work, and freshness;
2. select an evidence-backed task, requirement, decision, or blocker;
3. prepare a source-backed pack for an existing coding-agent harness;
4. observe the resulting files, checks, blockers, and completion claim;
5. see exactly which required work lacks completion evidence;
6. challenge the agent with evidence-backed questions before accepting the work.

The demo is successful only if every warning and question links to evidence. It
must not use vague LLM judgements such as `slop`, `bad code`, or `agent ignored this`
without a deterministic observation that supports the wording.

### Execution order and task ownership

#### Slice 0 — contract and dependency gate — completed

Task file: `.agent-runs/2026-07-14-kimi-founder-oversight-contract-task.md`

Define the exact schema/API/UI contract, truth vocabulary, migration order, and
acceptance fixtures before implementation. In particular, distinguish `not
attempted`, `no completion evidence`, `failed verification`, `blocked`, and
`verified`; never collapse them into an inferred `ignored` state.

#### Slice 1 — focused task and observed run loop — completed

Task file: `.agent-runs/2026-07-14-glm-founder-oversight-loop-task.md`

Implement the first end-to-end path:

- let a supported selected component become a task-pack focus without introducing
  a universal new WorkItem abstraction;
- record whether the objective came from trusted human input or an explicit source
  record, and never infer a task objective from arbitrary project evidence;
- make runtime event writes retry-safe and preserve source-first ingestion;
- reconcile durable terminal outcomes, verification results, blockers, and patch
  summaries through the normal evidence pipeline;
- expose a compact, source-backed run timeline;
- add `Prepare for agent` to the selected-card inspector;
- rename the generic no-objective toolbar action to `Copy project brief`;
- show current focus and the latest observed outcome without reintroducing a large
  preparation form or a new top-level page.

#### Slice 2 — deterministic founder scrutiny — completed

Task file: `.agent-runs/2026-07-14-qwen-founder-scrutiny-task.md`

Build a small rule engine over context-pack requirements and run observations. The
first supported findings are:

- required verification missing;
- verification failed;
- unresolved blocker;
- required item has no completion evidence;
- run outcome conflicts with its recorded checks;
- provider or repository state is too stale to support a current-state claim.

The UI representation is a compact `Attention` summary on the Project map and
finding details in the existing inspector/run timeline. `Challenge agent` may
generate questions only from these findings and must cite the triggering pack item,
observation, or source record. Findings are not autonomous code-quality verdicts.

#### Slice 3 — independent product-truth review — completed

Task file: `.agent-runs/2026-07-14-xiaomi-founder-oversight-review-task.md`

Audit the finished vertical slice from a non-technical founder's perspective. Verify
that the main workflow is discoverable, warnings are understandable, evidence is
one action away, and no internal graph/compiler machinery pollutes the primary UI.
Codex owns all integration decisions and final verification.

### User-facing placement contract

| Capability | User-facing placement | Do not expose |
| --- | --- | --- |
| Current focus, blocker/unverified/drift counts, freshness | Project bar and a compact Attention summary | Ranking weights or graph internals |
| Prepare a selected task | Existing evidence inspector | A new permanent Prepare page |
| Files changed, checks, blockers, outcome | Focus-specific run timeline in the inspector | Raw terminal/tool streams by default |
| Contradiction and temporal history | Current-truth/history disclosure in the inspector | Validity/transaction database fields |
| Code impact and relevant tests | Affected-code section in the inspector and context pack | Every symbol as a map node |
| Evidence-backed agent questions | Challenge action beside a finding/run | Uncited free-form criticism |
| Retrieval, idempotency, ACL checks, code edges | Internal services and manifest evidence | User-facing mode/configuration controls |
| Verified procedures | Collapsed `Known playbook` in a relevant future pack | A new Procedures navigation area |

Every user-facing addition must answer either `What should I understand?` or `What
should I do next?`. Infrastructure is complete when it improves those outputs, not
when it gains a dashboard card.

### Follow-on slices after the vertical loop passes

#### P1 — deterministic project compiler

- Populate factual import/reference/route/model/test-to-code `CodeEdge` records for
  supported Python and TypeScript/JavaScript constructs.
- Upsert by repository, path, and content hash instead of deleting the full index.
- Reparse changed files and invalidate only affected reverse dependants.
- Bind compiled artifacts to commit SHA and explain `why this file` in task packs.
- Keep the Project map module-level; show symbols and dependency paths only on
  inspection.

#### P1 — complete bi-temporal project truth

- Add explicit validity windows to claim revisions and make transaction/observation
  time semantics unambiguous.
- Close old validity windows rather than deleting or silently replacing history.
- Preserve unresolved conflicts when authority and evidence do not establish a
  winner.
- Verify volatile facts such as Git HEAD, PR/issue state, and latest checks before
  using them as current truth; store the verification as a new source revision.
- Expose human wording such as `Current`, `Superseded`, `Conflicting`, and `Verified
  3 minutes ago`, not retrieval-mode controls.

#### P2 — open loops, procedures, and shared-workspace permissions

- Expand open-loop rules only after measured precision on real runs. Persist them
  only when users need dismiss/assign/resolution state.
- Extract a procedure only from a completed, verified, secret-redacted run and
  require repetition or human approval before presenting it as a known playbook.
- Add principal/ACL provenance and pre-retrieval filtering before positioning the
  product for shared hosted teams. Workspace scoping remains sufficient for the
  initial solo-founder wedge.

### Evaluation and release gates

- Maintain a real-task fixture set containing expected files, requirements,
  blockers, citations, forbidden stale facts, and required verification commands.
- Measure task completion, relevant-file recall, citation validity, stale leakage,
  context tokens, manual corrections, and verification pass rate.
- Initial feedback is logged for review; ranking weights do not self-modify from a
  tiny sample.
- Focused backend and frontend tests pass for each slice.
- Full backend/frontend suites and production build pass before the milestone is
  called complete.
- Live desktop and narrow-width checks prove the primary action and findings are
  discoverable without crowding the map.
- The final report separates `Observed`, `Implemented`, `Proposed`, and `Not
  implemented yet`, and includes changed files, tests, evidence, risks, and gaps.

### Stop conditions

Do not add connector breadth, a graph database, autonomous provider writes, a
chat-first shell, a generic readiness score, visible symbol sprawl, or free-form
AI code criticism while the focused founder-oversight loop is incomplete.

## 2026-07-13 Meshery backend learnings — completed

### Objective

Finish the useful non-UI lessons from Meshery without duplicating infrastructure
that DaemonState already has. This pass strengthens the graph as a trusted,
source-backed projection; Cytoscape, decorative canvas work, provider webhooks,
and connector scheduling remain separate later work.

### Observed baseline

- Immutable source revisions, durable sync jobs, incremental/rebuild projection,
  relationship origin/evidence fields, and a graph-slice endpoint already exist.
- The current graph-slice endpoint is not a real focused slice: `max_hops` is
  unused, workspace/focus/cap inputs are absent, and relationship status is not
  filtered.
- Ingestion can invent template relationship evidence and can label an edge
  deterministic from its type alone.
- Digest-time noise filters hide malformed AI fragments after persistence, but
  there is no shared pre-persistence semantic-fact gate.

### Work plan

1. **Completed** — audit graph queries, relationship truth, ingestion quality,
   source revisions, and reconciliation behavior; exclude already-implemented
   infrastructure and parked connector/UI work.
2. **Completed** — implemented a workspace-scoped, bounded, focal N-hop graph
   slice with explicit edge status/origin filters and conservative proposed-edge
   defaults.
3. **Completed** — rejected relationships without source evidence, derived origin
   from the extraction path as well as the relationship type, preserved qualified
   cross-repository GitHub references, and report rejected edges without rewriting
   raw sources.
4. **Completed** — rejected malformed semantic fragments before Component creation,
   preserve the raw SourceDocument, and expose reasoned quality counts.
5. **Completed** — exposed projection reconciliation health (pending current
   revisions, historical active projections, and dangling relationships) in
   graph-build results.
6. **Completed** — added focused adversarial/API/build tests, ran the complete backend
   suite, and perform an independent truth/OSS review.

### Acceptance gates

- A focused slice never crosses workspace scope, respects `max_hops`, is bounded,
  and never returns rejected or superseded edges.
- Proposed/AI edges are opt-in for focused retrieval; persisted origin is never
  guessed from confidence.
- A relationship without evidence is rejected and counted; no template
  text is manufactured as provenance.
- Bare GitHub issue references resolve only inside the source repository, while
  qualified `owner/repository#number` references resolve against that repository.
- Malformed instruction/media/session fragments do not become Components, while
  their raw SourceDocument remains intact and inspectable.
- Graph-build output distinguishes a completed run from a consistent projection.
- Focused tests and the full backend suite pass.

> **Current product direction (2026-07-13):** The project-map simplification
> below supersedes earlier frontend language in this file about making a manual
> objective form the primary app surface. The compiler remains the only handoff
> engine, but preparation is now a one-click outcome from the source-backed map.

## 2026-07-13 project-map simplification — completed

1. **Completed** — replaced Prepare, Dashboard, Agents, and the legacy graph
   surface with Project, Sources, and Connectors as the primary navigation.
2. **Completed** — made local repository intake establish a single active
   boundary and emit deterministic `local_repository` source evidence for the
   repository root and top-level system areas.
3. **Completed** — implemented shared repository/path/commit relevance for the
   digest and compiler; unknown and different-project sessions remain visible
   as quiet roots but cannot drive project facts or context packs.
4. **Completed** — rebuilt the map around System, AI sessions, Direction,
   Delivery, Risks, Checks, and Next, using only source-backed relationships,
   searchable quiet records, one evidence inspector, and accessible controls.
5. **Completed** — routed Copy handoff through `context_pack.v2` prompt-risk and
   truth filters; project-snapshot purposes cannot become observed objectives.
6. **Completed** — removed legacy Cytoscape/animation dependencies and dead UI
   assemblies; aligned demo, Docker project mounting, and launch documentation.
7. **Completed** — passed 465 backend tests, 41 frontend tests, production build,
   Ruff, Compose config validation, and diff checks.

## Objective

Execute the technical, architectural, and usability goals from Codex task
`019f48d9-b816-74d3-a559-002353eb2608` now. Calendar estimates are deliberately
removed. Work advances only when its acceptance gates pass.

The canonical product is a tool-agnostic context compiler that turns changing
project evidence into a reproducible, source-backed execution packet and records
whether that packet helped an agent complete its objective.

The product loop is:

`Capture -> Compile -> Run -> Verify -> Learn`

`context_pack.v2` is the only user-facing context artifact. The knowledge graph
is a provenance and explainability projection over current evidence, not a
separate source of truth.

## Non-negotiable invariants

- Raw source history is append-only. A changed provider object creates a new
  revision; prior evidence remains addressable.
- A claim is never `verified` unless its evidence text occurs at the recorded
  source range and its hash matches.
- Current truth is derived from evidence/claim revisions and exposes historical,
  contested, stale, and unknown states honestly.
- Relationships remain optional and require explicit evidence or a deterministic
  rule.
- Every selected pack item has inspectable provenance. Code context is bound to
  a repository state and file hash where available.
- The final rendered artifact must fit the requested token budget. Health cannot
  be perfect when required context, relevance, or provenance is unknown.
- HTTP, CLI, MCP, and frontend use the same compiler and `context_pack.v2`
  contract.
- Existing user edits in the landing page and digest board are preserved unless
  integration explicitly requires compatible changes.
- No connector, model capability, or benchmark result is claimed without tested
  behavior.

## Execution slices and ownership

### Agent 1 — Kimi contract and dependency gate

Task file: `.agent-runs/2026-07-10-kimi-contract-task.md`

Produce a current-state contract, schema decisions, acceptance tests, and merge
order before the backend slices are integrated. This agent changes only its
contract artifact.

### Agent 2 — GLM evidence ledger and temporal truth

Task file: `.agent-runs/2026-07-10-glm-evidence-task.md`

Fix false evidence verification; implement append-only source revisions and
changed-content sync semantics; preserve provenance and migration safety; add
focused adversarial tests.

### Agent 3 — Qwen compiler integrity and context lockfile

Task file: `.agent-runs/2026-07-10-qwen-compiler-task.md`

Make `context_pack.v2` consume trustworthy evidence, improve objective-conditioned
retrieval, enforce rendered budgets and meaningful health, persist audit fields,
and add replay/diff-ready lockfile metadata with tests.

### Agent 4 — Xiaomi independent UX/OSS review

Task file: `.agent-runs/2026-07-10-xiaomi-review-task.md`

After implementation, audit the complete loop for stale claims, unsupported
promises, weak first-run behavior, provenance gaps, and missing tests. Changes are
limited to documentation and clearly safe copy/test corrections unless Codex
assigns a follow-up.

### Codex — integration owner

Codex owns task splitting, frontend product unification, cross-slice conflict
resolution, final architecture decisions, and all verification. The frontend
default becomes objective-first context preparation backed by
`POST /api/context/prepare`; Graph, Ask, Sources, Changes, and Connectors become
inspection/support surfaces.

## Dependency order

1. Record the contract and baseline behavior.
2. Land evidence correctness and migration guarantees.
3. Land compiler provenance/retrieval/budget guarantees.
4. Unify the frontend on the compiler artifact.
5. Add/verify outcome capture and replay/diff seams supported by current data.
6. Run the independent UX/OSS review.
7. Resolve review findings and run the full quality gate.

Parallel work is allowed only when file ownership does not overlap. Agents must
not rewrite unrelated user changes.

## Completion gates

### Evidence correctness

- An LLM fact whose claimed excerpt does not occur in the source cannot receive
  a verified evidence span.
- A changed external object is ingested as a new immutable revision and can be
  selected as current without deleting the previous revision.
- Unchanged content is idempotent.
- Source hashes always match stored content.
- SQLite migration is repeatable and preserves existing rows.

### Compiler correctness

- Selected evidence-backed items carry source document and evidence span IDs.
- Objective-relevant core files beat broad filename/test-token matches in a
  regression fixture.
- Required items cannot silently overflow the final rendered token budget.
- Health reflects missing required context, retrieval confidence, provenance,
  blockers, and contradictions; unknown relevance cannot score 100.
- Stored pack items contain enough audit data to reproduce selection/exclusion
  decisions.
- The manifest records compiler/ranking versions, target model capability,
  repository state, token accounting, and exact exclusions.

### Product-loop correctness

- A user can enter an objective, repository path, target model, and budget from
  the main application surface and receive persisted `context_pack.v2` output.
- The UI shows definition of done, selected context, blockers/uncertainties,
  verification commands, citations, exclusions, health, and copyable markdown
  when supplied by the compiler.
- No frontend path creates or labels a `context_packet.v1` as the canonical
  handoff.
- No fake activity or visually asserted unsupported graph edge is shown as live
  truth.
- Empty, loading, validation, server-error, and success states have focused tests.

### Outcome/evaluation correctness

- The existing run/outcome model can associate a run with its exact pack and
  repository result, or the remaining schema gap is explicitly implemented.
- Compiler evaluation invokes the real compiler against reproducible fixtures;
  it does not score only a hand-written manifest.
- Evaluation reports citation validity, stale leakage, budget compliance, and
  retrieval relevance in addition to schema conformance.
- Claims about model lift remain `Not implemented yet` until paired agent runs
  exist; benchmark scaffolding must not be presented as a result.

## Quality gate

- Focused backend tests for each changed contract pass.
- Full `pytest -q` passes.
- Focused frontend tests pass.
- Full frontend test suite passes.
- `npm run build` passes.
- Migration repeatability is tested.
- A live or equivalent end-to-end prepare flow is exercised.
- Final report separates `Observed`, `Implemented`, `Proposed`, and
  `Not implemented yet`.
- Final report includes changed files, tests, evidence, risks, and remaining gaps.

## Stop conditions

Do not expand connector count, generic dashboard analytics, decorative graph
work, or unsupported model profiles while a completion gate above is failing.

## 2026-07-10 finalization pass

The implementation is published in draft PR #67. Four independent agents now
audit it against the contract before Codex marks the work finished:

1. Contract/acceptance audit: map every completion gate to code and tests and
   report only evidence-backed gaps.
2. Backend invariant audit: review source revisions, migration repeatability,
   exact evidence verification, compiler provenance/budget/health, and MCP run
   outcomes for correctness and isolation bugs.
3. Frontend/product audit: review the objective-first prepare flow, error and
   empty states, accessibility, misleading truth claims, and canonical artifact
   usage.
4. OSS/integration audit: review documentation accuracy, packaging/CI readiness,
   diff cleanliness, and remaining unsupported claims after the first three
   reports.

Agents are review-only during the parallel pass. Codex owns fixes, conflict
resolution, final full-suite verification, and updates to PR #67.

## 2026-07-10 landing UI alignment

### Objective

Carry the landing page's restrained, evidence-first visual system into the
application shell and product pages without changing product behavior or
overstating live data.

### Work plan

1. **Completed** — audited the landing page and application routes for shared
   visual primitives, responsive behavior, and existing user changes.
2. **Completed** — aligned the shell, reusable controls, and selected route
   surfaces with the landing palette, typography, spacing, and honest states.
3. **Completed** — ran focused and full frontend coverage plus a production
   build. The in-app browser could not connect to the host's Vite preview, so
   visual verification remains limited to source review and compiled UI checks.

## 2026-07-10 in-app UX refinement

### Objective

Move beyond palette alignment and improve the internal product's navigation,
information hierarchy, and first-run experience while preserving all existing
data contracts and graph behavior.

### Work plan

1. **Completed** — replaced the crowded desktop header with grouped,
   responsive navigation and persistently reachable workspace/theme controls.
2. **Completed** — made Sources inventory-first and Connectors state-first, with
   compact summaries and progressive disclosure for setup/import actions.
3. **Completed** — aligned onboarding and shared loading/error/empty states with the
   flat paper/ink/lime component system.
4. **Completed** — ran focused/full frontend verification, production build,
   diff checks, and live 1280px/390px browser checks without page overflow.

## 2026-07-10 graph truth and workspace relevance rebuild

### Objective

Make the Graph route an evidence-backed view of the selected workspace. Every
visible session, decision, pull request, issue, blocker, and document warning
must be traceable to a current source record or be clearly labelled as unknown,
stale, or unavailable. The graph must not invent a workspace objective when no
objective has been supplied.

### Observed baseline

- `POST /api/graph/build` processes only `SourceDocument` rows whose
  `processed_at` is null; it does not rebuild existing components.
- The same operation runs relationship inference over existing components, so
  its current `relationships_inferred` result is not proof that sources were
  refreshed.
- GitHub freshness depends on a separate connector sync. The graph button does
  not currently fetch current PR or issue state.
- The digest frontend classifies PRs, issues, blockers, and broken documents
  from card text and URLs. These categories are presentation heuristics rather
  than explicit factual contracts.
- AI-session cards omit the identifying metadata and evidence needed to judge
  workspace relevance or inspect the session's contents.

### Work plan

1. **Completed** — defined the graph rebuild/freshness/workspace contract and
   focused acceptance tests.
2. **Completed** — implemented explicit build modes and honest processing,
   refresh, supersession, and warning information.
3. **Completed** — made digest categories source-typed and provenance-first;
   exclude unsupported or ambiguous cards from categorical panels.
4. **Completed** — added session identity, tool, timestamps, workspace/repository
   relevance, objective evidence, and inspectable excerpts.
5. **Completed** — redesigned the board for clear empty/unknown/stale states,
   smoother navigation, and a collapsible application sidebar.
6. **Completed** — ran focused and full backend/frontend verification, then the
   graph-model and OSS/UX reviews required by `AGENTS.md`.

## 2026-07-11 graph readability recovery

### Objective

Restore the Graph route as a readable project-state story without weakening the
truthfulness work already completed. The default view must help a solo builder
understand which AI sessions produced which decisions, how those decisions
connect to PRs and issues, and what blockers or document problems remain.

### Constraints

- Preserve current source typing, workspace relevance, imported provider state,
  objective honesty, and evidence inspection contracts.
- Default to a stable overview layout; pan and zoom support exploration but must
  not be required to read the primary story.
- Show sessions, decisions, PRs/issues, blockers, and broken/stale docs as the
  primary lanes. Hide secondary evidence behind selection or overflow controls.
- Keep controls compact and outside the main reading path.
- Never invent missing relationships or label unknown provider state as current.
- Follow the user-supplied reference interaction model: stacked AI sessions feed
  a decision hub, then branch to PRs, issues/blockers, document findings, and
  the next agent task; include compact search/filter/layout controls, minimap,
  legend, quick-peek drawer, and fit/zoom/lock controls where supported.
- Treat light and dark modes as separately tuned palettes with equivalent
  contrast, hierarchy, and semantic node colours.

### Work plan

1. **Completed** — audited the current projection and rendered hierarchy against
   task `019f4cfe-f6d7-7a80-b727-c3011aa08252` and the subsequent redesign.
2. **Completed** — replaced the generic evidence canvas with a restrained,
   category-first project-state board and readable progressive disclosure.
3. **Completed** — added focused projection/component tests for ordering, truncation,
   empty states, and truthful labels.
4. **Completed** — ran browser checks at desktop and narrow widths, then full
   frontend tests and production build.
5. **Completed** — completed graph/data-model and UX/OSS reviews; resolved findings
   before reporting completion.

### Follow-up corrections

- **Completed** — verified the graph canvas, cards, semantic group headers, and
  quick-peek surfaces render with genuinely light backgrounds and dark readable
  text when light mode is active.
- **Completed** — verified manual layout moves nodes, lock prevents further
  movement, and returning to auto layout resets manual offsets.
- **Completed** — replaced provider/ID session headings with shared,
  content-derived topics for Codex, Claude Code, and OpenCode, while filtering
  injected bootstrap, environment, tool, and skill instruction blocks.
- **Completed** — removed the oversized objective hero and retained objective
  context in the compact graph toolbar.
- **Completed** — removed enclosing canvas, group-header, node-card, and empty
  placeholder borders; hierarchy now comes from spacing, tint, and elevation.

## 2026-07-10 relationship-first graph UX redesign

### Objective

Turn the factual digest graph into a calm, professional evidence map that gives
the canvas back to the user's project. Preserve the source/provenance contract
from Codex task `019f4cfe-f6d7-7a80-b727-c3011aa08252`, while applying the
objective-first and relationship-first direction from the “DaemonState Design
Ideas” conversation.

### Acceptance contract

- The graph opens with a compact command bar; build, rebuild, scope, and freshness
  explanations do not permanently cover the upper-left canvas.
- The default view renders individual evidence records as nodes and draws only
  supported backend relationships. Decorative paths must remain visually and
  semantically distinct from factual edges.
- A supplied objective is visually central. When no objective exists, the UI says
  so and uses a neutral workspace-evidence anchor rather than inventing one.
- Selection quiets unrelated nodes and edges, exposes a readable local path, and
  opens the evidence inspector without hiding the whole map.
- Graph controls are compact, keyboard accessible, responsive, and use honest
  labels (`Update graph`, `Rebuild`, imported snapshot, relationship count).
- Empty and sparse workspaces still explain the next useful action without a
  large generic placeholder.
- Focused frontend tests, the full frontend suite, production build, and live
  desktop/mobile visual checks pass.

### Work plan

1. **Completed** — replaced the fixed board chrome and category wall with a
   relationship-first evidence map and compact command bar.
2. **Completed** — refined the evidence inspector, responsive behavior, focus states,
   and empty/sparse states.
3. **Completed** — added focused projection/interaction tests and updated graph UX documentation.
4. **Completed** — ran 72 frontend tests, 46 focused backend graph tests, a production
   build, and live browser QA in desktop light/dark and 390px mobile layouts.

### Verification result

- Full backend suite: 455 passed; one SQLite datetime-adapter deprecation
  warning remains outside this graph change.
- Full frontend suite: 69 passed.
- Production frontend build: passed.
- Current local GitHub snapshots confirm PRs #9, #10, #11, and #12 are closed
  and merged. The new UI renders that snapshot state instead of calling them
  active.
- The legacy Issue #12 row points at a pull-request URL. URL/type consistency
  now demotes that row to supporting evidence instead of duplicating PR #12.

### Acceptance gates

- The Graph UI explains whether Build Context incrementally processed pending
  evidence or rebuilt existing evidence; zero processed documents is not shown
  as a successful rebuild.
- Build Context never implies that GitHub or other remote providers were
  refreshed unless a connector sync actually ran and returned a timestamp.
- Only GitHub source documents with explicit item type, number, URL, repository,
  and state metadata appear as PR or issue cards.
- Closed or merged GitHub items cannot be labelled active; unknown freshness is
  visible and never rendered as current fact.
- Decisions and blockers require a component fact type plus inspectable source
  evidence. “Broken docs” requires an explicit extracted finding/status, not a
  frontend keyword match.
- AI sessions show a stable identifier, tool, import time/session time, source
  excerpt, and workspace/repository relevance signal. Sessions without enough
  metadata are labelled as unverified relevance.
- The board states that no objective is set when no source-backed objective is
  available; it does not generate one from arbitrary graph content.
- The desktop sidebar can be collapsed and restored with an accessible control;
  graph pan/zoom/card inspection remain smooth and keyboard reachable.

## 2026-07-11 context-map viewport correction

### Objective

Make the context map read as one fitted graph canvas: remove nested board sizing and
page-level graph scrollbars, replace the unlabeled dot matrix with a real structural
minimap, and keep the graph usable across desktop and narrow viewports.

### Work plan

1. **Completed** — removed fixed inner canvas width and scrolling ownership from
   the graph surface; fit the graph within the available viewport.
2. **Completed** — replaced the dot-matrix/legend hybrid with a structural minimap and
   kept category controls readable without duplication.
3. **Completed** — added focused regression coverage, ran frontend tests/build, and
   visually verified the live route at desktop and narrow widths.

### Navigation correction

- **Completed** — restored graph-native navigation after removing the old native
  scroll surfaces: drag empty canvas space to pan, use wheel/trackpad input to zoom
  around the pointer, and use Fit to reset pan and zoom.
- **Completed** — kept node selection and manual node movement isolated from canvas
  panning, reflected navigation in the minimap viewport, and verified live pointer
  behavior with focused tests and browser interaction.

## 2026-07-13 project control room simplification

### Objective

Replace the fragmented Prepare, Dashboard, and evidence-graph experience with a
single calm project control room for AI-native builders. Importing or selecting a
repository establishes the project scope. The default surface must explain the
project's current direction, delivery state, risks, and relevant agent activity
without requiring users to understand compiler configuration or knowledge-graph
internals.

### Product contract

- `/app` is the project overview and visual map. `/app/dashboard` redirects to it.
- The execution-brief form is removed from the primary UI. `context_pack.v2`
  remains an API, CLI, and MCP capability; this change does not weaken the
  compiler contract.
- Primary navigation contains only `Project`, `Sources`, and `Connectors`.
  Ask and Changes remain compatibility routes, not permanent top-level
  destinations.
- The visual map uses a small number of meaningful node families and supported
  evidence relationships. It must show project flow and problems at a glance,
  not present uniform cards or unexplained graph decoration.
- Session relevance is determined from workspace/repository identity and source
  metadata. Relevant, uncertain, and different-project sessions are conveyed by
  opacity, saturation, and stroke treatment, with accessible labels available
  on inspection rather than repeated prose on every node.
- An imported repository or local project path is evidence of project scope. It
  is not evidence for invented product goals, decisions, or relationships.
- Sources and Connectors remain available and honest; unsupported provider
  behavior is out of scope for this slice.

### Work plan

1. **Completed** — audit current navigation, Prepare, Dashboard, graph projection,
   workspace scope, and session relevance behavior; write the implementation
   contract and parallel graph/UX reviews.
2. **Completed** — combine the useful overview information and graph into one default
   project surface; remove the execution-brief form and redundant navigation.
3. **Completed** — rebuild graph hierarchy, node semantics, relevance styling,
   inspector disclosure, empty states, and responsive behavior.
4. **Completed** — strengthen deterministic project/session relevance using repository
   path, repository identity, branch, workspace, and imported source metadata while
   preserving provenance and unknown states.
5. **Completed** — add focused backend/frontend tests and update product/graph docs
   with observed, implemented, and not-yet-implemented behavior.
6. **Completed** — run focused and full tests, production build, and live desktop/mobile
   browser verification; complete graph/schema and OSS/UX review before handoff.

### 2026-07-13 visual regression correction

- **Completed** — replace percentage-packed node placement with a dimension-aware
  grid whose lane budgets fit their rendered zones; remove the record-expansion
  state that could overfill the canvas.
- **Completed** — suppress generic Slack/channel source hubs and duplicate visual roots
  from the visual projection while preserving their stored source and relationships.
- **Completed** — remove punctuation residue from derived titles and summaries while
  leaving stored source content and provenance identifiers unchanged.
- **Completed** — simplify the inspector so the useful summary, evidence, and factual
  connections lead; internal classification/scoring remains secondary.
- **Completed** — add regression coverage for collisions, comma-prefixed task text,
  generic channel hubs, and inspector hierarchy; repeat live browser verification.

### Acceptance gates

- A user no longer sees `Execution brief`, target-model, or token-budget fields in
  the application UI.
- `/app` presents the selected project and its evidence map without a second
  Dashboard page or competing primary actions.
- The graph distinguishes sessions, intent/decisions, delivery work, and
  risks/verification through visual form and position, not paragraphs of labels.
- Visually de-emphasized sessions still meet contrast/accessibility requirements
  when focused or selected, and the inspector exposes the exact relevance state
  and reasons.
- `not_relevant` sessions cannot drive project summaries, attention counts, or
  factual links; `unknown` sessions stay visible but subdued and are never called
  relevant.
- Focused backend and frontend tests cover route/navigation removal, visual
  relevance semantics, deterministic repository matching, unknown/different-project
  behavior, and provenance retention.
- Full backend/frontend verification and a production build pass, and the live UI
  is checked at desktop and 390px widths in light and dark modes.

## 2026-07-13 DaemonState logo integration

### Objective

Adopt the user-supplied circular node-path mark as the DaemonState logo across
the existing product brand surfaces without changing unrelated product work.

### Work plan

1. **Completed** — translated the supplied raster artwork into a faithful,
   transparent SVG that remains legible at favicon and navigation sizes.
2. **Completed** — replaced the shared React mark and browser favicon while preserving
   existing sizing and layout behavior.
3. **Completed** — added focused component coverage and verified the frontend tests,
   production build, and rendered light/dark presentation.

### Acceptance gates

- The landing page, desktop sidebar, mobile header, and favicon use the new mark.
- The mark preserves the circular boundary, connected black nodes, and single red
  node from the supplied artwork.
- The component remains decorative where adjacent text supplies the accessible
  name and does not create duplicate screen-reader output.
- Focused frontend tests and the production build pass.
