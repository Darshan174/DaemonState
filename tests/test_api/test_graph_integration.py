"""Integration tests: graph endpoints against a full demo-seeded workspace.

These tests exercise the seed → graph pipeline end-to-end using the
canonical demo workspace. They complement the fixture-based tests in
test_graph_api.py by catching regressions in how the real seed data is
serialized through the graph service and API layer.

Requires PostgreSQL with pgvector running (same as all backend tests).
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select

from app.evals.demo_seed import DEFAULT_WORKSPACE_NAME, seed_demo_workspace
from app.models.knowledge import Component, KnowledgeModel


@pytest.fixture
async def demo_workspace(db_session):
    """Seed the canonical demo workspace and return (workspace_id, models)."""
    result = await seed_demo_workspace(db_session, replace_existing=True)
    assert result.status == "created"

    models = list(
        await db_session.scalars(
            select(KnowledgeModel)
            .where(KnowledgeModel.workspace_id == result.workspace_id)
            .order_by(KnowledgeModel.name.asc())
        )
    )
    assert models, "demo seed must create at least one KnowledgeModel"

    return {"workspace_id": result.workspace_id, "models": models}


@pytest.fixture
async def first_component(db_session, demo_workspace):
    """Return the first component from the first model."""
    model = demo_workspace["models"][0]
    component = await db_session.scalar(
        select(Component).where(Component.model_id == model.id).limit(1)
    )
    assert component is not None, "demo seed must create components"
    return component


# ── Workspace graph ────────────────────────────────────────────────────


class TestDemoWorkspaceGraph:
    async def test_workspace_graph_returns_all_seeded_components(
        self, client, demo_workspace
    ):
        ws_id = demo_workspace["workspace_id"]
        resp = await client.get(f"/api/graph?workspace_id={ws_id}")
        assert resp.status_code == 200
        body = resp.json()

        assert "nodes" in body
        assert "edges" in body
        assert body["include_historical"] is False
        # The demo seed creates 18+ components across 5 models.
        assert len(body["nodes"]) >= 15, (
            f"expected 15+ graph nodes from demo seed, got {len(body['nodes'])}"
        )

    async def test_workspace_graph_nodes_have_required_fields(
        self, client, demo_workspace
    ):
        ws_id = demo_workspace["workspace_id"]
        resp = await client.get(f"/api/graph?workspace_id={ws_id}")
        body = resp.json()

        required_node_keys = {
            "id", "model_id", "name", "value", "confidence",
            "authority_weight", "valid_from", "is_stale",
            "source_count", "temporal_state",
        }
        for node in body["nodes"]:
            missing = required_node_keys - set(node.keys())
            assert not missing, (
                f"node {node.get('name', '?')} missing keys: {missing}"
            )

    async def test_workspace_graph_provenance_counts(
        self, client, demo_workspace
    ):
        """Every seeded component should have at least one source."""
        ws_id = demo_workspace["workspace_id"]
        resp = await client.get(f"/api/graph?workspace_id={ws_id}")
        body = resp.json()

        for node in body["nodes"]:
            assert node["source_count"] >= 1, (
                f"node '{node['name']}' has source_count={node['source_count']} "
                f"— demo seed should attach at least one source to every component"
            )


# ── Model-scoped graph ─────────────────────────────────────────────────


class TestDemoModelGraph:
    async def test_model_graph_scopes_to_single_model(
        self, client, demo_workspace
    ):
        """Model graph must only return components from that model."""
        model = demo_workspace["models"][0]
        resp = await client.get(f"/api/graph/models/{model.id}")
        assert resp.status_code == 200
        body = resp.json()

        assert len(body["nodes"]) >= 1
        model_ids_in_response = {n["model_id"] for n in body["nodes"]}
        assert model_ids_in_response == {str(model.id)}, (
            f"model graph returned nodes from other models: {model_ids_in_response}"
        )


# ── Component neighborhood ─────────────────────────────────────────────


class TestDemoComponentGraph:
    async def test_component_graph_includes_root(
        self, client, first_component
    ):
        resp = await client.get(
            f"/api/graph/components/{first_component.id}"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["root_component_id"] == str(first_component.id)
        root_ids = {n["id"] for n in body["nodes"]}
        assert str(first_component.id) in root_ids

    async def test_neighborhood_returns_stable_shape(
        self, client, first_component
    ):
        resp = await client.get(
            f"/api/graph/neighborhood/{first_component.id}?depth=2"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["root_id"] == str(first_component.id)
        assert body["depth"] == 2
        assert isinstance(body["nodes"], list)
        assert isinstance(body["edges"], list)

        # Node shape check.
        node = body["nodes"][0]
        for key in ("id", "name", "value", "confidence", "model_id",
                    "review_status", "temporal_state", "source_count"):
            assert key in node, f"neighborhood node missing key '{key}'"

    async def test_neighborhood_edges_reference_valid_nodes(
        self, client, first_component
    ):
        resp = await client.get(
            f"/api/graph/neighborhood/{first_component.id}?depth=2"
        )
        body = resp.json()
        node_ids = {n["id"] for n in body["nodes"]}

        for edge in body["edges"]:
            assert edge["source_id"] in node_ids, (
                f"edge source_id {edge['source_id']} not in returned nodes"
            )
            assert edge["target_id"] in node_ids, (
                f"edge target_id {edge['target_id']} not in returned nodes"
            )


# ── Founder workflows against seeded data ──────────────────────────────


class TestDemoFounderWorkflows:
    async def test_founder_brief_returns_for_seeded_workspace(
        self, client, demo_workspace
    ):
        ws_id = demo_workspace["workspace_id"]
        resp = await client.get(
            f"/api/founder-brief?workspace_id={ws_id}"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["workspace_id"] == str(ws_id)

    async def test_decisions_list_non_empty_for_seeded_workspace(
        self, client, demo_workspace
    ):
        ws_id = demo_workspace["workspace_id"]
        resp = await client.get(
            f"/api/decisions?workspace_id={ws_id}"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) >= 1, "demo seed should produce at least one decision"

    async def test_source_documents_present_for_seeded_workspace(
        self, client, demo_workspace
    ):
        ws_id = demo_workspace["workspace_id"]
        resp = await client.get(
            f"/api/source-documents?workspace_id={ws_id}&limit=5"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert len(body["items"]) >= 1, (
            "demo seed should create source documents with provenance"
        )

    async def test_query_returns_source_backed_answer(
        self, client, demo_workspace
    ):
        ws_id = demo_workspace["workspace_id"]
        resp = await client.post(
            "/api/query",
            json={
                "workspace_id": str(ws_id),
                "question": "What is the Starter Plan?",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "answer" in body
        assert "components" in body, "query must return provenance via components"
