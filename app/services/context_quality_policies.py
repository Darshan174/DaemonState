from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.schemas.context_quality import (
    CONTEXT_QUALITY_POLICY_VERSION,
    ClaimCriticality,
    ClaimSelection,
    ContextClaimEnvelope,
    ContextDecision,
    ContextKind,
    ContextQualityEvaluation,
    ContextSemanticDiff,
    canonical_sha256,
)


_AUTHORITY_STRENGTH = {
    "compiler_inference": 0,
    "agent_report": 1,
    "documentation": 2,
    "human_confirmed": 3,
    "repository_observation": 4,
    "verification_observation": 5,
    "direct_user": 6,
}
_TRUTH_STRENGTH = {
    "unknown": 0,
    "contested": 0,
    "historical": 1,
    "reported": 2,
    "current": 3,
    "verified": 4,
}
_SESSION_FORBIDDEN_MARKERS = (
    "## Start here",
    "## Exact next action",
    "## Done when",
    "## Acceptance criteria",
    "Status: **Execution Ready**",
)

# These describe useful background with known limitations, not permission to
# execute work. Unexplained claim loss, corrupt evidence, and authority changes
# still require rejection or review.
_BACKGROUND_INFORMATIONAL_WARNINGS = frozenset({
    "CURRENT_STATE_BOUND_TO_OLD_SNAPSHOT",
    "USER_OBJECTIVE_MISSING",
    "REQUIRED_DEPENDENCY_MISSING",
    "DURABLE_PROJECT_KNOWLEDGE_EMPTY",
    "CURRENT_VERIFICATION_INCOMPLETE",
    "SEMANTIC_COVERAGE_BELOW_PROMOTION_TARGET",
})


def semantic_claim_hash(claims: Iterable[ContextClaimEnvelope]) -> str:
    return canonical_sha256([
        {
            "stable_id": item.stable_id,
            "section": item.section,
            "kind": item.kind,
            "statement": " ".join(item.statement.split()),
            "scope": item.scope.value,
            "authority": item.authority,
            "truth_state": item.truth_state,
            "criticality": item.criticality.value,
            "selection": item.selection.value,
            "exclusion_reason": item.exclusion_reason,
            "evidence_refs": sorted(item.evidence_refs),
            "repository_snapshot_sha256": item.repository_snapshot_sha256,
            "session_boundary_id": item.session_boundary_id,
        }
        for item in sorted(claims, key=lambda claim: claim.stable_id)
    ])


def compare_context_claims(
    active_claims: Iterable[ContextClaimEnvelope],
    candidate_claims: Iterable[ContextClaimEnvelope],
) -> ContextSemanticDiff:
    active = {item.stable_id: item for item in active_claims}
    candidate = {item.stable_id: item for item in candidate_claims}
    added: list[str] = []
    retained: list[str] = []
    modified: list[str] = []
    weakened: list[str] = []
    strengthened: list[str] = []
    not_observed: list[str] = []
    exclusion_changed: list[str] = []
    details: list[dict[str, Any]] = []

    for stable_id in sorted(active.keys() | candidate.keys()):
        before = active.get(stable_id)
        after = candidate.get(stable_id)
        if before is None and after is not None:
            added.append(stable_id)
            details.append({"claim_id": stable_id, "change": "added"})
            continue
        if after is None and before is not None:
            not_observed.append(stable_id)
            details.append({
                "claim_id": stable_id,
                "change": "not_observed",
                "criticality": before.criticality.value,
                "authority": before.authority,
                "truth_state": before.truth_state,
            })
            continue
        assert before is not None and after is not None
        before_semantic = (
            " ".join(before.statement.split()),
            before.section,
            before.kind,
            before.authority,
            before.truth_state,
            before.criticality,
            before.selection,
            tuple(sorted(before.evidence_refs)),
            before.repository_snapshot_sha256,
            before.session_boundary_id,
        )
        after_semantic = (
            " ".join(after.statement.split()),
            after.section,
            after.kind,
            after.authority,
            after.truth_state,
            after.criticality,
            after.selection,
            tuple(sorted(after.evidence_refs)),
            after.repository_snapshot_sha256,
            after.session_boundary_id,
        )
        if before_semantic == after_semantic:
            retained.append(stable_id)
            continue
        modified.append(stable_id)
        if before.selection != after.selection:
            exclusion_changed.append(stable_id)
        authority_delta = (
            _AUTHORITY_STRENGTH[after.authority]
            - _AUTHORITY_STRENGTH[before.authority]
        )
        truth_delta = (
            _TRUTH_STRENGTH[after.truth_state]
            - _TRUTH_STRENGTH[before.truth_state]
        )
        if authority_delta < 0 or truth_delta < 0:
            weakened.append(stable_id)
        elif authority_delta > 0 or truth_delta > 0:
            strengthened.append(stable_id)
        details.append({
            "claim_id": stable_id,
            "change": "modified",
            "authority_before": before.authority,
            "authority_after": after.authority,
            "truth_before": before.truth_state,
            "truth_after": after.truth_state,
            "selection_before": before.selection.value,
            "selection_after": after.selection.value,
        })

    payload = {
        "added": added,
        "retained": retained,
        "modified": modified,
        "weakened": weakened,
        "strengthened": strengthened,
        "not_observed": not_observed,
        "exclusion_changed": exclusion_changed,
        "details": details,
    }
    return ContextSemanticDiff(**payload, sha256=canonical_sha256(payload))


