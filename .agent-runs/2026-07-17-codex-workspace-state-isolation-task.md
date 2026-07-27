# Codex task — workspace navigation and state isolation

## Objective

Make workspaces directly enterable and prevent transient UI state from crossing
project boundaries while preserving each workspace's durable configuration.

## Observed

- Workspace cards are not selectable.
- The selected workspace lives in React state/local storage, but route content
  is not remounted when it changes.
- Now goal drafts, grounded-query state, and Prepare mutation state are local to
  mounted page components.
- SQLite evidence shows stock-radar was created at `2026-07-17 16:56:01` and its
  goal was explicitly inserted at `16:56:47`; the backend did not copy the
  cleared DaemonState goal.

## Contract

- Active cards and switcher choices select the workspace and enter `/app`.
- Workspace-scoped page state receives a new lifecycle at the boundary.
- Questions, results, histories, goal drafts, and compiled outputs are
  transient and never copied to another workspace.
- Reusable Prepare and query-control preferences are saved with a workspace-keyed
  browser key; new workspaces receive honest defaults.
- Server-side goals, repositories, connectors, and evidence remain unchanged
  and workspace-scoped.

## Verification

- Focused frontend: 14 tests passed across five files.
- Focused backend workspace/goal coverage: 10 tests passed.
- Full frontend: 92 tests passed across 16 files.
- Production frontend build: passed (1,821 modules transformed).
- Full backend: 565 tests passed with one existing Python 3.13 SQLite warning.
- `ruff check .`: passed.
- `git diff --check`: passed.
- Live browser: clicking `Open stock radar` selected it and navigated to
  `/app`; an unsaved goal draft disappeared after switching to DaemonState
  and back; the saved stock-radar goal remained workspace-specific until it was
  deliberately cleared through the UI.

## Implemented

- Added accessible open targets to active project and sample cards.
- Made card and switcher selection enter the selected workspace's Now page.
- Keyed workspace route content by selected workspace ID to reset transient UI
  state at the boundary.
- Added an explicit Now goal-draft reset on workspace changes.
- Stored only reusable Prepare and query controls in workspace-keyed browser
  preferences; questions, histories, results, and compiled packets remain
  transient.
- Added frontend navigation/state-isolation regressions and a backend new-goal
  isolation regression.

## Remaining gap

- Prepare and retrieval-control preferences are local to the current browser.
  Cross-browser or cross-device preference sync is not implemented. Durable
  repositories, connectors, goals, and evidence remain server-persisted and
  workspace-scoped.
