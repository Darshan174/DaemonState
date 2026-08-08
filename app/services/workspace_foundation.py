from __future__ import annotations

import hashlib
import json
import posixpath
import re
import shlex
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from app.schemas.continuation_execution import (
    ProjectContextKind,
    ProjectEvidenceLevel,
)
from app.schemas.workspace_foundation import (
    ArchitectureComponent,
    ArchitectureComponentKind,
    Capability,
    CapabilityAssessment,
    CapabilityDeclarationStatus,
    CapabilityState,
    CapabilitySurface,
    CapabilityVerificationStatus,
    CommandKind,
    CommandOrigin,
    CommandVerification,
    CommandVerificationStatus,
    Concept,
    DurableFactKind,
    DurableKnowledgeFact,
    DocumentedSystemFlow,
    EvidenceReference,
    EvidenceTier,
    FoundationSection,
    ImplementationCoverage,
    ImplementationTrace,
    ImplementationTraceCoverage,
    ImplementationTraceHop,
    ImplementationTraceKind,
    ProductProfile,
    ProductClaim,
    ProductClaimKind,
    QualityIssue,
    QualityIssueKind,
    QualityReport,
    QualitySeverity,
    QualityStatus,
    RequiredCommandKey,
    RequiredVerificationCommand,
    RepositoryChange,
    RepositoryChangeKind,
    RepositoryChangeRole,
    RepositoryChangeScope,
    RepositoryEngineeringKnowledgeFact,
    RepositoryEngineeringKnowledgeKind,
    RepositorySemanticDelta,
    RepositoryState,
    SectionCoverage,
    SectionCoverageStatus,
    StructuralEdge,
    StructuralRelation,
    SurfaceKind,
    SurfaceDerivation,
    SurfaceRole,
    VerificationPolicy,
    VerificationPolicySource,
    WorkflowStep,
    WorkspaceCommand,
    WorkspaceFoundationArtifact,
    WorkspaceFoundationPayload,
)
from app.services.project_foundation import CompiledProjectFoundation
from app.services.repo_indexer import (
    IndexedFile,
    IndexedImport,
    IndexedSymbol,
    RepoFrame,
    _python_module_for_path,
    _resolve_javascript_import_path,
    _resolve_python_import_module,
    _test_reference_resolves_to_target,
    _test_target_candidates,
)
from app.services.workspace_foundation_adapters import (
    ADAPTER_VERSION,
    ArchitectureObservation,
    DeclaredCommand,
    DeclaredVerificationPolicy,
    DocumentedCapability,
    DocumentedEngineeringKnowledge,
    DocumentedProject,
    SourceLocation,
    StackObservation,
    collect_architecture_observations,
    collect_declared_commands,
    collect_documented_project,
    collect_required_check_policy,
    collect_stack_observations,
)
from app.services.workspace_foundation_edges import (
    WorkspaceEdgeObservation,
    observe_workspace_edges_result,
    observe_workspace_flow_edges_result,
)
from app.services.workspace_foundation_verification import (
    WorkspaceVerificationObservation,
)


WORKSPACE_FOUNDATION_COMPILER_VERSION = "workspace_foundation_compiler.v2"
MAX_CAPABILITIES = 8
MAX_CAPABILITY_SURFACES = 5
MAX_ARCHITECTURE_COMPONENTS = 256
MAX_RENDERED_CHANGES = 16
MAX_RELATED_TEST_PATHS_PER_CHANGE = 12
MAX_TARGETED_TEST_IMPORTS_PER_FILE = 256
MAX_TARGETED_TEST_REFERENCES_PER_FILE = 256
MAX_REPOSITORY_ENGINEERING_KNOWLEDGE = 16
MAX_DURABLE_KNOWLEDGE_FACTS = 12

_CAPABILITY_STOP_WORDS = frozenset(
    {
        "agent",
        "agents",
        "allows",
        "application",
        "code",
        "context",
        "current",
        "data",
        "exactly",
        "file",
        "files",
        "helps",
        "local",
        "project",
        "repository",
        "session",
        "shows",
        "source",
        "system",
        "user",
        "users",
        "workspace",
    }
)

_STATIC_FLOW_EDGE_RULES = frozenset({
    "static_http_route_reference.v1",
    "route_handler_owner.v1",
    "local_symbol_call.v1",
})
_EXACT_PRODUCTION_EDGE_RULES = frozenset({
    *_STATIC_FLOW_EDGE_RULES,
    "local_module_import.v1",
})


@dataclass(frozen=True)
class _SurfaceMatch:
    file: IndexedFile
    score: float
    rule_id: str
    matched_terms: tuple[str, ...]
    symbol: IndexedSymbol | None = None
    route: str | None = None


class _EvidenceRegistry:
    def __init__(self, snapshot_fingerprint: str) -> None:
        self.snapshot_fingerprint = snapshot_fingerprint
        self._items: dict[tuple[Any, ...], EvidenceReference] = {}

    def add(
        self,
        *,
        tier: EvidenceTier,
        source: SourceLocation | None = None,
        path: str | None = None,
        source_sha256: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        symbol: str | None = None,
        heading: str | None = None,
        rule: str | None = None,
        note: str | None = None,
    ) -> str:
        if source is not None:
            path = source.path
            source_sha256 = source.sha256
            start_line = source.start_line
            end_line = source.end_line
            heading = source.heading
            rule = source.rule_id
        digest = _valid_sha256(source_sha256)
        if path is not None and digest is None:
            raise ValueError(f"file-bound foundation evidence requires a source digest: {path}")
        digest = digest or self.snapshot_fingerprint
        if (start_line is None) != (end_line is None):
            start_line = None
            end_line = None
        normalized_note = _bounded_text(note, 1_000) or None
        key = (
            tier.value,
            path,
            digest,
            start_line,
            end_line,
            symbol,
            heading,
            rule,
            normalized_note,
        )
        existing = self._items.get(key)
        if existing is not None:
            return existing.id
        reference_id = f"ev.{_stable_hash(json.dumps(key, default=str))[:16]}"
        reference = EvidenceReference(
            id=reference_id,
            tier=tier,
            source_sha256=digest,
            path=path,
            start_line=start_line,
            end_line=end_line,
            symbol=_bounded_text(symbol, 500) or None,
            heading=_bounded_text(heading, 500) or None,
            rule=_bounded_text(rule, 240) or None,
            note=normalized_note,
        )
        self._items[key] = reference
        return reference_id

    def values(self) -> tuple[EvidenceReference, ...]:
        return tuple(sorted(self._items.values(), key=lambda item: item.id))


class WorkspaceFoundationCompiler:
    """Compile a typed, objective-independent workspace foundation.

    The compiler consumes the already bounded ``RepoFrame`` and the existing
    durable-foundation result. It performs no task retrieval and runs no
    repository command. Documentation, syntax observations, durable memory,
    and future runtime/test proof remain separate evidence tiers.
    """

    def compile(
        self,
        *,
        frame: RepoFrame,
        inventory: dict[str, Any],
        durable_foundation: CompiledProjectFoundation | None,
        repository_fingerprint: str | None = None,
        verification_observations: tuple[WorkspaceVerificationObservation, ...] = (),
    ) -> WorkspaceFoundationArtifact:
        snapshot_fingerprint = (
            _valid_sha256(repository_fingerprint)
            or _valid_sha256(frame.snapshot_fingerprint)
            or _sha256_json(
                {
                    "repo_path": frame.repo_path,
                    "branch": frame.branch,
                    "head_commit": frame.head_commit,
                    "changed_files": _canonical_changed_files(frame.changed_files),
                }
            )
        )
        registry = _EvidenceRegistry(snapshot_fingerprint)
        documented = collect_documented_project(frame, inventory)
        edge_observation = observe_workspace_edges_result(frame)
        all_architecture_observations = collect_architecture_observations(frame)
        architecture_observation_count = len(all_architecture_observations)
        architecture_observations = all_architecture_observations[:MAX_ARCHITECTURE_COMPONENTS]
        architecture_truncated = architecture_observation_count > len(architecture_observations)
        stack_observations = collect_stack_observations(frame, inventory)
        declared_verification_policy = collect_required_check_policy(frame)
        command_observations = _merge_required_command_declarations(
            collect_declared_commands(frame, inventory),
            declared_verification_policy.required_commands,
        )

        product, product_documented = _product_profile(
            documented,
            inventory,
            frame,
            registry,
        )
        concepts = _concepts(documented, registry)
        documented_system_flows = _documented_system_flows(documented, registry)
        repository_engineering_knowledge = _repository_engineering_knowledge(
            documented.engineering_knowledge,
            registry,
        )
        components = _architecture_components(
            architecture_observations,
            stack_observations,
            registry,
        )
        capabilities, surfaces = _capabilities(
            documented,
            frame,
            edge_observation,
            concepts,
            components,
            registry,
        )
        implementation_traces = _implementation_traces(
            edge_observation,
            capabilities,
            surfaces,
            registry,
            frame,
        )
        structural_edges = _structural_edges(
            edge_observation,
            components,
            capabilities,
            surfaces,
            implementation_traces,
            registry,
            frame,
        )
        capabilities = _capabilities_with_implementation_traces(
            capabilities,
            implementation_traces,
            frame,
        )
        verification_policy = _verification_policy(
            declared_verification_policy,
            registry,
        )
        commands = _commands(
            command_observations,
            verification_observations,
            registry,
        )
        capabilities = _capabilities_with_targeted_verification(
            capabilities,
            surfaces,
            commands,
        )
        repository_state = _repository_state(
            frame,
            inventory,
            capabilities,
            surfaces,
            implementation_traces,
            components,
            registry,
            snapshot_fingerprint,
        )
        durable_knowledge = _durable_knowledge(durable_foundation, registry)
        quality = _quality_report(
            frame=frame,
            product_documented=product_documented,
            documented=documented,
            documented_system_flows=documented_system_flows,
            concepts=concepts,
            capabilities=capabilities,
            surfaces=surfaces,
            components=components,
            edges=structural_edges,
            implementation_traces=implementation_traces,
            verification_policy=verification_policy,
            commands=commands,
            repository_state=repository_state,
            repository_engineering_knowledge=repository_engineering_knowledge,
            durable_knowledge=durable_knowledge,
            durable_foundation=durable_foundation,
            edge_observation=edge_observation,
            architecture_observation_count=architecture_observation_count,
            architecture_truncated=architecture_truncated,
        )
        payload = WorkspaceFoundationPayload(
            compiled_at=repository_state.captured_at,
            compiler_version=(f"{WORKSPACE_FOUNDATION_COMPILER_VERSION}+{ADAPTER_VERSION}"),
            product_profile=product,
            evidence_references=registry.values(),
            concepts=concepts,
            documented_system_flows=documented_system_flows,
            capability_surfaces=surfaces,
            capabilities=capabilities,
            architecture_components=components,
            structural_edges=structural_edges,
            implementation_traces=implementation_traces,
            verification_policy=verification_policy,
            commands=commands,
            repository_state=repository_state,
            repository_engineering_knowledge=repository_engineering_knowledge,
            durable_knowledge=durable_knowledge,
            quality_report=quality,
        )
        return WorkspaceFoundationArtifact.from_payload(payload)


def compile_workspace_foundation(
    *,
    frame: RepoFrame,
    inventory: dict[str, Any],
    durable_foundation: CompiledProjectFoundation | None,
    repository_fingerprint: str | None = None,
    verification_observations: tuple[WorkspaceVerificationObservation, ...] = (),
) -> WorkspaceFoundationArtifact:
    return WorkspaceFoundationCompiler().compile(
        frame=frame,
        inventory=inventory,
        durable_foundation=durable_foundation,
        repository_fingerprint=repository_fingerprint,
        verification_observations=verification_observations,
    )


def _product_profile(
    documented: DocumentedProject,
    inventory: dict[str, Any],
    frame: RepoFrame,
    registry: _EvidenceRegistry,
) -> tuple[ProductProfile, bool]:
    name = _bounded_text(
        documented.name
        or inventory.get("project_name")
        or (Path(frame.repo_path).name if frame.repo_path else "Unindexed workspace"),
        200,
    )
    product_documented = bool(documented.summary and documented.source)
    summary = (
        _bounded_text(documented.summary, 2_000)
        if product_documented
        else (
            f"{name} has indexed repository structure, but no safe repository-stated "
            "product purpose was found. Treat its purpose as unknown until supported "
            "by documentation or durable workspace evidence."
        )
    )
    if documented.source is not None:
        evidence_id = registry.add(
            tier=EvidenceTier.DOCUMENTATION_STATED,
            source=documented.source,
            note="Repository-stated product profile; not promoted to code verification.",
        )
    else:
        evidence_id = registry.add(
            tier=EvidenceTier.CODE_OBSERVED,
            rule="product_identity_fallback.v1",
            note="Only repository identity was observed; product purpose is unknown.",
        )
    maturity = next(
        (
            "active alpha"
            for boundary in documented.boundaries
            if "active alpha" in boundary.text.casefold()
        ),
        None,
    )
    profile_text = " ".join(
        [documented.summary or "", *(item.text for item in documented.boundaries)]
    ).casefold()
    deployment_models = tuple(
        dict.fromkeys(
            value
            for value, marker in (
                ("self-hosted", "self-host"),
                ("local", "local"),
                ("containerized", "docker"),
            )
            if marker in profile_text
        )
    )
    explicit_boundaries = tuple(
        boundary
        for boundary in documented.boundaries
        if _is_explicit_product_boundary(boundary.text)
    )
    claims: list[ProductClaim] = []

    def claim(
        kind: ProductClaimKind,
        value: str,
        source: SourceLocation | None,
        note: str,
    ) -> None:
        if source is None:
            return
        claims.append(
            ProductClaim(
                kind=kind,
                value=value,
                evidence_ref_ids=(
                    registry.add(
                        tier=EvidenceTier.DOCUMENTATION_STATED,
                        source=source,
                        note=note,
                    ),
                ),
            )
        )

    if product_documented:
        claim(
            ProductClaimKind.PURPOSE,
            summary,
            documented.source,
            "Repository-stated product purpose.",
        )
    for audience in documented.audiences[:8]:
        claim(
            ProductClaimKind.AUDIENCE,
            audience.text,
            audience.source,
            "Repository-stated intended audience.",
        )
    if maturity:
        maturity_source = next(
            (
                boundary.source
                for boundary in documented.boundaries
                if "active alpha" in boundary.text.casefold()
            ),
            documented.source,
        )
        claim(
            ProductClaimKind.MATURITY,
            maturity,
            maturity_source,
            "Repository-stated product maturity.",
        )
    for deployment in deployment_models:
        deployment_source = next(
            (
                boundary.source
                for boundary in documented.boundaries
                if deployment.split("-", 1)[0] in boundary.text.casefold()
            ),
            documented.source,
        )
        claim(
            ProductClaimKind.DEPLOYMENT,
            deployment,
            deployment_source,
            "Repository-stated deployment or operating model.",
        )
    for boundary in explicit_boundaries[:6]:
        claim(
            ProductClaimKind.BOUNDARY,
            boundary.text,
            boundary.source,
            "Repository-stated product boundary or limitation.",
        )
    all_claim_evidence = tuple(
        dict.fromkeys(
            reference_id
            for product_claim in claims
            for reference_id in product_claim.evidence_ref_ids
        )
    )
    return ProductProfile(
        name=name or "Unindexed workspace",
        summary=summary,
        maturity=maturity,
        intended_users=tuple(item.text for item in documented.audiences[:8]),
        deployment_models=deployment_models,
        non_goals=tuple(item.text for item in explicit_boundaries[:6]),
        claims=tuple(claims),
        evidence_ref_ids=tuple(dict.fromkeys((evidence_id, *all_claim_evidence))),
    ), product_documented


