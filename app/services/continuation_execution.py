from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContinuationExecution, ContinuationRequirement
from app.schemas.continuation_execution import (
    MAX_CONTINUATION_ARTIFACTS,
    MAX_PROJECT_CONTEXT_ITEMS,
    MAX_REPOSITORY_EVIDENCE_ITEMS,
    AtomicRequirement,
    ArtifactReference,
    AuthoritativeRequest,
    ContinuationArtifactInput,
    ContinuationExecutionContract,
    ContinuationTaskIdentity,
    ExecutionAuthority,
    ExecutionPolicy,
    HandoffReconciliation,
    HandoffTruthState,
    PreexistingChange,
    ProjectContextItem,
    ProjectContextKind,
    ReadPlanItem,
    RepositoryEvidenceItem,
    RepositoryEvidenceKind,
    RequestSourceSpan,
    RepositoryReconciliationState,
    RepositoryContract,
    RequiredCapability,
    RequirementPriority,
    StructuredHandoff,
    StructuredHandoffItem,
    SupportingContextItem,
    TaskMode,
    VerificationSpec,
    VerifierType,
    build_authoritative_request,
    compile_request_requirements,
    resolve_task_mode,
    sha256_text,
)
from app.services.checkpoints import derive_session_handoff_requirements
from app.services.execution_prompt_renderer import (
    canonical_contract_json,
    render_continuation_execution_prompt,
)
from app.time import utc_now


WORKER_CONTEXT_PROJECTION_VERSION = "worker_context_projection.v6"
_TOOL_SELECTION_DECISION_RE = re.compile(
    r"\b(?:i|we)\s*(?:(?:'ll|’ll|will|would|should|can)\s+|"
    r"(?:am|are|'m|’m|'re|’re)\s+(?:now\s+)?)"
    r"(?:call|inspect\s+with|open|run|use|using)\s+"
    r"(?:the\s+)?(?:browser(?:-control)?|command|exec|git|js|node|"
    r"playwright|pytest|python|rg|shell|terminal|tool|skill)\b",
    re.IGNORECASE,
)
_READ_ONLY_PROJECT_COMMANDS = {
    "cat",
    "command",
    "env",
    "find",
    "grep",
    "head",
    "ls",
    "printenv",
    "pwd",
    "rg",
    "sed",
    "tail",
    "test",
    "type",
    "which",
}


@dataclass(frozen=True)
class CompiledContinuationExecution:
    execution: ContinuationExecution
    contract: ContinuationExecutionContract
    prompt_markdown: str


async def compile_and_persist_continuation_execution(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    context_pack_id: UUID | str,
    request_verbatim: str,
    task_mode: TaskMode | str | None,
    repository: dict[str, Any] | None,
    restored_checkpoint: dict[str, Any] | None,
    context_manifest: dict[str, Any],
    task_identity: ContinuationTaskIdentity | dict[str, Any] | None = None,
    checkpoint_id: UUID | str | None = None,
    execution_focus: str | None = None,
    artifacts: Iterable[
        ArtifactReference | ContinuationArtifactInput | dict[str, Any]
    ] = (),
    supporting_context: Iterable[dict[str, Any]] = (),
) -> CompiledContinuationExecution:
    """Compile and persist the canonical worker contract for one continuation.

    `context_manifest` remains the complete audit artifact. Only the typed,
    validated contract and its concise renderer are executable.
    """

    authoritative_request = build_authoritative_request(request_verbatim)
    mode = resolve_task_mode(
        authoritative_request.request_verbatim,
        task_mode,
    )
    source_spans, extracted_requirements = compile_request_requirements(
        authoritative_request,
        task_mode=mode,
    )
    supporting_context_items = _supporting_context_items(supporting_context)
    extracted_requirements = _augment_requirements_from_supporting_context(
        extracted_requirements,
        source_spans=source_spans,
        request_verbatim=authoritative_request.request_verbatim,
        supporting_context=supporting_context_items,
    )
    command_verifiers = _command_verifiers(
        context_manifest,
        mode=mode,
        repository_root=_repository_root(repository, context_manifest),
    )
    artifact_references = _artifact_references(
        authoritative_request.request_verbatim,
        supplied=(
            *tuple(artifacts),
            *_manifest_artifact_inputs(context_manifest),
        ),
    )
    (
        extracted_requirements,
        artifact_references,
    ) = _augment_requirements_from_artifacts(
        extracted_requirements,
        artifact_references,
    )
    requirements, verification = _link_requirement_verifiers(
        extracted_requirements,
        command_verifiers=command_verifiers,
        artifacts=artifact_references,
    )
    repository_contract = _repository_contract(repository, context_manifest)
    task_identity_contract = _continuation_task_identity(
        workspace_id=workspace_id,
        task=authoritative_request,
        repository=repository_contract,
        manifest=context_manifest,
        supplied=task_identity,
    )
    handoff = reconcile_structured_handoff(
        structured_handoff_from_checkpoint(restored_checkpoint),
        repository=repository_contract,
        manifest=context_manifest,
    )
    project_context = _project_context_items(context_manifest)
    repository_evidence = _repository_evidence_items(
        context_manifest,
        repository=repository_contract,
    )
    read_plan = _read_plan(context_manifest, handoff)
    capabilities = _required_capabilities(
        mode=mode,
        artifacts=artifact_references,
        has_command_verifiers=bool(command_verifiers),
    )
    contract_id = uuid4()
    checkpoint_key = _checkpoint_key(checkpoint_id, restored_checkpoint)
    created_at = utc_now()
    contract = ContinuationExecutionContract(
        id=str(contract_id),
        context_pack_id=str(context_pack_id),
        checkpoint_id=checkpoint_key,
        created_at=created_at,
        task_mode=mode,
        task=authoritative_request,
        task_identity=task_identity_contract,
        execution_focus=(
            str(execution_focus).strip() if execution_focus else None
        ),
        source_spans=source_spans,
        requirements=requirements,
        definition_of_done=tuple(
            requirement.id
            for requirement in requirements
            if requirement.priority is RequirementPriority.MUST
        ),
        repository=repository_contract,
        handoff=handoff,
        project_context=project_context,
        repository_evidence=repository_evidence,
        supporting_context=supporting_context_items,
        artifacts=artifact_references,
        read_plan=read_plan,
        verification=verification,
        required_capabilities=capabilities,
        authority=ExecutionAuthority.for_mode(mode),
        execution_policy=ExecutionPolicy(),
    )
    prompt = render_continuation_execution_prompt(contract)
    contract_json = canonical_contract_json(contract)
    idempotency_key = _execution_idempotency_key(
        context_pack_id=str(context_pack_id),
        request_sha256=authoritative_request.request_sha256,
        task_mode=mode,
        checkpoint_id=checkpoint_key,
        repository_fingerprint=repository_contract.status_fingerprint,
        execution_focus=execution_focus,
        artifacts=artifact_references,
        supporting_context=supporting_context_items,
    )
    existing = await session.scalar(
        select(ContinuationExecution)
        .where(ContinuationExecution.idempotency_key == idempotency_key)
        .order_by(ContinuationExecution.created_at, ContinuationExecution.id)
        .limit(1)
    )
    if existing is not None:
        return _compiled_existing(existing)

    execution = ContinuationExecution(
        id=contract_id,
        workspace_id=workspace_id,
        context_pack_id=_required_uuid(context_pack_id, "context_pack_id"),
        checkpoint_id=_uuid_or_none(checkpoint_key),
        schema_version=contract.schema_version,
        task_mode=mode.value,
        request_verbatim=authoritative_request.request_verbatim,
        request_normalized=authoritative_request.request_normalized,
        request_sha256=authoritative_request.request_sha256,
        display_title=authoritative_request.display_title,
        contract_json=contract_json,
        contract_sha256=sha256_text(contract_json),
        prompt_markdown=prompt,
        prompt_sha256=sha256_text(prompt),
        status="compiled",
        idempotency_key=idempotency_key,
    )
    execution.requirements.extend(
        ContinuationRequirement(
            requirement_key=requirement.id,
            text=requirement.text,
            priority=requirement.priority.value,
            source_span_ids_json=json.dumps(
                list(requirement.source_span_ids),
                separators=(",", ":"),
            ),
            verification_ids_json=json.dumps(
                list(requirement.verification_ids),
                separators=(",", ":"),
            ),
        )
        for requirement in contract.requirements
    )
    try:
        async with session.begin_nested():
            session.add(execution)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(ContinuationExecution).where(
                ContinuationExecution.idempotency_key == idempotency_key
            )
        )
        if existing is None:
            raise
        return _compiled_existing(existing)
    return CompiledContinuationExecution(
        execution=execution,
        contract=contract,
        prompt_markdown=prompt,
    )


