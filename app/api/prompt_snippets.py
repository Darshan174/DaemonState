from __future__ import annotations

import hashlib
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_access_scope
from app.database import get_db_session
from app.models import PromptSnippet, Workspace
from app.services.access import AccessScope
from app.time import utc_now


router = APIRouter()
MAX_PROMPT_CHARACTERS = 20_000
MAX_PROMPTS_PER_WORKSPACE = 200


class PromptSnippetCreate(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_PROMPT_CHARACTERS)

    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("content must contain a visible character")
        return normalized


class PromptSnippetUsage(BaseModel):
    prompt_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("prompt_ids")
    @classmethod
    def unique_ids(cls, value: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(value))


async def _active_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    access_scope: AccessScope,
) -> Workspace:
    if not access_scope.allows_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.status != "active":
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _snippet_dict(snippet: PromptSnippet) -> dict:
    return {
        "id": str(snippet.id),
        "workspace_id": str(snippet.workspace_id),
        "content": snippet.content,
        "content_sha256": snippet.content_sha256,
        "use_count": snippet.use_count,
        "last_used_at": snippet.last_used_at,
        "created_at": snippet.created_at,
        "updated_at": snippet.updated_at,
    }


@router.get("/workspaces/{workspace_id}/prompt-snippets")
async def list_prompt_snippets(
    workspace_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    await _active_workspace(session, workspace_id, access_scope)
    snippets = list(await session.scalars(
        select(PromptSnippet)
        .where(PromptSnippet.workspace_id == workspace_id)
        .order_by(
            PromptSnippet.last_used_at.desc().nulls_last(),
            PromptSnippet.created_at.desc(),
            PromptSnippet.id,
        )
        .limit(MAX_PROMPTS_PER_WORKSPACE)
    ))
    return {
        "schema_version": "prompt_snippet_list.v1",
        "workspace_id": str(workspace_id),
        "prompts": [_snippet_dict(snippet) for snippet in snippets],
    }


@router.post(
    "/workspaces/{workspace_id}/prompt-snippets",
    status_code=status.HTTP_201_CREATED,
)
async def create_prompt_snippet(
    workspace_id: UUID,
    payload: PromptSnippetCreate,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    await _active_workspace(session, workspace_id, access_scope)
    digest = hashlib.sha256(payload.content.encode("utf-8")).hexdigest()
    existing = await session.scalar(
        select(PromptSnippet).where(
            PromptSnippet.workspace_id == workspace_id,
            PromptSnippet.content_sha256 == digest,
        )
    )
    if existing is not None:
        return _snippet_dict(existing)

    # Count separately so the limit is enforced without loading prompt bodies.
    count = int(await session.scalar(
        select(func.count())
        .select_from(PromptSnippet)
        .where(PromptSnippet.workspace_id == workspace_id)
    ) or 0)
    if count >= MAX_PROMPTS_PER_WORKSPACE:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "prompt_library_full",
                "message": (
                    f"This project already stores {MAX_PROMPTS_PER_WORKSPACE} prompts. "
                    "Delete one before saving another."
                ),
            },
        )

    snippet = PromptSnippet(
        workspace_id=workspace_id,
        content=payload.content,
        content_sha256=digest,
    )
    session.add(snippet)
    await session.flush()
    await session.commit()
    await session.refresh(snippet)
    return _snippet_dict(snippet)


@router.post("/workspaces/{workspace_id}/prompt-snippets/usage")
async def record_prompt_snippet_usage(
    workspace_id: UUID,
    payload: PromptSnippetUsage,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    await _active_workspace(session, workspace_id, access_scope)
    now = utc_now()
    result = await session.execute(
        update(PromptSnippet)
        .where(
            PromptSnippet.workspace_id == workspace_id,
            PromptSnippet.id.in_(payload.prompt_ids),
        )
        .values(
            use_count=PromptSnippet.use_count + 1,
            last_used_at=now,
            updated_at=now,
        )
    )
    await session.commit()
    return {
        "schema_version": "prompt_snippet_usage.v1",
        "workspace_id": str(workspace_id),
        "updated": int(result.rowcount or 0),
    }


@router.delete(
    "/workspaces/{workspace_id}/prompt-snippets/{prompt_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_prompt_snippet(
    workspace_id: UUID,
    prompt_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> Response:
    await _active_workspace(session, workspace_id, access_scope)
    snippet = await session.scalar(
        select(PromptSnippet).where(
            PromptSnippet.workspace_id == workspace_id,
            PromptSnippet.id == prompt_id,
        )
    )
    if snippet is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    await session.delete(snippet)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
