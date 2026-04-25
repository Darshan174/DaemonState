"""Evaluation harness for source-backed startup questions.

Runs gold-set questions against ``QueryService`` and scores three dimensions:
  1. **Retrieval hit quality** — did we find the right components?
  2. **Extracted fact correctness** — did the right source types contribute?
  3. **Final answer correctness** — does the answer contain expected substrings?
  4. **Citation accuracy** — do cited sources contain the expected evidence?
  5. **Stale context detection** — does freshness match the expected truth state?
  6. **Context lift** — how much better is Context Engine than naive source-only RAG?

``EvalSummary`` exposes per-case results plus per-domain and overall averages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence
from uuid import UUID

from sqlalchemy import select

from app.evals.baseline import BaselineResult
from app.evals.metrics import (
    answer_substring_coverage,
    confidence_calibration_error,
)
from app.models.source import SourceDocument
from app.schemas.query import FreshnessStatus, QueryFilters
from app.services.query_service import QueryService


@dataclass(frozen=True, slots=True)
class EvalCase:
    question: str
    expected_answer_substrings: tuple[str, ...] = ()
    expected_component_names: tuple[str, ...] = ()
    expected_source_types: tuple[str, ...] = ()
    expected_source_external_ids: tuple[str, ...] = ()
    excluded_source_external_ids: tuple[str, ...] = ()
    expected_freshness: str | None = None
    case_id: str = ""
    domain: str = ""


@dataclass(frozen=True, slots=True)
class EvalCaseResult:
    case_id: str
    domain: str
    question: str
    predicted_confidence: float
    retrieval_hit_quality: float
    extracted_fact_correctness: float
    final_answer_correctness: float
    citation_accuracy: float
    stale_context_detection: float
    naive_answer_correctness: float
    context_answer_lift: float
    passed: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class DomainSummary:
    domain: str
    case_count: int
    avg_retrieval: float
    avg_extraction: float
    avg_answer: float
    avg_citation: float
    avg_staleness: float
    avg_context_lift: float
    pass_rate: float


@dataclass(slots=True)
class EvalSummary:
    cases: list[EvalCaseResult] = field(default_factory=list)
    pass_threshold: float = 0.5
    average_retrieval_hit_quality: float = 0.0
    average_extracted_fact_correctness: float = 0.0
    average_final_answer_correctness: float = 0.0
    average_citation_accuracy: float = 0.0
    average_stale_context_detection: float = 0.0
    average_naive_answer_correctness: float = 0.0
    average_context_answer_lift: float = 0.0
    confidence_calibration_error: float = 0.0
    domain_summaries: list[DomainSummary] = field(default_factory=list)
    pass_rate: float = 0.0
    total: int = 0
    passed_count: int = 0
    failed_count: int = 0

    @property
    def all_passed(self) -> bool:
        return self.failed_count == 0


# Minimum per-metric score for a case to be considered passing.
PASS_THRESHOLD = 0.5


class BaselineRunner(Protocol):
    async def answer(self, question: str, workspace_id: UUID) -> BaselineResult:
        """Return a source-only answer for the same question."""


class StartupEvalHarness:
    def __init__(
        self,
        query_service: QueryService,
        *,
        baseline_runner: BaselineRunner | None = None,
        pass_threshold: float = PASS_THRESHOLD,
    ) -> None:
        self.query_service = query_service
        self.baseline_runner = baseline_runner
        self.pass_threshold = pass_threshold

    async def run(
        self,
        *,
        workspace_id: UUID,
        cases: Sequence[EvalCase],
        filters: QueryFilters | None = None,
    ) -> EvalSummary:
        results: list[EvalCaseResult] = []
        for case in cases:
            response = await self.query_service.query(
                case.question,
                workspace_id,
                filters=filters,
            )
            component_names = {component.name for component in response.components}
            source_types = {source.type for source in response.sources}
            cited_external_ids, cited_source_text = await self._resolve_citations(response)
            answer_text = response.answer.lower()

            retrieval_score = self._coverage_score(
                component_names,
                case.expected_component_names,
            )
            source_score = self._coverage_score(source_types, case.expected_source_types)
            fact_score = retrieval_score
            if case.expected_source_types:
                fact_score = round((retrieval_score + source_score) / 2.0, 2)

            answer_score = self._answer_score(
                answer_text,
                case.expected_answer_substrings,
            )
            citation_score = self._citation_score(
                case=case,
                cited_external_ids=cited_external_ids,
                cited_source_text=cited_source_text,
            )
            response_freshness = getattr(response, "freshness", FreshnessStatus.CURRENT)
            stale_score = self._stale_score(case, response_freshness)
            baseline_answer_score = await self._baseline_answer_score(
                case=case,
                workspace_id=workspace_id,
            )
            context_lift = round(answer_score - baseline_answer_score, 2)

            case_passed = (
                retrieval_score >= self.pass_threshold
                and fact_score >= self.pass_threshold
                and answer_score >= self.pass_threshold
                and citation_score >= self.pass_threshold
                and stale_score >= self.pass_threshold
            )

            detail_parts: list[str] = []
            if retrieval_score < self.pass_threshold:
                detail_parts.append(
                    f"retrieval={retrieval_score:.2f} (expected {case.expected_component_names}, "
                    f"got {sorted(component_names)})"
                )
            if case.expected_source_types and fact_score < self.pass_threshold:
                detail_parts.append(
                    f"extraction={fact_score:.2f} (expected {case.expected_source_types}, "
                    f"got {sorted(source_types)})"
                )
            if answer_score < self.pass_threshold:
                missing = [
                    s for s in case.expected_answer_substrings
                    if s.lower() not in answer_text
                ]
                detail_parts.append(f"answer missing {missing}")
            if citation_score < self.pass_threshold:
                detail_parts.append(
                    f"citation={citation_score:.2f} "
                    f"(expected {case.expected_source_external_ids}, "
                    f"excluded {case.excluded_source_external_ids}, "
                    f"got {sorted(cited_external_ids)})"
                )
            if stale_score < self.pass_threshold:
                detail_parts.append(
                    f"freshness={response_freshness.value} "
                    f"(expected {case.expected_freshness})"
                )

            results.append(
                EvalCaseResult(
                    case_id=case.case_id,
                    domain=case.domain,
                    question=case.question,
                    predicted_confidence=response.confidence,
                    retrieval_hit_quality=retrieval_score,
                    extracted_fact_correctness=fact_score,
                    final_answer_correctness=answer_score,
                    citation_accuracy=citation_score,
                    stale_context_detection=stale_score,
                    naive_answer_correctness=baseline_answer_score,
                    context_answer_lift=context_lift,
                    passed=case_passed,
                    detail="; ".join(detail_parts),
                )
            )

        domain_summaries = self._build_domain_summaries(results)
        passed_count = sum(1 for r in results if r.passed)

        return EvalSummary(
            cases=results,
            pass_threshold=self.pass_threshold,
            average_retrieval_hit_quality=self._average(
                item.retrieval_hit_quality for item in results
            ),
            average_extracted_fact_correctness=self._average(
                item.extracted_fact_correctness for item in results
            ),
            average_final_answer_correctness=self._average(
                item.final_answer_correctness for item in results
            ),
            average_citation_accuracy=self._average(
                item.citation_accuracy for item in results
            ),
            average_stale_context_detection=self._average(
                item.stale_context_detection for item in results
            ),
            average_naive_answer_correctness=self._average(
                item.naive_answer_correctness for item in results
            ),
            average_context_answer_lift=self._average(
                item.context_answer_lift for item in results
            ),
            confidence_calibration_error=confidence_calibration_error(
                [item.predicted_confidence for item in results],
                [item.passed for item in results],
            ),
            domain_summaries=domain_summaries,
            pass_rate=round(passed_count / len(results), 2) if results else 0.0,
            total=len(results),
            passed_count=passed_count,
            failed_count=len(results) - passed_count,
        )

    def _build_domain_summaries(
        self, results: list[EvalCaseResult]
    ) -> list[DomainSummary]:
        by_domain: dict[str, list[EvalCaseResult]] = {}
        for r in results:
            by_domain.setdefault(r.domain or "unknown", []).append(r)

        summaries: list[DomainSummary] = []
        for domain, items in sorted(by_domain.items()):
            passed = sum(1 for i in items if i.passed)
            summaries.append(
                DomainSummary(
                    domain=domain,
                    case_count=len(items),
                    avg_retrieval=self._average(i.retrieval_hit_quality for i in items),
                    avg_extraction=self._average(i.extracted_fact_correctness for i in items),
                    avg_answer=self._average(i.final_answer_correctness for i in items),
                    avg_citation=self._average(i.citation_accuracy for i in items),
                    avg_staleness=self._average(i.stale_context_detection for i in items),
                    avg_context_lift=self._average(i.context_answer_lift for i in items),
                    pass_rate=round(passed / len(items), 2),
                )
            )
        return summaries

    async def _baseline_answer_score(
        self,
        *,
        case: EvalCase,
        workspace_id: UUID,
    ) -> float:
        if self.baseline_runner is None:
            return 0.0
        result = await self.baseline_runner.answer(case.question, workspace_id)
        return answer_substring_coverage(
            case.expected_answer_substrings,
            result.answer,
        )

    async def _resolve_citations(self, response) -> tuple[set[str], str]:
        source_ids = [
            source.source_document_id
            for source in response.sources
            if getattr(source, "source_document_id", None) is not None
        ]
        if not source_ids:
            return self._fallback_external_ids(response), ""

        session = getattr(self.query_service, "session", None)
        if session is None:
            return self._fallback_external_ids(response), ""

        rows = await session.scalars(
            select(SourceDocument).where(SourceDocument.id.in_(source_ids))
        )
        documents = list(rows)
        return (
            {doc.external_id for doc in documents},
            "\n".join(doc.content for doc in documents),
        )

    @staticmethod
    def _fallback_external_ids(response) -> set[str]:
        external_ids: set[str] = set()
        for source in response.sources:
            url = getattr(source, "url", None)
            if not url:
                continue
            external_ids.add(url.rstrip("/").rsplit("/", 1)[-1])
        return external_ids

    def _citation_score(
        self,
        *,
        case: EvalCase,
        cited_external_ids: set[str],
        cited_source_text: str,
    ) -> float:
        checks: list[float] = []
        if case.expected_source_external_ids:
            checks.append(
                self._coverage_score(
                    cited_external_ids,
                    case.expected_source_external_ids,
                )
            )
        if case.excluded_source_external_ids:
            excluded = set(case.excluded_source_external_ids)
            checks.append(1.0 if cited_external_ids.isdisjoint(excluded) else 0.0)
        if (
            cited_source_text
            and case.expected_answer_substrings
            and case.expected_source_external_ids
        ):
            checks.append(
                answer_substring_coverage(
                    case.expected_answer_substrings,
                    cited_source_text,
                )
            )
        if not checks:
            return 1.0
        return round(sum(checks) / len(checks), 2)

    @staticmethod
    def _stale_score(case: EvalCase, actual_freshness: FreshnessStatus) -> float:
        if case.expected_freshness is None:
            return 1.0
        return 1.0 if actual_freshness.value == case.expected_freshness else 0.0

    @staticmethod
    def _coverage_score(found: set[str], expected: Sequence[str]) -> float:
        if not expected:
            return 1.0 if found else 0.0
        hits = sum(1 for item in expected if item in found)
        return round(hits / len(expected), 2)

    @staticmethod
    def _answer_score(answer_text: str, expected_substrings: Sequence[str]) -> float:
        if not expected_substrings:
            return 1.0 if answer_text else 0.0
        hits = sum(1 for item in expected_substrings if item.lower() in answer_text)
        return round(hits / len(expected_substrings), 2)

    @staticmethod
    def _average(values) -> float:
        values = list(values)
        if not values:
            return 0.0
        return round(sum(values) / len(values), 2)