def structured_handoff_from_checkpoint(
    restored_checkpoint: dict[str, Any] | None,
) -> StructuredHandoff:
    """Project checkpoint sections directly into typed handoff state.

    This deliberately never renders or reparses checkpoint Markdown.
    """

    payload = restored_checkpoint if isinstance(restored_checkpoint, dict) else {}
    checkpoint = (
        payload.get("checkpoint")
        if isinstance(payload.get("checkpoint"), dict)
        else {}
    )
    restored = (
        payload.get("restore_context")
        if isinstance(payload.get("restore_context"), dict)
        else {}
    )
    sections = (
        checkpoint.get("sections")
        if isinstance(checkpoint.get("sections"), dict)
        else restored.get("sections")
        if isinstance(restored.get("sections"), dict)
        else {}
    )
    if sections:
        sections = _project_handoff_sections(sections)
    progress = _handoff_items(sections.get("progress"), category="progress")
    completed = tuple(
        item for item in progress if _completed_state(item.state)
    )
    in_progress = tuple(
        item for item in progress if not _completed_state(item.state)
    )
    remaining = _handoff_items(
        sections.get("exact_next_action"),
        category="exact_next_action",
    )
    decisions = _handoff_items(sections.get("decisions"), category="decisions")
    failed = _handoff_items(
        sections.get("failed_attempts"),
        category="failed_attempts",
    )
    blockers = _handoff_items(sections.get("blockers"), category="blockers")
    files = _handoff_items(
        sections.get("relevant_files"),
        category="relevant_files",
    )
    prior_verification = _handoff_items(
        sections.get("verification"),
        category="verification",
    )
    unknowns = _handoff_items(
        sections.get("unknowns"),
        category="unknowns",
    )

    # Legacy provider checkpoints may not have v5 sections. Preserve their
    # actionable fields as typed, explicitly untrusted state without injecting
    # their historical Markdown into the execution prompt.
    if not sections:
        objective = _safe_historical_statement(restored.get("objective"))
        legacy_remaining: list[StructuredHandoffItem] = []
        if objective:
            legacy_remaining.append(StructuredHandoffItem(
                    id="legacy:objective",
                    statement=objective,
                    state="active",
                    truth_state=HandoffTruthState.AGENT_REPORTED,
                    payload={"legacy_checkpoint": True},
            ))
        earlier_requirements = restored.get("earlier_requirements")
        if isinstance(earlier_requirements, list):
            seen_legacy = {
                " ".join(item.statement.split())
                for item in legacy_remaining
            }
            for index, value in enumerate(earlier_requirements, start=1):
                statement = _safe_historical_statement(value)
                dedupe = " ".join(statement.split())
                if not statement or dedupe in seen_legacy:
                    continue
                seen_legacy.add(dedupe)
                legacy_remaining.append(StructuredHandoffItem(
                    id=f"legacy:requirement:{index}",
                    statement=statement,
                    state="active",
                    truth_state=HandoffTruthState.AGENT_REPORTED,
                    payload={
                        "legacy_checkpoint": True,
                        "source": "earlier_user_requirement",
                    },
                ))
        remaining = tuple(legacy_remaining)
        agent_state = _safe_historical_statement(
            restored.get("agent_reported_state")
        )
        if agent_state:
            in_progress = (
                StructuredHandoffItem(
                    id="legacy:agent-reported-state",
                    statement=agent_state,
                    state="active",
                    truth_state=HandoffTruthState.AGENT_REPORTED,
                    payload={"legacy_checkpoint": True},
                ),
            )
        referenced_files = restored.get("referenced_files")
        if isinstance(referenced_files, list):
            legacy_files: list[StructuredHandoffItem] = []
            for index, value in enumerate(referenced_files, start=1):
                statement = str(value or "").strip()
                if not statement or _looks_like_conversation_dump(statement):
                    continue
                legacy_files.append(StructuredHandoffItem(
                    id=f"legacy:file:{index}",
                    statement=statement[:1_200],
                    state="active",
                    truth_state=HandoffTruthState.AGENT_REPORTED,
                    payload={"legacy_checkpoint": True},
                ))
            files = tuple(legacy_files)

    return StructuredHandoff(
        checkpoint_id=(
            str(checkpoint.get("id") or "").strip()
            or str(restored.get("checkpoint_id") or "").strip()
            or None
        ),
        schema_version=(
            str(checkpoint.get("schema_version") or "").strip() or None
        ),
        completed=completed,
        in_progress=in_progress,
        remaining=remaining,
        decisions=decisions,
        failed_approaches=failed,
        blockers=blockers,
        referenced_files=files,
        prior_verification=prior_verification,
        unknowns=unknowns,
    )


