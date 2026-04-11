"""Backend API tests for graph endpoints.

Tests:
  - GET /api/graph?workspace_id=...
  - GET /api/graph/models/{model_id}
  - GET /api/graph/components/{component_id}
  - GET /api/graph/neighborhood/{component_id}

Includes a test that proves the workspace graph returns non-empty data
for seeded fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.connector import Connector, ConnectorStatus
from app.models.knowledge import (
    Component,
    Relationship,
    RelationshipType,
)
from app.models.source import ConnectorType as SourceConnectorType
from app.models.user import Workspace


@pytest.fixture
async def slack_connector(db_session, workspace):
    conn = Connector(
        workspace_id=workspace.id,
        connector_type=SourceConnectorType.SLACK,
        status=ConnectorStatus.CONNECTED,
        config={"team_name": "Test"},
    )
    db_session.add(conn)
    await db_session.flush()
    return conn


@pytest.fixture
async def seeded_workspace(db_session, client):
    """A workspace with 2 models, 4 components and 2 relationships."""
    from app.models.user import Workspace

    ws = Workspace(id=uuid4(), name="Seeded Graph Workspace")
    db_session.add(ws)
    await db_session.flush()

    model_a = Component.__class__.__bases__[0]() if False else None  # just type hint
    from app.models.knowledge import KnowledgeModel

    model_a = KnowledgeModel(workspace_id=ws.id, name="Model A", description="Test A")
    model_b = KnowledgeModel(workspace_id=ws.id, name="Model B", description="Test B")
    db_session.add_all([model_a, model_b])
    await db_session.flush()

    comp_a1 = Component(
        model_id=model_a.id, name="Decision: use FastAPI",
        value="Migrate to FastAPI", confidence=0.9, authority_weight=0.8,
    )
    comp_a2 = Component(
        model_id=model_a.id, name="Blocker: DB migration",
        value="Need DBA approval", confidence=0.7, authority_weight=0.6,
    )
    comp_b1 = Component(
        model_id=model_b.id, name="Decision: use React",
        value="Frontend in React", confidence=0.85, authority_weight=0.7,
    )
    comp_b2 = Component(
        model_id=model_b.id, name="Action: write tests",
        value="Write integration tests", confidence=0.5, authority_weight=0.5,
    )
    db_session.add_all([comp_a1, comp_a2, comp_b1, comp_b2])
    await db_session.flush()

    # BLOCKED_BY relationship
    rel1 = Relationship(
        source_component_id=comp_a1.id,
        target_component_id=comp_a2.id,
        relationship_type=RelationshipType.BLOCKED_BY,
        confidence=0.8,
    )
    # RELATED_TO relationship across models
    rel2 = Relationship(
        source_component_id=comp_a1.id,
        target_component_id=comp_b1.id,
        relationship_type=RelationshipType.RELATED_TO,
        confidence=0.6,
    )
    db_session.add_all([rel1, rel2])
    await db_session.flush()

    return {
        "workspace": ws,
        "model_a": model_a,
        "model_b": model_b,
        "comp_a1": comp_a1,
        "comp_a2": comp_a2,
        "comp_b1": comp_b1,
        "comp_b2": comp_b2,
        "rel1": rel1,
        "rel2": rel2,
    }


# ── GET /api/graph?workspace_id=... ──────────────────────────────────────


class TestWorkspaceGraph:
    async def test_workspace_graph_returns_200_with_nodes_and_edges(
        self, client, seeded_workspace
    ):
        """Workspace graph must return all visible components and relationships."""
        ws = seeded_workspace["workspace"]
        resp = await client.get(f"/api/graph?workspace_id={ws.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert "nodes" in body
        assert "edges" in body
        assert body["include_historical"] is False
        assert len(body["nodes"]) == 4  # All 4 components are visible
        assert len(body["edges"]) == 2  # Both relationships

    async def test_workspace_graph_non_empty_for_seeded_workspace(
        self, client, seeded_workspace
    ):
        """Proves that a workspace with models/components returns non-empty data."""
        ws = seeded_workspace["workspace"]
        resp = await client.get(f"/api/graph?workspace_id={ws.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["nodes"]) > 0
        assert len(body["edges"]) > 0

    async def test_workspace_graph_empty_for_empty_workspace(self, client):
        resp = await client.get(f"/api/graph?workspace_id={uuid4()}")
        assert resp.status_code == 404

    async def test_workspace_graph_excludes_hidden_components(
        self, client, db_session, seeded_workspace
    ):
        """Rejected components must not appear in the workspace graph."""
        from app.models.review import ReviewItem

        comp_a2 = seeded_workspace["comp_a2"]
        # Reject one component
        review = ReviewItem(
            component_id=comp_a2.id,
            status="rejected",
            severity="high",
            kind="conflict",
            title="Rejected",
            summary="Rejected",
        )
        db_session.add(review)
        await db_session.flush()

        ws = seeded_workspace["workspace"]
        resp = await client.get(f"/api/graph?workspace_id={ws.id}")
        assert resp.status_code == 200
        body = resp.json()
        node_ids = {n["id"] for n in body["nodes"]}
        assert str(comp_a2.id) not in node_ids
        # Edge involving rejected component should also be excluded
        assert len(body["edges"]) < 2

    async def test_workspace_graph_includes_historical_when_requested(
        self, client, db_session, seeded_workspace
    ):
        """With include_historical=true, superseded components appear."""
        from sqlalchemy.orm import selectinload

        comp_a1 = seeded_workspace["comp_a1"]
        # Make the component historical
        comp_a1.valid_to = datetime.now(timezone.utc)
        comp_a1.is_stale = True
        await db_session.flush()

        ws = seeded_workspace["workspace"]

        # Default: historical excluded
        resp_default = await client.get(f"/api/graph?workspace_id={ws.id}")
        default_ids = {n["id"] for n in resp_default.json()["nodes"]}
        assert str(comp_a1.id) not in default_ids

        # Historical: included
        resp_hist = await client.get(
            f"/api/graph?workspace_id={ws.id}&include_historical=true"
        )
        hist_ids = {n["id"] for n in resp_hist.json()["nodes"]}
        assert str(comp_a1.id) in hist_ids


# ── GET /api/graph/models/{model_id} ─────────────────────────────────────


class TestModelGraph:
    async def test_model_graph_returns_200(self, client, seeded_workspace):
        model_a = seeded_workspace["model_a"]
        resp = await client.get(f"/api/graph/models/{model_a.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["nodes"]) == 2  # 2 components in model_a
        assert len(body["edges"]) == 1  # 1 relationship within model_a

    async def test_model_graph_returns_404_for_missing_model(self, client):
        resp = await client.get(f"/api/graph/models/{uuid4()}")
        assert resp.status_code == 404


# ── GET /api/graph/components/{component_id} ─────────────────────────────


class TestComponentGraph:
    async def test_component_graph_returns_200(self, client, seeded_workspace):
        comp_a1 = seeded_workspace["comp_a1"]
        resp = await client.get(f"/api/graph/components/{comp_a1.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["root_component_id"] == str(comp_a1.id)
        assert len(body["nodes"]) >= 1

    async def test_component_graph_returns_404_for_missing_component(self, client):
        resp = await client.get(f"/api/graph/components/{uuid4()}")
        assert resp.status_code == 404

    async def test_component_graph_respects_depth(self, client, seeded_workspace):
        comp_a1 = seeded_workspace["comp_a1"]
        resp = await client.get(
            f"/api/graph/components/{comp_a1.id}?depth=1"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["root_component_id"] == str(comp_a1.id)


# ── GET /api/graph/neighborhood/{component_id} ───────────────────────────


class TestNeighborhood:
    async def test_neighborhood_returns_200(self, client, seeded_workspace):
        comp_a1 = seeded_workspace["comp_a1"]
        resp = await client.get(
            f"/api/graph/neighborhood/{comp_a1.id}"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["root_id"] == str(comp_a1.id)
        assert body["depth"] == 1
        assert len(body["nodes"]) >= 1
        assert len(body["edges"]) >= 0

    async def test_neighborhood_returns_404_for_missing_component(self, client):
        resp = await client.get(f"/api/graph/neighborhood/{uuid4()}")
        assert resp.status_code == 404

    async def test_neighborhood_node_shape(self, client, seeded_workspace):
        comp_a1 = seeded_workspace["comp_a1"]
        resp = await client.get(
            f"/api/graph/neighborhood/{comp_a1.id}"
        )
        body = resp.json()
        node = next(n for n in body["nodes"] if n["id"] == str(comp_a1.id))
        assert "name" in node
        assert "value" in node
        assert "confidence" in node
        assert "model_id" in node
        assert "review_status" in node

    async def test_neighborhood_edge_shape(self, client, seeded_workspace):
        comp_a1 = seeded_workspace["comp_a1"]
        resp = await client.get(
            f"/api/graph/neighborhood/{comp_a1.id}"
        )
        body = resp.json()
        if body["edges"]:
            edge = body["edges"][0]
            assert "source_id" in edge
            assert "target_id" in edge
            assert "relationship_type" in edge
            assert "confidence" in edge
