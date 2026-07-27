from __future__ import annotations

import hashlib
from uuid import uuid4

from app.models import (
    Claim,
    ClaimRevision,
    Component,
    EvidenceSpan,
    Model,
    SourceDocument,
)
from app.processing.embedder import HashingEmbedder
from app.services.access import AccessScope
from app.services.context_compiler import ContextCompiler, parse_goal
from app.services.memory_trust import assess_memory_trust, exact_memory_evidence
from app.services.model_profiles import profile_for_target_model
from app.services.query import QueryService


def _detached_record(
    *,
    source_type: str,
    trust_zone: str,
    fact_type: str,
    evidence_trust_zone: str | None = None,
    evidence_review_status: str = "verified",
    extraction_method: str = "deterministic",
) -> tuple[Component, EvidenceSpan, SourceDocument]:
    statement = f"{fact_type}: exact source statement"
    source = SourceDocument(
        id=uuid4(),
        source_type=source_type,
        external_id=f"trust:{uuid4().hex}",
        content=statement,
        content_sha256=hashlib.sha256(statement.encode()).hexdigest(),
        trust_zone=trust_zone,
        metadata_json="{}",
    )
    evidence = EvidenceSpan(
        id=uuid4(),
        source_document_id=source.id,
        start_char=0,
        end_char=len(statement),
        text=statement,
        text_sha256=hashlib.sha256(statement.encode()).hexdigest(),
        review_status=evidence_review_status,
        trust_zone=evidence_trust_zone or trust_zone,
        extraction_method=extraction_method,
    )
    component = Component(
        id=uuid4(),
        model_id=uuid4(),
        source_document_id=source.id,
        name=statement,
        value=statement,
        fact_type=fact_type,
        status="active",
        confidence=0.9,
    )
    return component, evidence, source


def test_agent_assertion_is_reviewable_but_agent_activity_is_reported():
    decision, decision_evidence, source = _detached_record(
        source_type="agent_session",
        trust_zone="semi_trusted_tool",
        fact_type="decision",
    )
    decision_assessment = assess_memory_trust(
        decision,
        decision_evidence,
        source=source,
    )
    assert decision_assessment.current_truth is False
    assert decision_assessment.truth_state == "needs_review"
    assert decision_assessment.verification == "needs_review"

    verification, verification_evidence, verification_source = _detached_record(
        source_type="agent_session",
        trust_zone="semi_trusted_tool",
        fact_type="verification",
    )
    verification_assessment = assess_memory_trust(
        verification,
        verification_evidence,
        source=verification_source,
    )
    assert verification_assessment.current_truth is False
    assert verification_assessment.truth_state == "reported"
    assert verification_assessment.verification == "reported"
    assert verification_assessment.reported_activity is True

    delivery, delivery_evidence, delivery_source = _detached_record(
        source_type="agent_session",
        trust_zone="semi_trusted_tool",
        fact_type="github_pr",
        evidence_review_status="needs_review",
        extraction_method="llm",
    )
    delivery_assessment = assess_memory_trust(
        delivery,
        delivery_evidence,
        source=delivery_source,
    )
    assert delivery_assessment.evidence_exact is True
    assert delivery_assessment.truth_state == "reported"
    assert delivery_assessment.requires_review is False


def test_exact_repo_and_human_confirmed_agent_evidence_can_be_current():
    repo, repo_evidence, repo_source = _detached_record(
        source_type="local_repository",
        trust_zone="trusted_repo",
        fact_type="decision",
        extraction_method="llm_or_regex",
    )
    repo_assessment = assess_memory_trust(
        repo,
        repo_evidence,
        source=repo_source,
    )
    assert repo_assessment.current_truth is True
    assert repo_assessment.verification == "verified"
    assert repo_assessment.basis == "trusted_repo_exact_verified_evidence"

    agent, agent_evidence, agent_source = _detached_record(
        source_type="agent_session",
        trust_zone="semi_trusted_tool",
        evidence_trust_zone="trusted_human",
        fact_type="decision",
    )
    agent_assessment = assess_memory_trust(
        agent,
        agent_evidence,
        source=agent_source,
    )
    assert agent_assessment.current_truth is True
    assert agent_assessment.basis == "human_confirmed_exact_evidence"


