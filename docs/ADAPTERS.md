# Adapter boundary

`daemonstate_public.adapters.ContextBundleAdapter` is a small public protocol
for obtaining a bundle. It does not contain connector discovery, OAuth, local
session access, repository indexing, or context compilation.

The included `examples/minimal_adapter.py` reads the bundled synthetic JSON from
disk. It performs no network access and executes no commands.

A future hosted adapter should:

- receive credentials from an environment variable, operating-system keychain,
  or another secret store rather than command-line arguments;
- send only the minimum workspace or bundle identifier required;
- let the private service enforce authentication and Free/Pro entitlements;
- reject unrecognized schema versions;
- avoid logging raw context or credentials; and
- fail closed when integrity or authorization cannot be established.

The public adapter must not reproduce private extraction, scoring, ranking,
memory, graph, or handoff logic locally.
