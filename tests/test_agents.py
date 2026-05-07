from __future__ import annotations

from uuid import uuid4

from app.agents.gap_detector import GapDetectorAgent
from app.agents.relationship_agent import RelationshipAgent
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