def _project_handoff_sections(
    sections: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Remove presentation/process noise without weakening historical truth."""

    projected = {
        key: [
            item for item in value if isinstance(item, dict)
        ]
        for key, value in sections.items()
        if isinstance(value, list)
    }
    projected["decisions"] = [
        item
        for item in projected.get("decisions", [])
        if not _is_tool_selection_statement(
            str(item.get("statement") or "")
        )
    ]
    projected["verification"] = [
        item
        for item in projected.get("verification", [])
        if not _is_low_signal_handoff_observation(item)
        and _handoff_observation_has_definitive_outcome(item)
    ]
    passing_sequences: dict[tuple[str, str], int] = {}
    for item in projected["verification"]:
        if not _handoff_observation_passed(item):
            continue
        key = _handoff_command_key(item)
        sequence = _handoff_item_sequence(item)
        if key is None or sequence is None:
            continue
        passing_sequences[key] = max(
            sequence,
            passing_sequences.get(key, sequence),
        )
    retained_failures: list[dict[str, Any]] = []
    for item in projected.get("failed_attempts", []):
        if _is_low_signal_handoff_observation(item):
            continue
        key = _handoff_command_key(item)
        failed_sequence = _handoff_item_sequence(item)
        passing_sequence = (
            passing_sequences.get(key) if key is not None else None
        )
        if (
            failed_sequence is not None
            and passing_sequence is not None
            and passing_sequence > failed_sequence
        ):
            continue
        retained_failures.append(item)
    projected["failed_attempts"] = retained_failures
    return projected


def _is_tool_selection_statement(statement: str) -> bool:
    return bool(_TOOL_SELECTION_DECISION_RE.search(statement))


def _is_low_signal_handoff_observation(item: dict[str, Any]) -> bool:
    key = _handoff_command_key(item)
    return bool(key and _is_low_signal_discovery_command(key[1]))


def _handoff_command_key(
    item: dict[str, Any],
) -> tuple[str, str] | None:
    payload = item.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    command = str(payload.get("command") or "").strip()
    if not command:
        statement = str(item.get("statement") or "").strip()
        match = re.match(r"^`([^`]+)`\s+", statement)
        command = match.group(1).strip() if match is not None else ""
    if not command:
        return None
    normalized_command = re.sub(r"\s+", " ", command).strip()
    cwd = str(payload.get("cwd") or "").strip()
    return cwd, normalized_command


def _handoff_item_sequence(item: dict[str, Any]) -> int | None:
    sequences = [
        evidence.get("locator", {}).get("sequence_number")
        for evidence in item.get("evidence") or []
        if isinstance(evidence, dict)
        and isinstance(evidence.get("locator"), dict)
    ]
    values = [
        value
        for value in sequences
        if isinstance(value, int) and not isinstance(value, bool)
    ]
    return max(values) if values else None


def _handoff_observation_passed(item: dict[str, Any]) -> bool:
    payload = item.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    return bool(
        payload.get("passed") is True
        or payload.get("exit_code") == 0
        or str(item.get("state") or "").strip().casefold()
        in {"passed", "success", "succeeded", "verified"}
    )


def _handoff_observation_has_definitive_outcome(
    item: dict[str, Any],
) -> bool:
    """Keep proof sections limited to observations with an actual result."""

    payload = item.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    passed = payload.get("passed")
    exit_code = payload.get("exit_code")
    state = str(item.get("state") or "").strip().casefold()
    return bool(
        isinstance(passed, bool)
        or (isinstance(exit_code, int) and not isinstance(exit_code, bool))
        or state in {
            "failed",
            "failure",
            "passed",
            "success",
            "succeeded",
            "verified",
        }
    )


def _is_low_signal_discovery_command(command: str) -> bool:
    """Identify inspection/collection commands that prove no task outcome."""

    segments = _shell_command_segments(command)
    if not segments:
        return False
    return all(_is_discovery_segment(segment) for segment in segments)


def _shell_command_segments(command: str) -> tuple[tuple[str, ...], ...]:
    if not command.strip() or "$(" in command or "`" in command:
        return ()
    try:
        lexer = shlex.shlex(
            command,
            posix=True,
            punctuation_chars=";&|<>",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return ()
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {"&&", "||", ";", "|"}:
            if not segments[-1]:
                return ()
            segments.append([])
            continue
        if token and set(token) <= set(";&|<>"):
            return ()
        segments[-1].append(token)
    if any(not segment for segment in segments):
        return ()
    return tuple(tuple(segment) for segment in segments)


def _is_discovery_segment(segment: tuple[str, ...]) -> bool:
    executable = Path(segment[0]).name.casefold()
    lowered = tuple(value.casefold() for value in segment[1:])
    if executable in {"pytest", "py.test"}:
        return any(
            value == "--collect-only"
            or value.startswith("--collect-only=")
            for value in lowered
        )
    if (
        executable.startswith("python")
        and len(lowered) >= 3
        and lowered[:2] == ("-m", "pytest")
    ):
        return any(
            value == "--collect-only"
            or value.startswith("--collect-only=")
            for value in lowered[2:]
        )
    if executable == "node":
        return _is_safe_package_script_probe(segment)
    if executable == "git":
        subcommand = next(
            (value for value in lowered if not value.startswith("-")),
            "",
        )
        return subcommand in {
            "branch",
            "diff",
            "log",
            "ls-files",
            "rev-parse",
            "show",
            "status",
        }
    if executable not in _READ_ONLY_PROJECT_COMMANDS:
        return False
    if executable == "sed" and any(
        value == "--in-place"
        or value.startswith("--in-place=")
        or (
            value.startswith("-")
            and not value.startswith("--")
            and "i" in value[1:]
        )
        for value in lowered
    ):
        return False
    if executable == "find" and any(
        value == "-delete"
        or value.startswith("-exec")
        or value.startswith("-ok")
        or value.startswith("-fprint")
        or value == "-fls"
        for value in lowered
    ):
        return False
    return True


def _is_safe_package_script_probe(segment: tuple[str, ...]) -> bool:
    if (
        len(segment) != 3
        or segment[1].casefold() not in {"-e", "--eval"}
    ):
        return False
    script = segment[2]
    lowered = script.casefold()
    if "package.json" not in lowered or "scripts" not in lowered:
        return False
    if re.search(
        r"\b(?:child_process|exec|spawn|fork|eval|function|fetch|"
        r"https?|write|append|unlink|rename|mkdir|rmdir|chmod|chown|"
        r"truncate|rm)\b|process\s*\.",
        lowered,
    ):
        return False
    required_modules = re.findall(
        r"\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
        script,
        re.IGNORECASE,
    )
    return bool(required_modules) and all(
        _is_safe_relative_package_json(module)
        for module in required_modules
    )


def _is_safe_relative_package_json(module: str) -> bool:
    normalized = module.replace("\\", "/")
    if not normalized or normalized.startswith("/") or "\x00" in normalized:
        return False
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    return bool(
        parts
        and parts[-1].casefold() == "package.json"
        and ".." not in parts
    )


def reconcile_structured_handoff(
    handoff: StructuredHandoff,
    *,
    repository: RepositoryContract,
    manifest: dict[str, Any],
) -> StructuredHandoff:
    """Reconcile checkpoint work claims against the repository captured now.

    A checkpoint can report progress, but it cannot prove its own completion.
    When the repository has moved or cannot be matched, completion claims are
    moved to ``unknowns`` instead of being presented as accomplished work.
    Exact contradictions across work-state sections are also made explicit.
    """

    relation = _checkpoint_repository_relation(repository, manifest)
    completed = list(handoff.completed)
    in_progress = list(handoff.in_progress)
    remaining = list(handoff.remaining)
    unknowns = list(handoff.unknowns)

    # Some checkpoint producers use ``active`` for every captured progress
    # item, including statements that unambiguously report completed work.
    # Classify those statements by their semantics before comparing them with
    # the current repository. Otherwise "Implemented." is misleadingly
    # rendered under In progress and escapes stale-completion reconciliation.
    semantically_completed = [
        item for item in in_progress
        if _reported_completion_claim(item.statement)
    ]
    if semantically_completed:
        semantically_completed_ids = {
            item.id for item in semantically_completed
        }
        in_progress = [
            item
            for item in in_progress
            if item.id not in semantically_completed_ids
        ]
        completed.extend(
            item.model_copy(update={
                "state": "reported_complete",
                "payload": {
                    **item.payload,
                    "reconciliation_reason": (
                        "The statement reports completed work even though the "
                        "checkpoint stored it with an active progress state."
                    ),
                },
            })
            for item in semantically_completed
        )
        completed = _dedupe_handoff_items(completed)

    # A generic fallback copied from the original goal is not a later command
    # to reopen work when a subsequent progress event reports completion.
    # Apply the same event chronology defensively here even when an older
    # checkpoint projection did not already suppress that fallback.
    superseded_continuation_ids = {
        item.id
        for item in (*in_progress, *remaining)
        if _recovered_continuation_superseded(
            item,
            completed=completed,
        )
    }
    if superseded_continuation_ids:
        in_progress = [
            item
            for item in in_progress
            if item.id not in superseded_continuation_ids
        ]
        remaining = [
            item
            for item in remaining
            if item.id not in superseded_continuation_ids
        ]

    captured_completion_claims = bool(completed) or any(
        _reported_completion_claim(item.statement)
        for item in unknowns
    )
    completion_claims = [
        item
        for item in (*completed, *in_progress)
        if _generic_completion_claim(item.statement)
    ]
    continuation_claims = [
        item
        for item in (*in_progress, *remaining)
        if _generic_continuation_claim(item.statement)
    ]
    if completion_claims and continuation_claims:
        completion_ids = {item.id for item in completion_claims}
        continuation_ids = {item.id for item in continuation_claims}
        completed = [
            item for item in completed if item.id not in completion_ids
        ]
        in_progress = [
            item
            for item in in_progress
            if item.id not in completion_ids | continuation_ids
        ]
        remaining = [
            item for item in remaining if item.id not in continuation_ids
        ]
        unknowns.append(StructuredHandoffItem(
            id=(
                "reconciliation:semantic-conflict:"
                f"{sha256_text('|'.join(sorted(completion_ids | continuation_ids)))[:16]}"
            ),
            statement=(
                "Prior session reports conflict: completion was claimed while "
                "a continuation action still remained."
            ),
            state="requires_reconciliation",
            truth_state=HandoffTruthState.CONTRADICTED,
            payload={
                "reconciliation_reason": (
                    "A generic completion claim conflicts with a generic "
                    "continuation instruction."
                ),
                "completion_claims": [
                    item.statement for item in completion_claims
                ],
                "continuation_claims": [
                    item.statement for item in continuation_claims
                ],
            },
        ))

    buckets = {
        "completed": completed,
        "in_progress": in_progress,
        "remaining": remaining,
    }
    locations: dict[str, set[str]] = {}
    representative: dict[str, StructuredHandoffItem] = {}
    for bucket_name, values in buckets.items():
        for item in values:
            key = _handoff_statement_key(item.statement)
            if not key:
                continue
            locations.setdefault(key, set()).add(bucket_name)
            representative.setdefault(key, item)

    contradicted_keys = {
        key for key, bucket_names in locations.items()
        if len(bucket_names) > 1
    }
    if contradicted_keys:
        completed = [
            item
            for item in completed
            if _handoff_statement_key(item.statement) not in contradicted_keys
        ]
        in_progress = [
            item
            for item in in_progress
            if _handoff_statement_key(item.statement) not in contradicted_keys
        ]
        remaining = [
            item
            for item in remaining
            if _handoff_statement_key(item.statement) not in contradicted_keys
        ]
        for key in sorted(contradicted_keys):
            item = representative[key]
            unknowns.append(item.model_copy(update={
                "id": f"reconciliation:contradicted:{sha256_text(key)[:16]}",
                "state": "requires_reconciliation",
                "truth_state": HandoffTruthState.CONTRADICTED,
                "payload": {
                    "reconciliation_reason": (
                        "The checkpoint placed the same work in conflicting "
                        "completed, in-progress, or remaining sections."
                    ),
                },
            }))

    unresolved_completion: list[StructuredHandoffItem] = []
    if relation is not RepositoryReconciliationState.MATCHES_CHECKPOINT:
        retained_completion: list[StructuredHandoffItem] = []
        for item in completed:
            if item.truth_state in {
                HandoffTruthState.CONFIRMED_COMMAND,
                HandoffTruthState.USER_ASSERTED,
            }:
                retained_completion.append(item)
                continue
            unresolved_completion.append(item.model_copy(update={
                "id": (
                    "reconciliation:completion:"
                    f"{sha256_text(_handoff_statement_key(item.statement))[:16]}"
                ),
                "state": "requires_revalidation",
                "truth_state": (
                    HandoffTruthState.STALE
                    if relation
                    is RepositoryReconciliationState.CHANGED_SINCE_CHECKPOINT
                    else HandoffTruthState.UNKNOWN
                ),
                "payload": {
                    **item.payload,
                    "reconciliation_reason": (
                        "The completion claim is historical and the checkpoint "
                        "repository snapshot is not the current proven state."
                    ),
                },
            }))
        unknowns.extend(unresolved_completion)
        completed = retained_completion

    unknowns = _dedupe_handoff_items(unknowns)
    if relation is RepositoryReconciliationState.MATCHES_CHECKPOINT:
        summary = (
            "The current repository matches the checkpoint snapshot. Historical "
            "completion statements remain labeled by their evidence authority."
        )
    else:
        relation_summary = (
            "The repository changed after the checkpoint."
            if relation
            is RepositoryReconciliationState.CHANGED_SINCE_CHECKPOINT
            else "The checkpoint and current repository could not be matched."
        )
        if unresolved_completion:
            summary = (
                f"{relation_summary} Unconfirmed completion claims require "
                "revalidation and are listed under Unknowns."
            )
        elif completed:
            summary = (
                f"{relation_summary} Only completion claims carrying explicit "
                "user or command authority remain under Completed; inspect the "
                "current repository before relying on them."
            )
        elif captured_completion_claims:
            summary = (
                f"{relation_summary} No unconfirmed completion claim remains "
                "presented as completed; inspect Unknowns and the current "
                "repository before relying on the handoff."
            )
        else:
            summary = (
                f"{relation_summary} No historical completion claim was "
                "captured; inspect the current repository before relying on "
                "the remaining handoff state."
            )
    return handoff.model_copy(update={
        "completed": tuple(completed),
        "in_progress": tuple(_dedupe_handoff_items(in_progress)),
        "remaining": tuple(_dedupe_handoff_items(remaining)),
        "unknowns": tuple(unknowns),
        "reconciliation": HandoffReconciliation(
            repository_state=relation,
            summary=summary,
        ),
    })


def _checkpoint_repository_relation(
    repository: RepositoryContract,
    manifest: dict[str, Any],
) -> RepositoryReconciliationState:
    continuation = (
        manifest.get("continuation")
        if isinstance(manifest.get("continuation"), dict)
        else {}
    )
    checkpoint_fingerprint = str(
        continuation.get("checkpoint_fingerprint") or ""
    ).strip()
    current_fingerprint = str(
        repository.status_fingerprint
        or continuation.get("current_repo_fingerprint")
        or ""
    ).strip()
    if not checkpoint_fingerprint or not current_fingerprint:
        return RepositoryReconciliationState.UNKNOWN
    if checkpoint_fingerprint == current_fingerprint:
        return RepositoryReconciliationState.MATCHES_CHECKPOINT
    return RepositoryReconciliationState.CHANGED_SINCE_CHECKPOINT


def _handoff_statement_key(value: str) -> str:
    return " ".join(
        re.sub(r"[^a-z0-9/_.-]+", " ", value.casefold()).split()
    )


def _handoff_sequence(item: StructuredHandoffItem) -> int | None:
    for evidence in item.evidence:
        locator = (
            evidence.get("locator")
            if isinstance(evidence.get("locator"), dict)
            else {}
        )
        value = locator.get("sequence_number")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    value = item.payload.get("sequence_number")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _recovered_continuation_superseded(
    item: StructuredHandoffItem,
    *,
    completed: Iterable[StructuredHandoffItem],
) -> bool:
    if (
        item.payload.get("derived_from_recovered_goal") is not True
        or not _generic_continuation_claim(item.statement)
    ):
        return False
    continuation_sequence = _handoff_sequence(item)
    if continuation_sequence is None:
        return False
    return any(
        completion_sequence > continuation_sequence
        for completed_item in completed
        if (completion_sequence := _handoff_sequence(completed_item))
        is not None
    )


def _generic_completion_claim(value: str) -> bool:
    normalized = " ".join(str(value or "").split())
    if re.search(
        r"\b(?:not|never|isn't|wasn't|unfinished|incomplete|failed to)\b",
        normalized,
        re.IGNORECASE,
    ):
        return False
    return bool(re.fullmatch(
        r"(?:implemented|completed|done|finished|fixed)"
        r"(?:\s+(?:it|everything|end[\s-]*to[\s-]*end|"
        r"the\s+(?:task|work|request)))?[.!]?",
        normalized,
        re.IGNORECASE,
    ))


def _reported_completion_claim(value: str) -> bool:
    """Recognize an affirmative historical statement of completed work.

    This is intentionally narrower than generic progress detection. It accepts
    result-state wording but rejects partial, negated, or explicitly remaining
    work so those statements stay under In progress.
    """

    normalized = " ".join(str(value or "").split())
    if not normalized or re.search(
        r"\b(?:not|never|isn't|isnt|wasn't|wasnt|aren't|arent|"
        r"unfinished|incomplete|failed\s+to|partially|in[\s-]+progress|"
        r"working\s+on|still\s+(?:needs?|requires?)|remaining|todo|"
        r"to[\s-]+do)\b",
        normalized,
        re.IGNORECASE,
    ):
        return False
    return _generic_completion_claim(normalized) or bool(re.search(
        r"\b(?:added|built|captured|completed|confirmed|created|fixed|"
        r"implemented|passed|removed|replaced|updated|wired)\b|"
        r"\b(?:is|are|was|were)\s+"
        r"(?:fully\s+)?(?:added|built|captured|complete|completed|confirmed|"
        r"created|fixed|implemented|in\s+place|passed|removed|replaced|"
        r"updated|wired|working)\b",
        normalized,
        re.IGNORECASE,
    ))


def _generic_continuation_claim(value: str) -> bool:
    return bool(re.match(
        r"^(?:continue|complete|finish|resume)\b[\s\S]*"
        r"(?:request|task|work)\b",
        " ".join(str(value or "").split()),
        re.IGNORECASE,
    ))


def _dedupe_handoff_items(
    values: Iterable[StructuredHandoffItem],
) -> list[StructuredHandoffItem]:
    result: list[StructuredHandoffItem] = []
    seen: set[str] = set()
    for item in values:
        key = _handoff_statement_key(item.statement)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _project_context_items(
    manifest: dict[str, Any],
) -> tuple[ProjectContextItem, ...]:
    """Project only current, provenance-verified, task-relevant workspace facts.

    Selection scores, citations, source IDs, hashes, and exclusion metadata
    remain in ContextPack. They must never leak into the worker contract.
    Historical tasks, raw conversations, and generic repository inventory are
    deliberately excluded even when they happened to rank into the audit pack.
    """

    selected = manifest.get("selected_context")
    if not isinstance(selected, list):
        return ()

    result: list[ProjectContextItem] = []
    seen_identities: set[str] = set()
    seen_statements: set[str] = set()
    for raw in selected:
        if not isinstance(raw, dict):
            continue
        kind = _project_context_kind(raw)
        if not _eligible_project_context_raw(raw, kind=kind):
            continue

        title = _project_context_title(raw.get("title"))
        statement = _project_context_statement(raw.get("summary"))
        if (
            not title
            or not statement
            or re.match(r"^(?:area|repository)\s*:", title, re.IGNORECASE)
            or (
                kind in {
                    ProjectContextKind.DECISION,
                    ProjectContextKind.INVARIANT,
                }
                and _is_tool_selection_statement(f"{title}\n{statement}")
            )
        ):
            continue
        identity = str(
            raw.get("claim_id") or raw.get("identity_key") or ""
        ).strip()
        statement_key = _project_context_dedupe_key(statement)
        if (
            (identity and identity in seen_identities)
            or statement_key in seen_statements
        ):
            continue
        if identity:
            seen_identities.add(identity)
        seen_statements.add(statement_key)
        result.append(ProjectContextItem(
            id=f"P{len(result) + 1}",
            kind=kind,
            title=title,
            statement=statement,
        ))
        if len(result) >= MAX_PROJECT_CONTEXT_ITEMS:
            break
    return tuple(result)


def _repository_evidence_items(
    manifest: dict[str, Any],
    *,
    repository: RepositoryContract,
) -> tuple[RepositoryEvidenceItem, ...]:
    """Bind syntax-level index evidence to files that still hash identically.

    Repository evidence is deliberately separate from durable project facts:
    declarations and exact index edges are observable, but they do not prove
    code behavior or architectural intent.
    """

    payload = manifest.get("repository_evidence")
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "repository_evidence.v1"
        or repository.status_truncated
    ):
        return ()
    repo_state = (
        manifest.get("repo_state")
        if isinstance(manifest.get("repo_state"), dict)
        else {}
    )
    evidence_fingerprint = str(
        payload.get("snapshot_fingerprint") or ""
    ).strip()
    manifest_fingerprint = str(
        repo_state.get("snapshot_fingerprint") or ""
    ).strip()
    if (
        not evidence_fingerprint
        or not manifest_fingerprint
        or evidence_fingerprint != manifest_fingerprint
    ):
        return ()
    evidence_head = str(payload.get("head_commit") or "").strip()
    if (
        evidence_head
        and repository.head_commit
        and evidence_head != repository.head_commit
    ):
        return ()
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return ()
    try:
        root = Path(repository.root).expanduser().resolve(strict=True)
    except OSError:
        return ()
    if not root.is_dir():
        return ()

    result: list[RepositoryEvidenceItem] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        try:
            item = RepositoryEvidenceItem.model_validate(raw)
        except ValueError:
            continue
        file_bindings = _repository_evidence_file_bindings(item)
        if not file_bindings or any(
            not _repository_evidence_file_matches(
                root,
                path=path,
                expected_sha256=digest,
            )
            for path, digest in file_bindings
        ):
            continue
        result.append(item)
        if len(result) >= MAX_REPOSITORY_EVIDENCE_ITEMS:
            break
    return tuple(result)


def _repository_evidence_file_bindings(
    item: RepositoryEvidenceItem,
) -> tuple[tuple[str, str], ...]:
    if item.kind is RepositoryEvidenceKind.SYMBOL_DECLARATION:
        return ((str(item.path), str(item.file_sha256)),)
    if item.kind is RepositoryEvidenceKind.TEST_LINK:
        return (
            (str(item.test_path), str(item.test_sha256)),
            (str(item.target_path), str(item.target_sha256)),
        )
    return ((str(item.manifest_path), str(item.manifest_sha256)),)


def _repository_evidence_file_matches(
    root: Path,
    *,
    path: str,
    expected_sha256: str,
) -> bool:
    normalized = str(path or "").replace("\\", "/").removeprefix("./")
    if (
        not normalized
        or normalized.startswith("/")
        or ".." in normalized.split("/")
    ):
        return False
    try:
        candidate = (root / normalized).resolve(strict=True)
    except OSError:
        return False
    if not candidate.is_file() or not candidate.is_relative_to(root):
        return False
    try:
        return _sha256_file(candidate) == expected_sha256
    except OSError:
        return False


def _eligible_project_context_raw(
    raw: dict[str, Any],
    *,
    kind: ProjectContextKind | None = None,
) -> bool:
    kind = kind or _project_context_kind(raw)
    allowed_kinds = {
        ProjectContextKind.DECISION,
        ProjectContextKind.INVARIANT,
        ProjectContextKind.BLOCKER,
        ProjectContextKind.RISK,
        ProjectContextKind.LEARNING,
        ProjectContextKind.CONTEXT,
    }
    if kind not in allowed_kinds:
        return False
    if (
        not str(raw.get("component_id") or "").strip()
        or not str(raw.get("source_document_id") or "").strip()
        or not str(raw.get("evidence_span_id") or "").strip()
        or raw.get("provenance_verified") is not True
        or str(raw.get("truth_state") or "").strip().casefold() != "current"
        or str(raw.get("status") or "").strip().casefold()
        not in {"active", "verified"}
        or str(raw.get("conflict_state") or "none").strip().casefold()
        not in {"", "none"}
        or _project_context_prompt_risk(raw) >= 0.70
    ):
        return False
    title = str(raw.get("title") or "")
    statement = str(raw.get("summary") or "")
    return not _looks_like_conversation_dump(f"{title}\n{statement}")


def _looks_like_conversation_dump(value: str) -> bool:
    """Reject transcript-shaped blobs from the compact project projection."""

    normalized = value.casefold()
    if any(marker in normalized for marker in (
        "referenced chatgpt conversation",
        '"conversationid"',
        '"conversation":[',
        '"content_type":"text"',
        "chatgpt-conversation://",
    )):
        return True
    json_roles = re.findall(
        r'"role"\s*:\s*"(?:user|assistant|system|developer)"',
        normalized,
    )
    line_roles = re.findall(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:user|assistant|system|developer)\s*:",
        value,
    )
    if len(json_roles) >= 2 or len(line_roles) >= 2:
        return True
    # Atomic project facts should not contain an embedded multi-section essay.
    return len(re.findall(r"(?m)^\s*#{1,6}\s+\S", value)) >= 3


def _project_context_dedupe_key(value: str) -> str:
    return " ".join(
        re.sub(r"[^a-z0-9/_.-]+", " ", value.casefold()).split()
    )


def _continuation_task_identity(
    *,
    workspace_id: UUID,
    task: AuthoritativeRequest,
    repository: RepositoryContract,
    manifest: dict[str, Any],
    supplied: ContinuationTaskIdentity | dict[str, Any] | None,
) -> ContinuationTaskIdentity:
    continuation = (
        manifest.get("continuation")
        if isinstance(manifest.get("continuation"), dict)
        else {}
    )
    raw_identity: ContinuationTaskIdentity | dict[str, Any] | None = supplied
    if raw_identity is None and isinstance(
        continuation.get("task_identity"),
        dict,
    ):
        raw_identity = continuation["task_identity"]
    if raw_identity is not None:
        identity = (
            raw_identity
            if isinstance(raw_identity, ContinuationTaskIdentity)
            else ContinuationTaskIdentity.model_validate(raw_identity)
        )
        if identity.workspace_id != workspace_id:
            raise ValueError(
                "task identity workspace does not match continuation workspace"
            )
        if identity.authoritative_request_sha256 != task.request_sha256:
            raise ValueError(
                "task identity request hash does not match authoritative request"
            )
        return identity

    selected_objective = str(
        continuation.get("selected_objective")
        or task.request_normalized
    ).strip()
    selected_objective_key = re.sub(
        r"[^a-z0-9]+",
        " ",
        selected_objective.casefold(),
    ).strip()
    root = str(Path(repository.root).expanduser())
    branch = " ".join(str(repository.branch or "").casefold().split())
    fallback_digest = hashlib.sha256(
        (
            f"{workspace_id}:{root}:{branch}:"
            f"{selected_objective_key}"
        ).encode("utf-8")
    ).hexdigest()
    return ContinuationTaskIdentity(
        id=(
            str(continuation.get("task_id") or "").strip()
            or f"task:{fallback_digest[:24]}"
        ),
        workspace_id=workspace_id,
        selected_objective_key=selected_objective_key,
        selected_objective_sha256=sha256_text(selected_objective),
        authoritative_request_sha256=task.request_sha256,
    )


def _project_context_kind(value: dict[str, Any]) -> ProjectContextKind:
    item_type = str(value.get("item_type") or "").strip().casefold()
    direct = {
        "decision": ProjectContextKind.DECISION,
        "invariant": ProjectContextKind.INVARIANT,
        "blocker": ProjectContextKind.BLOCKER,
        "risk": ProjectContextKind.RISK,
        "verification": ProjectContextKind.VERIFICATION,
        "task": ProjectContextKind.TASK,
        "component": ProjectContextKind.CONTEXT,
        "context": ProjectContextKind.CONTEXT,
    }
    if item_type in direct:
        return direct[item_type]
    lane = str(value.get("lane") or "").strip().casefold()
    if lane == "prior_failures":
        return ProjectContextKind.LEARNING
    if lane == "verification":
        return ProjectContextKind.VERIFICATION
    if lane == "decisions_and_invariants":
        # A ranking lane is not evidence that an ordinary fact is an
        # invariant. Reserve that stronger label for an explicit item type.
        return ProjectContextKind.CONTEXT
    return ProjectContextKind.CONTEXT


def _project_context_title(value: Any) -> str:
    normalized = " ".join(str(value or "").split())
    return normalized[:240].rstrip()


def _project_context_statement(value: Any) -> str:
    normalized = str(value or "").strip()
    if len(normalized) <= 1_200:
        return normalized
    return normalized[:1_199].rstrip() + "…"


def _project_context_prompt_risk(value: dict[str, Any]) -> float:
    try:
        return float(value.get("prompt_injection_risk_score") or 0.0)
    except (TypeError, ValueError):
        return 1.0


def _supporting_context_items(
    values: Iterable[dict[str, Any]],
) -> tuple[SupportingContextItem, ...]:
    result: list[SupportingContextItem] = []
    seen: set[tuple[str, str]] = set()
    for raw in values:
        if not isinstance(raw, dict):
            raise ValueError("supporting context items must be objects")
        role = str(raw.get("role") or "").strip().lower()
        text = str(raw.get("text") or "").strip()
        source = str(raw.get("source") or "").strip()
        key = (role, sha256_text(text))
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(SupportingContextItem(
            role=role,
            text=text,
            source=source,
            truth_state="historical_data",
            content_sha256=key[1],
        ))
    return tuple(result)


def _augment_requirements_from_supporting_context(
    requirements: tuple[AtomicRequirement, ...],
    *,
    source_spans: tuple[RequestSourceSpan, ...],
    request_verbatim: str,
    supporting_context: tuple[SupportingContextItem, ...],
) -> tuple[AtomicRequirement, ...]:
    if not supporting_context or not source_spans:
        return requirements
    derived = derive_session_handoff_requirements(
        request_verbatim,
        supporting_context=(
            item.model_dump(mode="json") for item in supporting_context
        ),
    )
    accepted = [
        item
        for item in derived
        if item.get("authority") == "accepted_by_user_reference"
        and item.get("completion_relevant") is not False
    ]
    if not accepted:
        return requirements
    adoption_span = next(
        (
            span
            for span in source_spans
            if re.search(
                r"\b(?:adopt|build|implement|ship|use)\b",
                span.text,
                re.IGNORECASE,
            )
        ),
        source_spans[0],
    )
    result = list(requirements)
    seen = {
        re.sub(r"\W+", " ", item.text.casefold()).strip()
        for item in result
    }
    for item in accepted:
        text = " ".join(str(item.get("text") or "").split())
        key = re.sub(r"\W+", " ", text.casefold()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(AtomicRequirement(
            id=f"R{len(result) + 1}",
            text=text,
            priority=RequirementPriority.MUST,
            source_span_ids=(adoption_span.id,),
        ))
    return tuple(result)


def _link_requirement_verifiers(
    requirements: Iterable[AtomicRequirement],
    *,
    command_verifiers: tuple[VerificationSpec, ...],
    artifacts: tuple[ArtifactReference, ...],
) -> tuple[tuple[AtomicRequirement, ...], tuple[VerificationSpec, ...]]:
    """Build honest requirement-to-proof links.

    A repository command is linked only when its concrete argv/cwd shares
    task-specific vocabulary or an explicit path with that requirement. Generic
    checks never become universal proof.
    """

    requirement_links: dict[str, list[str]] = {
        requirement.id: [] for requirement in requirements
    }
    command_links: dict[str, list[str]] = {
        verifier.id: [] for verifier in command_verifiers
    }
    supplemental: list[VerificationSpec] = []
    artifact_requirement_ids = {
        requirement_id
        for artifact in artifacts
        for requirement_id in artifact.requirement_ids
    }
    requirement_values = tuple(requirements)
    for requirement in requirement_values:
        if requirement.priority is not RequirementPriority.MUST:
            continue
        semantic_type = _semantic_verifier_type(
            requirement.text,
            has_artifact=requirement.id in artifact_requirement_ids,
        )
        matching_commands = [
            verifier
            for verifier in command_verifiers
            if _command_matches_requirement(verifier, requirement)
        ]
        semantic_executor = next(
            (
                verifier
                for verifier in matching_commands
                if verifier.verifier_type is semantic_type
                and verifier.command_argv
            ),
            None,
        )
        if semantic_type is not None and semantic_executor is None:
            verifier_id = f"VS-{requirement.id}"
            supplemental.append(VerificationSpec(
                id=verifier_id,
                verifier_type=semantic_type,
                requirement_ids=(requirement.id,),
                required=True,
                rubric=(
                    "Verify this exact requirement against observed runtime or "
                    f"visual evidence: {requirement.text}"
                    if semantic_type
                    in {
                        VerifierType.BROWSER_ASSERTION,
                        VerifierType.SCREENSHOT_COMPARISON,
                        VerifierType.EVENT_ASSERTION,
                    }
                    else None
                ),
            ))
            requirement_links[requirement.id].append(verifier_id)

        for verifier in matching_commands:
            requirement_links[requirement.id].append(verifier.id)
            command_links[verifier.id].append(requirement.id)

        # A model rubric records the semantic proof contract but remains
        # supplemental when a real deterministic/runtime verifier exists.
        rubric_id = f"VR-{requirement.id}"
        has_required_executor = bool(
            semantic_type is not None or matching_commands
        )
        supplemental.append(VerificationSpec(
            id=rubric_id,
            verifier_type=VerifierType.MODEL_RUBRIC,
            requirement_ids=(requirement.id,),
            required=not has_required_executor,
            rubric=(
                "Judge the observed repository/runtime evidence for this exact "
                f"requirement; a worker claim alone is not proof: {requirement.text}"
            ),
        ))
        requirement_links[requirement.id].append(rubric_id)

    linked_commands = tuple(
        verifier.model_copy(
            update={
                "requirement_ids": tuple(command_links[verifier.id]),
                "required": (
                    verifier.required
                    and bool(command_links[verifier.id])
                ),
            }
        )
        for verifier in command_verifiers
    )
    linked_requirements = tuple(
        requirement.model_copy(
            update={
                "verification_ids": tuple(requirement_links[requirement.id])
            }
        )
        if requirement.priority is RequirementPriority.MUST
        else requirement
        for requirement in requirement_values
    )
    return linked_requirements, (*supplemental, *linked_commands)


def _command_verifiers(
    manifest: dict[str, Any],
    *,
    mode: TaskMode,
    repository_root: str,
) -> tuple[VerificationSpec, ...]:
    if mode not in {TaskMode.CHANGE, TaskMode.DIAGNOSE, TaskMode.TEST_ONLY}:
        return ()
    verification = manifest.get("verification")
    commands = (
        verification.get("commands")
        if isinstance(verification, dict)
        and isinstance(verification.get("commands"), list)
        else []
    )
    result: list[VerificationSpec] = []
    used_ids: set[str] = set()
    for index, value in enumerate(commands, start=1):
        if not isinstance(value, dict):
            continue
        command = str(value.get("command") or "").strip()
        if not command or _is_low_signal_discovery_command(command):
            continue
        try:
            argv = tuple(shlex.split(command))
        except ValueError:
            continue
        if not argv:
            continue
        identifier = str(value.get("id") or f"VC{index}").strip()
        if (
            identifier.startswith(("VR-", "VS-"))
            or identifier in used_ids
        ):
            identifier = f"VC{index}"
        used_ids.add(identifier)
        cwd = _relative_cwd(
            str(value.get("cwd") or repository_root),
            repository_root,
        )
        result.append(VerificationSpec(
            id=identifier,
            verifier_type=_declared_command_verifier_type(value, argv),
            requirement_ids=_declared_requirement_ids(value),
            command_argv=argv,
            cwd=cwd,
            required=bool(value.get("required", True)),
            expected_exit_code=0,
        ))
    return tuple(result)


def _semantic_verifier_type(
    requirement_text: str,
    *,
    has_artifact: bool,
) -> VerifierType | None:
    normalized = requirement_text.casefold()
    if re.search(
        r"\b(?:screenshot|visual parity|pixel|layout|appearance|styling|colour|color)\b",
        normalized,
    ):
        return (
            VerifierType.SCREENSHOT_COMPARISON
            if has_artifact
            else VerifierType.BROWSER_ASSERTION
        )
    if re.search(
        r"\b(?:browser|dom|page|route renders|screen|ui|visible|card|selector)\b",
        normalized,
    ):
        return VerifierType.BROWSER_ASSERTION
    if re.search(
        r"\b(?:event|streamed output|agent ?run|process launches|invocation)\b",
        normalized,
    ):
        return VerifierType.EVENT_ASSERTION
    return None


def _command_matches_requirement(
    verifier: VerificationSpec,
    requirement: AtomicRequirement,
) -> bool:
    if requirement.id in verifier.requirement_ids:
        return True
    requirement_text = requirement.text
    if (
        verifier.verifier_type
        in {VerifierType.UNIT_TEST, VerifierType.INTEGRATION_TEST}
        and _has_explicit_test_intent(requirement_text)
    ):
        return True
    requirement_paths = {
        match.group(0).strip("`'\".,:;()[]{}")
        for match in re.finditer(
            r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+",
            requirement_text,
        )
    }
    verifier_paths = _verifier_paths(verifier)
    if requirement_paths & verifier_paths:
        return True
    requirement_stems = {
        Path(path).stem.casefold()
        for path in requirement_paths
    }
    verifier_test_stems = {
        stem
        for path in verifier_paths
        if Path(path).name.casefold().startswith("test")
        for stem in [
            re.sub(r"^test[_-]?", "", Path(path).stem.casefold())
        ]
        if stem
    }
    if requirement_stems & verifier_test_stems:
        return True
    # Vocabulary overlap is not proof. For example, "Implement API rate
    # limiting" must not inherit tests/api/test_health.py merely because both
    # strings contain "api". An explicit test clause, exact path lineage, or a
    # declared requirement link above is required.
    return False


def _has_explicit_test_intent(requirement_text: str) -> bool:
    return bool(re.search(
        r"\b(?:pytest|vitest|playwright|unittest)\b|"
        r"\b(?:add|create|execute|fix|rerun|run|update|verify|write)\b"
        r"(?:\W+\w+){0,5}\W+tests?\b|"
        r"\btests?\b(?:\W+\w+){0,5}\W+"
        r"(?:coverage|pass|passing|suite)\b",
        requirement_text,
        re.IGNORECASE,
    ))


def _declared_requirement_ids(value: dict[str, Any]) -> tuple[str, ...]:
    raw = value.get("requirement_ids")
    if isinstance(raw, (list, tuple)):
        candidates = raw
    else:
        singular = value.get("requirement_id")
        candidates = (singular,) if singular is not None else ()
    return tuple(dict.fromkeys(
        identifier
        for item in candidates
        if (identifier := str(item or "").strip())
    ))


def _declared_command_verifier_type(
    value: dict[str, Any],
    argv: tuple[str, ...],
) -> VerifierType:
    raw = str(value.get("verifier_type") or "").strip()
    if raw:
        try:
            declared = VerifierType(raw)
        except ValueError:
            declared = None
        if declared not in {
            None,
            VerifierType.MODEL_RUBRIC,
            VerifierType.HUMAN_REVIEW,
        }:
            return declared
    return _command_verifier_type(argv)


def _verifier_paths(verifier: VerificationSpec) -> set[str]:
    paths: set[str] = set()
    for raw in (*verifier.command_argv, verifier.cwd):
        candidate = str(raw or "").strip().replace("\\", "/")
        if candidate.startswith("-") and "=" in candidate:
            candidate = candidate.split("=", 1)[1]
        candidate = candidate.split("::", 1)[0]
        candidate = candidate.strip("`'\".,:;()[]{}")
        if "/" in candidate:
            paths.add(candidate)
    return paths


def _artifact_references(
    request_verbatim: str,
    *,
    supplied: Iterable[
        ArtifactReference | ContinuationArtifactInput | dict[str, Any]
    ],
) -> tuple[ArtifactReference, ...]:
    result: list[ArtifactReference] = []
    seen_paths: set[str] = set()
    for value in supplied:
        if isinstance(value, ArtifactReference):
            artifact = value
        elif isinstance(value, ContinuationArtifactInput):
            artifact = _artifact_from_input(
                value.model_dump(mode="json"),
                fallback_id=f"A{len(result) + 1}",
                requirement_ids=(),
            )
        elif isinstance(value, dict):
            artifact = _artifact_from_input(
                value,
                fallback_id=f"A{len(result) + 1}",
                requirement_ids=(),
            )
        else:
            raise ValueError("artifact inputs must be ArtifactReference objects")
        artifact_paths = {
            artifact.path,
            *(
                (artifact.source_path,)
                if artifact.source_path
                else ()
            ),
        }
        if artifact_paths & seen_paths:
            continue
        seen_paths.update(artifact_paths)
        result.append(artifact)

    attachment_paths: list[str] = []
    for match in re.finditer(
        r"(?is)<image\b[^>]*\bpath\s*=\s*"
        r"(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))[^>]*>",
        request_verbatim,
    ):
        path = next(
            (group for group in match.groups() if group is not None),
            "",
        ).strip()
        if path:
            attachment_paths.append(path)
    for path in attachment_paths:
        if path in seen_paths:
            continue
        seen_paths.add(path)
        # Authoritative request text is not filesystem-read authority. Keep
        # embedded image markup visible to the worker and quality gate, but
        # never resolve or hash the referenced path unless the same path was
        # supplied through the explicit artifact API or trusted manifest.
        result.append(ArtifactReference(
            id=f"A{len(result) + 1}",
            kind="screenshot",
            path=path,
            sha256=None,
            mime_type=mimetypes.guess_type(path)[0],
            required=True,
            available=False,
            requirement_ids=(),
        ))
    if len(result) > MAX_CONTINUATION_ARTIFACTS:
        raise ValueError(
            "continuation artifacts exceed the supported limit of "
            f"{MAX_CONTINUATION_ARTIFACTS}"
        )
    # Provider-recovered artifacts use compact A1/A2/... identifiers, while
    # callers may legitimately supply those same IDs for explicit artifacts.
    # Paths are already deduplicated above; make only colliding identifiers
    # unique before requirement lineage is compiled so one source artifact can
    # never shadow another or make the contract fail validation.
    used_ids: set[str] = set()
    next_generated_id = 1
    canonical: list[ArtifactReference] = []
    for artifact in result:
        artifact_id = artifact.id
        if artifact_id in used_ids:
            while f"A{next_generated_id}" in used_ids:
                next_generated_id += 1
            artifact_id = f"A{next_generated_id}"
            next_generated_id += 1
            artifact = artifact.model_copy(update={"id": artifact_id})
        used_ids.add(artifact_id)
        canonical.append(artifact)
    return tuple(canonical)


def _augment_requirements_from_artifacts(
    requirements: tuple[AtomicRequirement, ...],
    artifacts: tuple[ArtifactReference, ...],
) -> tuple[tuple[AtomicRequirement, ...], tuple[ArtifactReference, ...]]:
    """Give each unlinked required image one explicit semantic dependency.

    Attachment transport tags are not executable requirements. The artifact
    itself is the provenance source, and bidirectional IDs keep its requirement
    lineage exact instead of attaching every image to every visual sentence.
    """

    result_requirements = list(requirements)
    result_artifacts: list[ArtifactReference] = []
    known_requirement_ids = {
        requirement.id for requirement in result_requirements
    }
    for artifact in artifacts:
        linked_ids = tuple(
            requirement_id
            for requirement_id in artifact.requirement_ids
            if requirement_id in known_requirement_ids
        )
        if artifact.required and not linked_ids:
            requirement_id = f"R{len(result_requirements) + 1}"
            result_requirements.append(AtomicRequirement(
                id=requirement_id,
                text=(
                    "Use this required visual attachment as an implementation "
                    "reference and verify the resulting interface against it."
                ),
                priority=RequirementPriority.MUST,
                source_artifact_ids=(artifact.id,),
            ))
            known_requirement_ids.add(requirement_id)
            linked_ids = (requirement_id,)
        result_artifacts.append(
            artifact.model_copy(update={"requirement_ids": linked_ids})
        )
    return tuple(result_requirements), tuple(result_artifacts)


def _manifest_artifact_inputs(
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Read only explicitly artifact-shaped local paths from durable manifests."""

    if not isinstance(manifest, dict):
        return ()
    containers: list[Any] = [
        manifest.get("artifacts"),
        manifest.get("attachments"),
        manifest.get("visual_artifacts"),
    ]
    continuation = manifest.get("continuation")
    if isinstance(continuation, dict):
        containers.extend([
            continuation.get("artifacts"),
            continuation.get("attachments"),
            continuation.get("visual_artifacts"),
        ])
    selected = manifest.get("selected_context")
    if isinstance(selected, list):
        for item in selected:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("item_type") or "").casefold()
            if item_type in {
                "artifact",
                "attachment",
                "image",
                "screenshot",
                "visual_reference",
            }:
                containers.append([item])
            containers.extend([
                item.get("artifacts"),
                item.get("attachments"),
            ])

    result: list[dict[str, Any]] = []
    for container in containers:
        values = (
            container
            if isinstance(container, (list, tuple))
            else [container]
            if isinstance(container, dict)
            else []
        )
        for raw in values:
            if not isinstance(raw, dict):
                continue
            path = str(
                raw.get("path") or raw.get("local_path") or ""
            ).strip()
            if not path:
                continue
            result.append(raw)
            if len(result) > MAX_CONTINUATION_ARTIFACTS:
                return tuple(result)
    return tuple(result)


