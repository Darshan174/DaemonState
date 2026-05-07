from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.models import Component, Model, Relationship, SourceDocument
from app.processing.extractor import ExtractedFact, ExtractedRelationship
from app.services.ingest import IngestionService


class TestCrossModelRelationships:
    async def test_creates_cross_model_relationship(self, db_session):
        model_a = Model(id=uuid4(), name="Pricing")
        model_b = Model(id=uuid4(), name="Security")
        db_session.add_all([model_a, model_b])
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="cross-test",
            content="Pricing depends on SOC2. SOC2 required.",
            metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        soc2 = Component(
            id=uuid4(), model_id=model_b.id, source_document_id=doc.id,
            name="SOC2 certification required",
            value="SOC2 is required before enterprise launch",
            fact_type="fact", confidence=0.85, status="active",
        )
        db_session.add(soc2)
        await db_session.flush()

        svc = IngestionService(db_session)
        component = Component(
            id=uuid4(), model_id=model_a.id, source_document_id=doc.id,
            name="Enterprise pricing $200/mo",
            value="Enterprise tier at $200/month",
            fact_type="fact", confidence=0.8, status="active",
        )
        db_session.add(component)
        await db_session.flush()

        rel = ExtractedRelationship(
            target_name="SOC2 certification required",
            relationship_type="depends_on",
            confidence=0.85,
        )
        await svc._create_relationship(component, rel)

        rels = (await db_session.scalars(
            select(Relationship).where(
                Relationship.source_component_id == component.id,
                Relationship.target_component_id == soc2.id,
                Relationship.relationship_type == "depends_on",
            )
        )).all()
        assert len(rels) == 1
        assert rels[0].confidence == 0.85
        assert rels[0].evidence is not None
        assert "depends_on" in rels[0].evidence

    async def test_same_model_relationship_still_works(self, db_session):
        model = Model(id=uuid4(), name="Pricing")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="same-test",
            content="Basic enables Pro. Pro tier is $80.",
            metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        basic = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Basic tier $20/mo",
            value="Basic plan at $20/month",
            fact_type="fact", confidence=0.8, status="active",
        )
        pro = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Pro tier $80/mo",
            value="Pro plan at $80/month",
            fact_type="fact", confidence=0.8, status="active",
        )
        db_session.add_all([basic, pro])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="Pro tier $80/mo",
            relationship_type="enables",
            confidence=0.75,
        )
        await svc._create_relationship(basic, rel)

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == basic.id)
        )).all()
        assert len(rels) == 1
        assert rels[0].target_component_id == pro.id


class TestConfidenceThreshold:
    async def test_skips_low_confidence_relationship(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="low-conf",
            content="Maybe related to X.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        source = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Source", value="source", fact_type="fact",
            confidence=0.5, status="active",
        )
        target = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Target", value="target", fact_type="fact",
            confidence=0.5, status="active",
        )
        db_session.add_all([source, target])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="Target",
            relationship_type="related_to",
            confidence=0.45,
        )
        await svc._create_relationship(source, rel)

        count = await db_session.scalar(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )
        assert count is None

    async def test_creates_relationship_at_threshold(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="threshold",
            content="A depends on B.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        source = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="A", value="Component A", fact_type="fact",
            confidence=0.8, status="active",
        )
        target = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="B", value="Component B", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add_all([source, target])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="B",
            relationship_type="depends_on",
            confidence=0.60,
        )
        await svc._create_relationship(source, rel)

        count = await db_session.scalar(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )
        assert count is not None


class TestDuplicatePrevention:
    async def test_no_duplicate_relationship(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="dup-test",
            content="A depends on B.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        source = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="A", value="A", fact_type="fact",
            confidence=0.8, status="active",
        )
        target = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="B", value="B", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add_all([source, target])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="B", relationship_type="depends_on", confidence=0.8,
        )

        await svc._create_relationship(source, rel)
        await svc._create_relationship(source, rel)

        rels = (await db_session.scalars(
            select(Relationship).where(
                Relationship.source_component_id == source.id,
                Relationship.target_component_id == target.id,
            )
        )).all()
        assert len(rels) == 1

    async def test_no_self_loops(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="self-test",
            content="A depends on A.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        component = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="A", value="A", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add(component)
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="A", relationship_type="depends_on", confidence=0.8,
        )
        await svc._create_relationship(component, rel)

        count = await db_session.scalar(
            select(Relationship).where(
                Relationship.source_component_id == component.id,
                Relationship.target_component_id == component.id,
            )
        )
        assert count is None


