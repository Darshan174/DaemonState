from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db_session
from app.models import Component, Model, Relationship, SourceDocument

router = APIRouter()


class ModelRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    component_count: int = 0

    model_config = {"from_attributes": True}


class ComponentRead(BaseModel):
    id: UUID
    model_id: UUID
    model_name: str | None = None
    name: str
    value: str
    fact_type: str
    confidence: float
    authority_weight: float
    status: str
    source_document_id: UUID | None = None
    source_type: str | None = None
    source_url: str | None = None
    ingested_at: datetime | None = None

    model_config = {"from_attributes": True}


class RelationshipRead(BaseModel):
    id: UUID
    source_component_id: UUID
    target_component_id: UUID
    relationship_type: str
    confidence: float = 0.7
    evidence: str | None = None

    model_config = {"from_attributes": True}


class GraphResponse(BaseModel):
    models: list[ModelRead]
    components: list[ComponentRead]
    relationships: list[RelationshipRead]


@router.get("/graph", response_model=GraphResponse)
async def get_graph(
    model_id: UUID | None = None,
    source_type: str | None = None,
    workspace_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> GraphResponse:
    model_stmt = select(Model).order_by(Model.name)
    if model_id:
        model_stmt = model_stmt.where(Model.id == model_id)
    models = list(await session.scalars(model_stmt))

    comp_stmt = (
        select(Component)
        .options(selectinload(Component.model), selectinload(Component.source_document))
        .where(Component.status.in_(["active", "needs_review", "proposed"]))
        .order_by(Component.created_at.desc())
    )
    if model_id:
        comp_stmt = comp_stmt.where(Component.model_id == model_id)
    components = list(await session.scalars(comp_stmt))

    if source_type:
        components = [
            c for c in components
            if c.source_document and c.source_document.source_type == source_type
        ]
    if workspace_id:
        comps_to_keep = []
        for c in components:
            if c.source_document:
                md = c.source_document.metadata_json
                if isinstance(md, dict) and md.get("workspace_id") == workspace_id:
                    comps_to_keep.append(c)
                elif isinstance(md, str):
                    try:
                        parsed = json.loads(md)
                        if parsed.get("workspace_id") == workspace_id:
                            comps_to_keep.append(c)
                    except (json.JSONDecodeError, TypeError):
                        pass
        components = comps_to_keep

    comp_ids = {c.id for c in components}
    rel_stmt = select(Relationship).where(
        Relationship.source_component_id.in_(comp_ids),
        Relationship.target_component_id.in_(comp_ids),
    )
    relationships = list(await session.scalars(rel_stmt))

    model_counts: dict[UUID, int] = {}
    for c in components:
        model_counts[c.model_id] = model_counts.get(c.model_id, 0) + 1

    return GraphResponse(
        models=[ModelRead(
            id=m.id, name=m.name, description=m.description,
            component_count=model_counts.get(m.id, 0),
        ) for m in models],
        components=[ComponentRead(
            id=c.id, model_id=c.model_id,
            model_name=c.model.name if c.model else None,
            name=c.name, value=c.value, fact_type=c.fact_type,
            confidence=c.confidence, authority_weight=c.authority_weight,
            status=c.status, source_document_id=c.source_document_id,
            source_type=c.source_document.source_type if c.source_document else None,
            source_url=c.source_document.source_url if c.source_document else None,
            ingested_at=c.source_document.ingested_at if c.source_document else None,
        ) for c in components],
        relationships=[RelationshipRead(
            id=r.id, source_component_id=r.source_component_id,
            target_component_id=r.target_component_id,
            relationship_type=r.relationship_type,
            confidence=r.confidence,
            evidence=r.evidence,
        ) for r in relationships],
    )


@router.patch("/components/{component_id}")
async def update_component_status(
    component_id: UUID,
    status: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    component = await session.get(Component, component_id)
    if component is None:
        raise HTTPException(status_code=404, detail="Component not found")
    component.status = status
    await session.flush()
    await session.commit()
    return {"id": str(component.id), "status": component.status}


class StatsResponse(BaseModel):
    models: int
    components: int
    relationships: int
    sources: int
    pending_review: int
    stale: int


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    workspace_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> StatsResponse:
    from sqlalchemy import func
    models = await session.scalar(select(func.count(Model.id)))
    components = await session.scalar(select(func.count(Component.id)))
    relationships = await session.scalar(select(func.count(Relationship.id)))
    sources = await session.scalar(select(func.count(SourceDocument.id)))
    pending = await session.scalar(
        select(func.count(Component.id)).where(Component.status == "needs_review")
    )
    stale = await session.scalar(
        select(func.count(Component.id)).where(Component.status == "stale")
    )
    return StatsResponse(
        models=models or 0,
        components=components or 0,
        relationships=relationships or 0,
        sources=sources or 0,
        pending_review=pending or 0,
        stale=stale or 0,
    )


class TimelineEvent(BaseModel):
    id: str
    type: str
    title: str
    timestamp: datetime
    detail: str | None = None


class TimelineResponse(BaseModel):
    events: list[TimelineEvent]


@router.get("/timeline", response_model=TimelineResponse)
async def get_timeline(
    limit: int = 50,
    workspace_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> TimelineResponse:
    events: list[TimelineEvent] = []

    sources_result = await session.scalars(
        select(SourceDocument)
        .order_by(SourceDocument.ingested_at.desc())
        .limit(limit)
    )
    for doc in sources_result:
        events.append(TimelineEvent(
            id=str(doc.id),
            type="source_ingest",
            title=f"Source ingested: {doc.external_id}",
            timestamp=doc.ingested_at,
            detail=f"Type: {doc.source_type}",
        ))

    components_result = await session.scalars(
        select(Component)
        .options(selectinload(Component.model))
        .order_by(Component.created_at.desc())
        .limit(limit)
    )
    for comp in components_result:
        events.append(TimelineEvent(
            id=str(comp.id),
            type="component_created",
            title=f"Component: {comp.name}",
            timestamp=comp.created_at,
            detail=f"Model: {comp.model.name if comp.model else 'unknown'} | Status: {comp.status}",
        ))

    events.sort(key=lambda e: e.timestamp, reverse=True)
    return TimelineResponse(events=events[:limit])