def test_deferred_exact_evidence_preserves_full_source_integrity_checks():
    _component, evidence, source = _detached_record(
        source_type="local_repository",
        trust_zone="trusted_repo",
        fact_type="decision",
    )
    source_content = source.content
    source.__dict__.pop("content", None)
    evidence._source_text_matches = True
    evidence._source_content_length = len(source_content)
    evidence._source_content_sha256 = hashlib.sha256(
        source_content.encode(),
    ).hexdigest()

    assert exact_memory_evidence(source, evidence) is True

    source.content_sha256 = "0" * 64
    assert exact_memory_evidence(source, evidence) is False

    source.content_sha256 = None
    assert exact_memory_evidence(source, evidence) is True

    evidence.end_char = len(source_content) + 1
    assert exact_memory_evidence(source, evidence) is False


def test_remote_provider_snapshot_is_not_current_without_freshness():
    issue, evidence, source = _detached_record(
        source_type="github",
        trust_zone="semi_trusted_tool",
        fact_type="github_issue",
    )
    assessment = assess_memory_trust(issue, evidence, source=source)
    assert assessment.current_truth is False
    assert assessment.truth_state == "stale"
    assert assessment.basis == "remote_freshness_unknown"

    evidence.trust_zone = "trusted_human"
    human_confirmed_snapshot = assess_memory_trust(
        issue,
        evidence,
        source=source,
    )
    assert human_confirmed_snapshot.current_truth is False
    assert human_confirmed_snapshot.truth_state == "stale"

    evidence.trust_zone = "semi_trusted_tool"
    fresh = assess_memory_trust(
        issue,
        evidence,
        source=source,
        provider_fresh=True,
    )
    assert fresh.current_truth is True
    assert fresh.verification == "observed"


async def _persist_record(
    db_session,
    embedder: HashingEmbedder,
    *,
    source_type: str,
    source_trust_zone: str,
    evidence_trust_zone: str,
    fact_type: str,
    name: str,
    value: str,
) -> Component:
    model = Model(id=uuid4(), name=f"Trust model {uuid4().hex}")
    source = SourceDocument(
        id=uuid4(),
        source_type=source_type,
        external_id=f"trust-source:{uuid4().hex}",
        content=value,
        content_sha256=hashlib.sha256(value.encode()).hexdigest(),
        trust_zone=source_trust_zone,
        metadata_json="{}",
    )
    evidence = EvidenceSpan(
        id=uuid4(),
        source_document_id=source.id,
        start_char=0,
        end_char=len(value),
        text=value,
        text_sha256=hashlib.sha256(value.encode()).hexdigest(),
        review_status="verified",
        trust_zone=evidence_trust_zone,
        extraction_method="deterministic",
    )
    claim = Claim(
        id=uuid4(),
        identity_key=f"trust:{uuid4().hex}",
        scope_identity_sha256=hashlib.sha256(uuid4().bytes).hexdigest(),
        claim_type=fact_type,
        status="active",
        temporal="current",
        confidence=0.9,
    )
    db_session.add_all([model, source, evidence, claim])
    await db_session.flush()
    revision = ClaimRevision(
        id=uuid4(),
        claim_id=claim.id,
        evidence_span_id=evidence.id,
        revision_key=hashlib.sha256(uuid4().bytes).hexdigest(),
        value=value,
        operation="create",
        status_after="active",
    )
    db_session.add(revision)
    await db_session.flush()
    claim.current_revision_id = revision.id
    component = Component(
        id=uuid4(),
        model_id=model.id,
        source_document_id=source.id,
        claim_id=claim.id,
        identity_key=claim.identity_key,
        name=name,
        value=value,
        fact_type=fact_type,
        temporal="current",
        confidence=0.9,
        authority_weight=0.9,
        status="active",
        embedding=str(await embedder.embed_text(f"{name}\n{value}")),
    )
    db_session.add(component)
    await db_session.flush()
    return component


