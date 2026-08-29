# Context Quality Engine — corrected gold-adjudicated result

> Correction, 2026-08-24: the earlier 75.5/100 result was invalid. Missing
> expectations were filled with hashes from the same request and attachment
> resolvers being graded. That made exact self-reproduction look like
> independent objective and dependency recovery. The old JSON is retained as
> explicitly superseded historical evidence; the corrected report is
> [`context-quality-engine-gold-run-2026-08-24.json`](context-quality-engine-gold-run-2026-08-24.json).

The corrected comparison uses the same eight immutable checkpoint UUIDs and a
separate, baseline-hash-bound gold manifest. It does not select recent sessions,
write to the application database, persist the Workspace candidate, or commit
raw session text.

## Result

| Context | Frozen baseline | Current candidate | Meaning |
| --- | ---: | ---: | --- |
| Session mean score | 35.25/100 | 28.62/100 strict; 85.125 pre-cap | −6.62 strict after delivery/readiness caps |
| Session candidates promoted | 0/8 | 1/8 | One candidate is fully copy-safe background context |
| Session candidates rejected | 8/8 | 7/8 | Five lack source bytes; two lack change-ownership readiness |
| Workspace score | 59/100 | 59/100 | Its underlying evidence quality has not been overstated |
| Workspace delivery | copy allowed | copy blocked; review required | The controller now enforces the existing warning state |

All eight Session candidates now match the raw-event-adjudicated objective text
contract and independently verify the minimum required provider-event authority
chain. All eight also match the complete frozen attachment manifest exactly;
the seven required attachment hashes are recovered with no omissions or
unexpected required dependencies.

The remaining rejects are delivery/readiness failures, not objective or
attachment-identity failures. Five cases recover the exact required attachment
identities but the source bytes are unavailable in this replay environment, so
they receive `REQUIRED_ATTACHMENT_BYTES_UNAVAILABLE`. The two push-only cases
have no required attachments but retain the runtime's non-attachment
`REQUIRED_DEPENDENCY_MISSING` change-ownership gate. Those seven cases are
capped at 19. Case `968ab8a38e` has exact objective authority, zero expected and
zero candidate-required attachments, no hard failures, and promotes at 96.

The corrected result is deliberately harsher than a semantic-only score.
Before hard caps, the two push-only candidates score 93 and the five
byte-unavailable candidates score 79–83. The 28.62 mean therefore says that
automatic copy remains unsafe in this environment; it does not say objective
reconstruction or attachment identity recovery failed. Those two semantic
lanes are 8/8 and 7/7 respectively.

Workspace Context remains a 59-point review candidate because durable promoted
knowledge and exact-snapshot verification are still absent. The important
change is control, not an inflated score: the legacy path exposed it as
copyable, while the controller returns `copy_allowed=false` and `review`.

## Repository drift

The Workspace comparison crossed repository snapshots, so drift is reported
separately:

- Baseline HEAD: `3ab7d1f65d6d85771c0f328983f91f43d0a385fb`
- Corrected-run candidate HEAD: `5d2a28ba02f1609a8b735cb9a90e122eed6b645e`
- Baseline changed paths: 39
- Corrected-run changed paths: 70
- Changed identity fields: snapshot fingerprint, HEAD, and changed-path count

Therefore the unchanged Workspace score is not presented as a compiler-only
causal comparison. It shows that the new controller correctly preserves the
review verdict despite repository movement.

## Validation

- Exact read-only benchmark: 8/8 frozen checkpoint identities, baseline payload
  hashes, and gold case identities validated; exit code 0.
- Gold SHA-256: `8f86ee7342153be9cb31b19b697b4931c03cd202c6b23f31e7ec2032e5a67485`.
- Candidate-derived expectations: disabled.
- All 34 case-scoped source-event records (30 unique across the corpus) were
  verified as belonging to the frozen session at or before its boundary; all
  seven required attachment hashes were verified directly in raw payloads.
- The final gold is single-reviewer and non-fully-blinded. The reviewer was
  blind to candidates, resolver output, benchmark code, tests, and prior gold,
  but knew the corpus, frozen boundaries, and disputed questions. There is no
  inter-rater agreement estimate. An earlier candidate-contaminated draft was
  discarded and is not used by this run.
- Objective authority uses source-adjudicated provider message IDs. Database
  `SessionEvent` UUIDs remain audit evidence in a separate namespace and never
  satisfy candidate authority bindings. The scorer requires the minimal active
  leaf, permits only a bounded antecedent envelope, and supports one-of groups
  for byte-identical duplicate provider transports.
- Attachment gold is complete at every boundary. Candidate-required dependency
  count and SHA-256 set must match exactly; omission and over-inclusion are
  distinct failures. Missing source bytes are reported separately from either.
- Focused verification: 44 benchmark tests, 10 context-safety regressions,
  eight documentation checks, and 65 objective/session-context tests passed;
  Ruff passed on the benchmark implementation, CLI, and tests.
- Deterministic all-of intent concepts can still reject a faithful paraphrase
  or reward keyword-shaped text. Relevant-file labels remain sparse, and the
  Workspace comparison crosses repository snapshots.
- Full corrected scores and failure codes are in
  [`context-quality-engine-gold-run-2026-08-24.json`](context-quality-engine-gold-run-2026-08-24.json).

Run it with:

```bash
.venv/bin/python scripts/benchmark_context_quality.py \
  --baseline docs/experiments/context-quality-engine-baseline-2026-08-20.json \
  --gold docs/experiments/context-quality-engine-frozen-gold-2026-08-24.json \
  --mode all
```
