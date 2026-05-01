from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models import Connector, SourceDocument, SyncJob
from app.services.ingest import IngestionService

router = APIRouter()

CONNECTOR_CATALOG: list[dict[str, Any]] = [
    {
        "type": "slack",
        "name": "Slack",
        "description": "Channels, DMs, and thread history",
        "color": "#4A154B",
        "availability": "available",
        "provider": "native",
        "provider_label": "Built in",
        "provider_note": "Slack stays native because OAuth, thread expansion, and real-time events are product-critical.",
        "auth_mode": "oauth",
        "supported": False,
        "setup_note": "Slack requires OAuth configuration. Run self-hosted setup or use managed connect to enable real-time sync.",
    },
    {
        "type": "discord",
        "name": "Discord",
        "description": "Server channels, threads, and DM history",
        "color": "#5865F2",
        "availability": "coming_soon",
        "provider": "official_api",
        "provider_label": "Official API",
        "provider_note": "Discord connector is planned for a future milestone.",
        "auth_mode": None,
        "supported": False,
        "setup_note": "Discord integration is not yet available. Join the waitlist for early access.",
    },
    {
        "type": "gmail",
        "name": "Gmail",
        "description": "Email threads, attachments, and sender context",
        "color": "#EA4335",
        "availability": "coming_soon",
        "provider": "official_api",
        "provider_label": "Official API",
        "provider_note": "Gmail should ingest selected mailbox threads and attachments with source provenance.",
        "auth_mode": None,
        "supported": False,
        "setup_note": "Gmail integration is not yet available. It will use Google OAuth for secure mailbox access.",
    },
    {
        "type": "ai_context",
        "name": "AI Context",
        "description": "Developer agent sessions, plans, diffs, and review notes",
        "color": "#6366F1",
        "availability": "available",
        "provider": "native",
        "provider_label": "Built in",
        "provider_note": "Import context from Codex, Claude Code, OpenCode, and other AI development tools.",
        "auth_mode": "manual",
        "supported": True,
        "setup_note": "AI context import is ready. Use the import endpoint to submit agent sessions, plans, and diffs.",
    },
    {
        "type": "local",
        "name": "Local Files",
        "description": "Upload local documents and files",
        "color": "#6B7280",
        "availability": "available",
        "provider": "native",
        "provider_label": "Built in",
        "provider_note": "Local file upload creates source documents for extraction.",
        "auth_mode": None,
        "supported": True,
        "setup_note": "Local file upload is always available via the sources endpoint.",
    },
]


class AIContextDocument(BaseModel):
    external_id: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    author: str | None = None
    tool: str | None = None
    session_type: str | None = None
    session_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AIContextImportRequest(BaseModel):
    documents: list[AIContextDocument] = Field(min_length=1)


class ConnectorConnectRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectorRead(BaseModel):
    connector_id: UUID | None = None
    type: str
    name: str
    description: str
    color: str
    availability: str
    provider: str
    provider_label: str
    provider_note: str | None = None
    status: str
    last_sync: str | None = None
    items_synced: int = 0
    message: str | None = None
    team_name: str | None = None
    scope: str | None = None
    sync_queued_at: str | None = None
    sync_mode: str | None = None
    sync_mode_note: str | None = None
    processed_count: int = 0
    total_processed_count: int = 0
    auth_mode: str | None = None
    account_id: str | None = None
    ingestion_mode: str | None = None
    source_focus: str | None = None
    last_webhook_event: str | None = None
    last_webhook_received_at: str | None = None
    is_configured: bool = False
    managed_connect_available: bool = False
    managed_install_url: str | None = None

    model_config = {"from_attributes": True}


class SyncJobRead(BaseModel):
    job_id: UUID
    connector_id: UUID
    status: str
    error_type: str | None = None
    error_message: str | None = None
    result_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class ProcessingSummaryItem(BaseModel):
    connector_type: str
    total_documents: int = 0
    processed_documents: int = 0
    unprocessed_documents: int = 0


class ProcessingSummaryResponse(BaseModel):
    items: list[ProcessingSummaryItem]


def _catalog_entry(connector_type: str) -> dict[str, Any] | None:
    for entry in CONNECTOR_CATALOG:
        if entry["type"] == connector_type:
            return entry
    return None


