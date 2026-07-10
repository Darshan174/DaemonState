from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from app.models import EvidenceSpan, SourceDocument, Workspace
from app.services.evidence import create_evidence_span, sha256_text
from app.services.source_revisions import (
    get_current_source_document,
    ingest_source_document_revision,
)
from app.sync.ai_session import ingest_ai_session


async def test_append_only_revisions_are_content_aware_and_workspace_scoped(db_session):
    workspace_a = Workspace(id=uuid4(), name="Revision A", slug=f"revision-a-{uuid4().hex}")
    workspace_b = Workspace(id=uuid4(), name="Revision B", slug=f"revision-b-{uuid4().hex}")
    db_session.add_all([workspace_a, workspace_b])
    await db_session.flush()

    first = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace_a.id,
        source_type="github",
        external_id="github:acme/repo:issue:7",
        content="State: open",
        metadata_json={"provider_version": "one"},
    )
    old_evidence = await create_evidence_span(
        db_session,
        source_document=first.document,
        text="State: open",
    )
    unchanged = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace_a.id,
        source_type="github",
        external_id="github:acme/repo:issue:7",
        content="State: open",
        metadata_json={"provider_version": "ignored-on-idempotent-retry"},
    )
    second = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace_a.id,
        source_type="github",
        external_id="github:acme/repo:issue:7",
        content="State: closed",
    )
    third = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace_a.id,
        source_type="github",
        external_id="github:acme/repo:issue:7",
        content="State: open",
    )
    isolated = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace_b.id,
        source_type="github",
        external_id="github:acme/repo:issue:7",
        content="State: open",
    )

    assert first.created is True and first.document.revision_number == 1
    assert unchanged.unchanged is True and unchanged.document.id == first.document.id
    assert second.revised is True and second.document.revision_number == 2
    assert second.document.supersedes_source_document_id == first.document.id
    assert third.document.revision_number == 3
    assert third.document.supersedes_source_document_id == second.document.id
    assert third.document.id != first.document.id
    assert isolated.document.revision_number == 1
    assert isolated.document.source_identity_sha256 != first.document.source_identity_sha256

    current = await get_current_source_document(
        db_session,
        workspace_id=workspace_a.id,
        source_type="github",
        external_id="github:acme/repo:issue:7",
    )
    assert current is not None and current.id == third.document.id

    revisions = list(
        await db_session.scalars(
            select(SourceDocument)
            .where(SourceDocument.source_identity_sha256 == first.document.source_identity_sha256)
            .order_by(SourceDocument.revision_number)
        )
    )
    assert [doc.content for doc in revisions] == ["State: open", "State: closed", "State: open"]
    assert all(doc.content_sha256 == sha256_text(doc.content) for doc in revisions)
    stored_evidence = await db_session.get(EvidenceSpan, old_evidence.span.id)
    assert stored_evidence is not None
    assert stored_evidence.source_document_id == first.document.id


async def test_ai_session_sync_appends_changed_content_and_skips_unchanged(db_session):
    workspace = Workspace(id=uuid4(), name="AI revisions", slug=f"ai-revisions-{uuid4().hex}")
    db_session.add(workspace)
    await db_session.flush()

    first = await ingest_ai_session(
        "codex",
        db_session,
        "session-revision-test",
        "Decision: keep the original evidence.",
        workspace_id=str(workspace.id),
    )
    unchanged = await ingest_ai_session(
        "codex",
        db_session,
        "session-revision-test",
        "Decision: keep the original evidence.",
        workspace_id=str(workspace.id),
    )
    changed = await ingest_ai_session(
        "codex",
        db_session,
        "session-revision-test",
        "Decision: retain both evidence revisions.",
        workspace_id=str(workspace.id),
    )

    docs = list(
        await db_session.scalars(
            select(SourceDocument)
            .where(SourceDocument.workspace_id == workspace.id)
            .where(SourceDocument.external_id == "codex:session:session-revision-test")
            .order_by(SourceDocument.revision_number)
        )
    )
    assert first["documents_persisted"] == 1
    assert unchanged["documents_persisted"] == 0
    assert unchanged["unchanged"] == 1
    assert changed["documents_persisted"] == 1
    assert changed["documents_updated"] == 1
    assert len(docs) == 2
    assert docs[0].content_sha256 == sha256_text(docs[0].content)
    assert docs[1].content_sha256 == sha256_text(docs[1].content)
    assert docs[1].supersedes_source_document_id == docs[0].id
