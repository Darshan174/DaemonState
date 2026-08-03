# Prompt Quality Contract

All production LLM calls use `PromptArtifact`. Prompt text is treated as a
versioned execution contract rather than an interpolated string.

## Required Shape

Every prompt has four ordered authority lanes:

1. trusted system policy;
2. trusted task instruction;
3. an untrusted JSON data envelope;
4. a closed JSON output contract.

Raw documents, questions, graph values, tool output, and retrieved text belong
only in the untrusted envelope. They must never be interpolated into the system
message. The runtime selects the strongest provider mode available: native JSON
Schema, JSON-object mode, then prompt-only JSON. Every response is still parsed
and validated locally before it affects product state. Providers receive a
conservative structural schema; bounds and uniqueness stay in the full local
contract because provider JSON-Schema subsets differ.

Artifacts bind rendering and hashes to constructor-validated deep snapshots.
API-visible audit metadata is content-independent: prompt, renderer, input
contract and validator versions, model identifier, definition/schema hashes,
and authority lanes. Input-dependent hashes and lengths are not exposed because
they can make low-entropy private state guessable.

## Definition And Behavior Gates

Prompt versions use semantic versioning. Any behavioral policy, output schema,
temperature, token limit, renderer, declared input contract, or semantic
validator version changes `definition_sha256` and must deliberately update the
golden pin in `tests/test_prompt_quality_gates.py`. Behavior changes also bump
the prompt version.

The golden gate additionally fails when:

- adversarial source text reaches a system message or audit metadata;
- a completion call bypasses the single `PromptArtifact` provider boundary;
- a production prompt consumer is introduced without registration;
- a prompt definition varies with runtime input or provider choice.

Golden fingerprints detect definition drift; they are not a semantic quality
score. The adjacent behavior corpus rejects unsupported extraction facts,
uncited or unrelated answers, context-pack task injection, graph claims without
supporting edges, truncated-snapshot absence claims, and unauthorized outbound
source data.

Run the focused gate with:

```bash
pytest -q tests/test_prompt_quality_gates.py
```

## Adding Or Changing A Prompt

1. Add a pure artifact builder and stable prompt ID/version constants.
2. Use bounded structured records with stable local IDs as untrusted data.
3. Define a closed schema with all object properties required.
4. Add semantic validation for citations, entity IDs, allowed transitions, and
   contradictions that JSON Schema cannot establish.
5. Preserve a deterministic, non-LLM fallback.
6. Add injection, malformed-output, provider-capability, audit-redaction, and
   fallback tests.
7. Register and pin the definition in the golden quality gate.

Agent prompts must apply the caller's workspace and source grants before data is
materialized into an artifact. Context-pack models select typed evidence IDs;
the application validates those IDs, removes high-risk prompt-injection-like
records, and renders the Markdown deterministically.

Trust separation prevents source text from gaining instruction authority; it
does not prove the source is true. Source provenance, trust zones, freshness,
and conflict handling remain the responsibility of the evidence ledger and
context compiler described in [Security For Context Packs](security-context-packs.md).
