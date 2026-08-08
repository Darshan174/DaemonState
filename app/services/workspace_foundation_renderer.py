from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from app.schemas.workspace_foundation import (
    ArchitectureComponent,
    ArchitectureComponentKind,
    Capability,
    CapabilitySurface,
    CapabilityVerificationStatus,
    CommandVerificationStatus,
    EvidenceReference,
    EvidenceTier,
    ImplementationTrace,
    ImplementationTraceKind,
    ProductClaim,
    QualitySeverity,
    ProductClaimKind,
    RepositoryChangeCompletionStatus,
    RepositoryChangeRemainingWorkStatus,
    RepositoryChangeRole,
    RepositorySemanticParserCoverage,
    StructuralEdge,
    StructuralRelation,
    SurfaceDerivation,
    SurfaceRole,
    WorkspaceFoundationArtifact,
)


MAX_RENDERED_CAPABILITIES = 6
MAX_RENDERED_SURFACES_PER_CAPABILITY = 2
MAX_RENDERED_WORKFLOWS = 4
MAX_RENDERED_STEPS_PER_FLOW = 8
MAX_RENDERED_TRACES = 4
MAX_RENDERED_COMPONENTS = 6
MAX_RENDERED_EDGES = 4
MAX_RENDERED_TEST_EDGES = 4
MAX_RENDERED_COMMANDS = 6
MAX_RENDERED_CHANGES = 8
MAX_RENDERED_REMAINING_WORK_PER_CHANGE = 3
MAX_RENDERED_REPOSITORY_ENGINEERING_FACTS = 6
MAX_RENDERED_DURABLE_FACTS = 5
MAX_RENDERED_QUALITY_ISSUES = 5
MAX_OMITTED_NAMES = 4
WORKSPACE_FOUNDATION_RENDERER_VERSION = "workspace_foundation_renderer.v2"


