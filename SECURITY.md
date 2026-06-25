# Security Policy

Context Engine is self-hosted project memory for AI agents. Security reports
should focus on issues that could expose source documents, connector
credentials, workspace data, generated context packs, or MCP/API access.

## Supported Versions

Security fixes target the current `main` branch until the project publishes
versioned releases.

## Reporting A Vulnerability

Please do not open a public issue for a suspected vulnerability.

Until a dedicated security advisory channel is configured, email the maintainer
listed in the GitHub repository profile or open a private GitHub security
advisory if the repository enables advisories.

Include:

- A short description of the impact.
- Reproduction steps or a proof of concept.
- Affected commit, release, or Docker image tag.
- Whether connector credentials, source documents, or MCP responses can be
  accessed or modified.

## Security Expectations

- Do not log access tokens, OAuth secrets, source document bodies, or generated
  context packs in plaintext.
- Do not mark a connector as working unless auth, sync, and `SourceDocument`
  ingestion are implemented and tested.
- Every extracted fact and relationship should preserve provenance so users can
  audit what an AI agent consumed.
- New API or MCP surfaces should keep workspace scope, source IDs, and evidence
  explicit.
