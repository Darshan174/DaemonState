from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select

from app.agents.context_pack import ContextPackAgent
from app.agents.gap_detector import GapDetectorAgent
from app.agents.relationship_agent import RelationshipAgent
from app.agents.semantic_linker import SemanticRelationshipLinker
from app.models import Component, Model, Relationship, SourceDocument


async def test_gap_detector_normalizes_legacy_plural_model_names(db_session):
    decisions = Model(id=uuid4(), name="Decisions")
    actions = Model(id=uuid4(), name="Actions")
    doc = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="legacy-agent-test",
        content="Decision and task",
        metadata_json="{}",
    )
    decision = Component(
        id=uuid4(),
        model_id=decisions.id,
        source_document_id=doc.id,
        name="Use Postgres",
        value="Use Postgres for production",
        fact_type="decision",
        confidence=0.9,
        status="active",
    )
    task = Component(
        id=uuid4(),
        model_id=actions.id,
        source_document_id=doc.id,
        name="Provision database",
        value="Provision the production database",
        fact_type="task",
        confidence=0.9,
        status="active",
    )
    rel = Relationship(
        id=uuid4(),
        source_component_id=decision.id,
        target_component_id=task.id,
        relationship_type="depends_on",
    )
    db_session.add_all([decisions, actions, doc, decision, task, rel])
    await db_session.flush()

    report = await GapDetectorAgent(db_session).run()

    assert report.stats["by_type"]["Decision"] == 1
    assert report.stats["by_type"]["Task"] == 1
    assert not any(g.category == "unimplemented_decision" for g in report.gaps)


async def test_relationship_agent_persists_high_confidence_suggestions(db_session, monkeypatch):
    model = Model(id=uuid4(), name="Decision")
    doc = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="relationship-agent-test",
        content="Decision and task",
        metadata_json="{}",
    )
    source = Component(
        id=uuid4(),
        model_id=model.id,
        source_document_id=doc.id,
        name="Use Postgres",
        value="Use Postgres for production",
        fact_type="decision",
        confidence=0.9,
        status="active",
    )
    target = Component(
        id=uuid4(),
        model_id=model.id,
        source_document_id=doc.id,
        name="Provision database",
        value="Provision the production database",
        fact_type="task",
        confidence=0.9,
        status="active",
    )
    db_session.add_all([model, doc, source, target])
    await db_session.flush()

    async def fake_discover(self, components, relationships):
        return {
            "suggested_relationships": [{
                "source_name": "Use Postgres",
                "target_name": "Provision database",
                "relationship_type": "implements",
                "confidence": 0.82,
                "reasoning": "The task implements the database decision.",
            }],
            "duplicates": [],
        }

    monkeypatch.setattr(RelationshipAgent, "_ai_discover", fake_discover)

    report = await RelationshipAgent(db_session, api_key="test", model="test-model").run()

    assert "Persisted 1" in report.message
    rels = list((await db_session.execute(
        Relationship.__table__.select()
    )).mappings())
    assert len(rels) == 1
    assert rels[0]["relationship_type"] == "implemented_in"
    assert rels[0]["confidence"] == 0.82
    assert rels[0]["status"] == "proposed"


async def test_semantic_linker_creates_proposed_cross_source_edges(db_session):
    model = Model(id=uuid4(), name="Issue")
    slack_doc = SourceDocument(
        id=uuid4(),
        source_type="slack",
        external_id="semantic-slack",
        content="Stripe webhook failures are blocking checkout.",
        metadata_json="{}",
    )
    github_doc = SourceDocument(
        id=uuid4(),
        source_type="github",
        external_id="semantic-github",
        content="Issue: Stripe webhook checkout failures.",
        metadata_json="{}",
    )
    source = Component(
        id=uuid4(),
        model_id=model.id,
        source_document_id=slack_doc.id,
        name="Slack Stripe webhook complaint",
        value="Customer reports Stripe webhook failures blocking checkout",
        fact_type="risk",
        confidence=0.9,
        status="active",
        embedding=json.dumps([1.0, 0.0, 0.0]),
    )
    target = Component(
        id=uuid4(),
        model_id=model.id,
        source_document_id=github_doc.id,
        name="GitHub Stripe webhook issue",
        value="Fix Stripe webhook failures in checkout",
        fact_type="issue",
        confidence=0.9,
        status="active",
        embedding=json.dumps([0.97, 0.03, 0.0]),
    )
    db_session.add_all([model, slack_doc, github_doc, source, target])
    await db_session.flush()

    created = await SemanticRelationshipLinker(db_session, threshold=0.9).create_relationships()

    rels = list(await db_session.scalars(select(Relationship)))
    assert created == 1
    assert len(rels) == 1
    assert rels[0].relationship_type == "related_to"
    assert rels[0].status == "proposed"
    assert rels[0].origin == "ai_proposed"
    assert "Semantic similarity" in rels[0].evidence


