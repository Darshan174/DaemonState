from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db_session
from app.models import Component, Model, Relationship, SourceDocument

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────

class ModelListItem(BaseModel):
    id: UUID
    name: str
    description: str | None
    component_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ComponentItem(BaseModel):
    id: UUID
    name: str
    value: str
    fact_type: str
    confidence: float
    authority_weight: float
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ModelDetail(BaseModel):
    id: UUID
    name: str
    description: str | None
    created_at: datetime
    lastUpdated: str
    components: list[ComponentItem]

    model_config = {"from_attributes": True}


class RelationshipItem(BaseModel):
    id: UUID
    source_component_id: UUID
    target_component_id: UUID
    relationship_type: str

    model_config = {"from_attributes": True}


class SourceDocumentItem(BaseModel):
    id: UUID
    source_type: str
    external_id: str
    author: str | None
    source_url: str | None
    ingested_at: datetime
    processed_at: datetime | None
    content_preview: str

    model_config = {"from_attributes": True}


class SourceDocumentPage(BaseModel):
    items: list[SourceDocumentItem]
    total: int
    has_more: bool
    next_cursor: str | None


# ── Models ─────────────────────────────────────────────────────────────────────

@router.get("/models", response_model=list[ModelListItem])
async def list_models(
    workspace_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    models = list(await session.scalars(select(Model).order_by(Model.name)))

    counts_result = await session.execute(
        select(Component.model_id, func.count(Component.id).label("cnt"))
        .group_by(Component.model_id)
    )
    counts: dict[UUID, int] = {row.model_id: row.cnt for row in counts_result}

    return [
        {
            "id": m.id,
            "name": m.name,
            "description": m.description,
            "component_count": counts.get(m.id, 0),
            "created_at": m.created_at,
        }
        for m in models
    ]


@router.get("/models/{model_id}", response_model=ModelDetail)
async def get_model(
    model_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    model = await session.scalar(
        select(Model)
        .options(selectinload(Model.components))
        .where(Model.id == model_id)
    )
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    last = max((c.created_at for c in model.components), default=model.created_at)
    return {
        "id": model.id,
        "name": model.name,
        "description": model.description,
        "created_at": model.created_at,
        "lastUpdated": last.isoformat(),
        "components": [
            {
                "id": c.id,
                "name": c.name,
                "value": c.value,
                "fact_type": c.fact_type,
                "confidence": c.confidence,
                "authority_weight": c.authority_weight,
                "status": c.status,
                "created_at": c.created_at,
            }
            for c in model.components
            if c.status in ("active", "needs_review")
        ],
    }


@router.get("/models/{model_id}/relationships", response_model=list[RelationshipItem])
async def get_model_relationships(
    model_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> list[Relationship]:
    model = await session.get(Model, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    comp_ids_result = await session.scalars(
        select(Component.id).where(Component.model_id == model_id)
    )
    comp_ids = list(comp_ids_result)

    rels = list(await session.scalars(
        select(Relationship).where(
            Relationship.source_component_id.in_(comp_ids),
            Relationship.target_component_id.in_(comp_ids),
        )
    ))
    return rels


# ── Source Documents ───────────────────────────────────────────────────────────

@router.get("/source-documents", response_model=SourceDocumentPage)
async def list_source_documents(
    workspace_id: str | None = None,
    connector_type: str | None = None,
    processed: bool | None = None,
    cursor: str | None = None,
    limit: int = 25,
    session: AsyncSession = Depends(get_db_session),
) -> SourceDocumentPage:
    stmt = select(SourceDocument).order_by(SourceDocument.ingested_at.desc())

    if connector_type and connector_type != "all":
        stmt = stmt.where(SourceDocument.source_type == connector_type)

    if processed is True:
        stmt = stmt.where(SourceDocument.processed_at.is_not(None))
    elif processed is False:
        stmt = stmt.where(SourceDocument.processed_at.is_(None))

    if cursor:
        stmt = stmt.where(SourceDocument.id < UUID(cursor))

    total_stmt = select(func.count(SourceDocument.id))
    if connector_type and connector_type != "all":
        total_stmt = total_stmt.where(SourceDocument.source_type == connector_type)
    if processed is True:
        total_stmt = total_stmt.where(SourceDocument.processed_at.is_not(None))
    elif processed is False:
        total_stmt = total_stmt.where(SourceDocument.processed_at.is_(None))

    total = await session.scalar(total_stmt) or 0

    stmt = stmt.limit(limit + 1)
    docs = list(await session.scalars(stmt))
    has_more = len(docs) > limit
    docs = docs[:limit]

    items = [
        SourceDocumentItem(
            id=d.id,
            source_type=d.source_type,
            external_id=d.external_id,
            author=d.author,
            source_url=d.source_url,
            ingested_at=d.ingested_at,
            processed_at=d.processed_at,
            content_preview=d.content[:200] if d.content else "",
        )
        for d in docs
    ]

    next_cursor = str(docs[-1].id) if has_more and docs else None
    return SourceDocumentPage(
        items=items,
        total=total,
        has_more=has_more,
        next_cursor=next_cursor,
    )
