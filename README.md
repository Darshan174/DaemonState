<p align="center">
  <img src="assets/daemonstate-mark.svg" width="96" height="96" alt="DaemonState logo">
</p>

<h1 align="center">DaemonState</h1>

<p align="center">
  <strong>Continue the work. Not the explanation.</strong>
</p>

<p align="center">
  <img alt="Toolkit version 0.1.0" src="https://img.shields.io/badge/toolkit-0.1.0-171713">
  <a href="LICENSE"><img alt="SUL 1.0 license" src="https://img.shields.io/badge/license-SUL--1.0-d9ff68"></a>
  <img alt="Python 3.10 or newer" src="https://img.shields.io/badge/python-%E2%89%A53.10-3776AB">
  <img alt="Alpha status" src="https://img.shields.io/badge/status-alpha-f59e0b">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#whats-in-this-repository">What's included</a> ·
  <a href="#documentation">Documentation</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="SECURITY.md">Security</a>
</p>

DaemonState is a local, source-backed continuity layer for AI coding agents. It
turns project and session state into verified context so a new session can pick
up the work without reconstructing the entire project story.

This repository is DaemonState's public integration and demonstration surface.
It provides a small, offline toolkit for validating and rendering clearly
labelled **synthetic context bundles**. It is **not the DaemonState engine** and
it is **not the complete Free product**.

> **Alpha software.** The public toolkit is ready to explore, integrate, and
> test, but its schema and adapter boundaries may change before a stable release.
> It never discovers local sessions, inspects a repository, executes commands
> found in a bundle, or contacts a remote service.

## Quick start

You need Git and Python 3.10 or newer. The demo has no runtime dependencies and
does not require network access after cloning.

```bash
git clone https://github.com/Darshan174/DaemonState-Public.git daemonstate-public
cd daemonstate-public
python -m daemonstate_public demo
```

The command validates the bundled fictional TaskBoard example, then renders a
human-readable Workspace Context and Session Context. Every generated page is
marked as synthetic and no command shown in the output is run.

### Try the core commands

| Goal | Command |
|---|---|
| Run the bundled demonstration | `python -m daemonstate_public demo` |
| Validate a context bundle | `python -m daemonstate_public validate path/to/context.json` |
| Render a bundle as Markdown | `python -m daemonstate_public render path/to/context.json` |
| Render a bundle as normalized JSON | `python -m daemonstate_public render path/to/context.json --format json` |

For a convenient shell command, install the project in editable mode:

```bash
python -m pip install -e .
daemonstate-demo demo
```

## What's in this repository

The public toolkit is deliberately narrow: it makes the integration contract
easy to inspect without publishing the private product implementation.

| Included here | Not included here |
|---|---|
| Zero-dependency Python CLI | Repository or coding-session discovery |
| Simplified public demonstration schema | Context extraction, scoring, ranking, or quality gates |
| Clearly labelled synthetic TaskBoard fixture | Production memory, knowledge graph, or checkpoints |
| Adapter protocol and local-file example | Handoff delivery, dashboard, desktop app, or connectors |
| Network-disabled Docker demo | Authentication, entitlements, billing, analytics, or infrastructure |
| Export verifier, tests, and boundary documentation | Private engine or hosted-service implementation |

Free-product access and public-source availability are separate boundaries. A
Free product may use the private DaemonState engine through a packaged local
daemon or controlled service; this repository does not implement product
entitlements.

## Use your own demonstration bundle

Start with the bundled fixture at
[`daemonstate_public/examples/synthetic_context.json`](daemonstate_public/examples/synthetic_context.json),
then follow the [public schema reference](docs/SCHEMA.md). The validator rejects
missing fields, unknown fields, incompatible schema versions, and any bundle
that is not explicitly marked as synthetic.

```bash
python -m daemonstate_public validate my-context.json
python -m daemonstate_public render my-context.json
```

The renderer treats every value as display-only data. In particular, strings in
the `commands` and `verification` fields are shown as reported evidence and are
never executed.

## Adapter example

The adapter protocol illustrates how a future integration can obtain a bundle
without coupling application code to a transport:

```python
from pathlib import Path

from daemonstate_public.adapters import BundleRequest, LocalFileAdapter

fixture = Path("daemonstate_public/examples/synthetic_context.json")
adapter = LocalFileAdapter(fixture)
bundle = adapter.fetch_bundle(BundleRequest("workspace-synthetic-taskboard"))
```

Run the complete example with:

```bash
python -m examples.minimal_adapter
```

The hosted adapter is intentionally a stub until a reviewed service contract is
published. See the [adapter boundary](docs/ADAPTERS.md) and
[hosted API boundary](docs/API_BOUNDARY.md) before building an integration.

## Docker demo

The container runs the same synthetic renderer with networking disabled, a
read-only filesystem, a non-root user, and all Linux capabilities dropped.

```bash
docker compose run --rm demo
```

This command does not start the DaemonState dashboard or private engine.

## Verify the checkout

Run the same checks used to review the public export:

```bash
python scripts/verify_public_export.py
python -m unittest discover -s tests -v
docker compose config --quiet
```

The verifier enforces the reviewed file allowlist, rejects symlinks and
sensitive file types, scans for common secret signatures and local absolute
paths, and validates the synthetic fixture against the public contract.

## Repository layout

```text
daemonstate_public/   CLI, validator, renderer, adapters, and synthetic fixture
docs/                 Schema and integration-boundary references
examples/             Minimal adapter example
schemas/              Machine-readable demonstration schema
scripts/              Fail-closed public-export verifier
tests/                Standard-library unit tests
```

## Documentation

- [Repository boundary](docs/REPOSITORY_BOUNDARY.md) — what is public, what is
  private, and why product access is a separate decision.
- [Public demonstration schema](docs/SCHEMA.md) — fields, validation rules, and
  compatibility expectations.
- [Adapter boundary](docs/ADAPTERS.md) — safe integration responsibilities.
- [Hosted API boundary](docs/API_BOUNDARY.md) — requirements for a future
  service-backed adapter.
- [Contributing](CONTRIBUTING.md) — setup, tests, and change expectations.
- [Security policy](SECURITY.md) — how to report a vulnerability privately.

## Status and license

DaemonState Public Toolkit 0.1.0 is alpha software and is source-available under
the [Sustainable Use License 1.0](LICENSE). SUL-1.0 is not an OSI-approved
open-source license. See [NOTICE](NOTICE) for the repository's scope and
attribution details.
