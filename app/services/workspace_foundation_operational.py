from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from app.schemas.workspace_foundation import (
    ArchitectureComponent,
    Capability,
    ChangeIntent,
    CommandVerificationStatus,
    DurableKnowledgeFact,
    DurablePromotionReason,
    EvidenceTier,
    ImplementationTrace,
    ImplementationTraceKind,
    ProductionFlow,
    ProductionFlowProof,
    ProductionFlowStage,
    ProductionFlowStageKind,
    RepositoryChange,
    RepositoryState,
    VerificationRun,
    VerificationRunResult,
    WorkspaceCommand,
)


MAX_OPERATIONAL_PRODUCTION_FLOWS = 8
MAX_OPERATIONAL_CHANGE_INTENTS = 16
MAX_OPERATIONAL_VERIFICATION_RUNS = 32

_PERSISTENCE_TERMS = frozenset({
    "database",
    "db",
    "model",
    "models",
    "persistence",
    "repository",
    "schema",
    "session",
    "storage",
    "store",
})
_COMPILER_TERMS = frozenset({
    "compile",
    "compiled",
    "compiler",
    "contextpack",
    "foundation",
    "renderer",
})
_OUTPUT_TERMS = frozenset({
    "clipboard",
    "component",
    "dialog",
    "display",
    "frontend",
    "output",
    "page",
    "panel",
    "render",
    "response",
    "ui",
    "view",
})


def compile_verification_runs(
    commands: Iterable[WorkspaceCommand],
    *,
    snapshot: str,
) -> tuple[VerificationRun, ...]:
    """Project admitted command observations into first-class snapshot proof."""

    result: list[VerificationRun] = []
    seen: set[tuple[str, str, str, int]] = set()
    for command in commands:
        verification = command.verification
        status = verification.status
        if status not in {
            CommandVerificationStatus.PASSED,
            CommandVerificationStatus.FAILED,
            CommandVerificationStatus.BLOCKED,
        }:
            continue
        if (
            verification.verified_at is None
            or verification.exit_code is None
            or verification.output_sha256 is None
            or not verification.evidence_ref_ids
        ):
            # The source command record remains available, but an incomplete
            # observation cannot be upgraded into a VerificationRun.
            continue
        key = (
            command.command,
            command.working_directory,
            verification.verified_at.isoformat(),
            verification.exit_code,
        )
        if key in seen:
            continue
        seen.add(key)
        run_result = {
            CommandVerificationStatus.PASSED: VerificationRunResult.PASSED,
            CommandVerificationStatus.FAILED: VerificationRunResult.FAILED,
            CommandVerificationStatus.BLOCKED: VerificationRunResult.BLOCKED,
        }[status]
        failures = () if run_result is VerificationRunResult.PASSED else (
            verification.summary
            or (
                "The snapshot-bound command was blocked."
                if run_result is VerificationRunResult.BLOCKED
                else "The snapshot-bound command returned a non-zero exit code."
            ),
        )
        identity = "\0".join(map(str, key))
        result.append(VerificationRun(
            id=f"verification.{_stable_hash(identity)[:16]}",
            command=command.command,
            working_directory=command.working_directory,
            snapshot=snapshot,
            exit_code=verification.exit_code,
            result=run_result,
            failures=failures,
            observed_at=verification.verified_at,
            output_sha256=verification.output_sha256,
            evidence_ref_ids=verification.evidence_ref_ids,
        ))
        if len(result) >= MAX_OPERATIONAL_VERIFICATION_RUNS:
            break
    return tuple(result)