class TestTemporalHandling:
    async def test_future_component_gets_proposed_status(self, db_session):
        svc = IngestionService(db_session)
        model = await svc._get_or_create_model("Roadmap")

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="future",
            content="We plan to add SSO.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        fact = ExtractedFact(
            model_name="Roadmap", name="SSO support",
            value="We plan to add SSO support in Q4 2026",
            fact_type="fact", confidence=0.75, temporal_hint="future",
        )
        component = await svc._upsert_component(model, doc, fact)
        assert component.status == "proposed"

    async def test_past_component_gets_needs_review_status(self, db_session):
        svc = IngestionService(db_session)
        model = await svc._get_or_create_model("Pricing")

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="past",
            content="Old pricing was $10.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        fact = ExtractedFact(
            model_name="Pricing", name="Old price $10/mo",
            value="Previously the price was $10/month",
            fact_type="fact", confidence=0.65, temporal_hint="past",
        )
        component = await svc._upsert_component(model, doc, fact)
        assert component.status == "needs_review"

    async def test_current_component_defaults_to_active(self, db_session):
        svc = IngestionService(db_session)
        model = await svc._get_or_create_model("Pricing")

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="current",
            content="Pricing is $20/month.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        fact = ExtractedFact(
            model_name="Pricing", name="$20/mo tier",
            value="Pricing is $20/month",
            fact_type="fact", confidence=0.85, temporal_hint="current",
        )
        component = await svc._upsert_component(model, doc, fact)
        assert component.status == "active"


class TestFullIngestion:
    async def test_process_document_creates_components(self, db_session):
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="full",
            content="Decision: Use Postgres.\nAction: Set up CI/CD.\nBlocker: Need AWS access.",
            metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        count = await svc.process_document(doc.id)
        assert count > 0

        models = (await db_session.scalars(select(Model))).all()
        assert len(models) > 0

        components = (await db_session.scalars(
            select(Component).where(Component.source_document_id == doc.id)
        )).all()
        assert len(components) == count

    async def test_process_document_skips_already_processed(self, db_session):
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="processed",
            content="Decision: Use Postgres.",
            metadata_json="{}",
            processed_at=datetime.now(timezone.utc),
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        count = await svc.process_document(doc.id)
        assert count == 0

    async def test_upsert_updates_confidence(self, db_session):
        model = Model(id=uuid4(), name="Pricing")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="upsert",
            content="Pricing is $20.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        existing = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="$20/mo tier", value="Pricing is $20/month",
            fact_type="fact", confidence=0.5, status="active",
        )
        db_session.add(existing)
        await db_session.flush()

        svc = IngestionService(db_session)
        fact = ExtractedFact(
            model_name="Pricing", name="$20/mo tier",
            value="Pricing is $20/month", fact_type="fact",
            confidence=0.9, temporal_hint="current",
        )
        result = await svc._upsert_component(model, doc, fact)
        assert result.id == existing.id
        assert result.confidence == 0.9

    async def test_upsert_matches_across_statuses(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="status-match",
            content="Test.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        existing = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Test item", value="Test value",
            fact_type="fact", confidence=0.8, status="needs_review",
        )
        db_session.add(existing)
        await db_session.flush()

        svc = IngestionService(db_session)
        fact = ExtractedFact(
            model_name="Test", name="Test item", value="Test value",
            fact_type="fact", confidence=0.85, temporal_hint="current",
        )
        result = await svc._upsert_component(model, doc, fact)
        assert result.id == existing.id


class TestRelationshipEvidence:
    async def test_relationship_stores_evidence_from_extraction(self, db_session):
        model = Model(id=uuid4(), name="Features")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="evidence-test",
            content="SSO depends on OAuth2.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        source = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="SSO support", value="SSO module",
            fact_type="fact", confidence=0.8, status="active",
        )
        target = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="OAuth2 auth", value="OAuth2 module",
            fact_type="fact", confidence=0.8, status="active",
        )
        db_session.add_all([source, target])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="OAuth2 auth",
            relationship_type="depends_on",
            confidence=0.85,
            evidence="SSO requires OAuth2 for authentication flow",
        )
        await svc._create_relationship(source, rel)

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )).all()
        assert len(rels) == 1
        assert rels[0].evidence == "SSO requires OAuth2 for authentication flow"

    async def test_relationship_without_evidence_generates_template(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="no-evidence",
            content="A enables B.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        source = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="A", value="Component A", fact_type="fact",
            confidence=0.8, status="active",
        )
        target = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="B", value="Component B", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add_all([source, target])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="B",
            relationship_type="enables",
            confidence=0.75,
        )
        await svc._create_relationship(source, rel)

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )).all()
        assert len(rels) == 1
        assert "'A' enables 'B'" in rels[0].evidence

    async def test_relationship_stores_confidence(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="rel-conf",
            content="X depends on Y.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        source = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="X", value="Component X", fact_type="fact",
            confidence=0.8, status="active",
        )
        target = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Y", value="Component Y", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add_all([source, target])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="Y",
            relationship_type="depends_on",
            confidence=0.77,
        )
        await svc._create_relationship(source, rel)

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )).all()
        assert len(rels) == 1
        assert rels[0].confidence == 0.77