def _artifact_from_input(
    value: dict[str, Any],
    *,
    fallback_id: str,
    requirement_ids: tuple[str, ...],
) -> ArtifactReference:
    path_text = str(
        value.get("path") or value.get("local_path") or ""
    ).strip()
    if not path_text:
        raise ValueError("artifact path is required")
    path = Path(path_text).expanduser()
    available = False
    digest: str | None = None
    try:
        if path.is_symlink():
            resolved = None
        else:
            resolved = path.resolve(strict=True)
        available = resolved is not None and resolved.is_file()
        if available:
            assert resolved is not None
            path_text = str(resolved)
            digest = _sha256_file(resolved)
    except OSError:
        available = False
    provided_requirement_ids = value.get("requirement_ids")
    linked = (
        tuple(str(item) for item in provided_requirement_ids)
        if isinstance(provided_requirement_ids, (list, tuple))
        else requirement_ids
    )
    return ArtifactReference(
        id=str(value.get("id") or fallback_id),
        kind=str(value.get("kind") or "attachment"),
        path=path_text,
        source_path=(
            str(value.get("source_path") or "").strip() or None
        ),
        sha256=digest,
        mime_type=(
            str(value.get("mime_type") or "").strip()
            or mimetypes.guess_type(path_text)[0]
        ),
        required=bool(value.get("required", True)),
        available=available,
        visual_summary=(
            str(value.get("visual_summary") or "").strip() or None
        ),
        requirement_ids=linked,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_contract(
    repository: dict[str, Any] | None,
    manifest: dict[str, Any],
) -> RepositoryContract:
    current = repository if isinstance(repository, dict) else {}
    if isinstance(current.get("current"), dict):
        current = current["current"]
    repo_state = (
        manifest.get("repo_state")
        if isinstance(manifest.get("repo_state"), dict)
        else {}
    )
    root = str(
        current.get("root")
        or current.get("path")
        or repo_state.get("repo_path")
        or "."
    )
    changes: list[PreexistingChange] = []
    raw_changes = current.get("changed_file_entries")
    if not isinstance(raw_changes, list):
        raw_changes = current.get("changed_files")
    if not isinstance(raw_changes, list):
        raw_changes = repo_state.get("changed_files")
    for raw in raw_changes if isinstance(raw_changes, list) else []:
        if isinstance(raw, dict):
            path = str(raw.get("path") or "").strip()
            status = str(raw.get("status") or "modified").strip("\n\r")
            xy = (
                str(raw.get("xy") or "").strip("\n\r")
                or (status if len(status) == 2 else "")
                or None
            )
            change_kind = (
                str(raw.get("change_kind") or "").strip()
                or _git_change_kind(status)
            )
            digest = str(raw.get("sha256") or "").strip() or None
        else:
            path = str(raw or "").strip()
            status = "modified"
            xy = None
            change_kind = "modified"
            digest = None
        if not path:
            continue
        changes.append(PreexistingChange(
            status=status,
            path=path,
            xy=xy if xy is not None and len(xy) == 2 else None,
            change_kind=change_kind,
            content_sha256=(
                digest if digest and len(digest) == 64 else None
            ),
        ))
    fingerprint = str(
        current.get("status_fingerprint")
        or repo_state.get("state_fingerprint")
        or ""
    ).strip() or None
    return RepositoryContract(
        root=root,
        branch=(
            str(current.get("branch") or repo_state.get("branch") or "").strip()
            or None
        ),
        head_commit=(
            str(
                current.get("head_commit")
                or repo_state.get("head_commit")
                or ""
            ).strip()
            or None
        ),
        status_fingerprint=fingerprint,
        status_truncated=bool(current.get("status_truncated", False)),
        preexisting_changes=tuple(changes),
    )


def _git_change_kind(status_code: str) -> str:
    normalized = str(status_code or "")
    lowered = normalized.casefold()
    if lowered in {
        "added",
        "changed",
        "conflicted",
        "copied",
        "deleted",
        "modified",
        "renamed",
        "type_changed",
        "untracked",
    }:
        return lowered
    if "U" in normalized or normalized in {"AA", "DD"}:
        return "conflicted"
    if "R" in normalized:
        return "renamed"
    if "C" in normalized:
        return "copied"
    if "D" in normalized:
        return "deleted"
    if "A" in normalized:
        return "added"
    if "?" in normalized:
        return "untracked"
    if "T" in normalized:
        return "type_changed"
    if "M" in normalized:
        return "modified"
    return "changed"


def _read_plan(
    manifest: dict[str, Any],
    handoff: StructuredHandoff,
) -> tuple[ReadPlanItem, ...]:
    result: list[ReadPlanItem] = []
    seen: set[str] = set()
    affected = manifest.get("affected_code")
    affected_files = (
        affected.get("files")
        if isinstance(affected, dict)
        and isinstance(affected.get("files"), list)
        else []
    )
    repo_state = (
        manifest.get("repo_state")
        if isinstance(manifest.get("repo_state"), dict)
        else {}
    )
    relevant = (
        repo_state.get("relevant_files")
        if isinstance(repo_state.get("relevant_files"), list)
        else []
    )
    candidates: list[tuple[str, str, str | None]] = []
    for item in affected_files:
        if isinstance(item, dict):
            candidates.append((
                str(item.get("path") or "").strip(),
                str(
                    item.get("why")
                    or item.get("role")
                    or "Objective-matched implementation surface."
                ).strip(),
                str(item.get("symbol") or "").strip() or None,
            ))
            for related in item.get("related_tests") or []:
                if not isinstance(related, dict):
                    continue
                candidates.append((
                    str(related.get("path") or "").strip(),
                    str(
                        related.get("why")
                        or "Exact repository test-path relationship."
                    ).strip(),
                    None,
                ))
    for item in handoff.referenced_files:
        candidates.append((
            item.statement,
            "Referenced by the restored checkpoint; validate before editing.",
            None,
        ))
    selected_context = manifest.get("selected_context")
    for raw in selected_context if isinstance(selected_context, list) else []:
        if not isinstance(raw, dict):
            continue
        kind = _project_context_kind(raw)
        if not _eligible_project_context_raw(raw, kind=kind):
            continue
        title = _project_context_title(raw.get("title"))
        file_refs = raw.get("file_refs")
        if not isinstance(file_refs, list):
            files = raw.get("files")
            file_refs = [
                {"path": value}
                for value in (files if isinstance(files, list) else [])
                if isinstance(value, str)
            ]
        for file_ref in file_refs:
            if not isinstance(file_ref, dict):
                continue
            candidates.append((
                str(file_ref.get("path") or "").strip(),
                (
                    f"Supports accepted current {kind.value}: {title}."
                    if title
                    else f"Supports accepted current {kind.value}."
                ),
                str(file_ref.get("symbol") or "").strip() or None,
            ))
    for item in relevant:
        if isinstance(item, dict):
            reason = str(item.get("reason") or "").strip()
            if reason == "repo_state_fallback":
                continue
            candidates.append((
                str(item.get("path") or "").strip(),
                reason or "Matched the authoritative current lead.",
                str(item.get("symbol") or "").strip() or None,
            ))
    for path, reason, symbol in candidates:
        normalized = path.replace("\\", "/").removeprefix("./")
        if (
            not normalized
            or normalized in seen
            or normalized.startswith("/")
            or ".." in normalized.split("/")
        ):
            continue
        seen.add(normalized)
        result.append(ReadPlanItem(
            path=normalized,
            reason=reason or "Matched the request.",
            symbol=symbol,
            priority=len(result),
        ))
        if len(result) >= 20:
            break
    return tuple(result)


def _handoff_items(value: Any, *, category: str) -> tuple[StructuredHandoffItem, ...]:
    if not isinstance(value, list):
        return ()
    result: list[StructuredHandoffItem] = []
    seen_statements: set[str] = set()
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            continue
        raw_statement = str(raw.get("statement") or "").strip()
        if (
            category == "relevant_files"
            and _looks_like_conversation_dump(raw_statement)
        ):
            continue
        statement = _safe_historical_statement(raw_statement)
        if not statement:
            continue
        deduplication_key = " ".join(statement.split())
        if deduplication_key in seen_statements:
            continue
        seen_statements.add(deduplication_key)
        evidence = tuple(
            item for item in raw.get("evidence") or [] if isinstance(item, dict)
        )
        result.append(StructuredHandoffItem(
            id=(
                str(raw.get("id") or raw.get("item_key") or "").strip()
                or f"{category}:{index}"
            ),
            statement=statement,
            state=str(raw.get("state") or "active").strip() or "active",
            truth_state=_handoff_truth_state(raw, evidence),
            evidence=evidence,
            payload=(
                raw.get("payload")
                if isinstance(raw.get("payload"), dict)
                else {}
            ),
        ))
    return tuple(result)


def _safe_historical_statement(value: Any) -> str:
    statement = str(value or "").strip()
    if not statement:
        return ""
    if _looks_like_conversation_dump(statement):
        return (
            "Transcript-shaped historical content was omitted from the worker "
            "handoff; consult the internal audit artifact only if required."
        )
    if len(statement) > 1_200:
        return statement[:1_199].rstrip() + "…"
    return statement


def _handoff_truth_state(
    item: dict[str, Any],
    evidence: tuple[dict[str, Any], ...],
) -> HandoffTruthState:
    """Classify imported history without trusting its self-declared proof.

    Checkpoint payloads are historical agent data. Only a live reconciliation
    pass may promote them to repository- or command-confirmed authority.
    Negative/uncertain states are safe to preserve because they cannot inflate
    completion confidence.
    """

    raw = str(item.get("truth_state") or "").strip().casefold()
    canonical = {state.value: state for state in HandoffTruthState}
    preserved = {
        HandoffTruthState.AGENT_REPORTED,
        HandoffTruthState.STALE,
        HandoffTruthState.CONTRADICTED,
        HandoffTruthState.UNKNOWN,
    }
    declared = canonical.get(raw)
    if declared in preserved:
        return declared
    if raw in {"reported", "observed"}:
        return HandoffTruthState.AGENT_REPORTED
    if raw or evidence:
        return HandoffTruthState.AGENT_REPORTED
    return HandoffTruthState.UNKNOWN


def _completed_state(value: str) -> bool:
    return value.strip().casefold() in {
        "closed",
        "complete",
        "completed",
        "done",
        "passed",
        "resolved",
        "succeeded",
        "success",
        "verified",
    }


def _required_capabilities(
    *,
    mode: TaskMode,
    artifacts: tuple[ArtifactReference, ...],
    has_command_verifiers: bool,
) -> tuple[RequiredCapability, ...]:
    result = [RequiredCapability.FILE_CONTEXT]
    if mode.allows_edits:
        result.append(RequiredCapability.FILESYSTEM_WRITE)
    if has_command_verifiers:
        result.append(RequiredCapability.COMMAND_EXECUTION)
    if any(
        (
            artifact.kind.casefold()
            in {"image", "screenshot", "visual_reference"}
            or str(artifact.mime_type or "").casefold().startswith("image/")
        )
        and not artifact.visual_summary
        for artifact in artifacts
    ):
        result.append(RequiredCapability.IMAGE_INPUT)
    return tuple(result)


def _command_verifier_type(argv: tuple[str, ...]) -> VerifierType:
    joined = " ".join(argv).casefold()
    if "pytest" in joined or "unittest" in joined:
        return VerifierType.UNIT_TEST
    if "npm test" in joined or "vitest" in joined or "playwright" in joined:
        return VerifierType.INTEGRATION_TEST
    return VerifierType.STATIC_ANALYSIS


def _relative_cwd(cwd: str, repository_root: str) -> str:
    cwd = cwd.strip() or repository_root
    if not os.path.isabs(cwd):
        normalized = os.path.normpath(cwd).replace("\\", "/")
        return "." if normalized == "." else normalized
    try:
        relative = os.path.relpath(cwd, repository_root).replace("\\", "/")
    except ValueError:
        return "."
    if relative == ".":
        return "."
    if relative.startswith("../") or relative == "..":
        return "."
    return relative


def _repository_root(
    repository: dict[str, Any] | None,
    manifest: dict[str, Any],
) -> str:
    return _repository_contract(repository, manifest).root


def _checkpoint_key(
    checkpoint_id: UUID | str | None,
    restored_checkpoint: dict[str, Any] | None,
) -> str | None:
    explicit = str(checkpoint_id or "").strip()
    if explicit:
        return explicit
    handoff = structured_handoff_from_checkpoint(restored_checkpoint)
    return handoff.checkpoint_id


def _execution_idempotency_key(
    *,
    context_pack_id: str,
    request_sha256: str,
    task_mode: TaskMode,
    checkpoint_id: str | None,
    repository_fingerprint: str | None,
    execution_focus: str | None,
    artifacts: tuple[ArtifactReference, ...],
    supporting_context: tuple[SupportingContextItem, ...],
) -> str:
    payload = {
        "worker_context_projection_version": WORKER_CONTEXT_PROJECTION_VERSION,
        "context_pack_id": context_pack_id,
        "request_sha256": request_sha256,
        "task_mode": task_mode.value,
        "checkpoint_id": checkpoint_id,
        "repository_fingerprint": repository_fingerprint,
        "execution_focus": str(execution_focus or "").strip() or None,
        "artifacts": [
            artifact.model_dump(mode="json")
            for artifact in artifacts
        ],
        "supporting_context": [
            item.model_dump(mode="json")
            for item in supporting_context
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _compiled_existing(
    execution: ContinuationExecution,
) -> CompiledContinuationExecution:
    contract = ContinuationExecutionContract.model_validate_json(
        execution.contract_json
    )
    if execution.contract_sha256 != sha256_text(execution.contract_json):
        raise ValueError("Persisted continuation contract failed its integrity check")
    if execution.prompt_sha256 != sha256_text(execution.prompt_markdown):
        raise ValueError("Persisted continuation prompt failed its integrity check")
    return CompiledContinuationExecution(
        execution=execution,
        contract=contract,
        prompt_markdown=execution.prompt_markdown,
    )


def _required_uuid(value: UUID | str, label: str) -> UUID:
    parsed = _uuid_or_none(value)
    if parsed is None:
        raise ValueError(f"{label} must be a UUID")
    return parsed


def _uuid_or_none(value: UUID | str | None) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        return None
