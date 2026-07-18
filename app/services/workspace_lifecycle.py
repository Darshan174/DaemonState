from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentRun,
    Claim,
    ClaimRevision,
    CodeEdge,
    CodeFile,
    CodeSymbol,
    Component,
    Connector,
    ContextPack,
    ContextPackItem,
    Entity,
    EntityAlias,
    EvidenceSpan,
    Fact,
    Mention,
    OpenLoop,
    Relationship,
    RepoEvent,
    RetrievalEvent,
    RunObservation,
    SourceDocument,
    SourceReadGrant,
    SyncJob,
    UnresolvedRelationship,
    VerifiedPlaybook,
    Workspace,
    WorkspaceGoal,
)


ACTIVE_RUN_STATUSES = frozenset({"queued", "running", "in_progress"})


class WorkspaceHasActiveRunError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkspaceImpact:
    source_count: int
    component_count: int
    run_count: int
    connector_count: int

    def to_dict(self) -> dict[str, int]:
        return {
            "source_count": self.source_count,
            "component_count": self.component_count,
            "run_count": self.run_count,
            "connector_count": self.connector_count,
        }


async def workspace_impact(session: AsyncSession, workspace_id: UUID) -> WorkspaceImpact:
    async def count(model) -> int:
        return int(await session.scalar(
            select(func.count()).select_from(model).where(model.workspace_id == workspace_id)
        ) or 0)

    return WorkspaceImpact(
        source_count=await count(SourceDocument),
        component_count=await count(Component),
        run_count=await count(AgentRun),
        connector_count=await count(Connector),
    )


async def workspace_to_dict(session: AsyncSession, workspace: Workspace) -> dict:
    impact = await workspace_impact(session, workspace.id)
    repo_roots = list(dict.fromkeys(
        value
        for value in await session.scalars(
            select(CodeFile.repo_root)
            .where(CodeFile.workspace_id == workspace.id, CodeFile.repo_root.is_not(None))
            .order_by(CodeFile.updated_at.desc())
        )
        if value
    ))
    latest_source = await session.scalar(
        select(func.max(SourceDocument.ingested_at)).where(
            SourceDocument.workspace_id == workspace.id
        )
    )
    latest_run = await session.scalar(
        select(func.max(AgentRun.started_at)).where(AgentRun.workspace_id == workspace.id)
    )
    timestamps = [value for value in (latest_source, latest_run, workspace.created_at) if value]
    last_activity_at = max(timestamps) if timestamps else None
    return {
        "id": str(workspace.id),
        "name": workspace.name,
        "slug": workspace.slug,
        "kind": workspace.kind,
        "status": workspace.status,
        "archived_at": workspace.archived_at,
        "created_at": workspace.created_at,
        "last_activity_at": last_activity_at,
        "repo_path": repo_roots[0] if repo_roots else None,
        "repo_paths": repo_roots,
        **impact.to_dict(),
    }


async def require_no_active_run(session: AsyncSession, workspace_id: UUID) -> None:
    active_run = await session.scalar(
        select(AgentRun.id).where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.status.in_(ACTIVE_RUN_STATUSES),
        ).limit(1)
    )
    if active_run is not None:
        raise WorkspaceHasActiveRunError(
            "Stop the active agent run before archiving or deleting this workspace."
        )


