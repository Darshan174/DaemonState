from __future__ import annotations

import json
from uuid import uuid4


from app.models import Component, Model, Relationship, SourceDocument


class TestGraphProvenance:
    async def test_component_read_includes_source_type(self, client, db_session):
        model = Model(id=uuid4(), name="Pricing")
        doc = SourceDocument(
            id=uuid4(), source_type="slack", external_id="msg-1",
            content="Pricing decision.", metadata_json="{}",
        )
        component = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="$20/mo tier", value="Pricing $20/mo",
            fact_type="fact", confidence=0.8, status="active",
        )
        db_session.add_all([model, doc, component])
        await db_session.flush()

        resp = await client.get("/api/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["components"]) >= 1
        comp = data["components"][0]
        assert comp["source_type"] == "slack"
        assert comp["source_document_id"] is not None

    async def test_component_read_includes_source_url(self, client, db_session):
        model = Model(id=uuid4(), name="Decisions")
        doc = SourceDocument(
            id=uuid4(), source_type="slack", external_id="msg-url",
            content="Decision.", source_url="https://slack.com/archives/C01/msg",
            metadata_json="{}",
        )
        component = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Test decision", value="Test value",
            fact_type="decision", confidence=0.8, status="active",
        )
        db_session.add_all([model, doc, component])
        await db_session.flush()

        resp = await client.get("/api/graph")
        data = resp.json()
        comp = next(c for c in data["components"] if c["id"] == str(component.id))
        assert comp["source_url"] == "https://slack.com/archives/C01/msg"

    async def test_component_read_includes_ingested_at(self, client, db_session):
        model = Model(id=uuid4(), name="Test")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="ts-test",
            content="Some content.", metadata_json="{}",
        )
        component = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Timestamped", value="Value", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add_all([model, doc, component])
        await db_session.flush()

        resp = await client.get("/api/graph")
        data = resp.json()
        comp = next(c for c in data["components"] if c["id"] == str(component.id))
        assert comp["ingested_at"] is not None

    async def test_relationship_read_includes_confidence(self, client, db_session):
        model = Model(id=uuid4(), name="Test")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="rel-conf",
            content="A depends on B.", metadata_json="{}",
        )
        a = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="A", value="A", fact_type="fact",
            confidence=0.8, status="active",
        )
        b = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="B", value="B", fact_type="fact",
            confidence=0.8, status="active",
        )
        rel = Relationship(
            id=uuid4(), source_component_id=a.id,
            target_component_id=b.id,
            relationship_type="depends_on",
            confidence=0.85,
            evidence="'A' depends_on 'B'",
        )
        db_session.add_all([model, doc, a, b, rel])
        await db_session.flush()

        resp = await client.get("/api/graph")
        data = resp.json()
        rels = [r for r in data["relationships"] if r["id"] == str(rel.id)]
        assert len(rels) == 1
        assert rels[0]["confidence"] == 0.85
        assert rels[0]["evidence"] == "'A' depends_on 'B'"


class TestSourceTypeFiltering:
    async def test_source_type_filter(self, client, db_session):
        model = Model(id=uuid4(), name="Pricing")
        doc_slack = SourceDocument(
            id=uuid4(), source_type="slack", external_id="slack-1",
            content="Slack message.", metadata_json="{}",
        )
        doc_local = SourceDocument(
            id=uuid4(), source_type="local", external_id="local-1",
            content="Local content.", metadata_json="{}",
        )
        comp_slack = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc_slack.id,
            name="Slack component", value="From Slack",
            fact_type="fact", confidence=0.8, status="active",
        )
        comp_local = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc_local.id,
            name="Local component", value="Local",
            fact_type="fact", confidence=0.8, status="active",
        )
        db_session.add_all([model, doc_slack, doc_local, comp_slack, comp_local])
        await db_session.flush()

        resp = await client.get("/api/graph", params={"source_type": "slack"})
        data = resp.json()
        comps = data["components"]
        assert len(comps) == 1
        assert comps[0]["source_type"] == "slack"

    async def test_source_type_filter_no_matches(self, client, db_session):
        model = Model(id=uuid4(), name="Test")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="no-match",
            content="Test.", metadata_json="{}",
        )
        comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Test", value="Test", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add_all([model, doc, comp])
        await db_session.flush()

        resp = await client.get("/api/graph", params={"source_type": "discord"})
        data = resp.json()
        assert len(data["components"]) == 0


