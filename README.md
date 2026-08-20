# DaemonState Public Toolkit

DaemonState helps coding agents continue work from verified project and session
context. This repository is the public integration and demonstration surface.
This repository is not the DaemonState engine. It is not the complete Free
product.

The toolkit contains one honest, deliberately limited workflow: validate and
render a synthetic context bundle so that developers can understand the public
boundary without receiving private extraction, scoring, ranking, graph, memory,
handoff, authentication, analytics, or deployment code.

## What is included

- A zero-dependency Python CLI.
- A simplified demonstration schema.
- A clearly labelled synthetic TaskBoard fixture.
- A safe adapter protocol and local-file example.
- A network-disabled Docker demo.
- Documentation describing what remains private.

## What is not included

- Repository or coding-session discovery.
- Workspace or Session Context compilation.
- Extraction, scoring, ranking, verification, or quality gates.
- Production memory, knowledge graph, checkpoints, or handoff delivery.
- DaemonState's production API, dashboard, desktop overlay, or connectors.
- Authentication, Free/Pro entitlements, billing, analytics, or infrastructure.

The Free product may still use the private DaemonState engine through a packaged
local daemon or controlled service. Public source and Free access are separate
decisions.

## Quick start

Requirements: Python 3.10 or newer. No installation or network access is needed.

```bash
python -m daemonstate_public demo
```

Validate the bundled example:

```bash
python -m daemonstate_public validate \
  daemonstate_public/examples/synthetic_context.json
```

Render another bundle that follows the public demonstration schema:

```bash
python -m daemonstate_public render path/to/context.json
```

An optional editable install provides the `daemonstate-demo` command:

```bash
python -m pip install -e .
daemonstate-demo demo
```

## Docker demo

Docker runs the same synthetic renderer with networking disabled, a read-only
filesystem, a non-root user, and all Linux capabilities dropped.

```bash
docker compose run --rm demo
```

This does not start the DaemonState dashboard or private engine.

## Verify the export

```bash
python scripts/verify_public_export.py
python -m unittest discover -s tests -v
```

The verifier enforces the exact file allowlist, rejects symlinks and sensitive
file types, scans for common secret signatures and local absolute paths, and
validates the synthetic example.

## Documentation

- [Repository boundary](docs/REPOSITORY_BOUNDARY.md)
- [Public demonstration schema](docs/SCHEMA.md)
- [Adapter boundary](docs/ADAPTERS.md)
- [Hosted API boundary](docs/API_BOUNDARY.md)

## Status and licence

This toolkit is an alpha staging export. It is source-available under SUL-1.0;
see [LICENSE](LICENSE). It should be published only after the repository name,
licence, branding, and security contact receive a final human review.
