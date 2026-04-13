from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FreshnessStatus(str, enum.Enum):
    CURRENT = "current"
    POSSIBLY_STALE = "possibly_stale"
    STALE = "stale"


class QueryFilters(BaseModel):
    model_names: list[str] | None = None
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    max_age_days: int | None = Field(default=None, ge=0)
    as_of: datetime | None = None


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    workspace_id: UUID
    model_names: list[str] | None = None
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    max_age_days: int | None = Field(default=None, ge=0)
    as_of: datetime | None = None

    def to_filters(self) -> QueryFilters:
        return QueryFilters(
            model_names=self.model_names,
            min_confidence=self.min_confidence,
            max_age_days=self.max_age_days,
            as_of=self.as_of,
        )


class QuerySourceRead(BaseModel):
    type: str
    author: str | None = None
    date: str | None = None
    url: str | None = None
    source_document_id: UUID | None = None


class QuerySourceDocumentRead(BaseModel):
    id: UUID
    label: str
    connector_type: str


class QueryComponentRead(BaseModel):
    id: UUID
    model: str
    name: str
    value: str
    confidence: float
    authority_source: str | None = None
    authority_weight: float = 0.5
    last_verified_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    superseded_by: UUID | None = None
    review_status: str | None = None
    review_summary: str | None = None
    review_item_id: UUID | None = None
    temporal_state: str | None = None
    source_documents: list[QuerySourceDocumentRead] = []


class QueryResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    freshness: FreshnessStatus
    components: list[QueryComponentRead]
    sources: list[QuerySourceRead]
    answered_at: str = Field(serialization_alias="answeredAt")
