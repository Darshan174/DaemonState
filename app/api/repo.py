from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models import Workspace
from app.services.ingest import IngestionService
from app.services.repo_indexer import PROJECT_ROOT_MARKERS, RepoFrame, RepoIndexer
from app.services.source_revisions import ingest_source_document_revision

router = APIRouter()

class RepoIndexRequest(BaseModel):
    workspace_id: UUID
    repo_path: str = Field(min_length=1)


class RepoIndexResponse(BaseModel):
    workspace_id: UUID
    repo_path: str
    branch: str | None = None
    head_commit: str | None = None
    dirty: bool
    files_indexed: int
    files_added: int
    files_changed: int
    files_unchanged: int
    files_deleted: int
    symbols_indexed: int
    edges_indexed: int
    snapshot_fingerprint: str
    persistence_available: bool


@router.post("/repo/index", response_model=RepoIndexResponse)
async def index_repo(
    payload: RepoIndexRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RepoIndexResponse:
    """Validate and persist one local repository as workspace project evidence."""
    if await session.get(Workspace, payload.workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    requested_root = Path(payload.repo_path).expanduser().resolve()
    if (
        requested_root.exists()
        and requested_root.is_dir()
        and not any((requested_root / marker).exists() for marker in PROJECT_ROOT_MARKERS)
    ):
        raise HTTPException(
            status_code=422,
            detail="repo path is not a project root: expected .git or a supported project manifest",
        )

    try:
        frame = await RepoIndexer(session).inspect_repo(
            payload.repo_path,
            workspace_id=payload.workspace_id,
            persist=True,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not frame.indexed_files:
        await session.rollback()
        raise HTTPException(
            status_code=422,
            detail="No supported project files were found in the repository path",
        )

    if not frame.persistence_available:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail=frame.persistence_reason or "Repository index could not be persisted",
        )

    inventory_content, inventory_metadata = _project_inventory(frame)
    inventory = await ingest_source_document_revision(
        session,
        workspace_id=payload.workspace_id,
        source_type="local_repository",
        external_id="active-project-inventory",
        content=inventory_content,
        author="Context Engine repository indexer",
        source_url=None,
        metadata_json=inventory_metadata,
        trust_zone="trusted_repo",
    )
    if inventory.created or inventory.document.processed_at is None:
        await IngestionService(session).process_document(inventory.document.id)

    await session.commit()
    return RepoIndexResponse(
        workspace_id=payload.workspace_id,
        repo_path=frame.repo_path,
        branch=frame.branch,
        head_commit=frame.head_commit,
        dirty=frame.dirty,
        files_indexed=len(frame.indexed_files),
        files_added=frame.files_added,
        files_changed=frame.files_changed,
        files_unchanged=frame.files_unchanged,
        files_deleted=frame.files_deleted,
        symbols_indexed=sum(min(len(item.symbols), 300) for item in frame.indexed_files),
        edges_indexed=frame.edges_indexed,
        snapshot_fingerprint=frame.snapshot_fingerprint,
        persistence_available=True,
    )


def _project_inventory(frame: RepoFrame) -> tuple[str, dict[str, Any]]:
    grouped: dict[str, list] = {}
    for indexed in frame.indexed_files:
        parts = Path(indexed.path).parts
        group = parts[0] if len(parts) > 1 else "Root files"
        grouped.setdefault(group, []).append(indexed)

    ranked_groups = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0].lower()))
    visible_groups = ranked_groups[:8]
    overflow = ranked_groups[8:]
    if overflow:
        visible_groups.append((
            "Other areas",
            [indexed for _, items in overflow for indexed in items],
        ))

    branch = frame.branch or "untracked branch"
    root_name = Path(frame.repo_path).name or "Project"
    root_summary = (
        f"Repository {root_name}: {len(frame.indexed_files)} indexed files on {branch}. "
        f"Snapshot {frame.snapshot_fingerprint}; HEAD {frame.head_commit or 'none'}; "
        f"dirty {str(frame.dirty).lower()}."
    )
    areas = []
    lines = [root_summary]
    for label, items in visible_groups:
        languages = sorted({item.language for item in items if item.language})
        examples = ", ".join(item.path for item in sorted(items, key=lambda item: item.path)[:3])
        details = f"; languages {', '.join(languages[:4])}" if languages else ""
        examples_text = f"; examples {examples}" if examples else ""
        summary = f"Area {label}: {len(items)} indexed files{details}{examples_text}."
        areas.append({"label": label, "summary": summary, "file_count": len(items)})
        lines.append(summary)

    metadata = {
        "workspace_project": True,
        "repo_root": frame.repo_path,
        "branch": frame.branch,
        "head_commit": frame.head_commit,
        "dirty": frame.dirty,
        "snapshot_fingerprint": frame.snapshot_fingerprint,
        "repository": {
            "name": root_name,
            "repo_root": frame.repo_path,
            "head_commit": frame.head_commit,
            "summary": root_summary,
        },
        "areas": areas,
    }
    return "\n".join(lines), metadata
