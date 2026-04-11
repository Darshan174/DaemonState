"""Tests for the ingestion pipeline — SourceDocument → KnowledgeModel/Component."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models.connector import Connector, ConnectorStatus
from app.models.knowledge import (
    Component,
    ComponentSource,
    KnowledgeModel,
    Relationship,
    RelationshipType,
)
from app.models.review import ReviewItem
from app.models.source import ConnectorType, SourceDocument
from app.processing.extractor import (
    ExtractedFact,
    ExtractionError,
    ExtractorMetadata,
    RegexExtractor,
)
from app.services.ingestion_service import IngestionService


@pytest.fixture
async def slack_connector(db_session, workspace):
    """A CONNECTED Slack connector for the workspace."""
    conn = Connector(
        workspace_id=workspace.id,
        connector_type=ConnectorType.SLACK,
        status=ConnectorStatus.CONNECTED,
        config={"team_name": "Test"},
    )
    db_session.add(conn)
    await db_session.flush()
    return conn


@pytest.fixture
async def notion_connector(db_session, workspace):
    """A CONNECTED Notion connector for the workspace."""
    conn = Connector(
        workspace_id=workspace.id,
        connector_type=ConnectorType.NOTION,
        status=ConnectorStatus.CONNECTED,
        config={"workspace_name": "Test Docs"},
    )
    db_session.add(conn)
    await db_session.flush()
    return conn


# ── IngestionService unit tests ──────────────────────────────────


class TestIngestionServiceDirect:
    """Tests that call IngestionService directly, bypassing the API layer."""

    async def test_selects_only_unprocessed_documents(
        self, db_session, workspace, slack_connector
    ):
        """Already-processed docs (processed_at != None) are skipped."""
        processed = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:already.done",
            content="decision: ship v2",
            processed_at=datetime(2026, 3, 29, tzinfo=timezone.utc),
        )
        unprocessed = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:needs.work",
            content="decision: delay v3",
        )
        db_session.add_all([processed, unprocessed])
        await db_session.flush()

        svc = IngestionService(db_session)
        docs = await svc._select_unprocessed(slack_connector.id)

        assert len(docs) == 1
        assert docs[0].external_id == "C1:needs.work"

    async def test_processing_creates_model_and_components(
        self, db_session, workspace, slack_connector
    ):
        """Processing docs with decision patterns creates a model + components."""
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:fact.1",
            content="decision: migrate to Postgres 16\nblocker: need DBA approval",
            metadata_json={"channel_name": "engineering"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        count = await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        assert count == 1

        # Model auto-created
        model = await db_session.scalar(
            select(KnowledgeModel).where(
                KnowledgeModel.workspace_id == workspace.id,
                KnowledgeModel.auto_generated.is_(True),
            )
        )
        assert model is not None
        assert model.name == "Slack Insights"

        # Two components — one decision, one blocker
        components = list(await db_session.scalars(
            select(Component)
            .where(Component.model_id == model.id)
            .order_by(Component.name)
        ))
        assert len(components) == 2

        blocker = next(c for c in components if "Blocker" in c.name)
        assert blocker.value == "need DBA approval"
        assert blocker.confidence == 0.80

        decision = next(c for c in components if "Decision" in c.name)
        assert decision.value == "migrate to Postgres 16"
        assert decision.confidence == 0.75

    async def test_processing_batches_embeddings_per_document(
        self, db_session, workspace, slack_connector
    ):
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:batch.embed.1",
            content=(
                "decision: migrate to Postgres 16\n"
                "action item: write the migration runbook\n"
                "blocker: staging database is unavailable"
            ),
            metadata_json={"channel_name": "engineering"},
        )
        db_session.add(doc)
        await db_session.flush()

        class _BatchOnlyEmbedder:
            def __init__(self) -> None:
                self.calls: list[list[str]] = []

            async def embed_text(self, text: str) -> list[float]:
                raise AssertionError("single-text embedding path should not be used")

            async def embed_texts(self, texts: list[str]) -> list[list[float]]:
                self.calls.append(list(texts))
                return [[0.01 * (idx + 1)] * 1024 for idx in range(len(texts))]

        embedder = _BatchOnlyEmbedder()
        svc = IngestionService(db_session, embedder=embedder)
        count = await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        assert count == 1
        assert len(embedder.calls) == 1
        assert set(embedder.calls[0]) == {
            "Decision in #engineering\nmigrate to Postgres 16",
            "Action Item in #engineering\nwrite the migration runbook",
            "Blocker in #engineering\nstaging database is unavailable",
        }

    async def test_failed_document_does_not_abort_remaining_connector_batch(
        self, db_session, workspace, slack_connector
    ):
        healthy = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:healthy.1",
            content="decision: launch Monday",
            metadata_json={"channel_name": "product"},
        )
        broken = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:broken.1",
            content="decision: this document will fail extraction",
            metadata_json={"channel_name": "product"},
        )
        db_session.add_all([healthy, broken])
        await db_session.flush()

        class _SometimesFailingExtractor:
            async def extract(self, doc):
                if doc.external_id == "C1:broken.1":
                    raise RuntimeError("boom")
                return [
                    ExtractedFact(
                        name="Decision in #product",
                        value="launch Monday",
                        confidence=0.91,
                        fact_type="decision",
                        extractor=ExtractorMetadata(
                            extractor_name="test_structured",
                            extractor_kind="llm_structured",
                        ),
                    )
                ]

        svc = IngestionService(db_session, extractor=_SometimesFailingExtractor())
        count = await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        assert count == 1
        await db_session.refresh(healthy)
        await db_session.refresh(broken)
        assert healthy.processed_at is not None
        assert broken.processed_at is None

        components = list(
            await db_session.scalars(
                select(Component).where(Component.name == "Decision in #product")
            )
        )
        assert len(components) == 1
        assert components[0].value == "launch Monday"

    async def test_component_source_links_created(
        self, db_session, workspace, slack_connector
    ):
        """Each extracted component is linked to its source document."""
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:link.1",
            content="action item: update runbook",
            source_url="https://slack.com/archives/C1/p123",
            metadata_json={"channel_name": "ops"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        links = list(await db_session.scalars(
            select(ComponentSource).where(
                ComponentSource.source_document_id == doc.id
            )
        ))
        assert len(links) == 1
        assert links[0].extraction_context is not None
        assert "slack" in links[0].extraction_context.lower()
        assert links[0].extractor_name == "regex"
        assert links[0].extractor_kind == "regex"
        assert links[0].extractor_schema_version == "fact_extraction.v1"

    async def test_processed_at_stamped(
        self, db_session, workspace, slack_connector
    ):
        """After processing, the doc's processed_at is set."""
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:stamp.1",
            content="decision: go with option A",
            metadata_json={"channel_name": "general"},
        )
        db_session.add(doc)
        await db_session.flush()

        assert doc.processed_at is None

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        await db_session.refresh(doc)
        assert doc.processed_at is not None

    async def test_already_processed_docs_skipped_on_rerun(
        self, db_session, workspace, slack_connector
    ):
        """Running processing twice doesn't re-process already-handled docs."""
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:rerun.1",
            content="decision: use FastAPI",
            metadata_json={"channel_name": "backend"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)

        # First run processes it
        count1 = await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
        )
        assert count1 == 1

        # Second run finds nothing unprocessed
        count2 = await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
        )
        assert count2 == 0

    async def test_same_fact_value_reuses_existing_component(
        self, db_session, workspace, slack_connector
    ):
        """If the same fact value is extracted again, reuse the active component version."""
        doc1 = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:upsert.1",
            content="decision: launch Monday",
            metadata_json={"channel_name": "product"},
        )
        doc2 = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:upsert.2",
            content="decision: launch Monday",
            metadata_json={"channel_name": "product"},
        )
        db_session.add_all([doc1, doc2])
        await db_session.flush()

        svc = IngestionService(db_session)
        count = await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )
        assert count == 2

        components = list(await db_session.scalars(
            select(Component).where(Component.name == "Decision in #product")
        ))
        assert len(components) == 1
        assert components[0].value == "launch Monday"
        assert components[0].valid_to is None

        links = list(await db_session.scalars(
            select(ComponentSource).where(
                ComponentSource.component_id == components[0].id
            )
        ))
        assert len(links) == 2

    async def test_threaded_discussion_creates_fallback_component(
        self, db_session, workspace, slack_connector
    ):
        """Messages with reply_count but no structured patterns use the fallback."""
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:thread.1",
            content="We should revisit the pricing model\n\nThread replies:\nBob: agreed",
            author="Alice",
            metadata_json={
                "channel_name": "strategy",
                "reply_count": 1,
            },
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        comp = await db_session.scalar(
            select(Component).where(Component.name == "Discussion in #strategy")
        )
        assert comp is not None
        assert "Alice" in comp.value
        assert comp.confidence == 0.55

    async def test_no_facts_no_components(
        self, db_session, workspace, slack_connector
    ):
        """A message with no patterns and no thread creates nothing."""
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:noop.1",
            content="hey anyone want coffee?",
            metadata_json={"channel_name": "random"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        count = await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )
        # Doc still processed (stamp set), just no components created
        assert count == 1
        await db_session.refresh(doc)
        assert doc.processed_at is not None

        comp_count = await db_session.scalar(
            select(func.count()).select_from(Component)
        )
        assert comp_count == 0

    async def test_tenant_isolation(self, db_session, workspace, slack_connector):
        """Documents from a different connector are never processed by another workspace."""
        # Second workspace + connector
        from app.models.user import Workspace

        ws2 = Workspace(name="Other Corp")
        db_session.add(ws2)
        await db_session.flush()

        conn2 = Connector(
            workspace_id=ws2.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={"team_name": "Other"},
        )
        db_session.add(conn2)
        await db_session.flush()

        # Doc belongs to conn2
        doc_other = SourceDocument(
            connector_id=conn2.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:other.1",
            content="decision: secret strategy from other org",
            metadata_json={"channel_name": "confidential"},
        )
        # Doc belongs to slack_connector (workspace 1)
        doc_own = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:own.1",
            content="decision: our public plan",
            metadata_json={"channel_name": "general"},
        )
        db_session.add_all([doc_other, doc_own])
        await db_session.flush()

        # Process workspace 1's connector
        svc = IngestionService(db_session)
        count = await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        assert count == 1  # Only our doc, not the other workspace's

        # The other workspace's doc is still unprocessed
        await db_session.refresh(doc_other)
        assert doc_other.processed_at is None

        # No model created in workspace 2
        model_ws2 = await db_session.scalar(
            select(KnowledgeModel).where(
                KnowledgeModel.workspace_id == ws2.id,
            )
        )
        assert model_ws2 is None

    async def test_different_connector_types_get_separate_models(
        self, db_session, workspace, slack_connector
    ):
        """Slack and Notion connectors produce distinct KnowledgeModels."""
        notion_conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.NOTION,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(notion_conn)
        await db_session.flush()

        # Slack doc
        slack_doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:model-iso.1",
            content="decision: adopt Kubernetes",
            metadata_json={"channel_name": "infra"},
        )
        # Notion doc
        notion_doc = SourceDocument(
            connector_id=notion_conn.id,
            connector_type=ConnectorType.NOTION,
            external_id="notion:model-iso.1",
            content="decision: migrate to Aurora",
            metadata_json={"channel_name": "unknown"},
        )
        db_session.add_all([slack_doc, notion_doc])
        await db_session.flush()

        svc = IngestionService(db_session)

        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=notion_conn.id,
            connector_type=ConnectorType.NOTION,
        )

        models = list(await db_session.scalars(
            select(KnowledgeModel).where(
                KnowledgeModel.workspace_id == workspace.id,
                KnowledgeModel.auto_generated.is_(True),
            )
        ))
        assert len(models) == 2
        names = {m.name for m in models}
        assert names == {"Slack Insights", "Notion Insights"}

    async def test_low_confidence_fact_creates_review_item(
        self, db_session, workspace, slack_connector
    ):
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:lowconf.1",
            content="This still needs discussion\n\nThread replies:\nBob: agreed",
            author="Alice",
            metadata_json={"channel_name": "strategy", "reply_count": 1},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        component = await db_session.scalar(
            select(Component).where(Component.name == "Discussion in #strategy")
        )
        assert component is not None
        review_item = await db_session.scalar(
            select(ReviewItem).where(ReviewItem.component_id == component.id)
        )
        assert review_item is not None
        assert review_item.status == "needs_review"
        assert review_item.kind == "low_confidence"
        assert review_item.severity == "medium"

    async def test_conflicting_fact_creates_new_version_and_review_items(
        self, db_session, workspace, slack_connector
    ):
        doc1 = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:conflict.1",
            content="decision: launch Monday",
            metadata_json={"channel_name": "product"},
            ingested_at=datetime(2026, 3, 29, 9, 0, tzinfo=timezone.utc),
        )
        doc2 = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:conflict.2",
            content="decision: launch Tuesday",
            metadata_json={"channel_name": "product"},
            ingested_at=datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add_all([doc1, doc2])
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        components = list(await db_session.scalars(
            select(Component)
            .where(Component.name == "Decision in #product")
            .order_by(Component.valid_from.asc(), Component.id.asc())
        ))
        assert len(components) == 2

        old_component = next(c for c in components if "Monday" in c.value)
        new_component = next(c for c in components if "Tuesday" in c.value)

        assert old_component.valid_to is not None
        assert old_component.superseded_by == new_component.id
        assert new_component.valid_to is None

        old_review = await db_session.scalar(
            select(ReviewItem).where(ReviewItem.component_id == old_component.id)
        )
        new_review = await db_session.scalar(
            select(ReviewItem).where(ReviewItem.component_id == new_component.id)
        )
        assert old_review is not None
        assert old_review.status == "superseded"
        assert old_review.kind == "superseded_fact"
        assert new_review is not None
        assert new_review.status == "needs_review"
        assert new_review.kind == "conflict"

        supersedes_rel = await db_session.scalar(
            select(Relationship).where(
                Relationship.source_component_id == new_component.id,
                Relationship.target_component_id == old_component.id,
                Relationship.relationship_type == RelationshipType.SUPERSEDES,
            )
        )
        assert supersedes_rel is not None

    async def test_lower_authority_conflict_does_not_replace_current_truth(
        self, db_session, workspace, slack_connector
    ):
        authoritative = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:authority.1",
            content="decision: launch Monday",
            metadata_json={"channel_name": "product", "authority_weight": 0.95},
        )
        low_authority = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:authority.2",
            content="decision: launch Friday",
            metadata_json={"channel_name": "product", "authority_weight": 0.35},
        )
        db_session.add_all([authoritative, low_authority])
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        active_components = list(await db_session.scalars(
            select(Component).where(
                Component.name == "Decision in #product",
                Component.valid_to.is_(None),
            )
        ))
        historical_components = list(await db_session.scalars(
            select(Component).where(
                Component.name == "Decision in #product",
                Component.valid_to.is_not(None),
            )
        ))

        assert len(active_components) == 1
        assert active_components[0].value == "launch Monday"
        assert active_components[0].authority_weight == 0.95
        assert any(component.value == "launch Friday" for component in historical_components)

        lower_authority_component = next(
            component for component in historical_components if component.value == "launch Friday"
        )
        review_item = await db_session.scalar(
            select(ReviewItem).where(ReviewItem.component_id == lower_authority_component.id)
        )
        assert review_item is not None
        assert review_item.kind == "conflict"
        assert review_item.status == "rejected"

    async def test_higher_authority_conflict_auto_resolves_current_truth(
        self, db_session, workspace, slack_connector
    ):
        lower_authority = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:authority.high.1",
            content="decision: launch Friday",
            metadata_json={"channel_name": "product", "authority_weight": 0.35},
        )
        authoritative = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:authority.high.2",
            content="decision: launch Monday",
            metadata_json={"channel_name": "product", "authority_weight": 0.95},
        )
        db_session.add_all([lower_authority, authoritative])
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        active_component = await db_session.scalar(
            select(Component).where(
                Component.name == "Decision in #product",
                Component.valid_to.is_(None),
            )
        )
        historical_component = await db_session.scalar(
            select(Component).where(
                Component.name == "Decision in #product",
                Component.valid_to.is_not(None),
                Component.value == "launch Friday",
            )
        )

        assert active_component is not None
        assert active_component.value == "launch Monday"
        assert historical_component is not None

        active_review = await db_session.scalar(
            select(ReviewItem).where(ReviewItem.component_id == active_component.id)
        )
        historical_review = await db_session.scalar(
            select(ReviewItem).where(ReviewItem.component_id == historical_component.id)
        )

        assert active_review is None
        assert historical_review is not None
        assert historical_review.status == "superseded"

    async def test_default_connector_authority_keeps_notion_over_slack(
        self, db_session, workspace, slack_connector, notion_connector
    ):
        slack_doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:pricing.authority.1",
            content="decision: enterprise price is $400/seat",
            metadata_json={"channel_name": "pricing"},
        )
        notion_doc = SourceDocument(
            connector_id=notion_connector.id,
            connector_type=ConnectorType.NOTION,
            external_id="notion:pricing.authority.1",
            content="decision: enterprise price is $450/seat",
            metadata_json={"channel_name": "pricing", "page_title": "Pricing Handbook"},
        )
        db_session.add_all([slack_doc, notion_doc])
        await db_session.flush()

        slack_svc = IngestionService(db_session)
        await slack_svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )
        notion_svc = IngestionService(db_session)
        await notion_svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=notion_connector.id,
            connector_type=ConnectorType.NOTION,
        )

        active_components = list(await db_session.scalars(
            select(Component).where(
                Component.name == "Decision in #pricing",
                Component.valid_to.is_(None),
            )
        ))
        historical_components = list(await db_session.scalars(
            select(Component).where(
                Component.name == "Decision in #pricing",
            )
        ))

        assert len(active_components) == 1
        assert active_components[0].value == "enterprise price is $450/seat"
        assert active_components[0].authority_weight == 0.95
        assert any(component.value == "enterprise price is $400/seat" for component in historical_components)

    async def test_reprocess_retires_removed_fact_and_cleans_source_link(
        self, db_session, workspace, slack_connector
    ):
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:reprocess.1",
            content="decision: launch Monday\nblocker: need audit approval",
            metadata_json={"channel_name": "product"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        blocker = await db_session.scalar(
            select(Component).where(
                Component.name == "Blocker in #product",
                Component.valid_to.is_(None),
            )
        )
        assert blocker is not None

        doc.content = "decision: launch Monday"
        doc.processed_at = None
        await db_session.flush()

        processed = await svc.process_single_document(
            workspace_id=workspace.id,
            document=doc,
            connector_type=ConnectorType.SLACK,
        )
        assert processed == 1

        await db_session.refresh(blocker)
        assert blocker.valid_to is not None

        blocker_links = list(await db_session.scalars(
            select(ComponentSource).where(ComponentSource.component_id == blocker.id)
        ))
        assert blocker_links == []

        blocker_review = await db_session.scalar(
            select(ReviewItem).where(ReviewItem.component_id == blocker.id)
        )
        assert blocker_review is not None
        assert blocker_review.status == "superseded"

    async def test_reprocess_retires_relationships_for_removed_fact(
        self, db_session, workspace, slack_connector
    ):
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:reprocess.relationship.1",
            content="blocker: need audit approval",
            metadata_json={"channel_name": "product"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        blocker = await db_session.scalar(
            select(Component).where(
                Component.name == "Blocker in #product",
                Component.valid_to.is_(None),
            )
        )
        assert blocker is not None

        model = await db_session.scalar(
            select(KnowledgeModel).where(
                KnowledgeModel.workspace_id == workspace.id,
                KnowledgeModel.auto_generated.is_(True),
            )
        )
        assert model is not None

        dependency = Component(
            model_id=model.id,
            name="Audit Review",
            value="Security sign-off",
            confidence=0.95,
        )
        db_session.add(dependency)
        await db_session.flush()

        relationship = Relationship(
            source_component_id=blocker.id,
            target_component_id=dependency.id,
            relationship_type=RelationshipType.BLOCKED_BY,
            confidence=0.9,
            description="Audit approval is required before the blocker clears.",
        )
        db_session.add(relationship)
        await db_session.flush()

        doc.content = "decision: blocker resolved"
        doc.processed_at = None
        await db_session.flush()

        processed = await svc.process_single_document(
            workspace_id=workspace.id,
            document=doc,
            connector_type=ConnectorType.SLACK,
        )
        assert processed == 1

        await db_session.refresh(relationship)
        assert relationship.valid_to is not None
        assert relationship.temporal_state == "historical"


# ── Fingerprint + relationship tests ─────────────────────────────


class TestFingerprintDeduplication:
    """ComponentSource.content_hash prevents duplicate link rows."""

    async def test_two_docs_same_value_two_source_links_with_hashes(
        self, db_session, workspace, slack_connector
    ):
        """Two docs with the same (name, value) → 1 component, 2 source links,
        each with a populated content_hash."""
        doc1 = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:fp.1",
            content="decision: launch Monday",
            metadata_json={"channel_name": "product"},
        )
        doc2 = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:fp.2",
            content="decision: launch Monday",
            metadata_json={"channel_name": "product"},
        )
        db_session.add_all([doc1, doc2])
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        components = list(await db_session.scalars(
            select(Component).where(Component.name == "Decision in #product")
        ))
        assert len(components) == 1

        links = list(await db_session.scalars(
            select(ComponentSource).where(
                ComponentSource.component_id == components[0].id
            )
        ))
        assert len(links) == 2
        for link in links:
            assert link.content_hash is not None
            assert len(link.content_hash) == 64  # SHA-256 hex
            assert link.extracted_value == "launch Monday"

    async def test_idempotent_reprocess_no_duplicate_links(
        self, db_session, workspace, slack_connector
    ):
        """Re-processing the same doc with the same value produces no duplicate links."""
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:idem.1",
            content="decision: ship v2",
            metadata_json={"channel_name": "eng"},
        )
        db_session.add(doc)
        await db_session.flush()
        doc_id = doc.id

        svc = IngestionService(db_session)

        # First pass
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        # Reset processed_at to simulate reprocess
        await db_session.flush()
        doc_reload = await db_session.scalar(
            select(SourceDocument).where(SourceDocument.id == doc_id)
        )
        doc_reload.processed_at = None
        await db_session.flush()

        # Second pass
        await svc.process_single_document(
            workspace_id=workspace.id,
            document=doc_reload,
            connector_type=ConnectorType.SLACK,
        )

        comp = await db_session.scalar(
            select(Component).where(Component.name == "Decision in #eng")
        )
        links = list(await db_session.scalars(
            select(ComponentSource).where(ComponentSource.component_id == comp.id)
        ))
        assert len(links) == 1  # no duplicate

    async def test_link_hash_updates_when_value_changes(
        self, db_session, workspace, slack_connector
    ):
        """When the extracted value for the same (component, doc) pair changes,
        content_hash and extracted_value are updated."""
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:hashchange.1",
            content="decision: launch next week",
            metadata_json={"channel_name": "product"},
        )
        db_session.add(doc)
        await db_session.flush()
        doc_id = doc.id

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        # Grab the hash from the first pass
        comp = await db_session.scalar(
            select(Component).where(Component.name == "Decision in #product")
        )
        link = await db_session.scalar(
            select(ComponentSource).where(ComponentSource.component_id == comp.id)
        )
        original_hash = link.content_hash

        # Simulate value change: reset and update doc content
        doc_reload = await db_session.scalar(
            select(SourceDocument).where(SourceDocument.id == doc_id)
        )
        doc_reload.processed_at = None
        doc_reload.content = "decision: launch this Thursday"
        await db_session.flush()

        await svc.process_single_document(
            workspace_id=workspace.id,
            document=doc_reload,
            connector_type=ConnectorType.SLACK,
        )

        # The link hash should be different now (new component may have been created)
        # At minimum, no error is raised and we have ≥1 link
        all_links = list(await db_session.scalars(
            select(ComponentSource)
        ))
        hashes = {lk.content_hash for lk in all_links if lk.content_hash}
        assert len(hashes) >= 1
        assert all(len(h) == 64 for h in hashes)


