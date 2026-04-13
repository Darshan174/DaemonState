"""Trust/review/provenance service layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.connector import Connector
from app.models.job import SyncJob, SyncJobStatus
from app.models.knowledge import Component, ComponentSource, KnowledgeModel
from app.models.review import ReviewDecision, ReviewItem
from app.models.source import SourceDocument
from app.models.user import Workspace


class TrustServiceError(Exception):
    """Base trust service error."""


class TrustResourceNotFoundError(TrustServiceError):
    """Raised when a requested trust resource does not exist."""


class WorkspaceNotFoundError(TrustServiceError):
    """Raised when the referenced workspace does not exist."""


class JobInProgressError(TrustServiceError):
    """Raised when a connector already has a pending or running job."""

    def __init__(self, job_id: UUID) -> None:
        super().__init__(f"Job already in progress. Job ID: {job_id}")
        self.job_id = job_id


class DispatchError(TrustServiceError):
    """Raised when a background job could not be dispatched."""


class InvalidStatusTransitionError(TrustServiceError):
    """Raised when a review item status transition is not allowed."""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(
            f"Invalid status transition: '{current}' -> '{target}'"
        )
        self.current_status = current
        self.target_status = target


# Explicit status transition map: current -> set of allowed targets.
# Terminal states (approved, rejected, superseded) cannot be re-mutated
# via the operator API. Only needs_review can transition to a terminal state.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "needs_review": frozenset({"approved", "rejected", "superseded"}),
}


@dataclass
class ReviewPage:
    """Paginated review items result."""
    items: list[ReviewItem]
    total: int
    limit: int
    offset: int


_SORT_COLUMNS: dict[str, object] = {
    "updated_at": ReviewItem.updated_at,
    "created_at": ReviewItem.created_at,
    "severity": ReviewItem.severity,
    "confidence": ReviewItem.confidence,
}


class TrustService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_review_items(
        self,
        workspace_id: UUID,
        *,
        status: str | None = None,
        severity: str | None = None,
        kind: str | None = None,
        model_id: UUID | None = None,
        source_document_id: UUID | None = None,
        sort: str = "updated_at",
        sort_dir: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ) -> ReviewPage:
        await self._require_workspace(workspace_id)

        base_query = (
            select(ReviewItem)
            .join(Component, ReviewItem.component_id == Component.id)
            .join(KnowledgeModel, Component.model_id == KnowledgeModel.id)
            .where(KnowledgeModel.workspace_id == workspace_id)
        )

        if status is not None:
            base_query = base_query.where(ReviewItem.status == status)
        if severity is not None:
            base_query = base_query.where(ReviewItem.severity == severity)
        if kind is not None:
            base_query = base_query.where(ReviewItem.kind == kind)
        if model_id is not None:
            base_query = base_query.where(Component.model_id == model_id)
        if source_document_id is not None:
            base_query = base_query.join(
                ComponentSource,
                ComponentSource.component_id == ReviewItem.component_id,
            ).join(
                SourceDocument,
                ComponentSource.source_document_id == SourceDocument.id,
            ).where(
                ComponentSource.source_document_id == source_document_id,
                SourceDocument.deleted_at.is_(None),
            )

        # Total count (without pagination)
        count_q = select(func.count()).select_from(base_query.subquery())
        total_result = await self.session.execute(count_q)
        total = total_result.scalar() or 0

        # Fetch paginated items
        query = base_query.options(
            selectinload(ReviewItem.component).selectinload(Component.model),
            selectinload(ReviewItem.component).selectinload(Component.source_documents),
            selectinload(ReviewItem.decision_history),
        )

        # Apply sorting
        sort_col = _SORT_COLUMNS.get(sort, ReviewItem.updated_at)
        if sort_dir == "asc":
            query = query.order_by(sort_col.asc(), ReviewItem.id.asc())
        else:
            query = query.order_by(sort_col.desc(), ReviewItem.id.desc())

        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        items = list(result.unique().scalars().all())
        return ReviewPage(items=items, total=total, limit=limit, offset=offset)

    async def get_review_summary(
        self,
        workspace_id: UUID,
    ) -> dict[str, object]:
        """Return review state summary for operator dashboard."""
        await self._require_workspace(workspace_id)

        subq = (
            select(ReviewItem)
            .join(Component, ReviewItem.component_id == Component.id)
            .join(KnowledgeModel, Component.model_id == KnowledgeModel.id)
            .where(KnowledgeModel.workspace_id == workspace_id)
        ).subquery()

        # By status
        status_rows = await self.session.execute(
            select(subq.c.status, func.count())
            .group_by(subq.c.status)
        )
        status_counts = dict(status_rows.all())

        # By severity
        severity_rows = await self.session.execute(
            select(subq.c.severity, func.count())
            .group_by(subq.c.severity)
        )
        severity_counts = dict(severity_rows.all())

        # By kind
        kind_rows = await self.session.execute(
            select(subq.c.kind, func.count())
            .group_by(subq.c.kind)
        )
        kind_counts = dict(kind_rows.all())

        total = sum(status_counts.values())
        actionable = status_counts.get("needs_review", 0)

        return {
            "total": total,
            "actionable": actionable,
            "by_status": {
                "needs_review": status_counts.get("needs_review", 0),
                "approved": status_counts.get("approved", 0),
                "rejected": status_counts.get("rejected", 0),
                "superseded": status_counts.get("superseded", 0),
            },
            "by_severity": {
                "high": severity_counts.get("high", 0),
                "medium": severity_counts.get("medium", 0),
                "low": severity_counts.get("low", 0),
            },
            "by_kind": {
                "review_item": kind_counts.get("review_item", 0),
                "conflict": kind_counts.get("conflict", 0),
                "low_confidence": kind_counts.get("low_confidence", 0),
                "fact_update": kind_counts.get("fact_update", 0),
                "superseded_fact": kind_counts.get("superseded_fact", 0),
            },
        }

    async def get_review_item(self, review_item_id: UUID) -> ReviewItem:
        item = await self.session.scalar(
            select(ReviewItem)
            .where(ReviewItem.id == review_item_id)
            .options(
                selectinload(ReviewItem.component).selectinload(Component.model),
                selectinload(ReviewItem.component).selectinload(Component.source_documents),
                selectinload(ReviewItem.decision_history),
            )
            .execution_options(populate_existing=True)
        )
        if item is None:
            raise TrustResourceNotFoundError("Review item not found")
        return item

    async def get_review_item_for_workspace(
        self,
        review_item_id: UUID,
        workspace_id: UUID,
    ) -> ReviewItem:
        await self._require_workspace(workspace_id)
        item = await self.session.scalar(
            select(ReviewItem)
            .join(Component, ReviewItem.component_id == Component.id)
            .join(KnowledgeModel, Component.model_id == KnowledgeModel.id)
            .where(
                ReviewItem.id == review_item_id,
                KnowledgeModel.workspace_id == workspace_id,
            )
            .options(
                selectinload(ReviewItem.component).selectinload(Component.model),
                selectinload(ReviewItem.component).selectinload(Component.source_documents),
                selectinload(ReviewItem.decision_history),
            )
            .execution_options(populate_existing=True)
        )
        if item is None:
            raise TrustResourceNotFoundError("Review item not found")
        return item

    async def _validate_transition(
        self, current: str, target: str
    ) -> None:
        """Raise InvalidStatusTransitionError if the transition is not allowed."""
        allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            raise InvalidStatusTransitionError(current, target)

    async def approve_review_item(self, review_item_id: UUID, workspace_id: UUID) -> ReviewItem:
        item = await self.get_review_item_for_workspace(review_item_id, workspace_id)
        await self._validate_transition(item.status, "approved")
        previous_status = item.status
        item.status = "approved"
        component = item.component
        if component is not None:
            component.is_stale = False
            component.last_verified_at = datetime.now(timezone.utc)
        await self._record_review_decision(
            item,
            previous_status=previous_status,
            new_status=item.status,
            actor_type="operator",
            note="Review item approved via operator API.",
        )
        await self.session.commit()
        return await self.get_review_item_for_workspace(review_item_id, workspace_id)

    async def reject_review_item(self, review_item_id: UUID, workspace_id: UUID) -> ReviewItem:
        item = await self.get_review_item_for_workspace(review_item_id, workspace_id)
        await self._validate_transition(item.status, "rejected")
        previous_status = item.status
        item.status = "rejected"
        component = item.component
        if component is not None:
            component.is_stale = True
            # Mark as historical so it is excluded from current-truth views
            if component.valid_to is None:
                component.valid_to = datetime.now(timezone.utc)
        await self._record_review_decision(
            item,
            previous_status=previous_status,
            new_status=item.status,
            actor_type="operator",
            note="Review item rejected via operator API.",
        )
        await self.session.commit()
        return await self.get_review_item_for_workspace(review_item_id, workspace_id)

    async def supersede_review_item(self, review_item_id: UUID, workspace_id: UUID) -> ReviewItem:
        item = await self.get_review_item_for_workspace(review_item_id, workspace_id)
        await self._validate_transition(item.status, "superseded")
        previous_status = item.status
        item.status = "superseded"
        component = item.component
        if component is not None:
            component.is_stale = True
            if component.valid_to is None:
                component.valid_to = datetime.now(timezone.utc)
        await self._record_review_decision(
            item,
            previous_status=previous_status,
            new_status=item.status,
            actor_type="operator",
            note="Review item superseded via operator API.",
        )
        await self.session.commit()
        return await self.get_review_item_for_workspace(review_item_id, workspace_id)

    async def list_component_sources(
        self,
        component_id: UUID,
        workspace_id: UUID,
    ) -> list[tuple[ComponentSource, SourceDocument]]:
        await self._require_workspace(workspace_id)

        component = await self.session.scalar(
            select(Component)
            .join(KnowledgeModel, Component.model_id == KnowledgeModel.id)
            .where(
                Component.id == component_id,
                KnowledgeModel.workspace_id == workspace_id,
            )
        )
        if component is None:
            raise TrustResourceNotFoundError("Component not found")

        connector_ids_q = select(Connector.id).where(Connector.workspace_id == workspace_id)
        rows = await self.session.execute(
            select(ComponentSource, SourceDocument)
            .join(
                SourceDocument,
                ComponentSource.source_document_id == SourceDocument.id,
            )
            .where(
                ComponentSource.component_id == component_id,
                SourceDocument.connector_id.in_(connector_ids_q),
                SourceDocument.deleted_at.is_(None),
            )
            .order_by(SourceDocument.ingested_at.desc(), SourceDocument.id.desc())
        )
        return list(rows.all())

    async def list_source_document_components(
        self, document_id: UUID, workspace_id: UUID
    ) -> list[tuple[Component, KnowledgeModel, ReviewItem | None]]:
        await self._get_source_document_for_workspace(document_id, workspace_id)

        rows = await self.session.execute(
            select(Component, KnowledgeModel, ReviewItem)
            .options(selectinload(ReviewItem.decision_history))
            .join(ComponentSource, ComponentSource.component_id == Component.id)
            .join(KnowledgeModel, Component.model_id == KnowledgeModel.id)
            .outerjoin(ReviewItem, ReviewItem.component_id == Component.id)
            .where(
                ComponentSource.source_document_id == document_id,
                KnowledgeModel.workspace_id == workspace_id,
            )
            .order_by(KnowledgeModel.name.asc(), Component.name.asc())
        )
        return list(rows.all())

    async def _record_review_decision(
        self,
        item: ReviewItem,
        *,
        previous_status: str | None,
        new_status: str,
        actor_type: str,
        note: str | None,
    ) -> None:
        if previous_status == new_status:
            return
        self.session.add(
            ReviewDecision(
                review_item_id=item.id,
                previous_status=previous_status,
                new_status=new_status,
                actor_type=actor_type,
                note=note,
            )
        )
        await self.session.flush()

    async def queue_document_reprocess(
        self, document_id: UUID, workspace_id: UUID
    ) -> SyncJob:
        document = await self._get_source_document_for_workspace(document_id, workspace_id)
        connector = await self.session.get(Connector, document.connector_id)
        if connector is None:
            raise TrustResourceNotFoundError("Connector not found")

        existing = await self.session.scalar(
            select(SyncJob).where(
                SyncJob.connector_id == connector.id,
                SyncJob.status.in_([SyncJobStatus.PENDING, SyncJobStatus.RUNNING]),
            )
        )
        if existing is not None:
            raise JobInProgressError(existing.id)

        previous_processed_at = document.processed_at
        job = SyncJob(
            connector_id=connector.id,
            job_type="reprocess",
            status=SyncJobStatus.PENDING,
            result_metadata={
                "trigger": "reprocess",
                "document_id": str(document_id),
            },
        )
        document.processed_at = None
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)

        try:
            from app.tasks.ingestion import run_ingestion

            task_result = run_ingestion.delay(str(job.id), str(document_id))
            job.celery_task_id = task_result.id
            await self.session.commit()
            await self.session.refresh(job)
        except Exception as dispatch_exc:
            job.status = SyncJobStatus.FAILED
            job.error_type = "DispatchError"
            job.error_message = str(dispatch_exc)
            document.processed_at = previous_processed_at
            await self.session.commit()
            raise DispatchError(
                f"Failed to dispatch reprocess task: {dispatch_exc}"
            ) from dispatch_exc

        return job

    async def _require_workspace(self, workspace_id: UUID) -> None:
        workspace = await self.session.scalar(
            select(Workspace.id).where(Workspace.id == workspace_id)
        )
        if workspace is None:
            raise WorkspaceNotFoundError("Workspace not found")

    async def _get_source_document_for_workspace(
        self, document_id: UUID, workspace_id: UUID
    ) -> SourceDocument:
        await self._require_workspace(workspace_id)

        connector_ids_q = select(Connector.id).where(
            Connector.workspace_id == workspace_id
        )
        document = await self.session.scalar(
            select(SourceDocument).where(
                SourceDocument.id == document_id,
                SourceDocument.connector_id.in_(connector_ids_q),
                SourceDocument.deleted_at.is_(None),
            )
        )
        if document is None:
            raise TrustResourceNotFoundError("Source document not found")
        return document