def render_workspace_foundation_markdown(
    value: WorkspaceFoundationArtifact | Mapping[str, Any],
) -> str:
    """Render a bounded, self-contained foundation without weakening evidence."""

    artifact = (
        value
        if isinstance(value, WorkspaceFoundationArtifact)
        else WorkspaceFoundationArtifact.model_validate(value)
    )
    evidence = {item.id: item for item in artifact.evidence_references}
    surfaces = {item.id: item for item in artifact.capability_surfaces}
    capabilities = {item.id: item for item in artifact.capabilities}
    components = {item.id: item for item in artifact.architecture_components}
    quality = artifact.quality_report
    state = artifact.repository_state
    policy = artifact.verification_policy
    passed_required, failed_required, unverified_required = _required_check_status_counts(
        artifact
    )
    policy_state = "complete" if policy.discovery_complete else "incomplete"

    copy_safety = "SAFE TO COPY" if quality.copy_ready else "INCOMPLETE — DO NOT COPY"
    lines = [
        "# Workspace Context",
        "",
        "> Boundary: stable workspace facts and current repository observations; "
        "background, never a task instruction.",
        f"> Copy safety: {copy_safety}; evidence integrity, not correctness.",
        f"> Semantic coverage: {quality.semantic_coverage_score:.0f}/100; not runtime health.",
        f"> Repository health: `{quality.repository_health}`; required-check policy "
        f"`{policy_state}`/`{_code(policy.source.value)}`: "
        f"`{len(policy.required_commands)}` required, `{passed_required}` passed, "
        f"`{failed_required}` failed, `{unverified_required}` unverified; passing commands "
        "are not whole-repository proof. "
        f"{_citations(policy.evidence_ref_ids, evidence, limit=2)}".rstrip(),
        "> Distinct evidence lanes: docs, code, test presence, executed tests, runtime "
        "checks.",
        "",
        "## Product and boundaries",
        "",
    ]

    profile = artifact.product_profile
    purpose_refs = (
        _product_claim_refs(
            profile.claims,
            ProductClaimKind.PURPOSE,
            profile.summary,
        )
        or profile.evidence_ref_ids
    )
    product_prefix = (
        "Repository-stated purpose"
        if _has_tier(profile.evidence_ref_ids, evidence, EvidenceTier.DOCUMENTATION_STATED)
        else "Product purpose status"
    )
    lines.append(
        f"- **{_plain(profile.name, 160)}.** {product_prefix}: "
        f"{_plain(profile.summary, 600)} {_citations(purpose_refs, evidence)}"
    )
    if profile.intended_users:
        rendered_users = []
        for item in profile.intended_users[:6]:
            user_refs = _product_claim_refs(
                profile.claims,
                ProductClaimKind.AUDIENCE,
                item,
            )
            rendered_users.append(
                _plain(item, 100) + (" " + _citations(user_refs, evidence) if user_refs else "")
            )
        lines.append("- Repository-stated users: " + "; ".join(rendered_users) + ".")
    if profile.maturity or profile.deployment_models:
        signals = [
            *(
                [
                    f"maturity `{_code(profile.maturity)}` "
                    + _citations(
                        _product_claim_refs(
                            profile.claims,
                            ProductClaimKind.MATURITY,
                            profile.maturity,
                        ),
                        evidence,
                    )
                ]
                if profile.maturity
                else []
            ),
            *(
                [
                    "deployment "
                    + ", ".join(
                        f"`{_code(item)}` "
                        + _citations(
                            _product_claim_refs(
                                profile.claims,
                                ProductClaimKind.DEPLOYMENT,
                                item,
                            ),
                            evidence,
                        )
                        for item in profile.deployment_models
                    )
                ]
                if profile.deployment_models
                else []
            ),
        ]
        lines.append("- Repository-stated operating boundary: " + "; ".join(signals) + ".")
    displayed_boundaries = _select_product_boundaries(profile.non_goals, limit=3)
    for boundary in displayed_boundaries:
        boundary_refs = _product_claim_refs(
            profile.claims,
            ProductClaimKind.BOUNDARY,
            boundary,
        )
        lines.append(
            f"- Boundary: {_plain(boundary, 280)} "
            f"{_citations(boundary_refs, evidence) if boundary_refs else ''}".rstrip()
        )
    _append_omission(
        lines,
        displayed=len(displayed_boundaries),
        total=len(profile.non_goals),
        label="product boundary record(s)",
        omitted_names=(
            boundary for boundary in profile.non_goals if boundary not in displayed_boundaries
        ),
    )

    if artifact.concepts:
        displayed_concepts = artifact.concepts[:4]
        lines.extend(["", "## Domain concepts", ""])
        for concept in displayed_concepts:
            lines.append(
                f"- **{_plain(concept.name, 120)}:** {_plain(concept.definition, 360)} "
                f"{_citations(concept.evidence_ref_ids, evidence)}"
            )
        _append_omission(
            lines,
            displayed=len(displayed_concepts),
            total=len(artifact.concepts),
            label="domain concept(s)",
            omitted_names=(item.name for item in artifact.concepts[len(displayed_concepts) :]),
        )

    _render_system_mental_model(lines, artifact, capabilities, evidence)

    lines.extend(["", "## Workflows and capability-to-code map", ""])
    lines.append(
        "Surface evidence: `exact_route` declaration; `symbol_match` static identifier; "
        "`exact_edge` structural relation; `path_heuristic` candidate only. None proves "
        "runtime behavior."
    )
    lines.append("")
    displayed_capabilities = artifact.capabilities[:MAX_RENDERED_CAPABILITIES]
    if not displayed_capabilities:
        lines.append("- No defensible capability root was found.")
    for capability in displayed_capabilities:
        _render_capability(lines, capability, surfaces, components, evidence)
    _append_omission(
        lines,
        displayed=len(displayed_capabilities),
        total=len(artifact.capabilities),
        label="capability record(s)",
        omitted_names=(item.name for item in artifact.capabilities[len(displayed_capabilities) :]),
    )

    selected_components, selected_edges, production_components, production_edges = (
        _select_production_architecture(artifact, components)
    )
    lines.extend(["", "## Architecture and system map", ""])
    stack_signals = tuple(
        dict.fromkeys(
            technology
            for component in production_components
            for technology in component.technologies
            if not _is_manifest_stack_label(technology)
        )
    )
    if stack_signals:
        lines.append(
            "- Repository-declared stack signals: "
            + ", ".join(f"`{_code(item)}`" for item in stack_signals[:10])
            + ". Manifest scope does not prove ownership by every component."
        )
    if not selected_components:
        lines.append("- No production component was established from current repository evidence.")
    for component in selected_components:
        _render_component(lines, component, evidence)
    if selected_edges:
        lines.append("- Exact production structure (syntax-level; not runtime order):")
        for edge in selected_edges:
            source = components[edge.source_component_id]
            target = components[edge.target_component_id]
            detail = f" — {_plain(edge.description, 180)}" if edge.description else ""
            lines.append(
                f"  - `{_code(source.name)}` **{edge.relation.value.replace('_', ' ')}** "
                f"`{_code(target.name)}`{detail} "
                f"{_citations(edge.evidence_ref_ids, evidence)}"
            )
    else:
        lines.append(
            "- Unknown: no exact cross-component production edge was established; "
            "do not infer calls or data flow from directory proximity."
        )
    displayed_component_ids = {item.id for item in selected_components}
    _append_omission(
        lines,
        displayed=len(selected_components),
        total=len(production_components),
        label="production component(s)",
        omitted_names=(
            item.name for item in production_components if item.id not in displayed_component_ids
        ),
    )
    selected_edge_ids = {item.id for item in selected_edges}
    _append_omission(
        lines,
        displayed=len(selected_edges),
        total=len(production_edges),
        label="production structural edge(s)",
        omitted_names=(
            _edge_name(item, components)
            for item in production_edges
            if item.id not in selected_edge_ids
        ),
    )
    supporting_components = [
        item
        for item in artifact.architecture_components
        if item.kind is ArchitectureComponentKind.DOCUMENTATION
    ]
    if supporting_components:
        names = ", ".join(
            f"`{_code(item.name)}`" for item in supporting_components[:MAX_OMITTED_NAMES]
        )
        remainder = len(supporting_components) - min(len(supporting_components), MAX_OMITTED_NAMES)
        suffix = f"; {remainder} more not expanded" if remainder else ""
        lines.append(
            f"- Non-production documentation component(s): {names}{suffix}. They provide "
            "context but do not establish production flow."
        )

    _render_development_and_verification(
        lines,
        artifact,
        components,
        evidence,
    )
    _render_repository_state(lines, artifact, capabilities, components, evidence)

    lines.extend(
        [
            "",
            "## Repository engineering notes (source-scoped)",
            "",
            "These are exact documentation statements scoped to their cited source. "
            "Currentness and workspace-wide authority are unverified; they are not "
            "implementation, execution, or promoted-memory proof.",
        ]
    )
    displayed_repository_facts = _select_repository_engineering_facts(
        artifact.repository_engineering_knowledge,
        limit=MAX_RENDERED_REPOSITORY_ENGINEERING_FACTS,
    )
    if not displayed_repository_facts:
        lines.append(
            "- Unknown: no bounded decision, invariant, convention, current-limit, "
            "known-failure, or lesson statement was found under an exact repository "
            "heading."
        )
    for fact in displayed_repository_facts:
        lines.append(
            f"- **{fact.kind.value.replace('_', ' ')} — "
            f"{_plain(fact.title, 150)}:** {_plain(fact.statement, 420)} "
            f"{_citations(fact.evidence_ref_ids, evidence)}"
        )
    _append_omission(
        lines,
        displayed=len(displayed_repository_facts),
        total=len(artifact.repository_engineering_knowledge),
        label="source-scoped engineering note(s)",
        omitted_names=(
            item.title
            for item in artifact.repository_engineering_knowledge
            if item.id not in {fact.id for fact in displayed_repository_facts}
        ),
    )

    lines.extend(
        [
            "",
            "## Promoted durable workspace knowledge",
            "",
            "Only current facts that passed the Project Foundation promotion boundary appear here.",
        ]
    )
    displayed_facts = artifact.durable_knowledge[:MAX_RENDERED_DURABLE_FACTS]
    if not displayed_facts:
        lines.append("- No durable fact met the promotion boundary; none was invented.")
    for fact in displayed_facts:
        lines.append(
            f"- **{_plain(fact.title, 160)}:** {_plain(fact.statement, 420)} "
            f"({fact.kind.value.replace('_', ' ')}; "
            f"{fact.evidence_tier.value.replace('_', ' ')}) "
            f"{_citations(fact.evidence_ref_ids, evidence)}"
        )
    lines.append(
        "- Promotion exclusions: "
        f"`{quality.excluded_historical_provisional_fact_count}` historical/provisional; "
        f"`{quality.excluded_conflicting_superseded_fact_count}` conflicting/superseded. "
        "Excluded records are not presented as current workspace facts."
    )
    _append_omission(
        lines,
        displayed=len(displayed_facts),
        total=len(artifact.durable_knowledge),
        label="durable fact(s)",
        omitted_names=(item.title for item in artifact.durable_knowledge[len(displayed_facts) :]),
    )

    material_issues = sorted(
        quality.issues,
        key=lambda item: (
            0 if item.blocking else 1,
            0 if item.severity is QualitySeverity.ERROR else 1,
            item.id,
        ),
    )
    if material_issues:
        displayed_issues = material_issues[:MAX_RENDERED_QUALITY_ISSUES]
        lines.extend(["", "## Known gaps", ""])
        for issue in displayed_issues:
            blocking = "blocking" if issue.blocking else issue.severity.value
            lines.append(f"- **{blocking}:** {_plain(issue.message, 360)}")
        _append_omission(
            lines,
            displayed=len(displayed_issues),
            total=len(material_issues),
            label="quality issue(s)",
            omitted_names=(item.id for item in material_issues[len(displayed_issues) :]),
        )

    lines.extend(
        [
            "",
            "## Snapshot identity",
            "",
            f"- Foundation schema: `{artifact.schema_version}`; compiler: "
            f"`{_code(artifact.compiler_version)}`; renderer: "
            f"`{WORKSPACE_FOUNDATION_RENDERER_VERSION}`.",
            f"- Stable foundation fingerprint: `{artifact.semantic_sha256}`.",
            f"- Repository snapshot fingerprint: `{state.snapshot_fingerprint}`.",
            "- Bounded projection: unknown or omitted areas remain unknown.",
        ]
    )
    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


