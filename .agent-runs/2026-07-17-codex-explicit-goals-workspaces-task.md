# Codex task — explicit goals, workspace lifecycle, realistic project validation

## Objective

Implement the ordered product corrections identified during the Now/workspace
audit: explicit current goals, urgent-attention versus backlog semantics,
workspace lifecycle management, repo-first onboarding, and a realistic external
project validation path.

## Observed before implementation

- The Now page inferred Current goal from the newest old context pack that had a
  focus component, even when newer prepared objectives had no focus component.
- The selected DaemonState workspace explicitly tracked this repository and
  included one AI session whose repository relevance was unknown.
- Every unresolved issue category was rendered under Needs attention.
- Workspace creation accepted only a name; rename, archive, and delete were not
  implemented, while GET `/workspaces` could create a Default workspace.
- Demo and real workspaces were indistinguishable in the native selector.

## Slice 1 contract

- Add durable workspace-goal history with at most one active selection.
- Active agent runs override a stored selection only while actually active.
- Context packs remain preparation artifacts and never imply current work.
- Add set/clear goal endpoints with workspace and source access validation.
- Add `attention_required` and a Backlog digest cluster so open issues are not
  presented as urgent by category alone.
- Give Now explicit choose/change/clear controls, visible provenance, a separate
  suggestion, and selectable backlog.

## Slice 2 contract

- Add project/demo/sandbox identity plus active/archive state without changing
  existing workspace IDs or slugs.
- Make GET `/workspaces` read-only and access scoped; expose active-only and
  include-archived views with repository, activity, and impact summaries.
- Rename and archive are recoverable. Permanent deletion requires archive state,
  exact-name confirmation, and a dependency-ordered workspace-only cascade.
- Never archive or delete a workspace with an active run.
- Replace the native selector with an explicit project/sample picker and a
  dedicated management page.
- Make the quick start repository-first. If indexing fails, remove the newly
  created empty workspace so setup remains clean.
- Keep unknown-relevance sessions inspectable but explicitly outside project
  health, goal suggestions, and compiled truth.

## Implemented

- `Workspace.kind`, `Workspace.status`, and `Workspace.archived_at`, with runtime
  and Alembic migrations that classify existing `*Demo*` and `Default` rows.
- Scoped list/create/update/delete APIs and application-level deletion ordering
  across source, graph, claim, pack, run, connector, and repository evidence.
- Workspace management cards with rename, archive, restore, impact preview, and
  inline typed permanent-delete confirmation.
- Custom picker grouped into Projects and Samples, always reachable even with
  zero or one workspace.
- Shared repository-first creation form used by first-use gating and workspace
  management, with automatic project naming and failed-index cleanup.
- Now-page warning for unassigned AI sessions.

## Not implemented yet

- The external-project walkthrough. It requires the absolute path to the user's
  separate real repository; this repository and seeded demos do not qualify.

## Verification record

- Focused backend goal/digest/migration tests: 55 passed.
- Full backend suite: 557 passed with one existing Python 3.12 SQLite warning.
- Focused frontend product-loop tests: 4 passed; full frontend suite: 80 passed.
- Production frontend build, Ruff, and `git diff --check`: passed.
- Workspace/repository/auth/migration focused backend tests: 28 passed; full
  backend suite: 561 passed with one existing Python 3.12 SQLite warning.
- Workspace flow frontend tests and desktop/mobile visual pass: passed; all 88
  frontend tests and the production build passed. The
  visual pass caught and fixed mobile popover stacking under the page content.
- Focused Ruff and `git diff --check`: passed.