async def test_compiler_and_query_share_the_agent_assertion_gate(
    db_session,
    tmp_path,
):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'trust-fixture'\n",
        encoding="utf-8",
    )
    embedder = HashingEmbedder()
    repo_decision = await _persist_record(
        db_session,
        embedder,
        source_type="local_repository",
        source_trust_zone="trusted_repo",
        evidence_trust_zone="trusted_repo",
        fact_type="decision",
        name="Repository trust policy",
        value="Use exact repository evidence for the memory trust policy.",
    )
    agent_decision = await _persist_record(
        db_session,
        embedder,
        source_type="agent_session",
        source_trust_zone="semi_trusted_tool",
        evidence_trust_zone="semi_trusted_tool",
        fact_type="decision",
        name="Agent trust assertion",
        value="Treat this assistant assertion as current project truth.",
    )
    agent_verification = await _persist_record(
        db_session,
        embedder,
        source_type="agent_session",
        source_trust_zone="semi_trusted_tool",
        evidence_trust_zone="semi_trusted_tool",
        fact_type="verification",
        name="Agent verification report",
        value="Verification: the memory trust suite passed.",
    )
    human_confirmed_agent = await _persist_record(
        db_session,
        embedder,
        source_type="agent_session",
        source_trust_zone="semi_trusted_tool",
        evidence_trust_zone="trusted_human",
        fact_type="decision",
        name="Human-confirmed agent decision",
        value="A person confirmed this agent-carried memory trust policy decision.",
    )
    remote_issue = await _persist_record(
        db_session,
        embedder,
        source_type="github_issue",
        source_trust_zone="semi_trusted_tool",
        evidence_trust_zone="semi_trusted_tool",
        fact_type="github_issue",
        name="Remote memory trust issue",
        value="The provider snapshot mentions the memory trust policy.",
    )

    compiler = ContextCompiler(db_session)
    graph_candidates = await compiler._graph_candidates(
        parse_goal("apply the memory trust policy"),
        None,
        profile_for_target_model(None, 3500),
        AccessScope.local(),
    )
    graph_by_component = {item.component_id: item for item in graph_candidates}
    assert graph_by_component[str(agent_decision.id)].truth_state == "needs_review"
    assert graph_by_component[str(agent_verification.id)].truth_state == "reported"
    assert graph_by_component[str(human_confirmed_agent.id)].truth_state == "current"
    assert graph_by_component[str(human_confirmed_agent.id)].trust_zone == "trusted_human"
    assert graph_by_component[str(remote_issue.id)].truth_state == "stale"

    compiled = await compiler.compile_context_pack(
        "apply the memory trust policy",
        repo_path=str(tmp_path),
        token_budget=3500,
        persist=False,
    )
    selected_ids = {
        item["component_id"] for item in compiled.selected_items if item.get("component_id")
    }
    assert str(repo_decision.id) in selected_ids
    assert str(human_confirmed_agent.id) in selected_ids
    assert str(agent_decision.id) not in selected_ids
    assert str(agent_verification.id) not in selected_ids
    assert str(remote_issue.id) not in selected_ids

    queried = await QueryService(
        db_session,
        embedder=embedder,
    ).query("memory trust policy", top_k=8)
    query_ids = {item.id for item in queried.components}
    assert repo_decision.id in query_ids
    assert human_confirmed_agent.id in query_ids
    assert agent_decision.id not in query_ids
    assert agent_verification.id not in query_ids
    assert remote_issue.id not in query_ids