def _render_system_mental_model(
    lines: list[str],
    artifact: WorkspaceFoundationArtifact,
    capabilities: Mapping[str, Capability],
    evidence: Mapping[str, EvidenceReference],
) -> None:
    lines.extend(
        [
            "",
            "## System mental model",
            "",
            "Documented flows, entrypoint-backed static call flows, internal call chains, "
            "and import-only dependencies are separate evidence lanes.",
            "",
            "### Documentation-stated system and data flows",
            "",
        ]
    )

    documented_flows = artifact.documented_system_flows[:MAX_RENDERED_WORKFLOWS]
    if not documented_flows:
        lines.append("- Unknown: no repository-stated ordered system or data flow was found.")
    for flow in documented_flows:
        ordered_steps = sorted(flow.steps, key=lambda item: item.position)
        steps = ordered_steps[:MAX_RENDERED_STEPS_PER_FLOW]
        descriptions = " → ".join(_plain(item.description, 220) for item in steps)
        step_reference_ids = tuple(
            reference_id for item in steps for reference_id in item.evidence_ref_ids
        )
        lines.append(
            f"- **{_plain(flow.name, 120)}** — repository-stated, not implementation "
            f"proof: {_plain(flow.summary, 260)} "
            f"{_citations(flow.evidence_ref_ids, evidence, limit=2)}"
        )
        lines.append(
            f"  - Stated sequence: {descriptions} "
            f"{_citations(step_reference_ids, evidence, limit=2)}"
        )
        if len(steps) < len(ordered_steps):
            lines.append(
                f"  - {len(ordered_steps) - len(steps)} additional documented step(s) "
                "are not shown; the displayed sequence is incomplete."
            )
    _append_omission(
        lines,
        displayed=len(documented_flows),
        total=len(artifact.documented_system_flows),
        label="documented system/data flow(s)",
        omitted_names=(
            item.name for item in artifact.documented_system_flows[len(documented_flows) :]
        ),
    )

    lines.extend(["", "### Documentation-stated capability workflows", ""])
    workflows = [item for item in artifact.capabilities if item.workflow]
    displayed_workflows = workflows[:MAX_RENDERED_WORKFLOWS]
    if not displayed_workflows:
        lines.append("- Unknown: no repository-stated ordered capability workflow was found.")
    for capability in displayed_workflows:
        steps = sorted(capability.workflow, key=lambda item: item.position)[
            :MAX_RENDERED_STEPS_PER_FLOW
        ]
        descriptions = " → ".join(_plain(item.description, 220) for item in steps)
        reference_ids = tuple(
            reference_id for item in steps for reference_id in item.evidence_ref_ids
        )
        lines.append(
            f"- **{_plain(capability.name, 120)}:** {descriptions} "
            f"{_citations(reference_ids, evidence, limit=2)}"
        )
        if len(steps) < len(capability.workflow):
            lines.append(
                f"  - {len(capability.workflow) - len(steps)} additional documented step(s) "
                "are not shown; the displayed sequence is incomplete."
            )
    _append_omission(
        lines,
        displayed=len(displayed_workflows),
        total=len(workflows),
        label="documented workflow(s)",
        omitted_names=(item.name for item in workflows[len(displayed_workflows) :]),
    )

    lines.extend(["", "### Code-observed production call flows", ""])
    capability_rank = {capability_id: rank for rank, capability_id in enumerate(capabilities)}
    traces = sorted(
        artifact.implementation_traces,
        key=lambda item: (
            {
                ImplementationTraceKind.PRODUCTION_CALL_FLOW: 0,
                ImplementationTraceKind.INTERNAL_CALL_CHAIN: 1,
                ImplementationTraceKind.STRUCTURAL_DEPENDENCY: 2,
            }[item.kind],
            min(
                (
                    capability_rank.get(capability_id, 10_000)
                    for capability_id in item.capability_ids
                ),
                default=10_000,
            ),
            -len(item.hops),
            item.name.casefold(),
            item.id,
        ),
    )
    call_flows = [
        item for item in traces if item.kind is ImplementationTraceKind.PRODUCTION_CALL_FLOW
    ]
    internal_chains = [
        item for item in traces if item.kind is ImplementationTraceKind.INTERNAL_CALL_CHAIN
    ]
    dependency_traces = [
        item for item in traces if item.kind is ImplementationTraceKind.STRUCTURAL_DEPENDENCY
    ]
    displayed_call_flows = call_flows[:MAX_RENDERED_TRACES]
    if not displayed_call_flows:
        lines.append(
            "- Unknown: no exact static route/handler/local-call chain was established. "
            "Runtime dispatch and production data flow remain unknown."
        )
    else:
        lines.append(
            "- Flow meaning: exact static client-route, route-owner, and local-symbol-call "
            "evidence. It does not prove runtime execution, branch selection, success, or "
            "end-to-end completeness."
        )
        displayed_gaps = tuple(
            dict.fromkeys(gap for trace in displayed_call_flows for gap in trace.gaps)
        )
        if displayed_gaps:
            lines.append(
                "- Unresolved across displayed traces: "
                + "; ".join(_plain(gap, 240) for gap in displayed_gaps[:2])
            )
    for trace in displayed_call_flows:
        _render_trace(lines, trace, capabilities, evidence)
    _append_omission(
        lines,
        displayed=len(displayed_call_flows),
        total=len(call_flows),
        label="production call flow(s)",
        omitted_names=(item.name for item in call_flows[len(displayed_call_flows) :]),
    )

    remaining_slots = max(0, MAX_RENDERED_TRACES - len(displayed_call_flows))
    displayed_internal = internal_chains[:remaining_slots]
    if internal_chains:
        lines.extend(["", "### Internal static call chains", ""])
        lines.append(
            "- Internal-chain meaning: exact local-symbol calls with no route or handler "
            "entrypoint established; not a production call flow or runtime proof."
        )
        for trace in displayed_internal:
            _render_trace(lines, trace, capabilities, evidence)
        _append_omission(
            lines,
            displayed=len(displayed_internal),
            total=len(internal_chains),
            label="internal call chain(s)",
            omitted_names=(item.name for item in internal_chains[len(displayed_internal) :]),
        )

    remaining_slots = max(0, remaining_slots - len(displayed_internal))
    displayed_dependencies = dependency_traces[:remaining_slots]
    lines.extend(["", "### Structural dependency traces", ""])
    lines.append(
        "- Dependency meaning: exact local imports only. These records describe code "
        "structure, not handler calls, runtime order, or data movement."
    )
    if not displayed_dependencies:
        lines.append(
            "- No import-only fallback trace is displayed; this does not establish that "
            "all production flow is known."
        )
    for trace in displayed_dependencies:
        _render_trace(lines, trace, capabilities, evidence)
    _append_omission(
        lines,
        displayed=len(displayed_dependencies),
        total=len(dependency_traces),
        label="structural dependency trace(s)",
        omitted_names=(item.name for item in dependency_traces[len(displayed_dependencies) :]),
    )


def _render_trace(
    lines: list[str],
    trace: ImplementationTrace,
    capabilities: Mapping[str, Capability],
    evidence: Mapping[str, EvidenceReference],
) -> None:
    capability_names = [
        capabilities[capability_id].name
        for capability_id in trace.capability_ids
        if capability_id in capabilities
    ]
    capability_label = ", ".join(_plain(item, 100) for item in capability_names) or "unknown"
    chain = [_trace_endpoint(trace.hops[0].source_path, trace.hops[0].source_symbol)]
    for hop in trace.hops:
        chain.append(
            f"—{hop.relation.value.replace('_', ' ')}→ "
            f"{_trace_endpoint(hop.target_path, hop.target_symbol)}"
        )
    reference_ids = tuple(
        reference_id for hop in trace.hops for reference_id in hop.evidence_ref_ids
    )
    lines.append(
        f"- **{_plain(trace.name, 120)}** (`{trace.kind.value}`; "
        f"`{trace.coverage.value}`; capability: "
        f"{capability_label}): {' '.join(chain)} "
        f"{_citations(reference_ids, evidence, limit=2)}"
    )


def _trace_endpoint(path: str, symbol: str | None) -> str:
    suffix = f"#{_code(symbol)}" if symbol else ""
    return f"`{_code(path)}{suffix}`"


