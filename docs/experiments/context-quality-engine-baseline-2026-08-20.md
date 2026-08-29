# Context Quality Engine baseline — 2026-08-20

This is the frozen pre-controller benchmark for the Context Quality Engine.
The machine-readable corpus is
[`context-quality-engine-baseline-2026-08-20.json`](context-quality-engine-baseline-2026-08-20.json).
Its separately adjudicated labels are frozen in
[`context-quality-engine-frozen-gold-2026-08-24.json`](context-quality-engine-frozen-gold-2026-08-24.json).

Raw Session Context text is intentionally not committed. The manifest records
the exact immutable checkpoint UUID, checkpoint payload SHA-256, rendered
SHA-256, rubric version, score, and hard failures needed to replay each case
from the local application database.

## Verdict

- Eight real Session Contexts: **35.3/100 mean; 8/8 rejected**.
- Current Workspace Context: **59/100; review only** despite the old
  `copy_ready=true` result.

All eight Session Contexts contain generated `Start here` and `Done when`
sections. That is incompatible with the corrected product contract: Session
Context is background the user builds on, not authority to continue a task.
Four samples also fail to recover an unambiguous underlying objective, one
drops required screenshot evidence, and two allow “changes from this session”
language to contaminate target-file inference.

The Workspace Context is substantially safer: it is background-only,
hash-bound, and honest about uncertainty. It is nevertheless too incomplete
for automatic promotion: no promoted durable facts, no exact-snapshot
verification runs, weak provenance, only 25% required-lane coverage, and
material bounded omissions.

## Comparison rule

The post-change run must use the same eight checkpoint UUIDs. It may not
reselect the latest sessions. A case cannot disappear from the result. The
Workspace comparison must separately report repository snapshot drift because
the controller implementation itself changes the repository.

Hard failures override aggregate scores. A high average can never compensate
for a dropped user constraint, missing required evidence, inferred action,
unsupported completion claim, stale current-state claim, scope leak, or
unjustified removal.

## Reproduce the corrected benchmark

Session scoring requires the separate gold manifest. The benchmark refuses to
manufacture missing objective or attachment expectations from runtime resolver
output.

```bash
.venv/bin/python scripts/benchmark_context_quality.py \
  --baseline docs/experiments/context-quality-engine-baseline-2026-08-20.json \
  --gold docs/experiments/context-quality-engine-frozen-gold-2026-08-24.json \
  --mode all
```

The final gold was independently re-adjudicated from raw `session_events` and
assistant completion/status evidence at or before each frozen checkpoint
boundary. The final reviewer did not inspect candidate Session Contexts,
request/attachment resolver output, benchmark code, tests, or prior labels; an
earlier contaminated draft was discarded. This remains a **single-reviewer,
non-fully-blinded** label set: the reviewer knew the corpus and case boundaries,
and there is no inter-rater agreement estimate. A resolved objective must match
either a frozen acceptable hash or every frozen intent concept, and must
independently cover its required raw provider message IDs in both resolver
provenance and claim evidence. Database `SessionEvent` UUIDs are audit evidence
only and are never compared with provider message IDs. Attachment gold is
complete at every boundary: candidate-required dependencies must match the
frozen count and SHA-256 set exactly, so both omission and over-inclusion fail.
The deterministic phrase contract can still miss valid paraphrases or reward
keyword-shaped text, and several relevant-file lanes remain unlabelled.
