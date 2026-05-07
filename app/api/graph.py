from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db_session
from app.models import Component, Model, Relationship, SourceDocument
from app.taxonomy import (
    relationship_display_label,
    source_type_display,
    canonical_source_type,
)

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
    display_title: str | None = None
    value: str
    fact_type: str
    temporal: str = "unknown"
    confidence: float
    authority_weight: float
    status: str
    source_document_id: UUID | None = None
    source_type: str | None = None
    source_url: str | None = None
    source_external_id: str | None = None
    source_metadata_summary: dict | None = None
    ingested_at: datetime | None = None
    provenance: str | None = None
    excerpt: str | None = None
    relationship_count: int = 0

    model_config = {"from_attributes": True}


class RelationshipRead(BaseModel):
    id: UUID
    source_component_id: UUID
    target_component_id: UUID
    relationship_type: str
    confidence: float = 0.7
    evidence: str | None = None
    status: str = "active"
    origin: str = "proposed"
    display_label: str | None = None
    source_component_name: str | None = None
    target_component_name: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class GraphResponse(BaseModel):
    models: list[ModelRead]
    components: list[ComponentRead]
    relationships: list[RelationshipRead]


class SourceKnowledgeDiff(BaseModel):
    source: dict
    components: list[ComponentRead]
    relationships: list[RelationshipRead]