def _parse_config_json(config: Any) -> dict[str, Any]:
    if config is None:
        return {}
    if isinstance(config, dict):
        return config
    if isinstance(config, str):
        try:
            return json.loads(config)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _build_connector_read(
    catalog_entry: dict[str, Any],
    db_connector: Connector | None,
    latest_job: SyncJob | None = None,
    processed_count: int = 0,
) -> ConnectorRead:
    items_synced = db_connector.items_synced if db_connector else 0
    conn_status = db_connector.status if db_connector else "disconnected"
    conn_id = db_connector.id if db_connector else None
    last_sync = db_connector.last_sync_at.isoformat() if db_connector and db_connector.last_sync_at else None

    message = None
    team_name = None
    scope = None
    sync_queued_at = None
    sync_mode = None
    sync_mode_note = None
    account_id = None
    ingestion_mode = None
    source_focus = None
    managed_install_url = None
    is_configured = False
    managed_connect_available = False

    if db_connector:
        config = _parse_config_json(db_connector.config_json)
        team_name = config.get("team_name")
        scope = config.get("scope")
        account_id = config.get("account_id")
        ingestion_mode = config.get("ingestion_mode")
        source_focus = config.get("source_focus")

    if catalog_entry["type"] == "ai_context":
        if db_connector:
            conn_status = db_connector.status
            is_configured = db_connector.status in ("connected", "disconnected")
        else:
            conn_status = "connected"
            is_configured = True
    elif catalog_entry["type"] == "local":
        if db_connector:
            conn_status = db_connector.status
            is_configured = True
        else:
            conn_status = "connected"
            is_configured = True
    elif catalog_entry.get("supported") is False:
        is_configured = False
        conn_status = "disconnected"
    elif db_connector:
        is_configured = True

    if catalog_entry.get("supported") is False:
        message = catalog_entry.get("setup_note")

    if latest_job:
        if latest_job.status == "pending":
            sync_queued_at = latest_job.created_at.isoformat() if latest_job.created_at else None
        elif latest_job.status == "running":
            sync_mode = "full"

    return ConnectorRead(
        connector_id=conn_id,
        type=catalog_entry["type"],
        name=catalog_entry["name"],
        description=catalog_entry["description"],
        color=catalog_entry["color"],
        availability=catalog_entry["availability"],
        provider=catalog_entry["provider"],
        provider_label=catalog_entry["provider_label"],
        provider_note=catalog_entry.get("provider_note"),
        status=conn_status,
        last_sync=last_sync,
        items_synced=items_synced,
        message=message,
        team_name=team_name,
        scope=scope,
        sync_queued_at=sync_queued_at,
        sync_mode=sync_mode,
        sync_mode_note=sync_mode_note,
        processed_count=processed_count,
        total_processed_count=processed_count,
        auth_mode=catalog_entry.get("auth_mode"),
        account_id=account_id,
        ingestion_mode=ingestion_mode,
        source_focus=source_focus,
        last_webhook_event=None,
        last_webhook_received_at=None,
        is_configured=is_configured,
        managed_connect_available=managed_connect_available,
        managed_install_url=managed_install_url,
    )


def _build_sync_job_read(job: SyncJob) -> SyncJobRead:
    return SyncJobRead(
        job_id=job.id,
        connector_id=job.connector_id,
        status=job.status,
        error_type=job.error_type,
        error_message=job.error_message,
        result_metadata=_parse_config_json(job.result_metadata_json),
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


async def _run_ai_context_ingestion(doc_id: UUID, database_url: str) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession as AS, async_sessionmaker, create_async_engine
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, class_=AS, expire_on_commit=False)
    async with session_factory() as session:
        svc = IngestionService(session)
        await svc.process_document(doc_id)
        await session.commit()
    await engine.dispose()


async def _count_processed(session: AsyncSession, connector_type: str) -> int:
    type_patterns = _ai_context_subtypes(connector_type)
    return await session.scalar(
        select(sa_func.count(SourceDocument.id)).where(
            SourceDocument.source_type.in_(type_patterns),
            SourceDocument.processed_at.isnot(None),
        )
    ) or 0


def _ai_context_subtypes(connector_type: str) -> list[str]:
    if connector_type == "ai_context":
        return [
            "ai_context",
            "ai_context_codex",
            "ai_context_claude_code",
            "ai_context_opencode",
        ]
    return [connector_type]


async def _get_setup_status_items(session: AsyncSession) -> list[dict[str, Any]]:
    connectors = (await session.scalars(select(Connector))).all()
    connector_map: dict[str, Connector] = {c.connector_type: c for c in connectors}

    result: list[dict[str, Any]] = []
    for entry in CONNECTOR_CATALOG:
        db_conn = connector_map.get(entry["type"])
        if entry["type"] == "ai_context":
            configured = True
            status_str = "available"
        elif entry["type"] == "local":
            configured = True
            status_str = "available"
        elif entry.get("supported") is False:
            configured = False
            status_str = "coming_soon" if entry.get("availability") == "coming_soon" else "disconnected"
        elif db_conn:
            configured = True
            status_str = db_conn.status
        else:
            configured = False
            status_str = "disconnected"

        result.append({
            "connector_type": entry["type"],
            "type": entry["type"],
            "name": entry["name"],
            "configured": configured,
            "status": status_str,
            "availability": entry["availability"],
            "auth_mode": entry.get("auth_mode"),
        })

    return result


