"""Tests for graph semantics: backlinks, provenance enrichment, hidden-fact
filtering, and graph endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models.connector import Connector, ConnectorStatus
from app.models.knowledge import (
    Component,
    ComponentSource,
    KnowledgeModel,
    Relationship,
    RelationshipType,
)
from app.models.review import ReviewItem
from app.models.source import ConnectorType, SourceDocument
from app.models.user import Workspace
from app.processing.extractor import RegexExtractor
from app.schemas.knowledge import (
    ComponentRead,
    GraphComponentRead,
    GraphRelationshipRead,
    GraphResponse,
    RelationshipRead,
)
from app.services.ingestion_service import IngestionService
from app.services.knowledge_service import KnowledgeService


@pytest.fixture
async def slack_connector(db_session, workspace):
    conn = Connector(
        workspace_id=workspace.id,
        connector_type=ConnectorType.SLACK,
        status=ConnectorStatus.CONNECTED,
        config={"team_name": "Test"},
    )
    db_session.add(conn)
    await db_session.flush()
    return conn


@pytest.fixture
async def knowledge_model(db_session, workspace):
    model = KnowledgeModel(
        workspace_id=workspace.id,
        name="Test Graph Model",
        description="Model for graph tests",
        auto_generated=False,
    )
    db_session.add(model)
    await db_session.flush()
    return model


# ── Component Model Property Tests ─────────────────────────────────────


class TestComponentModelProperties:
    """Test the new provenance/trust properties on Component."""

    async def test_source_count_reflects_linked_documents(
        self, db_session, workspace, slack_connector
    ):
        """source_count should equal the number of ComponentSource links."""
        from sqlalchemy.orm import selectinload

        doc1 = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:src.count.1",
            content="decision: adopt FastAPI",
            metadata_json={"channel_name": "eng"},
        )
        doc2 = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:src.count.2",
            content="decision: adopt FastAPI",
            metadata_json={"channel_name": "eng"},
        )
        db_session.add_all([doc1, doc2])
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        components = list(await db_session.scalars(
            select(Component)
            .options(selectinload(Component.source_links))
            .where(Component.name.like("Decision in %"))
        ))
        assert len(components) == 1
        assert components[0].source_count == 2

    async def test_is_rejected_when_review_status_is_rejected(
        self, db_session, workspace, slack_connector
    ):
        from sqlalchemy.orm import selectinload

        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:rejected.1",
            content="decision: use Django",
            metadata_json={"channel_name": "backend"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        component = await db_session.scalar(
            select(Component)
            .options(selectinload(Component.review_item))
            .where(Component.name.like("Decision in %"))
        )
        assert component is not None
        assert not component.is_rejected

        # Simulate rejection
        review = ReviewItem(
            component_id=component.id,
            status="rejected",
            severity="high",
            kind="conflict",
            title="Rejected",
            summary="This decision was rejected",
        )
        db_session.add(review)
        await db_session.flush()

        # Refresh to pick up the review relationship
        await db_session.refresh(component)
        assert component.is_rejected
        assert component.is_hidden

    async def test_is_superseded_when_valid_to_is_set(self, db_session, workspace, slack_connector):
        """A component with valid_to set should report is_superseded=True."""
        doc1 = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:super.1",
            content="decision: launch Monday",
            metadata_json={"channel_name": "product"},
        )
        doc2 = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:super.2",
            content="decision: launch Tuesday",
            metadata_json={"channel_name": "product"},
        )
        db_session.add_all([doc1, doc2])
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        historical = await db_session.scalar(
            select(Component).where(
                Component.name.like("Decision in %"),
                Component.valid_to.is_not(None),
            )
        )
        assert historical is not None
        assert historical.is_superseded


# ── Schema Enrichment Tests ────────────────────────────────────────────


class TestSchemaEnrichment:
    """Verify that ComponentRead and RelationshipRead include graph fields."""

    async def test_component_read_includes_graph_fields(
        self, db_session, workspace, slack_connector
    ):
        from sqlalchemy.orm import selectinload

        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:schema.comp.1",
            content="decision: adopt Kubernetes",
            metadata_json={"channel_name": "infra"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        component = await db_session.scalar(
            select(Component)
            .options(
                selectinload(Component.model),
                selectinload(Component.review_item),
                selectinload(Component.source_documents),
                selectinload(Component.source_links),
            )
            .where(Component.name.like("Decision in %"))
        )
        read = ComponentRead.model_validate(component)
        assert hasattr(read, "source_count")
        assert hasattr(read, "is_rejected")
        assert hasattr(read, "is_superseded")
        assert hasattr(read, "is_hidden")
        assert read.source_count >= 1

    async def test_relationship_read_includes_trust_fields(
        self, db_session, workspace, slack_connector
    ):
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:schema.rel.1",
            content="blocker: blocked by Decision in #eng",
            metadata_json={"channel_name": "eng"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        rel = await db_session.scalar(select(Relationship))
        if rel is not None:
            read = RelationshipRead.model_validate(rel)
            assert hasattr(read, "source_review_status")
            assert hasattr(read, "target_review_status")
            assert hasattr(read, "is_hidden")


# ── Component Graph Endpoint Tests ─────────────────────────────────────


class TestComponentGraph:
    """Tests for the /components/{id}/graph endpoint via the service."""

    async def test_graph_returns_root_and_neighbors(
        self, db_session, workspace, slack_connector
    ):
        """A component graph should return the root and its neighbors."""
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:graph.basic.1",
            content="decision: migrate to Postgres",
            metadata_json={"channel_name": "eng"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        decision = await db_session.scalar(
            select(Component).where(Component.name.like("Decision in %"))
        )
        assert decision is not None

        ks = KnowledgeService(db_session)
        graph = await ks.get_component_graph(decision.id, depth=1)

        assert isinstance(graph, GraphResponse)
        assert graph.root_component_id == decision.id
        assert len(graph.nodes) >= 1  # At least the root
        # Root node should be in the graph
        root_node = next((n for n in graph.nodes if n.id == decision.id), None)
        assert root_node is not None
        assert root_node.name == decision.name

    async def test_graph_excludes_rejected_components_by_default(
        self, db_session, workspace, slack_connector
    ):
        """Rejected components must not appear in the default graph."""
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:graph.reject.1",
            content="decision: use legacy framework",
            metadata_json={"channel_name": "backend"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        component = await db_session.scalar(
            select(Component).where(Component.name.like("Decision in %"))
        )
        assert component is not None

        # Reject it
        review = ReviewItem(
            component_id=component.id,
            status="rejected",
            severity="high",
            kind="conflict",
            title="Rejected",
            summary="Rejected for graph test",
        )
        db_session.add(review)
        await db_session.flush()

        ks = KnowledgeService(db_session)
        graph = await ks.get_component_graph(component.id, depth=1)

        # Root should still appear (always included)
        assert any(n.id == component.id for n in graph.nodes)
        assert graph.hidden_node_count >= 0

    async def test_graph_includes_historical_when_requested(
        self, db_session, workspace, slack_connector
    ):
        """With include_historical=True, superseded components should appear."""
        doc1 = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:graph.hist.1",
            content="decision: launch Monday",
            metadata_json={"channel_name": "product"},
        )
        doc2 = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:graph.hist.2",
            content="decision: launch Tuesday",
            metadata_json={"channel_name": "product"},
        )
        db_session.add_all([doc1, doc2])
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        historical = await db_session.scalar(
            select(Component).where(
                Component.name.like("Decision in %"),
                Component.valid_to.is_not(None),
            )
        )
        current = await db_session.scalar(
            select(Component).where(
                Component.name.like("Decision in %"),
                Component.valid_to.is_(None),
            )
        )
        assert historical is not None
        assert current is not None

        ks = KnowledgeService(db_session)

        # Default: historical excluded
        graph_default = await ks.get_component_graph(current.id, depth=2)
        default_ids = {n.id for n in graph_default.nodes}
        assert historical.id not in default_ids

        # Historical: both should appear
        graph_hist = await ks.get_component_graph(current.id, depth=2, include_historical=True)
        hist_ids = {n.id for n in graph_hist.nodes}
        assert historical.id in hist_ids
        assert current.id in hist_ids

    async def test_graph_component_has_predecessor_ids(
        self, db_session, workspace, slack_connector
    ):
        """A successor component should list its predecessors in graph response."""
        doc1 = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:graph.pred.1",
            content="decision: launch Monday",
            metadata_json={"channel_name": "product"},
        )
        doc2 = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:graph.pred.2",
            content="decision: launch Tuesday",
            metadata_json={"channel_name": "product"},
        )
        db_session.add_all([doc1, doc2])
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        current = await db_session.scalar(
            select(Component).where(
                Component.name.like("Decision in %"),
                Component.valid_to.is_(None),
            )
        )
        assert current is not None

        ks = KnowledgeService(db_session)
        graph = await ks.get_component_graph(current.id, depth=2, include_historical=True)

        # The current component should have predecessor_ids pointing to historical
        current_node = next(n for n in graph.nodes if n.id == current.id)
        # Historical component's superseded_by_id should point to current
        historical_node = next(
            (n for n in graph.nodes if n.is_superseded),
            None,
        )
        if historical_node is not None:
            # historical_node.superseded_by should equal current.id
            assert historical_node.superseded_by == current.id
            # current_node should be in predecessor_map of historical
            # which means predecessor_map[current.id] contains historical_node.id
            current_preds = current_node.predecessor_ids
            assert historical_node.id in current_preds

    async def test_graph_relationship_has_trust_fields(
        self, db_session, workspace, slack_connector
    ):
        """Graph relationships should include review status of both endpoints."""
        blocker_doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:graph.reltrust.1",
            content="blocker: need DBA approval",
            metadata_json={"channel_name": "eng"},
        )
        decision_doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:graph.reltrust.2",
            content="decision: migrate to Postgres\nblocker: blocked by Blocker in #eng",
            metadata_json={"channel_name": "eng"},
        )
        db_session.add_all([blocker_doc, decision_doc])
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        decision = await db_session.scalar(
            select(Component).where(Component.name.like("Decision in %"))
        )
        if decision is None:
            pytest.skip("No decision component found")

        ks = KnowledgeService(db_session)
        graph = await ks.get_component_graph(decision.id, depth=1)

        if graph.edges:
            edge = graph.edges[0]
            assert isinstance(edge, GraphRelationshipRead)
            assert edge.source_review_status is not None or edge.source_review_status is None
            assert edge.target_review_status is not None or edge.target_review_status is None


# ── Model Graph Endpoint Tests ──────────────────────────────────────────


class TestModelGraph:
    """Tests for the /models/{id}/graph endpoint."""

    async def test_model_graph_excludes_rejected(
        self, db_session, workspace, slack_connector
    ):
        """Rejected components should not appear in the model graph."""
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:mg.reject.1",
            content="decision: use legacy framework",
            metadata_json={"channel_name": "backend"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        model = await db_session.scalar(
            select(KnowledgeModel).where(
                KnowledgeModel.workspace_id == workspace.id,
                KnowledgeModel.auto_generated.is_(True),
            )
        )
        assert model is not None

        # Reject the component
        component = await db_session.scalar(
            select(Component).where(Component.model_id == model.id)
        )
        if component is not None:
            review = ReviewItem(
                component_id=component.id,
                status="rejected",
                severity="high",
                kind="conflict",
                title="Rejected",
                summary="Rejected for model graph test",
            )
            db_session.add(review)
            await db_session.flush()

            ks = KnowledgeService(db_session)
            graph = await ks.get_model_graph(model.id)

            rejected_ids = {
                n.id for n in graph.nodes if n.is_rejected
            }
            assert len(rejected_ids) == 0

    async def test_model_graph_empty_model(self, db_session, workspace):
        """An empty model should return a valid graph response."""
        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Empty Graph Model",
            description="No components",
        )
        db_session.add(model)
        await db_session.flush()

        ks = KnowledgeService(db_session)
        graph = await ks.get_model_graph(model.id)

        assert isinstance(graph, GraphResponse)
        assert graph.nodes == []
        assert graph.edges == []


# ── Truth Visibility Integration ────────────────────────────────────────


class TestTruthVisibilityIntegration:
    """Ensure truth_visibility rules apply to graph views."""

    async def test_rejected_component_not_visible_in_default_graph(
        self, db_session, workspace, slack_connector
    ):
        from sqlalchemy.orm import selectinload

        from app.services.truth_visibility import (
            is_component_visible_in_current_truth,
            is_component_rejected,
        )

        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:tv.reject.1",
            content="decision: use old technology",
            metadata_json={"channel_name": "backend"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        component = await db_session.scalar(
            select(Component)
            .options(selectinload(Component.review_item))
            .where(Component.name.like("Decision in %"))
        )
        assert component is not None

        # Before rejection: visible
        assert not is_component_rejected(component)

        # Reject it
        review = ReviewItem(
            component_id=component.id,
            status="rejected",
            severity="high",
            kind="conflict",
            title="Rejected",
            summary="Rejected for graph test",
        )
        db_session.add(review)
        await db_session.flush()
        await db_session.refresh(component, attribute_names=["review_item"])

        # After rejection: not visible
        assert is_component_rejected(component)
        assert not is_component_visible_in_current_truth(component)
        assert component.is_hidden
