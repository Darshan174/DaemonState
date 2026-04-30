from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db_session
from app.models import Component, Model, Relationship

router = APIRouter()


class ModelRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    component_count: int = 0

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


class RelationshipRead(BaseModel):
    id: UUID
    source_component_id: UUID
    target_component_id: UUID
    relationship_type: str

    class Config:
        from_attributes = True


class GraphResponse(BaseModel):
    models: list[ModelRead]
    components: list[ComponentRead]
    relationships: list[RelationshipRead]


@router.get("/graph", response_model=GraphResponse)
async def get_graph(
    model_id: UUID | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> GraphResponse:
    model_stmt = select(Model).order_by(Model.name)
    if model_id:
        model_stmt = model_stmt.where(Model.id == model_id)
    models = list(await session.scalars(model_stmt))

    comp_stmt = (
        select(Component)
        .options(selectinload(Component.model))
        .where(Component.status.in_(["active", "needs_review"]))
        .order_by(Component.created_at.desc())
    )
    if model_id:
        comp_stmt = comp_stmt.where(Component.model_id == model_id)
    components = list(await session.scalars(comp_stmt))

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
        ) for c in components],
        relationships=[RelationshipRead(
            id=r.id, source_component_id=r.source_component_id,
            target_component_id=r.target_component_id,
            relationship_type=r.relationship_type,
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