def _render_capability(
    lines: list[str],
    capability: Capability,
    surfaces: Mapping[str, CapabilitySurface],
    components: Mapping[str, ArchitectureComponent],
    evidence: Mapping[str, EvidenceReference],
) -> None:
    source_label = (
        "repository-stated"
        if _has_tier(
            capability.evidence_ref_ids,
            evidence,
            EvidenceTier.DOCUMENTATION_STATED,
        )
        else "code-derived root"
    )
    assessment = capability.assessment
    lines.append(
        f"- **{_plain(capability.name, 140)}** — `{capability.state.value}`; "
        f"{source_label}: {_plain(capability.summary, 360)} "
        f"{_citations(capability.evidence_ref_ids, evidence, limit=2)}"
    )
    lines.append(
        "  - Assessment axes: "
        f"declaration=`{assessment.declaration_status.value}`; "
        f"implementation=`{assessment.implementation_coverage.value}` "
        f"({assessment.production_surface_count} production surface(s), "
        f"{assessment.candidate_surface_count} heuristic candidate(s), "
        f"{assessment.exact_production_edge_count} exact production edge(s)); "
        f"verification={_verification_assessment(assessment.verification_status.value, assessment.verification_surface_count)}. "
        + (
            _citations(
                (
                    reference_id
                    for reference_id in capability.evidence_ref_ids
                    if evidence.get(reference_id) is not None
                    and evidence[reference_id].tier
                    in {EvidenceTier.TEST_VERIFIED, EvidenceTier.RUNTIME_VERIFIED}
                ),
                evidence,
            )
            if assessment.verification_status
            in {
                CapabilityVerificationStatus.PASSED,
                CapabilityVerificationStatus.FAILED,
                CapabilityVerificationStatus.RUNTIME_VERIFIED,
            }
            else ""
        )
    )
    linked = [
        surfaces[surface_id] for surface_id in capability.surface_ids if surface_id in surfaces
    ]
    production = sorted(
        (
            item
            for item in linked
            if item.role is not SurfaceRole.VERIFICATION
            and item.derivation is not SurfaceDerivation.PATH_HEURISTIC
        ),
        key=_surface_sort_key,
    )
    candidates = sorted(
        (
            item
            for item in linked
            if item.role is not SurfaceRole.VERIFICATION
            and item.derivation is SurfaceDerivation.PATH_HEURISTIC
        ),
        key=_surface_sort_key,
    )
    verification = sorted(
        (item for item in linked if item.role is SurfaceRole.VERIFICATION),
        key=_surface_sort_key,
    )
    displayed_production = production[:MAX_RENDERED_SURFACES_PER_CAPABILITY]
    if displayed_production:
        rendered = [
            f"{item.role.value}/{item.kind.value} "
            f"`{_code(item.repository_path or item.locator)}` [{item.derivation.value}]"
            for item in displayed_production
        ]
        lines.append("  - Current code surfaces (production): " + "; ".join(rendered) + ".")
    else:
        lines.append("  - Current code surfaces (production): none established.")
    if len(displayed_production) < len(production):
        omitted = ", ".join(
            f"`{_code(item.repository_path or item.locator)}`"
            for item in production[len(displayed_production) :][:2]
        )
        lines.append(
            f"  - {len(production) - len(displayed_production)} additional production "
            f"surface(s) not shown: {omitted}. Do not infer complete implementation coverage."
        )
    if candidates:
        rendered_candidates = "; ".join(
            f"`{_code(item.repository_path or item.locator)}`"
            for item in candidates[:MAX_RENDERED_SURFACES_PER_CAPABILITY]
        )
        lines.append(
            "  - Heuristic code candidates (name/path association only; not "
            f"implementation evidence): {rendered_candidates}."
        )
        if len(candidates) > MAX_RENDERED_SURFACES_PER_CAPABILITY:
            lines.append(
                f"  - {len(candidates) - MAX_RENDERED_SURFACES_PER_CAPABILITY} "
                "additional heuristic candidate(s) are not shown."
            )
    displayed_verification = verification[:MAX_RENDERED_SURFACES_PER_CAPABILITY]
    if displayed_verification:
        rendered_tests = "; ".join(
            f"`{_code(item.repository_path or item.locator)}` [{item.derivation.value}]"
            for item in displayed_verification
        )
        link_meaning = (
            "exact targeted execution failed for at least one linked test"
            if assessment.verification_status is CapabilityVerificationStatus.FAILED
            else "exact targeted execution passed for the linked test named by the command"
            if assessment.verification_status is CapabilityVerificationStatus.PASSED
            else "presence/link only; not passing evidence"
        )
        lines.append(f"  - Linked tests ({link_meaning}): {rendered_tests}.")
    else:
        lines.append("  - Linked tests: none established; test execution status is unknown.")
    if len(displayed_verification) < len(verification):
        lines.append(
            f"  - {len(verification) - len(displayed_verification)} additional linked "
            "test surface(s) are not shown; no pass result is implied."
        )
    component_names = [
        components[component_id].name
        for component_id in capability.component_ids
        if component_id in components
        and components[component_id].kind is not ArchitectureComponentKind.TEST_SUITE
    ][:4]
    if component_names:
        lines.append(
            "  - Production/supporting components: "
            + ", ".join(f"`{_code(name)}`" for name in component_names)
            + "."
        )


def _select_production_architecture(
    artifact: WorkspaceFoundationArtifact,
    components: Mapping[str, ArchitectureComponent],
) -> tuple[
    list[ArchitectureComponent],
    list[StructuralEdge],
    list[ArchitectureComponent],
    list[StructuralEdge],
]:
    production_components = sorted(
        (
            item
            for item in artifact.architecture_components
            if item.kind
            not in {
                ArchitectureComponentKind.TEST_SUITE,
                ArchitectureComponentKind.DOCUMENTATION,
            }
        ),
        key=_component_sort_key,
    )
    production_ids = {item.id for item in production_components}
    production_edges = sorted(
        (
            edge
            for edge in artifact.structural_edges
            if edge.relation is not StructuralRelation.TESTS
            and edge.source_component_id in production_ids
            and edge.target_component_id in production_ids
        ),
        key=lambda item: _edge_sort_key(item, components),
    )
    selected_edges: list[StructuralEdge] = []
    endpoint_ids: set[str] = set()
    selected_pairs: set[frozenset[str]] = set()
    remaining_edges = list(production_edges)
    while remaining_edges and len(selected_edges) < MAX_RENDERED_EDGES:
        eligible = [
            edge
            for edge in remaining_edges
            if len(
                endpoint_ids
                | {edge.source_component_id, edge.target_component_id}
            )
            <= MAX_RENDERED_COMPONENTS
            and frozenset({edge.source_component_id, edge.target_component_id})
            not in selected_pairs
        ]
        if not eligible:
            break
        edge = min(
            eligible,
            key=lambda item: _architecture_edge_selection_key(
                item,
                selected_ids=endpoint_ids,
                components=components,
            ),
        )
        remaining_edges.remove(edge)
        selected_edges.append(edge)
        endpoint_ids.update((edge.source_component_id, edge.target_component_id))
        selected_pairs.add(
            frozenset({edge.source_component_id, edge.target_component_id})
        )
    selected_components = [item for item in production_components if item.id in endpoint_ids]
    selected_components.extend(
        _diverse_architecture_fill(
            production_components,
            selected=selected_components,
            limit=MAX_RENDERED_COMPONENTS - len(selected_components),
        )
    )
    selected_components.sort(key=_component_sort_key)
    return selected_components, selected_edges, production_components, production_edges


