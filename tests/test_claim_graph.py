from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select

from app.models import Claim, ClaimRevision, Component, EvidenceSpan, Relationship, SourceDocument, UnresolvedRelationship
from app.processing.extractor import ExtractedFact, ExtractedRelationship
from app.services.ingest import IngestionService


class _StaticExtractor:
    def __init__(self, facts):
        self.facts = facts
        self.last_error = None
        self.last_warnings = []
        self.last_report = None

    async def extract(self, content, metadata):
        return list(self.facts)


async def test_grounded_deterministic_claim_becomes_active(db_session):
    fact = ExtractedFact(
        model_name="Decision",
        name="Decision: Use Postgres",
        value="Use Postgres.",
        fact_type="decision",
        confidence=0.91,
        temporal="current",
        temporal_hint="current",
        excerpt="Use Postgres.",
        provenance="unit:test",
    )
    doc = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="grounded-claim",
        content="Decision: Use Postgres.",
        metadata_json="{}",
    )
    db_session.add(doc)
    await db_session.flush()

    svc = IngestionService(db_session, extractor=_StaticExtractor([fact]))
    assert await svc.process_document(doc.id) == 1

    component = await db_session.scalar(select(Component).where(Component.source_document_id == doc.id))
    assert component is not None
    assert component.status == "active"
    assert component.claim_id is not None
    assert component.provenance == "unit:test"
    assert component.excerpt == "Use Postgres."

    claim = await db_session.get(Claim, component.claim_id)
    assert claim is not None
    assert claim.status == "active"
    assert claim.current_revision_id is not None

    revision = await db_session.get(ClaimRevision, claim.current_revision_id)
    assert revision is not None
    assert revision.operation == "create"
    assert revision.status_after == "active"
    evidence = await db_session.get(EvidenceSpan, revision.evidence_span_id)
    assert evidence is not None
    assert evidence.start_char is not None
    assert evidence.end_char is not None
    assert evidence.evidence_type == "decision"


async def test_ungrounded_extracted_claim_becomes_needs_review(db_session):
    fact = ExtractedFact(
        model_name="Risk",
        name="Risk: Legal launch blocker",
        value="Launch is blocked by legal approval.",
        fact_type="risk",
        confidence=0.88,
        temporal="current",
        temporal_hint="current",
        excerpt="Launch is blocked by legal approval.",
    )
    doc = SourceDocument(
        id=uuid4(),
        source_type="gmail",
        external_id="ungrounded-claim",
        content="The email says the launch plan is still being discussed.",
        metadata_json="{}",
    )
    db_session.add(doc)
    await db_session.flush()

    svc = IngestionService(db_session, extractor=_StaticExtractor([fact]))
    assert await svc.process_document(doc.id) == 1

    component = await db_session.scalar(select(Component).where(Component.source_document_id == doc.id))
    assert component is not None
    assert component.status == "needs_review"

    claim = await db_session.get(Claim, component.claim_id)
    assert claim is not None
    assert claim.status == "needs_review"
    revision = await db_session.get(ClaimRevision, claim.current_revision_id)
    evidence = await db_session.get(EvidenceSpan, revision.evidence_span_id)
    assert evidence.evidence_type == "needs_review"
    assert evidence.review_status == "needs_review"
    assert evidence.start_char is None
    assert evidence.end_char is None
    assert evidence.trust_zone == "untrusted_external"


async def test_claim_revisions_are_append_only(db_session):
    first = ExtractedFact(
        model_name="Decision",
        name="Decision: Auth provider",
        value="Use OAuth2.",
        fact_type="decision",
        confidence=0.82,
        excerpt="Use OAuth2.",
    )
    second = ExtractedFact(
        model_name="Decision",
        name="Decision: Auth provider",
        value="Use OIDC.",
        fact_type="decision",
        confidence=0.89,
        excerpt="Use OIDC.",
    )
    doc1 = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="claim-rev-1",
        content="Decision: Use OAuth2.",
        metadata_json="{}",
    )
    doc2 = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="claim-rev-2",
        content="Decision: Use OIDC.",
        metadata_json="{}",
    )
    db_session.add_all([doc1, doc2])
    await db_session.flush()

    assert await IngestionService(db_session, extractor=_StaticExtractor([first])).process_document(doc1.id) == 1
    assert await IngestionService(db_session, extractor=_StaticExtractor([second])).process_document(doc2.id) == 1

    claims = (await db_session.scalars(select(Claim).where(Claim.identity_key == "component:auth-provider"))).all()
    assert len(claims) == 1
    claim = claims[0]
    revisions = (await db_session.scalars(
        select(ClaimRevision).where(ClaimRevision.claim_id == claim.id).order_by(ClaimRevision.created_at)
    )).all()
    assert [revision.value for revision in revisions] == ["Use OAuth2.", "Use OIDC."]
    assert revisions[0].operation == "create"
    assert revisions[1].operation == "update"
    assert claim.current_revision_id == revisions[1].id


async def test_component_projection_preserves_graph_api_compatibility(client, db_session):
    fact = ExtractedFact(
        model_name="Task",
        name="Task: Add pagination tests",
        value="Add pagination tests.",
        fact_type="task",
        confidence=0.86,
        excerpt="Add pagination tests.",
        provenance=json.dumps({"source_type": "local", "external_id": "graph-compat"}),
    )
    doc = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="graph-compat",
        content="Task: Add pagination tests.",
        source_url="file:///repo/TASKS.md",
        metadata_json="{}",
    )
    db_session.add(doc)
    await db_session.flush()

    await IngestionService(db_session, extractor=_StaticExtractor([fact])).process_document(doc.id)

    response = await client.get("/api/graph")
    assert response.status_code == 200
    data = response.json()
    components = [item for item in data["components"] if item["name"] == "Task: Add pagination tests"]
    assert len(components) == 1
    component = components[0]
    assert component["value"] == "Add pagination tests."
    assert component["provenance"] is not None
    assert component["excerpt"] == "Add pagination tests."
    assert component["source_type"] == "local"
    assert component["source_url"] == "file:///repo/TASKS.md"


async def test_relationships_still_require_confidence_and_evidence(db_session):
    source = ExtractedFact(
        model_name="Task",
        name="Task: Checkout",
        value="Checkout depends on Payments API.",
        fact_type="task",
        confidence=0.85,
        excerpt="Checkout depends on Payments API.",
        relationships=[
            ExtractedRelationship(
                target_name="Payments API",
                relationship_type="depends_on",
                confidence=0.55,
                evidence="Checkout depends on Payments API.",
            )
        ],
    )
    doc = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="low-rel",
        content="Task: Checkout depends on Payments API.",
        metadata_json="{}",
    )
    db_session.add(doc)
    await db_session.flush()

    await IngestionService(db_session, extractor=_StaticExtractor([source])).process_document(doc.id)

    assert await db_session.scalar(select(Relationship)) is None
    assert await db_session.scalar(select(UnresolvedRelationship)) is None
