from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models import SourceDocument, Workspace
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
            "title": "Board graph needs source-first clusters",
        },
        "content": {
            "number": 12,
            "title": "Board graph needs source-first clusters",
            "state": "open",
            "user": {"login": "maya"},
            "labels": ["enhancement", "graph", "trust"],
            "body": "\n".join([
                "Decision: Board should group facts by source family before entity type.",
                "Task: Add Board | Explore toggle with Board as the default URL state.",
                "Risk: Users lose trust when facts are not visibly tied to source evidence.",
            ]),
            "comments": [
                "Keep canvas quiet by default and move trust metadata into the inspector.",
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
            "title": "Ship Board graph default",
        },
        "content": {
            "number": 11,
            "title": "Ship Board graph default",
            "state": "closed",
            "merged": True,
            "user": {"login": "ravi"},
            "labels": ["enhancement"],
            "body": "\n".join([
                "Fixes #12",
                "Decision: Keep confidence, temporal state, and edge origin in the inspector.",
                "Task: Add hover-only edge labels so default zoom stays quiet.",
            ]),
            "changed_files": [
                {"filename": "frontend/src/pages/GraphView.jsx"},
                {"filename": "frontend/src/graph/boardMode.js"},
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
            "Decision: Use a right-rail inspector for provenance and trust metadata.",
            "Task: Expose source links for every selected fact.",
            "Risk: Rainbow edge styling overwhelms the graph at default zoom.",
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
            "snippet": "Top-K controls and facts-used traces would make answers auditable.",
        },
        "content": "\n".join([
            "Subject: AI agents need project memory before sprint planning",
            "From: Priya <founder@example.com>",
            "",
            "Decision: Retrieval answers must show the facts used with source provenance.",
            "Task: Add top_k and min_confidence controls to the Ask workflow.",
            "Metric: Demo users should understand why an answer was returned in under 30 seconds.",
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
            "Task: Publish architecture, connector, Board vs Explore, and MCP documentation.",
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
            "title": "Board and Explore graph implementation",
            "branch": "demo/board-explore",
        },
        "content": "\n".join([
            "# Board and Explore graph implementation",
            "Decision: Board remains default and Explore handles Obsidian-style local navigation.",
            "Next step: Add frontend smoke tests for the onboarding demo and graph views.",
            "Risk: Explore mode is impressive only if the local graph panel explains one-hop context.",
            "Touched files: frontend/src/pages/GraphView.jsx frontend/src/graph/exploreMode.js",
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
        "message": "Seeded launch demo data from GitHub, Slack, Gmail, Google Drive, and Codex sources.",
    }


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
