# Session handoff brief v2 paired replay

Date: 2026-08-03

## Method

- Rendered `legacy_v1` and `compact_v2` from the same typed contract for 20
  recent, distinct, real DaemonState checkpoints.
- Kept every requirement, repository snapshot, authority rule, and preservation
  rule identical between variants.
- Ran a blinded behavioral smoke test on six paired prompts with local
  `qwen2.5:7b`, temperature zero, alternating variant order.
- The benchmark was read-only: it did not stage a desktop handoff, launch a
  provider turn, edit a repository, or write results to the product database.

## Results

| Measure | `legacy_v1` | `compact_v2` |
|---|---:|---:|
| Mean prompt characters | 4,770 | 2,631 |
| Mean estimated tokens | 1,193 | 658 |
| Mean headings | 25.5 | 6.0 |
| Mean non-empty lines | 63.4 | 26.7 |
| Median characters before the action | 1,807 | 1,038 |
| Full requirement coverage | 100% | 100% |
| Cases with opaque action IDs | 10/20 | 0/20 |
| Cases with render issues | 1/20 | 0/20 |

The compact prompt was shorter in all 20 pairs, with a mean size reduction of
44.6%.

The original permission and requirement scores were contract-consistency
checks: they could confirm that a renderer followed its input, but not that the
input contract correctly understood the user. A later adversarial case
(`dont let cards be transparent`) exposed that limitation by compiling a UI
change as a read-only report while still scoring the rendered permission as
correct. Intent-classification, normalized-outcome, target-resolution, and
acceptance checks now use independently labeled regression fixtures before
renderer fidelity is evaluated.

| Local-model replay | `legacy_v1` | `compact_v2` |
|---|---:|---:|
| Correct concrete first action | 33% | 100% |
| Captured “do not repeat” state | 33% | 100% |
| Completion-criterion coverage | 0% | 50% |
| Permission accuracy | 100% | 100% |
| Preservation accuracy | 100% | 100% |
| Combined orientation score | 41.7% | 87.5% |

The first replay exposed a candidate defect: the repository safety check
preceded the concrete task action, so the model selected inspection as the task.
The candidate was corrected to put `First action` first, while retaining the
mandatory pre-edit repository check. The table contains the corrected replay.

A later attachment-backed UI fixture exposed a second projection defect. The
renderer turned attachment inspection into a synthetic R2, fell back to a
generic goal, exposed capture-host paths and numeric target confidence, and
omitted a concrete verification method. The current projection keeps exactly
five sections, links A1 directly to the real R1, uses a contract-local evidence
identity plus hash, renders qualitative candidate evidence, separates task
capability from capture-time permission, and emits ordered discovery and
planned-verification steps. It now also carries an integrity-checked Git
index/worktree manifest rather than only a dirty-file count, and delegates
artifact materialization and hash checks to infrastructure. Desktop staging
publishes hash-verified, receiver-local copies of required images and the exact
baseline manifest before opening the composer. The inspection
validator accepts only hash-bound observations from infrastructure-owned
descriptors; no production inspection producer exists yet. Capture permission
is rendered as not observed rather than inferred from task type, and any
unmet terminal prerequisite stops the action list until the context is
regenerated. The richer projection permits up to 5,000
characters of renderer overhead and up to 85% of the legacy prompt in the
representative fail-closed fixture; compactness is subordinate to preserving
execution-critical evidence.

## Verdict

`compact_v2` passes the offline paired smoke test and is eligible for a live
user trial. It is not yet proven to improve production outcomes: the behavioral
sample is small, uses one local model, uses historical Codex checkpoints, and
relies on an automated lexical grader. Promotion still requires comparable live
submitted tasks with observed completion and verification outcomes.

## Reproduce

Structural replay:

```bash
.venv/bin/python scripts/compare_session_handoff_variants.py \
  --workspace daemonstate --cases 20
```

Optional local-model replay:

```bash
.venv/bin/python scripts/compare_session_handoff_variants.py \
  --workspace daemonstate --cases 12 \
  --ollama-model qwen2.5:7b --model-cases 6
```
