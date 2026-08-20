# Repository boundary

DaemonState uses two separate boundaries:

1. **Source boundary:** what code is public or private.
2. **Entitlement boundary:** what Free or Pro users can access.

They are intentionally not the same.

## Public source

This toolkit can:

- validate the simplified public demonstration bundle;
- render that bundle as readable Markdown or normalized JSON;
- show the shape of a safe adapter integration; and
- run the same synthetic demonstration in Docker.

It cannot generate a real bundle from a repository or coding session.

## Private source

The private product contains:

- extraction, compiler, scoring, ranking, and quality logic;
- workspace graph, durable memory, evidence, and claim handling;
- session discovery, checkpoints, verification, and handoff delivery;
- production API, dashboard, desktop overlay, and connectors;
- authentication, authorization, Free/Pro entitlements, and monetization; and
- analytics, infrastructure, deployment, and internal strategy.

## Free and Pro

A Free user may receive limited results produced by the private engine. A Pro
user may receive greater scope, history, delivery, or automation from that same
engine. The public toolkit does not implement or enforce either entitlement.
Entitlements must be enforced inside the private daemon or service, not by
hiding public UI controls.

## Clean-history rule

The public repository must be created from this export only. Do not fork the
private repository, copy its `.git` directory, merge its history, or build the
public repository by deleting private paths from a private checkout.
