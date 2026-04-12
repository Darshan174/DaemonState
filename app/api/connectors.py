"""Connector management endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.strategy import get_connector_strategy
from app.database import get_db_session
from app.models.source import ConnectorType, SourceDocument
from app.schemas.connector import (
    ConnectorProcessingSummary,
    ConnectorRead,
    GitHubConnectRequest,
    NotionConnectRequest,
    SyncJobDetail,
    SyncJobResponse,
    ZoomConnectRequest,
)
from app.schemas.imports import ImportDocumentInput
from app.schemas.source import SourceDocumentList, SourceDocumentRead
from app.services.connector_service import (
    ConfigurationError,
    ConnectorNotFoundError,
    ConnectorService,
    InvalidStateError,
    OAuthError,
    SyncError,
    SyncInProgressError,
    WebhookVerificationError,
    WorkspaceNotFoundError,
)
from app.services.import_service import ImportService, ImportWorkspaceNotFoundError


router = APIRouter()


def _service(session: AsyncSession = Depends(get_db_session)) -> ConnectorService:
    return ConnectorService(session)


def _serialize_sync_job(job) -> SyncJobDetail:
    return SyncJobDetail(
        job_id=job.id,
        job_type=job.job_type,
        connector_id=job.connector_id,
        status=job.status.value,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_type=job.error_type,
        error_message=job.error_message,
        result_metadata=job.result_metadata,
        created_at=job.created_at,
    )


def _serialize_connector(connector) -> ConnectorRead:
    strategy = get_connector_strategy(connector.connector_type)
    provider_note = strategy.note
    if connector.connector_type == ConnectorType.ZOOM:
        auth_mode = (connector.config or {}).get("auth_mode")
        if auth_mode == "manual_token":
            provider_note = (
                f"{strategy.note} Manual-token Zoom connections are polling-only; "
                "webhook-driven sync requires OAuth install."
            )
        elif auth_mode == "oauth":
            provider_note = (
                f"{strategy.note} OAuth-installed Zoom connections support "
                "webhook-driven sync."
            )
    if connector.connector_type == ConnectorType.GITHUB:
        auth_mode = (connector.config or {}).get("auth_mode")
        if auth_mode == "manual_token":
            provider_note = (
                f"{strategy.note} Manual-token GitHub connections are polling-only."
            )
    return ConnectorRead(
        id=connector.id,
        workspace_id=connector.workspace_id,
        connector_type=connector.connector_type.value,
        status=connector.status.value,
        last_sync_at=connector.last_sync_at,
        config=connector.config,
        provider=strategy.provider.value,
        provider_label=strategy.provider_label,
        provider_note=provider_note,
    )


def _serialize_source_document(document: SourceDocument) -> SourceDocumentRead:
    return SourceDocumentRead(
        id=document.id,
        connector_id=document.connector_id,
        connector_type=document.connector_type.value,
        external_id=document.external_id,
        content=document.content,
        author=document.author,
        source_url=document.source_url,
        created_at_source=document.created_at_source,
        ingested_at=document.ingested_at,
        processed_at=document.processed_at,
        deleted_at=document.deleted_at,
        metadata=document.metadata_json,
    )


@router.post("/source-documents/upload", response_model=SourceDocumentRead)
async def upload_source_document(
    workspace_id: UUID = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
) -> SourceDocumentRead:
    """Compatibility upload endpoint that routes browser files through local import."""
    filename = file.filename or "uploaded-file"
    suffix = Path(filename).suffix.lower()
    content = await file.read()

    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        text_content = content.decode("latin-1")

    if not text_content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    service = ImportService(session)
    try:
        result = await service.import_documents(
            workspace_id=workspace_id,
            documents=[
                ImportDocumentInput(
                    external_id=f"browser-upload:{filename}",
                    content=text_content,
                    author="Browser Upload",
                    metadata={
                        "title": filename,
                        "file_name": filename,
                        "file_extension": suffix,
                        "mime_type": file.content_type,
                        "source_type": "browser_upload",
                    },
                )
            ],
        )
    except ImportWorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    document = await session.get(SourceDocument, result.documents[0].document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Imported document could not be loaded.",
        )

    return _serialize_source_document(document)

# ── Connector list / processing summary (no path params) ─────────


@router.get("/connectors", response_model=list[ConnectorRead])
async def list_connectors(
    workspace_id: UUID,
    svc: ConnectorService = Depends(_service),
) -> list[ConnectorRead]:
    try:
        connectors = await svc.list_connectors(workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    return [_serialize_connector(c) for c in connectors]


@router.get(
    "/connectors/processing-summary",
    response_model=list[ConnectorProcessingSummary],
)
async def processing_summary(
    workspace_id: UUID,
    svc: ConnectorService = Depends(_service),
) -> list[ConnectorProcessingSummary]:
    try:
        summaries = await svc.get_processing_summary(workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    return [ConnectorProcessingSummary(**s) for s in summaries]


# ── Slack OAuth ───────────────────────────────────────────────────


@router.get("/connectors/slack/install")
async def slack_install(
    workspace_id: UUID,
    svc: ConnectorService = Depends(_service),
):
    try:
        await svc._require_workspace(workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    try:
        url = await svc.build_slack_install_url(workspace_id)
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        )

    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/connectors/slack/callback", response_model=ConnectorRead)
async def slack_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    svc: ConnectorService = Depends(_service),
) -> ConnectorRead:
    try:
        connector = await svc.handle_slack_callback(
            code=code, state=state, error=error
        )
    except InvalidStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        )

    return _serialize_connector(connector)


@router.get("/connectors/zoom/install")
async def zoom_install(
    workspace_id: UUID,
    svc: ConnectorService = Depends(_service),
):
    try:
        url = await svc.build_zoom_install_url(workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        )

    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/connectors/zoom/callback", response_model=ConnectorRead)
async def zoom_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    svc: ConnectorService = Depends(_service),
) -> ConnectorRead:
    try:
        connector = await svc.handle_zoom_callback(
            code=code,
            state=state,
            error=error,
        )
    except InvalidStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        )
    return _serialize_connector(connector)


@router.post("/connectors/zoom/webhook")
async def zoom_webhook(
    request: Request,
    svc: ConnectorService = Depends(_service),
) -> dict[str, object]:
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Zoom webhook payload must be valid JSON",
        ) from exc

    try:
        return await svc.handle_zoom_webhook(
            payload=payload,
            raw_body=raw_body,
            signature=request.headers.get("x-zm-signature"),
            request_timestamp=request.headers.get("x-zm-request-timestamp"),
        )
    except WebhookVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )
    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        )


# ── Notion manual connect ─────────────────────────────────────────


@router.post("/connectors/notion/connect", response_model=ConnectorRead)
async def connect_notion(
    body: NotionConnectRequest,
    svc: ConnectorService = Depends(_service),
) -> ConnectorRead:
    try:
        connector = await svc.connect_notion(
            workspace_id=body.workspace_id,
            token=body.token,
        )
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        )
    return _serialize_connector(connector)


@router.post("/connectors/zoom/connect", response_model=ConnectorRead)
async def connect_zoom(
    body: ZoomConnectRequest,
    svc: ConnectorService = Depends(_service),
) -> ConnectorRead:
    try:
        connector = await svc.connect_zoom(
            workspace_id=body.workspace_id,
            token=body.token,
        )
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        )
    return _serialize_connector(connector)


@router.post("/connectors/github/connect", response_model=ConnectorRead)
async def connect_github(
    body: GitHubConnectRequest,
    svc: ConnectorService = Depends(_service),
) -> ConnectorRead:
    try:
        connector = await svc.connect_github(
            workspace_id=body.workspace_id,
            token=body.token,
            repositories=body.repositories,
        )
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        )
    return _serialize_connector(connector)


# ── Connector actions (path-param routes AFTER static routes) ─────


@router.post(
    "/connectors/{connector_id}/sync",
    response_model=SyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_connector(
    connector_id: UUID,
    svc: ConnectorService = Depends(_service),
) -> SyncJobResponse:
    try:
        job = await svc.queue_sync(connector_id)
    except ConnectorNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector not found",
        )
    except SyncInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except SyncError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        )
    return SyncJobResponse(
        job_id=job.id,
        job_type=job.job_type,
        connector_id=job.connector_id,
        status=job.status.value,
        created_at=job.created_at,
    )


@router.get(
    "/connectors/{connector_id}/sync-status",
    response_model=SyncJobDetail,
)
async def get_sync_status(
    connector_id: UUID,
    svc: ConnectorService = Depends(_service),
) -> SyncJobDetail:
    """Return the most recent sync job for this connector."""
    try:
        job = await svc.get_latest_sync_job(connector_id)
    except ConnectorNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector not found",
        )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No sync jobs found for this connector",
        )
    return _serialize_sync_job(job)


@router.get(
    "/connectors/{connector_id}/sync-jobs",
    response_model=list[SyncJobDetail],
)
async def list_sync_jobs(
    connector_id: UUID,
    svc: ConnectorService = Depends(_service),
) -> list[SyncJobDetail]:
    """Return recent sync jobs for this connector (most recent first, max 20)."""
    try:
        jobs = await svc.list_sync_jobs(connector_id)
    except ConnectorNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector not found",
        )
    return [_serialize_sync_job(j) for j in jobs]


@router.delete(
    "/connectors/{connector_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def disconnect_connector(
    connector_id: UUID,
    svc: ConnectorService = Depends(_service),
) -> None:
    try:
        await svc.disconnect(connector_id)
    except ConnectorNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector not found",
        )


# ── Source documents ──────────────────────────────────────────────


@router.get("/source-documents", response_model=SourceDocumentList)
async def list_source_documents(
    workspace_id: UUID,
    connector_type: str | None = None,
    processed: bool | None = None,
    limit: int = 50,
    cursor: str | None = None,
    svc: ConnectorService = Depends(_service),
) -> SourceDocumentList:
    ct = None
    if connector_type is not None:
        try:
            ct = ConnectorType(connector_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid connector_type: {connector_type}",
            )

    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 200",
        )

    try:
        items, total, has_more = await svc.list_source_documents(
            workspace_id,
            connector_type=ct,
            processed=processed,
            limit=limit,
            cursor=cursor,
        )
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    next_cursor = str(items[-1].id) if has_more and items else None
    return SourceDocumentList(
        items=[
            SourceDocumentRead(
                id=d.id,
                connector_id=d.connector_id,
                connector_type=d.connector_type.value,
                external_id=d.external_id,
                content=d.content,
                author=d.author,
                source_url=d.source_url,
                created_at_source=d.created_at_source,
                ingested_at=d.ingested_at,
                processed_at=d.processed_at,
                deleted_at=d.deleted_at,
                metadata=d.metadata_json,
            )
            for d in items
        ],
        total=total,
        has_more=has_more,
        next_cursor=next_cursor,
    )


@router.get(
    "/source-documents/{document_id}",
    response_model=SourceDocumentRead,
)
async def get_source_document(
    document_id: UUID,
    workspace_id: UUID,
    svc: ConnectorService = Depends(_service),
) -> SourceDocumentRead:
    try:
        d = await svc.get_source_document(document_id, workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    except ConnectorNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source document not found",
        )
    return SourceDocumentRead(
        id=d.id,
        connector_id=d.connector_id,
        connector_type=d.connector_type.value,
        external_id=d.external_id,
        content=d.content,
        author=d.author,
        source_url=d.source_url,
        created_at_source=d.created_at_source,
        ingested_at=d.ingested_at,
        processed_at=d.processed_at,
        deleted_at=d.deleted_at,
        metadata=d.metadata_json,
    )