def _architecture_edge_selection_key(
    edge: StructuralEdge,
    *,
    selected_ids: set[str],
    components: Mapping[str, ArchitectureComponent],
) -> tuple[int, int, int, int, tuple[int, int, int, str, str, str]]:
    endpoints = tuple(
        component
        for component_id in (edge.source_component_id, edge.target_component_id)
        if (component := components.get(component_id)) is not None
    )
    selected = tuple(
        component
        for component_id in selected_ids
        if (component := components.get(component_id)) is not None
    )
    new_endpoints = tuple(item for item in endpoints if item.id not in selected_ids)
    generic_penalty = sum(_is_generic_architecture_component(item) for item in new_endpoints)
    overlap_penalty = sum(
        any(_architecture_component_paths_overlap(item, prior) for prior in selected)
        for item in new_endpoints
    )
    return (
        0 if edge.capability_ids else 1,
        generic_penalty,
        overlap_penalty,
        len(new_endpoints),
        _edge_sort_key(edge, components),
    )


def _is_generic_architecture_component(component: ArchitectureComponent) -> bool:
    name = component.name.casefold().strip("/")
    paths = tuple(_normalized_component_path(path) for path in component.repository_paths)
    return name in {"app", "backend", "client", "frontend", "server", "src", "web"} or (
        len(paths) == 1 and "/" not in paths[0] and paths[0] in {"app", "src"}
    )


def _diverse_architecture_fill(
    components: Iterable[ArchitectureComponent],
    *,
    selected: Iterable[ArchitectureComponent],
    limit: int,
) -> list[ArchitectureComponent]:
    """Fill renderer slots without letting broad or repeated paths crowd out layers."""

    chosen = list(selected)
    chosen_ids = {item.id for item in chosen}
    remaining = sorted(
        (item for item in components if item.id not in chosen_ids),
        key=_component_sort_key,
    )
    additions: list[ArchitectureComponent] = []
    while remaining and len(additions) < max(0, limit):
        candidate = min(
            remaining,
            key=lambda item: _architecture_fill_key(item, chosen),
        )
        remaining.remove(candidate)
        chosen.append(candidate)
        additions.append(candidate)
    return additions


def _architecture_fill_key(
    candidate: ArchitectureComponent,
    selected: Iterable[ArchitectureComponent],
) -> tuple[int, int, int, int, int, tuple[int, str, str]]:
    selected_items = tuple(selected)
    selected_kinds = [item.kind for item in selected_items]
    selected_layers = [_architecture_component_layer(item) for item in selected_items]
    candidate_paths = tuple(
        path
        for path in (_normalized_component_path(item) for item in candidate.repository_paths)
        if path
    )
    overlaps = any(
        _architecture_component_paths_overlap(candidate, item)
        for item in selected_items
    )
    # A component without a concrete path cannot establish path diversity. Keep it
    # ahead of a known ancestor/descendant only when its kind/layer adds information.
    path_penalty = 0 if candidate_paths and not overlaps else 1 if not candidate_paths else 2
    layer = _architecture_component_layer(candidate)
    new_layer = layer not in selected_layers
    new_kind = candidate.kind not in selected_kinds
    novelty_penalty = 0 if new_layer else 1 if new_kind else 2
    return (
        path_penalty,
        novelty_penalty,
        selected_layers.count(layer),
        selected_kinds.count(candidate.kind),
        -max((path.count("/") for path in candidate_paths), default=-1),
        _component_sort_key(candidate),
    )


def _architecture_component_paths_overlap(
    left: ArchitectureComponent,
    right: ArchitectureComponent,
) -> bool:
    left_paths = {
        path
        for path in (_normalized_component_path(item) for item in left.repository_paths)
        if path
    }
    right_paths = {
        path
        for path in (_normalized_component_path(item) for item in right.repository_paths)
        if path
    }
    return any(
        left_path == right_path
        or left_path.startswith(f"{right_path}/")
        or right_path.startswith(f"{left_path}/")
        for left_path in left_paths
        for right_path in right_paths
    )


def _normalized_component_path(path: str) -> str:
    return re.sub(r"/+", "/", path.replace("\\", "/").strip("/")).casefold()


def _architecture_component_layer(component: ArchitectureComponent) -> str:
    kind = component.kind
    if kind is ArchitectureComponentKind.APPLICATION:
        return "application"
    if kind is ArchitectureComponentKind.FRONTEND:
        return "frontend"
    if kind is ArchitectureComponentKind.API:
        return "api"
    if kind is ArchitectureComponentKind.CLI:
        return "entrypoint"
    if kind in {
        ArchitectureComponentKind.SERVICE,
        ArchitectureComponentKind.BACKEND,
        ArchitectureComponentKind.WORKER,
    }:
        return "backend"
    if kind in {
        ArchitectureComponentKind.MODULE,
        ArchitectureComponentKind.PACKAGE,
    }:
        return "module"
    if kind in {
        ArchitectureComponentKind.DATASTORE,
        ArchitectureComponentKind.CACHE,
        ArchitectureComponentKind.QUEUE,
    }:
        return "data"
    if kind in {
        ArchitectureComponentKind.INFRASTRUCTURE,
        ArchitectureComponentKind.DEPLOYMENT,
    }:
        return "operations"
    return kind.value


def _render_component(
    lines: list[str],
    component: ArchitectureComponent,
    evidence: Mapping[str, EvidenceReference],
) -> None:
    paths = ", ".join(f"`{_code(path)}`" for path in component.repository_paths[:3])
    lines.append(
        f"- **{_plain(component.kind.value.replace('_', ' '), 60)} — "
        f"{_plain(component.name, 140)}:** {_plain(component.responsibility, 260)} "
        f"Paths: {paths or '`unknown`'}. "
        f"{_citations(component.evidence_ref_ids, evidence)}"
    )


def _render_development_and_verification(
    lines: list[str],
    artifact: WorkspaceFoundationArtifact,
    components: Mapping[str, ArchitectureComponent],
    evidence: Mapping[str, EvidenceReference],
) -> None:
    lines.extend(["", "## Development and verification", ""])
    policy = artifact.verification_policy
    lines.extend(["### Commands and observed results", ""])
    if policy.incomplete_reasons:
        reasons = ", ".join(
            f"`{_code(reason)}`" for reason in policy.incomplete_reasons
        )
        lines.append(f"- Incomplete reason(s): {reasons}.")
    displayed_commands = _select_rendered_commands(
        artifact.commands,
        limit=MAX_RENDERED_COMMANDS,
    )
    if not displayed_commands:
        lines.append("- No repository-declared workflow command was found.")
    for command in displayed_commands:
        status = command.verification.status.value.replace("_", " ")
        reference_ids = tuple(
            dict.fromkeys(
                [
                    *command.evidence_ref_ids,
                    *command.verification.evidence_ref_ids,
                ]
            )
        )
        result_detail = (
            f" cwd=`{_code(command.working_directory)}`; "
            f"observed=`{command.verification.verified_at.isoformat()}`; "
            f"exit_code=`{command.verification.exit_code}`; "
            f"output_sha256=`{command.verification.output_sha256}`."
            if command.verification.verified_at is not None
            else " No exact-snapshot result is available."
        )
        lines.append(
            f"- `{_code(command.command)}` — {_plain(command.purpose, 220)} "
            f"(**{status}**, {command.origin.value}).{result_detail} "
            f"{_citations(reference_ids, evidence, limit=2)}"
        )
    _append_omission(
        lines,
        displayed=len(displayed_commands),
        total=len(artifact.commands),
        label="command(s)",
        omitted_names=(
            item.command
            for item in artifact.commands
            if item.id not in {command.id for command in displayed_commands}
        ),
    )

    lines.extend(["", "### Exact test links", ""])
    test_edges = sorted(
        (
            edge
            for edge in artifact.structural_edges
            if edge.relation is StructuralRelation.TESTS
            or (
                components.get(edge.source_component_id) is not None
                and components[edge.source_component_id].kind
                is ArchitectureComponentKind.TEST_SUITE
            )
            or (
                components.get(edge.target_component_id) is not None
                and components[edge.target_component_id].kind
                is ArchitectureComponentKind.TEST_SUITE
            )
        ),
        key=lambda item: _edge_sort_key(item, components),
    )
    displayed_test_edges = test_edges[:MAX_RENDERED_TEST_EDGES]
    if not displayed_test_edges:
        lines.append(
            "- No exact cross-component test edge was established. Linked test-file "
            "surfaces, when present, are listed per capability."
        )
    else:
        endpoint_ids = {
            component_id
            for edge in displayed_test_edges
            for component_id in (edge.source_component_id, edge.target_component_id)
            if component_id in components
        }
        endpoint_names = ", ".join(
            f"`{_code(components[component_id].name)}`"
            for component_id in sorted(
                endpoint_ids,
                key=lambda item: _component_sort_key(components[item]),
            )
        )
        lines.append(f"- Displayed test-link endpoints: {endpoint_names}.")
        lines.append(
            "- Meaning: an exact structural association involving a test component "
            "exists; this does not mean the test ran or passed."
        )
        for edge in displayed_test_edges:
            source = components.get(edge.source_component_id)
            target = components.get(edge.target_component_id)
            if source is None or target is None:
                continue
            lines.append(
                f"  - `{_code(source.name)}` "
                f"**{edge.relation.value.replace('_', ' ')}** "
                f"`{_code(target.name)}` "
                f"{_citations(edge.evidence_ref_ids, evidence)}"
            )
    _append_omission(
        lines,
        displayed=len(displayed_test_edges),
        total=len(test_edges),
        label="exact test edge(s)",
        omitted_names=(
            _edge_name(item, components) for item in test_edges[len(displayed_test_edges) :]
        ),
    )


