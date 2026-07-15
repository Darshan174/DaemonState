from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db_session
from app.api.dependencies import get_access_scope
from app.services.access import AccessScope, source_access_predicate
from app.models import Component, SourceDocument
from app.services.ingest import IngestionService
from app.services.source_revisions import ingest_source_document_revision
from app.services.workspace_scope import (
    source_matches_workspace,
    workspace_connector_types,
    workspace_ids_equal,
)

router = APIRouter()


class SourceCreate(BaseModel):
    workspace_id: UUID | None = None
    source_type: str = Field(min_length=1, max_length=50)
    external_id: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    author: str | None = None
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceBulkCreate(BaseModel):
    documents: list[SourceCreate]


class SourceRead(BaseModel):
    id: UUID
    workspace_id: UUID | None = None
    source_type: str
    external_id: str
    author: str | None
    source_url: str | None
    source_identity_sha256: str
    revision_number: int
    supersedes_source_document_id: UUID | None
    ingested_at: datetime
    processed_at: datetime | None

    model_config = {"from_attributes": True}


class SourceComponentRead(BaseModel):
    id: UUID
    entity_id: UUID | None = None
    identity_key: str | None = None
    name: str
    value: str
    fact_type: str
    confidence: float
    authority_weight: float
    status: str
    temporal: str
    model_id: UUID
    model_name: str | None = None
    created_at: datetime | None = None


class SourceDetailRead(SourceRead):
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    components: list[SourceComponentRead] = Field(default_factory=list)