async def delete_workspace_graph(session: AsyncSession, workspace_id: UUID) -> WorkspaceImpact:
    """Delete one workspace in dependency order while preserving every other workspace."""
    await require_no_active_run(session, workspace_id)

    impact = await workspace_impact(session, workspace_id)
    component_ids = select(Component.id).where(Component.workspace_id == workspace_id)
    claim_ids = select(Claim.id).where(Claim.workspace_id == workspace_id)
    source_ids = select(SourceDocument.id).where(SourceDocument.workspace_id == workspace_id)
    pack_ids = select(ContextPack.id).where(ContextPack.workspace_id == workspace_id)
    run_ids = select(AgentRun.id).where(AgentRun.workspace_id == workspace_id)
    file_ids = select(CodeFile.id).where(CodeFile.workspace_id == workspace_id)
    symbol_ids = select(CodeSymbol.id).where(CodeSymbol.code_file_id.in_(file_ids))

    await session.execute(delete(WorkspaceGoal).where(WorkspaceGoal.workspace_id == workspace_id))
    await session.execute(delete(OpenLoop).where(OpenLoop.workspace_id == workspace_id))
    await session.execute(delete(VerifiedPlaybook).where(VerifiedPlaybook.workspace_id == workspace_id))
    await session.execute(delete(RunObservation).where(RunObservation.agent_run_id.in_(run_ids)))
    await session.execute(delete(AgentRun).where(AgentRun.workspace_id == workspace_id))
    await session.execute(delete(ContextPackItem).where(ContextPackItem.context_pack_id.in_(pack_ids)))
    await session.execute(delete(ContextPack).where(ContextPack.workspace_id == workspace_id))

    await session.execute(delete(UnresolvedRelationship).where(
        or_(
            UnresolvedRelationship.workspace_id == workspace_id,
            UnresolvedRelationship.source_component_id.in_(component_ids),
        )
    ))
    await session.execute(delete(Relationship).where(
        or_(
            Relationship.source_component_id.in_(component_ids),
            Relationship.target_component_id.in_(component_ids),
        )
    ))

    await session.execute(delete(CodeEdge).where(
        or_(CodeEdge.source_symbol_id.in_(symbol_ids), CodeEdge.target_symbol_id.in_(symbol_ids))
    ))
    await session.execute(delete(CodeSymbol).where(CodeSymbol.code_file_id.in_(file_ids)))
    await session.execute(delete(CodeFile).where(CodeFile.workspace_id == workspace_id))
    await session.execute(delete(RepoEvent).where(RepoEvent.workspace_id == workspace_id))
    await session.execute(delete(RetrievalEvent).where(RetrievalEvent.workspace_id == workspace_id))

    await session.execute(delete(Fact).where(Fact.workspace_id == workspace_id))
    await session.execute(delete(Mention).where(Mention.workspace_id == workspace_id))
    await session.execute(update(Component).where(
        Component.superseded_by_id.in_(component_ids)
    ).values(
        superseded_by_id=None
    ))
    await session.execute(delete(Component).where(Component.workspace_id == workspace_id))
    await session.execute(delete(EntityAlias).where(EntityAlias.workspace_id == workspace_id))
    await session.execute(delete(Entity).where(Entity.workspace_id == workspace_id))

    await session.execute(update(Claim).where(Claim.id.in_(claim_ids)).values(
        current_revision_id=None
    ))
    await session.execute(update(ClaimRevision).where(
        ClaimRevision.supersedes_claim_id.in_(claim_ids)
    ).values(supersedes_claim_id=None))
    await session.execute(update(ClaimRevision).where(
        ClaimRevision.contradicts_claim_id.in_(claim_ids)
    ).values(contradicts_claim_id=None))
    await session.execute(delete(ClaimRevision).where(ClaimRevision.claim_id.in_(claim_ids)))
    await session.execute(delete(Claim).where(Claim.workspace_id == workspace_id))

    await session.execute(delete(EvidenceSpan).where(EvidenceSpan.workspace_id == workspace_id))
    await session.execute(delete(SourceReadGrant).where(SourceReadGrant.workspace_id == workspace_id))
    await session.execute(update(SourceDocument).where(
        SourceDocument.supersedes_source_document_id.in_(source_ids)
    ).values(supersedes_source_document_id=None))
    await session.execute(delete(SourceDocument).where(SourceDocument.workspace_id == workspace_id))

    await session.execute(delete(SyncJob).where(SyncJob.workspace_id == workspace_id))
    await session.execute(delete(Connector).where(Connector.workspace_id == workspace_id))
    await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
    await session.flush()
    return impact
