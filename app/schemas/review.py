"""Schemas for trust/review/provenance endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


ReviewStatus = Literal["needs_review", "approved", "rejected", "superseded"]
ReviewSeverity = Literal["high", "medium", "low"]
ReviewKind = Literal[
    "review_item",
    "conflict",
    "low_confidence",
    "fact_update",
    "superseded_fact",
]


class ReviewItemSourceDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    label: str
    connector_type: str


class ReviewDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    previous_status: str | None
    new_status: str
    actor_type: str
    note: str | None
    created_at: datetime


class ReviewItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: ReviewStatus
    severity: ReviewSeverity
    kind: ReviewKind
    title: str
    summary: str
    confidence: float | None
    last_seen_at: datetime
    model_id: UUID | None
    model_name: str | None
    sources: list[str]
    source_documents: list[ReviewItemSourceDocumentRead]
    rationale: str | None
    suggested_action: str | None
    decision_history: list[ReviewDecisionRead] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_actionable(self) -> bool:
        """True when the item needs operator attention (still in needs_review)."""
        return self.status == "needs_review"


class ReviewItemPage(BaseModel):
    """Paginated response wrapper for review items."""
    model_config = ConfigDict(from_attributes=True)

    items: list[ReviewItemRead]
    total: int = Field(ge=0)
    limit: int | None = Field(default=None, ge=1)
    offset: int | None = Field(default=None, ge=0)
    has_more: bool

    @computed_field  # type: ignore[prop-decorator]
    @property
    def page_size(self) -> int:
        return len(self.items)


class ReviewStatusCounts(BaseModel):
    """Counts of review items by status."""
    model_config = ConfigDict(from_attributes=True)

    needs_review: int = 0
    approved: int = 0
    rejected: int = 0
    superseded: int = 0


class ReviewSeverityCounts(BaseModel):
    """Counts of review items by severity."""
    model_config = ConfigDict(from_attributes=True)

    high: int = 0
    medium: int = 0
    low: int = 0


class ReviewKindCounts(BaseModel):
    """Counts of review items by kind."""
    model_config = ConfigDict(from_attributes=True)

    review_item: int = 0
    conflict: int = 0
    low_confidence: int = 0
    fact_update: int = 0
    superseded_fact: int = 0


class ReviewSummaryRead(BaseModel):
    """Summary of review state for an operator dashboard."""
    model_config = ConfigDict(from_attributes=True)

    total: int = 0
    actionable: int = 0
    by_status: ReviewStatusCounts
    by_severity: ReviewSeverityCounts
    by_kind: ReviewKindCounts


class ComponentSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    connector_type: str
    external_id: str | None = None
    label: str
    author: str | None
    source_url: str | None
    created_at_source: datetime | None
    ingested_at: datetime
    processed_at: datetime | None
    extraction_context: str | None
    extractor_name: str | None = None
    extractor_kind: str | None = None
    extractor_schema_version: str | None = None


class SourceDocumentComponentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    model_id: UUID
    model_name: str
    name: str
    value: str
    confidence: float
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    superseded_by: UUID | None = None
    review_status: ReviewStatus | None
    review_item_id: UUID | None
    review_summary: str | None = None
    decision_history: list[ReviewDecisionRead] = []
    temporal_state: str | None
    is_stale: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def review_state(self) -> str:
        """Structured review state for consumer visibility.

        Returns one of:
        - 'needs_review': component is under review, not yet safe for production use
        - 'approved': component has been explicitly approved by an operator
        - 'rejected': component has been explicitly rejected
        - 'superseded': component has been replaced by a newer version
        - 'unreviewed': no review item exists for this component
        """
        if self.review_status is None:
            return "unreviewed"
        return self.review_status

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_safe_for_production(self) -> bool:
        """True when this component is approved and not stale/superseded."""
        return (
            self.review_status == "approved"
            and not self.is_stale
            and self.valid_to is None
        )
