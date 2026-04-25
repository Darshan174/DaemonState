from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.evals.baseline import NaiveRagBaseline
from app.evals.gold_set import load_default_cases
from app.evals.harness import DomainSummary, EvalSummary, StartupEvalHarness
from app.models.eval import EvalCaseResultRecord, EvalRun
from app.models.user import Workspace
from app.schemas.eval import (
    EvalBlockerRead,
    EvalCaseRead,
    EvalCasesRead,
    EvalDomainSummaryRead,
    EvalSummaryRead,
)
from app.schemas.query import QueryFilters
from app.services.query_service import QueryService


class EvalServiceError(Exception):
    """Base eval service error."""


class EvalWorkspaceNotFoundError(EvalServiceError):
    """Raised when the referenced workspace does not exist."""


class EvalRequestError(EvalServiceError):
    """Raised when an eval trigger request is invalid."""


class EvalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run_latest(
        self,
        *,
        workspace_id: UUID,
        domains: list[str] | None = None,
        case_ids: list[str] | None = None,
        pass_threshold: float = 0.5,
        trigger_source: str = "admin_api",
    ) -> EvalRun:
        await self._require_workspace(workspace_id)
        cases = load_default_cases(domains=domains, ids=case_ids)
        if not cases:
            raise EvalRequestError("No eval cases matched the requested filters")

        summary = await StartupEvalHarness(
            QueryService(self.session),
            baseline_runner=NaiveRagBaseline(self.session),
            pass_threshold=pass_threshold,
        ).run(
            workspace_id=workspace_id,
            cases=cases,
            filters=QueryFilters(),
        )

        run = EvalRun(
            workspace_id=workspace_id,
            total=summary.total,
            passed_count=summary.passed_count,
            failed_count=summary.failed_count,
            pass_rate=summary.pass_rate,
            pass_threshold=summary.pass_threshold,
            average_retrieval_hit_quality=summary.average_retrieval_hit_quality,
            average_extracted_fact_correctness=summary.average_extracted_fact_correctness,
            average_final_answer_correctness=summary.average_final_answer_correctness,
            average_citation_accuracy=summary.average_citation_accuracy,
            average_stale_context_detection=summary.average_stale_context_detection,
            average_naive_answer_correctness=summary.average_naive_answer_correctness,
            average_context_answer_lift=summary.average_context_answer_lift,
            confidence_calibration_error=summary.confidence_calibration_error,
            trigger_source=trigger_source,
        )
        self.session.add(run)
        await self.session.flush()

        for case in summary.cases:
            self.session.add(
                EvalCaseResultRecord(
                    eval_run_id=run.id,
                    case_id=case.case_id or "",
                    domain=case.domain or "unknown",
                    question=case.question,
                    predicted_confidence=case.predicted_confidence,
                    retrieval_hit_quality=case.retrieval_hit_quality,
                    extracted_fact_correctness=case.extracted_fact_correctness,
                    final_answer_correctness=case.final_answer_correctness,
                    citation_accuracy=case.citation_accuracy,
                    stale_context_detection=case.stale_context_detection,
                    naive_answer_correctness=case.naive_answer_correctness,
                    context_answer_lift=case.context_answer_lift,
                    passed=case.passed,
                    detail=case.detail or "",
                )
            )

        await self.session.commit()
        return await self._get_run(run.id)

    async def get_latest_run(self, workspace_id: UUID) -> EvalRun | None:
        await self._require_workspace(workspace_id)
        return await self.session.scalar(
            select(EvalRun)
            .options(selectinload(EvalRun.case_results))
            .where(EvalRun.workspace_id == workspace_id)
            .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
        )

    async def get_summary_payload(self, workspace_id: UUID) -> EvalSummaryRead:
        run = await self.get_latest_run(workspace_id)
        if run is None:
            return EvalSummaryRead(workspace_id=workspace_id)
        return self._serialize_summary(run)

    async def get_cases_payload(
        self,
        workspace_id: UUID,
        *,
        domain: str | None = None,
    ) -> EvalCasesRead:
        run = await self.get_latest_run(workspace_id)
        if run is None:
            return EvalCasesRead(workspace_id=workspace_id, selected_domain=domain)

        cases = [
            self._serialize_case(case)
            for case in run.case_results
            if domain is None or case.domain == domain
        ]
        return EvalCasesRead(
            **self._serialize_summary(run).model_dump(),
            selected_domain=domain,
            cases=cases,
        )

    async def _require_workspace(self, workspace_id: UUID) -> None:
        workspace = await self.session.scalar(
            select(Workspace.id).where(Workspace.id == workspace_id).limit(1)
        )
        if workspace is None:
            raise EvalWorkspaceNotFoundError("Workspace not found")

    async def _get_run(self, run_id: UUID) -> EvalRun:
        run = await self.session.scalar(
            select(EvalRun)
            .options(selectinload(EvalRun.case_results))
            .where(EvalRun.id == run_id)
        )
        assert run is not None
        return run

    def _serialize_summary(self, run: EvalRun) -> EvalSummaryRead:
        case_results = [
            self._to_harness_case_result(case)
            for case in run.case_results
        ]
        summary = EvalSummary(
            cases=case_results,
            pass_threshold=run.pass_threshold,
            average_retrieval_hit_quality=run.average_retrieval_hit_quality,
            average_extracted_fact_correctness=run.average_extracted_fact_correctness,
            average_final_answer_correctness=run.average_final_answer_correctness,
            average_citation_accuracy=run.average_citation_accuracy,
            average_stale_context_detection=run.average_stale_context_detection,
            average_naive_answer_correctness=run.average_naive_answer_correctness,
            average_context_answer_lift=run.average_context_answer_lift,
            confidence_calibration_error=run.confidence_calibration_error,
            domain_summaries=self._build_domain_summaries(case_results),
            pass_rate=run.pass_rate,
            total=run.total,
            passed_count=run.passed_count,
            failed_count=run.failed_count,
        )
        return EvalSummaryRead(
            run_id=run.id,
            workspace_id=run.workspace_id,
            latest_run_timestamp=run.created_at,
            total=summary.total,
            passed_count=summary.passed_count,
            failed_count=summary.failed_count,
            pass_rate=summary.pass_rate,
            pass_threshold=summary.pass_threshold,
            average_retrieval_hit_quality=summary.average_retrieval_hit_quality,
            average_extracted_fact_correctness=summary.average_extracted_fact_correctness,
            average_final_answer_correctness=summary.average_final_answer_correctness,
            average_citation_accuracy=summary.average_citation_accuracy,
            average_stale_context_detection=summary.average_stale_context_detection,
            average_naive_answer_correctness=summary.average_naive_answer_correctness,
            average_context_answer_lift=summary.average_context_answer_lift,
            confidence_calibration_error=summary.confidence_calibration_error,
            all_passed=summary.all_passed,
            domain_summaries=[
                EvalDomainSummaryRead(
                    domain=item.domain,
                    case_count=item.case_count,
                    avg_retrieval=item.avg_retrieval,
                    avg_extraction=item.avg_extraction,
                    avg_answer=item.avg_answer,
                    avg_citation=item.avg_citation,
                    avg_staleness=item.avg_staleness,
                    avg_context_lift=item.avg_context_lift,
                    pass_rate=item.pass_rate,
                )
                for item in summary.domain_summaries
            ],
            blockers=[
                EvalBlockerRead(
                    case_id=item.case_id or "",
                    domain=item.domain or "unknown",
                    question=item.question,
                    detail=item.detail or "Eval case failed",
                )
                for item in summary.cases
                if not item.passed
            ],
        )

    @staticmethod
    def _serialize_case(case: EvalCaseResultRecord) -> EvalCaseRead:
        return EvalCaseRead(
            case_id=case.case_id,
            domain=case.domain,
            question=case.question,
            predicted_confidence=case.predicted_confidence,
            retrieval_hit_quality=case.retrieval_hit_quality,
            extracted_fact_correctness=case.extracted_fact_correctness,
            final_answer_correctness=case.final_answer_correctness,
            citation_accuracy=case.citation_accuracy,
            stale_context_detection=case.stale_context_detection,
            naive_answer_correctness=case.naive_answer_correctness,
            context_answer_lift=case.context_answer_lift,
            passed=case.passed,
            detail=case.detail,
        )

    @staticmethod
    def _to_harness_case_result(case: EvalCaseResultRecord):
        from app.evals.harness import EvalCaseResult

        return EvalCaseResult(
            case_id=case.case_id,
            domain=case.domain,
            question=case.question,
            predicted_confidence=case.predicted_confidence,
            retrieval_hit_quality=case.retrieval_hit_quality,
            extracted_fact_correctness=case.extracted_fact_correctness,
            final_answer_correctness=case.final_answer_correctness,
            citation_accuracy=case.citation_accuracy,
            stale_context_detection=case.stale_context_detection,
            naive_answer_correctness=case.naive_answer_correctness,
            context_answer_lift=case.context_answer_lift,
            passed=case.passed,
            detail=case.detail,
        )

    @staticmethod
    def _build_domain_summaries(case_results) -> list[DomainSummary]:
        by_domain: dict[str, list] = {}
        for result in case_results:
            by_domain.setdefault(result.domain or "unknown", []).append(result)

        summaries: list[DomainSummary] = []
        for domain, items in sorted(by_domain.items()):
            passed = sum(1 for item in items if item.passed)
            summaries.append(
                DomainSummary(
                    domain=domain,
                    case_count=len(items),
                    avg_retrieval=round(
                        sum(item.retrieval_hit_quality for item in items) / len(items),
                        2,
                    ),
                    avg_extraction=round(
                        sum(item.extracted_fact_correctness for item in items) / len(items),
                        2,
                    ),
                    avg_answer=round(
                        sum(item.final_answer_correctness for item in items) / len(items),
                        2,
                    ),
                    avg_citation=round(
                        sum(item.citation_accuracy for item in items) / len(items),
                        2,
                    ),
                    avg_staleness=round(
                        sum(item.stale_context_detection for item in items) / len(items),
                        2,
                    ),
                    avg_context_lift=round(
                        sum(item.context_answer_lift for item in items) / len(items),
                        2,
                    ),
                    pass_rate=round(passed / len(items), 2),
                )
            )
        return summaries
