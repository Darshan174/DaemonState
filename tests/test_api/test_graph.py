from __future__ import annotations

from uuid import uuid4

import pytest


@pytest.fixture
async def graph_setup(client, created_model):
    """Create a small graph: A --related_to--> B --depends_on--> C."""
    model_id = created_model["id"]

    components = []
    for name, value in [
        ("Component A", "Root node"),
        ("Component B", "One hop away"),
        ("Component C", "Two hops away"),
    ]:
        resp = await client.post(
            f"/api/models/{model_id}/components",
            json={"name": name, "value": value, "confidence": 0.9},
        )
        assert resp.status_code == 201
        components.append(resp.json())

    a, b, c = components

    edges = []
    for src, tgt, rel_type in [
        (a, b, "related_to"),
        (b, c, "depends_on"),
    ]:
        resp = await client.post(
            "/api/relationships",
            json={
                "source_component_id": src["id"],
                "target_component_id": tgt["id"],
                "relationship_type": rel_type,
                "confidence": 0.85,
            },
        )
        assert resp.status_code == 201
        edges.append(resp.json())

    return {"components": components, "edges": edges}


async def test_neighborhood_depth_1(client, graph_setup):
    a = graph_setup["components"][0]
    resp = await client.get(f"/api/graph/neighborhood/{a['id']}?depth=1")
    assert resp.status_code == 200

    data = resp.json()
    assert data["root_id"] == a["id"]
    assert data["depth"] == 1
    assert data["include_historical"] is False

    node_ids = {n["id"] for n in data["nodes"]}
    b_id = graph_setup["components"][1]["id"]
    c_id = graph_setup["components"][2]["id"]

    assert a["id"] in node_ids
    assert b_id in node_ids
    # C is 2 hops away — should not appear at depth 1
    assert c_id not in node_ids

    assert len(data["edges"]) == 1
    edge = data["edges"][0]
    assert edge["source_id"] == a["id"]
    assert edge["target_id"] == b_id


async def test_workspace_graph_endpoint(client, graph_setup, created_model):
    resp = await client.get(
        f"/api/graph?workspace_id={created_model['workspace_id']}"
    )
    assert resp.status_code == 200

    data = resp.json()
    node_ids = {n["id"] for n in data["nodes"]}
    edge_ids = {e["id"] for e in data["edges"]}

    assert graph_setup["components"][0]["id"] in node_ids
    assert graph_setup["components"][1]["id"] in node_ids
    assert graph_setup["components"][2]["id"] in node_ids
    assert graph_setup["edges"][0]["id"] in edge_ids
    assert graph_setup["edges"][1]["id"] in edge_ids


async def test_component_graph_endpoint(client, graph_setup):
    a = graph_setup["components"][0]
    resp = await client.get(f"/api/graph/components/{a['id']}?depth=1")
    assert resp.status_code == 200

    data = resp.json()
    assert data["root_component_id"] == a["id"]
    assert len(data["nodes"]) >= 2
    assert len(data["edges"]) == 1


async def test_model_graph_endpoint(client, graph_setup, created_model):
    resp = await client.get(f"/api/graph/models/{created_model['id']}")
    assert resp.status_code == 200

    data = resp.json()
    node_ids = {n["id"] for n in data["nodes"]}
    assert graph_setup["components"][0]["id"] in node_ids
    assert graph_setup["components"][1]["id"] in node_ids
    assert graph_setup["components"][2]["id"] in node_ids


async def test_neighborhood_depth_2(client, graph_setup):
    a = graph_setup["components"][0]
    resp = await client.get(f"/api/graph/neighborhood/{a['id']}?depth=2")
    assert resp.status_code == 200

    data = resp.json()
    node_ids = {n["id"] for n in data["nodes"]}
    c_id = graph_setup["components"][2]["id"]

    # At depth 2, all three nodes should be present
    assert len(node_ids) == 3
    assert c_id in node_ids
    assert len(data["edges"]) == 2


async def test_neighborhood_relationship_type_filter(client, graph_setup):
    a = graph_setup["components"][0]
    # Filter to only depends_on — the A->B edge is related_to, so depth-1 from A yields nothing matching
    resp = await client.get(
        f"/api/graph/neighborhood/{a['id']}?depth=2&relationship_types=depends_on"
    )
    assert resp.status_code == 200

    data = resp.json()
    # Only depends_on edges returned
    for edge in data["edges"]:
        assert edge["relationship_type"] == "depends_on"


async def test_neighborhood_not_found(client):
    resp = await client.get(f"/api/graph/neighborhood/{uuid4()}?depth=1")
    assert resp.status_code == 404


async def test_neighborhood_node_metadata(client, graph_setup):
    a = graph_setup["components"][0]
    resp = await client.get(f"/api/graph/neighborhood/{a['id']}?depth=1")
    data = resp.json()

    root_node = next(n for n in data["nodes"] if n["id"] == a["id"])
    assert "name" in root_node
    assert "confidence" in root_node
    assert "model_id" in root_node
    assert "source_count" in root_node
    assert "temporal_state" in root_node
    assert "valid_from" in root_node


async def test_neighborhood_edge_metadata(client, graph_setup):
    a = graph_setup["components"][0]
    resp = await client.get(f"/api/graph/neighborhood/{a['id']}?depth=1")
    data = resp.json()

    edge = data["edges"][0]
    assert "source_id" in edge
    assert "target_id" in edge
    assert "relationship_type" in edge
    assert "sentiment" in edge
    assert "confidence" in edge
    assert "temporal_state" in edge
    assert "valid_from" in edge
