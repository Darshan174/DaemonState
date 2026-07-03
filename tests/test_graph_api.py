from __future__ import annotations

import json
from uuid import UUID, uuid4

from sqlalchemy import select

from app.models import (
    Component,
    Connector,
    Entity,
    Model,
    Relationship,
    RetrievalEvent,
    SourceDocument,
    UnresolvedRelationship,
    Workspace,
)
from app.processing.embedder import HashingEmbedder
from app.services.vector_search import (
    TextSearchMatch,
    TextSearchResult,
    VectorSearchMatch,
    VectorSearchResult,
)


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

    async def test_graph_exposes_unresolved_relationships_separately(self, client, db_session):
        model = Model(id=uuid4(), name="Feature")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="graph-unresolved",
            content="Checkout depends on Payments API.", metadata_json="{}",
        )
        component = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Checkout", value="Checkout work is blocked by Payments API",
            fact_type="feature", confidence=0.8, status="active",
        )
        gap = UnresolvedRelationship(
            id=uuid4(),
            source_component_id=component.id,
            source_document_id=doc.id,
            target_name="Payments API",
            target_identity_key="component:payments-api",
            relationship_type="depends_on",
            confidence=0.82,
            evidence="Checkout depends on Payments API.",
            origin="extracted",
        )
        db_session.add_all([model, doc, component, gap])
        await db_session.flush()

        resp = await client.get("/api/graph")
        assert resp.status_code == 200
        data = resp.json()
        unresolved = [
            item for item in data["unresolved_relationships"]
            if item["id"] == str(gap.id)
        ]
        assert len(unresolved) == 1
        assert unresolved[0]["source_component_name"] == "Checkout"
        assert unresolved[0]["target_name"] == "Payments API"
        assert unresolved[0]["relationship_type"] == "depends_on"
        assert all(edge["id"] != str(gap.id) for edge in data["relationships"])

    async def test_legacy_source_detail_returns_components(self, client, db_session):
        model = Model(id=uuid4(), name="Email")
        doc = SourceDocument(
            id=uuid4(), source_type="gmail", external_id="gmail:detail",
            content="Email body.", metadata_json="{}",
        )
        component = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Email detail component", value="Extracted email fact",
            fact_type="fact", confidence=0.8, status="active",
        )
        db_session.add_all([model, doc, component])
        await db_session.flush()

        resp = await client.get(f"/api/sources/{doc.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(doc.id)
        assert len(data["components"]) == 1
        assert data["components"][0]["name"] == "Email detail component"

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

    async def test_connector_metadata_summary_includes_display_fields(self, client, db_session):
        email_model = Model(id=uuid4(), name="Email")
        message_model = Model(id=uuid4(), name="Message")
        gmail_doc = SourceDocument(
            id=uuid4(),
            source_type="gmail",
            external_id="gmail:msg-1",
            content="Email body.",
            metadata_json=json.dumps({
                "subject": "Launch plan",
                "from": "PM <pm@example.com>",
                "snippet": "Launch plan update",
                "thread_id": "thread-1",
            }),
        )
        slack_doc = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="slack:C123:1.0",
            content="Slack body.",
            metadata_json=json.dumps({
                "channel_name": "growth",
                "author_name": "Darshan",
                "ts": "1.0",
                "thread_ts": "1.0",
                "parent_ts": "0.9",
                "is_thread_reply": True,
                "reply_count": 0,
                "permalink": "https://slack.example/C123/p10",
            }),
        )
        gmail_component = Component(
            id=uuid4(), model_id=email_model.id, source_document_id=gmail_doc.id,
            name="Email: Launch plan from PM", value="Launch plan update",
            fact_type="email", confidence=0.7, status="active",
        )
        slack_component = Component(
            id=uuid4(), model_id=message_model.id, source_document_id=slack_doc.id,
            name="Slack: #growth - Darshan: Slack body", value="Slack body",
            fact_type="message", confidence=0.7, status="active",
        )
        db_session.add_all([
            email_model, message_model, gmail_doc, slack_doc,
            gmail_component, slack_component,
        ])
        await db_session.flush()

        resp = await client.get("/api/graph")
        assert resp.status_code == 200
        data = resp.json()
        gmail = next(c for c in data["components"] if c["id"] == str(gmail_component.id))
        slack = next(c for c in data["components"] if c["id"] == str(slack_component.id))

        assert gmail["source_metadata_summary"]["subject"] == "Launch plan"
        assert gmail["source_metadata_summary"]["from"] == "PM <pm@example.com>"
        assert gmail["source_metadata_summary"]["snippet"] == "Launch plan update"
        assert slack["source_metadata_summary"]["channel_name"] == "growth"
        assert slack["source_metadata_summary"]["author_name"] == "Darshan"
        assert slack["source_metadata_summary"]["thread_ts"] == "1.0"
        assert slack["source_metadata_summary"]["parent_ts"] == "0.9"
        assert slack["source_metadata_summary"]["is_thread_reply"] is True
        assert slack["source_metadata_summary"]["reply_count"] == 0
        assert slack["source_metadata_summary"]["permalink"] == "https://slack.example/C123/p10"

    async def test_workspace_graph_includes_legacy_connector_documents(self, client, db_session):
        workspace_id = uuid4()
        workspace = Workspace(id=workspace_id, name="Research Radar", slug=f"research-{workspace_id.hex[:8]}")
        connector = Connector(
            id=uuid4(),
            workspace_id=workspace_id,
            connector_type="gmail",
            status="connected",
            config_json="{}",
        )
        model = Model(id=uuid4(), name="Email")
        doc = SourceDocument(
            id=uuid4(), source_type="gmail", external_id="gmail:legacy",
            content="Legacy Gmail source.", metadata_json="{}",
        )
        component = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Legacy email component", value="Legacy value",
            fact_type="fact", confidence=0.8, status="active",
        )
        db_session.add_all([workspace, connector, model, doc, component])
        await db_session.flush()

        resp = await client.get("/api/graph", params={"workspace_id": str(workspace_id)})
        assert resp.status_code == 200
        data = resp.json()
        assert any(c["id"] == str(component.id) for c in data["components"])

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

    async def test_stats_counts_only_workspace_graph_items(self, client, db_session):
        ws1 = "00000000-0000-0000-0000-000000000031"
        ws2 = "00000000-0000-0000-0000-000000000032"
        model = Model(id=uuid4(), name="Scoped Stats")
        doc_ws1 = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="stats-ws1",
            content="Workspace one stats.",
            metadata_json=json.dumps({"workspace_id": ws1}),
        )
        doc_ws2 = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="stats-ws2",
            content="Workspace two stats.",
            metadata_json=json.dumps({"workspace_id": ws2}),
        )
        active = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc_ws1.id,
            name="WS1 active", value="Active", fact_type="fact",
            confidence=0.8, status="active",
        )
        proposed = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc_ws1.id,
            name="WS1 proposed", value="Proposed", fact_type="fact",
            confidence=0.7, status="proposed",
        )
        stale_other = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc_ws2.id,
            name="WS2 stale", value="Stale", fact_type="fact",
            confidence=0.4, status="stale",
        )
        scoped_rel = Relationship(
            id=uuid4(),
            source_component_id=active.id,
            target_component_id=proposed.id,
            relationship_type="related_to",
        )
        cross_rel = Relationship(
            id=uuid4(),
            source_component_id=active.id,
            target_component_id=stale_other.id,
            relationship_type="related_to",
        )
        db_session.add_all([
            model, doc_ws1, doc_ws2, active, proposed, stale_other, scoped_rel, cross_rel,
        ])
        await db_session.flush()

        resp = await client.get("/api/stats", params={"workspace_id": ws1})
        assert resp.status_code == 200
        data = resp.json()

        assert data["models"] == 1
        assert data["components"] == 2
        assert data["relationships"] == 1
        assert data["sources"] == 1
        assert data["proposed"] == 1
        assert data["stale"] == 0

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


