# Release Candidate Guide

This is the maintainer path for deciding whether Context Engine is releasable as an OSS v1 candidate.

## Maintainer Flow

1. Bootstrap the stack with `ctxe demo` or `bash scripts/bootstrap.sh`.
2. Confirm the backend founder workflows with `bash scripts/smoke.sh`.
3. Run the full release gate with `ctxe verify --json`.
4. Merge or tag a release candidate only when local `ctxe verify` and the PR `Release Gate` workflow are both green.

## CI Path

- The GitHub Actions workflow `Release Gate` is the CI mirror of the local maintainer flow.
- CI runs `ctxe verify --json --test-database-url postgresql+asyncpg://postgres:postgres@localhost:5432/context_engine_verify`.
- The workflow summary must show the release `status`, selected phases, completed phases, and the failing `phase` plus `next_step` when the gate stops early.
- Compatibility-only routes are not part of the release story: `GET /api/query`, `POST /api/source-documents/upload`, and `POST /api/imports/trigger` do not count as founder-workflow release coverage.

## What Must Be Green

- Local `ctxe verify`
- GitHub Actions `Release Gate` workflow on the PR
- `ctxe verify` phases:
  - `boot`
  - `readiness`
  - `seed`
  - `smoke`
  - `contract-tests`
  - `frontend-tests`
  - `frontend-build`

`Release Gate` is the CI mirror of the local maintainer command. It installs backend + frontend dependencies, boots the Docker stack, runs `ctxe verify --json`, uploads `release-gate.json` as an artifact, and renders the result in the GitHub Actions step summary.

## Prerequisites

- Docker Engine with Compose v2
- `python3`
- `curl`
- `npm`
- PostgreSQL client tools: `dropdb`, `createdb`, `psql`

The CLI boot path will create `.env` from `.env.example` and generate `ENCRYPTION_KEY` automatically when missing.

## Exact RC Steps

1. Refresh the branch and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd frontend && npm ci && cd ..
```

2. Run the full release gate:

```bash
ctxe verify --json
```

By default the contract-tests phase uses this disposable database:

```text
postgresql+asyncpg://postgres:postgres@localhost:5432/context_engine_verify
```

Override it only if your local Postgres port or credentials differ:

```bash
ctxe verify --test-database-url postgresql+asyncpg://postgres:postgres@localhost:15432/context_engine_verify
```

3. If the gate fails, rerun only the failing slice:

```bash
ctxe verify --phase boot --phase readiness --phase seed --phase smoke --skip-frontend
ctxe verify --phase contract-tests
ctxe verify --phase frontend-tests --phase frontend-build
```

4. Open or update the PR and confirm `Release Gate` is green.

5. If you need the manual fallback instead of `ctxe verify`, run:

```bash
bash scripts/smoke.sh
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/context_engine_verify \
  python3 -m pytest \
    tests/test_cli/test_main.py \
    tests/test_cli/test_http.py \
    tests/test_api/test_imports.py \
    tests/test_api/test_admin.py::TestSeedDemoAPI \
    tests/test_api/test_connectors_upload.py \
    tests/test_api/test_truth_regression.py \
    tests/test_api/test_query.py \
    tests/test_api/test_briefing.py \
    -q
cd frontend && npm test
cd frontend && npm run build
```

## Expected Output

Human output should identify the selected phases first, print skipped phases when applicable, and then print one line per successful phase:

```text
verify phases: boot, readiness, seed, smoke, contract-tests
skipped phases: frontend-tests, frontend-build
boot: ...
readiness: ...
...
OSS v1 verification passed.
```

`ctxe verify --json` should return:

- `status`
- `selected_phases`
- `skipped_phases`
- `steps`
- on failure: `phase`, `next_step`, `completed_steps`

In CI, the same JSON should be visible in both places:

- the `release-gate-report` workflow artifact
- the `Release Gate` step summary on the PR or push run, alongside a human-readable status/phase summary

## Rollback Notes

- If `Release Gate` is red, do not tag or announce a release candidate.
- If a PR merged and the gate later identifies a release blocker, revert the merge and rerun `Release Gate`.
- If a deployed stack must be rolled back:
  - `docker compose down`
  - redeploy the previous known-good image or commit
  - keep Docker volumes intact unless you are intentionally restoring from backup
- If a migration or seed step wrote bad data, restore Postgres from the most recent backup before re-running the release gate.
