"""Import API — trigger and monitor zero-auth file imports.

These endpoints let users point the system at files they have already
exported from their tools (Notion, Slack, etc.) and have them ingested
into the knowledge graph without needing OAuth or API tokens.
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models.source import SourceDocument
from app.schemas.imports import (
    ImportConnectorRead,
    ImportSourceDocumentList,
    ImportSourceDocumentRead,
    ImportTriggerRequest,
    ImportTriggerResponse,
    ImportValidateRequest,
    ImportValidateResponse,
)
from app.services.import_service import (
    ImportService,
    ImportServiceError,
    ImportStatus,
    ImportType,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/imports", tags=["imports"])


# ── Trigger import ─────────────────────────────────────────────────────


@router.post(
    "/trigger",
    response_model=ImportTriggerResponse,
    status_code=200,
    summary="Trigger a file-based import",
)
async def trigger_import(
    body: ImportTriggerRequest,
    db: AsyncSession = next(get_db_session()),
):
    """Point the system at an exported file/directory and ingest it.

    The import runs synchronously (suitable for MVP-scale file sizes).
    Large imports should be handled via the Celery task path.
    """
    source_path = Path(body.source_path)

    if not source_path.is_absolute():
        raise HTTPException(
            status_code=400,
            detail="source_path must be an absolute path",
        )

    import_type = ImportType(body.import_type)
    service = ImportService(db)

    try:
        result = await service.run_import(
            import_type=import_type,
            source_path=source_path,
            workspace_id=body.workspace_id,
            run_ingestion=body.run_ingestion,
            options=body.options,
        )
    except ImportServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if result.status == ImportStatus.FAILED:
        return ImportTriggerResponse(
            import_type=result.import_type.value,
            status=result.status.value,
            source_path=result.source_path,
            connector_id=result.connector_id,
            documents_imported=result.documents_imported,
            documents_ingested=result.documents_ingested,
            errors=result.errors,
            started_at=result.started_at,
            completed_at=result.completed_at,
            error_detail=result.error_detail,
        )

    return ImportTriggerResponse(
        import_type=result.import_type.value,
        status=result.status.value,
        source_path=result.source_path,
        connector_id=result.connector_id,
        documents_imported=result.documents_imported,
        documents_ingested=result.documents_ingested,
        errors=result.errors,
        started_at=result.started_at,
        completed_at=result.completed_at,
        error_detail=result.error_detail,
    )


# ── Validate source path ──────────────────────────────────────────────


@router.post(
    "/validate",
    response_model=ImportValidateResponse,
    summary="Validate a source path before importing",
)
async def validate_import_source(body: ImportValidateRequest):
    """Quick sanity check — does the path exist and look importable?"""
    from app.importers.notion import NotionDirectoryImporter
    from app.importers.slack import SlackExportImporter
    from app.importers.generic import GenericFileScanner

    source_path = Path(body.source_path)

    import_type_map = {
        "notion_directory": NotionDirectoryImporter,
        "slack_export": SlackExportImporter,
        "generic_file": GenericFileScanner,
    }

    importer_cls = import_type_map.get(body.import_type)
    if importer_cls is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown import_type: {body.import_type}",
        )

    valid, error = importer_cls.validate_source(source_path)
    return ImportValidateResponse(
        valid=valid,
        error=error,
        import_type=body.import_type,
    )


# ── List import connectors ─────────────────────────────────────────────


@router.get(
    "/connectors",
    response_model=list[ImportConnectorRead],
    summary="List manual import connectors for a workspace",
)
async def list_import_connectors(
    workspace_id: UUID = Query(..., description="Workspace ID"),
    db: AsyncSession = next(get_db_session()),
):
    service = ImportService(db)
    connectors = await service.get_import_connectors(workspace_id)
    return [
        ImportConnectorRead.model_validate(c)
        for c in connectors
    ]


# ── List source documents from an import connector ─────────────────────


@router.get(
    "/connectors/{connector_id}/documents",
    response_model=ImportSourceDocumentList,
    summary="List source documents from an import connector",
)
async def list_import_documents(
    connector_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    processed: bool | None = None,
    db: AsyncSession = next(get_db_session()),
):
    service = ImportService(db)
    documents = await service.get_source_documents_for_connector(
        connector_id,
        limit=limit,
        offset=offset,
        processed=processed,
    )

    # Get total count
    count_query = (
        select(func.count())
        .select_from(SourceDocument)
        .where(SourceDocument.connector_id == connector_id)
    )
    total = await db.scalar(count_query) or 0

    return ImportSourceDocumentList(
        items=[ImportSourceDocumentRead.model_validate(d) for d in documents],
        total=total,
    )
