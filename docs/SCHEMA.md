# Public demonstration schema

`schemas/context-bundle.schema.json` describes
`daemonstate.public.context_bundle.v1`.

This is a simplified educational contract. It is not the production Workspace
Context schema, Session Context schema, database model, or hosted API response.
It deliberately omits internal identifiers, hashes, scores, graph structures,
ranking signals, trust policy, integrity gates, and entitlement metadata.

The bundle has three sections:

- `workspace`: plain project-wide facts in a synthetic example.
- `session`: plain state for one synthetic work session.
- `provenance`: an explicit statement that the fixture is synthetic.

The CLI rejects unknown schema versions and missing or incorrectly typed fields.
That validation only checks this public format; it does not establish that a
claim is true, current, safe, or eligible for a real DaemonState handoff.

To validate a file:

```bash
python -m daemonstate_public validate path/to/context.json
```

To render it:

```bash
python -m daemonstate_public render path/to/context.json --format markdown
```