def _is_explicit_product_boundary(value: str) -> bool:
    return bool(
        re.search(
            r"\b(?:does not|do not|is not|isn't|not a|not another|not the|"
            r"unsupported|only supports)\b",
            value.casefold(),
        )
    )


def _concepts(
    documented: DocumentedProject,
    registry: _EvidenceRegistry,
) -> tuple[Concept, ...]:
    concepts: list[Concept] = []
    seen: set[str] = set()
    for value in documented.concepts[:8]:
        key = _normalized(value.term)
        if not key or key in seen:
            continue
        seen.add(key)
        evidence_id = registry.add(
            tier=EvidenceTier.DOCUMENTATION_STATED,
            source=value.source,
            note="Repository-stated term definition.",
        )
        concepts.append(
            Concept(
                id=f"concept.{_stable_hash(key)[:16]}",
                name=value.term,
                definition=value.definition,
                evidence_ref_ids=(evidence_id,),
            )
        )
    return tuple(concepts)


def _documented_system_flows(
    documented: DocumentedProject,
    registry: _EvidenceRegistry,
) -> tuple[DocumentedSystemFlow, ...]:
    result: list[DocumentedSystemFlow] = []
    for flow in documented.system_flows[:4]:
        flow_ref = registry.add(
            tier=EvidenceTier.DOCUMENTATION_STATED,
            source=flow.source,
            note=(
                "Repository-stated system or data flow; current implementation and "
                "runtime completeness are not implied."
            ),
        )
        steps = tuple(
            WorkflowStep(
                position=step.position,
                description=step.description,
                evidence_ref_ids=(
                    registry.add(
                        tier=EvidenceTier.DOCUMENTATION_STATED,
                        source=step.source,
                        note="Repository-stated system-flow step; not runtime proof.",
                    ),
                ),
            )
            for step in flow.steps
        )
        result.append(
            DocumentedSystemFlow(
                id=f"flow.{_stable_hash(f'{flow.source.path}:{flow.name}')[:16]}",
                name=flow.name,
                summary=flow.summary,
                steps=steps,
                evidence_ref_ids=(flow_ref,),
            )
        )
    return tuple(result)


def _architecture_components(
    observations: tuple[ArchitectureObservation, ...],
    stack: tuple[StackObservation, ...],
    registry: _EvidenceRegistry,
) -> tuple[ArchitectureComponent, ...]:
    result: list[ArchitectureComponent] = []
    seen_paths: set[str] = set()
    for observation in observations:
        if observation.path in seen_paths:
            continue
        seen_paths.add(observation.path)
        evidence_id = registry.add(
            tier=EvidenceTier.CODE_OBSERVED,
            source=observation.source,
            note=(
                "Repository role derived from path and syntax metadata; it does "
                "not assert runtime behaviour."
            ),
        )
        applicable_stack = tuple(
            item for item in stack if _stack_applies_to_component(item, observation)
        )
        technologies = tuple(dict.fromkeys(item.name for item in applicable_stack))[:12]
        stack_evidence_ids = tuple(
            dict.fromkeys(
                registry.add(
                    tier=EvidenceTier.CODE_OBSERVED,
                    source=item.source,
                    note="Technology is declared by a repository manifest.",
                )
                for item in applicable_stack
                if item.name in technologies
            )
        )
        result.append(
            ArchitectureComponent(
                id=f"component.{_stable_hash(observation.path)[:16]}",
                kind=_architecture_kind(observation),
                name=observation.path,
                responsibility=observation.summary,
                repository_paths=(observation.path,),
                technologies=technologies,
                evidence_ref_ids=(evidence_id, *stack_evidence_ids),
            )
        )
    return tuple(result)


def _capabilities(
    documented: DocumentedProject,
    frame: RepoFrame,
    edges: WorkspaceEdgeObservation,
    concepts: tuple[Concept, ...],
    components: tuple[ArchitectureComponent, ...],
    registry: _EvidenceRegistry,
) -> tuple[tuple[Capability, ...], tuple[CapabilitySurface, ...]]:
    seeds: list[tuple[DocumentedCapability, EvidenceTier]] = [
        (item, EvidenceTier.DOCUMENTATION_STATED)
        for item in documented.capabilities[:MAX_CAPABILITIES]
    ]
    if not seeds:
        seeds.extend(
            (item, EvidenceTier.CODE_OBSERVED)
            for item in _observed_capability_seeds(frame)[:MAX_CAPABILITIES]
        )

    deduped_seeds: list[tuple[DocumentedCapability, EvidenceTier]] = []
    seen_seed_names: set[str] = set()
    for seed, seed_tier in seeds:
        normalized_name = _normalized(seed.name)
        if not normalized_name or normalized_name in seen_seed_names:
            continue
        seen_seed_names.add(normalized_name)
        deduped_seeds.append((seed, seed_tier))

    capabilities: list[Capability] = []
    all_surfaces: list[CapabilitySurface] = []
    used_surface_ids: set[str] = set()
    for seed, seed_tier in deduped_seeds:
        capability_id = f"capability.{_stable_hash(_normalized(seed.name))[:16]}"
        seed_ref = registry.add(
            tier=seed_tier,
            source=seed.source,
            note=(
                "Repository-stated capability."
                if seed_tier is EvidenceTier.DOCUMENTATION_STATED
                else "Capability root derived from an observed interface declaration."
            ),
        )
        matches = _surface_matches(seed, frame)
        matches = _augment_exact_surface_matches(matches, edges, frame)
        selected_matches = _select_surface_matches(matches)
        surface_ids: list[str] = []
        component_ids: list[str] = []
        surface_ref_ids: list[str] = []
        production_matches: list[_SurfaceMatch] = []
        verification_matches: list[_SurfaceMatch] = []
        for match in selected_matches:
            surface = _surface(
                capability_id,
                seed,
                match,
                registry,
            )
            if surface.id in used_surface_ids:
                continue
            used_surface_ids.add(surface.id)
            all_surfaces.append(surface)
            surface_ids.append(surface.id)
            surface_ref_ids.extend(surface.evidence_ref_ids)
            if match.file.is_test:
                verification_matches.append(match)
            else:
                production_matches.append(match)
            component = _component_for_path(match.file.path, components)
            if component is not None:
                component_ids.append(component.id)
        concept_ids = tuple(
            concept.id
            for concept in concepts
            if _word_roots(concept.name) & _word_roots(f"{seed.name} {seed.summary}")
        )
        strongly_observed = any(
            _surface_match_is_established(match) for match in production_matches
        )
        indexed_by_path = {item.path: item for item in frame.indexed_files}
        established_production_matches = [
            match for match in production_matches if _surface_match_is_established(match)
        ]
        candidate_production_matches = [
            match for match in production_matches if not _surface_match_is_established(match)
        ]
        production_paths = {match.file.path for match in established_production_matches}
        exact_production_edges = [
            edge
            for edge in edges.edges
            if str(edge.get("rule_id") or "") in _EXACT_PRODUCTION_EDGE_RULES
            and (
                str(edge.get("rule_id") or "") != "local_module_import.v1"
                or str(edge.get("source_path") or "")
                != str(edge.get("target_path") or "")
            )
            and (
                str(edge.get("source_path") or "") in production_paths
                or str(edge.get("target_path") or "") in production_paths
            )
            and not getattr(
                indexed_by_path.get(str(edge.get("source_path") or "")),
                "is_test",
                False,
            )
            and not getattr(
                indexed_by_path.get(str(edge.get("target_path") or "")),
                "is_test",
                False,
            )
        ]
        # Individual exact edges establish structural association, not a
        # capability trace. Typed, contiguous traces are reconciled only after
        # ``_implementation_traces`` has proved the required hop sequence.
        implementation_coverage = (
            ImplementationCoverage.NONE
            if not production_matches
            else ImplementationCoverage.CANDIDATE_ONLY
            if not established_production_matches
            else ImplementationCoverage.ENTRYPOINT_ONLY
        )
        workflow = tuple(
            WorkflowStep(
                position=step.position,
                description=step.description,
                evidence_ref_ids=(
                    registry.add(
                        tier=EvidenceTier.DOCUMENTATION_STATED,
                        source=step.source,
                        note="Repository-stated workflow step; not execution proof.",
                    ),
                ),
            )
            for step in seed.steps[:8]
        )
        capabilities.append(
            Capability(
                id=capability_id,
                name=seed.name,
                summary=seed.summary,
                state=(
                    CapabilityState.OBSERVED
                    if surface_ids and strongly_observed
                    else CapabilityState.PARTIAL
                    if surface_ids
                    else CapabilityState.DOCUMENTED_ONLY
                ),
                workflow=workflow,
                assessment=CapabilityAssessment(
                    declaration_status=(
                        CapabilityDeclarationStatus.DECLARED
                        if seed_tier is EvidenceTier.DOCUMENTATION_STATED
                        else CapabilityDeclarationStatus.UNDECLARED
                    ),
                    implementation_coverage=implementation_coverage,
                    verification_status=(
                        CapabilityVerificationStatus.TEST_PRESENT
                        if verification_matches
                        else CapabilityVerificationStatus.ABSENT
                    ),
                    production_surface_count=len(established_production_matches),
                    candidate_surface_count=len(candidate_production_matches),
                    verification_surface_count=len(verification_matches),
                    exact_production_edge_count=len(exact_production_edges),
                ),
                concept_ids=concept_ids,
                surface_ids=tuple(surface_ids),
                component_ids=tuple(dict.fromkeys(component_ids)),
                evidence_ref_ids=tuple(dict.fromkeys([seed_ref, *surface_ref_ids])),
            )
        )
    return tuple(capabilities), tuple(all_surfaces)


def _surface_matches(
    capability: DocumentedCapability,
    frame: RepoFrame,
) -> list[_SurfaceMatch]:
    primary_terms = _capability_primary_terms(capability.name)
    secondary_terms = (
        _word_roots(
            " ".join(
                [
                    capability.summary,
                    *(step.description for step in capability.steps),
                ]
            )
        )
        - _CAPABILITY_STOP_WORDS
        - primary_terms
    )
    matches: list[_SurfaceMatch] = []
    for item in frame.indexed_files:
        if item.language == "markdown" or _is_noise_path(item.path):
            continue
        path_terms = _word_roots(item.path)
        symbol_pairs = [
            (symbol, _word_roots(symbol.name))
            for symbol in item.symbols[:120]
            if symbol.symbol_type != "module"
        ]
        route_pairs = [
            (route, _word_roots(route)) for route in item.route_hints
        ]
        matching_routes = [
            (route, terms) for route, terms in route_pairs if terms & primary_terms
        ]
        selected_route = (
            sorted(
                matching_routes,
                key=lambda pair: (
                    -len(pair[1] & primary_terms),
                    -len(pair[1] & secondary_terms),
                    len(pair[0]),
                    pair[0].casefold(),
                ),
            )[0]
            if matching_routes
            else None
        )
        primary_path = primary_terms & path_terms
        primary_symbols = [
            (symbol, terms & primary_terms)
            for symbol, terms in symbol_pairs
            if terms & primary_terms
        ]
        primary_routes = (
            primary_terms & selected_route[1] if selected_route is not None else set()
        )
        secondary_routes = (
            secondary_terms & selected_route[1] if selected_route is not None else set()
        )
        secondary_path = secondary_terms & path_terms
        secondary_symbol_terms = (
            set().union(*(terms & secondary_terms for _symbol, terms in symbol_pairs))
            if symbol_pairs
            else set()
        )
        score = (
            8.0 * len(primary_path)
            + 6.0 * len(primary_routes)
            + 5.0 * len({term for _symbol, terms in primary_symbols for term in terms})
            + 3.0 * len(secondary_routes)
            + 1.5 * len(secondary_path)
            + 0.5 * len(secondary_symbol_terms)
        )
        # Summary nouns are useful for ranking only after the capability's
        # own name (or one of its narrow product-interface aliases) matched.
        # Otherwise broad prose such as "provider" or "ready" creates a
        # convincing but false capability map.
        if not (primary_path or primary_symbols or primary_routes):
            continue
        if item.is_test:
            score -= 1.0
        route = selected_route[0] if selected_route is not None else None
        route_symbols = [
            symbol
            for symbol in item.symbols
            if route is not None
            and symbol.symbol_type == "route"
            and symbol.name == route
        ]
        symbol = (
            route_symbols[0]
            if len(route_symbols) == 1
            else primary_symbols[0][0]
            if primary_symbols
            else None
        )
        rule_id = (
            "capability_route_match.v1"
            if route
            else "capability_symbol_match.v1"
            if symbol
            else "capability_path_match.v1"
        )
        matched = tuple(
            sorted(
                primary_path
                | primary_routes
                | secondary_routes
                | {term for _symbol, terms in primary_symbols for term in terms}
                | secondary_path
                | secondary_symbol_terms
            )
        )
        matches.append(
            _SurfaceMatch(
                file=item,
                score=round(score, 6),
                rule_id=rule_id,
                matched_terms=matched,
                symbol=symbol,
                route=route,
            )
        )
    return sorted(matches, key=lambda item: (-item.score, item.file.path))


def _augment_exact_surface_matches(
    matches: list[_SurfaceMatch],
    edge_observation: WorkspaceEdgeObservation,
    frame: RepoFrame,
) -> list[_SurfaceMatch]:
    by_path = {item.path: item for item in frame.indexed_files}
    result = list(matches)
    matched_paths = {item.file.path for item in matches[:8] if _surface_match_is_established(item)}
    for edge in edge_observation.edges:
        source = str(edge.get("source_path") or "")
        target = str(edge.get("target_path") or "")
        related = None
        if target in matched_paths and source not in matched_paths:
            related = source
        elif source in matched_paths and target not in matched_paths:
            related = target
        if not related or related not in by_path:
            continue
        existing_for_path = [item for item in result if item.file.path == related]
        if any(_surface_match_is_established(item) for item in existing_for_path):
            continue
        if existing_for_path:
            result = [item for item in result if item.file.path != related]
        rule_id = str(edge.get("rule_id") or "")
        bonus = 7.5 if rule_id.startswith("test_") else 5.5
        result.append(
            _SurfaceMatch(
                file=by_path[related],
                score=bonus,
                rule_id=rule_id,
                matched_terms=(),
            )
        )
    return sorted(result, key=lambda item: (-item.score, item.file.path))


def _surface_match_is_established(match: _SurfaceMatch) -> bool:
    return match.rule_id != "capability_path_match.v1"


