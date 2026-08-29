from __future__ import annotations

from app.schemas.context_quality import (
    ClaimCriticality,
    ContextClaimEnvelope,
    ContextDecision,
    ContextKind,
)
from app.services.context_quality_policies import (
    compare_context_claims,
    evaluate_context_candidate,
)


def _claim(
    stable_id: str,
    statement: str,
    *,
    authority: str = "repository_observation",
    truth_state: str = "current",
    criticality: ClaimCriticality = ClaimCriticality.NORMAL,
    scope: ContextKind = ContextKind.WORKSPACE,
) -> ContextClaimEnvelope:
    return ContextClaimEnvelope(
        stable_id=stable_id,
        section="test",
        kind="fact",
        statement=statement,
        scope=scope,
        authority=authority,
        truth_state=truth_state,
        criticality=criticality,
        evidence_refs=(f"evidence:{stable_id}",),
    )


def test_claim_diff_ignores_whitespace_and_renderer_movement() -> None:
    before = _claim("fact:one", "The API owns request routing.")
    after = before.model_copy(update={
        "statement": "  The API owns   request routing. ",
    })

    diff = compare_context_claims((before,), (after,))

    assert diff.retained == ("fact:one",)
    assert not diff.modified


def test_missing_claim_is_not_observed_and_never_silent_removal() -> None:
    before = _claim(
        "constraint:one",
        "Preserve the public API.",
        authority="direct_user",
        criticality=ClaimCriticality.CRITICAL,
    )

    evaluation = evaluate_context_candidate(
        context_kind=ContextKind.WORKSPACE,
        active_claims=(before,),
        candidate_claims=(),
        rendered_text="Workspace background",
        metadata={
            "objective_independent": True,
            "copy_ready": True,
            "hash_valid": True,
            "snapshot_current": True,
            "permissions_current": True,
            "semantic_coverage_score": 100,
            "durable_fact_count": 1,
            "verification_complete": True,
        },
    )

    assert evaluation.diff.not_observed == ("constraint:one",)
    assert "CRITICAL_CLAIM_NOT_OBSERVED" in evaluation.hard_failures
    assert evaluation.decision is ContextDecision.REJECT


def test_authority_or_verification_downgrade_is_blocking() -> None:
    before = _claim(
        "requirement:one",
        "Keep context background-only.",
        authority="direct_user",
        truth_state="verified",
        criticality=ClaimCriticality.CRITICAL,
    )
    after = before.model_copy(update={
        "authority": "agent_report",
        "truth_state": "reported",
    })

    evaluation = evaluate_context_candidate(
        context_kind=ContextKind.SESSION,
        active_claims=(before,),
        candidate_claims=(after,),
        rendered_text=(
            "Background only. Awaiting user instruction. "
            "The user supplies the next request."
        ),
        metadata={
            "context_role": "background_only",
            "copy_ready": True,
            "hash_valid": True,
            "snapshot_current": True,
            "permissions_current": True,
            "required_dependencies_complete": True,
        },
    )

    assert "USER_AUTHORITY_DOWNGRADED" in evaluation.hard_failures
    assert "VERIFIED_TO_UNVERIFIED" in evaluation.hard_failures
    assert evaluation.decision is ContextDecision.REJECT


def test_high_not_observed_claim_requires_review_not_automatic_deletion() -> None:
    before = _claim(
        "capability:one",
        "Users can inspect current repository context.",
        criticality=ClaimCriticality.HIGH,
    )

    evaluation = evaluate_context_candidate(
        context_kind=ContextKind.WORKSPACE,
        active_claims=(before,),
        candidate_claims=(),
        rendered_text="Workspace background",
        metadata={
            "objective_independent": True,
            "copy_ready": True,
            "hash_valid": True,
            "snapshot_current": True,
            "permissions_current": True,
            "semantic_coverage_score": 100,
            "durable_fact_count": 1,
            "verification_complete": True,
        },
    )

    assert evaluation.decision is ContextDecision.REVIEW
    assert "HIGH_CLAIM_NOT_OBSERVED_REVIEW_REQUIRED" in evaluation.warnings

