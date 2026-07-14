from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models import Connector, SourceDocument, Workspace
from app.services.ingest import IngestionService

router = APIRouter()

DEMO_WORKSPACE_NAME = "Context Engine Demo"
DEMO_WORKSPACE_SLUG = "context-engine-demo"


class SeedDemoRequest(BaseModel):
    workspace_id: UUID | None = None


DEMO_SOURCES: list[dict[str, Any]] = [
    {
        "source_type": "github_issue",
        "external_id": "demo:github_issue:12",
        "author": "maya",
        "metadata": {
            "item_type": "issue",
            "repo_full_name": "your-org/context-engine",
            "number": 12,
            "title": "Project map needs source-backed relevance",
        },
        "content": {
            "number": 12,
            "title": "Project map needs source-backed relevance",
            "state": "open",
            "user": {"login": "maya"},
            "labels": ["enhancement", "graph", "trust"],
            "body": "\n".join([
                "Decision: The project map should group evidence by delivery meaning.",
                "Task: Show imported session relevance through visual weight and color.",
                "Risk: Users lose trust when facts are not visibly tied to source evidence.",
            ]),
            "comments": [
                "Keep the map quiet and move detailed trust metadata into one inspector.",
            ],
        },
    },
    {
        "source_type": "github_pr",
        "external_id": "demo:github_pr:11",
        "author": "ravi",
        "metadata": {
            "item_type": "pull_request",
            "repo_full_name": "your-org/context-engine",
            "number": 11,
            "title": "Ship the source-backed project map",
        },
        "content": {
            "number": 11,
            "title": "Ship the source-backed project map",
            "state": "closed",
            "merged": True,
            "user": {"login": "ravi"},
            "labels": ["enhancement"],
            "body": "\n".join([
                "Fixes #12",
                "Decision: Keep confidence, temporal state, and edge origin in the inspector.",
                "Task: Draw only evidence-backed relationships on the default map.",
            ]),
            "changed_files": [
                {"filename": "frontend/src/pages/ContextMapPage.jsx"},
                {"filename": "frontend/src/context-map/components/DigestBoard.jsx"},
            ],
            "review_comments": [
                "Concern: source links must stay visible before this can launch.",
            ],
        },
    },
    {
        "source_type": "slack",
        "external_id": "demo:slack:eng:1715000000.000100",
        "author": "Asha",
        "metadata": {
            "channel_id": "CDEMOENG",
            "channel_name": "eng-launch",
            "ts": "1715000000.000100",
            "thread_ts": "1715000000.000100",
            "permalink": "https://slack.com/app_redirect?channel=CDEMOENG",
        },
        "content": "\n".join([
            "Decision: Use one evidence inspector for provenance and trust metadata.",
            "Task: Expose source links for every selected fact.",
            "Risk: Decorative relationships overwhelm the project map at default zoom.",
        ]),
    },
    {
        "source_type": "gmail",
        "external_id": "demo:gmail:thread-alpha-usage",
        "author": "founder@example.com",
        "metadata": {
            "thread_id": "thread-alpha-usage",
            "subject": "AI agents need project memory before sprint planning",
            "from": "Priya <founder@example.com>",
            "snippet": "A source-backed handoff would reduce context switching between agents.",
        },
        "content": "\n".join([
            "Subject: AI agents need project memory before sprint planning",
            "From: Priya <founder@example.com>",
            "",
            "Decision: Agent handoffs must identify the source evidence they use.",
            "Task: Generate a concise project handoff directly from the map.",
            "Metric: Demo users should understand project direction in under 30 seconds.",
        ]),
    },
    {
        "source_type": "gdrive",
        "external_id": "demo:gdrive:oss-launch-runbook",
        "author": "launch-team",
        "metadata": {
            "name": "OSS Launch Runbook",
            "mime_type": "application/vnd.google-apps.document",
            "drive_id": "demo-drive",
        },
        "content": "\n".join([
            "OSS Launch Runbook",
            "Decision: Keep MCP and context packs as the primary outputs for AI agents.",
            "Task: Publish architecture, project map, connector, and MCP documentation.",
            "Risk: Demo datasets that mention unsupported connectors will damage trust.",
        ]),
    },
    {
        "source_type": "ai_context_codex",
        "external_id": "demo:ai_context_codex:board-explore-session",
        "author": "codex",
        "metadata": {
            "tool": "codex",
            "connector_type": "codex",
            "session_id": "board-explore-session",
            "title": "Source-backed project map implementation",
            "branch": "demo/project-map",
        },
        "content": "\n".join([
            "# Source-backed project map implementation",
            "Decision: The map is the default project view and uses fixed semantic zones.",
            "Next step: Add frontend smoke tests for project intake and evidence inspection.",
            "Risk: Visual polish is meaningless if session relevance is not deterministic.",
            "Touched files: frontend/src/pages/ContextMapPage.jsx frontend/src/context-map/components/DigestBoard.jsx",
        ]),
    },
]


