# Evals and Benchmarks

Context Engine ships with a deterministic startup-memory benchmark so changes
can be judged by evidence, not screenshots.

The benchmark asks the same questions against:

- **Naive source-only RAG**: lexical retrieval over raw source documents.
- **Context Engine**: structured facts, source provenance, review state, current
  truth filtering, and freshness signals.

## Tracks

| Track | What It Measures | Why It Matters |
| --- | --- | --- |
| Answer quality | Expected answer facts are present in the response | The system should answer the user, not only retrieve nearby text |
| Citation accuracy | Cited source documents contain the expected evidence and avoid superseded sources | Teams need to know where an answer came from |
| Stale context detection | Returned freshness matches the expected current-truth state | Fast-moving teams need old decisions and stale facts to stop leaking into answers |
| Retrieval hit quality | Expected structured components were selected | Regressions in retrieval stay visible before they become product bugs |
| Context lift | Context Engine answer score minus naive source-only answer score | Shows whether structured context is improving on plain RAG |

## Dataset

The canonical dataset is [app/evals/fixtures.jsonl](../app/evals/fixtures.jsonl).
It models a small startup memory with:

- product roadmap docs
- pricing changes
- customer feedback
- meeting notes
- old decisions superseded by newer decisions
- conflicting or stale source documents

The deterministic source data is seeded by
[app/evals/demo_seed.py](../app/evals/demo_seed.py). The same data powers the
demo workspace, local benchmarks, API tests, and contributor onboarding.

## Run Locally

Start the stack and seed the demo workspace:

```bash
bash scripts/bootstrap.sh
```

Run the regression gate against the seeded workspace:

```bash
python3 scripts/run_eval_regression.py --workspace-id <workspace-id>
```

For machine-readable output:

```bash
python3 scripts/run_eval_regression.py --workspace-id <workspace-id> --json
```

Run only one track or case family:

```bash
python3 scripts/run_eval_regression.py --workspace-id <workspace-id> --domains staleness
python3 scripts/run_eval_regression.py --workspace-id <workspace-id> --case-ids stale-001
```

## Current Gate

| Requirement | Threshold |
| --- | ---: |
| Total cases | 30 |
| Cases per required domain | 5 |
| Required domains | pricing, blocker, roadmap, decision, meeting, staleness |
| Pass rate | 80% |
| Retrieval hit quality | 80% |
| Extracted fact correctness | 80% |
| Final answer correctness | 75% |
| Citation accuracy | 80% |
| Stale context detection | 90% |
| Confidence calibration error | <= 25% |

These thresholds live in [app/evals/policy.py](../app/evals/policy.py).

## Interpreting Results

The human report shows every case with retrieval, extraction, answer, citation,
staleness, and context-lift scores. A failing case includes the missing
component names, source types, answer substrings, or freshness state.

The JSON report includes:

- `average_naive_answer_correctness`
- `average_final_answer_correctness`
- `average_context_answer_lift`
- `average_citation_accuracy`
- `average_stale_context_detection`
- per-domain summaries
- per-case blockers

This makes the eval output suitable for local development, CI gates, dashboard
display, and release notes.