class TestWorkspaceIdFiltering:
    async def test_workspace_id_filter_accepts_param(self, client, db_session):
        model = Model(id=uuid4(), name="Test")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="ws-test",
            content="Test.",
            metadata_json=json.dumps({"workspace_id": "00000000-0000-0000-0000-000000000001"}),
        )
        comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Test", value="Test", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add_all([model, doc, comp])
        await db_session.flush()

        resp = await client.get(
            "/api/graph",
            params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
        )
        assert resp.status_code == 200
        data = resp.json()
        comps = data["components"]
        assert len(comps) == 1

    async def test_workspace_id_filter_excludes_others(self, client, db_session):
        model = Model(id=uuid4(), name="Test")
        doc_ws1 = SourceDocument(
            id=uuid4(), source_type="local", external_id="ws1",
            content="WS1 content.",
            metadata_json=json.dumps({"workspace_id": "00000000-0000-0000-0000-000000000001"}),
        )
        doc_ws2 = SourceDocument(
            id=uuid4(), source_type="local", external_id="ws2",
            content="WS2 content.",
            metadata_json=json.dumps({"workspace_id": "00000000-0000-0000-0000-000000000002"}),
        )
        comp1 = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc_ws1.id,
            name="WS1 comp", value="WS1", fact_type="fact",
            confidence=0.8, status="active",
        )
        comp2 = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc_ws2.id,
            name="WS2 comp", value="WS2", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add_all([model, doc_ws1, doc_ws2, comp1, comp2])
        await db_session.flush()

        resp = await client.get(
            "/api/graph",
            params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
        )
        data = resp.json()
        assert len(data["components"]) == 1
        assert data["components"][0]["name"] == "WS1 comp"


class TestStatsEndpoint:
    async def test_stats_returns_counts(self, client, db_session):
        model = Model(id=uuid4(), name="Stats")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="stats",
            content="Content.", metadata_json="{}",
        )
        comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Stat comp", value="Value", fact_type="fact",
            confidence=0.8, status="active",
        )
        stale = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Stale comp", value="Old", fact_type="fact",
            confidence=0.3, status="stale",
        )
        db_session.add_all([model, doc, comp, stale])
        await db_session.flush()

        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["models"] >= 1
        assert data["components"] >= 2
        assert data["sources"] >= 1
        assert data["stale"] >= 1

    async def test_stats_supports_workspace_id(self, client, db_session):
        model = Model(id=uuid4(), name="Stats WS")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="stats-ws",
            content="Content.",
            metadata_json=json.dumps({"workspace_id": "00000000-0000-0000-0000-000000000003"}),
        )
        comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="WS comp", value="Value", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add_all([model, doc, comp])
        await db_session.flush()

        resp = await client.get(
            "/api/stats",
            params={"workspace_id": "00000000-0000-0000-0000-000000000003"},
        )
        assert resp.status_code == 200

    async def test_stats_counts_proposed_components(self, client, db_session):
        model = Model(id=uuid4(), name="Roadmap")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="stats-proposed",
            content="Content.", metadata_json="{}",
        )
        active = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Active", value="Active", fact_type="fact",
            confidence=0.8, status="active",
        )
        proposed = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Planned", value="Planned", fact_type="fact",
            confidence=0.7, status="proposed",
        )
        db_session.add_all([model, doc, active, proposed])
        await db_session.flush()

        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["proposed"] >= 1


class TestTimelineEndpoint:
    async def test_timeline_returns_events(self, client, db_session):
        doc = SourceDocument(
            id=uuid4(), source_type="slack", external_id="tl-1",
            content="Timeline event.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        resp = await client.get("/api/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) >= 1

    async def test_timeline_supports_workspace_id(self, client, db_session):
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="tl-ws",
            content="Content.",
            metadata_json=json.dumps({"workspace_id": "00000000-0000-0000-0000-000000000004"}),
        )
        db_session.add(doc)
        await db_session.flush()

        resp = await client.get(
            "/api/timeline",
            params={"workspace_id": "00000000-0000-0000-0000-000000000004"},
        )
        assert resp.status_code == 200


