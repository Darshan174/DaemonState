from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.knowledge import (
    Component,
    ComponentSource,
    KnowledgeModel,
    Relationship,
    RelationshipType,
)
from app.models.review import ReviewItem
from app.models.user import Workspace
from app.schemas.decision import (
    DecisionHistoryRead,
    DecisionRationaleSourceRead,
    DecisionRead,
)
from app.services.truth_visibility import (
    history_where,
    is_component_visible_in_current_truth,
    is_component_visible_in_history,
)


class DecisionServiceError(Exception):
    """Base decision-register service error."""


class DecisionWorkspaceNotFoundError(DecisionServiceError):
    """Raised when the workspace does not exist."""


class DecisionNotFoundError(DecisionServiceError):
    """Raised when a decision component is missing or out of scope."""


class DecisionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_decisions(
        self,
        *,
        workspace_id: UUID,
        include_historical: bool = False,
        limit: int = 50,
    ) -> list[DecisionRead]:
        await self._require_workspace(workspace_id)

        stmt = self._decision_stmt(workspace_id)
        if not include_historical:
            # Push current-truth filtering into SQL
            stmt = stmt.where(Component.valid_to.is_(None))
            stmt = stmt.where(
                or_(
                    ~Component.review_item.has(),
                    ~Component.review_item.has(
                        ReviewItem.status.in_(("rejected", "superseded"))
                    ),
                )
            )
        else:
            stmt = history_where(stmt)

        rows = list(
            await self.session.scalars(
                stmt.order_by(
                    Component.valid_to.is_not(None).asc(),
                    Component.valid_from.desc(),
                    Component.id.desc(),
                ).limit(limit)
            )
        )
        return [self._serialize_decision(component) for component in rows]

    async def get_decision_history(
        self,
        *,
        workspace_id: UUID,
        component_id: UUID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> DecisionHistoryRead:
        await self._require_workspace(workspace_id)
        target = await self.session.scalar(
            self._decision_stmt(workspace_id).where(Component.id == component_id)
        )
        if target is None or not is_component_visible_in_history(target):
            raise DecisionNotFoundError("Decision not found")

        lineage_stmt = self._decision_stmt(workspace_id).where(
            Component.model_id == target.model_id,
            func.lower(Component.name) == target.name.lower(),
        )
        # History view: include all versions except rejected
        lineage_stmt = history_where(lineage_stmt)
        lineage_components = list(
            await self.session.scalars(
                lineage_stmt.order_by(
                    Component.valid_from.desc(),
                    Component.id.desc(),
                )
            )
        )
        current = next(
            (
                component
                for component in lineage_components
                if component.valid_to is None
                and is_component_visible_in_current_truth(component)
            ),
            None,
        )

        entries = lineage_components
        if cursor:
            try:
                cursor_id = UUID(cursor)
                start_index = next(
                    index + 1
                    for index, component in enumerate(entries)
                    if component.id == cursor_id
                )
                entries = entries[start_index:]
            except (StopIteration, ValueError):
                pass
        has_more = len(entries) > limit
        paged_entries = entries[:limit]
        next_cursor = str(paged_entries[-1].id) if has_more and paged_entries else None
        return DecisionHistoryRead(
            workspace_id=workspace_id,
            decision_name=target.name,
            current_decision_id=current.id if current is not None else None,
            total_versions=len(lineage_components),
            has_more=has_more,
            next_cursor=next_cursor,
            entries=[self._serialize_decision(component) for component in paged_entries],
        )

    def _decision_stmt(self, workspace_id: UUID):
        return (
            select(Component)
            .join(KnowledgeModel, Component.model_id == KnowledgeModel.id)
            .options(
                selectinload(Component.model),
                selectinload(Component.review_item).selectinload(ReviewItem.decision_history),
                selectinload(Component.source_links).selectinload(ComponentSource.source_document),
                selectinload(Component.outgoing_relationships)
                .selectinload(Relationship.target_component)
                .selectinload(Component.review_item),
                selectinload(Component.incoming_relationships).selectinload(
                    Relationship.source_component
                ).selectinload(Component.review_item),
            )
            .where(
                KnowledgeModel.workspace_id == workspace_id,
                func.lower(Component.name).like("%decision%"),
            )
        )

    async def _require_workspace(self, workspace_id: UUID) -> None:
        workspace = await self.session.scalar(
            select(Workspace.id).where(Workspace.id == workspace_id).limit(1)
        )
        if workspace is None:
            raise DecisionWorkspaceNotFoundError("Workspace not found")

    @staticmethod
    def _serialize_decision(component: Component) -> DecisionRead:
        model = component.model
        review_item = component.review_item
        rationale_sources = [
            DecisionRationaleSourceRead(
                source_document_id=link.source_document.id,
                label=link.source_document.label,
                connector_type=link.source_document.connector_type.value,
                source_url=link.source_document.source_url,
                author=link.source_document.author,
                created_at_source=link.source_document.created_at_source,
                extraction_context=link.extraction_context,
                extracted_value=link.extracted_value,
                extractor_name=link.extractor_name,
                extractor_kind=link.extractor_kind,
                extractor_schema_version=link.extractor_schema_version,
            )
            for link in sorted(
                [
                    link
                    for link in component.source_links
                    if link.source_document is not None
                ],
                key=lambda item: (
                    item.source_document.created_at_source or item.source_document.ingested_at
                ),
                reverse=True,
            )
            if link.source_document.deleted_at is None
        ]
        primary_source = rationale_sources[0] if rationale_sources else None
        return DecisionRead(
            id=component.id,
            model_id=component.model_id,
            model_name=model.name if model is not None else "",
            name=component.name,
            value=component.value,
            summary=review_item.summary if review_item is not None else component.value,
            confidence=component.confidence,
            authority_weight=component.authority_weight,
            authority_source=component.authority_source,
            source_document_id=primary_source.source_document_id if primary_source else None,
            source_label=primary_source.label if primary_source else None,
            connector_type=primary_source.connector_type if primary_source else None,
            related_blocker=DecisionService._related_blocker(component),
            review_status=component.review_status,
            review_summary=component.review_summary,
            review_item_id=component.review_item_id,
            valid_from=component.valid_from,
            valid_to=component.valid_to,
            superseded_by=component.superseded_by,
            is_current=component.valid_to is None,
            temporal_state=component.temporal_state,
            decision_history=list(review_item.decision_history) if review_item is not None else [],
            rationale_sources=rationale_sources,
        )

    @staticmethod
    def _related_blocker(component: Component) -> str | None:
        blockers: list[str] = []
        for relationship in component.outgoing_relationships:
            if relationship.valid_to is not None:
                continue
            if relationship.relationship_type != RelationshipType.BLOCKED_BY:
                continue
            target_component = relationship.target_component
            if not DecisionService._is_visible_blocker(target_component):
                continue
            blockers.append(target_component.value)

        if blockers:
            return blockers[0]

        for relationship in component.incoming_relationships:
            if relationship.valid_to is not None:
                continue
            if relationship.relationship_type != RelationshipType.BLOCKED_BY:
                continue
            source_component = relationship.source_component
            if not DecisionService._is_visible_blocker(source_component):
                continue
            blockers.append(source_component.value)
        return blockers[0] if blockers else None

    @staticmethod
    def _is_visible_blocker(component: Component | None) -> bool:
        if component is None:
            return False
        if not component.name.lower().startswith("blocker"):
            return False
        return is_component_visible_in_current_truth(component)