class TestCrossModelTargetResolution:
    async def test_prefers_same_model_target_over_cross_model(self, db_session):
        model_a = Model(id=uuid4(), name="Pricing")
        model_b = Model(id=uuid4(), name="Security")
        db_session.add_all([model_a, model_b])
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="cross-lookup",
            content="Pricing depends on Enterprise readiness.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        target_cross = Component(
            id=uuid4(), model_id=model_b.id, source_document_id=doc.id,
            name="Enterprise readiness", value="Enterprise is ready",
            fact_type="fact", confidence=0.9, status="active",
        )
        target_same = Component(
            id=uuid4(), model_id=model_a.id, source_document_id=doc.id,
            name="Enterprise readiness", value="Enterprise is almost ready",
            fact_type="fact", confidence=0.6, status="active",
        )
        source = Component(
            id=uuid4(), model_id=model_a.id, source_document_id=doc.id,
            name="Enterprise pricing $500/mo", value="Enterprise tier",
            fact_type="fact", confidence=0.8, status="active",
        )
        db_session.add_all([target_cross, target_same, source])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="Enterprise readiness",
            relationship_type="depends_on",
            confidence=0.85,
        )
        await svc._create_relationship(source, rel)

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )).all()
        assert len(rels) == 1
        assert rels[0].target_component_id == target_same.id

    async def test_falls_back_to_cross_model_when_no_same_model_match(self, db_session):
        model_a = Model(id=uuid4(), name="Pricing")
        model_b = Model(id=uuid4(), name="Security")
        db_session.add_all([model_a, model_b])
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="cross-fallback",
            content="Pricing depends on SOC2.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        target_cross = Component(
            id=uuid4(), model_id=model_b.id, source_document_id=doc.id,
            name="SOC2 certification", value="SOC2 required",
            fact_type="fact", confidence=0.85, status="active",
        )
        source = Component(
            id=uuid4(), model_id=model_a.id, source_document_id=doc.id,
            name="Enterprise pricing", value="Enterprise tier",
            fact_type="fact", confidence=0.8, status="active",
        )
        db_session.add_all([target_cross, source])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="SOC2 certification",
            relationship_type="depends_on",
            confidence=0.85,
        )
        await svc._create_relationship(source, rel)

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )).all()
        assert len(rels) == 1
        assert rels[0].target_component_id == target_cross.id

    async def test_creates_same_model_relationship_when_target_in_same_model(self, db_session):
        model = Model(id=uuid4(), name="Features")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="same-model-lookup",
            content="Dark mode depends on Theme system.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        target = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Theme system", value="Theme infrastructure",
            fact_type="fact", confidence=0.85, status="active",
        )
        source = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Dark mode UI", value="Dark mode toggle",
            fact_type="fact", confidence=0.8, status="active",
        )
        db_session.add_all([target, source])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="Theme system",
            relationship_type="depends_on",
            confidence=0.75,
        )
        await svc._create_relationship(source, rel)

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )).all()
        assert len(rels) == 1
        assert rels[0].target_component_id == target.id


class TestNonActiveTargetRelationships:
    async def test_allows_needs_review_target(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="needs-review-target",
            content="A depends on B.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        source = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="A", value="Component A", fact_type="fact",
            confidence=0.8, status="active",
        )
        target = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="B", value="Component B", fact_type="fact",
            confidence=0.5, status="needs_review",
        )
        db_session.add_all([source, target])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="B",
            relationship_type="depends_on",
            confidence=0.85,
        )
        await svc._create_relationship(source, rel)

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )).all()
        assert len(rels) == 1

    async def test_allows_proposed_target(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="proposed-target",
            content="SSO depends on OAuth2.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        source = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="SSO", value="SSO module", fact_type="fact",
            confidence=0.8, status="active",
        )
        target = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="OAuth2", value="OAuth2 future", fact_type="fact",
            confidence=0.75, status="proposed",
        )
        db_session.add_all([source, target])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="OAuth2",
            relationship_type="depends_on",
            confidence=0.85,
        )
        await svc._create_relationship(source, rel)

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )).all()
        assert len(rels) == 1

    async def test_excludes_stale_target(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="stale-target",
            content="A depends on B.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        source = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="A", value="Component A", fact_type="fact",
            confidence=0.8, status="active",
        )
        target = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="B", value="Component B", fact_type="fact",
            confidence=0.3, status="stale",
        )
        db_session.add_all([source, target])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="B",
            relationship_type="depends_on",
            confidence=0.85,
        )
        await svc._create_relationship(source, rel)

        count = await db_session.scalar(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )
        assert count is None


class TestConfidenceFiltering:
    async def test_skips_relationship_below_0_6(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="below-threshold",
            content="Maybe A relates to B.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        source = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="A", value="Component A", fact_type="fact",
            confidence=0.8, status="active",
        )
        target = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="B", value="Component B", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add_all([source, target])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="B",
            relationship_type="related_to",
            confidence=0.59,
        )
        await svc._create_relationship(source, rel)

        count = await db_session.scalar(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )
        assert count is None

    async def test_creates_relationship_at_exact_threshold(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="at-threshold",
            content="A blocks B.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        source = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="A", value="Component A", fact_type="fact",
            confidence=0.8, status="active",
        )
        target = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="B", value="Component B", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add_all([source, target])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="B",
            relationship_type="blocked_by",
            confidence=0.60,
        )
        await svc._create_relationship(source, rel)

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )).all()
        assert len(rels) == 1
        assert rels[0].confidence == 0.60
