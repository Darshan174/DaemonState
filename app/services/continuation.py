from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Component, SessionEvent, SourceDocument, WorkCheckpoint, Workspace
from app.schemas.continuation_execution import (
    ArtifactReference,
    ContinuationArtifactInput,
    TaskMode,
    build_authoritative_request,
    infer_task_mode,
)
from app.services.access import AccessScope, source_access_predicate
from app.services.checkpoint_verifier import (
    compare_checkpoint_repository,
    verify_checkpoint,
)
from app.services.checkpoints import (
    capture_checkpoint,
    checkpoint_to_dict,
    get_checkpoint,
    list_checkpoints,
    recover_truncated_session_request_from_source,
    resolve_session_handoff_request_verbatim,
    resolve_session_handoff_supporting_context,
    session_request_requires_materialized_context,
)
from app.services.context_compiler import ContextCompiler
from app.services.continuation_execution import (
    compile_and_persist_continuation_execution,
)
from app.services.continuation_quality_gate import (
    ContinuationQualityIssue,
    ContinuationQualityReport,
    evaluate_continuation_quality,
)
from app.services.execution_prompt_renderer import (
    STAGING_CONTEXT_SCHEMA_VERSION,
    render_continuation_staging_context,
)
from app.services.local_harness import capture_repository_snapshot
from app.services.project_scope import normalize_local_path, path_is_within
from app.services.repo_paths import validated_repository_path
from app.services.request_artifacts import (
    TrustedRequestImageDescriptor,
    recover_codex_request_image_descriptors,
    resolve_trusted_request_image_artifacts,
    trusted_request_image_descriptors_from_payload,
)
from app.services.session_events import event_payload
from app.services.session_library import sync_local_session_library
from app.services.session_checkpoints import (
    SessionCheckpointNotFoundError,
    restore_session_checkpoint,
)
from app.services.session_scope import (
    normalize_optional_session_key,
    normalize_session_key,
    scoped_session_documents,
    session_provider_values,
    session_reference,
)
from app.services.session_summary import (
    extract_delegated_user_request,
    extract_user_authored_request,
    is_substantive_user_request,
    normalize_substantive_user_request,
)
from app.services.task_workflow import TaskWorkflowService
from app.services.workspace_goals import resolve_current_goal
from app.services.workspace_scope import current_source_documents, metadata_dict
from app.telemetry import traced


CONTINUATION_SCHEMA_VERSION = "continuation.v1"
CONTINUATION_TASK_IDENTITY_SCHEMA_VERSION = "continuation_task_identity.v1"
_EXECUTION_ONLY_QUALITY_CODES = frozenset({
    "mandatory_requirement_verification_unexecutable",
    "verifier_executor_unavailable",
    "verifier_command_missing",
    "provider_capability_missing",
    "handoff_semantic_conflict",
})
_PROJECT_CONTEXT_COPY_NON_BLOCKING_CODES = frozenset({
    "selected_task_completed",
})
_MAX_REQUEST_EVENTS = 2_000
_GOAL_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "for",
        "in",
        "of",
        "on",
        "please",
        "the",
        "this",
        "to",
        "with",
    }
)


class ContinuationError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class _SessionTaskCandidate:
    provider: str
    session_id: str
    source_document: SourceDocument
    goal_event: SessionEvent
    tip_event: SessionEvent
    objective: str
    request_verbatim: str
    request_recovered: bool = False


@dataclass
class ContinuationResult:
    objective: str
    task: dict[str, Any]
    source_session: dict[str, Any] | None
    checkpoint: dict[str, Any] | None
    verification: dict[str, Any] | None
    repository: dict[str, Any]
    context_pack_id: str
    continuation_execution_id: str
    project_context: dict[str, Any]
    execution_prompt: str
    execution_contract: dict[str, Any]
    quality_report: dict[str, Any]
    markdown: str
    manifest: dict[str, Any]
    health_score: float
    readiness: dict[str, Any]
    attention: list[dict[str, str]]
    sync: dict[str, Any] | None = None
    schema_version: str = CONTINUATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "objective": self.objective,
            "task": self.task,
            "source_session": self.source_session,
            "checkpoint": self.checkpoint,
            "verification": self.verification,
            "repository": self.repository,
            "context_pack_id": self.context_pack_id,
            "continuation_execution_id": self.continuation_execution_id,
            "project_context": self.project_context,
            "execution_prompt": self.execution_prompt,
            "execution_contract": self.execution_contract,
            "quality_report": self.quality_report,
            "markdown": self.markdown,
            "manifest": self.manifest,
            "health_score": self.health_score,
            "readiness": self.readiness,
            "attention": self.attention,
            "sync": self.sync,
        }