def _render_repository_state(
    lines: list[str],
    artifact: WorkspaceFoundationArtifact,
    capabilities: Mapping[str, Capability],
    components: Mapping[str, ArchitectureComponent],
    evidence: Mapping[str, EvidenceReference],
) -> None:
    state = artifact.repository_state
    lines.extend(["", "## Current repository state", ""])
    branch = "detached HEAD" if state.detached_head else (state.branch or "unknown")
    lines.extend(
        [
            f"- Repository: `{_code(state.repository_name)}`; branch: `{_code(branch)}`; "
            f"HEAD: `{_code(state.head_commit or 'unknown')}`.",
            f"- Worktree dirty: `{str(state.dirty).lower()}`; changed paths: "
            f"`{state.changed_path_count}`. Dirty observations may differ from HEAD.",
        ]
    )
    if state.dirty:
        lines.append(
            "- Git status establishes changed paths. Bounded semantic deltas below compare "
            "HEAD with current file syntax where available; capability/component labels are "
            "structural associations only."
        )
        lines.append(
            "- Change intent, authorship, behavioral effect, completion, and remaining work "
            "are unknown unless separately evidenced through the explicit source-backed "
            "fields below. Git status and syntax never populate those fields."
        )
    displayed_changes = _select_repository_changes(
        state.changes,
        limit=MAX_RENDERED_CHANGES,
    )
    if displayed_changes:
        grouped: dict[str, list[Any]] = {}
        for change in displayed_changes:
            label = _change_group_label(change, capabilities, components)
            grouped.setdefault(label, []).append(change)
        for label, changes in grouped.items():
            lines.extend(["", f"### {label}", ""])
            for change in changes:
                previous = (
                    f" (from `{_code(change.previous_path)}`)" if change.previous_path else ""
                )
                component_names = [
                    components[component_id].name
                    for component_id in change.component_ids
                    if component_id in components
                ]
                component_detail = (
                    "; component(s): "
                    + ", ".join(f"`{_code(item)}`" for item in component_names[:3])
                    if component_names
                    else ""
                )
                lines.append(
                    f"- **{change.role.value} signal** — `{change.kind.value}` / "
                    f"`{change.scope.value}`: `{_code(change.path)}`{previous}"
                    f"{component_detail}. "
                    f"{_citations(change.evidence_ref_ids, evidence, limit=2)}"
                )
                _render_change_purpose_contract(lines, change, evidence)
                _render_semantic_delta(lines, change)
                if change.related_test_paths:
                    lines.append(
                        "  - Exact linked test path(s), presence only: "
                        + ", ".join(f"`{_code(path)}`" for path in change.related_test_paths[:4])
                        + ". No execution result is implied."
                    )
    elif state.changed_path_count:
        lines.append("- Changed paths were reported, but no safe path detail is available here.")
    else:
        lines.append("- No changed path was observed in this repository snapshot.")
    _append_omission(
        lines,
        displayed=len(displayed_changes),
        total=state.changed_path_count,
        label="changed path(s)",
        omitted_names=(
            item.path
            for item in state.changes
            if item.path not in {change.path for change in displayed_changes}
        ),
    )


def _render_change_purpose_contract(
    lines: list[str],
    change: Any,
    evidence: Mapping[str, EvidenceReference],
) -> None:
    intended_behavior = change.intended_behavior
    if intended_behavior is None:
        lines.append(
            "  - Intended behavior: unknown; no documentation-stated or "
            "human-confirmed purpose was attached."
        )
    else:
        lines.append(
            "  - Intended behavior (source-backed): "
            f"{_plain(intended_behavior.statement, 420)} "
            f"{_citations(intended_behavior.evidence_ref_ids, evidence, limit=2)}"
        )

    if change.completion_status is RepositoryChangeCompletionStatus.UNKNOWN:
        lines.append(
            "  - Completion status: `unknown`; Git state and semantic deltas do not "
            "establish completion."
        )
    else:
        lines.append(
            f"  - Completion status (source-backed): "
            f"`{change.completion_status.value}` "
            f"{_citations(change.completion_evidence_ref_ids, evidence, limit=2)}. "
            "This is a sourced status declaration, not independent behavioral proof."
        )

    if change.remaining_work_status is RepositoryChangeRemainingWorkStatus.UNKNOWN:
        lines.append(
            "  - Remaining work: unknown; absence of a sourced item does not mean "
            "nothing remains."
        )
    elif change.remaining_work_status is RepositoryChangeRemainingWorkStatus.NONE_STATED:
        lines.append(
            "  - Remaining work (source-backed): `none_stated` "
            f"{_citations(change.remaining_work_evidence_ref_ids, evidence, limit=2)}. "
            "This reports the source statement, not independent completion proof."
        )
    else:
        lines.append(
            "  - Remaining work (source-backed; `identified`): "
            f"{_citations(change.remaining_work_evidence_ref_ids, evidence, limit=2)}"
        )
        displayed = change.remaining_work[:MAX_RENDERED_REMAINING_WORK_PER_CHANGE]
        for item in displayed:
            lines.append(
                f"    - {_plain(item.statement, 320)} "
                f"{_citations(item.evidence_ref_ids, evidence, limit=2)}"
            )
        omitted = len(change.remaining_work) - len(displayed)
        if omitted:
            lines.append(
                f"    - {omitted} additional source-backed remaining-work item(s) "
                "omitted by the per-change bound; do not infer their content."
            )


def _change_group_label(
    change: Any,
    capabilities: Mapping[str, Capability],
    components: Mapping[str, ArchitectureComponent],
) -> str:
    capability_names = [
        capabilities[capability_id].name
        for capability_id in change.capability_ids
        if capability_id in capabilities
    ]
    if capability_names:
        return "Capability-associated change group — " + ", ".join(
            _plain(item, 80) for item in capability_names[:3]
        )
    component_names = [
        components[component_id].name
        for component_id in change.component_ids
        if component_id in components
    ]
    if component_names:
        return "Component-associated change group — " + ", ".join(
            _plain(item, 80) for item in component_names[:3]
        )
    return "Unmapped change group"