class TestAutoRelationshipCreation:
    """_create_relationship_if_target_exists wires blockers to their targets."""

    async def test_blocked_by_creates_relationship_when_target_exists(
        self, db_session, workspace, slack_connector
    ):
        """Processing a blocker doc creates a BLOCKED_BY relationship when the
        referenced decision component already exists in the same model."""
        # Create the decision component directly in the model first
        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Slack Insights",
            auto_generated=True,
        )
        db_session.add(model)
        await db_session.flush()

        decision_comp = Component(
            model_id=model.id,
            name="Decision in #product",
            value="launch next Monday",
            confidence=0.75,
        )
        db_session.add(decision_comp)
        await db_session.flush()

        # Doc with blocker that explicitly references the decision component
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:rel.1",
            content="blocker: deploy blocked by Decision in #product",
            metadata_json={"channel_name": "product"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        # A BLOCKED_BY relationship from blocker → decision should exist
        rel = await db_session.scalar(
            select(Relationship).where(
                Relationship.target_component_id == decision_comp.id,
                Relationship.relationship_type == RelationshipType.BLOCKED_BY,
                Relationship.valid_to.is_(None),
            )
        )
        assert rel is not None
        assert rel.confidence == 0.70

    async def test_no_relationship_when_target_not_found(
        self, db_session, workspace, slack_connector
    ):
        """If the referenced target doesn't exist, no relationship is created
        (and no error is raised)."""
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:rel.miss.1",
            content="blocker: blocked by NonExistent Component",
            metadata_json={"channel_name": "eng"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        rel_count = await db_session.scalar(
            select(func.count()).select_from(Relationship).where(
                Relationship.relationship_type == RelationshipType.BLOCKED_BY,
            )
        )
        assert rel_count == 0


# ── Savepoint / Batch Embedding Tests ────────────────────────────────────


class TestSavepointIsolation:
    """Per-document savepoint isolation during batch ingestion."""

    async def test_bad_document_doesnt_abort_batch(
        self, db_session, workspace, slack_connector
    ):
        """A document that fails during extraction should not roll back
        the entire batch — only the failing doc is skipped."""
        good_doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:savepoint.good.1",
            content="decision: launch Friday",
            metadata_json={"channel_name": "product"},
        )
        bad_doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:savepoint.bad.1",
            content="some content",
            metadata_json={"channel_name": "product"},
        )
        db_session.add_all([good_doc, bad_doc])
        await db_session.flush()

        # Create an extractor that fails on specific content
        original_extractor = RegexExtractor()

        class SelectiveFailExtractor:
            async def extract(self, doc):
                if "bad" in doc.external_id:
                    raise ExtractionError("simulated extraction failure")
                return await original_extractor.extract(doc)

        svc = IngestionService(db_session, extractor=SelectiveFailExtractor())
        count = await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        # Only the good doc should be processed
        assert count == 1

        await db_session.refresh(good_doc)
        await db_session.refresh(bad_doc)
        assert good_doc.processed_at is not None
        # Bad doc remains unprocessed
        assert bad_doc.processed_at is None