def _select_surface_matches(
    matches: list[_SurfaceMatch],
) -> tuple[_SurfaceMatch, ...]:
    if not matches:
        return ()
    minimum_score = max(4.5, matches[0].score * 0.42)
    selected: list[_SurfaceMatch] = []
    roles: set[SurfaceKind] = set()
    paths: set[str] = set()
    production = sorted(
        (item for item in matches if not item.file.is_test),
        key=lambda item: (-item.score, item.file.path),
    )
    verification = sorted(
        (item for item in matches if item.file.is_test),
        key=lambda item: (-item.score, item.file.path),
    )
    production_limit = MAX_CAPABILITY_SURFACES - (1 if verification else 0)
    for match in production:
        if (
            match.score < minimum_score
            and match.rule_id not in _EXACT_PRODUCTION_EDGE_RULES
        ):
            continue
        role = _surface_kind(match.file)
        if match.file.path in paths:
            continue
        if role in roles and len(selected) < 3:
            continue
        selected.append(match)
        roles.add(role)
        paths.add(match.file.path)
        if len(selected) >= production_limit:
            break
    verification_limit = 2 if not selected else 1
    for match in verification:
        if (
            match.score < minimum_score
            and not match.rule_id.startswith("test_")
        ) or match.file.path in paths:
            continue
        selected.append(match)
        paths.add(match.file.path)
        if sum(item.file.is_test for item in selected) >= verification_limit:
            break
    if not selected:
        return ()
    return tuple(selected)


def _surface(
    capability_id: str,
    capability: DocumentedCapability,
    match: _SurfaceMatch,
    registry: _EvidenceRegistry,
) -> CapabilitySurface:
    symbol = match.symbol
    start_line = symbol.start_line if symbol else None
    end_line = symbol.end_line if symbol else None
    evidence_id = registry.add(
        tier=EvidenceTier.CODE_OBSERVED,
        path=match.file.path,
        source_sha256=match.file.sha256,
        start_line=start_line,
        end_line=end_line,
        symbol=(symbol.qualified_name or symbol.name) if symbol else None,
        rule=match.rule_id,
        note=(
            f"Deterministic code-location link for {capability.name}; matched "
            f"terms: {', '.join(match.matched_terms) or 'exact structural edge'}. "
            "This does not prove runtime behaviour."
        ),
    )
    locator = match.file.path
    if symbol and symbol.start_line:
        locator = f"{locator}:{symbol.start_line}"
    elif match.route:
        locator = f"{locator} route {match.route}"
    surface_id = f"surface.{_stable_hash(f'{capability_id}:{locator}')[:16]}"
    return CapabilitySurface(
        id=surface_id,
        kind=_surface_kind(match.file),
        role=_surface_role(match.file),
        derivation=_surface_derivation(match),
        name=(
            match.route or ((symbol.qualified_name or symbol.name) if symbol else match.file.path)
        ),
        description=(
            f"Code-observed surface linked by {match.rule_id}; runtime and test "
            "status remain unverified."
        ),
        locator=locator,
        repository_path=match.file.path,
        evidence_ref_ids=(evidence_id,),
    )


def _surface_derivation(match: _SurfaceMatch) -> SurfaceDerivation:
    if match.rule_id in {"capability_route_match.v1", "route_capability_root.v1"}:
        return SurfaceDerivation.EXACT_ROUTE
    if match.rule_id == "capability_symbol_match.v1":
        return SurfaceDerivation.SYMBOL_MATCH
    if match.rule_id in {
        "local_module_import.v1",
        "local_symbol_call.v1",
        "route_handler_owner.v1",
        "static_http_route_reference.v1",
        "test_path_match.v1",
        "test_symbol_match.v1",
    }:
        return SurfaceDerivation.EXACT_EDGE
    return SurfaceDerivation.PATH_HEURISTIC


def _structural_edges(
    observation: WorkspaceEdgeObservation,
    components: tuple[ArchitectureComponent, ...],
    capabilities: tuple[Capability, ...],
    surfaces: tuple[CapabilitySurface, ...],
    implementation_traces: tuple[ImplementationTrace, ...],
    registry: _EvidenceRegistry,
    frame: RepoFrame,
) -> tuple[StructuralEdge, ...]:
    indexed = {item.path: item for item in frame.indexed_files}
    surface_by_id = {surface.id: surface for surface in surfaces}
    grouped: dict[
        tuple[str, str, StructuralRelation],
        list[tuple[dict[str, Any], tuple[str, ...]]],
    ] = {}
    component_by_id = {component.id: component for component in components}
    for raw in observation.edges:
        source_path = str(raw.get("source_path") or "")
        target_path = str(raw.get("target_path") or "")
        source_component = _component_for_path(source_path, components)
        target_component = _component_for_path(target_path, components)
        if (
            source_component is None
            or target_component is None
            or source_component.id == target_component.id
        ):
            continue
        evidence_path = str(raw.get("evidence_path") or source_path)
        evidence_file = indexed.get(evidence_path)
        if evidence_file is None or not evidence_file.sha256:
            continue
        relation = _structural_relation(str(raw.get("edge_type") or ""))
        key = (source_component.id, target_component.id, relation)
        capability_ids = _structural_edge_capability_ids(
            raw,
            capabilities=capabilities,
            surface_by_id=surface_by_id,
            implementation_traces=implementation_traces,
        )
        grouped.setdefault(key, []).append((raw, capability_ids))

    result: list[StructuralEdge] = []
    for key, candidates in grouped.items():
        source_component_id, target_component_id, relation = key
        source_component = component_by_id[source_component_id]
        target_component = component_by_id[target_component_id]
        ordered_candidates = sorted(
            candidates,
            key=lambda item: (
                -len(item[1]),
                bool(indexed[str(item[0].get("source_path") or "")].is_test),
                str(item[0].get("edge_key") or ""),
            ),
        )
        representative, _representative_capabilities = ordered_candidates[0]
        capability_ids = tuple(
            capability.id
            for capability in capabilities
            if any(capability.id in candidate_ids for _raw, candidate_ids in candidates)
        )[:8]
        evidence_candidates = [representative]
        for capability_id in capability_ids:
            supporting = next(
                raw
                for raw, candidate_ids in ordered_candidates
                if capability_id in candidate_ids
            )
            if supporting not in evidence_candidates:
                evidence_candidates.append(supporting)
        evidence_ref_ids: list[str] = []
        for raw in evidence_candidates[:24]:
            evidence_path = str(
                raw.get("evidence_path") or raw.get("source_path") or ""
            )
            evidence_file = indexed[evidence_path]
            evidence_ref_ids.append(
                registry.add(
                    tier=EvidenceTier.CODE_OBSERVED,
                    path=evidence_path,
                    source_sha256=evidence_file.sha256,
                    start_line=raw.get("evidence_start_line"),
                    end_line=raw.get("evidence_end_line"),
                    rule=str(raw.get("rule_id") or "workspace_edge.v1"),
                    note="Exact syntax-level structural edge; not runtime proof.",
                )
            )
        source_path = str(representative.get("source_path") or "")
        target_path = str(representative.get("target_path") or "")
        description = (
            f"{source_path} "
            f"{representative.get('edge_type') or 'relates to'} {target_path}."
            if len(candidates) == 1
            else (
                f"{source_component.name} {relation.value} {target_component.name} "
                f"through {len(candidates)} exact syntax-level edges."
            )
        )
        result.append(
            StructuralEdge(
                id=f"edge.{_stable_hash(f'{source_component_id}:{target_component_id}:{relation.value}')[:16]}",
                source_component_id=source_component_id,
                target_component_id=target_component_id,
                relation=relation,
                description=description,
                capability_ids=capability_ids,
                evidence_ref_ids=tuple(dict.fromkeys(evidence_ref_ids)),
            )
        )
    return tuple(result)


def _structural_edge_capability_ids(
    raw: dict[str, Any],
    *,
    capabilities: tuple[Capability, ...],
    surface_by_id: dict[str, CapabilitySurface],
    implementation_traces: tuple[ImplementationTrace, ...],
) -> tuple[str, ...]:
    """Attribute one exact edge without inheriting broad component membership."""

    result: list[str] = []
    for capability in capabilities:
        exact_surface_match = any(
            _surface_supports_structural_edge(surface, raw)
            for surface_id in capability.surface_ids
            if (surface := surface_by_id.get(surface_id)) is not None
        )
        exact_trace_match = any(
            capability.id in trace.capability_ids
            and any(_trace_hop_matches_structural_edge(hop, raw) for hop in trace.hops)
            for trace in implementation_traces
        )
        if exact_surface_match or exact_trace_match:
            result.append(capability.id)
    return tuple(result[:8])


def _surface_supports_structural_edge(
    surface: CapabilitySurface,
    raw: dict[str, Any],
) -> bool:
    if (
        surface.repository_path is None
        or surface.derivation is SurfaceDerivation.PATH_HEURISTIC
    ):
        return False
    source_path = str(raw.get("source_path") or "")
    target_path = str(raw.get("target_path") or "")
    if surface.repository_path not in {source_path, target_path}:
        return False
    source_symbol, target_symbol = _raw_structural_edge_symbols(raw)
    endpoint_symbol = (
        source_symbol if surface.repository_path == source_path else target_symbol
    )
    if endpoint_symbol is None:
        return True
    if surface.derivation is SurfaceDerivation.EXACT_EDGE:
        return False
    return _normalized(surface.name) == _normalized(endpoint_symbol)


def _trace_hop_matches_structural_edge(
    hop: ImplementationTraceHop,
    raw: dict[str, Any],
) -> bool:
    if (
        hop.source_path != str(raw.get("source_path") or "")
        or hop.target_path != str(raw.get("target_path") or "")
        or hop.relation is not _structural_relation(str(raw.get("edge_type") or ""))
    ):
        return False
    source_symbol, target_symbol = _raw_structural_edge_symbols(raw)
    return _optional_symbol_matches(hop.source_symbol, source_symbol) and (
        _optional_symbol_matches(hop.target_symbol, target_symbol)
    )


def _optional_symbol_matches(observed: str | None, expected: str | None) -> bool:
    if expected is None:
        return True
    return observed is not None and _normalized(observed) == _normalized(expected)


def _raw_structural_edge_symbols(
    raw: dict[str, Any],
) -> tuple[str | None, str | None]:
    evidence = raw.get("evidence") or {}
    rule_id = str(raw.get("rule_id") or "")
    if rule_id == "static_http_route_reference.v1":
        return None, str(evidence.get("declared_route") or "") or None
    if rule_id == "route_handler_owner.v1":
        return (
            str(evidence.get("route") or "") or None,
            str(evidence.get("handler_symbol") or "") or None,
        )
    if rule_id == "local_symbol_call.v1":
        return (
            str(evidence.get("caller") or "") or None,
            str(evidence.get("callee") or "") or None,
        )
    if rule_id == "test_symbol_match.v1":
        return (
            str(evidence.get("test_symbol") or "") or None,
            str(evidence.get("target_symbol") or "") or None,
        )
    return None, None


def _implementation_traces(
    observation: WorkspaceEdgeObservation,
    capabilities: tuple[Capability, ...],
    surfaces: tuple[CapabilitySurface, ...],
    registry: _EvidenceRegistry,
    frame: RepoFrame,
) -> tuple[ImplementationTrace, ...]:
    """Build exact production call flows, with import dependencies as fallback.

    Both lanes intentionally exclude tests. Route/call relationships may establish
    a static production flow; imports remain structural dependencies and are never
    upgraded to call or data-flow evidence.
    """

    indexed = {item.path: item for item in frame.indexed_files}
    surface_by_id = {surface.id: surface for surface in surfaces}
    eligible = [
        raw
        for raw in observation.edges
        if str(raw.get("rule_id") or "") == "local_module_import.v1"
        and str(raw.get("source_path") or "") != str(raw.get("target_path") or "")
        and str(raw.get("source_path") or "") in indexed
        and str(raw.get("target_path") or "") in indexed
        and not indexed[str(raw.get("source_path"))].is_test
        and not indexed[str(raw.get("target_path"))].is_test
    ]
    adjacency: dict[str, list[dict[str, Any]]] = {}
    incoming: dict[str, list[dict[str, Any]]] = {}
    for raw in eligible:
        source = str(raw.get("source_path") or "")
        target = str(raw.get("target_path") or "")
        adjacency.setdefault(source, []).append(raw)
        incoming.setdefault(target, []).append(raw)
    for values in (*adjacency.values(), *incoming.values()):
        values.sort(key=lambda item: str(item.get("edge_key") or ""))

    def longest_from(
        path: str,
        *,
        visited: frozenset[str],
        remaining: int,
    ) -> tuple[dict[str, Any], ...]:
        if remaining <= 0:
            return ()
        candidates: list[tuple[dict[str, Any], ...]] = [()]
        for raw in adjacency.get(path, []):
            target = str(raw.get("target_path") or "")
            if target in visited:
                continue
            tail = longest_from(
                target,
                visited=visited | {target},
                remaining=remaining - 1,
            )
            candidates.append((raw, *tail))
        return max(
            candidates,
            key=lambda values: (
                len(values),
                tuple(str(item.get("edge_key") or "") for item in values),
            ),
        )

    traces: list[ImplementationTrace] = []
    for capability in capabilities:
        capability_surfaces = [
            surface
            for surface_id in capability.surface_ids
            if (surface := surface_by_id.get(surface_id)) is not None
            and surface.role is not SurfaceRole.VERIFICATION
            and surface.repository_path is not None
        ]
        surface_paths = {surface.repository_path for surface in capability_surfaces}
        call_flow = _capability_call_trace(
            capability,
            capability_surfaces,
            registry,
            frame,
        )
        if call_flow is not None:
            traces.append(call_flow)
            if len(traces) >= MAX_CAPABILITIES:
                break
            continue
        surface_role_score = {
            surface.repository_path: {
                SurfaceRole.ENTRYPOINT: 5,
                SurfaceRole.IMPLEMENTATION: 4,
                SurfaceRole.DATA: 3,
                SurfaceRole.OPERATIONS: 2,
                SurfaceRole.DOCUMENTATION: 1,
                SurfaceRole.OTHER: 0,
            }.get(surface.role, 0)
            for surface in capability_surfaces
        }
        candidates: list[tuple[dict[str, Any], ...]] = []
        for path in sorted(surface_paths):
            candidates.append(longest_from(path, visited=frozenset({path}), remaining=5))
            for raw in incoming.get(path, []):
                source = str(raw.get("source_path") or "")
                tail = longest_from(
                    path,
                    visited=frozenset({source, path}),
                    remaining=4,
                )
                candidates.append((raw, *tail))
        candidates = [candidate for candidate in candidates if candidate]
        if not candidates:
            continue
        selected = max(
            candidates,
            key=lambda values: (
                surface_role_score.get(
                    str(values[0].get("source_path") or ""),
                    0,
                ),
                len(values),
                sum(
                    str(item.get("source_path") or "") in surface_paths
                    or str(item.get("target_path") or "") in surface_paths
                    for item in values
                ),
                tuple(str(item.get("edge_key") or "") for item in values),
            ),
        )
        path_identity = (
            str(selected[0].get("source_path") or ""),
            *(str(item.get("target_path") or "") for item in selected),
        )
        hops: list[ImplementationTraceHop] = []
        for raw in selected:
            evidence_path = str(raw.get("evidence_path") or raw.get("source_path") or "")
            evidence_file = indexed.get(evidence_path)
            if evidence_file is None or not evidence_file.sha256:
                hops = []
                break
            evidence_id = registry.add(
                tier=EvidenceTier.CODE_OBSERVED,
                path=evidence_path,
                source_sha256=evidence_file.sha256,
                start_line=raw.get("evidence_start_line"),
                end_line=raw.get("evidence_end_line"),
                rule=str(raw.get("rule_id") or "local_module_import.v1"),
                note=(
                    "Exact local import used in a partial implementation trace; "
                    "this is not proof of runtime call order."
                ),
            )
            hops.append(
                ImplementationTraceHop(
                    source_path=str(raw.get("source_path") or ""),
                    target_path=str(raw.get("target_path") or ""),
                    relation=StructuralRelation.DEPENDS_ON,
                    evidence_ref_ids=(evidence_id,),
                )
            )
        if not hops:
            continue
        traces.append(
            ImplementationTrace(
                id=f"trace.{_stable_hash(f'{capability.id}:{path_identity}')[:16]}",
                name=capability.name,
                summary=(
                    "Exact local-import path connected to this capability's code "
                    "surfaces; dependency direction is structural, not runtime order."
                ),
                kind=ImplementationTraceKind.STRUCTURAL_DEPENDENCY,
                coverage=ImplementationTraceCoverage.PARTIAL,
                capability_ids=(capability.id,),
                hops=tuple(hops),
                gaps=(
                    "Runtime dispatch, network calls, persistence, and external-system "
                    "hops are unknown unless separately evidenced.",
                ),
            )
        )
        if len(traces) >= MAX_CAPABILITIES:
            break
    return tuple(traces)


