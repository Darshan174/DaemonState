# Security policy

## Supported versions

Security fixes are applied to the latest source-available release. This project
is in active alpha; older releases may not receive backports.

## Reporting a vulnerability

Please use the repository's
[private vulnerability report](https://github.com/Darshan174/DaemonState/security/advisories/new).
If GitHub reports that private reporting is unavailable, contact the
repository owner privately through the contact method on their GitHub profile.
Do not include exploit details, credentials, personal data, or unredacted logs
in a public issue.

Include the affected version, deployment profile, impact, reproduction steps,
and any suggested mitigation. You should receive an acknowledgment within
seven days. No bounty or response-time guarantee is currently offered.

## Deployment boundary

The personal Docker, workstation, and Vite development profiles are
loopback-only and are not safe to expose directly to the public internet. Use
an SSH tunnel for remote dashboard access. The hardened production profile is
API-only until browser session authentication is implemented; follow
[the production runbook](docs/production-runbook.md).