class TestWorkspaceScopedGraphEndpoints:
    async def test_work_lens_uses_graph_workspace_matching(self, client, db_session):
        workspace_id = uuid4()
        workspace = Workspace(id=workspace_id, name="Lens Workspace", slug=f"lens-{workspace_id.hex[:8]}")
        connector = Connector(
            id=uuid4(),
            workspace_id=workspace_id,
            connector_type="gmail",
            status="connected",
            config_json="{}",
        )
        model = Model(id=uuid4(), name="Risk")
        legacy_gmail_doc = SourceDocument(
            id=uuid4(),
            source_type="gmail",
            external_id="gmail:lens-legacy",
            content="Risk: churn is increasing.",
            metadata_json="{}",
        )
        other_doc = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="slack:lens-other",
            content="Risk: unrelated workspace.",
            metadata_json=json.dumps({"workspace_id": "00000000-0000-0000-0000-000000000041"}),
        )
        scoped_risk = Component(
            id=uuid4(), model_id=model.id, source_document_id=legacy_gmail_doc.id,
            name="Scoped churn risk", value="Churn is increasing",
            fact_type="risk", confidence=0.8, status="active",
        )
        other_risk = Component(
            id=uuid4(), model_id=model.id, source_document_id=other_doc.id,
            name="Other workspace risk", value="Unrelated",
            fact_type="risk", confidence=0.8, status="active",
        )
        db_session.add_all([
            workspace, connector, model, legacy_gmail_doc, other_doc, scoped_risk, other_risk,
        ])
        await db_session.flush()

        resp = await client.get("/api/work-lens", params={"workspace_id": str(workspace_id)})
        assert resp.status_code == 200
        blocker_names = {item["name"] for item in resp.json()["blockers"]}

        assert "Scoped churn risk" in blocker_names
        assert "Other workspace risk" not in blocker_names

    async def test_query_is_limited_to_workspace_components(self, client, db_session):
        ws1 = "00000000-0000-0000-0000-000000000051"
        ws2 = "00000000-0000-0000-0000-000000000052"
        embedder = HashingEmbedder()
        model = Model(id=uuid4(), name="Risk")
        doc_ws1 = SourceDocument(
            id=uuid4(),
            workspace_id=UUID(ws1),
            source_type="slack",
            external_id="query-ws1",
            content="Billing risk for workspace one.",
            metadata_json=json.dumps({"workspace_id": ws1}),
        )
        doc_ws2 = SourceDocument(
            id=uuid4(),
            workspace_id=UUID(ws2),
            source_type="slack",
            external_id="query-ws2",
            content="Billing risk for workspace two.",
            metadata_json=json.dumps({"workspace_id": ws2}),
        )
        comp_ws1 = Component(
            id=uuid4(), workspace_id=UUID(ws1), model_id=model.id, source_document_id=doc_ws1.id,
            name="Workspace one billing risk", value="Billing risk is in workspace one",
            fact_type="risk", confidence=0.9, status="active",
            embedding=json.dumps(await embedder.embed_text("billing risk workspace one")),
        )
        comp_ws2 = Component(
            id=uuid4(), workspace_id=UUID(ws2), model_id=model.id, source_document_id=doc_ws2.id,
            name="Workspace two billing risk", value="Billing risk is in workspace two",
            fact_type="risk", confidence=0.9, status="active",
            embedding=json.dumps(await embedder.embed_text("billing risk workspace two")),
        )
        db_session.add_all([model, doc_ws1, doc_ws2, comp_ws1, comp_ws2])
        await db_session.flush()

        resp = await client.post("/api/query", json={
            "question": "What is the billing risk?",
            "workspace_id": ws1,
        })
        assert resp.status_code == 200
        component_names = {component["name"] for component in resp.json()["components"]}

        assert "Workspace one billing risk" in component_names
        assert "Workspace two billing risk" not in component_names
        trace = resp.json()["trace"]
        assert trace["candidate_component_count"] == 1
        assert trace["scoped_component_count"] == 1
        assert trace["scored_component_count"] == 1

    async def test_query_exposes_versioned_trace_and_retrieval_knobs(self, client, db_session):
        embedder = HashingEmbedder()
        model = Model(id=uuid4(), name="Risk")
        doc = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="query-trace",
            content="Launch blocker discussion.",
            metadata_json="{}",
        )
        high_conf = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Launch blocker", value="Launch blocker is unresolved",
            fact_type="risk", confidence=0.9, status="active",
            embedding=json.dumps(await embedder.embed_text("launch blocker unresolved")),
        )
        low_conf = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Launch blocker maybe", value="Launch blocker maybe",
            fact_type="risk", confidence=0.4, status="active",
            embedding=json.dumps(await embedder.embed_text("launch blocker maybe")),
        )
        db_session.add_all([model, doc, high_conf, low_conf])
        await db_session.flush()

        resp = await client.post("/api/query", json={
            "question": "launch blocker",
            "top_k": 1,
            "min_confidence": 0.8,
            "hybrid": True,
        })
        assert resp.status_code == 200
        data = resp.json()

        assert data["schema_version"] == "query.v1"
        assert data["trace"]["retrieval_strategy"] == "python_scan"
        assert data["trace"]["vector_candidate_count"] == 0
        assert data["trace"]["vector_prefilter_limit"] is None
        assert data["trace"]["top_k"] == 1
        assert data["trace"]["min_confidence"] == 0.8
        assert data["trace"]["candidate_component_count"] == 1
        assert data["trace"]["scoped_component_count"] == 1
        assert data["trace"]["scored_component_count"] == 1
        assert data["trace"]["matched_component_count"] == 1
        assert data["trace"]["facts_used"][0]["name"] == "Launch blocker"
        assert {component["name"] for component in data["components"]} == {"Launch blocker"}
        assert data["answer"]
        assert "Launch blocker" in data["answer"]
        events = list(await db_session.scalars(
            select(RetrievalEvent).order_by(RetrievalEvent.created_at.desc())
        ))
        assert events
        latest = events[0]
        assert latest.question == "launch blocker"
        assert latest.schema_version == "query.v1"
        assert latest.top_k == 1
        assert latest.min_confidence == 0.8
        assert latest.component_count == 1
        trace_payload = json.loads(latest.trace_json)
        assert trace_payload["facts_used"][0]["name"] == "Launch blocker"

        empty_resp = await client.post("/api/query", json={
            "question": "launch blocker",
            "min_confidence": 0.99,
        })
        assert empty_resp.status_code == 200
        empty_data = empty_resp.json()
        assert empty_data["trace"]["min_confidence"] == 0.99
        assert empty_data["trace"]["candidate_component_count"] == 0
        assert empty_data["trace"]["scoped_component_count"] == 0
        assert empty_data["trace"]["scored_component_count"] == 0
        assert empty_data["trace"]["matched_component_count"] == 0
        assert empty_data["components"] == []
        assert "No matching context found" in empty_data["answer"]
        empty_event = await db_session.scalar(
            select(RetrievalEvent).where(RetrievalEvent.min_confidence == 0.99)
        )
        assert empty_event is not None
        assert empty_event.component_count == 0
        assert "No matching context found" in empty_event.answer

    async def test_query_uses_vector_prefilter_when_available(
        self,
        client,
        db_session,
        monkeypatch,
    ):
        embedder = HashingEmbedder()
        model = Model(id=uuid4(), name="Risk")
        doc = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="query-vector-prefilter",
            content="Launch risk discussion.",
            metadata_json="{}",
        )
        lexical_best = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Launch blocker exact", value="Launch blocker appears in this text",
            fact_type="risk", confidence=0.99, status="active",
            embedding=json.dumps(await embedder.embed_text("launch blocker exact")),
        )
        vector_best = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Vector-ranked blocker", value="The indexed vector path selected this fact",
            fact_type="risk", confidence=0.7, status="active",
            embedding=json.dumps(await embedder.embed_text("indexed semantic match")),
        )
        db_session.add_all([model, doc, lexical_best, vector_best])
        await db_session.flush()

        async def fake_vector_search(*args, **kwargs):
            assert kwargs["limit"] >= 100
            return VectorSearchResult(
                enabled=True,
                matches=[
                    VectorSearchMatch(
                        component_id=vector_best.id,
                        semantic_score=0.98,
                    )
                ],
            )

        monkeypatch.setattr("app.services.query.search_component_vectors", fake_vector_search)

        resp = await client.post("/api/query", json={
            "question": "launch blocker",
            "top_k": 1,
            "hybrid": True,
        })
        assert resp.status_code == 200
        data = resp.json()

        assert data["trace"]["retrieval_strategy"] == "postgres_vector"
        assert data["trace"]["vector_candidate_count"] == 1
        assert data["trace"]["vector_prefilter_limit"] >= 100
        assert data["trace"]["candidate_component_count"] == 1
        assert data["trace"]["facts_used"][0]["name"] == "Vector-ranked blocker"
        assert {component["name"] for component in data["components"]} == {
            "Vector-ranked blocker"
        }

    async def test_query_uses_postgres_text_prefilter_when_available(
        self,
        client,
        db_session,
        monkeypatch,
    ):
        embedder = HashingEmbedder()
        model = Model(id=uuid4(), name="Risk")
        doc = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="query-text-prefilter",
            content="Launch risk discussion.",
            metadata_json="{}",
        )
        text_best = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Text-ranked blocker", value="Full-text search selected this blocker",
            fact_type="risk", confidence=0.8, status="active",
            embedding=json.dumps(await embedder.embed_text("unrelated semantic vector")),
        )
        hidden = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Hidden blocker", value="Should be excluded by text prefilter",
            fact_type="risk", confidence=0.99, status="active",
            embedding=json.dumps(await embedder.embed_text("launch blocker")),
        )
        db_session.add_all([model, doc, text_best, hidden])
        await db_session.flush()

        async def fake_text_search(*args, **kwargs):
            assert kwargs["limit"] >= 100
            return TextSearchResult(
                enabled=True,
                matches=[
                    TextSearchMatch(
                        component_id=text_best.id,
                        lexical_score=1.3,
                    )
                ],
            )

        monkeypatch.setattr("app.services.query.search_component_text", fake_text_search)

        resp = await client.post("/api/query", json={
            "question": "launch blocker",
            "top_k": 1,
            "hybrid": True,
        })
        assert resp.status_code == 200
        data = resp.json()

        assert data["trace"]["retrieval_strategy"] == "postgres_text"
        assert data["trace"]["text_candidate_count"] == 1
        assert data["trace"]["text_prefilter_limit"] >= 100
        assert data["trace"]["candidate_component_count"] == 1
        assert data["trace"]["facts_used"][0]["name"] == "Text-ranked blocker"
        assert {component["name"] for component in data["components"]} == {
            "Text-ranked blocker"
        }

    async def test_query_diversifies_top_matches_by_entity(self, client, db_session):
        embedder = HashingEmbedder()
        model = Model(id=uuid4(), name="Risk")
        doc = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="query-entity-diversity",
            content="Billing risks from several sources.",
            metadata_json="{}",
        )
        billing_entity = Entity(
            id=uuid4(),
            model_id=model.id,
            identity_key="component:billing-risk",
            canonical_name="Billing risk",
        )
        security_entity = Entity(
            id=uuid4(),
            model_id=model.id,
            identity_key="component:security-risk",
            canonical_name="Security risk",
        )
        repeated_best = Component(
            id=uuid4(), entity_id=billing_entity.id,
            identity_key=billing_entity.identity_key,
            model_id=model.id, source_document_id=doc.id,
            name="Billing risk primary", value="Billing risk blocks launch",
            fact_type="risk", confidence=0.95, status="active",
            embedding=json.dumps(await embedder.embed_text("billing risk blocks launch")),
        )
        repeated_duplicate = Component(
            id=uuid4(), entity_id=billing_entity.id,
            identity_key=billing_entity.identity_key,
            model_id=model.id, source_document_id=doc.id,
            name="Billing risk duplicate", value="Billing risk also blocks onboarding",
            fact_type="risk", confidence=0.94, status="active",
            embedding=json.dumps(await embedder.embed_text("billing risk blocks launch")),
        )
        other_entity = Component(
            id=uuid4(), entity_id=security_entity.id,
            identity_key=security_entity.identity_key,
            model_id=model.id, source_document_id=doc.id,
            name="Security review", value="Security review needs follow-up",
            fact_type="risk", confidence=0.7, status="active",
            embedding=json.dumps(await embedder.embed_text("security review")),
        )
        db_session.add_all([
            model, doc, billing_entity, security_entity,
            repeated_best, repeated_duplicate, other_entity,
        ])
        await db_session.flush()

        resp = await client.post("/api/query", json={
            "question": "billing risk",
            "top_k": 2,
            "hybrid": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [component["name"] for component in data["components"] if component["matched"]]

        assert names == ["Billing risk primary", "Security review"]
        assert data["trace"]["scored_component_count"] == 3
        assert data["trace"]["entity_group_count"] == 2
        assert data["trace"]["entity_duplicate_count"] == 1
        assert data["trace"]["matched_component_count"] == 2
        assert data["trace"]["facts_used"][0]["entity_id"] == str(billing_entity.id)
        assert data["trace"]["facts_used"][1]["entity_id"] == str(security_entity.id)

    async def test_query_expands_relationships_from_top_matches(self, client, db_session):
        embedder = HashingEmbedder()
        model = Model(id=uuid4(), name="Task")
        doc = SourceDocument(
            id=uuid4(),
            source_type="github_issue",
            external_id="query-expand",
            content="PR fixes the launch blocker.",
            metadata_json="{}",
        )
        blocker = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Launch blocker", value="Launch blocker is unresolved",
            fact_type="risk", confidence=0.95, status="active",
            embedding=json.dumps(await embedder.embed_text("launch blocker unresolved")),
        )
        fix = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Fix launch PR", value="PR #7 fixes the blocker",
            fact_type="github_pr", confidence=0.9, status="active",
            embedding=json.dumps(await embedder.embed_text("totally different")),
        )
        rel = Relationship(
            id=uuid4(),
            source_component_id=fix.id,
            target_component_id=blocker.id,
            relationship_type="fixes",
            confidence=0.92,
            evidence="PR #7 explicitly says Fixes #12.",
            origin="deterministic",
        )
        db_session.add_all([model, doc, blocker, fix, rel])
        await db_session.flush()

        resp = await client.post("/api/query", json={
            "question": "launch blocker",
            "top_k": 1,
            "hybrid": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        names = {component["name"] for component in data["components"]}

        assert "Launch blocker" in names
        assert "Fix launch PR" in names
        assert data["trace"]["expanded_relationship_count"] == 1
        assert data["trace"]["relationships_used"][0]["evidence"] == "PR #7 explicitly says Fixes #12."

    async def test_graph_build_processes_only_workspace_pending_documents(self, client, db_session):
        ws1 = "00000000-0000-0000-0000-000000000061"
        ws2 = "00000000-0000-0000-0000-000000000062"
        doc_ws1 = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="build-ws1",
            content="Decision: use workspace-first graph scoping.",
            metadata_json=json.dumps({"workspace_id": ws1}),
        )
        doc_ws2 = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="build-ws2",
            content="Decision: keep this other workspace pending.",
            metadata_json=json.dumps({"workspace_id": ws2}),
        )
        db_session.add_all([doc_ws1, doc_ws2])
        await db_session.flush()

        resp = await client.post("/api/graph/build", json={"workspace_id": ws1, "limit": 100})
        assert resp.status_code == 200
        data = resp.json()

        await db_session.refresh(doc_ws1)
        await db_session.refresh(doc_ws2)
        assert data["docs_pending_before"] == 1
        assert data["docs_processed"] == 1
        assert data["stats"]["extraction_quality"]["fact_count"] >= 1
        assert data["stats"]["extraction_quality"]["contract_warning_count"] == 0
        assert doc_ws1.processed_at is not None
        assert doc_ws2.processed_at is None