def compile_change_intents(
    repository_state: RepositoryState,
    *,
    capabilities: Iterable[Capability],
    components: Iterable[ArchitectureComponent],
) -> tuple[ChangeIntent, ...]:
    """Group dirty paths by capability without inventing author intent.

    The returned records are deliberately intent *skeletons*. Git and syntax
    establish the grouping, paths, tests, and snapshot; trusted human or
    documentation evidence is still required for before/after/completion.
    """

    capability_by_id = {item.id: item for item in capabilities}
    component_by_id = {item.id: item for item in components}
    groups: dict[tuple[str, str], list[RepositoryChange]] = defaultdict(list)
    for change in repository_state.changes:
        if change.capability_ids:
            key = ("capability", change.capability_ids[0])
        elif change.component_ids:
            key = ("component", change.component_ids[0])
        else:
            parts = change.path.split("/")
            key = ("area", "/".join(parts[:2] if len(parts) > 1 else parts))
        groups[key].append(change)

    result: list[ChangeIntent] = []
    for key, changes in sorted(
        groups.items(),
        key=lambda item: (
            -len(item[1]),
            item[0],
            tuple(change.path for change in item[1]),
        ),
    ):
        kind, identity = key
        capability_ids = tuple(dict.fromkeys(
            capability_id
            for change in changes
            for capability_id in change.capability_ids
        ))[:16]
        if kind == "capability" and identity in capability_by_id:
            label = capability_by_id[identity].name
        elif kind == "component" and identity in component_by_id:
            label = component_by_id[identity].name
        else:
            label = f"Repository area: {identity}"
        changed_paths = tuple(sorted({change.path for change in changes}))
        affected_tests = tuple(sorted({
            path
            for change in changes
            for path in change.related_test_paths
        }))[:64]
        evidence_ref_ids = tuple(dict.fromkeys(
            reference_id
            for change in changes
            for reference_id in change.evidence_ref_ids
        ))[:64]
        if not evidence_ref_ids:
            continue
        group_identity = f"{kind}:{identity}:{'|'.join(changed_paths)}"
        result.append(ChangeIntent(
            id=f"intent.{_stable_hash(group_identity)[:16]}",
            capability=label,
            capability_ids=capability_ids,
            snapshot=repository_state.snapshot_fingerprint,
            changed_paths=changed_paths,
            affected_tests=affected_tests,
            evidence_ref_ids=evidence_ref_ids,
        ))
        if len(result) >= MAX_OPERATIONAL_CHANGE_INTENTS:
            break
    return tuple(result)


def compile_production_flows(
    traces: Iterable[ImplementationTrace],
    *,
    capabilities: Iterable[Capability],
    snapshot: str,
) -> tuple[ProductionFlow, ...]:
    """Normalize exact entrypoint-backed traces into honest partial flows."""

    capability_by_id = {item.id: item for item in capabilities}
    result: list[ProductionFlow] = []
    for trace in traces:
        if trace.kind is not ImplementationTraceKind.PRODUCTION_CALL_FLOW:
            continue
        hops = tuple(trace.hops)
        if not hops:
            continue
        nodes: list[tuple[str, str | None, tuple[str, ...]]] = [
            (hops[0].source_path, hops[0].source_symbol, hops[0].evidence_ref_ids)
        ]
        nodes.extend(
            (hop.target_path, hop.target_symbol, hop.evidence_ref_ids)
            for hop in hops
        )
        entry_path, entry_symbol, entry_refs = nodes[0]
        entrypoint = ProductionFlowStage(
            kind=ProductionFlowStageKind.ENTRYPOINT,
            path=entry_path,
            symbol=entry_symbol,
            evidence_ref_ids=entry_refs,
        )
        services: list[ProductionFlowStage] = []
        persistence: list[ProductionFlowStage] = []
        compilers: list[ProductionFlowStage] = []
        output: ProductionFlowStage | None = None
        observed_stage_kinds: list[ProductionFlowStageKind] = []
        for index, (path, symbol, references) in enumerate(nodes[1:], start=1):
            stage_kind = _operational_stage_kind(
                path,
                symbol,
                is_last=index == len(nodes) - 1,
            )
            stage = ProductionFlowStage(
                kind=stage_kind,
                path=path,
                symbol=symbol,
                evidence_ref_ids=references,
            )
            observed_stage_kinds.append(stage_kind)
            if stage_kind is ProductionFlowStageKind.PERSISTENCE:
                persistence.append(stage)
            elif stage_kind is ProductionFlowStageKind.COMPILER:
                compilers.append(stage)
            elif stage_kind is ProductionFlowStageKind.OUTPUT:
                output = stage
            else:
                services.append(stage)

        gaps = list(trace.gaps)
        if not services:
            gaps.append("No distinct service stage is established by the static trace.")
        if not persistence:
            gaps.append("Persistence or external-effect stage is not established.")
        if not compilers:
            gaps.append("Compiler or transformation stage is not established.")
        if output is None:
            gaps.append("Returned or displayed output is not established.")
        stage_rank = {
            ProductionFlowStageKind.SERVICE: 0,
            ProductionFlowStageKind.PERSISTENCE: 1,
            ProductionFlowStageKind.COMPILER: 2,
            ProductionFlowStageKind.OUTPUT: 3,
        }
        canonical_order = all(
            stage_rank[current] <= stage_rank[following]
            for current, following in zip(
                observed_stage_kinds,
                observed_stage_kinds[1:],
            )
        )
        if observed_stage_kinds and not canonical_order:
            gaps.append(
                "Observed hops do not follow service → persistence → compiler → output order."
            )
        complete = bool(
            services
            and persistence
            and compilers
            and output is not None
            and canonical_order
        )
        if complete:
            # A canonical syntax path is complete as a static projection, while
            # proof remains code_observed. Runtime execution is still not implied.
            gaps = []
        unique_gaps = tuple(dict.fromkeys(gaps))[:16]
        capability_names = [
            capability_by_id[capability_id].name
            for capability_id in trace.capability_ids
            if capability_id in capability_by_id
        ]
        flow_name = capability_names[0] if capability_names else trace.name
        evidence_ref_ids = tuple(dict.fromkeys(
            reference_id
            for hop in hops
            for reference_id in hop.evidence_ref_ids
        ))[:48]
        result.append(ProductionFlow(
            id=f"flow.{_stable_hash(trace.id)[:16]}",
            name=flow_name,
            capability_ids=trace.capability_ids,
            snapshot=snapshot,
            entrypoint=entrypoint,
            service=tuple(services[:8]),
            persistence=tuple(persistence[:8]),
            compiler=tuple(compilers[:8]),
            output=output,
            proof=ProductionFlowProof.CODE_OBSERVED,
            complete=complete,
            gaps=unique_gaps,
            evidence_ref_ids=evidence_ref_ids,
        ))
        if len(result) >= MAX_OPERATIONAL_PRODUCTION_FLOWS:
            break
    return tuple(result)


