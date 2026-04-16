"""Regression tests for the unified truth/provenance layer.

Covers:
- as-of historical queries correctness
- stale fact detection (is_stale, valid_to)
- conflicting fact resolution
- review-gated fact exclusion
- provenance in all major workflow responses
- cross-workflow truth invariants (Query, Brief, Timeline, Decisions agree on truth)
- superseded facts visibility consistency
- rejected facts exclusion everywhere
- historical facts not mislabeled as stale at as-of time
- freshness semantics relative to requested time
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from app.models.connector import Connector, ConnectorStatus
from app.models.knowledge import (
    Component,
    ComponentSource,
    KnowledgeModel,
)
from app.models.review import ReviewItem
from app.models.source import ConnectorType, SourceDocument
from app.services.truth_visibility import (
    is_component_visible_as_of,
    is_component_visible_in_current_truth,
    is_component_visible_in_history,
)


async def _seed_base(db_session, workspace):
    """Create a workspace with connector, model, and source doc."""
    connector = Connector(
        workspace_id=workspace.id,
        connector_type=ConnectorType.SLACK,
        status=ConnectorStatus.CONNECTED,
        config={},
    )
    db_session.add(connector)
    await db_session.flush()

    model = KnowledgeModel(
        workspace_id=workspace.id,
        name="Truth Tests",
        description="Model for truth layer regression tests",
    )
    db_session.add(model)
    await db_session.flush()

    doc = SourceDocument(
        connector_id=connector.id,
        connector_type=ConnectorType.SLACK,
        external_id="slack:truth-test",
        content="decision: enterprise price is $600/seat",
        author="founder@example.com",
        metadata_json={"channel_name": "pricing"},
    )
    db_session.add(doc)
    await db_session.flush()

    return {"connector": connector, "model": model, "doc": doc}


async def _link_source(db_session, component, document):
    db_session.add(
        ComponentSource(
            component_id=component.id,
            source_document_id=document.id,
            extraction_context="Test extraction",
            extracted_value=component.value,
            extractor_name="regex",
            extractor_kind="regex",
            extractor_schema_version="fact_extraction.v1",
        )
    )
    await db_session.flush()


class TestDeletedSourceVisibility:
    """Deleting the only source for a fact should remove it from founder workflows."""

    async def test_query_excludes_component_when_only_source_is_deleted(
        self, client, db_session, workspace
    ):
        seeded = await _seed_base(db_session, workspace)

        component = Component(
            model_id=seeded["model"].id,
            name="Starter Plan",
            value="$29/month",
            confidence=0.93,
            authority_weight=0.9,
            valid_from=datetime(2026, 3, 1, tzinfo=UTC),
            last_verified_at=datetime(2026, 3, 20, tzinfo=UTC),
        )
        db_session.add(component)
        await db_session.flush()
        await _link_source(db_session, component, seeded["doc"])
        await db_session.commit()

        before = await client.post(
            "/api/query",
            json={
                "question": "What is the Starter Plan?",
                "workspace_id": str(workspace.id),
            },
        )
        assert before.status_code == 200
        assert before.json()["components"]

        deleted = await client.delete(
            f"/api/source-documents/{seeded['doc'].id}",
            params={"workspace_id": str(workspace.id)},
        )
        assert deleted.status_code == 204

        after = await client.post(
            "/api/query",
            json={
                "question": "What is the Starter Plan?",
                "workspace_id": str(workspace.id),
            },
        )
        assert after.status_code == 200
        body = after.json()
        assert body["components"] == []
        assert body["sources"] == []


class TestAsOfQueries:
    """Historical (as-of) queries return the correct fact version."""

    async def test_as_of_returns_historical_version(self, client, db_session, workspace):
        """When querying as_of a past date, the historical component is returned."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Pricing",
            description="Pricing model",
        )
        db_session.add(model)
        await db_session.flush()

        old = Component(
            model_id=model.id,
            name="Enterprise Plan",
            value="$500/seat",
            confidence=0.9,
            authority_weight=0.9,
            valid_from=datetime(2026, 3, 1, tzinfo=UTC),
            valid_to=datetime(2026, 3, 20, tzinfo=UTC),
            last_verified_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        new = Component(
            model_id=model.id,
            name="Enterprise Plan",
            value="$600/seat",
            confidence=0.92,
            authority_weight=0.9,
            valid_from=datetime(2026, 3, 20, tzinfo=UTC),
            last_verified_at=datetime(2026, 3, 20, tzinfo=UTC),
        )
        db_session.add_all([old, new])
        await db_session.flush()
        old.superseded_by_id = new.id
        db_session.add(
            ReviewItem(
                component_id=old.id,
                status="superseded",
                severity="low",
                kind="superseded_fact",
                title="Enterprise Plan is now historical",
                summary="Superseded by a newer plan.",
                confidence=old.confidence,
            )
        )
        await db_session.flush()

        current = await client.post(
            "/api/query",
            json={
                "question": "What is the enterprise plan price?",
                "workspace_id": str(workspace.id),
            },
        )
        historical = await client.post(
            "/api/query",
            json={
                "question": "What is the enterprise plan price?",
                "workspace_id": str(workspace.id),
                "as_of": "2026-03-10T00:00:00Z",
            },
        )

        assert current.status_code == 200
        assert historical.status_code == 200
        assert current.json()["components"][0]["value"] == "$600/seat"
        assert historical.json()["components"][0]["value"] == "$500/seat"
        assert historical.json()["answer"].startswith("As of 2026-03-10")

    async def test_as_of_excludes_rejected_components(self, client, db_session, workspace):
        """Rejected components are never returned, even in as-of queries."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Pricing",
            description="Pricing model",
        )
        db_session.add(model)
        await db_session.flush()

        rejected = Component(
            model_id=model.id,
            name="Enterprise Plan",
            value="$300/seat",
            confidence=0.8,
            authority_weight=0.5,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            last_verified_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        db_session.add(rejected)
        await db_session.flush()
        db_session.add(
            ReviewItem(
                component_id=rejected.id,
                status="rejected",
                severity="high",
                kind="conflict",
                title="Rejected price",
                summary="This price was rejected",
                confidence=0.8,
            )
        )
        await db_session.commit()

        result = await client.post(
            "/api/query",
            json={
                "question": "What is the enterprise price?",
                "workspace_id": str(workspace.id),
                "as_of": "2026-02-15T00:00:00Z",
            },
        )
        assert result.status_code == 200
        # Rejected component should not appear
        body = result.json()
        assert not body["components"] or all(
            "$300" not in c["value"] for c in body["components"]
        )


class TestStaleFacts:
    """Stale facts are correctly identified in freshness scoring."""

    async def test_current_truth_returns_current_freshness(self, client, db_session, workspace):
        """Query service returns CURRENT freshness for recently verified components."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Policy",
            description="Policy model",
        )
        db_session.add(model)
        await db_session.flush()

        now = datetime.now(timezone.utc)
        current = Component(
            model_id=model.id,
            name="Current Policy",
            value="Current policy value",
            confidence=0.9,
            valid_from=now,
            last_verified_at=now,
        )
        db_session.add(current)
        await db_session.commit()

        resp = await client.post(
            "/api/query",
            json={
                "question": "What is the policy?",
                "workspace_id": str(workspace.id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["components"]
        assert body["components"][0]["value"] == "Current policy value"
        assert body["freshness"] == "current"


class TestConflictingFacts:
    """Conflicting facts create proper review items and supersession."""

    async def test_conflicting_facts_query_shows_review_status(self, client, db_session, workspace):
        """Query returns components with their review status visible."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Pricing",
            description="Pricing model",
        )
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            connector_id=connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="slack:pricing-conflict",
            content="Enterprise pricing: $600 per seat",
            metadata_json={"channel_name": "pricing"},
        )
        db_session.add(doc)
        await db_session.flush()

        first = Component(
            model_id=model.id,
            name="Enterprise Price",
            value="$400/seat",
            confidence=0.9,
            authority_weight=0.75,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2026, 2, 1, tzinfo=UTC),
            last_verified_at=datetime(2026, 1, 15, tzinfo=UTC),
        )
        second = Component(
            model_id=model.id,
            name="Enterprise Price",
            value="$600/seat",
            confidence=0.85,
            authority_weight=0.75,
            valid_from=datetime(2026, 2, 1, tzinfo=UTC),
            last_verified_at=datetime.now(timezone.utc),
        )
        db_session.add_all([first, second])
        await db_session.flush()
        first.superseded_by_id = second.id
        db_session.add(
            ComponentSource(
                component_id=second.id,
                source_document_id=doc.id,
                extraction_context="Test",
                extracted_value=second.value,
                extractor_name="regex",
                extractor_kind="regex",
                extractor_schema_version="fact_extraction.v1",
            )
        )
        db_session.add_all([
            ReviewItem(
                component_id=first.id,
                status="superseded",
                severity="low",
                kind="superseded_fact",
                title="Price superseded",
                summary="Changed from $400 to $600",
                confidence=0.9,
            ),
            ReviewItem(
                component_id=second.id,
                status="needs_review",
                severity="high",
                kind="conflict",
                title="Price conflict",
                summary="Two different prices found",
                confidence=0.85,
            ),
        ])
        await db_session.commit()

        resp = await client.post(
            "/api/query",
            json={
                "question": "What is the enterprise price?",
                "workspace_id": str(workspace.id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # Current truth excludes superseded; needs_review component is visible but penalized
        assert body["components"]
        comp = body["components"][0]
        assert comp["value"] == "$600/seat"
        assert comp["review_status"] == "needs_review"


class TestReviewGatedFacts:
    """Rejected and superseded facts are excluded from current truth.

    These are tested at the API level (see test_briefing.py
    test_workflow_views_hide_rejected_and_superseded_current_decisions)
    and via the unit tests in TestTruthVisibilityFunctions below.
    """
    pass


class TestTruthVisibilityFunctions:
    """Unit tests for truth_visibility.py helper functions."""

    def _make_component(self, **kwargs):
        """Create a minimal Component-like object for testing."""
        defaults = {
            "valid_to": None,
            "valid_from": datetime(2026, 1, 1, tzinfo=UTC),
            "review_item": None,
            "is_stale": False,
            "last_verified_at": datetime(2026, 3, 1, tzinfo=UTC),
        }
        defaults.update(kwargs)

        class _ReviewItemProxy:
            def __init__(self, status):
                self.status = status

        class _Component:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)
                # Add review_status property that delegates to review_item
                @property
                def review_status(self):
                    if self.review_item is None:
                        return None
                    return self.review_item.status
                type(self).review_status = review_status

        if "review_status" in defaults:
            status = defaults.pop("review_status")
            defaults["review_item"] = _ReviewItemProxy(status)

        return _Component(**defaults)

    def test_current_truth_excludes_historical(self):
        c = self._make_component(valid_to=datetime(2026, 2, 1, tzinfo=UTC))
        assert is_component_visible_in_current_truth(c) is False

    def test_current_truth_excludes_rejected(self):
        c = self._make_component(review_status="rejected")
        assert is_component_visible_in_current_truth(c) is False

    def test_current_truth_excludes_superseded(self):
        c = self._make_component(review_status="superseded")
        assert is_component_visible_in_current_truth(c) is False

    def test_current_truth_includes_approved(self):
        c = self._make_component(review_status="approved")
        assert is_component_visible_in_current_truth(c) is True

    def test_current_truth_includes_no_review(self):
        c = self._make_component()
        assert is_component_visible_in_current_truth(c) is True

    def test_as_of_excludes_rejected(self):
        c = self._make_component(
            review_status="rejected",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert is_component_visible_as_of(c, as_of=datetime(2026, 2, 1, tzinfo=UTC)) is False

    def test_as_of_includes_superseded_if_valid_at_time(self):
        """Superseded components that were valid at the as_of time should be visible."""
        c = self._make_component(
            review_status="superseded",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2026, 3, 1, tzinfo=UTC),
        )
        # At Feb 15, this component was still valid
        assert is_component_visible_as_of(c, as_of=datetime(2026, 2, 15, tzinfo=UTC)) is True
        # At Apr 1, it has expired
        assert is_component_visible_as_of(c, as_of=datetime(2026, 4, 1, tzinfo=UTC)) is False

    def test_history_includes_superseded(self):
        c = self._make_component(review_status="superseded")
        assert is_component_visible_in_history(c) is True

    def test_history_excludes_rejected(self):
        c = self._make_component(review_status="rejected")
        assert is_component_visible_in_history(c) is False


class TestProvenanceInWorkflows:
    """Provenance (source document IDs) is present in all major workflow responses."""

    async def test_founder_brief_fact_has_source_document_ids(self, client, workspace, db_session):
        """Founder brief facts include source_document_ids for provenance."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Brief Provenance",
            description="Test model",
        )
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            connector_id=connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="slack:prov-test",
            content="decision: launch next Tuesday",
            metadata_json={"channel_name": "general"},
        )
        db_session.add(doc)
        await db_session.flush()

        component = Component(
            model_id=model.id,
            name="Decision in #general",
            value="Launch next Tuesday.",
            confidence=0.9,
            authority_weight=0.75,
            valid_from=datetime.now(timezone.utc) - timedelta(hours=1),
            last_verified_at=datetime.now(timezone.utc),
        )
        db_session.add(component)
        await db_session.flush()

        db_session.add(
            ComponentSource(
                component_id=component.id,
                source_document_id=doc.id,
                extraction_context="Test",
                extracted_value=component.value,
                extractor_name="regex",
                extractor_kind="regex",
                extractor_schema_version="fact_extraction.v1",
            )
        )
        await db_session.commit()

        resp = await client.get(
            "/api/founder-brief",
            params={"workspace_id": str(workspace.id), "lookback_days": 7},
        )
        assert resp.status_code == 200
        body = resp.json()
        facts = body.get("changed_facts", [])
        assert facts
        fact = facts[0]
        assert "source_document_ids" in fact
        assert str(doc.id) in fact["source_document_ids"]

    async def test_risk_items_have_source_document_ids(self, client, workspace, db_session):
        """Stale high-risk items in founder brief include source_document_ids for provenance."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Risk Test",
            description="Test model",
        )
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            connector_id=connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="slack:risk-test",
            content="blocker: need security review",
            metadata_json={"channel_name": "engineering"},
        )
        db_session.add(doc)
        await db_session.flush()

        component = Component(
            model_id=model.id,
            name="Blocker in #engineering",
            value="Need security review",
            confidence=0.4,
            authority_weight=0.75,
            valid_from=datetime.now(timezone.utc) - timedelta(hours=2),
            last_verified_at=datetime.now(timezone.utc),
            is_stale=True,
        )
        db_session.add(component)
        await db_session.flush()

        db_session.add(
            ComponentSource(
                component_id=component.id,
                source_document_id=doc.id,
                extraction_context="Test",
                extracted_value=component.value,
                extractor_name="regex",
                extractor_kind="regex",
                extractor_schema_version="fact_extraction.v1",
            )
        )
        db_session.add(
            ReviewItem(
                component_id=component.id,
                status="needs_review",
                severity="medium",
                kind="low_confidence",
                title="Low confidence blocker",
                summary="Needs review",
                confidence=0.4,
            )
        )
        await db_session.commit()

        resp = await client.get(
            "/api/founder-brief",
            params={"workspace_id": str(workspace.id), "lookback_days": 7},
        )
        assert resp.status_code == 200
        body = resp.json()
        risks = body.get("stale_high_risk_items", [])
        assert risks
        risk = risks[0]
        assert "source_document_ids" in risk
        assert str(doc.id) in risk["source_document_ids"]


class TestAsOfFreshness:
    """as_of queries compute freshness relative to the requested time, not wall-clock now."""

    async def test_as_of_freshness_uses_requested_time(self, client, db_session, workspace):
        """A historical fact verified recently at the as_of time should not be stale."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Pricing",
            description="Pricing model",
        )
        db_session.add(model)
        await db_session.flush()

        # Historical component: verified 5 days before as_of time (2026-03-15)
        # as_of is 2026-03-20, so age = 5 days → should be CURRENT
        old = Component(
            model_id=model.id,
            name="Enterprise Plan",
            value="$500/seat",
            confidence=0.9,
            authority_weight=0.9,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2026, 3, 20, tzinfo=UTC),
            last_verified_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        db_session.add(old)
        await db_session.flush()
        db_session.add(
            ReviewItem(
                component_id=old.id,
                status="superseded",
                severity="low",
                kind="superseded_fact",
                title="Old price",
                summary="Price changed",
                confidence=0.9,
            )
        )
        await db_session.commit()

        # Query as_of March 18 — 3 days after last_verified_at → should be CURRENT
        resp = await client.post(
            "/api/query",
            json={
                "question": "What is the enterprise price?",
                "workspace_id": str(workspace.id),
                "as_of": "2026-03-18T00:00:00Z",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["components"]
        assert body["components"][0]["value"] == "$500/seat"
        # Freshness should be CURRENT (5 days old at as_of time), not stale
        assert body["freshness"] == "current"

    async def test_query_sources_include_source_document_id(self, client, db_session, workspace):
        """Query result sources include source_document_id for provenance linking."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Pricing",
            description="Pricing model",
        )
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            connector_id=connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="slack:source-prov",
            content="Enterprise pricing: $600/seat",
            author="ceo@example.com",
            source_url="https://slack.example.com/pricing",
            metadata_json={"channel_name": "pricing"},
        )
        db_session.add(doc)
        await db_session.flush()

        component = Component(
            model_id=model.id,
            name="Enterprise Plan",
            value="$600/seat",
            confidence=0.9,
            authority_weight=0.75,
            valid_from=datetime.now(timezone.utc) - timedelta(hours=1),
            last_verified_at=datetime.now(timezone.utc),
        )
        db_session.add(component)
        await db_session.flush()

        db_session.add(
            ComponentSource(
                component_id=component.id,
                source_document_id=doc.id,
                extraction_context="Test",
                extracted_value=component.value,
                extractor_name="regex",
                extractor_kind="regex",
                extractor_schema_version="fact_extraction.v1",
            )
        )
        await db_session.commit()

        resp = await client.post(
            "/api/query",
            json={
                "question": "What is enterprise pricing?",
                "workspace_id": str(workspace.id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["sources"]
        source = body["sources"][0]
        assert source["source_document_id"] is not None
        assert source["source_document_id"] == str(doc.id)


class TestCombinedTemporalFilters:
    """Tests for combined as_of + max_age_days and scoring edge cases."""

    async def test_as_of_plus_max_age_days_filters_correctly(self, client, db_session, workspace):
        """as_of with max_age_days should filter relative to as_of, not wall-clock now."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Pricing",
            description="Pricing model",
        )
        db_session.add(model)
        await db_session.flush()

        # Component verified 20 days before as_of — outside 7-day window relative to as_of
        old = Component(
            model_id=model.id,
            name="Enterprise Pricing",
            value="$500/seat",
            confidence=0.9,
            authority_weight=0.9,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2026, 3, 20, tzinfo=UTC),
            last_verified_at=datetime(2026, 3, 1, tzinfo=UTC),  # 19 days before as_of
        )
        # Component verified 5 days before as_of — inside 7-day window relative to as_of
        new = Component(
            model_id=model.id,
            name="Pricing Pro Plan",
            value="$99/mo",
            confidence=0.9,
            authority_weight=0.9,
            valid_from=datetime(2026, 3, 10, tzinfo=UTC),
            last_verified_at=datetime(2026, 3, 15, tzinfo=UTC),  # 5 days before as_of
        )
        db_session.add_all([old, new])
        await db_session.flush()
        old.superseded_by_id = new.id
        await db_session.flush()
        db_session.add_all([
            ReviewItem(
                component_id=old.id,
                status="superseded",
                severity="low",
                kind="superseded_fact",
                title="Old price",
                summary="Changed",
                confidence=0.9,
            ),
            ReviewItem(
                component_id=new.id,
                status="approved",
                severity="low",
                kind="fact_update",
                title="Pro plan",
                summary="Approved",
                confidence=0.9,
            ),
        ])
        await db_session.commit()

        # Query as_of March 20 with max_age_days=7:
        # - old component: last_verified_at=Mar 1 → 19 days before as_of → EXCLUDED
        # - new component: last_verified_at=Mar 15 → 5 days before as_of → INCLUDED
        resp = await client.post(
            "/api/query",
            json={
                "question": "What is the pricing?",
                "workspace_id": str(workspace.id),
                "as_of": "2026-03-20T00:00:00Z",
                "max_age_days": 7,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        values = {c["value"] for c in body["components"]}
        assert "$500/seat" not in values, "Old component should be excluded (19 days > 7 day window)"
        assert "$99/mo" in values, "New component should be included (5 days < 7 day window)"

    async def test_as_of_scoring_freshness_uses_historical_reference(self, client, db_session, workspace):
        """Scoring freshness adjustment should use as_of, not wall-clock now.

        A component verified 5 days before as_of should get a positive
        freshness bonus, not a stale penalty — even though wall-clock
        now is months later.
        """
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Pricing",
            description="Pricing model",
        )
        db_session.add(model)
        await db_session.flush()

        # Historical component verified 5 days before as_of
        old = Component(
            model_id=model.id,
            name="Enterprise Plan",
            value="$500/seat",
            confidence=0.9,
            authority_weight=0.9,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2026, 3, 20, tzinfo=UTC),
            last_verified_at=datetime(2026, 3, 15, tzinfo=UTC),  # 5 days before as_of
        )
        db_session.add(old)
        await db_session.flush()
        db_session.add(
            ReviewItem(
                component_id=old.id,
                status="superseded",
                severity="low",
                kind="superseded_fact",
                title="Old price",
                summary="Changed",
                confidence=0.9,
            )
        )
        await db_session.commit()

        # as_of March 18 — 3 days after verification → should be scored as "fresh"
        # (5 days old at as_of time), not stale
        resp = await client.post(
            "/api/query",
            json={
                "question": "What is the enterprise price?",
                "workspace_id": str(workspace.id),
                "as_of": "2026-03-18T00:00:00Z",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["components"]
        assert body["components"][0]["value"] == "$500/seat"
        assert body["freshness"] == "current"
        # Confidence should be reasonable since the scoring treats it as fresh
        assert body["confidence"] > 0.0


class TestCrossWorkflowTruthInvariants:
    """Cross-workflow truth invariants: Query, Brief, Timeline, and Decisions
    must all agree on what constitutes the current truth.

    These tests verify that the same fact resolves the same way across
    all workflow views, not just isolated query cases.
    """

    async def _seed_full_scenario(self, client, db_session, workspace):
        """Create a complete scenario with current, superseded, and rejected facts."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Cross-Workflow Test",
            description="Model for cross-workflow truth invariant tests",
        )
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            connector_id=connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="slack:cross-workflow",
            content="decision: launch on March 20\ndecision: launch on April 1",
            metadata_json={"channel_name": "product"},
        )
        db_session.add(doc)
        await db_session.flush()

        # Rejected fact
        rejected = Component(
            model_id=model.id,
            name="Launch Decision",
            value="Launch on March 1.",
            confidence=0.8,
            authority_weight=0.7,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2026, 1, 15, tzinfo=UTC),
            last_verified_at=datetime(2026, 1, 10, tzinfo=UTC),
        )
        # Superseded fact
        superseded = Component(
            model_id=model.id,
            name="Launch Decision",
            value="Launch on March 20.",
            confidence=0.85,
            authority_weight=0.8,
            valid_from=datetime(2026, 1, 15, tzinfo=UTC),
            valid_to=datetime(2026, 2, 1, tzinfo=UTC),
            last_verified_at=datetime(2026, 1, 20, tzinfo=UTC),
        )
        # Current fact
        current = Component(
            model_id=model.id,
            name="Launch Decision",
            value="Launch on April 1.",
            confidence=0.92,
            authority_weight=0.9,
            valid_from=datetime(2026, 2, 1, tzinfo=UTC),
            last_verified_at=datetime.now(timezone.utc),
        )
        db_session.add_all([rejected, superseded, current])
        await db_session.flush()

        superseded.superseded_by_id = current.id
        await db_session.flush()

        db_session.add_all([
            ReviewItem(
                component_id=rejected.id,
                status="rejected",
                severity="high",
                kind="conflict",
                title="Rejected launch date",
                summary="This date was rejected as unrealistic.",
                confidence=0.8,
            ),
            ReviewItem(
                component_id=superseded.id,
                status="superseded",
                severity="low",
                kind="superseded_fact",
                title="Superseded launch date",
                summary="Superseded by newer planning.",
                confidence=0.85,
            ),
            ReviewItem(
                component_id=current.id,
                status="approved",
                severity="low",
                kind="fact_update",
                title="Approved launch date",
                summary="April 1 is the approved launch date.",
                confidence=0.92,
            ),
        ])

        for component in (rejected, superseded, current):
            db_session.add(
                ComponentSource(
                    component_id=component.id,
                    source_document_id=doc.id,
                    extraction_context="Test",
                    extracted_value=component.value,
                    extractor_name="regex",
                    extractor_kind="regex",
                    extractor_schema_version="fact_extraction.v1",
                )
            )
        await db_session.commit()

        return {
            "connector": connector,
            "model": model,
            "doc": doc,
            "rejected": rejected,
            "superseded": superseded,
            "current": current,
        }

    async def test_query_brief_timeline_agree_on_current_truth(
        self, client, db_session, workspace
    ):
        """Query, Founder Brief, and Timeline must all show the same current fact."""
        scenario = await self._seed_full_scenario(client, db_session, workspace)
        current = scenario["current"]

        # Query current truth
        query_resp = await client.post(
            "/api/query",
            json={
                "question": "What is the launch decision?",
                "workspace_id": str(workspace.id),
            },
        )
        assert query_resp.status_code == 200
        query_body = query_resp.json()
        query_values = {c["value"] for c in query_body["components"]}
        assert "Launch on April 1." in query_values, "Query must return current truth"
        assert "Launch on March 20." not in query_values, "Query must exclude superseded"
        assert "Launch on March 1." not in query_values, "Query must exclude rejected"

        # Founder brief current facts
        brief_resp = await client.get(
            "/api/founder-brief",
            params={"workspace_id": str(workspace.id), "lookback_days": 90},
        )
        assert brief_resp.status_code == 200
        brief_body = brief_resp.json()
        brief_values = {f["value"] for f in brief_body["changed_facts"]}
        assert "Launch on April 1." in brief_values, "Brief must include current truth"
        assert "Launch on March 1." not in brief_values, "Brief must exclude rejected"

        # Timeline decision events
        timeline_resp = await client.get(
            "/api/timeline",
            params={"workspace_id": str(workspace.id), "limit": 100},
        )
        assert timeline_resp.status_code == 200
        timeline_body = timeline_resp.json()
        decision_events = [
            e for e in timeline_body["items"] if e["event_type"] == "decision_change"
        ]
        # Timeline shows current + superseded (but NOT rejected)
        timeline_values = {e["summary"] for e in decision_events}
        assert "Launch on April 1." in timeline_values, "Timeline must include current truth"
        assert "Launch on March 20." in timeline_values, "Timeline must include superseded (history view)"
        assert "Launch on March 1." not in timeline_values, "Timeline must exclude rejected"

    async def test_rejected_excluded_everywhere(
        self, client, db_session, workspace
    ):
        """Rejected facts must not appear in any default workflow view."""
        scenario = await self._seed_full_scenario(client, db_session, workspace)

        # Query (current)
        query_resp = await client.post(
            "/api/query",
            json={
                "question": "What is the launch decision?",
                "workspace_id": str(workspace.id),
            },
        )
        assert "March 1" not in str(query_resp.json())

        # Query (as_of) — rejected should also be excluded from as-of
        query_asof_resp = await client.post(
            "/api/query",
            json={
                "question": "What is the launch decision?",
                "workspace_id": str(workspace.id),
                "as_of": "2026-01-10T00:00:00Z",
            },
        )
        assert "March 1" not in str(query_asof_resp.json()), (
            "Rejected fact must not appear in as-of query"
        )

        # Brief
        brief_resp = await client.get(
            "/api/founder-brief",
            params={"workspace_id": str(workspace.id), "lookback_days": 90},
        )
        assert "March 1" not in str(brief_resp.json())

        # Decisions list
        decisions_resp = await client.get(
            "/api/decisions",
            params={"workspace_id": str(workspace.id)},
        )
        assert "March 1" not in str(decisions_resp.json())

    async def test_superseded_visible_in_history_but_not_current(
        self, client, db_session, workspace
    ):
        """Superseded facts appear in history/timeline but NOT in current query/brief."""
        scenario = await self._seed_full_scenario(client, db_session, workspace)

        # Query (current) must NOT include superseded
        query_resp = await client.post(
            "/api/query",
            json={
                "question": "What is the launch decision?",
                "workspace_id": str(workspace.id),
            },
        )
        body = query_resp.json()
        assert "March 20" not in str(body), "Superseded must not appear in current query"

        # Decision history MUST include superseded
        decisions_resp = await client.get(
            "/api/decisions",
            params={"workspace_id": str(workspace.id), "include_historical": "true"},
        )
        hist_body = decisions_resp.json()
        hist_values = [e["value"] for e in hist_body]
        assert "Launch on March 20." in hist_values, "Superseded must appear in historical decisions"

    async def test_historical_fact_not_mislabeled_stale_at_asof_time(
        self, client, db_session, workspace
    ):
        """A historical fact that was recently verified at the as_of time
        should NOT be marked as stale — even though wall-clock now is much later."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Pricing",
            description="Pricing model",
        )
        db_session.add(model)
        await db_session.flush()

        # Historical component: verified on March 15, superseded on March 20
        # Today is months later, but at as_of March 18, this was current and fresh
        old = Component(
            model_id=model.id,
            name="Enterprise Plan",
            value="$500/seat",
            confidence=0.9,
            authority_weight=0.9,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2026, 3, 20, tzinfo=UTC),  # superseded after as_of
            last_verified_at=datetime(2026, 3, 15, tzinfo=UTC),
            is_stale=True,  # marked stale at supersession time
        )
        db_session.add(old)
        await db_session.flush()
        db_session.add(
            ReviewItem(
                component_id=old.id,
                status="superseded",
                severity="low",
                kind="superseded_fact",
                title="Old price",
                summary="Price changed",
                confidence=0.9,
            )
        )
        await db_session.commit()

        # Query as_of March 18 — before supersession, before staleness was relevant
        resp = await client.post(
            "/api/query",
            json={
                "question": "What is the enterprise price?",
                "workspace_id": str(workspace.id),
                "as_of": "2026-03-18T00:00:00Z",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["components"]
        assert body["components"][0]["value"] == "$500/seat"
        # Freshness should be CURRENT: at as_of time, this was the active truth
        # and was verified only 3 days before as_of
        assert body["freshness"] == "current", (
            "Historical fact should not be stale at as_of time when it was current truth"
        )


class TestPayloadConsistencyAcrossWorkflows:
    """Verify that review/truth metadata fields are consistent across
    Query, Brief, Timeline, and Decision payloads."""

    async def _seed_scenario(self, db_session, workspace):
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Payload Test",
            description="Test model",
        )
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            connector_id=connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="slack:payload-test",
            content="decision: use PostgreSQL",
            metadata_json={"channel_name": "engineering"},
        )
        db_session.add(doc)
        await db_session.flush()

        component = Component(
            model_id=model.id,
            name="Decision in #engineering",
            value="Use PostgreSQL.",
            confidence=0.9,
            authority_weight=0.85,
            valid_from=datetime.now(timezone.utc) - timedelta(hours=2),
            last_verified_at=datetime.now(timezone.utc),
        )
        db_session.add(component)
        await db_session.flush()

        review = ReviewItem(
            component_id=component.id,
            status="approved",
            severity="low",
            kind="fact_update",
            title="Approved DB choice",
            summary="PostgreSQL is the approved database.",
            confidence=0.9,
        )
        db_session.add(review)
        db_session.add(
            ComponentSource(
                component_id=component.id,
                source_document_id=doc.id,
                extraction_context="Test",
                extracted_value=component.value,
                extractor_name="regex",
                extractor_kind="regex",
                extractor_schema_version="fact_extraction.v1",
            )
        )
        await db_session.commit()

        return {
            "component": component,
            "doc": doc,
        }

    async def test_query_and_brief_share_review_status_and_source_ids(
        self, client, db_session, workspace
    ):
        """Query and Brief must return the same review_status and source_document_ids."""
        scenario = await self._seed_scenario(db_session, workspace)
        component = scenario["component"]
        doc = scenario["doc"]

        query_resp = await client.post(
            "/api/query",
            json={
                "question": "What is the database decision?",
                "workspace_id": str(workspace.id),
            },
        )
        assert query_resp.status_code == 200
        query_body = query_resp.json()
        query_comp = query_body["components"][0]

        brief_resp = await client.get(
            "/api/founder-brief",
            params={"workspace_id": str(workspace.id), "lookback_days": 7},
        )
        assert brief_resp.status_code == 200
        brief_body = brief_resp.json()
        brief_fact = brief_body["changed_facts"][0]

        # Same review_status
        assert query_comp["review_status"] == brief_fact["review_status"], (
            "Query and Brief must agree on review_status"
        )
        # Same source provenance
        assert str(doc.id) in brief_fact["source_document_ids"], (
            "Brief fact must include source document ID"
        )

    async def test_decision_and_timeline_share_temporal_state(
        self, client, db_session, workspace
    ):
        """Decision register and Timeline must agree on is_current/temporal_state."""
        scenario = await self._seed_scenario(db_session, workspace)
        component = scenario["component"]

        decisions_resp = await client.get(
            "/api/decisions",
            params={"workspace_id": str(workspace.id)},
        )
        assert decisions_resp.status_code == 200
        decision = decisions_resp.json()[0]
        assert decision["is_current"] is True
        assert decision["temporal_state"] is None  # current has no temporal_state

        timeline_resp = await client.get(
            "/api/timeline",
            params={"workspace_id": str(workspace.id), "limit": 50},
        )
        assert timeline_resp.status_code == 200
        decision_events = [
            e for e in timeline_resp.json()["items"]
            if e["event_type"] == "decision_change"
        ]
        assert decision_events, "Timeline must have decision events"
        # Current decision should be labeled as "current" status
        current_events = [e for e in decision_events if e["status"] == "current"]
        assert current_events, "Timeline must label current decision as 'current'"

    async def test_provenance_ids_aligned_across_query_brief_decisions(
        self, client, db_session, workspace
    ):
        """Source document IDs in query sources, brief facts, and decisions
        must all reference the same provenance."""
        scenario = await self._seed_scenario(db_session, workspace)
        doc = scenario["doc"]

        # Query sources
        query_resp = await client.post(
            "/api/query",
            json={
                "question": "What is the database decision?",
                "workspace_id": str(workspace.id),
            },
        )
        query_sources = query_resp.json()["sources"]
        query_source_ids = {s["source_document_id"] for s in query_sources if s.get("source_document_id")}
        assert str(doc.id) in query_source_ids, "Query sources must include source document"

        # Brief facts source_document_ids
        brief_resp = await client.get(
            "/api/founder-brief",
            params={"workspace_id": str(workspace.id), "lookback_days": 7},
        )
        brief_facts = brief_resp.json()["changed_facts"]
        assert brief_facts, "Brief must have changed facts"
        brief_doc_ids = brief_facts[0].get("source_document_ids", [])
        assert str(doc.id) in brief_doc_ids, "Brief facts must include source document IDs"

        # Decisions rationale_sources
        decisions_resp = await client.get(
            "/api/decisions",
            params={"workspace_id": str(workspace.id)},
        )
        decisions = decisions_resp.json()
        assert decisions, "Decisions must not be empty"
        decision = decisions[0]
        rationale_source_ids = {
            str(rs["source_document_id"])
            for rs in decision.get("rationale_sources", [])
        }
        assert str(doc.id) in rationale_source_ids, (
            "Decision rationale_sources must include source document ID"
        )
