from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class EvalDomainSummaryRead(BaseModel):
    domain: str
    case_count: int
    avg_retrieval: float
    avg_extraction: float
    avg_answer: float
    avg_citation: float = 0.0
    avg_staleness: float = 0.0
    avg_context_lift: float = 0.0
    pass_rate: float


class EvalCaseRead(BaseModel):
    case_id: str
    domain: str
    question: str
    predicted_confidence: float
    retrieval_hit_quality: float
    extracted_fact_correctness: float
    final_answer_correctness: float
    citation_accuracy: float = 0.0
    stale_context_detection: float = 0.0
    naive_answer_correctness: float = 0.0
    context_answer_lift: float = 0.0
    passed: bool
    detail: str = ""


class EvalBlockerRead(BaseModel):
    case_id: str
    domain: str
    question: str
    detail: str


class EvalSummaryRead(BaseModel):
    run_id: UUID | None = None
    workspace_id: UUID
    latest_run_timestamp: datetime | None = None
    total: int = 0
    passed_count: int = 0
    failed_count: int = 0
    pass_rate: float = 0.0
    pass_threshold: float = 0.5
    average_retrieval_hit_quality: float = 0.0
    average_extracted_fact_correctness: float = 0.0
    average_final_answer_correctness: float = 0.0
    average_citation_accuracy: float = 0.0
    average_stale_context_detection: float = 0.0
    average_naive_answer_correctness: float = 0.0
    average_context_answer_lift: float = 0.0
    confidence_calibration_error: float = 0.0
    all_passed: bool = False
    domain_summaries: list[EvalDomainSummaryRead] = []
    blockers: list[EvalBlockerRead] = []


class EvalCasesRead(EvalSummaryRead):
    selected_domain: str | None = None
    cases: list[EvalCaseRead] = []


class EvalRunRequest(BaseModel):
    workspace_id: UUID
    domains: list[str] = Field(default_factory=list)
    case_ids: list[str] = Field(default_factory=list)
    pass_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