def compile_durable_facts(
    durable_knowledge: Iterable[DurableKnowledgeFact],
) -> tuple[DurableKnowledgeFact, ...]:
    """Populate the canonical v2 durable-facts lane with promotion metadata."""

    result: list[DurableKnowledgeFact] = []
    for fact in durable_knowledge:
        promotion_reason = _promotion_reason(fact.evidence_tier)
        payload = fact.model_dump(mode="python")
        payload.update(
            id=f"fact.{_stable_hash(fact.identity_key)[:16]}",
            promotion_reason=promotion_reason,
        )
        result.append(DurableKnowledgeFact.model_validate(payload))
    return tuple(result)


def operational_lane_statuses(
    *,
    repository_state: RepositoryState,
    production_flows: Iterable[ProductionFlow],
    verification_runs: Iterable[VerificationRun],
    change_intents: Iterable[ChangeIntent],
    durable_facts: Iterable[DurableKnowledgeFact],
) -> Mapping[str, str | bool | int]:
    """Small deterministic status capsule for renderers and quality reports."""

    flows = tuple(production_flows)
    runs = tuple(verification_runs)
    intents = tuple(change_intents)
    facts = tuple(durable_facts)
    known_intents = sum(
        intent.before_behavior is not None
        and intent.after_behavior is not None
        and intent.completed.value != "unknown"
        and intent.remaining_status.value != "unknown"
        for intent in intents
    )
    return {
        "production_flow_status": (
            "complete" if any(item.complete for item in flows)
            else "partial" if flows
            else "missing"
        ),
        "production_flow_count": len(flows),
        "verification_run_count": len(runs),
        "verification_fresh": bool(runs),
        "change_group_count": len(intents),
        "change_intent_known": (
            not repository_state.dirty
            or bool(intents) and known_intents == len(intents)
        ),
        "durable_fact_count": len(facts),
    }


def _operational_stage_kind(
    path: str,
    symbol: str | None,
    *,
    is_last: bool,
) -> ProductionFlowStageKind:
    terms = set(_terms(f"{path} {symbol or ''}"))
    if terms & _PERSISTENCE_TERMS:
        return ProductionFlowStageKind.PERSISTENCE
    if terms & _COMPILER_TERMS:
        return ProductionFlowStageKind.COMPILER
    if is_last and terms & _OUTPUT_TERMS:
        return ProductionFlowStageKind.OUTPUT
    return ProductionFlowStageKind.SERVICE


def _promotion_reason(tier: EvidenceTier) -> DurablePromotionReason:
    if tier is EvidenceTier.HUMAN_CONFIRMED:
        return DurablePromotionReason.HUMAN_CONFIRMED
    if tier is EvidenceTier.CORROBORATED:
        return DurablePromotionReason.INDEPENDENT_CORROBORATION
    if tier in {
        EvidenceTier.CODE_OBSERVED,
        EvidenceTier.SYSTEM_VERIFIED,
        EvidenceTier.TEST_VERIFIED,
        EvidenceTier.RUNTIME_VERIFIED,
    }:
        return DurablePromotionReason.MECHANICALLY_VERIFIED
    return DurablePromotionReason.LEGACY_PROMOTED


def _terms(value: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if token
    )


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "compile_change_intents",
    "compile_durable_facts",
    "compile_production_flows",
    "compile_verification_runs",
    "operational_lane_statuses",
]