async def test_relationship_agent_candidate_pairs_are_not_limited_to_six_per_type(db_session):
    model = Model(id=uuid4(), name="Task")
    db_session.add(model)
    await db_session.flush()

    for idx in range(8):
        slack_doc = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id=f"slack-{idx}",
            content=f"Task topic {idx}",
            metadata_json="{}",
        )
        github_doc = SourceDocument(
            id=uuid4(),
            source_type="github",
            external_id=f"github-{idx}",
            content=f"Task topic {idx}",
            metadata_json="{}",
        )
        vector = [0.0] * 10
        vector[idx] = 1.0
        db_session.add_all([
            slack_doc,
            github_doc,
            Component(
                id=uuid4(),
                model_id=model.id,
                source_document_id=slack_doc.id,
                name=f"Slack task {idx}",
                value=f"Slack task {idx}",
                fact_type="task",
                confidence=0.9,
                status="active",
                embedding=json.dumps(vector),
            ),
            Component(
                id=uuid4(),
                model_id=model.id,
                source_document_id=github_doc.id,
                name=f"GitHub task {idx}",
                value=f"GitHub task {idx}",
                fact_type="task",
                confidence=0.9,
                status="active",
                embedding=json.dumps(vector),
            ),
        ])
    await db_session.flush()

    candidates = await RelationshipAgent(db_session, api_key="test", model="test-model")._candidate_pairs()
    names = {(candidate.source.name, candidate.target.name) for candidate in candidates}

    assert ("Slack task 7", "GitHub task 7") in names


async def test_context_pack_can_scope_to_selected_component_and_neighbors(db_session):
    task_model = Model(id=uuid4(), name="Task")
    decision_model = Model(id=uuid4(), name="Decision")
    doc = SourceDocument(
        id=uuid4(),
        source_type="github_issue",
        external_id="context-pack-selected",
        content="Selected task and related decision.",
        metadata_json="{}",
    )
    selected = Component(
        id=uuid4(),
        model_id=task_model.id,
        source_document_id=doc.id,
        name="Build Board graph",
        value="Build the source-first Board graph",
        fact_type="task",
        temporal="current",
        confidence=0.9,
        status="active",
    )
    neighbor = Component(
        id=uuid4(),
        model_id=decision_model.id,
        source_document_id=doc.id,
        name="Board default",
        value="Board is the default graph mode",
        fact_type="decision",
        confidence=0.9,
        status="active",
    )
    unrelated = Component(
        id=uuid4(),
        model_id=task_model.id,
        source_document_id=doc.id,
        name="Unrelated task",
        value="This should not be in the selected context pack",
        fact_type="task",
        confidence=0.9,
        status="active",
    )
    rel = Relationship(
        id=uuid4(),
        source_component_id=selected.id,
        target_component_id=neighbor.id,
        relationship_type="depends_on",
        evidence="Board task depends on the product decision.",
        origin="deterministic",
    )
    db_session.add_all([task_model, decision_model, doc, selected, neighbor, unrelated, rel])
    await db_session.flush()

    pack = await ContextPackAgent(db_session).run(component_ids=[selected.id])

    assert pack.entity_count == 2
    assert "Build the source-first Board graph" in pack.content
    assert "Board is the default graph mode" in pack.content
    assert "This should not be in the selected context pack" not in pack.content