class ContinuationService:
    """Resolve, verify, and compile one task-centered continuation artifact."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @traced(
        "daemonstate.continuation.prepare",
        attributes=lambda _args, kwargs: {
            "daemonstate.phase": "continuation_prepare",
            "daemonstate.workspace.id": kwargs.get("workspace_id"),
            "daemonstate.checkpoint.id": kwargs.get("checkpoint_id"),
            "daemonstate.source.provider": kwargs.get("source_provider"),
            "daemonstate.task.mode": kwargs.get("task_mode"),
            "daemonstate.context.token_budget": kwargs.get("token_budget"),
        },
        result_attributes=lambda result: _continuation_trace_result(result),
    )
    async def prepare(
        self,
        *,
        workspace_id: UUID,
        access_scope: AccessScope,
        repo_path: str | None = None,
        objective: str | None = None,
        objective_is_user_edited: bool = False,
        checkpoint_id: UUID | str | None = None,
        checkpoint_source_id: UUID | None = None,
        source_provider: str | None = None,
        source_session_id: str | None = None,
        target_model: str | None = None,
        token_budget: int | None = None,
        task_mode: TaskMode | str | None = None,
        artifacts: tuple[ContinuationArtifactInput, ...] = (),
        sync_sessions: bool = False,
    ) -> ContinuationResult:
        await self._require_workspace(workspace_id, access_scope)
        if sync_sessions and access_scope.principal_id != "local":
            raise ContinuationError(
                "local_action_required",
                "Session sync and command verification are available only from the local app.",
                status_code=403,
            )
        if objective_is_user_edited and objective is None:
            raise ContinuationError(
                "continuation_edited_goal_missing",
                "An edited continuation lead must include the exact user text.",
            )

        try:
            source_session_filter = normalize_optional_session_key(
                source_provider,
                source_session_id,
            )
        except ValueError as exc:
            raise ContinuationError(
                "continuation_source_session_invalid",
                str(exc),
            ) from exc

        normalized_objective = _normalize_goal(
            normalize_substantive_user_request(objective)
            if objective is not None
            else None
        )
        authoritative_request_verbatim = (
            objective if objective is not None else None
        )
        if objective is not None and normalized_objective is None:
            raise ContinuationError(
                "continuation_invalid_goal",
                (
                    "The continuation goal is transport metadata or a control "
                    "instruction, not an executable user task."
                ),
            )
        objective_origin = "explicit" if normalized_objective else None
        trusted_request_event: SessionEvent | None = None
        trusted_request_document: SourceDocument | None = None
        current_goal = None
        sync_summary = None
        attention: list[dict[str, str]] = []

        if sync_sessions:
            sync_summary = await sync_local_session_library(
                self.session,
                workspace_id,
                commit=False,
            )
            failed = int(sync_summary.get("failed") or 0)
            if failed:
                attention.append(_attention(
                    "session_sync_partial",
                    "warning",
                    f"{failed} local session(s) could not be synchronized.",
                ))

        requested_repo = (
            str(validated_repository_path(repo_path))
            if repo_path and str(repo_path).strip()
            else None
        )
        current_repository, current_repo_error = await _current_repository(
            requested_repo
        )
        requested_checkpoint_key = _normalize_checkpoint_key(checkpoint_id)
        durable_checkpoint_id = _uuid_or_none(requested_checkpoint_key)

        if (
            normalized_objective is None
            and requested_checkpoint_key is None
            and source_session_filter is None
        ):
            allowed_source_document_ids = None
            allowed_component_ids = None
            if not access_scope.unrestricted:
                allowed_source_document_ids = set(await self.session.scalars(
                    select(SourceDocument.id).where(
                        source_access_predicate(
                            access_scope,
                            workspace_id=workspace_id,
                        )
                    )
                ))
                allowed_component_ids = set(await self.session.scalars(
                    select(Component.id).where(
                        Component.workspace_id == workspace_id,
                        or_(
                            Component.source_document_id.is_(None),
                            Component.source_document_id.in_(
                                allowed_source_document_ids
                            ),
                        ),
                    )
                ))
            current_goal = await resolve_current_goal(
                self.session,
                workspace_id=workspace_id,
                allowed_component_ids=allowed_component_ids,
                allowed_source_document_ids=allowed_source_document_ids,
            )
            if current_goal is not None:
                candidate_goal = _normalize_goal(current_goal.get("title"))
                if is_substantive_user_request(candidate_goal):
                    normalized_objective = candidate_goal
                    authoritative_request_verbatim = str(
                        current_goal.get("title") or candidate_goal
                    )
                    objective_origin = "current_goal"

        checkpoints = await list_checkpoints(
            self.session,
            workspace_id=workspace_id,
            limit=100,
            access_scope=access_scope,
        )
        requested_checkpoint: WorkCheckpoint | None = None
        requested_checkpoint_recovered_goal: str | None = None
        legacy_restore: dict[str, Any] | None = None
        legacy_document: SourceDocument | None = None
        legacy_checkpoint_summary: dict[str, Any] | None = None
        legacy_repo_path: str | None = None
        legacy_branch: str | None = None
        if durable_checkpoint_id is not None:
            requested_checkpoint = await self._accessible_checkpoint(
                workspace_id=workspace_id,
                checkpoint_id=durable_checkpoint_id,
                access_scope=access_scope,
            )
            requested_checkpoint_recovered_goal = (
                await resolve_session_handoff_request_verbatim(
                    self.session,
                    requested_checkpoint,
                    access_scope=access_scope,
                )
            )
            stored_checkpoint_goal = _checkpoint_goal(requested_checkpoint)
            checkpoint_goal = _checkpoint_goal(
                requested_checkpoint,
                recovered_goal=requested_checkpoint_recovered_goal,
            )
            if checkpoint_goal is None:
                raise ContinuationError(
                    "checkpoint_goal_unavailable",
                    "The requested checkpoint has no single source-backed objective.",
                )
            if (
                normalized_objective is not None
                and not _goals_compatible(normalized_objective, checkpoint_goal)
            ):
                raise ContinuationError(
                    "checkpoint_goal_mismatch",
                    "The requested checkpoint belongs to a different objective.",
                )
            if normalized_objective is not None and not objective_is_user_edited:
                exact_unedited_goals = {
                    value
                    for value in (
                        _normalize_goal(stored_checkpoint_goal),
                        _normalize_goal(checkpoint_goal),
                    )
                    if value is not None
                }
                if _normalize_goal(normalized_objective) not in exact_unedited_goals:
                    raise ContinuationError(
                        "checkpoint_goal_mismatch",
                        (
                            "The supplied checkpoint lead is not its exact "
                            "saved display goal. Mark an intentional user edit "
                            "explicitly or omit the derivative lead."
                        ),
                    )
                normalized_objective = checkpoint_goal
                authoritative_request_verbatim = (
                    requested_checkpoint_recovered_goal
                    or _checkpoint_goal_verbatim(requested_checkpoint)
                    or checkpoint_goal
                )
                objective_origin = "checkpoint"
            if not _checkpoint_repo_compatible(
                requested_checkpoint,
                requested_repo=requested_repo,
                current_repository=current_repository,
                allow_missing_repo=False,
                allow_missing_branch=False,
            ):
                raise ContinuationError(
                    "checkpoint_repository_mismatch",
                    "The requested checkpoint belongs to a different or unknown repository state.",
                )
            if normalized_objective is None:
                normalized_objective = checkpoint_goal
                authoritative_request_verbatim = (
                    requested_checkpoint_recovered_goal
                    or _checkpoint_goal_verbatim(requested_checkpoint)
                    or checkpoint_goal
                )
                objective_origin = "checkpoint"
            if requested_checkpoint_recovered_goal is not None:
                (
                    trusted_request_event,
                    trusted_request_document,
                ) = await self._trusted_checkpoint_request_event(
                    checkpoint=requested_checkpoint,
                    request_verbatim=requested_checkpoint_recovered_goal,
                    access_scope=access_scope,
                )
        elif requested_checkpoint_key is not None:
            if checkpoint_source_id is None:
                raise ContinuationError(
                    "checkpoint_source_required",
                    "A source document is required for a provider-compaction checkpoint.",
                )
            legacy_document = await self._accessible_source_document(
                workspace_id=workspace_id,
                source_document_id=checkpoint_source_id,
                access_scope=access_scope,
            )
            metadata = metadata_dict(legacy_document)
            current_branch = (current_repository or {}).get("branch")
            source_branch = _document_branch(legacy_document)
            provider, legacy_session_id = session_reference(
                legacy_document,
                metadata=metadata,
            )
            try:
                legacy_restore = restore_session_checkpoint(
                    legacy_document.content,
                    metadata,
                    requested_checkpoint_key,
                    session_title=str(metadata.get("title") or "").strip() or None,
                    source_document_id=str(legacy_document.id),
                    session_id=legacy_session_id,
                    harness=provider,
                    source_revision_number=legacy_document.revision_number,
                    source_content_sha256=legacy_document.content_sha256,
                )
            except SessionCheckpointNotFoundError as exc:
                raise ContinuationError(
                    "checkpoint_not_found",
                    "The requested provider-compaction checkpoint was not found.",
                    status_code=404,
                ) from exc
            descriptor = legacy_restore.get("checkpoint", {})
            legacy_repo_path = (
                normalize_local_path(descriptor.get("repo_path"))
                or _document_repo_path(legacy_document)
            )
            legacy_branch = (
                _normalize_goal(descriptor.get("branch"))
                or source_branch
            )
            if (
                requested_repo
                and legacy_repo_path != normalize_local_path(requested_repo)
            ):
                raise ContinuationError(
                    "checkpoint_repository_mismatch",
                    "The requested checkpoint has no exact binding to this repository.",
                )
            if current_branch and legacy_branch and current_branch != legacy_branch:
                raise ContinuationError(
                    "checkpoint_repository_mismatch",
                    "The requested checkpoint belongs to a different branch.",
                )
            checkpoint_goal = _normalize_goal(
                legacy_restore.get("restore_context", {}).get("objective")
            )
            if not is_substantive_user_request(checkpoint_goal):
                raise ContinuationError(
                    "checkpoint_goal_unavailable",
                    "The requested checkpoint has no source-backed objective.",
                )
            if (
                normalized_objective is not None
                and not _goals_compatible(normalized_objective, checkpoint_goal)
            ):
                raise ContinuationError(
                    "checkpoint_goal_mismatch",
                    "The requested checkpoint belongs to a different objective.",
                )
            if normalized_objective is None:
                normalized_objective = checkpoint_goal
                authoritative_request_verbatim = (
                    str(
                        legacy_restore.get("restore_context", {}).get(
                            "objective"
                        )
                        or checkpoint_goal
                    )
                )
                objective_origin = "checkpoint"
            legacy_checkpoint_summary = {
                "id": requested_checkpoint_key,
                "schema_version": "provider_compaction.v1",
                "capture_status": "legacy",
                "continuation_status": "review_required",
                "goal": checkpoint_goal,
                "boundary": descriptor,
                "repo": {
                    "root": legacy_repo_path,
                    "branch": legacy_branch,
                    "head_commit": metadata.get("commit") or metadata.get("head_commit"),
                    "worktree_fingerprint": None,
                },
            }

        session_candidate = await self._latest_session_task(
            workspace_id=workspace_id,
            access_scope=access_scope,
            requested_repo=requested_repo,
            objective=normalized_objective,
            source_session=source_session_filter,
        )
        if source_session_filter is not None:
            if session_candidate is None:
                unfiltered_source = await self._latest_session_task(
                    workspace_id=workspace_id,
                    access_scope=access_scope,
                    requested_repo=requested_repo,
                    objective=None,
                    source_session=source_session_filter,
                )
                if unfiltered_source is None:
                    raise ContinuationError(
                        "continuation_source_session_not_found",
                        (
                            "The requested source session is not available in "
                            "this workspace and repository scope."
                        ),
                        status_code=404,
                    )
                raise ContinuationError(
                    "continuation_source_session_objective_mismatch",
                    (
                        "The requested source session does not contain a "
                        "compatible source-backed objective."
                    ),
                )
            trusted_request_event = session_candidate.goal_event
            trusted_request_document = session_candidate.source_document
            if (
                normalized_objective is not None
                and not objective_is_user_edited
            ):
                exact_source_goals = {
                    value
                    for value in (
                        _normalize_goal(session_candidate.objective),
                        _normalize_goal(session_candidate.request_verbatim),
                    )
                    if value is not None
                }
                if _normalize_goal(normalized_objective) not in exact_source_goals:
                    raise ContinuationError(
                        "continuation_source_session_objective_mismatch",
                        (
                            "The supplied source-session lead is not its exact "
                            "lossless task. Mark an intentional user edit "
                            "explicitly or omit the derivative lead."
                        ),
                    )
                normalized_objective = session_candidate.objective
                authoritative_request_verbatim = (
                    session_candidate.request_verbatim
                )
                objective_origin = "session"

        if normalized_objective is None and session_candidate is not None:
            normalized_objective = session_candidate.objective
            authoritative_request_verbatim = session_candidate.request_verbatim
            objective_origin = "session"
            if source_session_filter is not None:
                trusted_request_event = session_candidate.goal_event
                trusted_request_document = session_candidate.source_document

        if normalized_objective is None:
            fallback_checkpoint = next(
                (
                    checkpoint
                    for checkpoint in checkpoints
                    if _checkpoint_repo_compatible(
                        checkpoint,
                        requested_repo=requested_repo,
                        current_repository=current_repository,
                        allow_missing_repo=False,
                        allow_missing_branch=False,
                    )
                    and _checkpoint_goal(checkpoint)
                ),
                None,
            )
            if fallback_checkpoint is not None:
                normalized_objective = _checkpoint_goal(fallback_checkpoint)
                authoritative_request_verbatim = (
                    _checkpoint_goal_verbatim(fallback_checkpoint)
                    or normalized_objective
                )
                objective_origin = "checkpoint"

        if normalized_objective is None:
            raise ContinuationError(
                "continuation_objective_not_found",
                "No explicit, selected, or source-backed session objective is available.",
            )
        if authoritative_request_verbatim is None:
            authoritative_request_verbatim = normalized_objective
        authoritative_request_verbatim = (
            extract_user_authored_request(authoritative_request_verbatim)
            or normalized_objective
        )
        expected_lossless_request = (
            requested_checkpoint_recovered_goal
            if (
                requested_checkpoint is not None
                and not objective_is_user_edited
            )
            else session_candidate.request_verbatim
            if (
                source_session_filter is not None
                and session_candidate is not None
                and not objective_is_user_edited
            )
            else None
        )
        if (
            expected_lossless_request is not None
            and hashlib.sha256(
                authoritative_request_verbatim.encode("utf-8")
            ).hexdigest()
            != hashlib.sha256(
                expected_lossless_request.encode("utf-8")
            ).hexdigest()
        ):
            raise ContinuationError(
                "continuation_authoritative_request_mismatch",
                (
                    "The compiled request does not match the lossless request "
                    "bound to the selected checkpoint or source session."
                ),
            )
        authoritative_request = build_authoritative_request(
            authoritative_request_verbatim
        )
        trusted_request_artifacts: tuple[ArtifactReference, ...] = ()
        if (
            trusted_request_event is not None
            and trusted_request_document is not None
        ):
            trusted_descriptors = (
                trusted_request_image_descriptors_from_payload(
                    event_payload(trusted_request_event)
                )
            )
            if (
                (
                    not trusted_descriptors
                    or any(
                        not descriptor.resolved_path
                        for descriptor in trusted_descriptors
                    )
                )
                and trusted_request_event.provider == "codex"
            ):
                source_path = str(
                    metadata_dict(trusted_request_document).get(
                        "source_path"
                    )
                    or ""
                ).strip()
                if source_path:
                    recovered_descriptors = (
                        recover_codex_request_image_descriptors(
                            source_path=source_path,
                            source_sequence_number=(
                                trusted_request_event.sequence_number
                            ),
                            request_verbatim=(
                                trusted_request_event.content
                                or authoritative_request.request_verbatim
                            ),
                            codex_sessions_root=_codex_sessions_root(),
                            artifact_data_dir=settings.data_dir,
                        )
                    )
                    if (
                        not trusted_descriptors
                        or _durable_descriptor_recovery_matches(
                            trusted_descriptors,
                            recovered_descriptors,
                        )
                    ):
                        trusted_descriptors = recovered_descriptors
            trusted_request_artifacts = (
                resolve_trusted_request_image_artifacts(
                    authoritative_request.request_verbatim,
                    trusted_descriptors=trusted_descriptors,
                    allow_local_files=(
                        access_scope.principal_id == "local"
                    ),
                    include_unreferenced_trusted_descriptors=(
                        not objective_is_user_edited
                    ),
                )
            )
        effective_artifacts: tuple[
            ContinuationArtifactInput | ArtifactReference,
            ...,
        ] = (*artifacts, *trusted_request_artifacts)
        resolved_task_mode = (
            task_mode
            if isinstance(task_mode, TaskMode)
            else TaskMode(str(task_mode))
            if task_mode is not None
            else infer_task_mode(authoritative_request.request_verbatim)
        )

        workflow_resolution = await TaskWorkflowService(self.session).resolve(
            workspace_id=workspace_id,
            access_scope=access_scope,
            selected_objective=normalized_objective,
            selected_component_id=(
                current_goal.get("component_id")
                if (
                    current_goal is not None
                    and objective_origin == "current_goal"
                )
                else None
            ),
        )
        execution_objective = workflow_resolution.execution_objective
        execution_differs_from_intent = (
            workflow_resolution.workflow.get("execution_reason")
            == "unfinished_prerequisite"
        )
        execution_context_objective = (
            execution_objective
            if execution_differs_from_intent
            else normalized_objective
        )
        if execution_differs_from_intent:
            intent_session_candidate = session_candidate
            session_candidate = await self._latest_session_task(
                workspace_id=workspace_id,
                access_scope=access_scope,
                requested_repo=requested_repo,
                objective=execution_objective,
                source_session=None,
            )
            if (
                intent_session_candidate is not None
                and session_candidate is None
            ):
                attention.append(_attention(
                    "execution_session_not_found",
                    "info",
                    (
                        "The selected intent has session history, but no compatible "
                        "session was found for its immediate prerequisite."
                    ),
                ))

        captured_checkpoint: WorkCheckpoint | None = None
        if (
            requested_checkpoint_key is None
            and session_candidate is not None
            and _goals_compatible(
                execution_context_objective,
                session_candidate.objective,
            )
        ):
            if await self._session_sources_accessible(
                workspace_id=workspace_id,
                provider=session_candidate.provider,
                session_id=session_candidate.session_id,
                access_scope=access_scope,
            ):
                try:
                    captured_checkpoint = await capture_checkpoint(
                        self.session,
                        workspace_id=workspace_id,
                        provider=session_candidate.provider,
                        session_id=session_candidate.session_id,
                        boundary_event_id=session_candidate.tip_event.id,
                        trigger="continuation",
                    )
                    captured_checkpoint = await get_checkpoint(
                        self.session,
                        captured_checkpoint.id,
                    )
                except ValueError as exc:
                    attention.append(_attention(
                        "checkpoint_capture_failed",
                        "warning",
                        str(exc),
                    ))
            else:
                attention.append(_attention(
                    "checkpoint_sources_not_accessible",
                    "warning",
                    "The session has source revisions outside the caller's evidence scope.",
                ))

        requested_checkpoint_execution_compatible = bool(
            requested_checkpoint is not None
            and (
                not execution_differs_from_intent
                or _goals_compatible(
                    execution_objective,
                    _checkpoint_goal(requested_checkpoint),
                )
            )
        )
        legacy_execution_compatible = bool(
            legacy_restore is not None
            and (
                not execution_differs_from_intent
                or _goals_compatible(
                    execution_objective,
                    _normalize_goal(
                        legacy_restore.get("restore_context", {}).get("objective")
                    ),
                )
            )
        )
        if (
            requested_checkpoint is not None
            and not requested_checkpoint_execution_compatible
        ) or (
            legacy_restore is not None
            and not legacy_execution_compatible
        ):
            attention.append(_attention(
                "checkpoint_excluded_from_execution",
                "warning",
                (
                    "The selected checkpoint belongs to the desired downstream "
                    "task, not the immediate prerequisite, so it was not injected "
                    "as execution context."
                ),
            ))

        checkpoint_candidates = (
            [requested_checkpoint]
            if requested_checkpoint_execution_compatible
            else []
            if legacy_restore is not None
            else [captured_checkpoint, *checkpoints]
        )
        recovered_checkpoint_goals = {
            checkpoint.id: recovered_goal
            for checkpoint in checkpoint_candidates
            if checkpoint is not None
            and (
                recovered_goal := _current_tip_recovered_checkpoint_goal(
                    checkpoint,
                    captured_checkpoint=captured_checkpoint,
                    session_candidate=session_candidate,
                )
            )
            is not None
        }
        if (
            requested_checkpoint is not None
            and requested_checkpoint_recovered_goal is not None
        ):
            recovered_checkpoint_goals[requested_checkpoint.id] = (
                requested_checkpoint_recovered_goal
            )
        compatible = [
            checkpoint
            for checkpoint in checkpoint_candidates
            if checkpoint is not None
            and _checkpoint_repo_compatible(
                checkpoint,
                requested_repo=requested_repo,
                current_repository=current_repository,
                allow_missing_repo=bool(
                    captured_checkpoint is not None
                    and checkpoint.id == captured_checkpoint.id
                    and session_candidate is not None
                ),
                allow_missing_branch=bool(
                    captured_checkpoint is not None
                    and checkpoint.id == captured_checkpoint.id
                    and session_candidate is not None
                ),
            )
            and _goals_compatible(
                execution_context_objective,
                _checkpoint_goal(
                    checkpoint,
                    recovered_goal=recovered_checkpoint_goals.get(
                        checkpoint.id
                    ),
                ),
            )
        ]
        selected_checkpoint = max(
            {checkpoint.id: checkpoint for checkpoint in compatible}.values(),
            key=_checkpoint_order_key,
            default=None,
        )
        if (
            selected_checkpoint is None
            and checkpoints
            and legacy_restore is None
        ):
            attention.append(_attention(
                "no_compatible_checkpoint",
                "warning",
                "Available checkpoints belong to a different goal or repository and were excluded.",
            ))

        verification_data = None
        checkpoint_data = None
        freshness = {
            "status": "not_applicable",
            "reason": "No compatible checkpoint was selected.",
            "current": current_repository,
        }
        restored_checkpoint = None
        source_session = None
        supporting_context: list[dict[str, str]] = []
        if selected_checkpoint is not None:
            verification = await verify_checkpoint(
                self.session,
                checkpoint_id=selected_checkpoint.id,
                execute_commands=False,
            )
            verification_data = _verification_to_dict(verification)
            freshness = await compare_checkpoint_repository(selected_checkpoint)
            selected_checkpoint = (
                await get_checkpoint(self.session, selected_checkpoint.id)
                or selected_checkpoint
            )
            checkpoint_data = checkpoint_to_dict(
                selected_checkpoint,
                recovered_goal=recovered_checkpoint_goals.get(
                    selected_checkpoint.id
                ),
                filter_presentation_noise=True,
            )
            checkpoint_source = selected_checkpoint.source_document
            checkpoint_source_title = (
                str(metadata_dict(checkpoint_source).get("title") or "").strip()
                if checkpoint_source is not None
                else ""
            )
            source_session = {
                "provider": checkpoint_data["provider"],
                "session_id": checkpoint_data["session_id"],
                "source_document_id": checkpoint_data["source_document_id"],
                **({"title": checkpoint_source_title} if checkpoint_source_title else {}),
            }
            restored_checkpoint = _compiler_checkpoint_adapter(
                selected_checkpoint,
                checkpoint_data,
            )
            supporting_context = await resolve_session_handoff_supporting_context(
                self.session,
                selected_checkpoint,
                request_verbatim=authoritative_request.request_verbatim,
                access_scope=access_scope,
            )
            if (
                session_request_requires_materialized_context(
                    authoritative_request.request_verbatim
                )
                and not supporting_context
            ):
                attention.append(_attention(
                    "referenced_context_unresolved",
                    "error",
                    (
                        "The authoritative request depends on referenced session "
                        "material that could not be embedded into Project Context."
                    ),
                ))
            attention.append(_attention(
                "agent_progress_is_reported",
                "info",
                "Session progress and decisions remain agent-reported unless repository or command evidence verifies them.",
            ))
            verification_status = str(verification_data.get("status") or "partial")
            if verification_status != "verified":
                attention.append(_attention(
                    f"checkpoint_{verification_status}",
                    "error" if verification_status == "failed" else "warning",
                    f"Checkpoint verification status is {verification_status}.",
                ))
            if freshness.get("status") == "changed":
                attention.append(_attention(
                    "repository_changed",
                    "warning",
                    "The current repository differs from the checkpoint snapshot.",
                ))
        elif (
            legacy_restore is not None
            and legacy_document is not None
            and legacy_execution_compatible
        ):
            legacy_metadata = metadata_dict(legacy_document)
            legacy_provider, legacy_session_id = session_reference(
                legacy_document,
                metadata=legacy_metadata,
            )
            restored_checkpoint = legacy_restore
            source_session = {
                "provider": legacy_provider,
                "session_id": legacy_session_id,
                "source_document_id": str(legacy_document.id),
                **(
                    {"title": str(metadata.get("title") or "").strip()}
                    if str(metadata.get("title") or "").strip()
                    else {}
                ),
            }
            freshness = {
                "status": "unavailable",
                "reason": (
                    "This provider-compaction checkpoint predates a durable "
                    "repository fingerprint and requires review."
                ),
                "current": current_repository,
            }
            attention.append(_attention(
                "legacy_checkpoint_unverified",
                "warning",
                "The exact provider-compaction checkpoint is restored as reported context without a durable repository snapshot.",
            ))
        elif session_candidate is not None:
            session_title = str(
                metadata_dict(session_candidate.source_document).get("title")
                or ""
            ).strip()
            source_session = {
                "provider": session_candidate.provider,
                "session_id": session_candidate.session_id,
                "source_document_id": str(session_candidate.source_document.id),
                **({"title": session_title} if session_title else {}),
            }

        effective_repo_path = (
            requested_repo
            or (selected_checkpoint.repo_root if selected_checkpoint else None)
            or (
                legacy_repo_path
                if legacy_document is not None
                else None
            )
            or _candidate_repo_path(session_candidate)
        )
        if current_repository is None and effective_repo_path:
            current_repository, current_repo_error = await _current_repository(
                effective_repo_path
            )
        if current_repo_error:
            attention.append(_attention(
                "repository_freshness_unavailable",
                "warning",
                current_repo_error,
            ))

        repository_compilation_issues: list[str] = []
        if effective_repo_path:
            repository_at_prepare_start = current_repository
            compilation_repository, compilation_repo_error = (
                await _current_repository(effective_repo_path)
            )
            if compilation_repository is not None:
                if (
                    repository_at_prepare_start is not None
                    and not _repository_snapshots_match(
                        repository_at_prepare_start,
                        compilation_repository,
                    )
                ):
                    repository_compilation_issues.append(
                        "repository_changed_before_compilation"
                    )
                current_repository = compilation_repository
                current_repo_error = None
                freshness = {
                    **freshness,
                    "current": current_repository,
                }
            elif repository_at_prepare_start is not None:
                repository_compilation_issues.append(
                    "repository_unavailable_before_compilation"
                )
                current_repo_error = (
                    compilation_repo_error
                    or "The repository snapshot became unavailable during preparation."
                )

        selected_checkpoint_key = (
            str(selected_checkpoint.id)
            if selected_checkpoint is not None
            else requested_checkpoint_key
            if legacy_restore is not None and legacy_execution_compatible
            else None
        )
        task_id = _task_identity(
            workspace_id=workspace_id,
            objective=normalized_objective,
            current_goal=current_goal,
            repo_root=effective_repo_path,
            branch=(
                current_repository.get("branch")
                if current_repository
                else selected_checkpoint.branch
                if selected_checkpoint is not None
                else legacy_branch
                if legacy_document is not None
                else None
            ),
        )
        task_identity = _task_identity_metadata(
            task_id=task_id,
            workspace_id=workspace_id,
            selected_objective=normalized_objective,
            authoritative_request_sha256=authoritative_request.request_sha256,
            current_goal=current_goal,
            selected_component_id=workflow_resolution.selected_component_id,
        )
        continuation_metadata = {
            "task_id": task_id,
            "task_identity": task_identity,
            "selected_objective": normalized_objective,
            "execution_objective": execution_objective,
            "task_mode": resolved_task_mode.value,
            "request_sha256": authoritative_request.request_sha256,
            "checkpoint_id": selected_checkpoint_key,
            "source_document_id": (
                source_session.get("source_document_id")
                if source_session
                else None
            ),
            "provider": source_session.get("provider") if source_session else None,
            "session_id": source_session.get("session_id") if source_session else None,
            "verification_status": (
                verification_data.get("status") if verification_data else None
            ),
            "checkpoint_fingerprint": (
                selected_checkpoint.worktree_fingerprint
                if selected_checkpoint is not None
                else None
            ),
            "current_repo_fingerprint": (
                current_repository.get("status_fingerprint")
                if current_repository
                else None
            ),
            "artifacts": [
                artifact.model_dump(mode="json")
                for artifact in effective_artifacts
            ],
            "workflow": workflow_resolution.workflow,
        }
        pack = await ContextCompiler(self.session).compile_context_pack(
            execution_objective,
            workspace_id=workspace_id,
            repo_path=effective_repo_path,
            target_model=target_model,
            token_budget=token_budget,
            persist=True,
            restored_checkpoint=restored_checkpoint,
            access_scope=access_scope,
            continuation=continuation_metadata,
            request_verbatim=authoritative_request.request_verbatim,
            task_mode=resolved_task_mode,
            authoritative_repository=current_repository,
        )
        if not pack.context_pack_id:
            raise ContinuationError(
                "continuation_persistence_failed",
                "The context compiler returned no durable context pack.",
                status_code=500,
            )
        compiled_execution = (
            await compile_and_persist_continuation_execution(
                self.session,
                access_scope=access_scope,
                workspace_id=workspace_id,
                context_pack_id=pack.context_pack_id,
                request_verbatim=authoritative_request.request_verbatim,
                task_mode=resolved_task_mode,
                repository=current_repository,
                restored_checkpoint=restored_checkpoint,
                context_manifest=pack.manifest,
                task_identity=task_identity,
                selected_task_lifecycle=(
                    workflow_resolution.workflow["selected_intent"][
                        "lifecycle"
                    ]
                ),
                checkpoint_id=selected_checkpoint_key,
                execution_focus=execution_objective,
                artifacts=effective_artifacts,
                supporting_context=supporting_context,
            )
        )
        if current_repository is not None:
            manifest_uses_snapshot = _manifest_uses_repository_snapshot(
                pack.manifest,
                current_repository,
            )
            repository_hash_mismatches: tuple[str, ...] = ()
            if not manifest_uses_snapshot:
                repository_compilation_issues.append(
                    "context_pack_snapshot_mismatch"
                )
            else:
                repository_hash_mismatches = (
                    await _manifest_repository_hash_mismatches(
                        pack.manifest,
                        current_repository,
                    )
                )
            if manifest_uses_snapshot and repository_hash_mismatches:
                repository_compilation_issues.append(
                    "context_pack_file_hash_mismatch:"
                    + ",".join(repository_hash_mismatches[:4])
                )
            if not _contract_uses_repository_snapshot(
                compiled_execution.contract.repository.model_dump(
                    mode="json"
                ),
                current_repository,
            ):
                repository_compilation_issues.append(
                    "execution_contract_snapshot_mismatch"
                )
            repository_after_compilation, final_repo_error = (
                await _current_repository(effective_repo_path)
            )
            if (
                repository_after_compilation is None
                or not _repository_snapshots_match(
                    current_repository,
                    repository_after_compilation,
                )
            ):
                repository_compilation_issues.append(
                    "repository_changed_after_compilation"
                )
                current_repo_error = (
                    final_repo_error
                    or "The repository changed while continuation artifacts were compiled."
                )
        project_context_content = render_continuation_staging_context(
            compiled_execution.contract
        )
        execution_quality = evaluate_continuation_quality(
            compiled_execution.contract,
            prompt_markdown=compiled_execution.prompt_markdown,
            project_context_markdown=project_context_content,
            expected_contract_sha256=(
                compiled_execution.execution.contract_sha256
            ),
            expected_prompt_sha256=(
                compiled_execution.execution.prompt_sha256
            ),
        )
        if repository_compilation_issues:
            execution_quality = ContinuationQualityReport(
                launchable=False,
                issues=(
                    *execution_quality.issues,
                    ContinuationQualityIssue(
                        code=(
                            "project_context_repository_changed_during_prepare"
                        ),
                        severity="blocking",
                        message=(
                            "The repository changed during continuation "
                            "compilation, so the ContextPack and execution "
                            "contract cannot be trusted as one current snapshot. "
                            "Prepare Project Context again. Detected: "
                            + ", ".join(repository_compilation_issues)
                            + "."
                        ),
                    ),
                ),
                contract_sha256=execution_quality.contract_sha256,
                prompt_sha256=execution_quality.prompt_sha256,
            )
        project_context = {
            "schema_version": STAGING_CONTEXT_SCHEMA_VERSION,
            "scope": "project",
            "content": project_context_content,
            "sha256": hashlib.sha256(
                project_context_content.encode("utf-8")
            ).hexdigest(),
            "estimated_tokens": max(
                1,
                (len(project_context_content) + 3) // 4,
            ),
        }
        quality_issues = [
            {
                **issue.to_dict(),
                "blocks_current_execution": issue.severity == "blocking",
            }
            for issue in execution_quality.issues
        ]
        # A handoff with a structurally invalid contract, an unresolved
        # required artifact, or an incomplete repository baseline is not a
        # trustworthy Project Context merely because its Markdown rendered.
        # Surface every blocking contract issue to the copy path. Warnings
        # remain automatic-execution concerns unless they are specifically
        # emitted by the Project Context renderer checks.
        project_context_quality_issues = [
            {
                **issue,
                "blocks_copy": (
                    (
                        issue["blocks_current_execution"]
                        and str(issue.get("code") or "")
                        not in _EXECUTION_ONLY_QUALITY_CODES
                        and str(issue.get("code") or "")
                        not in _PROJECT_CONTEXT_COPY_NON_BLOCKING_CODES
                    )
                    or str(issue.get("code") or "").startswith(
                        "project_context_copy_"
                    )
                ),
            }
            for issue in quality_issues
            if (
                issue["blocks_current_execution"]
                or str(issue.get("code") or "").startswith(
                    "project_context_copy_"
                )
                or str(issue.get("code") or "") in {
                    "project_context_untrusted",
                    "project_context_conversation_dump",
                    "project_context_missing_from_prompt",
                }
            )
        ]
        project_context["quality_issues"] = project_context_quality_issues
        project_context["copy_ready"] = not any(
            issue["blocks_copy"]
            for issue in project_context_quality_issues
        )
        quality_status = (
            "blocked"
            if not execution_quality.launchable
            else "review_required"
            if quality_issues
            else "ready"
        )
        quality_report = {
            **execution_quality.to_dict(),
            "status": quality_status,
            "blocking_issues": [
                issue
                for issue in quality_issues
                if issue["blocks_current_execution"]
            ],
        }

        readiness_status = _readiness_status(
            verification=verification_data,
            freshness=freshness,
            health_score=float(pack.health_score),
        )
        checkpoint_issues = _checkpoint_blocking_issues(
            checkpoint_data,
            workflow=workflow_resolution.workflow,
        )
        existing_project_issue_codes = {
            str(issue.get("code") or "")
            for issue in project_context_quality_issues
        }
        for issue in (
            *workflow_resolution.blocking_issues,
            *checkpoint_issues,
        ):
            if not issue.get("blocks_current_execution", True):
                continue
            code = str(issue.get("code") or "")
            if code in existing_project_issue_codes:
                continue
            existing_project_issue_codes.add(code)
            project_context_quality_issues.append({
                **issue,
                "blocks_copy": (
                    code not in _PROJECT_CONTEXT_COPY_NON_BLOCKING_CODES
                ),
            })
        project_context["quality_issues"] = project_context_quality_issues
        project_context["copy_ready"] = not any(
            issue["blocks_copy"]
            for issue in project_context_quality_issues
        )
        readiness_quality_issues = [
            issue
            for issue in quality_report["blocking_issues"]
            if str(issue.get("code") or "")
            not in _EXECUTION_ONLY_QUALITY_CODES
        ]
        readiness_issues = [
            *workflow_resolution.blocking_issues,
            *checkpoint_issues,
            *readiness_quality_issues,
        ]
        blocking_issues = [
            *workflow_resolution.blocking_issues,
            *checkpoint_issues,
            *quality_issues,
        ]
        handoff_blocking_issues = [
            issue
            for issue in blocking_issues
            if issue.get("blocks_current_execution", True)
            and str(issue.get("code") or "")
            not in _EXECUTION_ONLY_QUALITY_CODES
        ]
        if handoff_blocking_issues:
            readiness_status = "blocked"
        elif quality_status == "review_required" and readiness_status == "ready":
            readiness_status = "review_required"
        for issue in blocking_issues:
            execution_only = (
                str(issue.get("code") or "")
                in _EXECUTION_ONLY_QUALITY_CODES
            )
            attention.append(_attention(
                str(issue.get("code") or "continuation_blocked"),
                (
                    "error"
                    if (
                        issue.get("blocks_current_execution", True)
                        and not execution_only
                    )
                    else "warning"
                ),
                str(issue.get("message") or "Continuation is blocked."),
            ))
        reported_checkpoint_status = (
            str(checkpoint_data.get("continuation_status") or "")
            if checkpoint_data
            else ""
        )
        effective_checkpoint_status = reported_checkpoint_status
        if (
            reported_checkpoint_status == "blocked"
            and not any(
                issue.get("blocks_current_execution", True)
                for issue in checkpoint_issues
            )
        ):
            # Historical command failures and provider authentication reports
            # are context for the next run, not live launch authority.
            effective_checkpoint_status = "review_required"
        checkpoint_summary = (
            {
                "id": checkpoint_data["id"],
                "schema_version": checkpoint_data["schema_version"],
                "capture_status": checkpoint_data["capture_status"],
                "continuation_status": effective_checkpoint_status,
                "reported_continuation_status": reported_checkpoint_status,
                "goal": _checkpoint_data_goal(checkpoint_data),
                "boundary": checkpoint_data["boundary"],
                "repo": checkpoint_data["repo"],
                "sections": {
                    "blockers": _checkpoint_section_summary(
                        checkpoint_data,
                        "blockers",
                    ),
                },
            }
            if checkpoint_data
            else legacy_checkpoint_summary
            if legacy_execution_compatible
            else None
        )
        return ContinuationResult(
            objective=execution_objective,
            task={
                "id": task_id,
                "identity": task_identity,
                "title": execution_objective,
                "origin": objective_origin,
                "workspace_goal_id": (
                    current_goal.get("id") if current_goal is not None else None
                ),
                "selected_intent": workflow_resolution.workflow[
                    "selected_intent"
                ],
                "execution_task": workflow_resolution.workflow[
                    "execution_task"
                ],
                "workflow": workflow_resolution.workflow,
            },
            source_session=source_session,
            checkpoint=checkpoint_summary,
            verification=verification_data,
            repository={
                "path": effective_repo_path,
                "current": current_repository,
                "freshness": freshness,
            },
            context_pack_id=str(pack.context_pack_id),
            continuation_execution_id=str(
                compiled_execution.execution.id
            ),
            project_context=project_context,
            execution_prompt=compiled_execution.prompt_markdown,
            execution_contract=compiled_execution.contract.model_dump(
                mode="json"
            ),
            quality_report=quality_report,
            markdown=pack.markdown,
            manifest=pack.manifest,
            health_score=float(pack.health_score),
            readiness={
                "status": readiness_status,
                "score": float(pack.health_score),
                "blocking_issues": readiness_issues,
                "affected_tasks": workflow_resolution.workflow[
                    "affected_tasks"
                ],
            },
            attention=attention,
            sync=sync_summary,
        )
    async def _require_workspace(
        self,
        workspace_id: UUID,
        access_scope: AccessScope,
    ) -> Workspace:
        if not access_scope.allows_workspace(workspace_id):
            raise ContinuationError(
                "workspace_not_found",
                "Workspace not found",
                status_code=404,
            )
        workspace = await self.session.get(Workspace, workspace_id)
        if workspace is None:
            raise ContinuationError(
                "workspace_not_found",
                "Workspace not found",
                status_code=404,
            )
        return workspace

    async def _accessible_checkpoint(
        self,
        *,
        workspace_id: UUID,
        checkpoint_id: UUID,
        access_scope: AccessScope,
    ) -> WorkCheckpoint:
        checkpoint = await get_checkpoint(self.session, checkpoint_id)
        if checkpoint is None or checkpoint.workspace_id != workspace_id:
            raise ContinuationError(
                "checkpoint_not_found",
                "The requested checkpoint is not available in this workspace.",
                status_code=404,
            )
        source_ids = {checkpoint.source_document_id}
        source_ids.update(
            evidence.source_document_id
            for item in checkpoint.items
            for evidence in item.evidence
            if evidence.source_document_id is not None
        )
        visible_source_ids = set(await self.session.scalars(
            select(SourceDocument.id).where(
                SourceDocument.id.in_(source_ids),
                source_access_predicate(
                    access_scope,
                    workspace_id=workspace_id,
                ),
            )
        ))
        if visible_source_ids != source_ids:
            raise ContinuationError(
                "checkpoint_not_found",
                "The requested checkpoint is not available in this workspace.",
                status_code=404,
            )
        return checkpoint

    async def _accessible_source_document(
        self,
        *,
        workspace_id: UUID,
        source_document_id: UUID,
        access_scope: AccessScope,
    ) -> SourceDocument:
        document = await self.session.scalar(
            select(SourceDocument).where(
                SourceDocument.id == source_document_id,
                SourceDocument.workspace_id == workspace_id,
                source_access_predicate(
                    access_scope,
                    workspace_id=workspace_id,
                ),
            )
        )
        if document is None:
            raise ContinuationError(
                "checkpoint_not_found",
                "The requested checkpoint source is not available in this workspace.",
                status_code=404,
            )
        return document

    async def _trusted_checkpoint_request_event(
        self,
        *,
        checkpoint: WorkCheckpoint,
        request_verbatim: str,
        access_scope: AccessScope,
    ) -> tuple[SessionEvent | None, SourceDocument | None]:
        """Find the exact source event that authorized a checkpoint request."""

        boundary = await self.session.get(
            SessionEvent,
            checkpoint.boundary_event_id,
        )
        boundary_sequence = (
            boundary.sequence_number if boundary is not None else None
        )
        conditions = [
            SessionEvent.workspace_id == checkpoint.workspace_id,
            SessionEvent.provider.in_(
                session_provider_values(checkpoint.provider)
            ),
            SessionEvent.session_id == checkpoint.session_id,
            SessionEvent.event_type == "user_request",
            source_access_predicate(
                access_scope,
                workspace_id=checkpoint.workspace_id,
            ),
        ]
        if boundary_sequence is not None:
            conditions.append(
                SessionEvent.sequence_number <= boundary_sequence
            )
        events = list(await self.session.scalars(
            select(SessionEvent)
            .join(
                SourceDocument,
                SessionEvent.source_document_id == SourceDocument.id,
            )
            .where(*conditions)
            .order_by(
                SessionEvent.sequence_number.desc(),
                SessionEvent.id.desc(),
            )
            .limit(_MAX_REQUEST_EVENTS)
        ))
        expected_sha256 = hashlib.sha256(
            request_verbatim.encode("utf-8")
        ).hexdigest()
        for event in events:
            document = await self.session.get(
                SourceDocument,
                event.source_document_id,
            )
            if document is None:
                continue
            candidate = _event_request_verbatim(event)
            if candidate is not None and hashlib.sha256(
                candidate.encode("utf-8")
            ).hexdigest() == expected_sha256:
                return event, document
            recognized, recovered = (
                recover_truncated_session_request_from_source(
                    document,
                    event_content=event.content,
                    event_type=event.event_type,
                )
            )
            if (
                recognized
                and recovered is not None
                and hashlib.sha256(
                    recovered.encode("utf-8")
                ).hexdigest() == expected_sha256
            ):
                return event, document
        return None, None

    async def _latest_session_task(
        self,
        *,
        workspace_id: UUID,
        access_scope: AccessScope,
        requested_repo: str | None,
        objective: str | None,
        source_session: tuple[str, str] | None = None,
    ) -> _SessionTaskCandidate | None:
        documents = list(await self.session.scalars(
            select(SourceDocument).where(
                SourceDocument.workspace_id == workspace_id,
                SourceDocument.source_type == "agent_session",
                source_access_predicate(access_scope, workspace_id=workspace_id),
            )
        ))
        documents_by_id = {document.id: document for document in documents}
        current, _ = current_source_documents(documents)
        if requested_repo:
            current = [
                document
                for document in current
                if _document_matches_repo(document, requested_repo)
            ]
        else:
            current = await scoped_session_documents(
                self.session,
                workspace_id,
                current,
            )
        if source_session is None:
            current = [
                document
                for document in current
                if str(
                    metadata_dict(document).get("thread_source") or ""
                ).strip().casefold() != "subagent"
            ]
        documents_by_session = {
            normalize_session_key(*session_reference(document)): document
            for document in current
        }
        documents_by_session.pop(None, None)
        if (
            source_session is not None
            and source_session not in documents_by_session
        ):
            return None
        if not documents_by_session:
            return None

        event_conditions = [
            SessionEvent.workspace_id == workspace_id,
            SessionEvent.event_type.in_(("user_request", "runtime_instruction")),
            source_access_predicate(access_scope, workspace_id=workspace_id),
        ]
        if source_session is not None:
            event_conditions.extend((
                SessionEvent.provider.in_(
                    session_provider_values(source_session[0])
                ),
                SessionEvent.session_id == source_session[1],
            ))
        events = list(await self.session.scalars(
            select(SessionEvent)
            .join(
                SourceDocument,
                SessionEvent.source_document_id == SourceDocument.id,
            )
            .where(*event_conditions)
            .order_by(
                SessionEvent.occurred_at.desc().nulls_last(),
                SessionEvent.created_at.desc(),
                SessionEvent.sequence_number.desc(),
                SessionEvent.id.desc(),
            )
            .limit(_MAX_REQUEST_EVENTS)
        ))
        latest_by_session: dict[
            tuple[str, str],
            tuple[SessionEvent, str, str, bool],
        ] = {}
        sessions_with_unrecoverable_truncation: set[tuple[str, str]] = set()
        for event in events:
            key = normalize_session_key(event.provider, event.session_id)
            if (
                key not in documents_by_session
                or key in latest_by_session
                or key in sessions_with_unrecoverable_truncation
            ):
                continue
            recovered_request: str | None = None
            was_truncated = False
            if event.event_type == "user_request":
                exact_source = documents_by_id.get(event.source_document_id)
                if exact_source is None:
                    # The event query is access-filtered through SourceDocument,
                    # so a missing exact revision is inconsistent and must not
                    # be replaced with a different session document.
                    sessions_with_unrecoverable_truncation.add(key)
                    continue
                (
                    was_truncated,
                    recovered_request,
                ) = recover_truncated_session_request_from_source(
                    exact_source,
                    event_content=event.content,
                    event_type=event.event_type,
                )
                if was_truncated and recovered_request is None:
                    sessions_with_unrecoverable_truncation.add(key)
                    continue
            goal = (
                _normalize_goal(
                    normalize_substantive_user_request(recovered_request)
                )
                if recovered_request is not None
                else _event_goal(event)
            )
            if not goal:
                continue
            if (
                source_session is not None
                and objective
                and not _goals_compatible(objective, goal)
            ):
                continue
            latest_by_session[key] = (
                event,
                goal,
                recovered_request
                or _event_request_verbatim(event)
                or goal,
                was_truncated,
            )

        for key, (
            goal_event,
            goal,
            request_verbatim,
            request_recovered,
        ) in latest_by_session.items():
            if objective and not _goals_compatible(objective, goal):
                continue
            tip = await self.session.scalar(
                select(SessionEvent)
                .join(
                    SourceDocument,
                    SessionEvent.source_document_id == SourceDocument.id,
                )
                .where(
                    SessionEvent.workspace_id == workspace_id,
                    SessionEvent.provider.in_(session_provider_values(key[0])),
                    SessionEvent.session_id == key[1],
                    source_access_predicate(access_scope, workspace_id=workspace_id),
                )
                .order_by(SessionEvent.sequence_number.desc(), SessionEvent.id.desc())
                .limit(1)
            )
            if tip is None:
                continue
            return _SessionTaskCandidate(
                provider=tip.provider,
                session_id=tip.session_id,
                source_document=documents_by_session[key],
                goal_event=goal_event,
                tip_event=tip,
                objective=goal,
                request_verbatim=request_verbatim,
                request_recovered=request_recovered,
            )
        return None

    async def _session_sources_accessible(
        self,
        *,
        workspace_id: UUID,
        provider: str,
        session_id: str,
        access_scope: AccessScope,
    ) -> bool:
        source_ids = set(await self.session.scalars(
            select(SessionEvent.source_document_id).where(
                SessionEvent.workspace_id == workspace_id,
                SessionEvent.provider.in_(session_provider_values(provider)),
                SessionEvent.session_id == session_id,
            ).distinct()
        ))
        if not source_ids:
            return False
        visible = set(await self.session.scalars(
            select(SourceDocument.id).where(
                SourceDocument.id.in_(source_ids),
                source_access_predicate(access_scope, workspace_id=workspace_id),
            )
        ))
        return visible == source_ids


def _continuation_trace_result(
    result: ContinuationResult,
) -> dict[str, Any]:
    manifest = result.manifest if isinstance(result.manifest, dict) else {}
    rendering = (
        manifest.get("rendering")
        if isinstance(manifest.get("rendering"), dict)
        else {}
    )
    source_session = (
        result.source_session
        if isinstance(result.source_session, dict)
        else {}
    )
    checkpoint = (
        result.checkpoint
        if isinstance(result.checkpoint, dict)
        else {}
    )
    contract = (
        result.execution_contract
        if isinstance(result.execution_contract, dict)
        else {}
    )
    task = contract.get("task") if isinstance(contract.get("task"), dict) else {}
    quality = (
        result.quality_report
        if isinstance(result.quality_report, dict)
        else {}
    )
    return {
        "daemonstate.context_pack.id": result.context_pack_id,
        "daemonstate.context_pack.sha256": rendering.get("markdown_sha256"),
        "daemonstate.continuation.execution.id": result.continuation_execution_id,
        "daemonstate.checkpoint.id": checkpoint.get("id"),
        "daemonstate.source.provider": source_session.get("provider"),
        "daemonstate.session.id": source_session.get("session_id"),
        "daemonstate.request.sha256": task.get("request_sha256"),
        "daemonstate.task.mode": contract.get("task_mode"),
        "daemonstate.status": quality.get("status"),
    }


def _event_goal(event: SessionEvent) -> str | None:
    if event.event_type == "user_request":
        return _normalize_goal(normalize_substantive_user_request(event.content))
    if event.event_type == "runtime_instruction" and event.role == "user":
        return _normalize_goal(extract_delegated_user_request(event.content))
    return None


def _event_request_verbatim(event: SessionEvent) -> str | None:
    if event.event_type == "user_request":
        return extract_user_authored_request(event.content)
    if event.event_type == "runtime_instruction" and event.role == "user":
        return extract_delegated_user_request(event.content)
    return None


def _current_tip_recovered_checkpoint_goal(
    checkpoint: WorkCheckpoint,
    *,
    captured_checkpoint: WorkCheckpoint | None,
    session_candidate: _SessionTaskCandidate | None,
) -> str | None:
    """Bind a recovered request only to its exact current-tip checkpoint."""

    if (
        captured_checkpoint is None
        or session_candidate is None
        or not session_candidate.request_recovered
        or checkpoint.id != captured_checkpoint.id
        or checkpoint.boundary_event_id != session_candidate.tip_event.id
        or checkpoint.source_document_id
        != session_candidate.tip_event.source_document_id
        or normalize_session_key(checkpoint.provider, checkpoint.session_id)
        != normalize_session_key(
            session_candidate.provider,
            session_candidate.session_id,
        )
    ):
        return None
    return session_candidate.request_verbatim


def _checkpoint_goal(
    checkpoint: WorkCheckpoint | None,
    *,
    recovered_goal: str | None = None,
) -> str | None:
    if checkpoint is None:
        return None
    data = checkpoint_to_dict(
        checkpoint,
        recovered_goal=recovered_goal,
    )
    return _checkpoint_data_goal(data)


def _checkpoint_data_goal(data: dict[str, Any]) -> str | None:
    goals = data.get("sections", {}).get("goal") or []
    if len(goals) != 1:
        return None
    return _normalize_goal(
        normalize_substantive_user_request(goals[0].get("statement"))
    )


def _checkpoint_goal_verbatim(
    checkpoint: WorkCheckpoint | None,
) -> str | None:
    if checkpoint is None:
        return None
    data = checkpoint_to_dict(checkpoint)
    goals = data.get("sections", {}).get("goal") or []
    if len(goals) != 1:
        return None
    payload = (
        goals[0].get("payload")
        if isinstance(goals[0].get("payload"), dict)
        else {}
    )
    value = str(
        payload.get("request_verbatim")
        or goals[0].get("statement")
        or ""
    )
    expected_sha256 = str(payload.get("request_sha256") or "").strip()
    if expected_sha256 and hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest() != expected_sha256:
        return None
    return extract_user_authored_request(value)


def _checkpoint_repo_compatible(
    checkpoint: WorkCheckpoint,
    *,
    requested_repo: str | None,
    current_repository: dict[str, Any] | None,
    allow_missing_repo: bool,
    allow_missing_branch: bool,
) -> bool:
    if requested_repo:
        checkpoint_root = normalize_local_path(checkpoint.repo_root)
        if not checkpoint_root:
            if not allow_missing_repo:
                return False
        elif checkpoint_root != normalize_local_path(requested_repo):
            return False
    current_branch = (current_repository or {}).get("branch")
    if current_branch:
        if not checkpoint.branch:
            if not allow_missing_branch:
                return False
        elif checkpoint.branch != current_branch:
            return False
    return True


def _checkpoint_order_key(checkpoint: WorkCheckpoint) -> tuple[Any, int, str]:
    boundary = checkpoint.__dict__.get("boundary_event")
    occurred_at = getattr(boundary, "occurred_at", None) or checkpoint.created_at
    sequence = int(getattr(boundary, "sequence_number", 0) or 0)
    return occurred_at, sequence, str(checkpoint.id)


def _compiler_checkpoint_adapter(
    checkpoint: WorkCheckpoint,
    data: dict[str, Any],
) -> dict[str, Any]:
    source = checkpoint.__dict__.get("source_document")
    projected_goal = _checkpoint_data_goal(data)
    files = [
        str(item.get("statement") or "").strip()
        for item in data.get("sections", {}).get("relevant_files") or []
        if str(item.get("statement") or "").strip()
    ]
    return {
        "checkpoint": data,
        "restore_context": {
            "source_document_id": data.get("source_document_id"),
            "session_title": projected_goal or "Recovered task",
            "harness": data.get("provider"),
            "sections": data.get("sections") or {},
            "referenced_files": files,
            "agent_reported_state": projected_goal,
            "objective": projected_goal,
            "source_revision_number": getattr(source, "revision_number", None),
            "source_content_sha256": getattr(source, "content_sha256", None),
        },
    }


def _verification_to_dict(value: Any) -> dict[str, Any]:
    try:
        results = json.loads(value.results_json or "{}")
    except (TypeError, json.JSONDecodeError):
        results = {}
    return {
        "id": str(value.id),
        "status": value.status,
        "policy_version": value.policy_version,
        "worktree_fingerprint": value.worktree_fingerprint,
        "verified_at": value.verified_at,
        "results": results,
    }


async def _current_repository(
    repo_path: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    if not repo_path:
        return None, None
    try:
        snapshot = await capture_repository_snapshot(repo_path)
    except (OSError, ValueError) as exc:
        return None, str(exc)
    return snapshot.to_dict(), None


def _repository_snapshot_identity(
    repository: dict[str, Any],
) -> tuple[str, str | None, str | None, str, bool] | None:
    current = (
        repository.get("current")
        if isinstance(repository.get("current"), dict)
        else repository
    )
    root = str(current.get("root") or current.get("path") or "").strip()
    fingerprint = str(current.get("status_fingerprint") or "").strip()
    if not root or not fingerprint:
        return None
    return (
        str(Path(root).resolve()),
        str(current.get("branch") or "").strip() or None,
        str(current.get("head_commit") or "").strip() or None,
        fingerprint,
        bool(current.get("status_truncated", False)),
    )


def _repository_snapshots_match(
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:
    left_identity = _repository_snapshot_identity(left)
    return (
        left_identity is not None
        and left_identity == _repository_snapshot_identity(right)
    )


def _manifest_uses_repository_snapshot(
    manifest: dict[str, Any],
    repository: dict[str, Any],
) -> bool:
    repo_state = (
        manifest.get("repo_state")
        if isinstance(manifest.get("repo_state"), dict)
        else {}
    )
    bound = (
        repo_state.get("authoritative_snapshot")
        if isinstance(repo_state.get("authoritative_snapshot"), dict)
        else {}
    )
    if not _repository_snapshots_match(bound, repository):
        return False
    expected = _repository_snapshot_identity(repository)
    observed = _repository_snapshot_identity({
        "root": repo_state.get("repo_path"),
        "branch": repo_state.get("branch"),
        "head_commit": repo_state.get("head_commit"),
        "status_fingerprint": repo_state.get("status_fingerprint"),
        "status_truncated": repo_state.get("status_truncated"),
    })
    return expected is not None and observed == expected


def _contract_uses_repository_snapshot(
    contract_repository: dict[str, Any],
    repository: dict[str, Any],
) -> bool:
    return _repository_snapshots_match(
        {
            "root": contract_repository.get("root"),
            "branch": contract_repository.get("branch"),
            "head_commit": contract_repository.get("head_commit"),
            "status_fingerprint": contract_repository.get(
                "status_fingerprint"
            ),
            "status_truncated": contract_repository.get(
                "status_truncated"
            ),
        },
        repository,
    )


async def _manifest_repository_hash_mismatches(
    manifest: dict[str, Any],
    repository: dict[str, Any],
) -> tuple[str, ...]:
    """Reject a compiler scan that observed transient file contents.

    A dirty-tree fingerprint can return to its original value after a file is
    changed and restored. Hash-bearing read-plan references therefore also need
    to match current bytes before Project Context can be copied.
    """

    identity = _repository_snapshot_identity(repository)
    if identity is None:
        return ("repository_identity_unavailable",)
    root = Path(identity[0])
    expected_by_path: dict[str, str] = {}

    def collect(items: Any) -> bool:
        if not isinstance(items, list):
            return True
        for item in items:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            digest = str(item.get("sha256") or "").strip().lower()
            if not path or not digest:
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                return False
            previous = expected_by_path.setdefault(path, digest)
            if previous != digest:
                return False
        return True

    repo_state = (
        manifest.get("repo_state")
        if isinstance(manifest.get("repo_state"), dict)
        else {}
    )
    if not collect(repo_state.get("relevant_files")):
        return ("invalid_or_conflicting_repo_state_hash",)
    for item in manifest.get("selected_context") or []:
        if (
            isinstance(item, dict)
            and item.get("inclusion_reason") == "goal_file_match"
            and not collect(item.get("file_refs"))
        ):
            return ("invalid_or_conflicting_selected_context_hash",)
    affected_code = (
        manifest.get("affected_code")
        if isinstance(manifest.get("affected_code"), dict)
        else {}
    )
    if not collect(affected_code.get("files")):
        return ("invalid_or_conflicting_affected_code_hash",)
    repository_evidence = (
        manifest.get("repository_evidence")
        if isinstance(manifest.get("repository_evidence"), dict)
        else {}
    )
    evidence_bindings: list[dict[str, Any]] = []
    for item in repository_evidence.get("items") or []:
        if not isinstance(item, dict):
            continue
        for path_key, digest_key in (
            ("path", "file_sha256"),
            ("test_path", "test_sha256"),
            ("target_path", "target_sha256"),
            ("manifest_path", "manifest_sha256"),
        ):
            if item.get(path_key) or item.get(digest_key):
                evidence_bindings.append({
                    "path": item.get(path_key),
                    "sha256": item.get(digest_key),
                })
    if not collect(evidence_bindings):
        return ("invalid_or_conflicting_repository_evidence_hash",)

    paths_and_hashes = sorted(expected_by_path.items())
    matches = await asyncio.gather(
        *(
            asyncio.to_thread(
                _repository_file_matches_digest,
                root,
                relative_path,
                digest,
            )
            for relative_path, digest in paths_and_hashes
        )
    )
    return tuple(
        relative_path
        for (relative_path, _digest), matches_current in zip(
            paths_and_hashes,
            matches,
            strict=True,
        )
        if not matches_current
    )


def _repository_file_matches_digest(
    root: Path,
    relative_path: str,
    expected_sha256: str,
) -> bool:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        path = candidate
    else:
        path = root / candidate
    try:
        if path.is_symlink():
            return False
        resolved = path.resolve(strict=True)
        if resolved != root and root not in resolved.parents:
            return False
        if not resolved.is_file():
            return False
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == expected_sha256


def _codex_sessions_root() -> Path:
    root = (
        Path(settings.codex_home).expanduser()
        if settings.codex_home
        else Path.home() / ".codex"
    )
    return root / "sessions"


def _candidate_repo_path(candidate: _SessionTaskCandidate | None) -> str | None:
    if candidate is None:
        return None
    return _document_repo_path(candidate.source_document)


def _document_repo_path(document: SourceDocument) -> str | None:
    metadata = metadata_dict(document)
    for key in ("cwd", "working_directory", "workdir", "repo_path"):
        value = normalize_local_path(metadata.get(key))
        if value:
            return value
    return None


def _document_branch(document: SourceDocument | None) -> str | None:
    if document is None:
        return None
    metadata = metadata_dict(document)
    return _normalize_goal(metadata.get("branch") or metadata.get("git_branch"))


def _document_matches_repo(document: SourceDocument, requested_repo: str) -> bool:
    root = normalize_local_path(requested_repo)
    if not root:
        return False
    metadata = metadata_dict(document)
    candidates: list[Any] = [
        metadata.get("cwd"),
        metadata.get("working_directory"),
        metadata.get("workdir"),
        metadata.get("repo_path"),
    ]
    for key in ("observed_cwds", "git_common_roots"):
        value = metadata.get(key)
        candidates.extend(value if isinstance(value, list) else [value])
    for raw in candidates:
        path = normalize_local_path(raw)
        if path and (path == root or path_is_within(path, root)):
            return True
    return False


def _goals_compatible(left: str | None, right: str | None) -> bool:
    left_normalized = _normalize_goal(left)
    right_normalized = _normalize_goal(right)
    if not left_normalized or not right_normalized:
        return False
    left_key = _goal_key(left_normalized)
    right_key = _goal_key(right_normalized)
    if left_key == right_key:
        return True
    if min(len(left_key), len(right_key)) >= 16 and (
        left_key in right_key or right_key in left_key
    ):
        return True
    left_tokens = _goal_tokens(left_key)
    right_tokens = _goal_tokens(right_key)
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        return False
    intersection = left_tokens & right_tokens
    coverage = len(intersection) / min(len(left_tokens), len(right_tokens))
    union = left_tokens | right_tokens
    jaccard = len(intersection) / len(union)
    return coverage >= 0.8 and jaccard >= 0.5


def _normalize_goal(value: Any) -> str | None:
    normalized = " ".join(str(value or "").split())
    return normalized or None


def _normalize_checkpoint_key(value: UUID | str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _uuid_or_none(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


def _goal_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _goal_tokens(value: str) -> set[str]:
    return {
        token
        for token in value.split()
        if (len(token) > 1 or token.isdigit())
        and token not in _GOAL_STOP_WORDS
    }


def _task_identity(
    *,
    workspace_id: UUID,
    objective: str,
    current_goal: dict[str, Any] | None,
    repo_root: str | None,
    branch: str | None,
) -> str:
    if current_goal is not None and current_goal.get("id"):
        return str(current_goal["id"])
    normalized_root = normalize_local_path(repo_root) or ""
    normalized_branch = " ".join(str(branch or "").lower().split())
    digest = hashlib.sha256(
        (
            f"{workspace_id}:{normalized_root}:"
            f"{normalized_branch}:{_goal_key(objective)}"
        ).encode("utf-8")
    ).hexdigest()
    return f"task:{digest[:24]}"


def _task_identity_metadata(
    *,
    task_id: str,
    workspace_id: UUID,
    selected_objective: str,
    authoritative_request_sha256: str,
    current_goal: dict[str, Any] | None,
    selected_component_id: UUID | None,
) -> dict[str, Any]:
    """Return a presentation-independent identity for preview correlation.

    Display sanitizers are intentionally not involved. The objective key uses
    the same punctuation-insensitive normalization as the fallback task ID, so
    clients can compare the task they requested without rewriting either
    objective for display.
    """

    workspace_goal_id = (
        str(current_goal.get("id"))
        if current_goal is not None and current_goal.get("id")
        else None
    )
    return {
        "schema_version": CONTINUATION_TASK_IDENTITY_SCHEMA_VERSION,
        "id": task_id,
        "workspace_id": str(workspace_id),
        "selected_objective_key": _goal_key(selected_objective),
        "selected_objective_sha256": hashlib.sha256(
            selected_objective.encode("utf-8")
        ).hexdigest(),
        "authoritative_request_sha256": authoritative_request_sha256,
        "workspace_goal_id": workspace_goal_id,
        "selected_component_id": (
            str(selected_component_id)
            if selected_component_id is not None
            else None
        ),
    }


def _readiness_status(
    *,
    verification: dict[str, Any] | None,
    freshness: dict[str, Any],
    health_score: float,
) -> str:
    verification_status = (
        str(verification.get("status") or "") if verification else ""
    )
    if verification_status == "failed":
        return "blocked"
    if (
        verification_status in {"partial", "stale"}
        or freshness.get("status") in {"changed", "unavailable"}
        or health_score < 60
    ):
        return "review_required"
    return "ready"


def _checkpoint_blocking_issues(
    checkpoint_data: dict[str, Any] | None,
    *,
    workflow: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(checkpoint_data, dict):
        return []
    sections = checkpoint_data.get("sections")
    blockers = (
        sections.get("blockers")
        if isinstance(sections, dict)
        else None
    )
    if not isinstance(blockers, list):
        return []
    affected_tasks = _workflow_affected_tasks(workflow)
    issues: list[dict[str, Any]] = []
    for item in blockers:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "active").strip().lower()
        if state in {
            "cancelled",
            "completed",
            "dismissed",
            "historical",
            "rejected",
            "resolved",
            "superseded",
        }:
            continue
        statement = " ".join(str(item.get("statement") or "").split())
        if not statement:
            continue
        blocker = {
            "kind": "checkpoint",
            "id": str(item.get("id") or item.get("item_key") or ""),
            "statement": statement,
            "state": state,
            "truth_state": item.get("truth_state"),
            "checkpoint_id": checkpoint_data.get("id"),
        }
        provider = _reported_provider_auth_blocker(statement)
        provider_scoped = provider is not None
        truth_state = str(item.get("truth_state") or "").strip().lower()
        item_payload = item.get("payload")
        item_payload = item_payload if isinstance(item_payload, dict) else {}
        hard_checkpoint_blocker = bool(
            item_payload.get("blocks_current_execution") is True
            and truth_state in {"observed", "verified"}
        )
        issues.append({
            "code": (
                "checkpoint_provider_auth_reported"
                if provider_scoped
                else "checkpoint_blocker"
            ),
            "message": statement,
            "statement": statement,
            "blocker": blocker,
            "blocking_tasks": [],
            "affected_tasks": affected_tasks,
            # A sentence extracted from agent commentary is useful context, not
            # authority to prevent another agent from starting. Only an
            # explicitly typed, observation-backed hard blocker may stop launch.
            "blocks_current_execution": (
                hard_checkpoint_blocker and not provider_scoped
            ),
            "applicability": (
                {
                    "kind": "provider",
                    "providers": [provider],
                    "authority": "live_provider_readiness",
                }
                if provider_scoped
                else {
                    "kind": "task",
                    "task_ids": [
                        str(item.get("id") or "")
                        for item in affected_tasks
                        if item.get("id")
                    ],
                }
            ),
            "source": {
                "kind": "work_checkpoint",
                "checkpoint_id": checkpoint_data.get("id"),
                "checkpoint_item_id": blocker["id"] or None,
            },
        })
    return issues


def _reported_provider_auth_blocker(statement: str) -> str | None:
    lowered = statement.casefold()
    provider = next(
        (
            canonical
            for canonical, aliases in (
                ("claude", ("claude", "claude code")),
                ("codex", ("codex",)),
                ("opencode", ("opencode", "open code")),
            )
            if any(alias in lowered for alias in aliases)
        ),
        None,
    )
    if provider is None:
        return None
    auth_signal = any(
        signal in lowered
        for signal in (
            "auth",
            "credential",
            "oauth",
            "token",
        )
    )
    failure_signal = any(
        signal in lowered
        for signal in (
            "401",
            "expired",
            "failed",
            "invalid",
            "revoked",
            "unauthorized",
        )
    )
    return provider if auth_signal and failure_signal else None


def _checkpoint_section_summary(
    checkpoint_data: dict[str, Any],
    category: str,
) -> list[dict[str, Any]]:
    sections = checkpoint_data.get("sections")
    values = (
        sections.get(category)
        if isinstance(sections, dict)
        else None
    )
    if not isinstance(values, list):
        return []
    return [
        {
            "id": item.get("id"),
            "item_key": item.get("item_key"),
            "statement": item.get("statement"),
            "state": item.get("state"),
            "truth_state": item.get("truth_state"),
        }
        for item in values[:12]
        if isinstance(item, dict)
    ]


def _workflow_affected_tasks(
    workflow: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = [
        workflow.get("execution_task"),
        workflow.get("selected_intent"),
        *(workflow.get("affected_tasks") or []),
    ]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        key = str(
            candidate.get("id")
            or candidate.get("component_id")
            or candidate.get("title")
            or ""
        )
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(candidate)
        if len(result) >= 12:
            break
    return result


def _durable_descriptor_recovery_matches(
    persisted: tuple[TrustedRequestImageDescriptor, ...],
    recovered: tuple[TrustedRequestImageDescriptor, ...],
) -> bool:
    """Require exact attachment order/path and compatible content identity."""

    if not persisted or len(persisted) != len(recovered):
        return False
    return all(
        stored.path == restored.path
        and bool(restored.sha256)
        and bool(restored.resolved_path)
        and (
            stored.sha256 is None
            or stored.sha256 == restored.sha256
        )
        for stored, restored in zip(persisted, recovered, strict=True)
    )


def _attention(code: str, severity: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}