def _capability_call_trace(
    capability: Capability,
    capability_surfaces: list[CapabilitySurface],
    registry: _EvidenceRegistry,
    frame: RepoFrame,
) -> ImplementationTrace | None:
    """Build one entrypoint-backed flow, or an explicitly internal call chain."""

    indexed = {item.path: item for item in frame.indexed_files}
    established_surfaces = [
        surface
        for surface in capability_surfaces
        if surface.repository_path is not None
        and surface.derivation is not SurfaceDerivation.PATH_HEURISTIC
    ]
    anchor_paths = tuple(sorted({str(surface.repository_path) for surface in established_surfaces}))
    if not anchor_paths:
        return None
    primary_terms = frozenset(_capability_primary_terms(capability.name))
    secondary_terms = frozenset(
        _word_roots(
            " ".join(
                [
                    capability.summary,
                    *(step.description for step in capability.workflow),
                ]
            )
        )
        - _CAPABILITY_STOP_WORDS
        - primary_terms
    )
    preferred_terms = primary_terms | secondary_terms
    observed = observe_workspace_flow_edges_result(
        frame,
        anchor_paths=anchor_paths,
        preferred_terms=preferred_terms,
    )
    raw_edges = tuple(observed.edges)
    call_edges = tuple(
        edge for edge in raw_edges if str(edge.get("rule_id") or "") == "local_symbol_call.v1"
    )
    if not call_edges:
        return None

    calls_by_caller: dict[str, list[dict[str, Any]]] = {}
    for edge in call_edges:
        caller = str((edge.get("evidence") or {}).get("caller") or "")
        if caller:
            calls_by_caller.setdefault(caller, []).append(edge)
    for edges in calls_by_caller.values():
        edges.sort(key=lambda item: str(item.get("edge_key") or ""))

    def best_calls(
        caller: str,
        *,
        visited: frozenset[str],
        remaining: int,
    ) -> tuple[dict[str, Any], ...]:
        if remaining <= 0:
            return ()
        candidates: list[tuple[dict[str, Any], ...]] = [()]
        for edge in calls_by_caller.get(caller, ()):
            callee = str((edge.get("evidence") or {}).get("callee") or "")
            if not callee or callee in visited:
                continue
            candidates.append(
                (
                    edge,
                    *best_calls(
                        callee,
                        visited=visited | {callee},
                        remaining=remaining - 1,
                    ),
                )
            )
        return max(
            candidates,
            key=lambda values: _production_flow_candidate_key(
                values,
                primary_terms=primary_terms,
                secondary_terms=secondary_terms,
                anchor_paths=frozenset(anchor_paths),
                indexed=indexed,
            ),
        )

    route_edges = tuple(
        edge for edge in raw_edges if str(edge.get("rule_id") or "") == "route_handler_owner.v1"
    )
    http_edges = tuple(
        edge
        for edge in raw_edges
        if str(edge.get("rule_id") or "") == "static_http_route_reference.v1"
    )
    entrypoint_candidates: list[tuple[dict[str, Any], ...]] = []

    for route_edge in route_edges:
        handler = str((route_edge.get("evidence") or {}).get("handler_symbol") or "")
        tail = best_calls(
            handler,
            visited=frozenset({handler}),
            remaining=5,
        )
        if tail:
            entrypoint_candidates.append((route_edge, *tail))

    route_by_signature = {
        (
            str(edge.get("source_path") or ""),
            str((edge.get("evidence") or {}).get("route") or ""),
        ): edge
        for edge in route_edges
    }
    for http_edge in http_edges:
        signature = (
            str(http_edge.get("target_path") or ""),
            str((http_edge.get("evidence") or {}).get("declared_route") or ""),
        )
        route_edge = route_by_signature.get(signature)
        if route_edge is None:
            continue
        handler = str((route_edge.get("evidence") or {}).get("handler_symbol") or "")
        tail = best_calls(
            handler,
            visited=frozenset({handler}),
            remaining=5,
        )
        if tail:
            entrypoint_candidates.append((http_edge, route_edge, *tail))

    internal_candidates: list[tuple[dict[str, Any], ...]] = []
    for call_edge in call_edges:
        if str(call_edge.get("source_path") or "") not in anchor_paths:
            continue
        caller = str((call_edge.get("evidence") or {}).get("caller") or "")
        callee = str((call_edge.get("evidence") or {}).get("callee") or "")
        tail = best_calls(
            callee,
            visited=frozenset({caller, callee}),
            remaining=4,
        )
        internal_candidates.append((call_edge, *tail))

    relevance_terms = primary_terms | secondary_terms
    entrypoint_candidates = [
        candidate
        for candidate in entrypoint_candidates
        if _flow_candidate_has_endpoint_relevance(candidate, relevance_terms)
    ]
    internal_candidates = [
        candidate
        for candidate in internal_candidates
        if _flow_candidate_has_endpoint_relevance(candidate, relevance_terms)
    ]
    candidates = entrypoint_candidates or internal_candidates
    if not candidates:
        return None
    selected = max(
        candidates,
        key=lambda values: _production_flow_candidate_key(
            values,
            primary_terms=primary_terms,
            secondary_terms=secondary_terms,
            anchor_paths=frozenset(anchor_paths),
            indexed=indexed,
        ),
    )
    trace_kind = (
        ImplementationTraceKind.PRODUCTION_CALL_FLOW
        if entrypoint_candidates
        else ImplementationTraceKind.INTERNAL_CALL_CHAIN
    )
    if not any(str(edge.get("rule_id") or "") == "local_symbol_call.v1" for edge in selected):
        return None

    hops: list[ImplementationTraceHop] = []
    for raw in selected:
        evidence_path = str(raw.get("evidence_path") or raw.get("source_path") or "")
        evidence_file = indexed.get(evidence_path)
        if evidence_file is None or not evidence_file.sha256:
            return None
        rule_id = str(raw.get("rule_id") or "workspace_flow_edge.v1")
        evidence_id = registry.add(
            tier=EvidenceTier.CODE_OBSERVED,
            path=evidence_path,
            source_sha256=evidence_file.sha256,
            start_line=raw.get("evidence_start_line"),
            end_line=raw.get("evidence_end_line"),
            rule=rule_id,
            note=(
                "Exact static route, handler ownership, or local-symbol call in a "
                "partial capability trace; this is not runtime execution proof."
            ),
        )
        raw_evidence = raw.get("evidence") or {}
        source_symbol: str | None = None
        target_symbol: str | None = None
        if rule_id == "static_http_route_reference.v1":
            target_symbol = str(raw_evidence.get("declared_route") or "") or None
        elif rule_id == "route_handler_owner.v1":
            source_symbol = str(raw_evidence.get("route") or "") or None
            target_symbol = str(raw_evidence.get("handler_symbol") or "") or None
        elif rule_id == "local_symbol_call.v1":
            source_symbol = str(raw_evidence.get("caller") or "") or None
            target_symbol = str(raw_evidence.get("callee") or "") or None
        hops.append(
            ImplementationTraceHop(
                source_path=str(raw.get("source_path") or ""),
                target_path=str(raw.get("target_path") or ""),
                relation=_structural_relation(str(raw.get("edge_type") or "")),
                source_symbol=source_symbol,
                target_symbol=target_symbol,
                evidence_ref_ids=(evidence_id,),
            )
        )

    prefix_rules = {str(edge.get("rule_id") or "") for edge in selected[:2]}
    gaps = ["Runtime execution, branch selection, failures, and returned effects remain unknown."]
    if not prefix_rules & {
        "static_http_route_reference.v1",
        "route_handler_owner.v1",
    }:
        gaps.append("Dispatch before the first exact local-symbol call is not established.")
    final_path = str(selected[-1].get("target_path") or "")
    if final_path in indexed and _surface_role(indexed[final_path]) is not SurfaceRole.DATA:
        gaps.append(
            "Persistence and external-system effects after the final exact call are unknown."
        )
    identity = tuple(str(edge.get("edge_key") or "") for edge in selected)
    return ImplementationTrace(
        id=f"trace.{_stable_hash(f'{capability.id}:{identity}')[:16]}",
        name=capability.name,
        summary=(
            "Exact static client-route or route-handler entrypoint followed by a "
            "local-symbol call chain; runtime execution is not implied."
            if trace_kind is ImplementationTraceKind.PRODUCTION_CALL_FLOW
            else "Exact local-symbol call chain connected to this capability, with no "
            "entrypoint established; runtime execution is not implied."
        ),
        kind=trace_kind,
        coverage=ImplementationTraceCoverage.PARTIAL,
        capability_ids=(capability.id,),
        hops=tuple(hops),
        gaps=tuple(gaps),
    )


def _flow_candidate_endpoint_terms(
    edges: tuple[dict[str, Any], ...],
) -> tuple[set[str], set[str]]:
    route_terms = _word_roots(
        " ".join(
            str((edge.get("evidence") or {}).get(field) or "")
            for edge in edges
            for field in ("route", "declared_route", "client_path")
        )
    )
    symbol_terms = _word_roots(
        " ".join(
            str((edge.get("evidence") or {}).get(field) or "")
            for edge in edges
            for field in (
                "caller",
                "callee",
                "handler",
                "handler_symbol",
                "route_symbol",
            )
        )
    )
    return route_terms, symbol_terms


def _flow_candidate_has_endpoint_relevance(
    edges: tuple[dict[str, Any], ...],
    relevance_terms: frozenset[str],
) -> bool:
    route_terms, symbol_terms = _flow_candidate_endpoint_terms(edges)
    return bool((route_terms | symbol_terms) & relevance_terms)


def _production_flow_candidate_key(
    edges: tuple[dict[str, Any], ...],
    *,
    primary_terms: frozenset[str],
    secondary_terms: frozenset[str],
    anchor_paths: frozenset[str],
    indexed: dict[str, IndexedFile],
) -> tuple[int, int, int, int, int, int, int, int, tuple[str, ...]]:
    if not edges:
        return (0, 0, 0, 0, 0, 0, 0, 0, ())
    rules = [str(edge.get("rule_id") or "") for edge in edges]
    route_terms, symbol_terms = _flow_candidate_endpoint_terms(edges)
    path_terms = _word_roots(
        " ".join(
            str(edge.get(field) or "")
            for edge in edges
            for field in ("source_path", "target_path")
        )
    )
    primary_relevance = (
        24 * len(route_terms & primary_terms)
        + 16 * len(symbol_terms & primary_terms)
        + 4 * len(path_terms & primary_terms)
    )
    secondary_relevance = (
        12 * len(route_terms & secondary_terms)
        + 8 * len(symbol_terms & secondary_terms)
        + 2 * len(path_terms & secondary_terms)
    )
    relevance_score = primary_relevance + secondary_relevance
    paths = [
        str(edges[0].get("source_path") or ""),
        *(str(edge.get("target_path") or "") for edge in edges),
    ]
    roles = [_surface_role(indexed[path]) for path in paths if path in indexed]
    preferred_transitions = sum(
        (source, target)
        in {
            (SurfaceRole.ENTRYPOINT, SurfaceRole.IMPLEMENTATION),
            (SurfaceRole.ENTRYPOINT, SurfaceRole.DATA),
            (SurfaceRole.IMPLEMENTATION, SurfaceRole.DATA),
            (SurfaceRole.ENTRYPOINT, SurfaceRole.OPERATIONS),
            (SurfaceRole.IMPLEMENTATION, SurfaceRole.OPERATIONS),
        }
        for source, target in zip(roles, roles[1:])
    )
    distinct_roles = len(set(roles))
    cross_file_calls = sum(
        str(edge.get("rule_id") or "") == "local_symbol_call.v1"
        and str(edge.get("source_path") or "")
        != str(edge.get("target_path") or "")
        for edge in edges
    )
    prefix_strength = (
        3
        if rules[:2]
        == [
            "static_http_route_reference.v1",
            "route_handler_owner.v1",
        ]
        else 2
        if rules and rules[0] == "route_handler_owner.v1"
        else 1
    )
    return (
        relevance_score,
        primary_relevance,
        preferred_transitions,
        distinct_roles,
        cross_file_calls,
        prefix_strength,
        len(set(paths) & anchor_paths),
        len(edges),
        tuple(str(edge.get("edge_key") or "") for edge in edges),
    )


def _merge_required_command_declarations(
    observations: tuple[DeclaredCommand, ...],
    required_commands: tuple[DeclaredCommand, ...],
) -> tuple[DeclaredCommand, ...]:
    """Keep every required exact key while retaining other bounded declarations."""

    merged: list[DeclaredCommand] = []
    seen: set[tuple[str, str]] = set()
    for observation in (*required_commands, *observations):
        key = (observation.command, observation.working_directory)
        if key in seen:
            continue
        seen.add(key)
        merged.append(observation)
    return tuple(merged)


def _verification_policy(
    observation: DeclaredVerificationPolicy,
    registry: _EvidenceRegistry,
) -> VerificationPolicy:
    """Convert the fail-closed adapter result without upgrading its evidence tier."""

    evidence_by_source: dict[tuple[Any, ...], str] = {}

    def source_evidence(source: SourceLocation) -> str:
        key = (
            source.path,
            source.sha256,
            source.start_line,
            source.end_line,
            source.heading,
            source.rule_id,
        )
        existing = evidence_by_source.get(key)
        if existing is not None:
            return existing
        evidence_id = registry.add(
            tier=EvidenceTier.CODE_OBSERVED,
            source=source,
            note=(
                "Required-check declaration observed in an exact indexed workflow; "
                "the declaration is not an execution result."
            ),
        )
        evidence_by_source[key] = evidence_id
        return evidence_id

    policy_evidence = [source_evidence(source) for source in observation.sources]
    required: list[RequiredVerificationCommand] = []
    for command in observation.required_commands:
        evidence_id = source_evidence(command.source)
        policy_evidence.append(evidence_id)
        required.append(
            RequiredVerificationCommand(
                key=RequiredCommandKey(
                    command=command.command,
                    working_directory=command.working_directory,
                ),
                name=_bounded_text(command.purpose, 240),
                kind=_command_kind(command),
                evidence_ref_ids=(evidence_id,),
            )
        )
    return VerificationPolicy(
        source=VerificationPolicySource(observation.source),
        discovery_complete=observation.discovery_complete,
        required_commands=tuple(required),
        incomplete_reasons=observation.incomplete_reasons,
        evidence_ref_ids=tuple(dict.fromkeys(policy_evidence)),
    )


