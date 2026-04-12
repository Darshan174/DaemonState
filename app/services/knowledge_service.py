from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
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
from app.processing.embedder import BaseEmbedder, build_default_embedder
from app.schemas.knowledge import (
    GraphComponentRead,
    GraphRelationshipRead,
    GraphResponse,
)
from app.services.truth_visibility import history_where


class KnowledgeServiceError(Exception):
    """Base knowledge service error."""


class ResourceNotFoundError(KnowledgeServiceError):
    """Raised when a requested record is not present."""


class ResourceConflictError(KnowledgeServiceError):
    """Raised when a write violates a uniqueness or integrity rule."""


class InvalidRequestError(KnowledgeServiceError):
    """Raised when a request is semantically invalid."""


class KnowledgeService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        embedder: BaseEmbedder | None = None,
    ) -> None:
        self.session = session
        self._embedder = embedder or build_default_embedder()

    async def create_model(self, **payload: object) -> KnowledgeModel:
        workspace_id = payload["workspace_id"]
        if not await self._workspace_exists(workspace_id):
            raise ResourceNotFoundError("Workspace not found")

        knowledge_model = KnowledgeModel(**payload)
        self.session.add(knowledge_model)
        await self._commit_or_raise(
            "A knowledge model with this name already exists in the workspace"
        )
        await self.session.refresh(knowledge_model)
        return knowledge_model

    async def list_models_for_workspace(self, workspace_id: UUID) -> list[KnowledgeModel]:
        if not await self._workspace_exists(workspace_id):
            raise ResourceNotFoundError("Workspace not found")

        result = await self.session.scalars(
            select(KnowledgeModel)
            .where(KnowledgeModel.workspace_id == workspace_id)
            .order_by(KnowledgeModel.name.asc())
        )
        return list(result)

    async def get_model(self, model_id: UUID) -> KnowledgeModel:
        result = await self.session.scalar(self._model_select(model_id))
        if result is None:
            raise ResourceNotFoundError("Knowledge model not found")
        return result

    async def get_component(self, component_id: UUID) -> Component:
        component = await self.session.scalar(
            select(Component)
            .options(
                selectinload(Component.source_documents),
                selectinload(Component.review_item).selectinload(ReviewItem.decision_history),
                selectinload(Component.model),
            )
            .where(Component.id == component_id)
        )
        if component is None:
            raise ResourceNotFoundError("Component not found")
        return component

    async def add_component(self, model_id: UUID, **payload: object) -> Component:
        model = await self.get_model(model_id)
        payload.setdefault(
            "embedding",
            await self._embedder.embed_text(
                f"{payload['name']}\n{payload['value']}"
            ),
        )
        component = Component(model_id=model.id, **payload)
        self.session.add(component)
        await self._commit_or_raise("Unable to create component with the provided data")
        return await self.get_component(component.id)

    async def update_component(self, component_id: UUID, **payload: object) -> Component:
        component = await self._get_component(component_id)
        should_refresh_embedding = "name" in payload or "value" in payload
        for field, value in payload.items():
            setattr(component, field, value)
        if should_refresh_embedding:
            component.embedding = await self._embedder.embed_text(
                f"{component.name}\n{component.value}"
            )

        await self._commit_or_raise("Unable to update component with the provided data")
        return await self.get_component(component.id)

    async def delete_component(self, component_id: UUID) -> None:
        component = await self._get_component(component_id)
        await self.session.delete(component)
        await self.session.commit()

    async def create_relationship(self, **payload: object) -> Relationship:
        source_component_id = payload["source_component_id"]
        target_component_id = payload["target_component_id"]
        if source_component_id == target_component_id:
            raise InvalidRequestError("A relationship must connect two different components")

        await self._get_component(source_component_id)
        await self._get_component(target_component_id)

        relationship = Relationship(**payload)
        self.session.add(relationship)
        await self._commit_or_raise("Unable to create relationship with the provided data")
        return await self._get_relationship(relationship.id)

    async def get_model_relationships(self, model_id: UUID) -> list[Relationship]:
        await self.get_model(model_id)
        component_ids = select(Component.id).where(Component.model_id == model_id)

        result = await self.session.scalars(
            select(Relationship)
            .options(
                selectinload(Relationship.source_component),
                selectinload(Relationship.target_component),
            )
            .where(
                or_(
                    Relationship.source_component_id.in_(component_ids),
                    Relationship.target_component_id.in_(component_ids),
                )
            )
            .order_by(Relationship.created_at.desc())
        )
        return list(result)

    async def get_component_relationships(self, component_id: UUID) -> list[Relationship]:
        await self._get_component(component_id)
        result = await self.session.scalars(
            select(Relationship)
            .options(
                selectinload(Relationship.source_component),
                selectinload(Relationship.target_component),
            )
            .where(
                or_(
                    Relationship.source_component_id == component_id,
                    Relationship.target_component_id == component_id,
                )
            )
            .order_by(Relationship.created_at.desc())
        )
        return list(result)

    async def get_neighborhood(
        self,
        component_id: UUID,
        *,
        depth: int = 1,
        include_historical: bool = False,
        relationship_types: list[RelationshipType] | None = None,
    ) -> tuple[list[Component], list[Relationship]]:
        """BFS from a root component, returning the local subgraph.

        Returns (nodes, edges) within `depth` hops of the root.
        The root node is always included even if it is historical.
        """
        root = await self.session.scalar(
            select(Component).where(Component.id == component_id)
        )
        if root is None:
            raise ResourceNotFoundError("Component not found")

        visited_ids: set[UUID] = set()
        frontier: set[UUID] = {component_id}
        all_edge_ids: set[UUID] = set()
        all_edges: list[Relationship] = []

        for _ in range(depth):
            if not frontier:
                break

            stmt = (
                select(Relationship)
                .options(
                    selectinload(Relationship.source_component),
                    selectinload(Relationship.target_component),
                )
                .where(
                    or_(
                        Relationship.source_component_id.in_(frontier),
                        Relationship.target_component_id.in_(frontier),
                    )
                )
            )
            if not include_historical:
                stmt = stmt.where(Relationship.valid_to.is_(None))
            if relationship_types:
                stmt = stmt.where(Relationship.relationship_type.in_(relationship_types))

            edges = list(await self.session.scalars(stmt))

            visited_ids |= frontier
            next_frontier: set[UUID] = set()
            for edge in edges:
                if edge.id not in all_edge_ids:
                    all_edge_ids.add(edge.id)
                    all_edges.append(edge)
                for neighbor_id in (edge.source_component_id, edge.target_component_id):
                    if neighbor_id not in visited_ids:
                        next_frontier.add(neighbor_id)

            frontier = next_frontier

        # Include leaf frontier nodes discovered at final depth
        visited_ids |= frontier

        component_stmt = (
            select(Component)
            .options(
                selectinload(Component.source_links),
                selectinload(Component.review_item),
                selectinload(Component.model),
                selectinload(Component.outgoing_relationships)
                .selectinload(Relationship.target_component)
                .selectinload(Component.review_item),
                selectinload(Component.incoming_relationships)
                .selectinload(Relationship.source_component)
                .selectinload(Component.review_item),
            )
            .where(Component.id.in_(visited_ids))
        )
        if not include_historical:
            # Always keep the root; keep other active (valid_to is None) nodes
            # Exclude rejected and superseded for consistency with current-truth
            component_stmt = component_stmt.where(
                or_(
                    Component.id == component_id,
                    Component.valid_to.is_(None),
                )
            )
            component_stmt = component_stmt.where(
                or_(
                    ~Component.review_item.has(),
                    ~Component.review_item.has(ReviewItem.status.in_(("rejected", "superseded"))),
                )
            )

        nodes = list(await self.session.scalars(component_stmt))
        return nodes, all_edges

    # ── Graph endpoints with provenance / trust ───────────────────

    async def get_component_graph(
        self,
        component_id: UUID,
        *,
        depth: int = 1,
        include_historical: bool = False,
        relationship_types: list[RelationshipType] | None = None,
    ) -> GraphResponse:
        """Return the local subgraph around a component with full provenance.

        Hidden (rejected / superseded) nodes and edges are excluded unless
        ``include_historical`` is True.
        """
        nodes, edges = await self.get_neighborhood(
            component_id,
            depth=depth,
            include_historical=include_historical,
            relationship_types=relationship_types,
        )

        # Build predecessor map: component_id → list of predecessor component_ids
        predecessor_map: dict[UUID, list[UUID]] = {}
        for node in nodes:
            if node.superseded_by_id is not None:
                predecessor_map.setdefault(node.superseded_by_id, []).append(node.id)

        # Build relationship participation map
        rel_participation: dict[UUID, list[UUID]] = {}
        for edge in edges:
            rel_participation.setdefault(edge.source_component_id, []).append(edge.id)
            rel_participation.setdefault(edge.target_component_id, []).append(edge.id)

        # Filter hidden nodes/edges unless include_historical
        visible_nodes = nodes
        visible_edges = edges
        hidden_count = 0
        if not include_historical:
            visible_ids = {n.id for n in nodes if not n.is_hidden}
            # Always keep root
            visible_ids.add(component_id)
            visible_nodes = [n for n in nodes if n.id in visible_ids]
            visible_edges = [
                e
                for e in edges
                if e.source_component_id in visible_ids
                and e.target_component_id in visible_ids
                and not e.is_hidden
            ]
            hidden_count = len(nodes) - len(visible_nodes)

        graph_nodes = [
            self._serialize_graph_component(
                n,
                predecessor_ids=predecessor_map.get(n.id, []),
                relationship_ids=rel_participation.get(n.id, []),
            )
            for n in visible_nodes
        ]
        graph_edges = [self._serialize_graph_relationship(e) for e in visible_edges]

        return GraphResponse(
            root_component_id=component_id,
            nodes=graph_nodes,
            edges=graph_edges,
            include_historical=include_historical,
            hidden_node_count=hidden_count,
        )

    async def get_workspace_graph(
        self,
        workspace_id: UUID,
        *,
        include_historical: bool = False,
        relationship_types: list[RelationshipType] | None = None,
    ) -> GraphResponse:
        """Return the full workspace graph including cross-model edges.

        Rejected components are never included.  Superseded components are
        excluded unless ``include_historical`` is True.
        Cross-model relationships (where both endpoints are visible) are
        included.
        """
        models = await self.list_models_for_workspace(workspace_id)
        if not models:
            return GraphResponse(
                root_component_id=UUID(int=0),
                nodes=[],
                edges=[],
                include_historical=include_historical,
                hidden_node_count=0,
            )

        model_ids = [m.id for m in models]

        # Load all components across all models
        component_stmt = (
            select(Component)
            .options(
                selectinload(Component.source_links),
                selectinload(Component.review_item),
                selectinload(Component.model),
                selectinload(Component.outgoing_relationships)
                .selectinload(Relationship.target_component)
                .selectinload(Component.review_item),
                selectinload(Component.incoming_relationships)
                .selectinload(Relationship.source_component)
                .selectinload(Component.review_item),
            )
            .where(Component.model_id.in_(model_ids))
        )
        if not include_historical:
            component_stmt = component_stmt.where(
                Component.valid_to.is_(None)
            )
            component_stmt = component_stmt.where(
                Component.id.notin_(
                    select(ReviewItem.component_id).where(
                        ReviewItem.status == "rejected"
                    )
                )
            )

        nodes = list(await self.session.scalars(component_stmt))
        node_ids = {n.id for n in nodes}

        # Collect all edges (including cross-model)
        all_edges: list[Relationship] = []
        for node in nodes:
            for rel in node.outgoing_relationships:
                if rel.target_component_id in node_ids:
                    if include_historical or not rel.is_hidden:
                        all_edges.append(rel)

        # Deduplicate
        seen_edge_ids: set[UUID] = set()
        unique_edges: list[Relationship] = []
        for edge in all_edges:
            if edge.id not in seen_edge_ids:
                seen_edge_ids.add(edge.id)
                unique_edges.append(edge)

        # Predecessor map
        predecessor_map: dict[UUID, list[UUID]] = {}
        for node in nodes:
            if node.superseded_by_id is not None:
                predecessor_map.setdefault(node.superseded_by_id, []).append(node.id)

        # Relationship participation map
        rel_participation: dict[UUID, list[UUID]] = {}
        for edge in unique_edges:
            rel_participation.setdefault(edge.source_component_id, []).append(edge.id)
            rel_participation.setdefault(edge.target_component_id, []).append(edge.id)

        graph_nodes = [
            self._serialize_graph_component(
                n,
                predecessor_ids=predecessor_map.get(n.id, []),
                relationship_ids=rel_participation.get(n.id, []),
            )
            for n in nodes
        ]
        graph_edges = [self._serialize_graph_relationship(e) for e in unique_edges]

        return GraphResponse(
            root_component_id=nodes[0].id if nodes else UUID(int=0),
            nodes=graph_nodes,
            edges=graph_edges,
            include_historical=include_historical,
            hidden_node_count=0,
        )

    async def get_model_graph(
        self,
        model_id: UUID,
        *,
        include_historical: bool = False,
        relationship_types: list[RelationshipType] | None = None,
    ) -> GraphResponse:
        """Return the full model graph filtered by visibility.

        Rejected components are never included.  Superseded components are
        excluded unless ``include_historical`` is True.
        """
        await self.get_model(model_id)

        # Build subquery for rejected component IDs
        rejected_subq = (
            select(ReviewItem.component_id)
            .where(ReviewItem.status == "rejected")
            .scalar_subquery()
        )

        # Load all components and relationships for the model
        component_stmt = (
            select(Component)
            .options(
                selectinload(Component.source_links),
                selectinload(Component.review_item),
                selectinload(Component.model),
                selectinload(Component.outgoing_relationships)
                .selectinload(Relationship.target_component)
                .selectinload(Component.review_item),
                selectinload(Component.incoming_relationships)
                .selectinload(Relationship.source_component)
                .selectinload(Component.review_item),
            )
            .where(Component.model_id == model_id)
        )
        if not include_historical:
            component_stmt = component_stmt.where(
                Component.valid_to.is_(None)
            )
            # Exclude rejected components via a NOT IN subquery
            component_stmt = component_stmt.where(
                Component.id.notin_(
                    select(ReviewItem.component_id).where(
                        ReviewItem.status == "rejected"
                    )
                )
            )

        nodes = list(await self.session.scalars(component_stmt))

        node_ids = {n.id for n in nodes}
        all_edges = []
        for node in nodes:
            for rel in node.outgoing_relationships:
                if rel.target_component_id in node_ids:
                    if include_historical or not rel.is_hidden:
                        all_edges.append(rel)
            for rel in node.incoming_relationships:
                if rel.source_component_id in node_ids:
                    if rel not in all_edges:
                        if include_historical or not rel.is_hidden:
                            all_edges.append(rel)

        # Deduplicate edges
        seen_edge_ids: set[UUID] = set()
        unique_edges: list[Relationship] = []
        for edge in all_edges:
            if edge.id not in seen_edge_ids:
                seen_edge_ids.add(edge.id)
                unique_edges.append(edge)

        # Build predecessor map
        predecessor_map: dict[UUID, list[UUID]] = {}
        for node in nodes:
            if node.superseded_by_id is not None:
                predecessor_map.setdefault(node.superseded_by_id, []).append(node.id)

        # Build relationship participation map
        rel_participation: dict[UUID, list[UUID]] = {}
        for edge in unique_edges:
            rel_participation.setdefault(edge.source_component_id, []).append(edge.id)
            rel_participation.setdefault(edge.target_component_id, []).append(edge.id)

        graph_nodes = [
            self._serialize_graph_component(
                n,
                predecessor_ids=predecessor_map.get(n.id, []),
                relationship_ids=rel_participation.get(n.id, []),
            )
            for n in nodes
        ]
        graph_edges = [self._serialize_graph_relationship(e) for e in unique_edges]

        return GraphResponse(
            root_component_id=nodes[0].id if nodes else UUID(int=0),
            nodes=graph_nodes,
            edges=graph_edges,
            include_historical=include_historical,
            hidden_node_count=0,
        )

    # ── Graph serialization helpers ──────────────────────────────

    @staticmethod
    def _serialize_graph_component(
        component: Component,
        *,
        predecessor_ids: list[UUID] | None = None,
        relationship_ids: list[UUID] | None = None,
    ) -> GraphComponentRead:
        return GraphComponentRead(
            id=component.id,
            model_id=component.model_id,
            model_name=component.model_name,
            name=component.name,
            value=component.value,
            confidence=component.confidence,
            authority_source=component.authority_source,
            authority_weight=component.authority_weight,
            valid_from=component.valid_from,
            valid_to=component.valid_to,
            superseded_by=component.superseded_by,
            last_verified_at=component.last_verified_at,
            is_stale=component.is_stale,
            review_status=component.review_status,
            review_summary=component.review_summary,
            temporal_state=component.temporal_state,
            source_count=component.source_count,
            is_rejected=component.is_rejected,
            is_superseded=component.is_superseded,
            is_hidden=component.is_hidden,
            predecessor_ids=predecessor_ids or [],
            relationship_ids=relationship_ids or [],
        )

    @staticmethod
    def _serialize_graph_relationship(
        relationship: Relationship,
    ) -> GraphRelationshipRead:
        return GraphRelationshipRead(
            id=relationship.id,
            source_component_id=relationship.source_component_id,
            source_component_name=relationship.source_component_name,
            target_component_id=relationship.target_component_id,
            target_component_name=relationship.target_component_name,
            relationship_type=relationship.relationship_type,
            sentiment=relationship.sentiment,
            description=relationship.description,
            confidence=relationship.confidence,
            valid_from=relationship.valid_from,
            valid_to=relationship.valid_to,
            temporal_state=relationship.temporal_state,
            source_review_status=relationship.source_review_status,
            target_review_status=relationship.target_review_status,
            is_hidden=relationship.is_hidden,
        )

    async def _get_relationship(self, relationship_id: UUID) -> Relationship:
        relationship = await self.session.scalar(
            select(Relationship)
            .options(
                selectinload(Relationship.source_component),
                selectinload(Relationship.target_component),
            )
            .where(Relationship.id == relationship_id)
        )
        if relationship is None:
            raise ResourceNotFoundError("Relationship not found")
        return relationship

    def _model_select(self, model_id: UUID) -> Select[tuple[KnowledgeModel]]:
        return (
            select(KnowledgeModel)
            .options(
                selectinload(KnowledgeModel.components).selectinload(Component.source_documents),
                selectinload(KnowledgeModel.components)
                .selectinload(Component.review_item)
                .selectinload(ReviewItem.decision_history),
            )
            .where(KnowledgeModel.id == model_id)
        )

    async def _workspace_exists(self, workspace_id: UUID) -> bool:
        return (
            await self.session.scalar(
                select(Workspace.id).where(Workspace.id == workspace_id).limit(1)
            )
            is not None
        )

    async def _get_component(self, component_id: UUID) -> Component:
        component = await self.session.scalar(
            select(Component).where(Component.id == component_id)
        )
        if component is None:
            raise ResourceNotFoundError("Component not found")
        return component

    async def _commit_or_raise(self, message: str) -> None:
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ResourceConflictError(message) from exc
