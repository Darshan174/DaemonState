from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.evals.harness import EvalCase, StartupEvalHarness
from app.schemas.query import FreshnessStatus


@dataclass
class _FakeComponent:
    name: str


@dataclass
class _FakeSource:
    type: str


@dataclass
class _FakeQueryResult:
    answer: str
    confidence: float
    components: list[_FakeComponent]
    sources: list[_FakeSource]
    freshness: FreshnessStatus = FreshnessStatus.CURRENT


class _FakeQueryService:
    def __init__(self, results):
        self.results = results

    async def query(self, question, workspace_id, filters=None):
        return self.results[question]


class TestStartupEvalHarness:
    async def test_scores_retrieval_fact_and_answer_quality(self):
        harness = StartupEvalHarness(
            _FakeQueryService(
                {
                    "What is our pricing?": _FakeQueryResult(
                        answer="Enterprise Plan: $600/seat.",
                        confidence=0.9,
                        components=[_FakeComponent(name="Enterprise Plan")],
                        sources=[_FakeSource(type="notion")],
                    )
                }
            )
        )

        summary = await harness.run(
            workspace_id=uuid4(),
            cases=[
                EvalCase(
                    question="What is our pricing?",
                    expected_answer_substrings=("$600/seat",),
                    expected_component_names=("Enterprise Plan",),
                    expected_source_types=("notion",),
                )
            ],
        )

        assert len(summary.cases) == 1
        assert summary.cases[0].retrieval_hit_quality == 1.0
        assert summary.cases[0].extracted_fact_correctness == 1.0
        assert summary.cases[0].final_answer_correctness == 1.0
        assert summary.cases[0].citation_accuracy == 1.0
        assert summary.cases[0].stale_context_detection == 1.0
        assert summary.cases[0].naive_answer_correctness == 0.0
        assert summary.cases[0].context_answer_lift == 1.0
        assert summary.cases[0].predicted_confidence == 0.9
        assert summary.average_final_answer_correctness == 1.0
        assert summary.average_citation_accuracy == 1.0
        assert summary.average_stale_context_detection == 1.0
        assert summary.average_context_answer_lift == 1.0
        assert summary.confidence_calibration_error == 0.1

    async def test_scores_stale_context_detection(self):
        harness = StartupEvalHarness(
            _FakeQueryService(
                {
                    "What is current?": _FakeQueryResult(
                        answer="Old fact: $500/seat.",
                        confidence=0.7,
                        components=[_FakeComponent(name="Legacy Plan")],
                        sources=[_FakeSource(type="notion")],
                        freshness=FreshnessStatus.STALE,
                    )
                }
            )
        )

        summary = await harness.run(
            workspace_id=uuid4(),
            cases=[
                EvalCase(
                    question="What is current?",
                    expected_answer_substrings=("$600/seat",),
                    expected_component_names=("Enterprise Plan",),
                    expected_source_types=("notion",),
                    expected_freshness="current",
                )
            ],
        )

        assert summary.cases[0].stale_context_detection == 0.0
        assert not summary.cases[0].passed
        assert "freshness=stale" in summary.cases[0].detail