def _commands(
    observations: tuple[DeclaredCommand, ...],
    verification_observations: tuple[WorkspaceVerificationObservation, ...],
    registry: _EvidenceRegistry,
) -> tuple[WorkspaceCommand, ...]:
    newest_execution_by_key: dict[tuple[str, str], WorkspaceVerificationObservation] = {}
    for observation in sorted(
        verification_observations,
        key=lambda item: (
            -item.observed_at.timestamp(),
            item.command,
            item.cwd,
            item.run_observation_id,
        ),
    ):
        newest_execution_by_key.setdefault(
            (observation.command, observation.cwd),
            observation,
        )

    result: list[WorkspaceCommand] = []
    represented_execution_keys: set[tuple[str, str]] = set()
    seen_declarations: set[tuple[str, str]] = set()
    for observation in observations:
        declaration_key = (observation.command, observation.working_directory)
        if declaration_key in seen_declarations:
            continue
        seen_declarations.add(declaration_key)
        evidence_id = registry.add(
            tier=EvidenceTier.CODE_OBSERVED,
            source=observation.source,
            note=(
                "Required repository check; declaration alone does not establish an "
                "execution result."
                if observation.required
                else (
                    "Command is declared by the repository. Declaration alone does not "
                    "establish an execution result."
                )
            ),
        )
        execution = newest_execution_by_key.get(declaration_key)
        verification, execution_ref = _command_verification(
            execution,
            _command_kind(observation),
            registry,
        )
        if execution is not None:
            represented_execution_keys.add(declaration_key)
        result.append(
            WorkspaceCommand(
                id=(
                    "command."
                    f"{_stable_hash(f'{observation.command}\0{observation.working_directory}')[:16]}"
                ),
                name=_bounded_text(observation.purpose, 240),
                purpose=observation.purpose,
                kind=_command_kind(observation),
                origin=CommandOrigin.DECLARED,
                command=observation.command,
                working_directory=observation.working_directory,
                verification=verification,
                evidence_ref_ids=tuple(
                    reference_id
                    for reference_id in (evidence_id, execution_ref)
                    if reference_id is not None
                ),
            )
        )

    for execution_key, execution in newest_execution_by_key.items():
        if execution_key in represented_execution_keys:
            continue
        kind = _command_kind_text(execution.command)
        verification, evidence_id = _command_verification(execution, kind, registry)
        if evidence_id is None:
            continue
        result.append(
            WorkspaceCommand(
                id=f"command.{_stable_hash(f'{execution.command}\0{execution.cwd}')[:16]}",
                name=_observed_command_name(kind),
                purpose="Exact-snapshot command execution captured by the local harness.",
                kind=kind,
                origin=CommandOrigin.OBSERVED,
                command=execution.command,
                working_directory=execution.cwd,
                verification=verification,
                evidence_ref_ids=(evidence_id,),
            )
        )
    return tuple(result)


def _command_verification(
    observation: WorkspaceVerificationObservation | None,
    kind: CommandKind,
    registry: _EvidenceRegistry,
) -> tuple[CommandVerification, str | None]:
    if observation is None:
        return CommandVerification(), None
    evidence_id = registry.add(
        tier=(
            EvidenceTier.TEST_VERIFIED
            if kind in {CommandKind.TEST, CommandKind.SMOKE_TEST}
            else EvidenceTier.RUNTIME_VERIFIED
        ),
        source_sha256=observation.payload_sha256,
        rule=observation.evidence_rule,
        note=(
            "Local-harness command result admitted only after its complete "
            "repository-after snapshot exactly matched the current repository frame; "
            f"cwd={observation.cwd}; exit_code={observation.exit_code}; "
            f"agent_run={observation.agent_run_id}; "
            f"verification_observation={observation.run_observation_id}; "
            f"outcome_observation={observation.outcome_observation_id}."
        ),
    )
    if observation.timed_out and observation.exit_code == 0:
        status = CommandVerificationStatus.BLOCKED
        summary = "Exact-snapshot execution timed out; no passing result is claimed."
    elif observation.exit_code == 0:
        status = CommandVerificationStatus.PASSED
        summary = "Exact-snapshot execution completed with exit code 0."
    else:
        status = CommandVerificationStatus.FAILED
        summary = (
            "Exact-snapshot execution timed out with a non-zero exit code."
            if observation.timed_out
            else "Exact-snapshot execution completed with a non-zero exit code."
        )
    return (
        CommandVerification(
            status=status,
            verified_at=observation.observed_at,
            exit_code=observation.exit_code,
            output_sha256=observation.output_sha256,
            summary=summary,
            evidence_ref_ids=(evidence_id,),
        ),
        evidence_id,
    )


def _capabilities_with_implementation_traces(
    capabilities: tuple[Capability, ...],
    traces: tuple[ImplementationTrace, ...],
    frame: RepoFrame,
) -> tuple[Capability, ...]:
    """Reconcile syntax-level trace evidence with capability implementation axes.

    Trace kinds remain distinct: entrypoint flows, internal calls, and import-only
    dependencies can strengthen structural coverage, but none establishes runtime
    execution. The existing edge count is never reduced when the bounded trace is
    only a selected subset of observed exact edges.
    """

    indexed = {item.path: item for item in frame.indexed_files}
    traces_by_capability: dict[str, list[ImplementationTrace]] = {}
    for trace in traces:
        for capability_id in trace.capability_ids:
            traces_by_capability.setdefault(capability_id, []).append(trace)

    coverage_rank = {
        ImplementationCoverage.NONE: 0,
        ImplementationCoverage.CANDIDATE_ONLY: 1,
        ImplementationCoverage.ENTRYPOINT_ONLY: 2,
        ImplementationCoverage.PARTIAL_TRACE: 3,
        ImplementationCoverage.MULTI_LAYER_TRACE: 4,
    }
    result: list[Capability] = []
    for capability in capabilities:
        linked_traces = traces_by_capability.get(capability.id, ())
        if not linked_traces:
            result.append(capability)
            continue
        hop_keys = {
            (
                hop.source_path,
                hop.source_symbol,
                hop.relation,
                hop.target_path,
                hop.target_symbol,
            )
            for trace in linked_traces
            for hop in trace.hops
        }
        trace_roles = {
            _surface_role(indexed[path])
            for trace in linked_traces
            for hop in trace.hops
            for path in (hop.source_path, hop.target_path)
            if path in indexed
        }
        has_cross_file_hop = any(
            hop.source_path != hop.target_path
            for trace in linked_traces
            for hop in trace.hops
        )
        trace_coverage = (
            ImplementationCoverage.MULTI_LAYER_TRACE
            if has_cross_file_hop and len(trace_roles) >= 2
            else ImplementationCoverage.PARTIAL_TRACE
        )
        current = capability.assessment
        effective_coverage = max(
            (current.implementation_coverage, trace_coverage),
            key=coverage_rank.__getitem__,
        )
        assessment_payload = current.model_dump(mode="python")
        assessment_payload.update(
            implementation_coverage=effective_coverage,
            exact_production_edge_count=max(
                current.exact_production_edge_count,
                len(hop_keys),
            ),
        )
        payload = capability.model_dump(mode="python")
        payload["assessment"] = CapabilityAssessment.model_validate(assessment_payload)
        result.append(Capability.model_validate(payload))
    return tuple(result)


def _capabilities_with_targeted_verification(
    capabilities: tuple[Capability, ...],
    surfaces: tuple[CapabilitySurface, ...],
    commands: tuple[WorkspaceCommand, ...],
) -> tuple[Capability, ...]:
    """Promote only checks that name an exact linked test file.

    A broad suite result can establish repository health, but it cannot prove
    which product capability the suite covered. Capability-level promotion is
    therefore limited to command arguments that resolve to an exact linked
    verification surface.
    """

    surfaces_by_id = {surface.id: surface for surface in surfaces}
    verified_by_path: dict[str, list[WorkspaceCommand]] = {}
    for command in commands:
        if command.verification.status not in {
            CommandVerificationStatus.PASSED,
            CommandVerificationStatus.FAILED,
        }:
            continue
        for path in _command_target_paths(command.command, command.working_directory):
            verified_by_path.setdefault(path, []).append(command)

    result: list[Capability] = []
    for capability in capabilities:
        test_paths = {
            surface.repository_path
            for surface_id in capability.surface_ids
            if (surface := surfaces_by_id.get(surface_id)) is not None
            and surface.role is SurfaceRole.VERIFICATION
            and surface.repository_path is not None
        }
        matched_commands = [
            command for path in sorted(test_paths) for command in verified_by_path.get(path, ())
        ]
        if not matched_commands:
            result.append(capability)
            continue
        verification_status = (
            CapabilityVerificationStatus.FAILED
            if any(
                command.verification.status is CommandVerificationStatus.FAILED
                for command in matched_commands
            )
            else CapabilityVerificationStatus.PASSED
        )
        assessment_payload = capability.assessment.model_dump(mode="python")
        assessment_payload["verification_status"] = verification_status
        payload = capability.model_dump(mode="python")
        payload["assessment"] = CapabilityAssessment.model_validate(assessment_payload)
        payload["evidence_ref_ids"] = tuple(
            dict.fromkeys(
                [
                    *capability.evidence_ref_ids,
                    *(
                        reference_id
                        for command in matched_commands
                        for reference_id in command.verification.evidence_ref_ids
                    ),
                ]
            )
        )
        result.append(Capability.model_validate(payload))
    return tuple(result)


def _command_target_paths(command: str, cwd: str) -> tuple[str, ...]:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return ()
    paths: set[str] = set()
    for raw_token in tokens:
        token = raw_token.split("::", 1)[0]
        if not token or token.startswith("-") or token.startswith("/"):
            continue
        if not re.search(
            r"(?:^|/)(?:test[^/]*|[^/]+\.(?:py|js|jsx|ts|tsx|go|rs))$",
            token,
            flags=re.IGNORECASE,
        ):
            continue
        joined = token if cwd == "." else posixpath.join(cwd, token)
        normalized = posixpath.normpath(joined.replace("\\", "/"))
        if normalized not in {"", ".", ".."} and not normalized.startswith("../"):
            paths.add(normalized.removeprefix("./"))
    return tuple(sorted(paths))


def _change_capability_ids_by_path(
    capabilities: tuple[Capability, ...],
    surfaces: tuple[CapabilitySurface, ...],
    implementation_traces: tuple[ImplementationTrace, ...],
) -> dict[str, set[str]]:
    """Bind changed paths only to direct syntax surfaces or typed traces.

    A component membership or an arbitrary adjacent edge says where a file sits,
    not which product capability it implements. Direct route/symbol matches and
    paths explicitly present in a capability-linked implementation trace are the
    bounded code-observed associations strong enough for the dirty-state lane.
    """

    known_capability_ids = {capability.id for capability in capabilities}
    surface_by_id = {surface.id: surface for surface in surfaces}
    capability_by_path: dict[str, set[str]] = {}
    direct_derivations = {
        SurfaceDerivation.EXACT_ROUTE,
        SurfaceDerivation.SYMBOL_MATCH,
    }
    for capability in capabilities:
        for surface_id in capability.surface_ids:
            surface = surface_by_id.get(surface_id)
            if (
                surface is None
                or surface.derivation not in direct_derivations
                or surface.repository_path is None
            ):
                continue
            capability_by_path.setdefault(surface.repository_path, set()).add(
                capability.id
            )

    for trace in implementation_traces:
        capability_ids = known_capability_ids.intersection(trace.capability_ids)
        if not capability_ids:
            continue
        for hop in trace.hops:
            for path in (hop.source_path, hop.target_path):
                capability_by_path.setdefault(path, set()).update(capability_ids)
    return capability_by_path


