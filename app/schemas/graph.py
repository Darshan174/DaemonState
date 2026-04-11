from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.knowledge import RelationshipSentiment, RelationshipType


class GraphNodeRead(BaseModel):
    """Stable DTO for a node (component) in the knowledge graph."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    value: str
    confidence: float
    authority_weight: float
    authority_source: str | None
    model_id: UUID
    model_name: str | None = None
    review_status: str | None = None
    temporal_state: str | None = None
    is_stale: bool
    valid_from: datetime
    valid_to: datetime | None = None
    source_count: int = 0
    created_at: datetime
    updated_at: datetime


class GraphEdgeRead(BaseModel):
    """Stable DTO for an edge (relationship) in the knowledge graph."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID
    target_id: UUID
    relationship_type: RelationshipType
    sentiment: RelationshipSentiment
    description: str | None = None
    confidence: float
    temporal_state: str | None = None
    valid_from: datetime
    valid_to: datetime | None = None
    created_at: datetime


class GraphNeighborhoodResponse(BaseModel):
    """Local-neighborhood subgraph rooted at a specific node."""

    root_id: UUID
    depth: int
    include_historical: bool
    nodes: list[GraphNodeRead]
    edges: list[GraphEdgeRead]