def _render_semantic_delta(lines: list[str], change: Any) -> None:
    delta = change.semantic_delta
    if delta is None:
        lines.append(
            "  - Semantic delta: unknown; no bounded HEAD-vs-current observation was "
            "attached to this path."
        )
        return
    if delta.status == "not_observed":
        reason = f" (`{_code(delta.reason)}`)" if delta.reason else ""
        lines.append(
            f"  - Semantic delta: not observed{reason}; symbol, route, import, and "
            "documentation-heading changes are unknown."
        )
        return

    parser_languages = ", ".join(delta.parser_languages) or "unknown language"
    if delta.parser_coverage is RepositorySemanticParserCoverage.LINE_ONLY:
        completeness = f"partial; line-only parser coverage for {parser_languages}"
    elif delta.complete:
        completeness = "complete; parsed syntax coverage"
    else:
        completeness = "partial; parsed syntax coverage"
    line_counts = (
        f"+{delta.lines_added}/-{delta.lines_removed} lines"
        if delta.lines_added is not None and delta.lines_removed is not None
        else "line counts unavailable"
    )
    signals: list[str] = []
    for label, values in (
        ("symbols added", delta.symbols_added),
        ("symbols modified", delta.symbols_modified),
        ("symbols removed", delta.symbols_removed),
        ("routes added", delta.routes_added),
        ("routes removed", delta.routes_removed),
        ("imports added", delta.imports_added),
        ("imports removed", delta.imports_removed),
        ("headings added", delta.headings_added),
        ("headings removed", delta.headings_removed),
    ):
        if values:
            signals.append(
                f"{label}: "
                + ", ".join(f"`{_code(item)}`" for item in values[:4])
                + (f" (+{len(values) - 4} more)" if len(values) > 4 else "")
            )
    if signals:
        detail = "; ".join(signals)
    elif delta.parser_coverage is RepositorySemanticParserCoverage.LINE_ONLY:
        detail = "line counts only; syntax-level item changes are unknown"
    else:
        detail = "no bounded parsed-syntax item changed"
    truncation = "; item lists truncated" if delta.items_truncated else ""
    lines.append(
        f"  - Semantic delta vs `{_code(delta.base or 'unknown base')}` "
        f"(`{completeness}`): {line_counts}; {detail}{truncation}. This is source "
        "difference evidence, not behavioral or completion evidence."
    )


def _required_check_status_counts(
    artifact: WorkspaceFoundationArtifact,
) -> tuple[int, int, int]:
    commands_by_key: dict[tuple[str, str], list[Any]] = {}
    for command in artifact.commands:
        commands_by_key.setdefault(
            (command.command, command.working_directory),
            [],
        ).append(command)

    passed = 0
    failed = 0
    for required in artifact.verification_policy.required_commands:
        statuses = {
            command.verification.status
            for command in commands_by_key.get(
                (required.key.command, required.key.working_directory),
                (),
            )
        }
        if CommandVerificationStatus.FAILED in statuses:
            failed += 1
        elif CommandVerificationStatus.PASSED in statuses:
            passed += 1
    unverified = len(artifact.verification_policy.required_commands) - passed - failed
    return passed, failed, unverified


def _select_repository_engineering_facts(
    facts: Iterable[Any],
    *,
    limit: int,
) -> list[Any]:
    """Preserve engineering-knowledge kind diversity within the render bound."""

    values = list(facts)
    if limit <= 0:
        return []
    selected: list[Any] = []
    selected_ids: set[str] = set()
    for kind in (
        "decision",
        "invariant",
        "convention",
        "known_failure",
        "lesson",
        "current_limitation",
    ):
        match = next(
            (
                item
                for item in values
                if item.id not in selected_ids
                and str(getattr(item.kind, "value", item.kind)) == kind
            ),
            None,
        )
        if match is None:
            continue
        selected.append(match)
        selected_ids.add(match.id)
        if len(selected) >= limit:
            return selected
    for item in values:
        if item.id in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(item.id)
        if len(selected) >= limit:
            break
    return selected


def _select_rendered_commands(
    commands: Iterable[Any],
    *,
    limit: int,
) -> list[Any]:
    """Keep exact-snapshot results visible before unexecuted declarations."""

    status_rank = {
        CommandVerificationStatus.FAILED: 0,
        CommandVerificationStatus.BLOCKED: 1,
        CommandVerificationStatus.PASSED: 2,
        CommandVerificationStatus.STALE: 3,
        CommandVerificationStatus.UNVERIFIED: 4,
    }
    values = list(commands)
    original_order = {item.id: index for index, item in enumerate(values)}
    return sorted(
        values,
        key=lambda item: (
            status_rank.get(item.verification.status, 5),
            original_order[item.id],
        ),
    )[:limit]


def _select_repository_changes(
    changes: Iterable[Any],
    *,
    limit: int,
) -> list[Any]:
    """Keep role diversity while preferring richer observed semantic deltas."""

    ordered = sorted(
        changes,
        key=_repository_change_priority,
    )
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
    selected: list[Any] = []
    selected_paths: set[str] = set()
    for role in role_order:
        candidate = next(
            (item for item in ordered if item.role is role and item.path not in selected_paths),
            None,
        )
        if candidate is None:
            continue
        selected.append(candidate)
        selected_paths.add(candidate.path)
        if len(selected) >= limit:
            return selected
    for item in ordered:
        if item.path in selected_paths:
            continue
        selected.append(item)
        selected_paths.add(item.path)
        if len(selected) >= limit:
            break
    return selected


def _repository_change_priority(change: Any) -> tuple[int, int, int, int, str]:
    delta = change.semantic_delta
    if delta is None:
        return (2, 0, 0, 0 if change.capability_ids else 1, change.path.casefold())
    parser_coverage = getattr(delta.parser_coverage, "value", delta.parser_coverage)
    coverage_rank = {"parsed": 0, "line_only": 1}.get(str(parser_coverage), 2)
    semantic_item_count = sum(
        len(values)
        for values in (
            delta.symbols_added,
            delta.symbols_modified,
            delta.symbols_removed,
            delta.routes_added,
            delta.routes_removed,
            delta.imports_added,
            delta.imports_removed,
            delta.headings_added,
            delta.headings_removed,
        )
    )
    line_magnitude = sum(
        value
        for value in (delta.lines_added, delta.lines_removed)
        if isinstance(value, int) and not isinstance(value, bool)
    )
    return (
        coverage_rank,
        -line_magnitude,
        -semantic_item_count,
        0 if change.capability_ids else 1,
        change.path.casefold(),
    )


def _select_product_boundaries(
    boundaries: Iterable[str],
    *,
    limit: int,
) -> list[str]:
    values = list(boundaries)
    negative_markers = (
        " is not ",
        " isn't ",
        " does not ",
        " do not ",
        " not a ",
        "not another",
        "not the ",
        " unsupported",
        "only supports",
    )
    return sorted(
        values,
        key=lambda value: (
            0 if any(marker in f" {value.casefold()} " for marker in negative_markers) else 1,
            values.index(value),
        ),
    )[:limit]


def _is_manifest_stack_label(value: str) -> bool:
    return value.casefold() in {
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
    }