@router.get("/connectors")
async def list_connectors(
    workspace_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    connectors = (await session.scalars(select(Connector))).all()
    connector_map: dict[str, Connector] = {c.connector_type: c for c in connectors}

    result: list[dict[str, Any]] = []
    for entry in CONNECTOR_CATALOG:
        db_conn = connector_map.get(entry["type"])
        processed_count = 0
        if db_conn:
            processed_count = await _count_processed(session, entry["type"])

        latest_job = None
        if db_conn:
            latest_job = await session.scalar(
                select(SyncJob)
                .where(SyncJob.connector_id == db_conn.id)
                .order_by(SyncJob.created_at.desc())
                .limit(1)
            )

        item = _build_connector_read(entry, db_conn, latest_job, processed_count)
        serialized = item.model_dump(by_alias=False)
        serialized["connector_type"] = entry["type"]
        serialized["last_sync_at"] = db_conn.last_sync_at.isoformat() if db_conn and db_conn.last_sync_at else None
        config_dict: dict[str, Any] = {}
        if item.team_name:
            config_dict["team_name"] = item.team_name
        if item.scope:
            config_dict["scope"] = item.scope
        if item.sync_queued_at:
            config_dict["sync_queued_at"] = item.sync_queued_at
        if item.sync_mode:
            config_dict["sync_mode"] = item.sync_mode
        if item.sync_mode_note:
            config_dict["sync_mode_note"] = item.sync_mode_note
        if item.processed_count:
            config_dict["processed_count"] = item.processed_count
        if item.total_processed_count:
            config_dict["total_processed_count"] = item.total_processed_count
        if item.auth_mode:
            config_dict["auth_mode"] = item.auth_mode
        if item.account_id:
            config_dict["account_id"] = item.account_id
        if item.ingestion_mode:
            config_dict["ingestion_mode"] = item.ingestion_mode
        if item.source_focus:
            config_dict["source_focus"] = item.source_focus
        if item.message:
            config_dict["message"] = item.message
        serialized["config"] = config_dict
        result.append(serialized)

    setup_status = await _get_setup_status_items(session)

    return {"connectors": result, "setupStatus": setup_status}


@router.get("/connectors/setup-status")
async def get_setup_status(
    workspace_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    return await _get_setup_status_items(session)


@router.get("/connectors/processing-summary", response_model=ProcessingSummaryResponse)
async def get_processing_summary(
    workspace_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> ProcessingSummaryResponse:
    all_types = {
        "slack": ["slack"],
        "discord": ["discord"],
        "gmail": ["gmail"],
        "ai_context": ["ai_context", "ai_context_codex", "ai_context_claude_code", "ai_context_opencode"],
        "local": ["local"],
    }
    flat_types = [t for group in all_types.values() for t in group]
    rows = await session.execute(
        select(
            SourceDocument.source_type,
            sa_func.count(SourceDocument.id).label("total"),
            sa_func.count(SourceDocument.processed_at).label("processed"),
        )
        .where(SourceDocument.source_type.in_(flat_types))
        .group_by(SourceDocument.source_type)
    )
    raw_counts: dict[str, tuple[int, int]] = {}
    for row in rows:
        raw_counts[row.source_type] = (row.total, row.processed)

    items: list[ProcessingSummaryItem] = []
    for display_type, subtypes in all_types.items():
        total = sum(raw_counts.get(st, (0, 0))[0] for st in subtypes)
        processed = sum(raw_counts.get(st, (0, 0))[1] for st in subtypes)
        items.append(ProcessingSummaryItem(
            connector_type=display_type,
            total_documents=total,
            processed_documents=processed,
            unprocessed_documents=total - processed,
        ))

    return ProcessingSummaryResponse(items=items)


@router.post("/connectors/ai-context/import", status_code=201)
async def import_ai_context(
    payload: AIContextImportRequest,
    background_tasks: BackgroundTasks,
    sync: bool = False,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    valid_tools = {"codex", "claude_code", "opencode", "cursor", "generic"}
    created_ids: list[str] = []

    for doc in payload.documents:
        tool = doc.tool
        if tool and tool not in valid_tools:
            tool = "generic"

        source_type = "ai_context"
        if tool == "codex":
            source_type = "ai_context_codex"
        elif tool == "claude_code":
            source_type = "ai_context_claude_code"
        elif tool == "opencode":
            source_type = "ai_context_opencode"

        metadata = dict(doc.metadata) if doc.metadata else {}
        if doc.tool:
            metadata["tool"] = tool or doc.tool
        if doc.session_type:
            metadata["session_type"] = doc.session_type
        if doc.session_id:
            metadata["session_id"] = doc.session_id
        if doc.started_at:
            metadata["started_at"] = doc.started_at
        if doc.ended_at:
            metadata["ended_at"] = doc.ended_at
        metadata["ingested_via"] = "ai_context_import"

        source_doc = SourceDocument(
            source_type=source_type,
            external_id=doc.external_id,
            content=doc.content,
            author=doc.author,
            source_url=None,
            metadata_json=json.dumps(metadata),
        )
        session.add(source_doc)
        await session.flush()
        created_ids.append(str(source_doc.id))

    await session.commit()

    if sync:
        from app.config import settings
        for doc_id_str in created_ids:
            background_tasks.add_task(_run_ai_context_ingestion, UUID(doc_id_str), settings.database_url)

    return {
        "created": len(created_ids),
        "document_ids": created_ids,
        "source_type": "ai_context",
    }


@router.post("/connectors/{connector_type}/connect", response_model=ConnectorRead)
async def connect_connector(
    connector_type: str,
    payload: ConnectorConnectRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ConnectorRead:
    catalog_entry = _catalog_entry(connector_type)
    if catalog_entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown connector type: {connector_type}",
        )

    if catalog_entry["availability"] == "coming_soon":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connector {catalog_entry['name']} is not available yet. {catalog_entry.get('setup_note', '')}",
        )

    if not catalog_entry.get("supported", True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connector {catalog_entry['name']} does not have a working sync path yet. {catalog_entry.get('setup_note', '')}",
        )

    existing = await session.scalar(
        select(Connector).where(Connector.connector_type == connector_type)
    )

    if existing:
        existing.config_json = json.dumps(payload.config)
        existing.status = "connected"
        existing.updated_at = datetime.now(timezone.utc)
        await session.flush()
        await session.commit()
        processed_count = await session.scalar(
            select(sa_func.count(SourceDocument.id)).where(
                SourceDocument.source_type == connector_type,
                SourceDocument.processed_at.isnot(None),
            )
        ) or 0
        return _build_connector_read(catalog_entry, existing, None, processed_count)

    connector = Connector(
        id=uuid4(),
        connector_type=connector_type,
        status="connected",
        config_json=json.dumps(payload.config),
        items_synced=0,
    )
    session.add(connector)
    await session.flush()
    await session.commit()

    return _build_connector_read(catalog_entry, connector, None, 0)


@router.post("/connectors/{connector_id}/sync", response_model=SyncJobRead)
async def sync_connector(
    connector_id: UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
) -> SyncJobRead:
    connector = await session.get(Connector, connector_id)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector {connector_id} not found",
        )

    catalog_entry = _catalog_entry(connector.connector_type)
    if catalog_entry and not catalog_entry.get("supported", True):
        job = SyncJob(
            id=uuid4(),
            connector_id=connector.id,
            status="failed",
            error_type="unsupported_connector",
            error_message=f"Sync is not supported for {catalog_entry['name']}. {catalog_entry.get('setup_note', 'This connector is not yet available.')}",
            result_metadata_json="{}",
        )
        session.add(job)
        await session.flush()
        await session.commit()
        return _build_sync_job_read(job)

    job = SyncJob(
        id=uuid4(),
        connector_id=connector.id,
        status="pending",
        result_metadata_json="{}",
    )
    session.add(job)
    await session.flush()
    await session.commit()

    return _build_sync_job_read(job)


@router.get("/connectors/{connector_id}/sync-status", response_model=SyncJobRead | None)
async def get_sync_status(
    connector_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> SyncJobRead | None:
    connector = await session.get(Connector, connector_id)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector {connector_id} not found",
        )

    job = await session.scalar(
        select(SyncJob)
        .where(SyncJob.connector_id == connector_id)
        .order_by(SyncJob.created_at.desc())
        .limit(1)
    )
    if job is None:
        return None

    return _build_sync_job_read(job)


@router.get("/connectors/{connector_id}/sync-jobs", response_model=list[SyncJobRead])
async def get_sync_jobs(
    connector_id: UUID,
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> list[SyncJobRead]:
    connector = await session.get(Connector, connector_id)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector {connector_id} not found",
        )

    jobs = await session.scalars(
        select(SyncJob)
        .where(SyncJob.connector_id == connector_id)
        .order_by(SyncJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_build_sync_job_read(job) for job in jobs]


@router.delete("/connectors/{connector_id}")
async def disconnect_connector(
    connector_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    connector = await session.get(Connector, connector_id)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector {connector_id} not found",
        )

    connector.status = "disconnected"
    connector.config_json = "{}"
    connector.updated_at = datetime.now(timezone.utc)
    await session.flush()
    await session.commit()

    return {"status": "disconnected", "connector_id": str(connector_id)}