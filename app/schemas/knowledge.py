from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.knowledge import (
    KnowledgeModelStatus,
    RelationshipSentiment,
    RelationshipType,
)
from app.schemas.review import ReviewDecisionRead


class KnowledgeModelCreate(BaseModel):
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: KnowledgeModelStatus = KnowledgeModelStatus.ACTIVE
    auto_generated: bool = False


class ComponentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    value: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    authority_source: str | None = Field(default=None, max_length=255)
    authority_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    last_verified_at: datetime | None = None
    is_stale: bool = False


class ComponentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    value: str | None = Field(default=None, min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    authority_source: str | None = Field(default=None, max_length=255)
    authority_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    last_verified_at: datetime | None = None
    is_stale: bool | None = None


class RelationshipCreate(BaseModel):
    source_component_id: UUID
    target_component_id: UUID
    relationship_type: RelationshipType
    sentiment: RelationshipSentiment = RelationshipSentiment.NEUTRAL
    description: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class ComponentSourceDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    label: str
    connector_type: str


class ComponentSourceRead(BaseModel):
    """One source document that contributed to a component."""

    source_document_id: UUID
    connector_type: str
    external_id: str
    label: str
    source_url: str | None
    author: str | None
    ingested_at: datetime
    extraction_context: str | None
    extractor_name: str | None = None
    extractor_kind: str | None = None
    extractor_schema_version: str | None = None


class ComponentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    model_id: UUID
    model_name: str | None = None
    name: str
    value: str
    confidence: float
    authority_source: str | None
    authority_weight: float
    valid_from: datetime
    valid_to: datetime | None
    superseded_by: UUID | None = None
    last_verified_at: datetime
    is_stale: bool
    review_status: str | None = None
    review_summary: str | None = None
    review_item_id: UUID | None = None
    decision_history: list[ReviewDecisionRead] = []
    temporal_state: str | None = None
    source_documents: list[ComponentSourceDocumentRead] = []
    created_at: datetime
    updated_at: datetime

    # ── Graph / provenance fields ─────────────────────────────────
    source_count: int = 0
    is_rejected: bool = False
    is_superseded: bool = False
    is_hidden: bool = False


class KnowledgeModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    description: str | None
    status: KnowledgeModelStatus
    auto_generated: bool
    created_at: datetime
    updated_at: datetime


class KnowledgeModelDetail(KnowledgeModelRead):
    components: list[ComponentRead]


class RelationshipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_component_id: UUID
    source_component_name: str | None = None
    target_component_id: UUID
    target_component_name: str | None = None
    relationship_type: RelationshipType
    sentiment: RelationshipSentiment
    description: str | None
    confidence: float
    valid_from: datetime
    valid_to: datetime | None = None
    superseded_by: UUID | None = None
    temporal_state: str | None = None
    created_at: datetime

    # ── Trust / provenance fields ─────────────────────────────────
    source_review_status: str | None = None
    target_review_status: str | None = None
    is_hidden: bool = False


# ── Graph response schemas ────────────────────────────────────────


class GraphComponentRead(BaseModel):
    """Component enriched with graph navigation metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    model_id: UUID
    model_name: str | None = None
    name: str
    value: str
    confidence: float
    authority_source: str | None
    authority_weight: float
    valid_from: datetime
    valid_to: datetime | None = None
    superseded_by: UUID | None = None
    last_verified_at: datetime
    is_stale: bool
    review_status: str | None = None
    review_summary: str | None = None
    temporal_state: str | None = None
    source_count: int = 0
    is_rejected: bool = False
    is_superseded: bool = False
    is_hidden: bool = False
    # Navigation: component IDs that this one supersedes (predecessors)
    predecessor_ids: list[UUID] = []
    # Navigation: relationship IDs where this component participates
    relationship_ids: list[UUID] = []


class GraphRelationshipRead(BaseModel):
    """Relationship enriched with trust/provenance of both endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_component_id: UUID
    source_component_name: str | None = None
    target_component_id: UUID
    target_component_name: str | None = None
    relationship_type: RelationshipType
    sentiment: RelationshipSentiment
    description: str | None
    confidence: float
    valid_from: datetime
    valid_to: datetime | None = None
    temporal_state: str | None = None
    source_review_status: str | None = None
    target_review_status: str | None = None
    is_hidden: bool = False


class GraphResponse(BaseModel):
    """Full local subgraph response with nodes and edges."""

    model_config = ConfigDict(from_attributes=True)

    root_component_id: UUID
    nodes: list[GraphComponentRead]
    edges: list[GraphRelationshipRead]
    include_historical: bool = False
    hidden_node_count: int = 0
