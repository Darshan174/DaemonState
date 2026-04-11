from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models.knowledge import RelationshipType
from app.schemas.knowledge import GraphResponse
from app.schemas.graph import GraphEdgeRead, GraphNeighborhoodResponse, GraphNodeRead
from app.services.knowledge_service import KnowledgeService, ResourceNotFoundError


router = APIRouter()


def get_knowledge_service(session: AsyncSession = Depends(get_db_session)) -> KnowledgeService:
    return KnowledgeService(session)


def _merge_graphs(graphs: list[GraphResponse], *, include_historical: bool) -> GraphResponse:
    node_map = {}
    edge_map = {}
    hidden_node_count = 0
    root_component_id = UUID(int=0)

    for graph in graphs:
        if root_component_id.int == 0 and graph.root_component_id.int != 0:
            root_component_id = graph.root_component_id
        hidden_node_count += graph.hidden_node_count
        for node in graph.nodes:
            node_map[node.id] = node
        for edge in graph.edges:
            edge_map[edge.id] = edge

    return GraphResponse(
        root_component_id=root_component_id,
        nodes=list(node_map.values()),
        edges=list(edge_map.values()),
        include_historical=include_historical,
        hidden_node_count=hidden_node_count,
    )


@router.get("/graph", response_model=GraphResponse)
async def get_workspace_graph(
    workspace_id: UUID,
    include_historical: bool = Query(default=False),
    relationship_types: list[RelationshipType] | None = Query(default=None),
    service: KnowledgeService = Depends(get_knowledge_service),
) -> GraphResponse:
    try:
        return await service.get_workspace_graph(
            workspace_id,
            include_historical=include_historical,
            relationship_types=relationship_types,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/graph/models/{model_id}", response_model=GraphResponse)
async def get_model_graph(
    model_id: UUID,
    include_historical: bool = Query(default=False),
    relationship_types: list[RelationshipType] | None = Query(default=None),
    service: KnowledgeService = Depends(get_knowledge_service),
) -> GraphResponse:
    try:
        return await service.get_model_graph(
            model_id,
            include_historical=include_historical,
            relationship_types=relationship_types,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/graph/components/{component_id}", response_model=GraphResponse)
async def get_component_graph(
    component_id: UUID,
    depth: int = Query(default=1, ge=1, le=5),
    include_historical: bool = Query(default=False),
    relationship_types: list[RelationshipType] | None = Query(default=None),
    service: KnowledgeService = Depends(get_knowledge_service),
) -> GraphResponse:
    try:
        return await service.get_component_graph(
            component_id,
            depth=depth,
            include_historical=include_historical,
            relationship_types=relationship_types,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/graph/neighborhood/{node_id}",
    response_model=GraphNeighborhoodResponse,
)
async def get_neighborhood(
    node_id: UUID,
    depth: int = Query(default=1, ge=1, le=5),
    include_historical: bool = Query(default=False),
    relationship_types: list[RelationshipType] | None = Query(default=None),
    service: KnowledgeService = Depends(get_knowledge_service),
) -> GraphNeighborhoodResponse:
    """Return the local-neighborhood subgraph around a component node."""
    try:
        graph = await service.get_component_graph(
            node_id,
            depth=depth,
            include_historical=include_historical,
            relationship_types=relationship_types,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    return GraphNeighborhoodResponse(
        root_id=node_id,
        depth=depth,
        include_historical=include_historical,
        nodes=[
            GraphNodeRead(
                id=node.id,
                name=node.name,
                value=node.value,
                confidence=node.confidence,
                authority_weight=node.authority_weight,
                authority_source=node.authority_source,
                model_id=node.model_id,
                model_name=node.model_name,
                review_status=node.review_status,
                temporal_state=node.temporal_state,
                is_stale=node.is_stale,
                valid_from=node.valid_from,
                valid_to=node.valid_to,
                source_count=node.source_count,
                created_at=node.last_verified_at,
                updated_at=node.last_verified_at,
            )
            for node in graph.nodes
        ],
        edges=[
            GraphEdgeRead(
                id=edge.id,
                source_id=edge.source_component_id,
                target_id=edge.target_component_id,
                relationship_type=edge.relationship_type,
                sentiment=edge.sentiment,
                description=edge.description,
                confidence=edge.confidence,
                temporal_state=edge.temporal_state,
                valid_from=edge.valid_from,
                valid_to=edge.valid_to,
                created_at=edge.valid_from,
            )
            for edge in graph.edges
        ],
    )
