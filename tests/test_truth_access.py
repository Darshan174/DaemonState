from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import (
    Claim,
    CodeEdge,
    Component,
    ContextPack,
    Model,
    SourceDocument,
    Workspace,
)
from app.schemas.continuation_execution import ProjectEvidenceLevel
from app.services.access import AccessScope
from app.services.claims import append_claim_revision, claim_revisions_as_of
from app.services.context_compiler import ContextCompiler, FocusValidationError
from app.services.continuation_execution import (
    compile_and_persist_continuation_execution,
)
from app.services.evidence import create_evidence_span
from app.services.project_foundation import compile_workspace_project_foundation
from app.services.query import QueryService
from app.services.repo_indexer import inspect_repo
from app.services.source_revisions import ingest_source_document_revision
from app.time import utc_now


async def _workspace(session, name: str) -> Workspace:
    workspace = Workspace(id=uuid4(), name=name, slug=f"{name.lower()}-{uuid4().hex}")
    session.add(workspace)
    await session.flush()
    return workspace


async def _foundation_component(
    session,
    *,
    workspace: Workspace,
    source: SourceDocument,
    title: str,
    statement: str,
    identity_key: str,
    fact_type: str = "decision",
    claim_status: str = "active",
) -> Component:
    evidence = await create_evidence_span(
        session,
        source_document=source,
        text=statement,
        trust_zone=source.trust_zone,
    )
    model = Model(id=uuid4(), name=f"Foundation ACL {uuid4().hex}")
    claim = await session.scalar(
        select(Claim).where(
            Claim.workspace_id == workspace.id,
            Claim.identity_key == identity_key,
            Claim.claim_type == fact_type,
        )
    )
    if claim is None:
        claim = Claim(
            id=uuid4(),
            workspace_id=workspace.id,
            identity_key=identity_key,
            scope_identity_sha256=hashlib.sha256(uuid4().bytes).hexdigest(),
            claim_type=fact_type,
            status="active",
            temporal="current",
        )
        session.add(claim)
    session.add(model)
    await session.flush()
    await append_claim_revision(
        session,
        claim=claim,
        evidence_span=evidence.span,
        value=statement,
        operation="create",
        status_after=claim_status,
    )
    component = Component(
        id=uuid4(),
        workspace_id=workspace.id,
        model_id=model.id,
        source_document_id=source.id,
        claim_id=claim.id,
        identity_key=identity_key,
        name=title,
        value=statement,
        fact_type=fact_type,
        temporal="current",
        status="active",
        confidence=0.95,
        authority_weight=0.9,
    )
    session.add(component)
    await session.flush()
    return component


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