@router.get("/graph", response_model=GraphResponse)
async def get_graph(
    model_id: UUID | None = None,
    source_type: str | None = None,
    confidence_min: float | None = None,
    temporal: str | None = None,
    status: str | None = None,
    relationship_origin: str | None = None,
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
    if temporal:
        comp_stmt = comp_stmt.where(Component.temporal == temporal)
    if status:
        comp_stmt = comp_stmt.where(Component.status == status)
    components = list(await session.scalars(comp_stmt))

    if source_type:
        requested_source_type = canonical_source_type(source_type)
        components = [
            c for c in components
            if c.source_document and canonical_source_type(c.source_document.source_type) == requested_source_type
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
    if confidence_min is not None:
        components = [c for c in components if c.confidence >= confidence_min]

    comp_ids = {c.id for c in components}
    rel_stmt = select(Relationship).where(
        Relationship.source_component_id.in_(comp_ids),
        Relationship.target_component_id.in_(comp_ids),
    )
    if relationship_origin:
        rel_stmt = rel_stmt.where(Relationship.origin == relationship_origin)

    relationships = list(await session.scalars(rel_stmt))

    model_counts: dict[UUID, int] = {}
    for c in components:
        model_counts[c.model_id] = model_counts.get(c.model_id, 0) + 1
    relationship_counts = _relationship_counts(relationships)

    return GraphResponse(
        models=[ModelRead(
            id=m.id, name=m.name, description=m.description,
            component_count=model_counts.get(m.id, 0),
        ) for m in models],
        components=[_component_read(c, relationship_counts.get(c.id, 0)) for c in components],
        relationships=[_relationship_read(r) for r in relationships],
    )


@router.get("/graph/source-diff/{source_id}", response_model=SourceKnowledgeDiff)
async def get_source_knowledge_diff(
    source_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> SourceKnowledgeDiff:
    doc = await session.get(SourceDocument, source_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Source document not found")

    md = doc.metadata_json
    if isinstance(md, str):
        try:
            md = json.loads(md)
        except (json.JSONDecodeError, TypeError):
            md = {}

    components = list(await session.scalars(
        select(Component)
        .options(selectinload(Component.model), selectinload(Component.source_document))
        .where(Component.source_document_id == source_id)
        .order_by(Component.created_at.desc())
    ))
    comp_ids = {c.id for c in components}
    relationships = list(await session.scalars(
        select(Relationship).where(
            Relationship.source_component_id.in_(comp_ids),
        )
    ))

    return SourceKnowledgeDiff(
        source={
            "id": str(doc.id),
            "source_type": doc.source_type,
            "external_id": doc.external_id,
            "author": doc.author,
            "source_url": doc.source_url,
            "ingested_at": doc.ingested_at.isoformat() if doc.ingested_at else None,
            "processed_at": doc.processed_at.isoformat() if doc.processed_at else None,
            "metadata": md,
        },
        components=[_component_read(c, _relationship_counts(relationships).get(c.id, 0)) for c in components],
        relationships=[_relationship_read(r) for r in relationships],
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
    proposed: int
    stale: int


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    workspace_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> StatsResponse:
    models = await session.scalar(select(func.count(Model.id)))
    components = await session.scalar(select(func.count(Component.id)))
    relationships = await session.scalar(select(func.count(Relationship.id)))
    sources = await session.scalar(select(func.count(SourceDocument.id)))
    pending = await session.scalar(
        select(func.count(Component.id)).where(Component.status == "needs_review")
    )
    proposed = await session.scalar(
        select(func.count(Component.id)).where(Component.status == "proposed")
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
        proposed=proposed or 0,
        stale=stale or 0,
    )


class BuildRequest(BaseModel):
    limit: int = 100
    api_key: str | None = None
    model: str | None = None


class BuildResult(BaseModel):
    started_at: str
    finished_at: str
    llm_extraction: bool
    docs_processed: int
    docs_pending_before: int
    components_created: int
    relationships_inferred: int
    errors: list[dict]
    stats: dict


@router.post("/graph/build", response_model=BuildResult)
async def build_graph(
    body: BuildRequest = BuildRequest(),
    session: AsyncSession = Depends(get_db_session),
) -> BuildResult:
    from app.agents.graph_builder import GraphBuilderAgent
    agent = GraphBuilderAgent(session)
    result = await agent.run(limit=body.limit, api_key=body.api_key, model=body.model)
    return BuildResult(**result)


@router.get("/graph/agent-status")
async def agent_status() -> dict:
    from app.config import settings
    return {
        "llm_enabled": bool(settings.litellm_api_key and settings.extraction_model),
        "extraction_model": settings.extraction_model or None,
    }


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
            detail=f"Type: {source_type_display(doc.source_type)}",
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


# ── Graph Slice ────────────────────────────────────────────────────────────────

class GraphSliceRequest(BaseModel):
    model_ids: list[UUID] | None = None
    source_types: list[str] | None = None
    statuses: list[str] | None = None
    fact_types: list[str] | None = None
    confidence_min: float | None = None
    temporal: str | None = None
    include_stale: bool = False
    include_proposed_edges: bool = True
    max_hops: int = 2


@router.post("/graph/slice", response_model=GraphResponse)
async def get_graph_slice(
    body: GraphSliceRequest,
    session: AsyncSession = Depends(get_db_session),
) -> GraphResponse:
    allowed_statuses = ["active", "needs_review"]
    if body.include_stale:
        allowed_statuses.append("stale")
    if body.include_proposed_edges:
        allowed_statuses.append("proposed")

    comp_stmt = (
        select(Component)
        .options(selectinload(Component.model), selectinload(Component.source_document))
        .where(Component.status.in_(allowed_statuses))
        .order_by(Component.created_at.desc())
    )
    if body.model_ids:
        comp_stmt = comp_stmt.where(Component.model_id.in_(body.model_ids))
    if body.source_types:
        comp_stmt = comp_stmt.join(SourceDocument).where(
            SourceDocument.source_type.in_(body.source_types)
        )
    if body.fact_types:
        comp_stmt = comp_stmt.where(Component.fact_type.in_(body.fact_types))
    if body.statuses:
        comp_stmt = comp_stmt.where(Component.status.in_(body.statuses))
    if body.confidence_min is not None:
        comp_stmt = comp_stmt.where(Component.confidence >= body.confidence_min)
    if body.temporal:
        comp_stmt = comp_stmt.where(Component.temporal == body.temporal)

    components = list(await session.scalars(comp_stmt))
    comp_ids = {c.id for c in components}

    rel_stmt = select(Relationship).where(
        Relationship.source_component_id.in_(comp_ids),
        Relationship.target_component_id.in_(comp_ids),
    )
    relationships = list(await session.scalars(rel_stmt))

    model_ids_in_result = {c.model_id for c in components}
    model_stmt = select(Model).where(Model.id.in_(model_ids_in_result)).order_by(Model.name)
    models = list(await session.scalars(model_stmt))

    model_counts: dict[UUID, int] = {}
    for c in components:
        model_counts[c.model_id] = model_counts.get(c.model_id, 0) + 1

    rel_counts: dict[UUID, int] = {}
    inbound_counts: dict[UUID, int] = {}
    outbound_counts: dict[UUID, int] = {}
    for r in relationships:
        rel_counts[r.source_component_id] = rel_counts.get(r.source_component_id, 0) + 1
        rel_counts[r.target_component_id] = rel_counts.get(r.target_component_id, 0) + 1
        outbound_counts[r.source_component_id] = outbound_counts.get(r.source_component_id, 0) + 1
        inbound_counts[r.target_component_id] = inbound_counts.get(r.target_component_id, 0) + 1

    def _resolve_origin(rel: Relationship) -> str:
        stored = getattr(rel, "origin", None) or "proposed"
        if stored in ("deterministic", "extracted", "ai_proposed", "human_verified", "proposed"):
            return stored
        if rel.status == "human_verified":
            return "human_verified"
        if stored == "proposed" and rel.confidence >= 0.85:
            return "extracted"
        return stored

    def _display_title(comp: Component) -> str:
        if comp.fact_type in ("decision", "outcome"):
            return f"Decision: {comp.name}"
        if comp.fact_type in ("blocker", "risk"):
            return f"Risk: {comp.name}"
        if comp.fact_type in ("action_item", "task"):
            return f"Task: {comp.name}"
        return comp.name

    def _metadata_summary(comp: Component) -> dict | None:
        if not comp.source_document:
            return None
        md = comp.source_document.metadata_json
        if isinstance(md, str):
            try:
                md = json.loads(md)
            except (json.JSONDecodeError, TypeError):
                return None
        if not isinstance(md, dict):
            return None
        summary = {}
        for key in ("title", "author", "source", "tool", "platform", "workspace_id", "item_type", "number", "state", "merged", "repo_full_name"):
            if key in md:
                summary[key] = md[key]
        return summary if summary else None

    return GraphResponse(
        models=[ModelRead(
            id=m.id, name=m.name, description=m.description,
            component_count=model_counts.get(m.id, 0),
        ) for m in models],
        components=[ComponentRead(
            id=c.id, model_id=c.model_id,
            model_name=c.model.name if c.model else None,
            name=c.name, value=c.value, fact_type=c.fact_type,
            temporal=c.temporal,
            confidence=c.confidence, authority_weight=c.authority_weight,
            status=c.status, source_document_id=c.source_document_id,
            source_type=c.source_document.source_type if c.source_document else None,
            source_url=c.source_document.source_url if c.source_document else None,
            source_external_id=c.source_document.external_id if c.source_document else None,
            source_metadata_summary=_metadata_summary(c),
            ingested_at=c.source_document.ingested_at if c.source_document else None,
            provenance=getattr(c, "provenance", None),
            excerpt=getattr(c, "excerpt", None),
        ) for c in components],
        relationships=[RelationshipRead(
            id=r.id, source_component_id=r.source_component_id,
            target_component_id=r.target_component_id,
            relationship_type=r.relationship_type,
            display_label=relationship_display_label(r.relationship_type, getattr(r, "origin", "proposed")),
            confidence=r.confidence,
            evidence=r.evidence,
            status=r.status,
            origin=_resolve_origin(r),
        ) for r in relationships],
    )


# ── Component Detail ───────────────────────────────────────────────────────────

class ComponentDetail(BaseModel):
    id: UUID
    model_id: UUID
    model_name: str | None = None
    name: str
    display_title: str | None = None
    value: str
    fact_type: str
    temporal: str
    confidence: float
    authority_weight: float
    status: str
    source_document_id: UUID | None = None
    source_type: str | None = None
    source_url: str | None = None
    source_external_id: str | None = None
    source_author: str | None = None
    ingested_at: datetime | None = None
    created_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    metadata_summary: dict | None = None
    relationship_count: int = 0
    inbound_count: int = 0
    outbound_count: int = 0
    inbound_relationships: list[RelationshipRead] = []
    outbound_relationships: list[RelationshipRead] = []
    superseded_by_id: UUID | None = None


@router.get("/components/{component_id}", response_model=ComponentDetail)
async def get_component_detail(
    component_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> ComponentDetail:
    component = await session.get(Component, component_id)
    if component is None:
        raise HTTPException(status_code=404, detail="Component not found")

    await session.refresh(component, ["model", "source_document"])

    inbound_stmt = (
        select(Relationship)
        .where(Relationship.target_component_id == component_id)
        .order_by(Relationship.created_at.desc())
    )
    outbound_stmt = (
        select(Relationship)
        .where(Relationship.source_component_id == component_id)
        .order_by(Relationship.created_at.desc())
    )
    inbound_rels = list(await session.scalars(inbound_stmt))
    outbound_rels = list(await session.scalars(outbound_stmt))

    def _resolve_origin(rel: Relationship) -> str:
        stored = getattr(rel, "origin", None) or "proposed"
        if stored in ("deterministic", "extracted", "ai_proposed", "human_verified", "proposed"):
            return stored
        if rel.status == "human_verified":
            return "human_verified"
        if stored == "proposed" and rel.confidence >= 0.85:
            return "extracted"
        return stored

    def _format_rel(rel: Relationship) -> RelationshipRead:
        origin = _resolve_origin(rel)
        return RelationshipRead(
            id=rel.id,
            source_component_id=rel.source_component_id,
            target_component_id=rel.target_component_id,
            relationship_type=rel.relationship_type,
            display_label=relationship_display_label(rel.relationship_type, origin),
            confidence=rel.confidence,
            evidence=rel.evidence,
            status=rel.status,
            origin=origin,
            created_at=rel.created_at,
        )

    def _display_title(comp: Component) -> str:
        if comp.fact_type in ("decision", "outcome"):
            return f"Decision: {comp.name}"
        if comp.fact_type in ("blocker", "risk"):
            return f"Risk: {comp.name}"
        if comp.fact_type in ("action_item", "task"):
            return f"Task: {comp.name}"
        return comp.name

    def _metadata_summary(comp: Component) -> dict | None:
        if not comp.source_document:
            return None
        md = comp.source_document.metadata_json
        if isinstance(md, str):
            try:
                md = json.loads(md)
            except (json.JSONDecodeError, TypeError):
                return None
        if not isinstance(md, dict):
            return None
        summary = {}
        for key in ("title", "author", "source", "tool", "platform", "workspace_id", "item_type", "number", "state", "merged", "repo_full_name"):
            if key in md:
                summary[key] = md[key]
        return summary if summary else None

    return ComponentDetail(
        id=component.id,
        model_id=component.model_id,
        model_name=component.model.name if component.model else None,
        name=component.name,
        display_title=_display_title(component),
        value=component.value,
        fact_type=component.fact_type,
        temporal=component.temporal,
        confidence=component.confidence,
        authority_weight=component.authority_weight,
        status=component.status,
        source_document_id=component.source_document_id,
        source_type=component.source_document.source_type if component.source_document else None,
        source_url=component.source_document.source_url if component.source_document else None,
        source_external_id=component.source_document.external_id if component.source_document else None,
        source_author=component.source_document.author if component.source_document else None,
        ingested_at=component.source_document.ingested_at if component.source_document else None,
        created_at=component.created_at,
        valid_from=component.valid_from,
        valid_to=component.valid_to,
        metadata_summary=_metadata_summary(component),
        relationship_count=len(inbound_rels) + len(outbound_rels),
        inbound_count=len(inbound_rels),
        outbound_count=len(outbound_rels),
        inbound_relationships=[_format_rel(r) for r in inbound_rels],
        outbound_relationships=[_format_rel(r) for r in outbound_rels],
        superseded_by_id=component.superseded_by_id,
    )


# ── Relationship Detail ────────────────────────────────────────────────────────

class RelationshipDetail(BaseModel):
    id: UUID
    source_component_id: UUID
    target_component_id: UUID
    source_component_name: str | None = None
    target_component_name: str | None = None
    source_model_name: str | None = None
    target_model_name: str | None = None
    relationship_type: str
    display_label: str | None = None
    confidence: float
    evidence: str | None = None
    status: str
    origin: str
    created_at: datetime | None = None


@router.get("/relationships/{relationship_id}", response_model=RelationshipDetail)
async def get_relationship_detail(
    relationship_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> RelationshipDetail:
    rel = await session.get(Relationship, relationship_id)
    if rel is None:
        raise HTTPException(status_code=404, detail="Relationship not found")

    source_comp = await session.get(Component, rel.source_component_id)
    target_comp = await session.get(Component, rel.target_component_id)

    source_model_name = None
    target_model_name = None
    if source_comp and source_comp.model_id:
        source_model = await session.get(Model, source_comp.model_id)
        source_model_name = source_model.name if source_model else None
    if target_comp and target_comp.model_id:
        target_model = await session.get(Model, target_comp.model_id)
        target_model_name = target_model.name if target_model else None

    def _resolve_origin(r: Relationship) -> str:
        stored = getattr(r, "origin", None) or "proposed"
        if stored in ("deterministic", "extracted", "ai_proposed", "human_verified", "proposed"):
            return stored
        if r.status == "human_verified":
            return "human_verified"
        if stored == "proposed" and r.confidence >= 0.85:
            return "extracted"
        return stored

    return RelationshipDetail(
        id=rel.id,
        source_component_id=rel.source_component_id,
        target_component_id=rel.target_component_id,
        source_component_name=source_comp.name if source_comp else None,
        target_component_name=target_comp.name if target_comp else None,
        source_model_name=source_model_name,
        target_model_name=target_model_name,
        relationship_type=rel.relationship_type,
        display_label=relationship_display_label(rel.relationship_type, _resolve_origin(rel)),
        confidence=rel.confidence,
        evidence=rel.evidence,
        status=rel.status,
        origin=_resolve_origin(rel),
        created_at=rel.created_at,
    )


# ── Source-to-Knowledge Diff ───────────────────────────────────────────────────

class DiffComponentItem(BaseModel):
    id: UUID
    name: str
    display_title: str | None = None
    value: str
    fact_type: str
    status: str
    confidence: float
    temporal: str
    is_new: bool = False
    is_updated: bool = False
    is_duplicate: bool = False
    evidence: str | None = None


class DiffRelationshipItem(BaseModel):
    id: UUID
    source_component_name: str
    target_component_name: str
    relationship_type: str
    display_label: str | None = None
    confidence: float
    evidence: str | None = None
    origin: str
    is_new: bool = False


class SourceDiffResponse(BaseModel):
    source_id: UUID
    source_type: str
    external_id: str
    source_url: str | None = None
    author: str | None = None
    ingested_at: datetime
    content_preview: str
    components_added: list[DiffComponentItem]
    components_updated: list[DiffComponentItem]
    relationships_added: list[DiffRelationshipItem]
    models_affected: list[str]
    proposed_edges: list[DiffRelationshipItem]
    deterministic_edges: list[DiffRelationshipItem]
    total_components: int
    total_relationships: int


@router.get("/source-documents/{source_id}/diff", response_model=SourceDiffResponse)
async def get_source_diff(
    source_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> SourceDiffResponse:
    doc = await session.get(SourceDocument, source_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Source document not found")

    comp_stmt = (
        select(Component)
        .options(selectinload(Component.model))
        .where(Component.source_document_id == source_id)
        .order_by(Component.created_at.desc())
    )
    components = list(await session.scalars(comp_stmt))
    comp_ids = {c.id for c in components}

    rel_stmt = select(Relationship).where(
        Relationship.source_component_id.in_(comp_ids)
        | Relationship.target_component_id.in_(comp_ids)
    )
    relationships = list(await session.scalars(rel_stmt))

    comp_name_map: dict[UUID, str] = {c.id: c.name for c in components}
    for r in relationships:
        if r.source_component_id not in comp_name_map:
            src = await session.get(Component, r.source_component_id)
            if src:
                comp_name_map[r.source_component_id] = src.name
        if r.target_component_id not in comp_name_map:
            tgt = await session.get(Component, r.target_component_id)
            if tgt:
                comp_name_map[r.target_component_id] = tgt.name

    def _resolve_origin(rel: Relationship) -> str:
        stored = getattr(rel, "origin", None) or "proposed"
        if stored in ("deterministic", "extracted", "ai_proposed", "human_verified", "proposed"):
            return stored
        if rel.status == "human_verified":
            return "human_verified"
        return stored

    def _display_title(comp: Component) -> str:
        if comp.fact_type in ("decision", "outcome"):
            return f"Decision: {comp.name}"
        if comp.fact_type in ("blocker", "risk"):
            return f"Risk: {comp.name}"
        if comp.fact_type in ("action_item", "task"):
            return f"Task: {comp.name}"
        return comp.name

    components_added = []
    components_updated = []
    for c in components:
        item = DiffComponentItem(
            id=c.id, name=c.name, display_title=_display_title(c),
            value=c.value, fact_type=c.fact_type, status=c.status,
            confidence=c.confidence, temporal=c.temporal,
            is_new=c.status == "proposed",
            is_updated=c.status == "needs_review",
            evidence=c.value[:200] if c.value else None,
        )
        if c.status == "proposed":
            components_added.append(item)
        elif c.status == "needs_review":
            components_updated.append(item)
        else:
            components_added.append(item)

    relationships_added = []
    proposed_edges = []
    deterministic_edges = []
    for r in relationships:
        origin = _resolve_origin(r)
        item = DiffRelationshipItem(
            id=r.id,
            source_component_name=comp_name_map.get(r.source_component_id, "unknown"),
            target_component_name=comp_name_map.get(r.target_component_id, "unknown"),
            relationship_type=r.relationship_type,
            display_label=r.relationship_type.replace("_", " ").title(),
            confidence=r.confidence,
            evidence=r.evidence,
            origin=origin,
            is_new=True,
        )
        relationships_added.append(item)
        if origin == "ai_proposed":
            proposed_edges.append(item)
        elif origin == "deterministic":
            deterministic_edges.append(item)

    models_affected = list({
        c.model.name for c in components if c.model and c.model.name
    })

    return SourceDiffResponse(
        source_id=doc.id,
        source_type=doc.source_type,
        external_id=doc.external_id,
        source_url=doc.source_url,
        author=doc.author,
        ingested_at=doc.ingested_at,
        content_preview=doc.content[:500] if doc.content else "",
        components_added=components_added,
        components_updated=components_updated,
        relationships_added=relationships_added,
        models_affected=models_affected,
        proposed_edges=proposed_edges,
        deterministic_edges=deterministic_edges,
        total_components=len(components),
        total_relationships=len(relationships),
    )


# ── Work Lens ──────────────────────────────────────────────────────────────────

class WorkLensItem(BaseModel):
    id: UUID
    name: str
    display_title: str | None = None
    model_name: str | None = None
    fact_type: str
    status: str
    temporal: str
    confidence: float
    source_type: str | None = None
    source_url: str | None = None
    relationship_count: int = 0
    lens_category: str

class WorkLensResponse(BaseModel):
    blockers: list[WorkLensItem]
    open_decisions: list[WorkLensItem]
    active_tasks: list[WorkLensItem]
    unresolved_questions: list[WorkLensItem]
    proposed_items: list[WorkLensItem]
    stale_items: list[WorkLensItem]


@router.get("/work-lens", response_model=WorkLensResponse)
async def get_work_lens(
    workspace_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> WorkLensResponse:
    comp_stmt = (
        select(Component)
        .options(selectinload(Component.model), selectinload(Component.source_document))
        .order_by(Component.created_at.desc())
    )
    components = list(await session.scalars(comp_stmt))

    if workspace_id:
        filtered = []
        for c in components:
            if c.source_document:
                md = c.source_document.metadata_json
                if isinstance(md, dict) and md.get("workspace_id") == workspace_id:
                    filtered.append(c)
                elif isinstance(md, str):
                    try:
                        parsed = json.loads(md)
                        if parsed.get("workspace_id") == workspace_id:
                            filtered.append(c)
                    except (json.JSONDecodeError, TypeError):
                        pass
        components = filtered

    comp_ids = {c.id for c in components}
    rel_stmt = select(Relationship).where(
        Relationship.source_component_id.in_(comp_ids),
        Relationship.target_component_id.in_(comp_ids),
    )
    relationships = list(await session.scalars(rel_stmt))

    rel_counts: dict[UUID, int] = {}
    for r in relationships:
        rel_counts[r.source_component_id] = rel_counts.get(r.source_component_id, 0) + 1
        rel_counts[r.target_component_id] = rel_counts.get(r.target_component_id, 0) + 1

    def _to_item(c: Component, lens_category: str) -> WorkLensItem:
        return WorkLensItem(
            id=c.id, name=c.name,
            display_title=c.name,
            model_name=c.model.name if c.model else None,
            fact_type=c.fact_type, status=c.status,
            temporal=c.temporal, confidence=c.confidence,
            source_type=c.source_document.source_type if c.source_document else None,
            source_url=c.source_document.source_url if c.source_document else None,
            relationship_count=rel_counts.get(c.id, 0),
            lens_category=lens_category,
        )

    blockers = [
        _to_item(c, "blocker") for c in components
        if c.status == "blocked"
        or c.fact_type in ("blocker", "risk")
        and c.status not in ("stale", "superseded")
    ]
    open_decisions = [
        _to_item(c, "open_decision") for c in components
        if c.fact_type in ("decision", "outcome")
        and c.status in ("active", "needs_review")
    ]
    active_tasks = [
        _to_item(c, "active_task") for c in components
        if c.fact_type in ("action_item", "task")
        and c.status in ("active", "needs_review")
        and c.temporal in ("current", "unknown")
    ]
    unresolved_questions = [
        _to_item(c, "unresolved") for c in components
        if c.fact_type in ("question", "discussion")
        and c.status in ("active", "needs_review", "proposed")
    ]
    proposed_items = [
        _to_item(c, "proposed") for c in components
        if c.status == "proposed"
    ]
    stale_items = [
        _to_item(c, "stale") for c in components
        if c.status == "stale"
    ]

    return WorkLensResponse(
        blockers=blockers,
        open_decisions=open_decisions,
        active_tasks=active_tasks,
        unresolved_questions=unresolved_questions,
        proposed_items=proposed_items,
        stale_items=stale_items,
    )


def _relationship_counts(relationships: list[Relationship]) -> dict[UUID, int]:
    counts: dict[UUID, int] = {}
    for rel in relationships:
        counts[rel.source_component_id] = counts.get(rel.source_component_id, 0) + 1
        counts[rel.target_component_id] = counts.get(rel.target_component_id, 0) + 1
    return counts


def _component_read(c: Component, relationship_count: int = 0) -> ComponentRead:
    source_meta = None
    if c.source_document and c.source_document.metadata_json:
        md = c.source_document.metadata_json
        if isinstance(md, str):
            try:
                md = json.loads(md)
            except (json.JSONDecodeError, TypeError):
                md = {}
        if isinstance(md, dict):
            summary_keys = ["session_id", "tool", "model", "branch", "commit", "author", "number", "state", "title", "item_type", "repo_full_name", "merged"]
            source_meta = {k: v for k, v in md.items() if k in summary_keys and v}
    return ComponentRead(
        id=c.id, model_id=c.model_id,
        model_name=c.model.name if c.model else None,
        name=c.name,
        display_title=c.name,
        value=c.value, fact_type=c.fact_type,
        temporal=c.temporal,
        confidence=c.confidence, authority_weight=c.authority_weight,
        status=c.status, source_document_id=c.source_document_id,
        source_type=c.source_document.source_type if c.source_document else None,
        source_url=c.source_document.source_url if c.source_document else None,
        source_external_id=c.source_document.external_id if c.source_document else None,
        source_metadata_summary=source_meta,
        ingested_at=c.source_document.ingested_at if c.source_document else None,
        provenance=getattr(c, "provenance", None),
        excerpt=getattr(c, "excerpt", None),
        relationship_count=relationship_count,
    )


def _relationship_read(r: Relationship) -> RelationshipRead:
    origin = getattr(r, "origin", "proposed") or "proposed"
    return RelationshipRead(
        id=r.id, source_component_id=r.source_component_id,
        target_component_id=r.target_component_id,
        relationship_type=r.relationship_type,
        confidence=r.confidence,
        evidence=r.evidence,
        status=r.status,
        origin=origin,
        display_label=relationship_display_label(r.relationship_type, origin),
        created_at=r.created_at,
    )


def _work_lens_item(c: Component, lens_category: str = "blocker") -> WorkLensItem:
    return WorkLensItem(
        id=c.id,
        name=c.name,
        display_title=c.name,
        fact_type=c.fact_type,
        model_name=c.model.name if c.model else None,
        status=c.status,
        temporal=c.temporal,
        confidence=c.confidence,
        source_type=c.source_document.source_type if c.source_document else None,
        source_url=c.source_document.source_url if c.source_document else None,
        relationship_count=0,
        lens_category=lens_category,
    )
