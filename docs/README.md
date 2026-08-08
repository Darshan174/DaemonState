# DaemonState documentation

This is the documentation home for the current DaemonState working tree.
DaemonState is an active-alpha, source-available product, so the documentation
distinguishes shipped behavior from design contracts and future work.

## Start here

| Guide | Use it for |
|---|---|
| [Getting started](getting-started.md) | Choose an install profile, start DaemonState, connect a repository, and complete the first product loop. |
| [Product guide](product-guide.md) | Understand Continue, Library, Execute, Workspace Context, Session Context, checkpoints, evidence, and current browser boundaries. |
| [Product positioning](product-positioning.md) | Read the audience, category, promise, current wedge, non-goals, and evidence standard. |
| [Self-hosting](self-hosting.md) | Operate the workstation, personal Docker, or hardened single-host profile. |
| [Demo walkthrough](demo.md) | Tour the product with clearly marked sample evidence and no provider credentials. |

## Interfaces

| Reference | Covers |
|---|---|
| [Configuration](configuration.md) | Local `.env` settings, runtime controls, connector credentials, security settings, and profile-specific behavior. |
| [CLI reference](cli-reference.md) | Every `daemonstate` command, execution boundary, output mode, and common example. |
| [HTTP API](api-reference.md) | Authentication, workspace scoping, endpoint families, health probes, errors, and request examples. |
| [MCP](mcp.md) | Local stdio server, tools, trust boundary, runtime observations, and client configuration. |
| [MCP examples](../examples/mcp/) | Copy-paste configuration for an installed CLI or local checkout. |

## Product internals

| Document | Covers |
|---|---|
| [Architecture](architecture.md) | Runtime topology, storage, source ingestion, context compilation, continuation, and deployment boundaries. |
| [Continuation runtime](continuation-runtime.md) | Task resolution, checkpoints, Session Context, desktop staging, automatic provider runs, and outcome semantics. |
| [Workspace Foundation Compiler](workspace-foundation-compiler.md) | The objective-independent `workspace_foundation.v2` artifact, evidence tiers, deterministic repository observations, and copy gate. |
| [macOS floating context control](floating-context-control.md) | Native Workspace/Session Context copy and paste, focus preservation, setup, and safety boundaries. |
| [AI context](ai-context.md) | Local and imported coding-session evidence, supported tools, metadata, and extraction behavior. |
| [Agent harness](agent-harness.md) | Running an explicit worker command, capturing Git/check evidence, and reporting observed outcomes. |
| [Connectors](connectors.md) | Tested source paths, provider setup, status meanings, and the dashboard/API distinction. |
| [Prompt quality](prompt-quality.md) | Versioned prompt shapes, validation, and deterministic fallback rules. |

## Operations

| Document | Covers |
|---|---|
| [Production runbook](production-runbook.md) | Hardened single-host API deployment, TLS, secrets, backups, restore drills, upgrades, and rollback. |
| [OpenTelemetry](opentelemetry.md) | Optional metadata-only trace export and privacy boundaries. |
| [Release readiness](release-readiness.md) | Maintainer snapshot of release checks, known gaps, and verification history. It is not a support-policy guarantee. |
| [Changelog](../CHANGELOG.md) | User-visible additions, changes, and current alpha boundaries for the unreleased 0.3.0 line. |
| [Licensing](licensing.md) | SUL-1.0 permissions, restrictions, the earlier MIT boundary, and contribution implications. |
| [Security policy](../SECURITY.md) | Supported versions and private vulnerability reporting. |
| [Contributing](../CONTRIBUTING.md) | Maintainer setup, checks, code style, and the current contribution pause. |

## Implementation and design contracts

The files below are useful to maintainers and reviewers. Some contain a mix of
observed implementation, acceptance contracts, and explicitly labelled future
work. A proposed section is not a product claim. For current user-facing
behavior, prefer the README, Product guide, source code, and tests.

- [Context Compiler v2 contract](context-compiler-v2.md)
- [Context Pack v2 contract](context-pack-v2.md)
- [Security for context packs contract](security-context-packs.md)
- [Deterministic project compiler contract](deterministic-project-compiler-contract.md)
- [Knowledge graph contract](knowledge-graph-contract.md)
- [Knowledge graph display strategy](knowledge-graph-display-strategy.md)
- [Connector/graph contract](connectors-graph-contract.md)
- [Founder oversight contract](founder-oversight-contract.md)
- [Roadmap completion contract](roadmap-completion-contract.md)
- [Project map behavior](board-vs-explore.md)

## Status language

Documentation uses these terms consistently:

| Term | Meaning |
|---|---|
| **Available** | The implementation and a tested path exist in this checkout. Configuration, platform, or credentials may still be required. |
| **Dashboard available** | The route is usable through the current browser product shell. |
| **API available** | The backend path exists, even if the corresponding browser route is under construction. |
| **Under construction** | The browser intentionally blocks interaction with an in-progress surface. Data beneath the route is preserved, but it is not a supported browser workflow yet. |
| **Coming soon** | No supported working path exists in this release. |
| **Observed** | DaemonState recorded a result; it does not imply that the result passed or caused an outcome. |
| **Verified** | The stated verifier ran or an exact mechanical check passed under the documented contract. |

## Version and support boundary

The package version is `0.3.0` and the project is an active alpha. The personal
profiles are local, single-user deployments. The hardened profile is a
single-tenant, single-host API deployment without a public dashboard. There is
no hosted DaemonState service, multi-tenant control plane, high-availability
cluster, or browser login in this repository.