class TestContextDigestEndpoint:
    async def test_context_digest_ranks_attention_cards_with_provenance(self, client, db_session):
        model = Model(id=uuid4(), name="Auth")
        doc = SourceDocument(
            id=uuid4(),
            source_type="github_pr",
            external_id="pr-18",
            source_url="https://github.example/acme/repo/pull/18",
            content="OAuth callback handling is missing.",
            metadata_json=json.dumps({
                "title": "PR #18 OAuth callback",
                "repo_full_name": "acme/repo",
            }),
        )
        blocker = Component(
            id=uuid4(),
            model_id=model.id,
            source_document_id=doc.id,
            name="OAuth callback missing",
            value="Auth flow is blocked by missing OAuth callback handling.",
            fact_type="blocker",
            confidence=0.91,
            authority_weight=0.9,
            status="active",
            excerpt="OAuth callback handling is missing.",
        )
        decision = Component(
            id=uuid4(),
            model_id=model.id,
            source_document_id=doc.id,
            name="Keep FastAPI auth path",
            value="Decision: keep the FastAPI auth path for OAuth.",
            fact_type="decision",
            confidence=0.64,
            authority_weight=0.6,
            status="needs_review",
        )
        rel = Relationship(
            id=uuid4(),
            source_component_id=decision.id,
            target_component_id=blocker.id,
            relationship_type="blocks",
            confidence=0.88,
            evidence="Decision work is blocked until OAuth callback exists.",
        )
        db_session.add_all([model, doc, blocker, decision, rel])
        await db_session.flush()

        resp = await client.get("/api/context/digest")
        assert resp.status_code == 200
        data = resp.json()

        assert data["health"]["blocker_count"] >= 1
        assert data["health"]["agent_ready_score"] < 100
        assert data["cards"][0]["title"] == "Blocker: OAuth callback missing"
        assert data["cards"][0]["status"] == "blocked"
        assert data["cards"][0]["attention_score"] > data["cards"][1]["attention_score"]
        assert data["cards"][0]["provenance"][0]["source_label"] == "PR #18 OAuth callback"
        assert data["cards"][0]["provenance"][0]["source_url"] == "https://github.example/acme/repo/pull/18"
        assert any(cluster["id"] == "needs_attention" for cluster in data["clusters"])
        assert any(link["relationship_id"] == str(rel.id) for link in data["links"])

    async def test_context_digest_supports_workspace_id(self, client, db_session):
        ws1 = "00000000-0000-0000-0000-000000000061"
        ws2 = "00000000-0000-0000-0000-000000000062"
        model = Model(id=uuid4(), name="Workspace Digest")
        doc_ws1 = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="digest-ws1",
            content="Workspace one blocker.",
            metadata_json=json.dumps({"workspace_id": ws1}),
        )
        doc_ws2 = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="digest-ws2",
            content="Workspace two blocker.",
            metadata_json=json.dumps({"workspace_id": ws2}),
        )
        comp_ws1 = Component(
            id=uuid4(),
            model_id=model.id,
            source_document_id=doc_ws1.id,
            name="Workspace one blocker",
            value="Workspace one is blocked.",
            fact_type="blocker",
            confidence=0.8,
            status="active",
        )
        comp_ws2 = Component(
            id=uuid4(),
            model_id=model.id,
            source_document_id=doc_ws2.id,
            name="Workspace two blocker",
            value="Workspace two is blocked.",
            fact_type="blocker",
            confidence=0.8,
            status="active",
        )
        db_session.add_all([model, doc_ws1, doc_ws2, comp_ws1, comp_ws2])
        await db_session.flush()

        resp = await client.get("/api/context/digest", params={"workspace_id": ws1})
        assert resp.status_code == 200
        card_titles = {card["title"] for card in resp.json()["cards"]}

        assert "Blocker: Workspace one blocker" in card_titles
        assert "Blocker: Workspace two blocker" not in card_titles

    async def test_context_digest_filters_instruction_and_media_noise(self, client, db_session):
        model = Model(id=uuid4(), name="Codex session digest")
        doc = SourceDocument(
            id=uuid4(),
            source_type="agent_session",
            external_id="codex:session:noisy",
            content="Codex session with one real decision and noisy payload fragments.",
            metadata_json=json.dumps({"tool": "codex", "session_id": "noisy"}),
        )
        valid = Component(
            id=uuid4(),
            model_id=model.id,
            source_document_id=doc.id,
            name="Keep graph zoom inside board",
            value="Decision: keep graph zoom scoped to the digest board instead of scaling the page.",
            fact_type="decision",
            confidence=0.82,
            status="active",
        )
        instruction_noise = Component(
            id=uuid4(),
            model_id=model.id,
            source_document_id=doc.id,
            name="Decision: base_instructions",
            value="developer instructions require request escalation, prefix_rule handling, and current date handling.",
            fact_type="decision",
            confidence=0.91,
            status="active",
        )
        media_noise = Component(
            id=uuid4(),
            model_id=model.id,
            source_document_id=doc.id,
            name="./",
            value=f"data:image/png;base64,{'A' * 220}",
            fact_type="blocker",
            confidence=0.91,
            status="active",
        )
        progress_noise = Component(
            id=uuid4(),
            model_id=model.id,
            source_document_id=doc.id,
            name="Risk: only because Vitest does not accept Jest's --runInBand flag here, so I'm rerunning the actual project test command.",
            value="only because Vitest does not accept Jest's --runInBand flag here, so I'm rerunning the actual project test command.",
            fact_type="blocker",
            confidence=0.82,
            status="active",
        )
        db_session.add_all([model, doc, valid, instruction_noise, media_noise, progress_noise])
        await db_session.flush()

        resp = await client.get("/api/context/digest")
        assert resp.status_code == 200
        titles = {card["title"] for card in resp.json()["cards"]}

        assert "Decision: Keep graph zoom inside board" in titles
        assert "Decision: base_instructions" not in titles
        assert "Blocker: ./" not in titles
        assert not any("runInBand" in title for title in titles)

    async def test_context_digest_treats_agent_risk_as_risk_not_critical_blocker(self, client, db_session):
        model = Model(id=uuid4(), name="Codex session risk")
        doc = SourceDocument(
            id=uuid4(),
            source_type="agent_session",
            external_id="codex:session:risk",
            content="Codex session with one risk.",
            metadata_json=json.dumps({"tool": "codex", "session_id": "risk"}),
        )
        risk = Component(
            id=uuid4(),
            model_id=model.id,
            source_document_id=doc.id,
            name="Risk: Docker packaging still needs verification",
            value="Docker packaging still needs verification before release.",
            fact_type="blocker",
            confidence=0.82,
            status="active",
        )
        db_session.add_all([model, doc, risk])
        await db_session.flush()

        resp = await client.get("/api/context/digest")
        assert resp.status_code == 200
        data = resp.json()
        card = next(card for card in data["cards"] if card["title"] == "Risk: Docker packaging still needs verification")

        assert card["type"] == "risk"
        assert data["health"]["status"] != "critical"


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