def _verification_assessment(status: str, surface_count: int) -> str:
    if status == "test_present":
        return f"`test_present` ({surface_count} linked test surface(s); no pass result)"
    if status == "absent":
        return "`absent` (no linked test or executed-check evidence)"
    if status == "passed":
        return "`passed` (snapshot-bound executed evidence)"
    if status == "failed":
        return "`failed` (snapshot-bound executed evidence)"
    if status == "runtime_verified":
        return "`runtime_verified` (snapshot-bound runtime evidence)"
    if status == "stale":
        return "`stale` (not current for this snapshot)"
    return f"`{_code(status)}`"


def _surface_sort_key(surface: CapabilitySurface) -> tuple[int, str, str]:
    priority = {
        SurfaceRole.ENTRYPOINT: 0,
        SurfaceRole.IMPLEMENTATION: 1,
        SurfaceRole.DATA: 2,
        SurfaceRole.OPERATIONS: 3,
        SurfaceRole.VERIFICATION: 4,
        SurfaceRole.DOCUMENTATION: 5,
        SurfaceRole.OTHER: 6,
    }
    return (
        priority.get(surface.role, 99),
        (surface.repository_path or surface.locator).casefold(),
        surface.id,
    )


def _component_sort_key(component: ArchitectureComponent) -> tuple[int, str, str]:
    priority = {
        ArchitectureComponentKind.APPLICATION: 0,
        ArchitectureComponentKind.FRONTEND: 1,
        ArchitectureComponentKind.API: 2,
        ArchitectureComponentKind.CLI: 3,
        ArchitectureComponentKind.SERVICE: 4,
        ArchitectureComponentKind.BACKEND: 5,
        ArchitectureComponentKind.WORKER: 6,
        ArchitectureComponentKind.MODULE: 7,
        ArchitectureComponentKind.DATASTORE: 8,
        ArchitectureComponentKind.CACHE: 9,
        ArchitectureComponentKind.QUEUE: 10,
        ArchitectureComponentKind.INFRASTRUCTURE: 11,
        ArchitectureComponentKind.DEPLOYMENT: 12,
        ArchitectureComponentKind.TEST_SUITE: 90,
        ArchitectureComponentKind.DOCUMENTATION: 91,
    }
    normalized_name = component.name.casefold().strip("/")
    surface_priority = (
        0
        if normalized_name in {"frontend", "web", "ui", "client"}
        else 1
        if component.kind is ArchitectureComponentKind.FRONTEND
        else 0
    )
    return (
        priority.get(component.kind, 50),
        f"{surface_priority}:{normalized_name}",
        component.id,
    )


def _edge_sort_key(
    edge: StructuralEdge,
    components: Mapping[str, ArchitectureComponent],
) -> tuple[int, int, int, str, str, str]:
    relation_priority = {
        StructuralRelation.ROUTES_TO: 0,
        StructuralRelation.CALLS: 1,
        StructuralRelation.INVOKES: 2,
        StructuralRelation.READS_FROM: 3,
        StructuralRelation.WRITES_TO: 4,
        StructuralRelation.PUBLISHES_TO: 5,
        StructuralRelation.CONSUMES_FROM: 6,
        StructuralRelation.DEPENDS_ON: 7,
        StructuralRelation.EXPOSES: 8,
        StructuralRelation.OWNS: 9,
        StructuralRelation.TESTS: 20,
    }
    source = components.get(edge.source_component_id)
    target = components.get(edge.target_component_id)
    return (
        0 if edge.capability_ids else 1,
        _edge_layer_priority(source, target),
        relation_priority.get(edge.relation, 15),
        source.name.casefold() if source else edge.source_component_id,
        target.name.casefold() if target else edge.target_component_id,
        edge.id,
    )


def _edge_layer_priority(
    source: ArchitectureComponent | None,
    target: ArchitectureComponent | None,
) -> int:
    if source is None or target is None:
        return 50
    source_kind = source.kind
    target_kind = target.kind
    preferred_pairs = {
        (ArchitectureComponentKind.FRONTEND, ArchitectureComponentKind.API): 0,
        (ArchitectureComponentKind.API, ArchitectureComponentKind.SERVICE): 1,
        (ArchitectureComponentKind.API, ArchitectureComponentKind.BACKEND): 2,
        (ArchitectureComponentKind.API, ArchitectureComponentKind.MODULE): 3,
        (ArchitectureComponentKind.SERVICE, ArchitectureComponentKind.MODULE): 4,
        (ArchitectureComponentKind.SERVICE, ArchitectureComponentKind.DATASTORE): 4,
        (ArchitectureComponentKind.CLI, ArchitectureComponentKind.SERVICE): 5,
        (ArchitectureComponentKind.WORKER, ArchitectureComponentKind.SERVICE): 5,
    }
    if (source_kind, target_kind) in preferred_pairs:
        return preferred_pairs[(source_kind, target_kind)]
    if source_kind is target_kind:
        return 20
    if source_kind in {
        ArchitectureComponentKind.INFRASTRUCTURE,
        ArchitectureComponentKind.DEPLOYMENT,
    }:
        return 30
    return 10


def _edge_name(
    edge: StructuralEdge,
    components: Mapping[str, ArchitectureComponent],
) -> str:
    source = components.get(edge.source_component_id)
    target = components.get(edge.target_component_id)
    return (
        f"{source.name if source else edge.source_component_id} "
        f"{edge.relation.value.replace('_', ' ')} "
        f"{target.name if target else edge.target_component_id}"
    )


def _has_tier(
    reference_ids: Iterable[str],
    evidence: Mapping[str, EvidenceReference],
    tier: EvidenceTier,
) -> bool:
    return any(
        evidence.get(reference_id) is not None and evidence[reference_id].tier is tier
        for reference_id in reference_ids
    )


def _product_claim_refs(
    claims: Iterable[ProductClaim],
    kind: ProductClaimKind,
    value: str,
) -> tuple[str, ...]:
    normalized = value.casefold()
    return tuple(
        reference_id
        for claim in claims
        if claim.kind is kind and claim.value.casefold() == normalized
        for reference_id in claim.evidence_ref_ids
    )


def _citations(
    reference_ids: Iterable[str],
    evidence: Mapping[str, EvidenceReference],
    *,
    limit: int = 1,
) -> str:
    labels: list[str] = []
    for reference_id in reference_ids:
        reference = evidence.get(reference_id)
        if reference is None:
            continue
        location = reference.path or reference.rule or reference_id
        if reference.start_line is not None:
            suffix = (
                f":L{reference.start_line}"
                if reference.end_line == reference.start_line
                else f":L{reference.start_line}-L{reference.end_line}"
            )
            location += suffix
        labels.append(f"{reference.tier.value.replace('_', ' ')}: `{_code(location)}`")
        if len(labels) >= limit:
            break
    return "[" + "; ".join(labels) + "]" if labels else "[evidence unavailable]"


def _plain(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.replace("`", "'").replace("**", "")
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _code(value: Any) -> str:
    return _plain(value, 500).replace("\\", "/")


def _append_omission(
    lines: list[str],
    *,
    displayed: int,
    total: int,
    label: str,
    omitted_names: Iterable[Any] = (),
) -> None:
    if displayed >= total:
        return
    omitted_count = total - displayed
    names = [name for raw in omitted_names if (name := _plain(raw, 120))][:MAX_OMITTED_NAMES]
    if names:
        detail = ": " + ", ".join(f"`{_code(name)}`" for name in names)
        unnamed_count = omitted_count - len(names)
        if unnamed_count > 0:
            detail += f"; {unnamed_count} more not named here"
    else:
        detail = "; names are unavailable in this projection"
    lines.append(
        f"- Bounded projection omits {omitted_count} {label}{detail}. Coverage is "
        "partial; do not infer completeness from the displayed subset."
    )


__all__ = [
    "WORKSPACE_FOUNDATION_RENDERER_VERSION",
    "render_workspace_foundation_markdown",
]