def _targeted_related_test_paths(
    frame: RepoFrame,
    *,
    target_paths: set[str],
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """Resolve bounded test links directly for selected changed production paths.

    This deliberately does not consume the globally capped architecture edge
    projection. It reuses already-indexed path, import, and test-reference facts
    and retains a link only when the production target resolves uniquely.
    """

    indexed_by_path = _unique_indexed_files_by_path(frame.indexed_files)
    eligible_targets = {
        path
        for path in target_paths
        if (indexed := indexed_by_path.get(path)) is not None and not indexed.is_test
    }
    if not eligible_targets:
        return {}, {}

    python_paths_by_module: dict[str, list[str]] = {}
    for path in sorted(indexed_by_path):
        module_name = _python_module_for_path(path)
        if module_name is not None:
            python_paths_by_module.setdefault(module_name, []).append(path)

    links: dict[str, set[str]] = {path: set() for path in eligible_targets}
    capability_sources: dict[str, set[str]] = {
        path: set() for path in eligible_targets
    }
    test_files = sorted(
        (
            (path, indexed)
            for path, indexed in indexed_by_path.items()
            if indexed.is_test
        ),
        key=lambda pair: pair[0],
    )
    for test_path, test_file in test_files:
        observed_targets: set[str] = set()
        capability_targets: set[str] = set()
        path_candidates = _test_target_candidates(test_path, indexed_by_path)
        if len(path_candidates) == 1:
            observed_targets.add(path_candidates[0])
            capability_targets.add(path_candidates[0])

        import_hints = sorted(
            test_file.import_hints,
            key=lambda item: (
                item.start_line,
                item.end_line,
                item.specifier,
                item.python_level,
                item.python_module or "",
            ),
        )[:MAX_TARGETED_TEST_IMPORTS_PER_FILE]
        for hint in import_hints:
            target_path = _resolved_indexed_import_target(
                test_path,
                test_file,
                hint,
                indexed_by_path=indexed_by_path,
                python_paths_by_module=python_paths_by_module,
            )
            if target_path is not None:
                observed_targets.add(target_path)

        references = sorted(
            test_file.test_references,
            key=lambda item: (
                item.test_symbol_start_line,
                item.reference_line,
                item.binding_line,
                item.target_specifier,
                item.target_name,
            ),
        )[:MAX_TARGETED_TEST_REFERENCES_PER_FILE]
        for reference in references:
            hint = IndexedImport(
                specifier=reference.target_specifier,
                start_line=reference.binding_line,
                end_line=reference.binding_line,
                python_level=(
                    len(reference.target_specifier)
                    - len(reference.target_specifier.lstrip("."))
                    if test_file.language == "python"
                    else 0
                ),
                python_module=(
                    reference.target_specifier.lstrip(".") or None
                    if test_file.language == "python"
                    else None
                ),
            )
            target_path = _resolved_indexed_import_target(
                test_path,
                test_file,
                hint,
                indexed_by_path=indexed_by_path,
                python_paths_by_module=python_paths_by_module,
            )
            if (
                target_path is not None
                and _test_reference_resolves_to_target(
                    test_path,
                    target_path,
                    test_file,
                    reference,
                    indexed_by_path,
                )
                and _test_reference_has_unique_target_symbol(
                    indexed_by_path[target_path],
                    reference.target_name,
                )
            ):
                observed_targets.add(target_path)
                capability_targets.add(target_path)

        for target_path in sorted(observed_targets.intersection(eligible_targets)):
            if len(links[target_path]) < MAX_RELATED_TEST_PATHS_PER_CHANGE:
                links[target_path].add(test_path)
            if target_path in capability_targets and (
                len(capability_sources[target_path])
                < MAX_RELATED_TEST_PATHS_PER_CHANGE
            ):
                capability_sources[target_path].add(test_path)
        if all(
            len(paths) >= MAX_RELATED_TEST_PATHS_PER_CHANGE
            for paths in links.values()
        ):
            break
    return (
        {
            path: tuple(sorted(test_paths))
            for path, test_paths in sorted(links.items())
            if test_paths
        },
        {
            path: tuple(sorted(test_paths))
            for path, test_paths in sorted(capability_sources.items())
            if test_paths
        },
    )


def _resolved_indexed_import_target(
    source_path: str,
    source_file: IndexedFile,
    hint: IndexedImport,
    *,
    indexed_by_path: dict[str, IndexedFile],
    python_paths_by_module: dict[str, list[str]],
) -> str | None:
    if source_file.language == "python":
        module_name = _resolve_python_import_module(source_path, hint)
        candidates = python_paths_by_module.get(module_name or "", [])
        return candidates[0] if len(candidates) == 1 else None
    if source_file.language in {
        "javascript",
        "javascript-react",
        "typescript",
        "typescript-react",
    }:
        return _resolve_javascript_import_path(
            source_path,
            hint.specifier,
            indexed_by_path,
        )
    return None


def _test_reference_has_unique_target_symbol(
    target_file: IndexedFile,
    target_name: str,
) -> bool:
    matches = [
        symbol
        for symbol in target_file.symbols
        if symbol.name == target_name
        and symbol.symbol_type not in {"module", "import", "route", "test"}
    ]
    return len(matches) == 1


def _unique_indexed_files_by_path(
    indexed_files: list[IndexedFile],
) -> dict[str, IndexedFile]:
    grouped: dict[str, list[IndexedFile]] = {}
    for indexed in indexed_files:
        grouped.setdefault(indexed.path, []).append(indexed)
    return {
        path: items[0]
        for path, items in grouped.items()
        if len(items) == 1
    }


def _normalized_repository_path(value: object) -> str | None:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/"):
        return None
    normalized = posixpath.normpath(raw).removeprefix("./")
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        return None
    return normalized


def _repository_state(
    frame: RepoFrame,
    inventory: dict[str, Any],
    capabilities: tuple[Capability, ...],
    surfaces: tuple[CapabilitySurface, ...],
    implementation_traces: tuple[ImplementationTrace, ...],
    components: tuple[ArchitectureComponent, ...],
    registry: _EvidenceRegistry,
    snapshot_fingerprint: str,
) -> RepositoryState:
    state_ref = registry.add(
        tier=EvidenceTier.CODE_OBSERVED,
        source_sha256=snapshot_fingerprint,
        rule="git_repository_state.v1",
        note="Git branch, commit, and worktree state observed during repository scan.",
    )
    capability_by_path = _change_capability_ids_by_path(
        capabilities,
        surfaces,
        implementation_traces,
    )
    indexed_by_path = {item.path: item for item in frame.indexed_files}
    ordered_changes = _select_repository_change_rows(
        frame.changed_files,
        indexed_by_path=indexed_by_path,
        capability_by_path=capability_by_path,
        limit=MAX_RENDERED_CHANGES,
    )
    selected_production_paths = {
        path
        for raw in ordered_changes
        if (path := _normalized_repository_path(raw.get("path")))
        and (indexed := indexed_by_path.get(path)) is not None
        and not indexed.is_test
    }
    related_tests, capability_test_sources = _targeted_related_test_paths(
        frame,
        target_paths=selected_production_paths,
    )
    direct_surface_capabilities = _change_capability_ids_by_path(
        capabilities,
        surfaces,
        (),
    )
    for target_path, test_paths in capability_test_sources.items():
        for test_path in test_paths:
            capability_by_path.setdefault(target_path, set()).update(
                direct_surface_capabilities.get(test_path, set())
            )
    changes: list[RepositoryChange] = []
    for raw in ordered_changes:
        path = str(raw.get("path") or "").replace("\\", "/").strip("/")
        if not path or ".." in path.split("/"):
            continue
        # Git porcelain's two columns are positional: `` M`` is worktree-only
        # while ``M `` is index-only. Preserve the leading column.
        status = str(raw.get("status") or "").rstrip()
        content_sha = _valid_sha256(raw.get("sha256"))
        change_ref = registry.add(
            tier=EvidenceTier.CODE_OBSERVED,
            source_sha256=snapshot_fingerprint,
            rule="git_status_entry.v1",
            note=(
                f"Git status {status or 'unknown'} for {path} at compile time; "
                "the evidence digest binds the repository status snapshot."
            ),
        )
        semantic_delta = (
            RepositorySemanticDelta.model_validate(raw["semantic_delta"])
            if isinstance(raw.get("semantic_delta"), dict)
            else None
        )
        semantic_ref = (
            registry.add(
                tier=EvidenceTier.CODE_OBSERVED,
                source_sha256=snapshot_fingerprint,
                rule="head_vs_worktree_syntax.v1",
                note=(
                    f"Bounded HEAD-vs-working-tree syntax delta for {path}; "
                    "it describes observed source differences only and does not "
                    "establish intent, completion, or remaining work."
                ),
            )
            if semantic_delta is not None
            else None
        )
        changes.append(
            RepositoryChange(
                path=path,
                kind=_change_kind(status),
                scope=_change_scope(status),
                previous_path=(
                    str(raw.get("old_path") or "").replace("\\", "/").strip("/") or None
                ),
                content_sha256=content_sha,
                role=_repository_change_role(path, indexed_by_path.get(path)),
                capability_ids=tuple(sorted(capability_by_path.get(path, set())))[:16],
                component_ids=tuple(
                    [component.id]
                    if (component := _component_for_path(path, components)) is not None
                    else []
                ),
                related_test_paths=related_tests.get(path, ()),
                semantic_delta=semantic_delta,
                evidence_ref_ids=tuple(
                    reference_id
                    for reference_id in (change_ref, semantic_ref)
                    if reference_id is not None
                ),
            )
        )
    changed_count = len(frame.changed_files)
    captured_at = _timestamp(frame.last_indexed_at)
    branch = frame.branch
    detached = branch == "HEAD"
    return RepositoryState(
        repository_name=_bounded_text(
            inventory.get("project_name")
            or (Path(frame.repo_path).name if frame.repo_path else "Unindexed workspace"),
            240,
        ),
        branch=None if detached else branch,
        head_commit=(
            frame.head_commit.casefold()
            if re.fullmatch(r"[0-9a-fA-F]{40,64}", str(frame.head_commit or ""))
            else None
        ),
        detached_head=detached,
        dirty=bool(frame.dirty or changed_count),
        captured_at=captured_at,
        snapshot_fingerprint=snapshot_fingerprint,
        status_sha256=_sha256_json(_canonical_changed_files(frame.changed_files)),
        changed_path_count=changed_count,
        changes_truncated=changed_count != len(changes),
        changes=tuple(changes),
        evidence_ref_ids=(state_ref,),
    )


def _select_repository_change_rows(
    rows: list[dict[str, Any]],
    *,
    indexed_by_path: dict[str, IndexedFile],
    capability_by_path: dict[str, set[str]],
    limit: int,
) -> list[dict[str, Any]]:
    """Retain a diverse, high-signal subset of a bounded dirty snapshot.

    Git status does not reveal intent. Selection therefore uses only observed
    role and semantic-delta richness, keeping one representative per role
    before filling remaining slots by evidence density.
    """

    if limit <= 0:
        return []

    def role(raw: dict[str, Any]) -> RepositoryChangeRole:
        path = str(raw.get("path") or "")
        return _repository_change_role(path, indexed_by_path.get(path))

    def priority(raw: dict[str, Any]) -> tuple[int, int, int, int, str]:
        delta = raw.get("semantic_delta")
        delta = delta if isinstance(delta, dict) else {}
        parser_coverage = str(delta.get("parser_coverage") or "not_observed")
        coverage_rank = {"parsed": 0, "line_only": 1}.get(parser_coverage, 2)
        semantic_item_count = sum(
            len(value)
            for key, value in delta.items()
            if key
            in {
                "symbols_added",
                "symbols_modified",
                "symbols_removed",
                "routes_added",
                "routes_removed",
                "imports_added",
                "imports_removed",
                "headings_added",
                "headings_removed",
            }
            and isinstance(value, list)
        )
        line_magnitude = sum(
            value
            for value in (delta.get("lines_added"), delta.get("lines_removed"))
            if isinstance(value, int) and not isinstance(value, bool)
        )
        path = str(raw.get("path") or "")
        return (
            coverage_rank,
            -line_magnitude,
            -semantic_item_count,
            0 if path in capability_by_path else 1,
            path.casefold(),
        )

    ordered = sorted(rows, key=priority)
    role_order = (
        RepositoryChangeRole.MIGRATION,
        RepositoryChangeRole.SCHEMA,
        RepositoryChangeRole.IMPLEMENTATION,
        RepositoryChangeRole.TEST,
        RepositoryChangeRole.CONFIGURATION,
        RepositoryChangeRole.OPERATIONS,
        RepositoryChangeRole.DOCUMENTATION,
        RepositoryChangeRole.OTHER,
    )
    selected: list[dict[str, Any]] = []
    selected_paths: set[str] = set()
    for change_role in role_order:
        candidate = next(
            (
                raw
                for raw in ordered
                if role(raw) is change_role
                and str(raw.get("path") or "") not in selected_paths
            ),
            None,
        )
        if candidate is None:
            continue
        selected.append(candidate)
        selected_paths.add(str(candidate.get("path") or ""))
        if len(selected) >= limit:
            return selected
    for raw in ordered:
        path = str(raw.get("path") or "")
        if path in selected_paths:
            continue
        selected.append(raw)
        selected_paths.add(path)
        if len(selected) >= limit:
            break
    return selected


def _repository_engineering_knowledge(
    statements: tuple[DocumentedEngineeringKnowledge, ...],
    registry: _EvidenceRegistry,
) -> tuple[RepositoryEngineeringKnowledgeFact, ...]:
    result: list[RepositoryEngineeringKnowledgeFact] = []
    seen: set[tuple[str, str]] = set()
    for statement in statements:
        key = (statement.kind, " ".join(statement.statement.casefold().split()))
        if key in seen:
            continue
        seen.add(key)
        evidence_id = registry.add(
            tier=EvidenceTier.DOCUMENTATION_STATED,
            source=statement.source,
            note=(
                "Exact repository-stated engineering knowledge; this is not "
                "implementation, execution, or promoted-memory proof."
            ),
        )
        result.append(
            RepositoryEngineeringKnowledgeFact(
                id=(
                    "engineering."
                    + _stable_hash(
                        f"{statement.kind}:{statement.source.path}:"
                        f"{statement.source.start_line}:{statement.statement}"
                    )[:16]
                ),
                kind=RepositoryEngineeringKnowledgeKind(statement.kind),
                title=statement.title,
                statement=statement.statement,
                evidence_ref_ids=(evidence_id,),
            )
        )
        if len(result) >= MAX_REPOSITORY_ENGINEERING_KNOWLEDGE:
            break
    return tuple(result)


def _durable_knowledge(
    foundation: CompiledProjectFoundation | None,
    registry: _EvidenceRegistry,
) -> tuple[DurableKnowledgeFact, ...]:
    if foundation is None:
        return ()
    result: list[DurableKnowledgeFact] = []
    seen_identity_keys: set[str] = set()
    for item in sorted(foundation.items, key=_durable_item_sort_key):
        if item.identity_key in seen_identity_keys:
            continue
        seen_identity_keys.add(item.identity_key)
        tier = _durable_evidence_tier(
            item.evidence_level,
            source_types=(reference.source_type for reference in item.provenance_refs),
        )
        references = tuple(dict.fromkeys(
            registry.add(
                tier=tier,
                source_sha256=reference.source_content_sha256,
                rule="durable_evidence_span.v1",
                note=(
                    f"source_document_id={reference.source_document_id}; "
                    f"evidence_span_id={reference.evidence_span_id}; "
                    f"evidence_text_sha256={reference.evidence_text_sha256}"
                ),
            )
            for reference in item.provenance_refs
        ))
        if not references:
            continue
        if tier is EvidenceTier.CORROBORATED and len(references) < 2:
            # A malformed upstream item may claim corroboration while carrying
            # only one distinct evidence source. Fail closed instead of either
            # crashing artifact validation or weakening the evidence tier.
            continue
        corroboration_count = (
            min(max(2, item.corroboration_count), len(references))
            if tier is EvidenceTier.CORROBORATED
            else 1
        )
        result.append(
            DurableKnowledgeFact(
                id=f"knowledge.{_stable_hash(item.identity_key)[:16]}",
                identity_key=item.identity_key,
                kind=_durable_fact_kind(
                    item.kind,
                    item.section.value,
                    title=item.title,
                    identity_key=item.identity_key,
                ),
                title=item.title,
                statement=item.statement,
                evidence_tier=tier,
                corroboration_count=corroboration_count,
                evidence_ref_ids=references,
            )
        )
        if len(result) >= MAX_DURABLE_KNOWLEDGE_FACTS:
            break
    return tuple(result)


def _durable_item_sort_key(item: Any) -> tuple[int, int, int, str, str]:
    section_priority = {
        "decisions": 0,
        "architecture": 1,
        "conventions": 2,
        "constraints": 3,
        "direction": 4,
        "workflows": 5,
        "capabilities": 6,
        "domain": 7,
        "repository": 8,
        "stack": 9,
        "commands": 10,
        "identity": 11,
    }
    kind_priority = {
        ProjectContextKind.DECISION: 0,
        ProjectContextKind.INVARIANT: 1,
        ProjectContextKind.LEARNING: 2,
        ProjectContextKind.RISK: 3,
        ProjectContextKind.BLOCKER: 3,
        ProjectContextKind.CONTEXT: 4,
    }
    evidence_priority = {
        ProjectEvidenceLevel.MECHANICALLY_VERIFIED: 0,
        ProjectEvidenceLevel.HUMAN_CONFIRMED: 1,
        ProjectEvidenceLevel.CORROBORATED: 2,
    }
    return (
        section_priority.get(item.section.value, 50),
        kind_priority.get(item.kind, 20),
        evidence_priority.get(item.evidence_level, 20),
        item.title.casefold(),
        item.identity_key,
    )


def _quality_report(
    *,
    frame: RepoFrame,
    product_documented: bool,
    documented: DocumentedProject,
    documented_system_flows: tuple[DocumentedSystemFlow, ...],
    concepts: tuple[Concept, ...],
    capabilities: tuple[Capability, ...],
    surfaces: tuple[CapabilitySurface, ...],
    components: tuple[ArchitectureComponent, ...],
    edges: tuple[StructuralEdge, ...],
    implementation_traces: tuple[ImplementationTrace, ...],
    verification_policy: VerificationPolicy,
    commands: tuple[WorkspaceCommand, ...],
    repository_state: RepositoryState,
    repository_engineering_knowledge: tuple[RepositoryEngineeringKnowledgeFact, ...],
    durable_knowledge: tuple[DurableKnowledgeFact, ...],
    durable_foundation: CompiledProjectFoundation | None,
    edge_observation: WorkspaceEdgeObservation,
    architecture_observation_count: int,
    architecture_truncated: bool,
) -> QualityReport:
    mapped_capabilities = tuple(
        item
        for item in capabilities
        if item.assessment.implementation_coverage
        not in {ImplementationCoverage.NONE, ImplementationCoverage.CANDIDATE_ONLY}
    )
    traced_capability_ids = {
        capability_id for trace in implementation_traces for capability_id in trace.capability_ids
    }
    production_components = tuple(
        item
        for item in components
        if item.kind
        not in {
            ArchitectureComponentKind.TEST_SUITE,
            ArchitectureComponentKind.DOCUMENTATION,
        }
    )
    core = {
        FoundationSection.PRODUCT: product_documented and not documented.truncated,
        FoundationSection.CAPABILITIES: (bool(mapped_capabilities) and not documented.truncated),
        FoundationSection.ARCHITECTURE: (bool(production_components)),
        FoundationSection.REPOSITORY: bool(repository_state.snapshot_fingerprint and components),
    }
    issues: list[QualityIssue] = []

    def issue(
        key: str,
        *,
        kind: QualityIssueKind,
        severity: QualitySeverity,
        section: FoundationSection,
        message: str,
        blocking: bool = False,
        entities: Iterable[str] = (),
    ) -> None:
        issues.append(
            QualityIssue(
                id=f"issue.{key}",
                kind=kind,
                severity=severity,
                section=section,
                message=message,
                entity_ids=tuple(entities)[:64],
                blocking=blocking,
            )
        )

    if not product_documented:
        issue(
            "product_missing",
            kind=QualityIssueKind.MISSING_EVIDENCE,
            severity=QualitySeverity.ERROR,
            section=FoundationSection.PRODUCT,
            message="No safe repository-stated product purpose was found.",
            blocking=True,
        )
    if not mapped_capabilities:
        issue(
            "workflow_mapping_missing",
            kind=QualityIssueKind.INCOMPLETE_MAPPING,
            severity=QualitySeverity.ERROR,
            section=FoundationSection.CAPABILITIES,
            message="No workflow or capability is linked to a current code surface.",
            blocking=True,
            entities=(item.id for item in capabilities),
        )
    elif len(mapped_capabilities) != len(capabilities):
        issue(
            "workflow_mapping_partial",
            kind=QualityIssueKind.INCOMPLETE_MAPPING,
            severity=QualitySeverity.WARNING,
            section=FoundationSection.CAPABILITIES,
            message=(
                "Some documented capabilities have only weak path associations or no "
                "attributable code surface."
            ),
            entities=(
                item.id
                for item in capabilities
                if item.assessment.implementation_coverage is ImplementationCoverage.NONE
            ),
        )
    if mapped_capabilities and not implementation_traces:
        issue(
            "implementation_trace_missing",
            kind=QualityIssueKind.INCOMPLETE_MAPPING,
            severity=QualitySeverity.WARNING,
            section=FoundationSection.ARCHITECTURE,
            message=(
                "Capabilities have code locations, but no exact production dependency "
                "path could be established; end-to-end implementation flow is unknown."
            ),
            entities=(item.id for item in mapped_capabilities),
        )
    if not documented_system_flows:
        issue(
            "documented_system_flow_missing",
            kind=QualityIssueKind.MISSING_EVIDENCE,
            severity=QualitySeverity.WARNING,
            section=FoundationSection.ARCHITECTURE,
            message=(
                "No explicit repository-stated system or data flow was found; code "
                "traces remain structural and may not explain product sequencing."
            ),
        )
    elif traced_capability_ids and len(traced_capability_ids) < len(mapped_capabilities):
        issue(
            "implementation_trace_partial",
            kind=QualityIssueKind.INCOMPLETE_MAPPING,
            severity=QualitySeverity.WARNING,
            section=FoundationSection.ARCHITECTURE,
            message=(
                "Exact syntax-level implementation traces cover only some mapped "
                "capabilities; missing runtime, network, or persistence hops remain unknown."
            ),
            entities=(
                item.id for item in mapped_capabilities if item.id not in traced_capability_ids
            ),
        )
    if not core[FoundationSection.ARCHITECTURE]:
        issue(
            "architecture_incomplete",
            kind=QualityIssueKind.INCOMPLETE_MAPPING,
            severity=QualitySeverity.ERROR,
            section=FoundationSection.ARCHITECTURE,
            message="The repository scan did not establish a usable component map.",
            blocking=True,
            entities=(item.id for item in components),
        )
    if not core[FoundationSection.REPOSITORY]:
        issue(
            "repository_incomplete",
            kind=QualityIssueKind.MISSING_EVIDENCE,
            severity=QualitySeverity.ERROR,
            section=FoundationSection.REPOSITORY,
            message="A hash-bound repository snapshot and responsibility map are required.",
            blocking=True,
        )
    unverified_commands = tuple(
        item
        for item in commands
        if item.verification.status is CommandVerificationStatus.UNVERIFIED
    )
    failed_commands = tuple(
        item for item in commands if item.verification.status is CommandVerificationStatus.FAILED
    )
    current_passes = tuple(
        item for item in commands if item.verification.status is CommandVerificationStatus.PASSED
    )
    if unverified_commands:
        issue(
            "commands_unverified",
            kind=QualityIssueKind.UNVERIFIED_COMMAND,
            severity=QualitySeverity.WARNING,
            section=FoundationSection.COMMANDS,
            message=(
                "Some repository-declared commands have no exact-snapshot execution "
                "result; their pass/fail state is unknown."
            ),
            entities=(item.id for item in unverified_commands),
        )
    if failed_commands:
        issue(
            "commands_failed",
            kind=QualityIssueKind.OTHER,
            severity=QualitySeverity.ERROR,
            section=FoundationSection.COMMANDS,
            message="One or more exact-snapshot repository checks failed.",
            entities=(item.id for item in failed_commands),
        )
    if repository_state.dirty:
        issue(
            "worktree_dirty",
            kind=QualityIssueKind.OTHER,
            severity=QualitySeverity.WARNING,
            section=FoundationSection.REPOSITORY,
            message=(
                "The snapshot contains uncommitted paths; dirty content must not be "
                "attributed to HEAD."
            ),
        )
        mapped_changes = sum(
            bool(change.capability_ids or change.component_ids)
            for change in repository_state.changes
        )
        if repository_state.changes and mapped_changes < len(repository_state.changes):
            issue(
                "change_mapping_partial",
                kind=QualityIssueKind.INCOMPLETE_MAPPING,
                severity=QualitySeverity.WARNING,
                section=FoundationSection.REPOSITORY,
                message=(
                    "Some changed paths could not be tied to a capability or architecture "
                    "component; intended behavior and unfinished work remain unknown."
                ),
            )
    if documented.truncated:
        issue(
            "documentation_truncated",
            kind=QualityIssueKind.TRUNCATED_SCAN,
            severity=QualitySeverity.ERROR,
            section=FoundationSection.PRODUCT,
            message=(
                "The bounded documentation read was truncated, so product and "
                "workflow coverage cannot be declared complete."
            ),
            blocking=True,
        )
    if edge_observation.truncated:
        issue(
            "edge_scan_truncated",
            kind=QualityIssueKind.TRUNCATED_SCAN,
            severity=QualitySeverity.WARNING,
            section=FoundationSection.ARCHITECTURE,
            message="The bounded exact-edge lane was truncated; the graph is partial.",
        )
    if architecture_truncated:
        issue(
            "component_scan_truncated",
            kind=QualityIssueKind.TRUNCATED_SCAN,
            severity=QualitySeverity.WARNING,
            section=FoundationSection.ARCHITECTURE,
            message=(
                f"The component lane retained {len(components)} of "
                f"{architecture_observation_count} observed repository roles; "
                "the architecture map is partial."
            ),
        )
    semantic_languages = {
        "javascript",
        "javascript-react",
        "python",
        "typescript",
        "typescript-react",
    }
    structural_only_languages = sorted(
        {
            str(item.language)
            for item in frame.indexed_files
            if item.language
            and item.language
            not in {
                *semantic_languages,
                "dockerfile",
                "json",
                "markdown",
                "shell",
                "toml",
                "yaml",
            }
        }
    )
    if structural_only_languages:
        issue(
            "semantic_adapter_gap",
            kind=QualityIssueKind.INCOMPLETE_MAPPING,
            severity=QualitySeverity.WARNING,
            section=FoundationSection.ARCHITECTURE,
            message=(
                "Structural fallback indexed "
                + ", ".join(structural_only_languages)
                + "; syntax-level symbols and edges are not yet available for those "
                "languages."
            ),
        )
    if not durable_knowledge:
        issue(
            "durable_knowledge_empty",
            kind=QualityIssueKind.MISSING_EVIDENCE,
            severity=QualitySeverity.WARNING,
            section=FoundationSection.DURABLE_KNOWLEDGE,
            message=(
                "No durable workspace-memory fact qualified for promotion. Exact "
                "source-scoped repository engineering notes, when present, remain a "
                "separate documentation-only lane."
            ),
        )
    if repository_engineering_knowledge:
        issue(
            "repository_engineering_source_scoped",
            kind=QualityIssueKind.MISSING_EVIDENCE,
            severity=QualitySeverity.WARNING,
            section=FoundationSection.ENGINEERING_KNOWLEDGE,
            message=(
                "Repository engineering notes are exact but source-scoped; their "
                "currentness and workspace-wide authority are unverified."
            ),
        )

    capability_score = 0.0
    if capabilities:
        capability_points = []
        for capability in capabilities:
            assessment = capability.assessment
            points = 0.0
            points += (
                0.25
                if assessment.declaration_status is CapabilityDeclarationStatus.DECLARED
                else 0.0
            )
            points += 0.35 if assessment.production_surface_count else 0.0
            points += 0.25 if capability.id in traced_capability_ids else 0.0
            points += 0.10 if assessment.verification_surface_count else 0.0
            points += (
                0.05
                if assessment.verification_status
                in {
                    CapabilityVerificationStatus.PASSED,
                    CapabilityVerificationStatus.RUNTIME_VERIFIED,
                }
                else 0.0
            )
            capability_points.append(points)
        capability_score = 20.0 * sum(capability_points) / len(capability_points)
    trace_score = (
        7.5 * len(traced_capability_ids) / len(mapped_capabilities) if mapped_capabilities else 0.0
    )
    documented_flow_score = 7.5 if documented_system_flows else 0.0
    component_by_id = {item.id: item for item in components}
    production_edges = tuple(
        edge
        for edge in edges
        if component_by_id.get(edge.source_component_id) is not None
        and component_by_id.get(edge.target_component_id) is not None
        and component_by_id[edge.source_component_id].kind
        is not ArchitectureComponentKind.TEST_SUITE
        and component_by_id[edge.target_component_id].kind
        is not ArchitectureComponentKind.TEST_SUITE
    )
    architecture_score = 7.5 if core[FoundationSection.ARCHITECTURE] else 0.0
    architecture_score += 4.0 if production_edges else 0.0
    architecture_score += (
        3.5 if not edge_observation.truncated and not architecture_truncated else 0.0
    )
    repository_score = 8.0 if core[FoundationSection.REPOSITORY] else 0.0
    if core[FoundationSection.REPOSITORY]:
        if not repository_state.dirty:
            repository_score += 7.0
        elif repository_state.changes:
            annotated = sum(
                bool(change.capability_ids or change.component_ids)
                for change in repository_state.changes
            )
            repository_score += 7.0 * annotated / len(repository_state.changes)
            if repository_state.changes_truncated:
                repository_score = min(repository_score, 12.0)
    verification_score = (
        15.0
        if current_passes and not failed_commands and not unverified_commands
        else 10.0
        if current_passes and not failed_commands
        else 0.0
        if commands
        else 5.0
    )
    score = round(
        (15.0 if core[FoundationSection.PRODUCT] else 0.0)
        + capability_score
        + trace_score
        + documented_flow_score
        + architecture_score
        + repository_score
        + verification_score
        + (5.0 if durable_knowledge else 3.0 if repository_engineering_knowledge else 0.0),
        2,
    )
    copy_ready = all(core.values())
    status = (
        QualityStatus.FAIL
        if not copy_ready
        else QualityStatus.WARNING
        if issues
        else QualityStatus.PASS
    )
    coverage = (
        _coverage(
            FoundationSection.PRODUCT,
            1,
            1,
            complete=core[FoundationSection.PRODUCT],
            note=None if product_documented else "Repository identity only; purpose unknown.",
        ),
        _coverage(
            FoundationSection.CONCEPTS,
            len(concepts),
            len(concepts),
            complete=bool(concepts),
        ),
        _coverage(
            FoundationSection.CAPABILITIES,
            len(capabilities),
            len(mapped_capabilities),
            complete=(
                core[FoundationSection.CAPABILITIES]
                and len(mapped_capabilities) == len(capabilities)
            ),
            note=(
                f"Exact implementation traces cover {len(traced_capability_ids)} of "
                f"{len(mapped_capabilities)} mapped capabilities."
                if mapped_capabilities
                else None
            ),
        ),
        _coverage(
            FoundationSection.ARCHITECTURE,
            (
                len(components)
                + len(edges)
                + max(0, architecture_observation_count - len(components))
                + max(0, edge_observation.observed_count - len(edge_observation.edges))
            ),
            len(components) + len(edges),
            complete=(
                core[FoundationSection.ARCHITECTURE]
                and not edge_observation.truncated
                and not architecture_truncated
            ),
            note=(
                "Observed architecture exceeded a bounded compiler lane; omitted "
                "counts are included in item_count."
                if architecture_truncated or edge_observation.truncated
                else None
            ),
        ),
        _coverage(
            FoundationSection.COMMANDS,
            len(commands),
            len(commands) - len(unverified_commands),
            complete=bool(commands) and not unverified_commands,
            note=(
                f"{len(unverified_commands)} command(s) have no exact-snapshot result."
                if unverified_commands
                else None
            ),
        ),
        _coverage(
            FoundationSection.REPOSITORY,
            1 + repository_state.changed_path_count,
            1
            + sum(
                bool(change.capability_ids or change.component_ids)
                for change in repository_state.changes
            ),
            complete=(
                core[FoundationSection.REPOSITORY]
                and not repository_state.changes_truncated
                and all(
                    change.capability_ids or change.component_ids
                    for change in repository_state.changes
                )
            ),
            note=(
                "Change intent and completion are not inferred from Git status."
                if repository_state.dirty
                else None
            ),
        ),
        _coverage(
            FoundationSection.ENGINEERING_KNOWLEDGE,
            len(repository_engineering_knowledge),
            len(repository_engineering_knowledge),
            complete=False,
            note=(
                "Repository statements are source-scoped; currentness and "
                "workspace-wide authority remain unverified."
                if repository_engineering_knowledge
                else None
            ),
        ),
        _coverage(
            FoundationSection.DURABLE_KNOWLEDGE,
            len(durable_knowledge),
            len(durable_knowledge),
            complete=bool(durable_knowledge),
        ),
        _coverage(
            FoundationSection.EVIDENCE,
            1,
            1,
            complete=not (documented.truncated or edge_observation.truncated),
        ),
    )
    snapshot = durable_foundation.snapshot if durable_foundation else None
    required_keys = {
        (item.key.command, item.key.working_directory)
        for item in verification_policy.required_commands
    }
    commands_by_key: dict[tuple[str, str], tuple[WorkspaceCommand, ...]] = {
        key: tuple(
            item
            for item in commands
            if (item.command, item.working_directory) == key
        )
        for key in required_keys
    }
    all_required_passed = bool(required_keys) and all(
        any(
            item.verification.status is CommandVerificationStatus.PASSED
            for item in commands_by_key[key]
        )
        for key in required_keys
    )
    relevant_stale_commands = tuple(
        item
        for key in required_keys
        for item in commands_by_key[key]
        if item.verification.status is CommandVerificationStatus.STALE
    )
    if failed_commands:
        repository_health = "failing"
    elif verification_policy.discovery_complete and all_required_passed:
        repository_health = "passing"
    elif relevant_stale_commands:
        repository_health = "stale"
    else:
        repository_health = "unknown"
    return QualityReport(
        status=status,
        publishable=copy_ready,
        copy_ready=copy_ready,
        score=score,
        issues=tuple(issues),
        section_coverage=coverage,
        excluded_historical_provisional_fact_count=(
            int(snapshot.provisional_fact_count) if snapshot else 0
        ),
        excluded_conflicting_superseded_fact_count=(
            int(snapshot.superseded_conflicting_fact_count) if snapshot else 0
        ),
        semantic_coverage_score=score,
        repository_health=repository_health,
        projection_self_contained=True,
    )


def _coverage(
    section: FoundationSection,
    item_count: int,
    evidenced_count: int,
    *,
    complete: bool,
    note: str | None = None,
) -> SectionCoverage:
    if item_count == 0:
        status = SectionCoverageStatus.MISSING
    elif complete:
        status = SectionCoverageStatus.COMPLETE
    else:
        status = SectionCoverageStatus.PARTIAL
    return SectionCoverage(
        section=section,
        status=status,
        item_count=item_count,
        evidenced_item_count=evidenced_count,
        note=note,
    )


def _observed_capability_seeds(
    frame: RepoFrame,
) -> tuple[DocumentedCapability, ...]:
    groups: dict[tuple[str, str], list[tuple[IndexedFile, str]]] = {}
    for item in frame.indexed_files:
        for route in item.route_hints:
            route_path = route.split(" ", 1)[1] if " " in route else route
            parts = [part for part in route_path.strip("/").split("/") if part]
            if not parts:
                continue
            root = parts[1] if parts[0].casefold() == "api" and len(parts) > 1 else parts[0]
            key = (root.casefold(), item.path)
            groups.setdefault(key, []).append((item, route))
    result: list[DocumentedCapability] = []
    for (root, _path), values in sorted(groups.items()):
        item = values[0][0]
        routes = sorted({route for _file, route in values})
        result.append(
            DocumentedCapability(
                name=f"{root.replace('-', ' ').title()} interface",
                summary=(
                    f"Code-observed interface routes under {routes[0]}; product meaning "
                    "is not established by documentation."
                ),
                steps=(),
                source=SourceLocation(
                    path=item.path,
                    sha256=item.sha256,
                    start_line=None,
                    end_line=None,
                    rule_id="route_capability_root.v1",
                ),
            )
        )
        if len(result) >= MAX_CAPABILITIES:
            break
    return tuple(result)


def _component_for_path(
    path: str,
    components: tuple[ArchitectureComponent, ...],
) -> ArchitectureComponent | None:
    matches = [
        component
        for component in components
        if any(
            path == prefix or path.startswith(prefix.rstrip("/") + "/")
            for prefix in component.repository_paths
        )
    ]
    if not matches:
        return None
    return max(
        matches,
        key=lambda item: max(len(path) for path in item.repository_paths),
    )


def _architecture_kind(
    observation: ArchitectureObservation,
) -> ArchitectureComponentKind:
    if observation.role == "interface":
        return ArchitectureComponentKind.FRONTEND
    if observation.role == "api":
        return ArchitectureComponentKind.API
    if observation.role == "data":
        return ArchitectureComponentKind.MODULE
    if observation.role == "verification":
        return ArchitectureComponentKind.TEST_SUITE
    if observation.role == "operations":
        return ArchitectureComponentKind.INFRASTRUCTURE
    if observation.role == "documentation":
        return ArchitectureComponentKind.DOCUMENTATION
    if "service" in observation.path.casefold():
        return ArchitectureComponentKind.SERVICE
    return ArchitectureComponentKind.BACKEND


def _stack_applies_to_component(
    stack: StackObservation,
    component: ArchitectureObservation,
) -> bool:
    manifest = Path(stack.source.path).name.casefold()
    is_interface = component.role == "interface"
    if manifest == "package.json":
        return is_interface or stack.source.path == "package.json"
    if manifest in {"pyproject.toml", "requirements.txt"}:
        return not is_interface
    return stack.category == "manifest" and component.role in {
        "implementation",
        "operations",
    }


def _surface_kind(item: IndexedFile) -> SurfaceKind:
    path = item.path.casefold().replace("\\", "/")
    if item.is_test:
        return SurfaceKind.FILE
    if item.route_hints or "/api/" in f"/{path}":
        return SurfaceKind.API
    if path.startswith(("frontend/", "web/", "ui/", "client/")):
        return SurfaceKind.WEB_UI
    if path.startswith("desktop/"):
        return SurfaceKind.DESKTOP_UI
    if "/cli/" in f"/{path}" or Path(path).name.startswith("cli."):
        return SurfaceKind.CLI
    if path.startswith(("scripts/", "deploy/", "infra/", "ops/")):
        return SurfaceKind.OPERATIONS
    if any(marker in path.split("/") for marker in ("models", "database", "db")):
        return SurfaceKind.DATABASE
    return SurfaceKind.LIBRARY


def _surface_role(item: IndexedFile) -> SurfaceRole:
    path = item.path.casefold().replace("\\", "/")
    parts = set(path.split("/"))
    if item.is_test:
        return SurfaceRole.VERIFICATION
    if item.route_hints or "/api/" in f"/{path}" or path.startswith("frontend/"):
        return SurfaceRole.ENTRYPOINT
    if parts & {"models", "schemas", "database", "db", "migrations", "alembic"}:
        return SurfaceRole.DATA
    if path.startswith(("scripts/", "deploy/", "infra/", "ops/")):
        return SurfaceRole.OPERATIONS
    if path.endswith((".md", ".rst")) or path.startswith("docs/"):
        return SurfaceRole.DOCUMENTATION
    return SurfaceRole.IMPLEMENTATION


def _structural_relation(value: str) -> StructuralRelation:
    return {
        "imports": StructuralRelation.DEPENDS_ON,
        "calls": StructuralRelation.CALLS,
        "routes_to": StructuralRelation.ROUTES_TO,
        "tests": StructuralRelation.TESTS,
        "owned_by": StructuralRelation.OWNS,
    }.get(value, StructuralRelation.OTHER)


def _command_kind(value: DeclaredCommand) -> CommandKind:
    return _command_kind_text(value.command, category=value.category)


def _command_kind_text(value: str, *, category: str = "") -> CommandKind:
    lowered = f"{category} {value}".casefold()
    if "doctor" in lowered or "diagnostic" in lowered:
        return CommandKind.DOCTOR
    if "setup" in lowered or "bootstrap" in lowered:
        return CommandKind.SETUP
    if "smoke" in lowered:
        return CommandKind.SMOKE_TEST
    if "test" in lowered:
        return CommandKind.TEST
    if "lint" in lowered or "check" in lowered:
        return CommandKind.LINT
    if "type" in lowered:
        return CommandKind.TYPECHECK
    if "build" in lowered:
        return CommandKind.BUILD
    if "dev" in lowered:
        return CommandKind.DEVELOP
    if "deploy" in lowered or "publish" in lowered:
        return CommandKind.DEPLOY
    if category == "run":
        return CommandKind.RUN
    return CommandKind.OTHER


def _observed_command_name(kind: CommandKind) -> str:
    return {
        CommandKind.TEST: "Observed test command",
        CommandKind.SMOKE_TEST: "Observed smoke-test command",
        CommandKind.LINT: "Observed lint command",
        CommandKind.TYPECHECK: "Observed type-check command",
        CommandKind.BUILD: "Observed build command",
        CommandKind.DOCTOR: "Observed diagnostic command",
    }.get(kind, "Observed repository command")


def _repository_change_role(
    path: str,
    indexed: IndexedFile | None,
) -> RepositoryChangeRole:
    normalized = path.casefold().replace("\\", "/")
    parts = set(normalized.split("/"))
    name = Path(normalized).name
    if indexed is not None and indexed.is_test or parts & {"test", "tests", "spec", "specs"}:
        return RepositoryChangeRole.TEST
    if parts & {"migration", "migrations", "alembic"} or "migration" in name:
        return RepositoryChangeRole.MIGRATION
    if parts & {"schema", "schemas", "model", "models", "database", "db"}:
        return RepositoryChangeRole.SCHEMA
    if parts & {"docs", "documentation"} or normalized.endswith((".md", ".rst")):
        return RepositoryChangeRole.DOCUMENTATION
    if parts & {"scripts", "deploy", "deployment", "infra", "ops"}:
        return RepositoryChangeRole.OPERATIONS
    if (indexed is not None and (indexed.is_config or indexed.is_manifest)) or name in {
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "package.json",
        "pyproject.toml",
        "cargo.toml",
        "go.mod",
    }:
        return RepositoryChangeRole.CONFIGURATION
    if indexed is not None and indexed.language not in {None, "markdown"}:
        return RepositoryChangeRole.IMPLEMENTATION
    suffix = Path(normalized).suffix
    if suffix in {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".swift"}:
        return RepositoryChangeRole.IMPLEMENTATION
    return RepositoryChangeRole.OTHER


def _change_kind(status: str) -> RepositoryChangeKind:
    normalized = status.replace(" ", "")
    if normalized == "??":
        return RepositoryChangeKind.UNTRACKED
    if "R" in normalized:
        return RepositoryChangeKind.RENAMED
    if "C" in normalized:
        return RepositoryChangeKind.COPIED
    if "U" in normalized or normalized in {"AA", "DD"}:
        return RepositoryChangeKind.CONFLICTED
    if "D" in normalized:
        return RepositoryChangeKind.DELETED
    if "A" in normalized:
        return RepositoryChangeKind.ADDED
    if "T" in normalized:
        return RepositoryChangeKind.TYPE_CHANGED
    if "M" in normalized:
        return RepositoryChangeKind.MODIFIED
    return RepositoryChangeKind.UNKNOWN


def _change_scope(status: str) -> RepositoryChangeScope:
    if status == "??":
        return RepositoryChangeScope.UNTRACKED
    padded = status.ljust(2)[:2]
    if "U" in padded or padded in {"AA", "DD"}:
        return RepositoryChangeScope.CONFLICT
    index_changed = padded[0] not in {" ", "?"}
    worktree_changed = padded[1] not in {" ", "?"}
    if index_changed and worktree_changed:
        return RepositoryChangeScope.BOTH
    if index_changed:
        return RepositoryChangeScope.INDEX
    if worktree_changed:
        return RepositoryChangeScope.WORKTREE
    return RepositoryChangeScope.UNKNOWN


def _durable_evidence_tier(
    value: ProjectEvidenceLevel,
    *,
    source_types: Iterable[str] = (),
) -> EvidenceTier:
    if value is ProjectEvidenceLevel.HUMAN_CONFIRMED:
        return EvidenceTier.HUMAN_CONFIRMED
    if value is ProjectEvidenceLevel.CORROBORATED:
        return EvidenceTier.CORROBORATED
    repository_markers = {"code", "file", "git", "repo", "repository"}
    normalized_sources = tuple(str(item or "").casefold() for item in source_types)
    if normalized_sources and all(
        any(marker in source_type for marker in repository_markers)
        for source_type in normalized_sources
    ):
        return EvidenceTier.CODE_OBSERVED
    return EvidenceTier.SYSTEM_VERIFIED


def _durable_fact_kind(
    kind: ProjectContextKind,
    section: str,
    *,
    title: str = "",
    identity_key: str = "",
) -> DurableFactKind:
    if kind is ProjectContextKind.DECISION:
        return DurableFactKind.DECISION
    if kind is ProjectContextKind.INVARIANT:
        return DurableFactKind.INVARIANT
    if kind in {ProjectContextKind.RISK, ProjectContextKind.BLOCKER}:
        return DurableFactKind.RISK
    if kind is ProjectContextKind.LEARNING:
        normalized_title = " ".join(title.casefold().split())
        normalized_identity = identity_key.casefold().strip()
        if (
            re.match(r"^known\b.{0,120}\bfailure\b", normalized_title)
            or normalized_title.startswith(("failure ", "failure:"))
            or normalized_identity.startswith(
                ("known_failure:", "failed_attempt:", "failed_approach:")
            )
        ):
            return DurableFactKind.KNOWN_FAILURE
        return DurableFactKind.LESSON
    if section == "conventions":
        return DurableFactKind.CONVENTION
    if section == "constraints":
        return DurableFactKind.CONSTRAINT
    if section == "direction":
        return DurableFactKind.DIRECTION
    return DurableFactKind.CONTEXT


def _is_noise_path(path: str) -> bool:
    parts = path.casefold().replace("\\", "/").split("/")
    return bool(
        {
            ".agent-runs",
            "fixtures",
            "fixture",
            "node_modules",
            "vendor",
            "generated",
        }
        & set(parts)
    )


def _word_roots(value: str) -> set[str]:
    roots: set[str] = set()
    camel_split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value or ""))
    for token in re.findall(r"[a-z0-9]+", camel_split.casefold()):
        if len(token) < 4:
            continue
        root = token
        for prefix in (
            "continu",
            "execut",
            "eviden",
            "integrat",
            "librar",
            "memor",
            "sourc",
        ):
            if token.startswith(prefix):
                root = prefix
                break
        else:
            for suffix in ("ations", "ation", "ments", "ment", "ing", "ies", "es", "s"):
                if token.endswith(suffix) and len(token) - len(suffix) >= 4:
                    root = token[: -len(suffix)]
                    break
        roots.add(root)
    return roots