@router.post("/seed-demo")
async def seed_demo(
    payload: SeedDemoRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    workspace = await _resolve_workspace(session, payload.workspace_id if payload else None)
    ingestor = IngestionService(session)

    created_documents = 0
    existing_documents = 0
    processed_documents = 0
    components_created = 0
    document_ids: list[str] = []
    source_types: set[str] = set()
    project_boundary_created = await _ensure_demo_project_boundary(session, workspace.id)

    for spec in DEMO_SOURCES:
        doc = await _find_seed_document(session, spec, workspace.id)
        if doc is None:
            doc = _build_seed_document(spec, workspace)
            session.add(doc)
            await session.flush()
            created_documents += 1
        else:
            existing_documents += 1

        document_ids.append(str(doc.id))
        source_types.add(doc.source_type)

        if doc.processed_at is None:
            components_created += await ingestor.process_document(doc.id)
            processed_documents += 1

    await session.commit()

    status = "created" if created_documents else "ready"
    return {
        "status": status,
        "workspaceId": str(workspace.id),
        "workspace_id": str(workspace.id),
        "workspaceName": workspace.name,
        "workspaceSlug": workspace.slug,
        "createdDocuments": created_documents,
        "existingDocuments": existing_documents,
        "processedDocuments": processed_documents,
        "componentsCreated": components_created,
        "sourceTypes": sorted(source_types),
        "documentIds": document_ids,
        "projectBoundaryCreated": project_boundary_created,
        "message": "Seeded launch demo data from GitHub, Slack, Gmail, Google Drive, and Codex sources.",
    }


async def _ensure_demo_project_boundary(
    session: AsyncSession,
    workspace_id: UUID,
) -> bool:
    connectors = list(await session.scalars(
        select(Connector).where(
            Connector.workspace_id == workspace_id,
            Connector.connector_type == "github",
        )
    ))
    for connector in connectors:
        config = _metadata_dict(connector.config_json)
        if config.get("demo_seed") is True:
            return False

    session.add(Connector(
        workspace_id=workspace_id,
        connector_type="github",
        status="disconnected",
        config_json=json.dumps({
            "demo_seed": True,
            "repositories": ["your-org/context-engine"],
        }),
        credentials_json="{}",
    ))
    await session.flush()
    return True


async def _resolve_workspace(session: AsyncSession, workspace_id: UUID | None) -> Workspace:
    if workspace_id is not None:
        workspace = await session.get(Workspace, workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return workspace

    workspace = await session.scalar(select(Workspace).where(Workspace.slug == DEMO_WORKSPACE_SLUG))
    if workspace is not None:
        return workspace

    workspace = Workspace(name=DEMO_WORKSPACE_NAME, slug=DEMO_WORKSPACE_SLUG)
    session.add(workspace)
    await session.flush()
    return workspace


async def _find_seed_document(
    session: AsyncSession,
    spec: dict[str, Any],
    workspace_id: UUID,
) -> SourceDocument | None:
    docs = list(await session.scalars(
        select(SourceDocument).where(
            SourceDocument.source_type == spec["source_type"],
            SourceDocument.external_id == spec["external_id"],
        )
    ))
    workspace_id_str = str(workspace_id)
    for doc in docs:
        if doc.workspace_id == workspace_id:
            return doc
        metadata = _metadata_dict(doc.metadata_json)
        if metadata.get("demo_seed") is True and str(metadata.get("workspace_id")) == workspace_id_str:
            return doc
    return None


def _build_seed_document(spec: dict[str, Any], workspace: Workspace) -> SourceDocument:
    metadata = {
        **spec.get("metadata", {}),
        "demo_seed": True,
        "workspace_id": str(workspace.id),
        "workspace_name": workspace.name,
    }
    content = spec["content"]
    if not isinstance(content, str):
        content = json.dumps(content)
    return SourceDocument(
        workspace_id=workspace.id,
        source_type=spec["source_type"],
        external_id=spec["external_id"],
        content=content,
        author=spec.get("author"),
        source_url=spec.get("source_url"),
        metadata_json=json.dumps(metadata),
    )


def _metadata_dict(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}
