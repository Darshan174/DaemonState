from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import Claim, CodeEdge, Component, Model, SourceDocument, Workspace
from app.services.access import AccessScope
from app.services.claims import append_claim_revision, claim_revisions_as_of
from app.services.context_compiler import ContextCompiler, FocusValidationError
from app.services.evidence import create_evidence_span
from app.services.query import QueryService
from app.services.repo_indexer import inspect_repo
from app.services.source_revisions import ingest_source_document_revision
from app.time import utc_now


async def _workspace(session, name: str) -> Workspace:
    workspace = Workspace(id=uuid4(), name=name, slug=f"{name.lower()}-{uuid4().hex}")
    session.add(workspace)
    await session.flush()
    return workspace


async def test_permission_only_change_creates_source_revision_and_evidence_inherits_snapshot(
    db_session,
):
    workspace = await _workspace(db_session, "Permission revision")
    first = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="local",
        external_id="decision-1",
        content="Use Postgres.",
        visibility_scope="restricted",
        permission_source="explicit",
        allowed_principal_ids=["alice"],
    )
    retry = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="local",
        external_id="decision-1",
        content="Use Postgres.",
        visibility_scope="restricted",
        permission_source="explicit",
        allowed_principal_ids=["alice"],
    )
    changed = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="local",
        external_id="decision-1",
        content="Use Postgres.",
        visibility_scope="restricted",
        permission_source="explicit",
        allowed_principal_ids=["bob"],
    )
    assert retry.document.id == first.document.id
    assert retry.unchanged is True
    assert changed.document.revision_number == 2
    assert changed.document.permission_snapshot_sha256 != first.document.permission_snapshot_sha256

    evidence = await create_evidence_span(
        db_session, source_document=changed.document, text="Use Postgres."
    )
    assert evidence.span.visibility_scope == "restricted"
    assert (
        evidence.span.permission_snapshot_sha256
        == changed.document.permission_snapshot_sha256
    )


async def test_restricted_evidence_is_filtered_before_query_and_focus(db_session):
    workspace = await _workspace(db_session, "Restricted query")
    model = Model(id=uuid4(), name=f"Decision {uuid4().hex}")
    db_session.add(model)
    source = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="local",
        external_id="restricted-decision",
        content="Task: rotate signing keys.",
        visibility_scope="restricted",
        permission_source="explicit",
        allowed_principal_ids=["alice"],
    )
    component = Component(
        id=uuid4(),
        workspace_id=workspace.id,
        model_id=model.id,
        source_document_id=source.document.id,
        name="Rotate signing keys",
        value="Rotate signing keys.",
        fact_type="task",
        temporal="current",
        status="active",
        confidence=0.95,
        authority_weight=0.9,
    )
    db_session.add(component)
    await db_session.flush()

    alice = AccessScope("alice", frozenset({workspace.id}))
    bob = AccessScope("bob", frozenset({workspace.id}))
    allowed = await QueryService(db_session).query(
        "rotate signing keys", workspace_id=workspace.id, access_scope=alice
    )
    denied = await QueryService(db_session).query(
        "rotate signing keys", workspace_id=workspace.id, access_scope=bob
    )
    assert any(item.id == component.id for item in allowed.components)
    assert denied.components == []
    assert denied.trace.candidate_component_count == 0

    with pytest.raises(FocusValidationError, match="not found"):
        await ContextCompiler(db_session).compile_context_pack(
            "",
            workspace_id=workspace.id,
            focus_component_id=component.id,
            objective_origin="source_component",
            access_scope=bob,
            persist=False,
        )


async def test_claim_as_of_uses_valid_and_transaction_intervals(db_session):
    workspace = await _workspace(db_session, "Temporal truth")
    source = SourceDocument(
        workspace_id=workspace.id,
        source_type="local",
        external_id="temporal-evidence",
        content="OAuth2 then OIDC.",
        metadata_json="{}",
    )
    claim = Claim(
        workspace_id=workspace.id,
        identity_key="component:auth-provider",
        claim_type="decision",
        status="active",
    )
    db_session.add_all([source, claim])
    await db_session.flush()
    first_evidence = await create_evidence_span(
        db_session, source_document=source, text="OAuth2"
    )
    second_evidence = await create_evidence_span(
        db_session, source_document=source, text="OIDC"
    )
    first_start = datetime(2026, 1, 1)
    second_start = datetime(2026, 2, 1)
    first = await append_claim_revision(
        db_session,
        claim=claim,
        evidence_span=first_evidence.span,
        value="OAuth2",
        valid_from=first_start,
        observed_at=datetime(2026, 1, 2),
        validity_basis="source_time",
    )
    known_between = utc_now()
    second = await append_claim_revision(
        db_session,
        claim=claim,
        evidence_span=second_evidence.span,
        value="OIDC",
        valid_from=second_start,
        observed_at=datetime(2026, 2, 2),
        validity_basis="source_time",
    )
    assert first.valid_to == second_start
    assert first.transaction_to is not None
    historical = await claim_revisions_as_of(
        db_session,
        claim_id=claim.id,
        valid_at=datetime(2026, 1, 15),
        known_at=known_between,
    )
    current = await claim_revisions_as_of(
        db_session, claim_id=claim.id, valid_at=datetime(2026, 2, 15)
    )
    assert [item.id for item in historical] == [first.id]
    assert [item.id for item in current] == [second.id]


async def test_exact_python_and_typescript_test_symbol_edges(db_session, tmp_path):
    workspace = await _workspace(db_session, "Symbol edges")
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "math.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "test_math.py").write_text(
        "from src.math import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "calc.ts").write_text(
        "export function multiply(a, b) { return a * b; }\n", encoding="utf-8"
    )
    (tmp_path / "src" / "calc.test.ts").write_text(
        "import { multiply } from './calc';\n"
        "test('multiply', () => { expect(multiply(2, 3)).toBe(6); });\n",
        encoding="utf-8",
    )
    await inspect_repo(
        tmp_path, session=db_session, workspace_id=workspace.id, persist=True
    )
    edges = list(await db_session.scalars(
        select(CodeEdge).where(CodeEdge.rule_id == "test_symbol_match.v1")
    ))
    assert len(edges) == 2
    assert all(edge.evidence_start_line is not None for edge in edges)
    assert all("pairing_edge_key" in edge.evidence_json for edge in edges)
