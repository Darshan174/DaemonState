from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class FounderBriefFactRead(BaseModel):
    component_id: UUID
    model_id: UUID
    model_name: str
    name: str
    value: str
    confidence: float
    authority_weight: float
    valid_from: datetime
    review_status: str | None = None
    review_item_id: UUID | None = None
    source_labels: list[str] = []
    source_document_ids: list[UUID] = []


class FounderBriefConflictRead(BaseModel):
    review_item_id: UUID
    component_id: UUID
    component_name: str
    status: str
    severity: str
    kind: str
    title: str
    summary: str
    suggested_action: str | None = None
    created_at: datetime
    updated_at: datetime


class FounderBriefRiskRead(BaseModel):
    component_id: UUID
    name: str
    value: str
    reason: str
    confidence: float
    review_status: str | None = None
    source_labels: list[str] = []
    source_document_ids: list[UUID] = []


class FounderBriefConnectorFailureRead(BaseModel):
    job_id: UUID
    connector_id: UUID
    connector_type: str
    job_type: str
    failed_at: datetime
    error_type: str | None = None
    error_message: str | None = None


class FounderBriefRead(BaseModel):
    workspace_id: UUID
    generated_at: datetime
    lookback_days: int
    changed_facts: list[FounderBriefFactRead] = []
    new_blockers: list[FounderBriefFactRead] = []
    open_conflicts: list[FounderBriefConflictRead] = []
    stale_high_risk_items: list[FounderBriefRiskRead] = []
    recent_connector_failures: list[FounderBriefConnectorFailureRead] = []


class LaunchGuardRequest(BaseModel):
    workspace_id: UUID
    draft: str = Field(min_length=1)


class LaunchGuardEvidenceRead(BaseModel):
    source_document_id: UUID
    label: str
    connector_type: str
    source_url: str | None = None


class LaunchGuardClaimRead(BaseModel):
    claim: str
    status: Literal["supported", "contradicted", "stale", "unclear"]
    reason: str
    matched_component_id: UUID | None = None
    matched_component_name: str | None = None
    matched_component_value: str | None = None
    matched_component_valid_from: datetime | None = None
    matched_component_valid_to: datetime | None = None
    evidence: list[LaunchGuardEvidenceRead] = []


class LaunchGuardRead(BaseModel):
    workspace_id: UUID
    checked_at: datetime
    supported_count: int
    contradicted_count: int
    stale_count: int
    unclear_count: int
    claims: list[LaunchGuardClaimRead] = []


class TimelineEventRead(BaseModel):
    event_id: str
    event_type: Literal[
        "decision_change",
        "review_transition",
        "source_ingest",
        "connector_failure",
    ]
    occurred_at: datetime
    title: str
    summary: str
    component_id: UUID | None = None
    review_item_id: UUID | None = None
    source_document_id: UUID | None = None
    connector_id: UUID | None = None
    connector_type: str | None = None
    source_label: str | None = None
    model_name: str | None = None
    status: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class TimelineRead(BaseModel):
    workspace_id: UUID
    generated_at: datetime
    total_events: int
    has_more: bool = False
    next_cursor: str | None = None
    items: list[TimelineEventRead] = Field(default_factory=list)