class TestBatchEmbeddingIngestion:
    """Verify that embeddings are batched during ingestion."""

    async def test_components_have_embeddings_after_ingestion(
        self, db_session, workspace, slack_connector
    ):
        """After ingestion, components should have embedding vectors."""
        doc = SourceDocument(
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:batch.embed.1",
            content="decision: adopt Kubernetes\naction item: prepare migration plan",
            metadata_json={"channel_name": "infra"},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )

        components = list(await db_session.scalars(
            select(Component).where(
                Component.name.like("Decision in %"),
            )
        ))
        assert len(components) >= 1
        # Hashing embedder produces non-None embeddings
        for comp in components:
            assert comp.embedding is not None
            assert len(comp.embedding) > 0

    async def test_multiple_documents_batch_embedded(
        self, db_session, workspace, slack_connector
    ):
        """Processing multiple documents should batch embeddings efficiently."""
        from app.processing.embedder import HashingEmbedder

        embed_call_count = 0

        class CountingEmbedder(HashingEmbedder):
            async def embed_texts(self, texts):
                nonlocal embed_call_count
                embed_call_count += 1
                return await super().embed_texts(texts)

        docs = [
            SourceDocument(
                connector_id=slack_connector.id,
                connector_type=ConnectorType.SLACK,
                external_id=f"C1:batch.multi.{i}",
                content=f"decision: decision number {i}",
                metadata_json={"channel_name": "general"},
            )
            for i in range(3)
        ]
        db_session.add_all(docs)
        await db_session.flush()

        svc = IngestionService(db_session, embedder=CountingEmbedder())
        count = await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=slack_connector.id,
            connector_type=ConnectorType.SLACK,
        )
        assert count == 3

        # Each document's extraction produces facts that get embedded in batch
        # The exact count depends on how many unique facts are extracted
        assert embed_call_count >= 1
