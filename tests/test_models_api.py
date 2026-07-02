from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.models import Component, Model, Relationship, SourceDocument, Workspace


@pytest.mark.asyncio
async def test_list_models_counts_components_in_requested_workspace(client, db_session):
    ws_a = Workspace(id=uuid4(), name="Models A", slug=f"models-a-{uuid4().hex}")
    ws_b = Workspace(id=uuid4(), name="Models B", slug=f"models-b-{uuid4().hex}")
    model = Model(id=uuid4(), name=f"Workspace Model {uuid4().hex}")
    doc_a = SourceDocument(
        id=uuid4(),
        workspace_id=ws_a.id,
        source_type="local",
        external_id="model-a.md",
        content="Decision: model A.",
        metadata_json=json.dumps({"workspace_id": str(ws_a.id)}),
    )
    doc_b = SourceDocument(
        id=uuid4(),
        workspace_id=ws_b.id,
        source_type="local",
        external_id="model-b.md",
        content="Decision: model B.",
        metadata_json=json.dumps({"workspace_id": str(ws_b.id)}),
    )
    comp_a = Component(
        id=uuid4(),
        workspace_id=ws_a.id,
        model_id=model.id,
        source_document_id=doc_a.id,
        name="Workspace A fact",
        value="Only A",
        fact_type="fact",
        confidence=0.8,
        status="active",
    )
    comp_b = Component(
        id=uuid4(),
        workspace_id=ws_b.id,
        model_id=model.id,
        source_document_id=doc_b.id,
        name="Workspace B fact",
        value="Only B",
        fact_type="fact",
        confidence=0.8,
        status="active",
    )
    db_session.add_all([ws_a, ws_b, model, doc_a, doc_b, comp_a, comp_b])
    await db_session.flush()
    await db_session.commit()

    response = await client.get("/api/models", params={"workspace_id": str(ws_a.id)})

    assert response.status_code == 200
    item = next(model_item for model_item in response.json() if model_item["id"] == str(model.id))
    assert item["component_count"] == 1


@pytest.mark.asyncio
async def test_model_detail_and_relationships_filter_by_workspace(client, db_session):
    ws_a = Workspace(id=uuid4(), name="Detail Models A", slug=f"detail-models-a-{uuid4().hex}")
    ws_b = Workspace(id=uuid4(), name="Detail Models B", slug=f"detail-models-b-{uuid4().hex}")
    model = Model(id=uuid4(), name=f"Relationship Model {uuid4().hex}")
    doc_a = SourceDocument(
        id=uuid4(),
        workspace_id=ws_a.id,
        source_type="local",
        external_id="rel-a.md",
        content="Decision: A links to A target.",
        metadata_json=json.dumps({"workspace_id": str(ws_a.id)}),
    )
    doc_b = SourceDocument(
        id=uuid4(),
        workspace_id=ws_b.id,
        source_type="local",
        external_id="rel-b.md",
        content="Decision: B links to B target.",
        metadata_json=json.dumps({"workspace_id": str(ws_b.id)}),
    )
    a_source = Component(
        id=uuid4(),
        workspace_id=ws_a.id,
        model_id=model.id,
        source_document_id=doc_a.id,
        name="A source",
        value="A source",
        fact_type="fact",
        confidence=0.9,
        status="active",
    )
    a_target = Component(
        id=uuid4(),
        workspace_id=ws_a.id,
        model_id=model.id,
        source_document_id=doc_a.id,
        name="A target",
        value="A target",
        fact_type="fact",
        confidence=0.9,
        status="active",
    )
    b_source = Component(
        id=uuid4(),
        workspace_id=ws_b.id,
        model_id=model.id,
        source_document_id=doc_b.id,
        name="B source",
        value="B source",
        fact_type="fact",
        confidence=0.9,
        status="active",
    )
    b_target = Component(
        id=uuid4(),
        workspace_id=ws_b.id,
        model_id=model.id,
        source_document_id=doc_b.id,
        name="B target",
        value="B target",
        fact_type="fact",
        confidence=0.9,
        status="active",
    )
    rel_a = Relationship(
        id=uuid4(),
        source_component_id=a_source.id,
        target_component_id=a_target.id,
        relationship_type="depends_on",
        confidence=0.9,
    )
    rel_b = Relationship(
        id=uuid4(),
        source_component_id=b_source.id,
        target_component_id=b_target.id,
        relationship_type="depends_on",
        confidence=0.9,
    )
    db_session.add_all([
        ws_a, ws_b, model, doc_a, doc_b,
        a_source, a_target, b_source, b_target, rel_a, rel_b,
    ])
    await db_session.flush()
    await db_session.commit()

    detail = await client.get(f"/api/models/{model.id}", params={"workspace_id": str(ws_a.id)})
    relationships = await client.get(
        f"/api/models/{model.id}/relationships",
        params={"workspace_id": str(ws_a.id)},
    )

    assert detail.status_code == 200
    component_names = {component["name"] for component in detail.json()["components"]}
    assert component_names == {"A source", "A target"}

    assert relationships.status_code == 200
    relationship_ids = {relationship["id"] for relationship in relationships.json()}
    assert relationship_ids == {str(rel_a.id)}
    assert str(rel_b.id) not in relationship_ids