def _capability_primary_terms(value: str) -> set[str]:
    roots = _word_roots(value)
    aliases: dict[str, set[str]] = {
        "integrat": {"connector"},
        "float": {"overlay", "desktop"},
    }
    for root in tuple(roots):
        roots.update(aliases.get(root, set()))
    return roots


def _normalized(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _bounded_text(value: Any, limit: int) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= limit:
        return normalized
    prefix = normalized[: max(1, limit - 1)].rstrip()
    if " " in prefix:
        prefix = prefix.rsplit(" ", 1)[0]
    return prefix.rstrip(".,;:") + "…"


def _valid_sha256(value: Any) -> str | None:
    normalized = str(value or "").strip().casefold()
    return normalized if re.fullmatch(r"[0-9a-f]{64}", normalized) else None


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _stable_hash(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _canonical_changed_files(
    values: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized = [
        {
            "path": str(item.get("path") or "").replace("\\", "/").strip("/"),
            "old_path": str(item.get("old_path") or "").replace("\\", "/").strip("/") or None,
            "status": str(item.get("status") or "").rstrip(),
            "sha256": _valid_sha256(item.get("sha256")),
        }
        for item in values
    ]
    return sorted(
        normalized,
        key=lambda item: (
            item["path"].casefold(),
            str(item["old_path"] or "").casefold(),
            item["status"],
            str(item["sha256"] or ""),
        ),
    )


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


__all__ = [
    "WORKSPACE_FOUNDATION_COMPILER_VERSION",
    "WorkspaceFoundationCompiler",
    "compile_workspace_foundation",
]
