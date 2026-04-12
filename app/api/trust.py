"""Trust/operator endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.schemas.connector import SyncJobResponse
from app.schemas.review import (
    ComponentSourceRead,
    ReviewDecisionRead,
    ReviewItemRead,
    ReviewKind,
    ReviewStatus,
    ReviewSeverity,
    SourceDocumentComponentRead,
)
from app.services.trust_service import (
    DispatchError,
    InvalidStatusTransitionError,
    JobInProgressError,
    TrustResourceNotFoundError,
    TrustService,
    WorkspaceNotFoundError,
)


router = APIRouter()


def get_trust_service(session: AsyncSession = Depends(get_db_session)) -> TrustService:
    return TrustService(session)


def _serialize_source_document_ref(document) -> dict[str, object]:
    return {
        "id": document.id,
        "label": document.label,
        "connector_type": document.connector_type.value,
    }


def _serialize_review_item(item) -> ReviewItemRead:
    component = item.component
    model = component.model if component is not None else None
    source_documents = (
        sorted(
            component.source_documents,
            key=lambda document: str(_serialize_source_document_ref(document)["label"]),
        )
        if component is not None
        else []
    )
    return ReviewItemRead(
        id=item.id,
        status=item.status,
        severity=item.severity,
        kind=item.kind,
        title=item.title,
        summary=item.summary,
        confidence=item.confidence,
        last_seen_at=item.updated_at,
        model_id=model.id if model is not None else None,
        model_name=model.name if model is not None else None,
        sources=[ref["label"] for ref in map(_serialize_source_document_ref, source_documents)],
        source_documents=[
            _serialize_source_document_ref(document)
            for document in source_documents
        ],
        rationale=item.rationale,
        suggested_action=item.suggested_action,
        decision_history=[
            ReviewDecisionRead(
                id=decision.id,
                previous_status=decision.previous_status,
                new_status=decision.new_status,
                actor_type=decision.actor_type,
                note=decision.note,
                created_at=decision.created_at,
            )
            for decision in item.decision_history
        ],
    )


@router.get("/review-items", response_model=list[ReviewItemRead])
async def list_review_items(
    workspace_id: UUID,
    review_status: ReviewStatus | None = Query(default=None, alias="status"),
    severity: ReviewSeverity | None = None,
    kind: ReviewKind | None = None,
    source_document_id: UUID | None = None,
    service: TrustService = Depends(get_trust_service),
) -> list[ReviewItemRead]:
    try:
        items = await service.list_review_items(
            workspace_id,
            status=review_status,
            severity=severity,
            kind=kind,
            source_document_id=source_document_id,
        )
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    return [_serialize_review_item(item) for item in items]


@router.post("/review-items/{review_item_id}/approve", response_model=ReviewItemRead)
async def approve_review_item(
    review_item_id: UUID,
    workspace_id: UUID,
    service: TrustService = Depends(get_trust_service),
) -> ReviewItemRead:
    try:
        item = await service.approve_review_item(review_item_id, workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    except TrustResourceNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Review item not found",
        )
    except InvalidStatusTransitionError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return _serialize_review_item(item)


@router.post("/review-items/{review_item_id}/reject", response_model=ReviewItemRead)
async def reject_review_item(
    review_item_id: UUID,
    workspace_id: UUID,
    service: TrustService = Depends(get_trust_service),
) -> ReviewItemRead:
    try:
        item = await service.reject_review_item(review_item_id, workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    except TrustResourceNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Review item not found",
        )
    except InvalidStatusTransitionError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return _serialize_review_item(item)


@router.post("/review-items/{review_item_id}/supersede", response_model=ReviewItemRead)
async def supersede_review_item(
    review_item_id: UUID,
    workspace_id: UUID,
    service: TrustService = Depends(get_trust_service),
) -> ReviewItemRead:
    try:
        item = await service.supersede_review_item(review_item_id, workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    except TrustResourceNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Review item not found",
        )
    except InvalidStatusTransitionError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return _serialize_review_item(item)


@router.get(
    "/components/{component_id}/sources",
    response_model=list[ComponentSourceRead],
)
async def list_component_sources(
    component_id: UUID,
    workspace_id: UUID,
    service: TrustService = Depends(get_trust_service),
) -> list[ComponentSourceRead]:
    try:
        rows = await service.list_component_sources(component_id, workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    except TrustResourceNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Component not found",
        )

    return [
        ComponentSourceRead(
            id=document.id,
            connector_type=document.connector_type.value,
            external_id=document.external_id,
            label=_serialize_source_document_ref(document)["label"],
            author=document.author,
            source_url=document.source_url,
            created_at_source=document.created_at_source,
            ingested_at=document.ingested_at,
            processed_at=document.processed_at,
            deleted_at=document.deleted_at,
            extraction_context=link.extraction_context,
            extractor_name=link.extractor_name,
            extractor_kind=link.extractor_kind,
            extractor_schema_version=link.extractor_schema_version,
        )
        for link, document in rows
    ]


@router.get(
    "/source-documents/{document_id}/components",
    response_model=list[SourceDocumentComponentRead],
)
async def list_source_document_components(
    document_id: UUID,
    workspace_id: UUID,
    service: TrustService = Depends(get_trust_service),
) -> list[SourceDocumentComponentRead]:
    try:
        rows = await service.list_source_document_components(document_id, workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    except TrustResourceNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Source document not found",
        )

    return [
        SourceDocumentComponentRead(
            id=component.id,
            model_id=model.id,
            model_name=model.name,
            name=component.name,
            value=component.value,
            confidence=component.confidence,
            valid_from=component.valid_from,
            valid_to=component.valid_to,
            superseded_by=component.superseded_by,
            review_status=review_item.status if review_item is not None else None,
            review_item_id=review_item.id if review_item is not None else None,
            review_summary=review_item.summary if review_item is not None else None,
            decision_history=[
                ReviewDecisionRead(
                    id=decision.id,
                    previous_status=decision.previous_status,
                    new_status=decision.new_status,
                    actor_type=decision.actor_type,
                    note=decision.note,
                    created_at=decision.created_at,
                )
                for decision in (review_item.decision_history if review_item is not None else [])
            ],
            temporal_state=component.temporal_state,
            is_stale=component.is_stale,
        )
        for component, model, review_item in rows
    ]


@router.post(
    "/source-documents/{document_id}/reprocess",
    response_model=SyncJobResponse,
    status_code=http_status.HTTP_202_ACCEPTED,
)
async def reprocess_source_document(
    document_id: UUID,
    workspace_id: UUID,
    service: TrustService = Depends(get_trust_service),
) -> SyncJobResponse:
    try:
        job = await service.queue_document_reprocess(document_id, workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    except TrustResourceNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Source document not found",
        )
    except JobInProgressError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except DispatchError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )

    return SyncJobResponse(
        job_id=job.id,
        job_type=job.job_type,
        connector_id=job.connector_id,
        status=job.status.value,
        created_at=job.created_at,
    )
