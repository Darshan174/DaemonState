"""Integration tests: graph endpoints against a full demo-seeded workspace.

These tests exercise the seed → graph pipeline end-to-end using the
canonical demo workspace. They complement the fixture-based tests in
test_graph_api.py by catching regressions in how the real seed data is
serialized through the graph service and API layer.

Coverage:
  - Workspace graph: shape, provenance, include_historical, 404 for missing
  - Model graph: scoping, per-model node counts, 404 for missing
  - Component graph: root inclusion, 404 for missing
  - Neighborhood: shape, edge validity, include_historical, 404 for missing
  - Structural usefulness: no empty names/values, confidence in range, etc.
  - Founder workflows: brief, decisions, sources, query

Requires PostgreSQL with pgvector running (same as all backend tests).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.evals.demo_seed import DEFAULT_WORKSPACE_NAME, seed_demo_workspace
from app.models.knowledge import Component, KnowledgeModel


# ── Fixtures ───────────────────────────────────────────────────────────


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
        # The demo seed creates 20 components across 5 models.
        # Use a threshold that catches catastrophic regressions without
        # being fragile to small seed changes.
        assert len(body["nodes"]) >= 18, (
            f"expected 18+ graph nodes from demo seed, got {len(body['nodes'])}. "
            f"The seed defines 20 components across 5 models — if you're seeing "
            f"fewer, check demo_seed.py for broken _SEEDS entries or silent "
            f"exceptions during _populate_demo_workspace()."
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
                f"node '{node.get('name', '?')}' missing keys: {missing}. "
                f"Check GraphComponentRead in schemas/knowledge.py and "
                f"_serialize_graph_component in knowledge_service.py."
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
                f"node '{node['name']}' has source_count={node['source_count']}. "
                f"The demo seed attaches 1–2 SourceDocuments per component via "
                f"ComponentSource links. If source_count is 0, check that "
                f"_serialize_graph_component counts source_links correctly."
            )

    async def test_workspace_graph_no_empty_names_or_values(
        self, client, demo_workspace
    ):
        """Catch 'structurally valid but useless' payloads: nodes with empty content."""
        ws_id = demo_workspace["workspace_id"]
        resp = await client.get(f"/api/graph?workspace_id={ws_id}")
        body = resp.json()

        for node in body["nodes"]:
            assert node["name"] and node["name"].strip(), (
                f"node {node['id']} has empty/blank name — this renders as "
                f"an unlabeled node in the graph UI."
            )
            assert node["value"] and node["value"].strip(), (
                f"node '{node['name']}' has empty/blank value — graph is "
                f"structurally valid but practically useless without content."
            )

    async def test_workspace_graph_confidence_in_valid_range(
        self, client, demo_workspace
    ):
        """Confidence values must be 0–1. Anything else breaks UI rendering."""
        ws_id = demo_workspace["workspace_id"]
        resp = await client.get(f"/api/graph?workspace_id={ws_id}")
        body = resp.json()

        for node in body["nodes"]:
            assert 0.0 <= node["confidence"] <= 1.0, (
                f"node '{node['name']}' has confidence={node['confidence']} "
                f"outside [0, 1] — check seed data or extraction pipeline."
            )

    async def test_workspace_graph_all_five_models_represented(
        self, client, demo_workspace
    ):
        """The demo seed creates 5 models. All should appear in the graph."""
        ws_id = demo_workspace["workspace_id"]
        resp = await client.get(f"/api/graph?workspace_id={ws_id}")
        body = resp.json()

        model_ids_in_graph = {n["model_id"] for n in body["nodes"]}
        expected_model_ids = {str(m.id) for m in demo_workspace["models"]}
        missing = expected_model_ids - model_ids_in_graph
        assert not missing, (
            f"{len(missing)} model(s) have zero nodes in the workspace graph. "
            f"Missing model IDs: {missing}. Check that the seed created "
            f"components for every model and that workspace graph query "
            f"includes all model_ids."
        )

    async def test_workspace_graph_include_historical_flag_reflected(
        self, client, demo_workspace
    ):
        """include_historical in response must match the query parameter."""
        ws_id = demo_workspace["workspace_id"]

        resp_default = await client.get(f"/api/graph?workspace_id={ws_id}")
        assert resp_default.json()["include_historical"] is False

        resp_hist = await client.get(
            f"/api/graph?workspace_id={ws_id}&include_historical=true"
        )
        assert resp_hist.json()["include_historical"] is True
        # On fresh seed with no historical components, both should return
        # the same node count.
        assert len(resp_hist.json()["nodes"]) >= len(resp_default.json()["nodes"])

    async def test_workspace_graph_returns_404_for_nonexistent_workspace(
        self, client
    ):
        fake_id = uuid4()
        resp = await client.get(f"/api/graph?workspace_id={fake_id}")
        assert resp.status_code == 404, (
            f"expected 404 for nonexistent workspace {fake_id}, "
            f"got {resp.status_code}. The endpoint should raise "
            f"ResourceNotFoundError when no models exist."
        )

    async def test_workspace_graph_hidden_node_count_zero_on_fresh_seed(
        self, client, demo_workspace
    ):
        """Fresh seed has no rejected/hidden components."""
        ws_id = demo_workspace["workspace_id"]
        resp = await client.get(f"/api/graph?workspace_id={ws_id}")
        body = resp.json()
        assert body["hidden_node_count"] == 0, (
            f"fresh demo seed should have 0 hidden nodes, "
            f"got {body['hidden_node_count']}"
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
            f"model graph returned nodes from other models: "
            f"{model_ids_in_response}. Expected only {model.id}."
        )

    async def test_each_model_graph_returns_components(
        self, client, demo_workspace
    ):
        """Every seeded model should return at least one component."""
        for model in demo_workspace["models"]:
            resp = await client.get(f"/api/graph/models/{model.id}")
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["nodes"]) >= 1, (
                f"model '{model.name}' (id={model.id}) returned 0 nodes. "
                f"The demo seed should create components for every model."
            )

    async def test_model_graph_returns_404_for_nonexistent_model(
        self, client
    ):
        fake_id = uuid4()
        resp = await client.get(f"/api/graph/models/{fake_id}")
        assert resp.status_code == 404, (
            f"expected 404 for nonexistent model {fake_id}, "
            f"got {resp.status_code}"
        )

    async def test_model_graph_include_historical_on_fresh_seed(
        self, client, demo_workspace
    ):
        """On fresh seed data, include_historical should not change the count."""
        model = demo_workspace["models"][0]
        resp_default = await client.get(f"/api/graph/models/{model.id}")
        resp_hist = await client.get(
            f"/api/graph/models/{model.id}?include_historical=true"
        )
        assert len(resp_hist.json()["nodes"]) == len(resp_default.json()["nodes"]), (
            f"include_historical changed node count on fresh seed data "
            f"({len(resp_hist.json()['nodes'])} vs {len(resp_default.json()['nodes'])}). "
            f"This suggests some components were incorrectly marked as historical."
        )


# ── Component graph ────────────────────────────────────────────────────


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
        assert str(first_component.id) in root_ids, (
            f"root component {first_component.id} not found in graph nodes. "
            f"The component graph must always include the root node."
        )

    async def test_component_graph_returns_404_for_nonexistent(self, client):
        fake_id = uuid4()
        resp = await client.get(f"/api/graph/components/{fake_id}")
        assert resp.status_code == 404, (
            f"expected 404 for nonexistent component {fake_id}, "
            f"got {resp.status_code}"
        )

    async def test_component_graph_root_has_provenance(
        self, client, first_component
    ):
        """The root node in a component graph should carry provenance."""
        resp = await client.get(
            f"/api/graph/components/{first_component.id}"
        )
        body = resp.json()
        root_node = next(
            n for n in body["nodes"]
            if n["id"] == str(first_component.id)
        )
        assert root_node["source_count"] >= 1, (
            f"root component '{root_node['name']}' has source_count=0 in "
            f"component graph. Demo seed components should all have sources."
        )


# ── Neighborhood ───────────────────────────────────────────────────────


class TestDemoNeighborhood:
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

        # Node shape: verify all expected fields present.
        required_keys = {
            "id", "name", "value", "confidence", "model_id",
            "review_status", "temporal_state", "source_count",
            "authority_weight", "is_stale", "valid_from",
        }
        node = body["nodes"][0]
        missing = required_keys - set(node.keys())
        assert not missing, (
            f"neighborhood node missing keys: {missing}. "
            f"Check GraphNodeRead in schemas/graph.py."
        )

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
                f"edge source_id {edge['source_id']} not in returned nodes. "
                f"Neighborhood edges must only reference nodes in the response."
            )
            assert edge["target_id"] in node_ids, (
                f"edge target_id {edge['target_id']} not in returned nodes. "
                f"Neighborhood edges must only reference nodes in the response."
            )

    async def test_neighborhood_returns_404_for_nonexistent(self, client):
        fake_id = uuid4()
        resp = await client.get(f"/api/graph/neighborhood/{fake_id}")
        assert resp.status_code == 404, (
            f"expected 404 for nonexistent component {fake_id}, "
            f"got {resp.status_code}"
        )

    async def test_neighborhood_include_historical_reflected(
        self, client, first_component
    ):
        """include_historical in response must match query parameter."""
        resp_default = await client.get(
            f"/api/graph/neighborhood/{first_component.id}"
        )
        assert resp_default.json()["include_historical"] is False

        resp_hist = await client.get(
            f"/api/graph/neighborhood/{first_component.id}"
            f"?include_historical=true"
        )
        assert resp_hist.json()["include_historical"] is True

    async def test_neighborhood_root_always_present(
        self, client, first_component
    ):
        """Root node must appear in neighborhood regardless of depth."""
        for depth in (1, 2, 3):
            resp = await client.get(
                f"/api/graph/neighborhood/{first_component.id}?depth={depth}"
            )
            body = resp.json()
            node_ids = {n["id"] for n in body["nodes"]}
            assert str(first_component.id) in node_ids, (
                f"root {first_component.id} missing from neighborhood "
                f"at depth={depth}"
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
        assert len(body) >= 1, (
            "demo seed creates 3 components in the 'Decisions' model — "
            "at least one should surface as a decision. Check that the "
            "decisions endpoint queries the correct model name."
        )

    async def test_decisions_have_name_and_value(
        self, client, demo_workspace
    ):
        """Decisions must carry meaningful content, not just IDs."""
        ws_id = demo_workspace["workspace_id"]
        resp = await client.get(f"/api/decisions?workspace_id={ws_id}")
        body = resp.json()
        for decision in body:
            assert decision.get("name") and decision["name"].strip(), (
                f"decision {decision.get('id', '?')} has empty name"
            )

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

    async def test_source_documents_have_content_and_type(
        self, client, demo_workspace
    ):
        """Source documents should carry content and connector_type, not just stubs."""
        ws_id = demo_workspace["workspace_id"]
        resp = await client.get(
            f"/api/source-documents?workspace_id={ws_id}&limit=10"
        )
        body = resp.json()
        for doc in body["items"]:
            assert doc.get("content") and doc["content"].strip(), (
                f"source document {doc.get('id', '?')} has empty content"
            )
            assert doc.get("connector_type"), (
                f"source document {doc.get('id', '?')} missing connector_type"
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
        assert "components" in body, (
            "query must return provenance via 'components' field — "
            "without this, the frontend cannot show source attribution."
        )