class TestModelIdFilter:
    async def test_filters_by_model_id(self, client, db_session):
        model_a = Model(id=uuid4(), name="Pricing")
        model_b = Model(id=uuid4(), name="Security")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="model-filter",
            content="Content.", metadata_json="{}",
        )
        comp_a = Component(
            id=uuid4(), model_id=model_a.id, source_document_id=doc.id,
            name="Pricing comp", value="Pricing", fact_type="fact",
            confidence=0.8, status="active",
        )
        comp_b = Component(
            id=uuid4(), model_id=model_b.id, source_document_id=doc.id,
            name="Security comp", value="Security", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add_all([model_a, model_b, doc, comp_a, comp_b])
        await db_session.flush()

        resp = await client.get("/api/graph", params={"model_id": str(model_a.id)})
        data = resp.json()
        comps = data["components"]
        assert len(comps) == 1
        assert comps[0]["model_id"] == str(model_a.id)


class TestComponentStatusUpdate:
    async def test_update_component_status(self, client, db_session):
        model = Model(id=uuid4(), name="Test")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="status-update",
            content="Test.", metadata_json="{}",
        )
        comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Test", value="Test", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add_all([model, doc, comp])
        await db_session.flush()

        resp = await client.patch(
            f"/api/components/{comp.id}",
            params={"status": "stale"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "stale"

    async def test_update_nonexistent_component_returns_404(self, client):
        resp = await client.patch(
            f"/api/components/{uuid4()}",
            params={"status": "stale"},
        )
        assert resp.status_code == 404


class TestProposedComponentVisibility:
    async def test_graph_includes_proposed_components(self, client, db_session):
        model = Model(id=uuid4(), name="Roadmap")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="roadmap-doc",
            content="We will add SSO support in Q4.", metadata_json="{}",
        )
        active = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Active feature", value="Already shipped",
            fact_type="fact", confidence=0.8, status="active",
        )
        proposed = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Planned SSO support", value="Will ship in Q4",
            fact_type="fact", confidence=0.75, status="proposed",
        )
        db_session.add_all([model, doc, active, proposed])
        await db_session.flush()

        resp = await client.get("/api/graph")
        assert resp.status_code == 200
        data = resp.json()

        comps = data["components"]
        statuses = {c["status"] for c in comps}
        assert "proposed" in statuses
        proposed_comp = [c for c in comps if c["status"] == "proposed"]
        assert len(proposed_comp) >= 1
        assert proposed_comp[0]["name"] == "Planned SSO support"

    async def test_proposed_component_has_full_provenance(self, client, db_session):
        model = Model(id=uuid4(), name="Future")
        doc = SourceDocument(
            id=uuid4(), source_type="slack", external_id="future-msg",
            content="Plan: launch enterprise tier next quarter.",
            source_url="https://slack.com/archives/C02/plan",
            metadata_json="{}",
        )
        component = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Enterprise tier (planned)", value="Launch Q3",
            fact_type="fact", confidence=0.7, status="proposed",
        )
        db_session.add_all([model, doc, component])
        await db_session.flush()

        resp = await client.get("/api/graph")
        data = resp.json()
        comps = [c for c in data["components"] if c["status"] == "proposed"]
        assert len(comps) >= 1
        comp = comps[0]
        assert comp["source_type"] == "slack"
        assert comp["source_url"] == "https://slack.com/archives/C02/plan"
        assert comp["source_document_id"] is not None


class TestProposedRelationshipsInGraph:
    async def test_graph_includes_relationships_with_proposed_components(self, client, db_session):
        model = Model(id=uuid4(), name="Roadmap")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="rel-proposed",
            content="SSO depends on OAuth2 (planned).", metadata_json="{}",
        )
        active = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="SSO support", value="SSO module",
            fact_type="fact", confidence=0.8, status="active",
        )
        proposed = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="OAuth2 (planned)", value="Will ship Q4",
            fact_type="fact", confidence=0.7, status="proposed",
        )
        rel = Relationship(
            id=uuid4(), source_component_id=active.id,
            target_component_id=proposed.id,
            relationship_type="depends_on",
            confidence=0.85,
            evidence="SSO depends on OAuth2 (planned)",
        )
        db_session.add_all([model, doc, active, proposed, rel])
        await db_session.flush()

        resp = await client.get("/api/graph")
        assert resp.status_code == 200
        data = resp.json()

        rels = data["relationships"]
        assert len(rels) == 1
        assert rels[0]["relationship_type"] == "depends_on"
        assert rels[0]["confidence"] == 0.85
        assert rels[0]["evidence"] == "SSO depends on OAuth2 (planned)"

    async def test_graph_excludes_relationships_to_stale_components(self, client, db_session):
        model = Model(id=uuid4(), name="Test")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="rel-stale",
            content="Content.", metadata_json="{}",
        )
        active = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Active", value="Active", fact_type="fact",
            confidence=0.8, status="active",
        )
        stale = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Stale", value="Old", fact_type="fact",
            confidence=0.3, status="stale",
        )
        rel = Relationship(
            id=uuid4(), source_component_id=active.id,
            target_component_id=stale.id,
            relationship_type="related_to",
            confidence=0.7,
        )
        db_session.add_all([model, doc, active, stale, rel])
        await db_session.flush()

        resp = await client.get("/api/graph")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["components"]) == 1
        assert data["components"][0]["status"] == "active"
        assert len(data["relationships"]) == 0