async def test_project_foundation_restricted_fact_is_excluded_from_contract_and_reuse(
    db_session,
    tmp_path,
):
    workspace = await _workspace(db_session, "Restricted project foundation")
    secret = "Production authentication must use the restricted HSM signing key."
    restricted = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="local_repository",
        external_id="restricted-foundation-decision",
        content=secret,
        trust_zone="trusted_repo",
        visibility_scope="restricted",
        permission_source="explicit",
        allowed_principal_ids=["alice"],
    )
    await _foundation_component(
        db_session,
        workspace=workspace,
        source=restricted.document,
        title="Restricted production authentication requirement",
        statement=secret,
        identity_key="security:production-signing-key",
        fact_type="requirement",
    )
    pack = ContextPack(
        workspace_id=workspace.id,
        objective="Report the current authentication architecture.",
        markdown="# Scoped audit pack\n",
        manifest="{}",
        repo_state_json="{}",
    )
    db_session.add(pack)
    await db_session.flush()

    fingerprint = "b" * 64
    repository = {
        "root": str(tmp_path),
        "branch": "main",
        "head_commit": "a" * 40,
        "status_fingerprint": fingerprint,
        "status_truncated": False,
        "changed_files": [],
    }
    manifest = {
        "repo_state": {
            "repo_path": str(tmp_path),
            "branch": "main",
            "head_commit": "a" * 40,
            "state_fingerprint": fingerprint,
            "changed_files": [],
            "relevant_files": [],
        },
        "verification": {"commands": []},
    }
    compile_args = {
        "workspace_id": workspace.id,
        "context_pack_id": pack.id,
        "request_verbatim": "Report the current authentication architecture.",
        "task_mode": "report",
        "repository": repository,
        "restored_checkpoint": None,
        "context_manifest": manifest,
    }
    alice_scope = AccessScope("alice", frozenset({workspace.id}))
    bob_scope = AccessScope("bob", frozenset({workspace.id}))

    alice = await compile_and_persist_continuation_execution(
        db_session,
        access_scope=alice_scope,
        **compile_args,
    )
    bob = await compile_and_persist_continuation_execution(
        db_session,
        access_scope=bob_scope,
        **compile_args,
    )
    alice_reused = await compile_and_persist_continuation_execution(
        db_session,
        access_scope=alice_scope,
        **compile_args,
    )
    bob_reused = await compile_and_persist_continuation_execution(
        db_session,
        access_scope=bob_scope,
        **compile_args,
    )

    assert secret in alice.prompt_markdown
    assert any(
        item.statement == secret
        for item in alice.contract.project_context
    )
    bob_contract = bob.contract.model_dump_json()
    assert secret not in bob.prompt_markdown
    assert secret not in bob_contract
    assert str(restricted.document.id) not in bob_contract
    assert bob.contract.project_context == ()
    assert bob.contract.project_foundation is not None
    assert bob.contract.project_foundation.included_fact_count == 0
    assert bob.contract.project_foundation.provisional_fact_count == 0
    assert (
        bob.contract.project_foundation.superseded_conflicting_fact_count
        == 0
    )
    assert alice.execution.id != bob.execution.id
    assert alice.execution.idempotency_key != bob.execution.idempotency_key
    assert alice_reused.execution.id == alice.execution.id
    assert bob_reused.execution.id == bob.execution.id


async def test_project_foundation_scope_is_applied_before_supersession_and_corroboration(
    db_session,
):
    workspace = await _workspace(db_session, "Scoped foundation inputs")
    public_decision = "The public architecture uses signed deployment manifests."
    first_revision = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="local_repository",
        external_id="deployment-architecture",
        content=public_decision,
        trust_zone="trusted_repo",
    )
    await _foundation_component(
        db_session,
        workspace=workspace,
        source=first_revision.document,
        title="Deployment architecture decision",
        statement=public_decision,
        identity_key="architecture:deployment-manifests",
    )
    restricted_successor = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="local_repository",
        external_id="deployment-architecture",
        content=public_decision,
        trust_zone="trusted_repo",
        visibility_scope="restricted",
        permission_source="explicit",
        allowed_principal_ids=["alice"],
    )
    assert restricted_successor.document.supersedes_source_document_id == (
        first_revision.document.id
    )

    public_component_statement = (
        "The public deployment workflow requires signed manifests."
    )
    public_component_source = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="local_repository",
        external_id="public-deployment-workflow",
        content=public_component_statement,
        trust_zone="trusted_repo",
    )
    public_component = await _foundation_component(
        db_session,
        workspace=workspace,
        source=public_component_source.document,
        title="Public deployment workflow decision",
        statement=public_component_statement,
        identity_key="workflow:signed-deployment-manifests",
    )
    restricted_component_statement = (
        "The internal deployment workflow uses the confidential signer."
    )
    restricted_component_source = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="local_repository",
        external_id="restricted-deployment-workflow",
        content=restricted_component_statement,
        trust_zone="trusted_repo",
        visibility_scope="restricted",
        permission_source="explicit",
        allowed_principal_ids=["alice"],
    )
    restricted_component = await _foundation_component(
        db_session,
        workspace=workspace,
        source=restricted_component_source.document,
        title="Restricted deployment workflow decision",
        statement=restricted_component_statement,
        identity_key="workflow:confidential-deployment-signer",
    )
    public_component.superseded_by_id = restricted_component.id
    await db_session.flush()

    agent_statement = "The architecture should preserve portable agent handoffs."
    public_agent = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="agent-public",
        content=agent_statement,
        trust_zone="semi_trusted_tool",
    )
    restricted_agent = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="agent-restricted",
        content=agent_statement,
        trust_zone="semi_trusted_tool",
        visibility_scope="restricted",
        permission_source="explicit",
        allowed_principal_ids=["alice"],
    )
    for source in (public_agent.document, restricted_agent.document):
        await _foundation_component(
            db_session,
            workspace=workspace,
            source=source,
            title="Portable agent handoff decision",
            statement=agent_statement,
            identity_key="architecture:portable-agent-handoffs",
        )

    alice = await compile_workspace_project_foundation(
        db_session,
        workspace_id=workspace.id,
        repository_fingerprint="c" * 64,
        access_scope=AccessScope("alice", frozenset({workspace.id})),
    )
    bob = await compile_workspace_project_foundation(
        db_session,
        workspace_id=workspace.id,
        repository_fingerprint="c" * 64,
        access_scope=AccessScope("bob", frozenset({workspace.id})),
    )

    alice_agent = next(
        item for item in alice.items if item.statement == agent_statement
    )
    assert alice_agent.evidence_level is ProjectEvidenceLevel.CORROBORATED
    assert alice_agent.corroboration_count == 2
    assert public_decision not in {item.statement for item in alice.items}
    assert public_component_statement not in {
        item.statement for item in alice.items
    }
    assert restricted_component_statement in {
        item.statement for item in alice.items
    }
    assert alice.snapshot.superseded_conflicting_fact_count == 2

    assert public_decision in {item.statement for item in bob.items}
    assert public_component_statement in {item.statement for item in bob.items}
    assert restricted_component_statement not in {
        item.statement for item in bob.items
    }
    assert agent_statement not in {item.statement for item in bob.items}
    assert bob.snapshot.provisional_fact_count == 1
    assert bob.snapshot.superseded_conflicting_fact_count == 0
    bob_payload = "\n".join(
        item.model_dump_json()
        for item in bob.items
    )
    assert str(restricted_successor.document.id) not in bob_payload
    assert str(restricted_component_source.document.id) not in bob_payload
    assert str(restricted_agent.document.id) not in bob_payload


