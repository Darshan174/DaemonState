from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Any

from app.schemas.context_quality import (
    ClaimCriticality,
    ClaimSelection,
    ContextClaimEnvelope,
    ContextKind,
    canonical_json,
)


_SESSION_RELEVANT_FILE_RENDER_LIMIT = 12
_SESSION_TARGET_INFERENCE_NOISE = frozenset({
    "app/services/session_library.py",
    "app/services/session_summary.py",
    "frontend/src/pages/sessionContinuity.js",
})
_SESSION_CONTEXT_SUBJECT_RE = re.compile(
    r"\b(?:checkpoint|continuation|handoff|session\s+context|session\s+continuity)\b",
    re.IGNORECASE,
)
_SESSION_NEGATED_REFERENCE_ADOPTION_RE = re.compile(
    r"\b(?:do\s+not|don't|never|not\s+going\s+to|without)\b[\s\S]{0,48}"
    r"\b(?:adopt|address|apply|build|fix|implement|ship|use)\b",
    re.IGNORECASE,
)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _stable(prefix: str, value: Any) -> str:
    digest = hashlib.sha256(_text(value).casefold().encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _refs(*values: Any) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            for item in value:
                materialized = _text(item)
                if materialized and materialized not in result:
                    result.append(materialized)
            continue
        materialized = _text(value)
        if materialized and materialized not in result:
            result.append(materialized)
    return tuple(result)


def session_context_claims(
    contract: Mapping[str, Any],
    *,
    checkpoint_id: str,
    boundary_event_id: str | None,
) -> tuple[ContextClaimEnvelope, ...]:
    claims: list[ContextClaimEnvelope] = []
    boundary_ref = f"session_event:{boundary_event_id}" if boundary_event_id else None
    checkpoint_ref = f"checkpoint:{checkpoint_id}"
    current_goal = dict(contract.get("current_goal") or {})
    objective_resolution = dict(contract.get("objective_resolution") or {})
    objective_resolved = bool(
        not objective_resolution
        or (
            objective_resolution.get("status") == "resolved"
            and objective_resolution.get("blocks_copy") is not True
        )
    )
    goal = _text(current_goal.get("text") or current_goal.get("request_verbatim"))
    task_subject = " ".join([
        goal,
        *(
            _text(item.get("text"))
            for key in ("requirements", "constraints")
            for item in contract.get(key) or []
        ),
    ])
    context_system_is_subject = bool(_SESSION_CONTEXT_SUBJECT_RE.search(task_subject))
    referenced_context_is_negated = bool(_SESSION_NEGATED_REFERENCE_ADOPTION_RE.search(
        " ".join([
            _text(current_goal.get("request_verbatim")),
            _text(current_goal.get("text")),
        ])
    ))
    if goal and objective_resolved:
        claims.append(ContextClaimEnvelope(
            stable_id="session.prior_user_objective",
            section="prior_user_objective",
            kind="prior_user_objective",
            statement=goal,
            scope=ContextKind.SESSION,
            authority="direct_user",
            truth_state="historical",
            criticality=ClaimCriticality.CRITICAL,
            evidence_refs=_refs(
                "request_sha256:"
                + str(
                    current_goal.get("resolved_request_sha256")
                    or current_goal.get("request_sha256")
                ),
                [
                    f"objective_provider_event:{value}"
                    for value in objective_resolution.get(
                        "source_provider_event_ids"
                    ) or []
                    if _text(value)
                ],
                [
                    f"objective_session_event:{value}"
                    for value in objective_resolution.get(
                        "source_session_event_ids"
                    ) or []
                    if _text(value)
                ],
                boundary_ref,
                checkpoint_ref,
            ),
            session_boundary_id=boundary_event_id,
        ))

    for item in contract.get("requirements") or []:
        statement = _text(item.get("text"))
        if not statement:
            continue
        claims.append(ContextClaimEnvelope(
            stable_id=_stable("session.open_requirement", statement),
            section="open_context",
            kind="open_requirement",
            statement=statement,
            scope=ContextKind.SESSION,
            authority="direct_user",
            truth_state=(
                "historical" if str(item.get("status")) == "reported_done" else "current"
            ),
            criticality=ClaimCriticality.CRITICAL,
            evidence_refs=_refs(
                item.get("source_request_sha256"),
                item.get("source_event_id"),
                boundary_ref,
            ),
            session_boundary_id=boundary_event_id,
        ))

    for item in contract.get("constraints") or []:
        statement = _text(item.get("text"))
        if not statement:
            continue
        claims.append(ContextClaimEnvelope(
            stable_id=_stable("session.user_constraint", statement),
            section="prior_user_objective",
            kind="user_constraint",
            statement=statement,
            scope=ContextKind.SESSION,
            authority="direct_user",
            truth_state="current",
            criticality=ClaimCriticality.CRITICAL,
            evidence_refs=_refs(item.get("source_event_id"), boundary_ref),
            session_boundary_id=boundary_event_id,
        ))

    for item in contract.get("attachment_dependencies") or []:
        attachment_id = _text(item.get("id")) or _stable("attachment", item)
        statement = _text(
            item.get("name")
            or item.get("portable_reference")
            or f"Required attachment {attachment_id}"
        )
        if not statement:
            continue
        required = item.get("required") is True
        claims.append(ContextClaimEnvelope(
            stable_id=f"session.attachment:{attachment_id}",
            section="evidence_dependencies",
            kind="required_attachment" if required else "historical_attachment",
            statement=statement,
            scope=ContextKind.SESSION,
            authority="direct_user" if required else "agent_report",
            truth_state="current" if item.get("available") is True else "unknown",
            criticality=(
                ClaimCriticality.CRITICAL if required else ClaimCriticality.NORMAL
            ),
            evidence_refs=_refs(
                item.get("sha256"),
                item.get("content_hash"),
                item.get("portable_reference"),
            ),
            session_boundary_id=boundary_event_id,
        ))

    for index, item in enumerate(contract.get("supporting_context") or []):
        if not isinstance(item, Mapping):
            continue
        role = _text(item.get("role")).casefold()
        statement = _text(item.get("text"))
        if role not in {"user", "assistant"} or not statement:
            continue
        content_sha256 = _text(item.get("content_sha256"))
        claims.append(ContextClaimEnvelope(
            stable_id=(
                f"session.referenced_conversation:{index:04d}:{role}:"
                f"{hashlib.sha256(statement.encode('utf-8')).hexdigest()[:24]}"
            ),
            section="referenced_conversation_context",
            kind=f"referenced_{role}_turn",
            statement=statement,
            scope=ContextKind.SESSION,
            # Referenced turns are quoted historical evidence. Even a user-role
            # turn must not become fresh user authority in the receiving session.
            authority="agent_report",
            truth_state="historical",
            criticality=ClaimCriticality.NORMAL,
            selection=(
                ClaimSelection.EXCLUDED
                if referenced_context_is_negated
                else ClaimSelection.INCLUDED
            ),
            exclusion_reason=(
                "negated_historical_reference"
                if referenced_context_is_negated
                else None
            ),
            evidence_refs=_refs(
                f"content_sha256:{content_sha256}" if content_sha256 else None,
                item.get("source"),
                item.get("source_event_id"),
                item.get("source_document_id"),
                boundary_ref,
            ),
            session_boundary_id=boundary_event_id,
        ))

    for item in contract.get("implementation_summary") or []:
        statement = _text(item.get("statement"))
        if not statement:
            continue
        observed = item.get("authority") == "observed_session_evidence"
        claims.append(ContextClaimEnvelope(
            stable_id=_stable("session.progress", statement),
            section="state",
            kind="progress",
            statement=statement,
            scope=ContextKind.SESSION,
            authority="verification_observation" if observed else "agent_report",
            truth_state="verified" if observed else "reported",
            criticality=ClaimCriticality.HIGH,
            evidence_refs=_refs(item.get("evidence"), boundary_ref),
            session_boundary_id=boundary_event_id,
        ))

    historical_groups = (
        ("decision", "decisions", "historical", ClaimCriticality.HIGH),
        ("failed_attempt", "failed_attempts", "historical", ClaimCriticality.HIGH),
        ("blocker", "blockers", "reported", ClaimCriticality.HIGH),
        ("discovery", "discoveries", "reported", ClaimCriticality.NORMAL),
        ("open_item", "open_items", "reported", ClaimCriticality.HIGH),
    )
    for kind, key, truth_state, criticality in historical_groups:
        for item in contract.get(key) or []:
            statement = _text(item.get("statement"))
            if not statement:
                continue
            evidence = item.get("evidence") or []
            claims.append(ContextClaimEnvelope(
                stable_id=_stable(f"session.{kind}", statement),
                section=(
                    "decisions_and_failed_approaches"
                    if kind in {"decision", "failed_attempt"}
                    else "state"
                    if kind == "discovery"
                    else "open_context"
                ),
                kind=kind,
                statement=statement,
                scope=ContextKind.SESSION,
                authority="agent_report",
                truth_state=truth_state,
                criticality=criticality,
                evidence_refs=_refs(evidence, boundary_ref),
                session_boundary_id=boundary_event_id,
            ))

    for item in contract.get("verification") or []:
        command = _text(item.get("command"))
        status = _text(item.get("status")) or "unknown"
        exit_code = item.get("exit_code")
        scope = _text(item.get("scope"))
        cwd = _text(item.get("cwd"))
        statement = (
            f"`{command}` {status}"
            if command
            else f"A prior verification observation was recorded as {status}"
        )
        if exit_code is not None:
            statement += f" with exit code {exit_code}"
        details = [
            f"scope={scope}" if scope else "",
            f"cwd={cwd}" if cwd else "",
        ]
        visible_details = [value for value in details if value]
        if visible_details:
            statement += f" ({'; '.join(visible_details)})"
        statement += "."
        claims.append(ContextClaimEnvelope(
            stable_id=_stable(
                "session.verification",
                f"{command}|{status}|{exit_code}|{scope}|{cwd}|{item.get('observed_at')}",
            ),
            section="state",
            kind="verification_observation",
            statement=statement,
            scope=ContextKind.SESSION,
            authority="verification_observation",
            truth_state="verified",
            criticality=ClaimCriticality.HIGH,
            evidence_refs=_refs(
                item.get("id"),
                item.get("observed_at"),
                item.get("requirement_ids"),
                boundary_ref,
            ),
            session_boundary_id=boundary_event_id,
        ))

    repository = dict(contract.get("repository") or {})
    repository_root = _text(repository.get("root"))
    repository_snapshot = _text(
        repository.get("status_fingerprint")
        or repository.get("snapshot_fingerprint")
        or repository.get("head_commit")
    )
    if repository_root or repository_snapshot:
        statement = _text(
            f"Repository {repository_root or 'unresolved'}; "
            f"branch {repository.get('branch') or 'unknown'}; "
            f"HEAD {repository.get('head_commit') or 'unknown'}; "
            f"dirty {bool(repository.get('dirty'))}."
        )
        claims.append(ContextClaimEnvelope(
            stable_id="session.repository_snapshot",
            section="relevant_surfaces",
            kind="repository_state",
            statement=statement,
            scope=ContextKind.SESSION,
            authority="repository_observation",
            truth_state="current",
            criticality=ClaimCriticality.HIGH,
            evidence_refs=_refs(repository_snapshot, repository.get("captured_at")),
            repository_snapshot_sha256=(
                repository_snapshot if len(repository_snapshot) == 64 else None
            ),
            session_boundary_id=boundary_event_id,
        ))

    files = dict(contract.get("files") or {})
    file_entries: dict[str, dict[str, Any]] = {}
    for priority, group in enumerate(
        ("modified", "relevant", "pre_existing_at_handoff")
    ):
        for item in files.get(group) or []:
            path = _text(item.get("path"))
            if not path:
                continue
            entry = file_entries.setdefault(path, {
                "item": item,
                "priority": priority,
                "repository_observed": False,
            })
            entry["priority"] = min(int(entry["priority"]), priority)
            if group == "pre_existing_at_handoff":
                entry["repository_observed"] = True
                entry["item"] = item
    ordered_files = sorted(
        file_entries.items(),
        key=lambda value: (
            int(value[1]["priority"]),
            value[0].casefold(),
            value[0],
        ),
    )
    rendered_file_count = 0
    for path, entry in ordered_files:
        item = entry["item"]
        repository_observed = bool(entry["repository_observed"])
        inferred_target_noise = bool(
            path in _SESSION_TARGET_INFERENCE_NOISE
            and not context_system_is_subject
        )
        included = bool(
            not inferred_target_noise
            and rendered_file_count < _SESSION_RELEVANT_FILE_RENDER_LIMIT
        )
        if included:
            rendered_file_count += 1
        claims.append(ContextClaimEnvelope(
                stable_id=f"session.file:{path}",
                section="relevant_surfaces",
                kind="relevant_file",
                statement=path,
                scope=ContextKind.SESSION,
                authority=(
                    "repository_observation"
                    if repository_observed
                    else "agent_report"
                ),
                truth_state="current" if repository_observed else "reported",
                criticality=ClaimCriticality.NORMAL,
                selection=(
                    ClaimSelection.INCLUDED if included else ClaimSelection.EXCLUDED
                ),
                exclusion_reason=(
                    None
                    if included
                    else "inferred_target_noise"
                    if inferred_target_noise
                    else "bounded_inventory"
                ),
                evidence_refs=_refs(item.get("sha256"), repository_snapshot),
                repository_snapshot_sha256=(
                    repository_snapshot if len(repository_snapshot) == 64 else None
                ),
                session_boundary_id=boundary_event_id,
        ))

    readiness = dict(contract.get("readiness") or {})
    for item in readiness.get("unknowns") or []:
        statement = _text(item.get("message") if isinstance(item, dict) else item)
        if statement:
            claims.append(ContextClaimEnvelope(
                stable_id=_stable("session.unknown", statement),
                section="uncertainties",
                kind="known_unknown",
                statement=statement,
                scope=ContextKind.SESSION,
                authority="compiler_inference",
                truth_state="unknown",
                criticality=ClaimCriticality.HIGH,
                evidence_refs=_refs(checkpoint_ref),
                session_boundary_id=boundary_event_id,
            ))

    next_action = _text((contract.get("exact_next_action") or {}).get("text"))
    if next_action:
        claims.append(ContextClaimEnvelope(
            stable_id="session.inferred_action",
            section="excluded",
            kind="inferred_action",
            statement=next_action,
            scope=ContextKind.SESSION,
            authority="compiler_inference",
            truth_state="unknown",
            criticality=ClaimCriticality.NORMAL,
            selection=ClaimSelection.EXCLUDED,
            exclusion_reason="background_only_scope",
            evidence_refs=_refs(boundary_ref),
            session_boundary_id=boundary_event_id,
        ))
    for item in contract.get("verification_plan") or []:
        statement = _text(item.get("text"))
        if statement:
            claims.append(ContextClaimEnvelope(
                stable_id=_stable("session.future_verification", statement),
                section="excluded",
                kind="future_action",
                statement=statement,
                scope=ContextKind.SESSION,
                authority="compiler_inference",
                truth_state="unknown",
                criticality=ClaimCriticality.LOW,
                selection=ClaimSelection.EXCLUDED,
                exclusion_reason="background_only_scope",
                evidence_refs=_refs(boundary_ref),
                session_boundary_id=boundary_event_id,
            ))
    return tuple(sorted(claims, key=lambda item: item.stable_id))


def workspace_context_claims(
    foundation: Mapping[str, Any],
) -> tuple[ContextClaimEnvelope, ...]:
    claims: list[ContextClaimEnvelope] = []
    repository = dict(foundation.get("repository_state") or {})
    snapshot = _text(repository.get("snapshot_fingerprint"))

    product = dict(foundation.get("product_profile") or {})
    product_summary = _text(product.get("summary"))
    if product_summary:
        claims.append(ContextClaimEnvelope(
            stable_id="workspace.product:summary",
            section="product",
            kind="product_fact",
            statement=(
                f"{_text(product.get('name'))}: {product_summary}"
                if _text(product.get("name"))
                else product_summary
            ),
            scope=ContextKind.WORKSPACE,
            authority="documentation",
            truth_state="current",
            criticality=ClaimCriticality.CRITICAL,
            evidence_refs=_refs(product.get("evidence_ref_ids")),
            repository_snapshot_sha256=snapshot or None,
        ))
    for item in product.get("claims") or []:
        statement = _text(item.get("value") or item.get("statement"))
        if not statement:
            continue
        kind = _text(item.get("kind")) or "product_fact"
        claims.append(ContextClaimEnvelope(
            stable_id=f"workspace.product:{kind}",
            section="product",
            kind="product_fact",
            statement=statement,
            scope=ContextKind.WORKSPACE,
            authority="documentation",
            truth_state="current",
            criticality=ClaimCriticality.CRITICAL,
            evidence_refs=_refs(item.get("evidence_ref_ids")),
            repository_snapshot_sha256=snapshot or None,
        ))

    groups = (
        ("concepts", "concept", "product", ClaimCriticality.NORMAL),
        (
            "documented_system_flows",
            "documented_system_flow",
            "production_flows",
            ClaimCriticality.HIGH,
        ),
        (
            "capability_surfaces",
            "capability_surface",
            "capabilities",
            ClaimCriticality.NORMAL,
        ),
        ("capabilities", "capability", "capabilities", ClaimCriticality.HIGH),
        ("architecture_components", "architecture_component", "architecture", ClaimCriticality.HIGH),
        ("structural_edges", "architecture_edge", "architecture", ClaimCriticality.NORMAL),
        (
            "implementation_traces",
            "implementation_trace",
            "architecture",
            ClaimCriticality.HIGH,
        ),
        ("production_flows", "production_flow", "production_flows", ClaimCriticality.HIGH),
        ("commands", "workspace_command", "verification", ClaimCriticality.NORMAL),
        ("verification_runs", "verification_run", "verification", ClaimCriticality.HIGH),
        ("change_intents", "change_intent", "repository_state", ClaimCriticality.NORMAL),
        (
            "repository_engineering_knowledge",
            "source_scoped_engineering_fact",
            "engineering_knowledge",
            ClaimCriticality.NORMAL,
        ),
    )
    for key, kind, section, criticality in groups:
        for item in foundation.get(key) or []:
            item_id = _text(item.get("id")) or _stable(f"workspace.{kind}", item)
            statement = _text(
                item.get("summary")
                or item.get("description")
                or item.get("definition")
                or item.get("responsibility")
                or item.get("statement")
                or item.get("purpose")
                or item.get("name")
                or item.get("title")
                or canonical_json(item)
            )
            if not statement:
                continue
            claims.append(ContextClaimEnvelope(
                stable_id=f"workspace.{kind}:{item_id}",
                section=section,
                kind=kind,
                statement=statement,
                scope=ContextKind.WORKSPACE,
                authority=(
                    "verification_observation"
                    if kind == "verification_run"
                    else "documentation"
                    if kind
                    in {
                        "concept",
                        "documented_system_flow",
                        "workspace_command",
                        "source_scoped_engineering_fact",
                    }
                    else "repository_observation"
                ),
                truth_state=(
                    "verified"
                    if kind == "verification_run"
                    and (item.get("result") or item.get("status")) == "passed"
                    else "reported"
                    if kind == "source_scoped_engineering_fact"
                    else "current"
                ),
                criticality=criticality,
                evidence_refs=_refs(item.get("evidence_ref_ids"), snapshot),
                repository_snapshot_sha256=snapshot or None,
            ))

    durable_values: Iterable[Mapping[str, Any]] = (
        foundation.get("durable_facts")
        or foundation.get("durable_knowledge")
        or []
    )
    for item in durable_values:
        item_id = _text(item.get("id")) or _stable("workspace.durable", item)
        statement = _text(item.get("statement") or item.get("value") or item.get("title"))
        if not statement:
            continue
        evidence_level = _text(
            item.get("evidence_tier") or item.get("evidence_level")
        ).casefold()
        authority = (
            "verification_observation"
            if evidence_level
            in {
                "runtime_verified",
                "test_verified",
                "system_verified",
            }
            else "repository_observation"
            if evidence_level == "code_observed"
            else "human_confirmed"
            if "human" in evidence_level or "corroborated" in evidence_level
            else "agent_report"
        )
        claims.append(ContextClaimEnvelope(
            stable_id=f"workspace.durable_project_fact:{item_id}",
            section="durable_knowledge",
            kind="durable_project_fact",
            statement=statement,
            scope=ContextKind.WORKSPACE,
            authority=authority,
            truth_state="verified" if authority != "agent_report" else "reported",
            criticality=ClaimCriticality.HIGH,
            evidence_refs=_refs(item.get("evidence_ref_ids"), item.get("provenance_refs")),
            repository_snapshot_sha256=snapshot or None,
        ))

    if repository:
        statement = _text(
            f"Repository snapshot {snapshot or 'unknown'}; branch "
            f"{repository.get('branch') or 'unknown'}; HEAD "
            f"{repository.get('head_commit') or 'unknown'}; dirty "
            f"{bool(repository.get('dirty'))}."
        )
        claims.append(ContextClaimEnvelope(
            stable_id="workspace.repository_snapshot",
            section="repository_state",
            kind="repository_state",
            statement=statement,
            scope=ContextKind.WORKSPACE,
            authority="repository_observation",
            truth_state="current",
            criticality=ClaimCriticality.CRITICAL,
            evidence_refs=_refs(snapshot, repository.get("head_commit")),
            repository_snapshot_sha256=snapshot or None,
        ))

    quality = dict(foundation.get("quality_report") or {})
    for item in quality.get("issues") or []:
        statement = _text(item.get("message"))
        if not statement:
            continue
        issue_id = _text(item.get("id")) or _stable("workspace.issue", statement)
        claims.append(ContextClaimEnvelope(
            stable_id=f"workspace.known_unknown:{issue_id}",
            section="uncertainties",
            kind="known_unknown",
            statement=statement,
            scope=ContextKind.WORKSPACE,
            authority="compiler_inference",
            truth_state="unknown",
            criticality=(
                ClaimCriticality.HIGH
                if item.get("blocking") is True
                else ClaimCriticality.NORMAL
            ),
            evidence_refs=_refs(item.get("entity_ids"), snapshot),
            repository_snapshot_sha256=snapshot or None,
        ))
    return tuple(sorted(claims, key=lambda item: item.stable_id))