def evaluate_context_candidate(
    *,
    context_kind: ContextKind,
    candidate_claims: Iterable[ContextClaimEnvelope],
    active_claims: Iterable[ContextClaimEnvelope] = (),
    rendered_text: str,
    metadata: Mapping[str, Any] | None = None,
) -> ContextQualityEvaluation:
    metadata = dict(metadata or {})
    background_only = metadata.get("context_role") == "background_only"
    candidates = tuple(candidate_claims)
    active = tuple(active_claims)
    diff = compare_context_claims(active, candidates)
    candidate_by_id = {item.stable_id: item for item in candidates}
    active_by_id = {item.stable_id: item for item in active}
    included = tuple(
        item for item in candidates if item.selection is ClaimSelection.INCLUDED
    )
    hard_failures: list[str] = []
    warnings: list[str] = []

    def hard(code: str) -> None:
        if code not in hard_failures:
            hard_failures.append(code)

    def warn(code: str) -> None:
        if code not in warnings:
            warnings.append(code)

    if metadata.get("hash_valid") is False:
        hard("HASH_OR_LINEAGE_FAILURE")
    if metadata.get("permissions_current") is False:
        hard("PERMISSION_SNAPSHOT_STALE")
    if metadata.get("candidate_quarantined") is True:
        hard("CANDIDATE_QUARANTINED")
    if metadata.get("snapshot_current") is False:
        (warn if background_only else hard)("CURRENT_STATE_BOUND_TO_OLD_SNAPSHOT")
    if metadata.get("copy_ready") is False:
        hard("UPSTREAM_CONTEXT_NOT_COPY_READY")

    critical_exclusions = [
        item
        for item in candidates
        if item.selection is ClaimSelection.EXCLUDED
        and item.criticality is ClaimCriticality.CRITICAL
    ]
    if any(item.exclusion_reason == "token_budget" for item in critical_exclusions):
        hard("TOKEN_BUDGET_DROPPED_CRITICAL_CLAIM")
    elif critical_exclusions:
        hard("CRITICAL_CLAIM_EXCLUDED")

    for stable_id in diff.weakened:
        before = active_by_id[stable_id]
        after = candidate_by_id[stable_id]
        emitted_specific_failure = False
        if before.authority == "direct_user" and after.authority != "direct_user":
            hard("USER_AUTHORITY_DOWNGRADED")
            emitted_specific_failure = True
        if before.truth_state == "verified" and after.truth_state != "verified":
            hard("VERIFIED_TO_UNVERIFIED")
            emitted_specific_failure = True
        if (
            not emitted_specific_failure
            and before.criticality is ClaimCriticality.CRITICAL
        ):
            hard("CRITICAL_CLAIM_WEAKENED")
        elif not emitted_specific_failure:
            warn("CLAIM_WEAKENED")

    for stable_id in diff.not_observed:
        before = active_by_id[stable_id]
        if before.criticality is ClaimCriticality.CRITICAL:
            hard("CRITICAL_CLAIM_NOT_OBSERVED")
        elif before.criticality is ClaimCriticality.HIGH:
            warn("HIGH_CLAIM_NOT_OBSERVED_REVIEW_REQUIRED")
        else:
            warn("CLAIM_NOT_REOBSERVED")

    if context_kind is ContextKind.SESSION:
        if metadata.get("context_role") != "background_only":
            hard("SESSION_CONTEXT_NOT_BACKGROUND_ONLY")
        if any(
            line.lstrip().startswith(marker)
            for line in rendered_text.splitlines()
            for marker in _SESSION_FORBIDDEN_MARKERS
        ):
            hard("INFERRED_ACTION_OR_ACCEPTANCE_PRESENT")
        if any(
            item.kind == "inferred_action"
            and item.selection is ClaimSelection.INCLUDED
            for item in candidates
        ):
            hard("INFERRED_ACTION_PRESENT")
        user_objectives = [
            item
            for item in included
            if item.kind == "prior_user_objective"
            and item.authority == "direct_user"
        ]
        if not user_objectives:
            (warn if background_only else hard)("USER_OBJECTIVE_MISSING")
        if "awaiting user instruction" not in rendered_text.casefold():
            hard("AWAITING_USER_INSTRUCTION_BOUNDARY_MISSING")
        if metadata.get("required_dependencies_complete") is False:
            (warn if background_only else hard)("REQUIRED_DEPENDENCY_MISSING")
    else:
        if metadata.get("objective_independent") is not True:
            hard("WORKSPACE_CONTEXT_NOT_OBJECTIVE_INDEPENDENT")
        if any(item.scope is ContextKind.SESSION for item in included):
            hard("SESSION_CONTENT_IN_WORKSPACE")
        if any(
            item.kind == "durable_project_fact"
            and item.authority in {"agent_report", "compiler_inference"}
            and item.selection is ClaimSelection.INCLUDED
            for item in candidates
        ):
            hard("AGENT_REPORT_PROMOTED_TO_DURABLE_TRUTH")
        if metadata.get("durable_fact_count", 0) == 0:
            warn("DURABLE_PROJECT_KNOWLEDGE_EMPTY")
        if metadata.get("verification_complete") is False:
            warn("CURRENT_VERIFICATION_INCOMPLETE")
        if float(metadata.get("semantic_coverage_score") or 0.0) < 70.0:
            warn("SEMANTIC_COVERAGE_BELOW_PROMOTION_TARGET")

    supported = [item for item in included if item.evidence_refs]
    critical = [
        item
        for item in included
        if item.criticality is ClaimCriticality.CRITICAL
    ]
    critical_supported = [item for item in critical if item.evidence_refs]
    active_critical = [
        item
        for item in active
        if item.criticality is ClaimCriticality.CRITICAL
        and item.selection is ClaimSelection.INCLUDED
    ]
    retained_active_critical = [
        item for item in active_critical if item.stable_id in candidate_by_id
    ]
    quality_vector = {
        "evidence_support": round(100 * len(supported) / max(1, len(included)), 2),
        "critical_claim_support": round(
            100 * len(critical_supported) / max(1, len(critical)), 2
        ),
        "critical_active_recall": round(
            100 * len(retained_active_critical) / max(1, len(active_critical)), 2
        ),
        "temporal_freshness": 100.0 if metadata.get("snapshot_current") is not False else 0.0,
        "scope_fidelity": 0.0 if any(code.endswith("IN_WORKSPACE") for code in hard_failures) else 100.0,
        "compression_safety": 0.0 if critical_exclusions else 100.0,
        "stability": round(
            100 * len(diff.retained) / max(1, len(active)), 2
        ) if active else 100.0,
    }

    review_warnings = set(warnings) - (
        _BACKGROUND_INFORMATIONAL_WARNINGS if background_only else set()
    )
    if hard_failures:
        decision = ContextDecision.REJECT
    elif review_warnings:
        decision = ContextDecision.REVIEW
    elif active and semantic_claim_hash(active) == semantic_claim_hash(candidates):
        decision = ContextDecision.NO_CHANGE
    else:
        decision = ContextDecision.PROMOTE

    payload = {
        "policy_version": CONTEXT_QUALITY_POLICY_VERSION,
        "decision": decision.value,
        "hard_failures": sorted(hard_failures),
        "warnings": sorted(warnings),
        "quality_vector": quality_vector,
        "diff_sha256": diff.sha256,
    }
    return ContextQualityEvaluation(
        decision=decision,
        hard_failures=tuple(sorted(hard_failures)),
        warnings=tuple(sorted(warnings)),
        quality_vector=quality_vector,
        diff=diff,
        sha256=canonical_sha256(payload),
    )
