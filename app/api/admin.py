from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models.user import Workspace
from app.schemas.user import WorkspaceCreate, WorkspaceRead


router = APIRouter()


@router.post(
    "/workspaces",
    response_model=WorkspaceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace(
    payload: WorkspaceCreate,
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceRead:
    workspace = Workspace(**payload.model_dump())
    session.add(workspace)
    await session.commit()
    await session.refresh(workspace)
    return WorkspaceRead.model_validate(workspace)


from datetime import datetime, timezone
from app.models.connector import Connector, ConnectorStatus
from app.models.source import SourceDocument, ConnectorType

@router.post("/seed-demo")
async def seed_demo(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """Seed the current workspace with demo data."""
    # Find the latest workspace
    workspace = await session.scalar(select(Workspace).order_by(Workspace.created_at.desc()).limit(1))
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No workspace found to seed.")

    # Create a demo Slack connector
    connector = Connector(
        workspace_id=workspace.id,
        connector_type=ConnectorType.SLACK,
        status=ConnectorStatus.CONNECTED,
        config={"document_count": 3, "message": "Demo data seeded"}
    )
    session.add(connector)
    await session.flush()

    # Add mock documents
    docs = [
        SourceDocument(
            connector_id=connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="demo-1",
            content="Decision: We will adopt a mono-repo for Context Engine.",
            author="Founder",
            ingested_at=datetime.now(timezone.utc),
            metadata_json={"source": "demo"}
        ),
        SourceDocument(
            connector_id=connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="demo-2",
            content="Roadmap: Q3 will focus on accuracy and provenance review.",
            author="Product Lead",
            ingested_at=datetime.now(timezone.utc),
            metadata_json={"source": "demo"}
        ),
        SourceDocument(
            connector_id=connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="demo-3",
            content="Blocker: We need clearer definition for the trust layer API.",
            author="Eng Lead",
            ingested_at=datetime.now(timezone.utc),
            metadata_json={"source": "demo"}
        )
    ]
    for doc in docs:
        session.add(doc)
    
    await session.commit()
    return {"workspaceId": str(workspace.id), "status": "success"}

@router.get("/workspaces", response_model=list[WorkspaceRead])
async def list_workspaces(
    session: AsyncSession = Depends(get_db_session),
) -> list[WorkspaceRead]:
    result = await session.scalars(select(Workspace).order_by(Workspace.created_at.desc()))
    return [WorkspaceRead.model_validate(item) for item in result]


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceRead)
async def get_workspace(
    workspace_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceRead:
    workspace = await session.scalar(select(Workspace).where(Workspace.id == workspace_id))
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    return WorkspaceRead.model_validate(workspace)