async def test_project_foundation_claim_conflict_uses_only_visible_revisions(
    db_session,
):
    workspace = await _workspace(db_session, "Scoped foundation conflict")
    public_statement = "The release workflow requires signed attestations."
    public_source = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="local_repository",
        external_id="public-release-policy",
        content=public_statement,
        trust_zone="trusted_repo",
    )
    public_component = await _foundation_component(
        db_session,
        workspace=workspace,
        source=public_source.document,
        title="Release attestation policy",
        statement=public_statement,
        identity_key="policy:release-attestations",
    )

    restricted_statement = "The release workflow may skip signed attestations."
    restricted_source = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="local_repository",
        external_id="restricted-release-policy",
        content=restricted_statement,
        trust_zone="trusted_repo",
        visibility_scope="restricted",
        permission_source="explicit",
        allowed_principal_ids=["alice"],
    )
    await _foundation_component(
        db_session,
        workspace=workspace,
        source=restricted_source.document,
        title="Restricted release attestation exception",
        statement=restricted_statement,
        identity_key="policy:release-attestations",
        claim_status="contested",
    )
    claim = await db_session.get(Claim, public_component.claim_id)
    assert claim is not None
    assert claim.status == "contested"

    alice = await compile_workspace_project_foundation(
        db_session,
        workspace_id=workspace.id,
        repository_fingerprint="d" * 64,
        access_scope=AccessScope("alice", frozenset({workspace.id})),
    )
    bob = await compile_workspace_project_foundation(
        db_session,
        workspace_id=workspace.id,
        repository_fingerprint="d" * 64,
        access_scope=AccessScope("bob", frozenset({workspace.id})),
    )

    assert public_statement not in {item.statement for item in alice.items}
    assert restricted_statement not in {item.statement for item in alice.items}
    assert alice.snapshot.superseded_conflicting_fact_count == 2

    assert public_statement in {item.statement for item in bob.items}
    assert restricted_statement not in {item.statement for item in bob.items}
    assert bob.snapshot.superseded_conflicting_fact_count == 0
    bob_payload = "\n".join(item.model_dump_json() for item in bob.items)
    assert str(restricted_source.document.id) not in bob_payload


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
