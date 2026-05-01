from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models import SourceDocument
from app.services.ingest import IngestionService

router = APIRouter()


class SourceCreate(BaseModel):
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
    source_type: str
    external_id: str
    author: str | None
    source_url: str | None
    ingested_at: datetime
    processed_at: datetime | None

    model_config = {"from_attributes": True}


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
) -> SourceDocument:
    doc = SourceDocument(
        source_type=payload.source_type,
        external_id=payload.external_id,
        content=payload.content,
        author=payload.author,
        source_url=payload.url,
        metadata_json=json.dumps(payload.metadata),
    )
    session.add(doc)
    await session.flush()

    if sync:
        svc = IngestionService(session)
        await svc.process_document(doc.id)
        await session.commit()
    else:
        await session.commit()
        from app.config import settings
        background_tasks.add_task(_run_ingestion, doc.id, settings.database_url)

    return doc


@router.post("/sources/bulk", status_code=201)
async def create_sources_bulk(
    payload: SourceBulkCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    doc_ids = []
    for item in payload.documents:
        doc = SourceDocument(
            source_type=item.source_type,
            external_id=item.external_id,
            content=item.content,
            author=item.author,
            source_url=item.url,
            metadata_json=json.dumps(item.metadata),
        )
        session.add(doc)
        await session.flush()
        doc_ids.append(doc.id)

    await session.commit()
    from app.config import settings
    for doc_id in doc_ids:
        background_tasks.add_task(_run_ingestion, doc_id, settings.database_url)

    return {"created": len(doc_ids), "document_ids": [str(d) for d in doc_ids]}


@router.post("/sources/upload", response_model=SourceRead, status_code=201)
async def upload_source(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
) -> SourceRead:
    content = (await file.read()).decode("utf-8", errors="replace")
    doc = SourceDocument(
        source_type="local",
        external_id=file.filename or "upload",
        content=content,
        metadata_json=json.dumps({"filename": file.filename}),
    )
    session.add(doc)
    await session.flush()
    await session.commit()

    from app.config import settings
    background_tasks.add_task(_run_ingestion, doc.id, settings.database_url)
    return SourceRead(
        id=doc.id,
        source_type=doc.source_type,
        external_id=doc.external_id,
        author=doc.author,
        source_url=doc.source_url,
        ingested_at=doc.ingested_at,
        processed_at=doc.processed_at,
    )


@router.get("/sources", response_model=list[SourceRead])
async def list_sources(
    session: AsyncSession = Depends(get_db_session),
) -> list[SourceDocument]:
    result = await session.scalars(
        select(SourceDocument).order_by(SourceDocument.ingested_at.desc()).limit(100)
    )
    return list(result)