async def _run_ingestion(doc_id: UUID, database_url: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        svc = IngestionService(session)
        await svc.process_document(doc_id)
        await session.commit()
    await engine.dispose()


@router.post("/sources", response_model=SourceRead, status_code=201)
async def create_source(
    payload: SourceCreate,
    background_tasks: BackgroundTasks,
    sync: bool = False,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> SourceDocument:
    metadata = dict(payload.metadata)
    workspace_id = payload.workspace_id or _metadata_workspace_uuid(metadata)
    if not access_scope.allows_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    if workspace_id:
        metadata.setdefault("workspace_id", str(workspace_id))
    result = await ingest_source_document_revision(
        session,
        workspace_id=workspace_id,
        source_type=payload.source_type,
        external_id=payload.external_id,
        content=payload.content,
        author=payload.author,
        source_url=payload.url,
        metadata_json=metadata,
    )
    doc = result.document

    if sync and result.created:
        svc = IngestionService(session)
        await svc.process_document(doc.id)
        await session.commit()
    else:
        await session.commit()
        from app.config import settings
        if result.created:
            background_tasks.add_task(_run_ingestion, doc.id, settings.database_url)

    return doc


@router.post("/sources/bulk", status_code=201)
async def create_sources_bulk(
    payload: SourceBulkCreate,
    background_tasks: BackgroundTasks,
    sync: bool = False,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    doc_ids = []
    created_ids = []
    for item in payload.documents:
        metadata = dict(item.metadata)
        workspace_id = item.workspace_id or _metadata_workspace_uuid(metadata)
        if not access_scope.allows_workspace(workspace_id):
            raise HTTPException(status_code=404, detail="Workspace not found")
        if workspace_id:
            metadata.setdefault("workspace_id", str(workspace_id))
        result = await ingest_source_document_revision(
            session,
            workspace_id=workspace_id,
            source_type=item.source_type,
            external_id=item.external_id,
            content=item.content,
            author=item.author,
            source_url=item.url,
            metadata_json=metadata,
        )
        doc_ids.append(result.document.id)
        if result.created:
            created_ids.append(result.document.id)

    if sync:
        svc = IngestionService(session)
        for doc_id in created_ids:
            await svc.process_document(doc_id)
        await session.commit()
    else:
        await session.commit()
        from app.config import settings
        for doc_id in created_ids:
            background_tasks.add_task(_run_ingestion, doc_id, settings.database_url)

    return {
        "created": len(created_ids),
        "unchanged": len(doc_ids) - len(created_ids),
        "document_ids": [str(d) for d in doc_ids],
    }


@router.post("/sources/upload", response_model=SourceRead, status_code=201)
async def upload_source(
    background_tasks: BackgroundTasks,
    workspace_id: UUID | None = None,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> SourceRead:
    if not access_scope.allows_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    content = (await file.read()).decode("utf-8", errors="replace")
    metadata = {"filename": file.filename}
    if workspace_id:
        metadata["workspace_id"] = str(workspace_id)
    result = await ingest_source_document_revision(
        session,
        workspace_id=workspace_id,
        source_type="local",
        external_id=file.filename or "upload",
        content=content,
        metadata_json=metadata,
    )
    doc = result.document
    await session.commit()

    from app.config import settings
    if result.created:
        background_tasks.add_task(_run_ingestion, doc.id, settings.database_url)
    return SourceRead(
        id=doc.id,
        workspace_id=doc.workspace_id,
        source_type=doc.source_type,
        external_id=doc.external_id,
        author=doc.author,
        source_url=doc.source_url,
        source_identity_sha256=doc.source_identity_sha256,
        revision_number=doc.revision_number,
        supersedes_source_document_id=doc.supersedes_source_document_id,
        ingested_at=doc.ingested_at,
        processed_at=doc.processed_at,
    )


@router.get("/sources", response_model=list[SourceRead])
async def list_sources(
    workspace_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> list[SourceDocument]:
    workspace_uuid: UUID | None = None
    if workspace_id:
        workspace_id_str, _ = await _source_workspace_scope(session, workspace_id)
        workspace_uuid = UUID(workspace_id_str)
    stmt = (
        select(SourceDocument)
        .where(source_access_predicate(access_scope, workspace_id=workspace_uuid))
        .order_by(SourceDocument.ingested_at.desc())
        .limit(100)
    )
    result = await session.scalars(stmt)
    return list(result)


@router.get("/sources/{source_id}", response_model=SourceDetailRead)
async def get_source(
    source_id: UUID,
    workspace_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    workspace_uuid = UUID(workspace_id) if workspace_id else None
    doc = await session.scalar(
        select(SourceDocument)
        .where(SourceDocument.id == source_id)
        .where(source_access_predicate(access_scope, workspace_id=workspace_uuid))
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Source not found")
    workspace_id_str = None
    connector_types: set[str] = set()
    if workspace_id:
        workspace_id_str, connector_types = await _source_workspace_scope(session, workspace_id)
        if not source_matches_workspace(doc, workspace_id_str, connector_types):
            raise HTTPException(status_code=404, detail="Source not found")

    try:
        metadata = json.loads(doc.metadata_json or "{}") if isinstance(doc.metadata_json, str) else (doc.metadata_json or {})
    except (json.JSONDecodeError, TypeError):
        metadata = {}

    components = list(await session.scalars(
        select(Component)
        .options(selectinload(Component.model))
        .where(Component.source_document_id == source_id)
        .order_by(Component.created_at.desc())
    ))
    if workspace_id_str:
        components = [
            component for component in components
            if not component.workspace_id
            or workspace_ids_equal(component.workspace_id, workspace_id_str)
        ]

    return {
        "id": doc.id,
        "workspace_id": doc.workspace_id,
        "source_type": doc.source_type,
        "external_id": doc.external_id,
        "author": doc.author,
        "source_url": doc.source_url,
        "source_identity_sha256": doc.source_identity_sha256,
        "revision_number": doc.revision_number,
        "supersedes_source_document_id": doc.supersedes_source_document_id,
        "ingested_at": doc.ingested_at,
        "processed_at": doc.processed_at,
        "content": doc.content,
        "metadata": metadata,
        "components": [
            {
                "id": c.id,
                "entity_id": c.entity_id,
                "identity_key": c.identity_key,
                "name": c.name,
                "value": c.value,
                "fact_type": c.fact_type,
                "confidence": c.confidence,
                "authority_weight": c.authority_weight,
                "status": c.status,
                "temporal": c.temporal,
                "model_id": c.model_id,
                "model_name": c.model.name if c.model else None,
                "created_at": c.created_at,
            }
            for c in components
        ],
    }


def _metadata_workspace_uuid(metadata: dict[str, Any]) -> UUID | None:
    value = metadata.get("workspace_id")
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        return None


async def _source_workspace_scope(
    session: AsyncSession,
    workspace_id: str,
) -> tuple[str, set[str]]:
    try:
        return await workspace_connector_types(session, workspace_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid workspace_id")
