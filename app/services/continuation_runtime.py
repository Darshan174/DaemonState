from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import AgentRun, ContinuationExecution, SessionEvent
from app.schemas.continuation_execution import (
    ContinuationArtifactInput,
    ContinuationExecutionContract,
    TaskMode,
)
from app.services.access import AccessScope
from app.services.continuation import ContinuationResult, ContinuationService
from app.services.codex_thread_stager import (
    CodexThreadStagingError,
    stage_codex_thread,
)
from app.services.harness_adapters import (
    PROVIDER_AUTH_ACTIONS,
    PROVIDER_DISPLAY_NAMES,
    HarnessAdapterError,
    HarnessExecutableNotFound,
    HarnessInvocation,
    ProviderName,
    ProviderReadiness,
    build_harness_invocation,
    continuation_provider_model,
    probe_provider_readiness,
    provider_environment,
)
from app.services.harness_sessions import (
    HarnessSessionBridge,
    harness_session_payload,
    record_staged_harness_session,
)
from app.services.harness_launcher import (
    HarnessLaunchError,
    HarnessVisibility,
    launch_harness_session,
    probe_harness_visibility,
)
from app.services.local_harness import (
    LocalHarnessResult,
    LocalHarnessRunner,
    RepositoryStateChangedError,
    capture_repository_snapshot,
)
from app.services.continuation_quality_gate import (
    evaluate_continuation_quality,
)
from app.services.execution_prompt_renderer import (
    STAGING_CONTEXT_SCHEMA_VERSION,
    render_continuation_staging_context,
    render_targeted_repair_prompt,
)
from app.services.provider_capabilities import (
    check_provider_capabilities,
    provider_capabilities,
)
from app.services.requirement_verifier import (
    RequirementVerificationMatrix,
    build_requirement_matrix,
    persist_final_outcome,
    persist_requirement_matrix,
)
from app.services.session_summary import (
    is_substantive_user_request,
    normalize_substantive_user_request,
)
from app.services.task_workflow import (
    TaskWorkflowService,
    complete_verified_execution_task,
)
from app.telemetry import traced
from app.time import utc_now


CONTINUATION_RUN_SCHEMA_VERSION = "continuation.run.v1"
CONTINUATION_STAGE_SCHEMA_VERSION = "continuation.stage.v1"
PROVIDER_PREFERENCE: tuple[ProviderName, ...] = ("codex", "claude", "opencode")
TARGET_PROVIDERS = frozenset((*PROVIDER_PREFERENCE, "auto"))
MAX_BLOCKER_TASK_LENGTH = 140
PROVIDER_READINESS_CACHE_SECONDS = 30.0
_provider_readiness_cache: tuple[
    float,
    tuple[object, object],
    tuple[ProviderReadiness, ...],
] | None = None
EXTERNAL_BLOCKER_CODES = frozenset({
    "continuation_repository_changed",
    "provider_authentication_failed",
    "provider_authentication_required",
    "provider_authentication_revoked",
    "provider_billing_required",
    "provider_cli_broken",
    "provider_cli_invalid",
    "provider_cli_not_found",
    "provider_cli_update_required",
    "provider_model_access_required",
    "provider_model_configuration_required",
    "provider_readiness_invalid",
    "provider_readiness_failed",
    "provider_readiness_timeout",
    "provider_service_unavailable",
})
AMBIGUITY_BLOCKER_CODES = frozenset({
    "continuation_ambiguity",
    "continuation_intent_ambiguous",
    "user_intent_required",
})


class ContinuationRunError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        blocker: dict[str, Any] | None = None,
        readiness: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.blocker = blocker
        self.readiness = readiness
        super().__init__(message)


@dataclass(frozen=True)
class ContinuationRunResult:
    preparation: ContinuationResult
    delivery: dict[str, Any]
    run: LocalHarnessResult
    outcome: dict[str, Any]
    schema_version: str = CONTINUATION_RUN_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.outcome["status"],
            "preparation": self.preparation.to_dict(),
            "delivery": self.delivery,
            "run": self.run.to_dict(),
            "outcome": self.outcome,
        }


@dataclass(frozen=True)
class ContinuationStageResult:
    preparation: ContinuationResult
    delivery: dict[str, Any]
    run: dict[str, Any]
    schema_version: str = CONTINUATION_STAGE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": "awaiting_user",
            "execution_started": False,
            "preparation": self.preparation.to_dict(),
            "delivery": self.delivery,
            "run": self.run,
        }


def _continuation_boundary_trace_attributes(
    kwargs: dict[str, Any],
    *,
    phase: str,
) -> dict[str, Any]:
    return {
        "daemonstate.phase": phase,
        "daemonstate.workspace.id": kwargs.get("workspace_id"),
        "daemonstate.checkpoint.id": kwargs.get("checkpoint_id"),
        "daemonstate.source.provider": kwargs.get("source_provider"),
        "daemonstate.target.provider": kwargs.get("target_provider"),
        "daemonstate.task.mode": kwargs.get("task_mode"),
        "daemonstate.context.token_budget": kwargs.get("token_budget"),
    }


def _continuation_stage_trace_result(
    result: ContinuationStageResult,
) -> dict[str, Any]:
    delivery = result.delivery if isinstance(result.delivery, dict) else {}
    run = result.run if isinstance(result.run, dict) else {}
    preparation = result.preparation
    return {
        "daemonstate.context_pack.id": preparation.context_pack_id,
        "daemonstate.continuation.execution.id": (
            preparation.continuation_execution_id
        ),
        "daemonstate.run.id": run.get("run_id"),
        "daemonstate.provider": delivery.get("provider"),
        "daemonstate.source.provider": delivery.get("source_provider"),
        "daemonstate.session.id": run.get("provider_session_id"),
        "daemonstate.delivery.context_sha256": delivery.get("context_sha256"),
        "daemonstate.staging.awaiting_user": True,
        "daemonstate.staging.execution_started": False,
        "daemonstate.status": "awaiting_user",
    }


def _continuation_run_trace_result(
    result: ContinuationRunResult,
) -> dict[str, Any]:
    delivery = result.delivery if isinstance(result.delivery, dict) else {}
    outcome = result.outcome if isinstance(result.outcome, dict) else {}
    checks = (
        outcome.get("checks")
        if isinstance(outcome.get("checks"), dict)
        else {}
    )
    return {
        "daemonstate.context_pack.id": result.preparation.context_pack_id,
        "daemonstate.continuation.execution.id": (
            result.preparation.continuation_execution_id
        ),
        "daemonstate.run.id": result.run.run_id,
        "daemonstate.provider": delivery.get("provider"),
        "daemonstate.source.provider": delivery.get("source_provider"),
        "daemonstate.task.mode": delivery.get("task_mode"),
        "daemonstate.status": outcome.get("status"),
        "daemonstate.runtime.worker_succeeded": result.run.status == "completed",
        "daemonstate.runtime.bundle_integrity_passed": (
            result.run.runtime_bundle_integrity_passed
        ),
        "daemonstate.runtime.preservation_passed": (
            result.run.preservation_passed
        ),
        "daemonstate.verification.total": checks.get("total"),
        "daemonstate.verification.passed": checks.get("passed"),
        "daemonstate.verification.failed": checks.get("failed"),
        "daemonstate.verification.unproven": checks.get("unproven"),
    }


class ContinuationStageService:
    """Load lead-bound Project Context and wait for user authorization."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @traced(
        "daemonstate.continuation.stage",
        attributes=lambda _args, kwargs: (
            _continuation_boundary_trace_attributes(
                kwargs,
                phase="continuation_stage",
            )
        ),
        result_attributes=lambda result: _continuation_stage_trace_result(
            result
        ),
    )
    async def stage(
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
        target_provider: str = "auto",
        provider_model: str | None = None,
        provider_effort: str | None = None,
        task_mode: TaskMode | str | None = None,
        artifacts: tuple[ContinuationArtifactInput, ...] = (),
        token_budget: int | None = None,
        idempotency_key: str | None = None,
        sync_sessions: bool = True,
        request_timeout_seconds: float | None = None,
    ) -> ContinuationStageResult:
        if access_scope.principal_id != "local":
            raise ContinuationRunError(
                "local_action_required",
                "A continuation can be staged only from the local app.",
                status_code=403,
            )
        supplied_lead = (
            objective is not None
            and is_substantive_user_request(
                normalize_substantive_user_request(objective)
            )
        )
        source_bound_lead = bool(
            checkpoint_id
            or (
                str(source_provider or "").strip()
                and str(source_session_id or "").strip()
            )
        )
        if not supplied_lead and not source_bound_lead:
            raise ContinuationRunError(
                "continuation_lead_required",
                (
                    "Enter the immediate lead or select an exact source session "
                    "or checkpoint before loading Project Context. Task-relevant "
                    "retrieval cannot be compiled for an unknown future "
                    "instruction."
                ),
                status_code=422,
                blocker={
                    "code": "continuation_lead_required",
                    "title": "Immediate lead required",
                    "message": (
                        "Project Context has not been staged because no "
                        "substantive immediate lead was supplied."
                    ),
                    "action": (
                        "Enter or confirm the task, or select its exact source "
                        "session or checkpoint, then load Project Context."
                    ),
                    "affected_tasks": [],
                },
            )

        normalized_target = _target_provider(target_provider)
        if normalized_target not in {"auto", "codex"}:
            raise ContinuationRunError(
                "continuation_staging_unsupported",
                (
                    "Waiting handoff is currently supported only in Codex "
                    "because it can persist context without starting a turn."
                ),
                status_code=409,
                blocker={
                    "code": "context_staging_unsupported",
                    "provider": normalized_target,
                    "message": (
                        f"{PROVIDER_DISPLAY_NAMES[normalized_target]} cannot "
                        "receive a waiting continuation safely yet."
                    ),
                    "action": "Choose Codex for this continuation.",
                    "affected_tasks": [_bounded_task(
                        objective or "Current continuation task"
                    )],
                },
            )

        run_key = _continuation_run_key(workspace_id, idempotency_key)
        if idempotency_key:
            existing = await self.session.scalar(
                select(AgentRun).where(
                    AgentRun.workspace_id == workspace_id,
                    AgentRun.run_key == run_key,
                )
            )
            if existing is not None:
                raise _duplicate_run_error(existing)
        active_run = await active_continuation_run(
            self.session,
            workspace_id=workspace_id,
        )
        if active_run is not None:
            raise _active_run_error(active_run)

        preparation = await ContinuationService(self.session).prepare(
            workspace_id=workspace_id,
            access_scope=access_scope,
            repo_path=repo_path,
            objective=objective,
            objective_is_user_edited=objective_is_user_edited,
            checkpoint_id=checkpoint_id,
            checkpoint_source_id=checkpoint_source_id,
            source_provider=source_provider,
            source_session_id=source_session_id,
            target_model=target_model,
            token_budget=token_budget,
            sync_sessions=sync_sessions,
            task_mode=task_mode,
            artifacts=artifacts,
        )
        if _repository_baseline_needs_refresh(preparation):
            refresh_repo_path, _refresh_repository = _repository_coordinates(
                preparation
            )
            try:
                refreshed_snapshot = await capture_repository_snapshot(
                    refresh_repo_path
                )
            except (OSError, ValueError):
                refreshed_snapshot = None
            if (
                refreshed_snapshot is not None
                and not refreshed_snapshot.status_truncated
            ):
                preparation = await ContinuationService(self.session).prepare(
                    workspace_id=workspace_id,
                    access_scope=access_scope,
                    repo_path=repo_path,
                    objective=objective,
                    objective_is_user_edited=objective_is_user_edited,
                    checkpoint_id=checkpoint_id,
                    checkpoint_source_id=checkpoint_source_id,
                    source_provider=source_provider,
                    source_session_id=source_session_id,
                    target_model=target_model,
                    token_budget=token_budget,
                    sync_sessions=False,
                    task_mode=task_mode,
                    artifacts=artifacts,
                )
        effective_repo_path, current_repository = _repository_coordinates(
            preparation
        )
        expected_fingerprint = _repository_fingerprint(current_repository)

        try:
            launch_snapshot = await capture_repository_snapshot(effective_repo_path)
        except (OSError, ValueError) as exc:
            raise ContinuationRunError(
                "continuation_repository_unavailable",
                "A readable local Git repository is required to continue this task.",
            ) from exc
        if launch_snapshot.status_fingerprint != expected_fingerprint:
            preparation = await ContinuationService(self.session).prepare(
                workspace_id=workspace_id,
                access_scope=access_scope,
                repo_path=repo_path,
                objective=objective,
                objective_is_user_edited=objective_is_user_edited,
                checkpoint_id=checkpoint_id,
                checkpoint_source_id=checkpoint_source_id,
                source_provider=source_provider,
                source_session_id=source_session_id,
                target_model=target_model,
                token_budget=token_budget,
                sync_sessions=False,
                task_mode=task_mode,
                artifacts=artifacts,
            )
            effective_repo_path, current_repository = _repository_coordinates(
                preparation
            )
            expected_fingerprint = _repository_fingerprint(current_repository)

        _execution, contract = await _prepared_execution(
            self.session,
            preparation,
        )
        context_message = _staging_context_for_preparation(
            preparation,
            contract=contract,
            expected_lead=objective or contract.task.request_verbatim,
        )

        invocation = await _select_ready_invocation(
            repo_path=effective_repo_path,
            target_provider="codex",
            provider_model=provider_model,
            provider_effort=provider_effort,
            current_task=preparation.objective,
            affected_tasks=_preparation_affected_task_titles(preparation),
            contract=contract,
        )
        pack_id = UUID(preparation.context_pack_id)
        run = AgentRun(
            workspace_id=workspace_id,
            context_pack_id=pack_id,
            continuation_execution_id=None,
            attempt_index=1,
            run_key=run_key,
            tool="daemonstate:codex",
            model=invocation.model or "codex",
            objective=preparation.objective,
            branch=current_repository.get("branch"),
            base_commit=current_repository.get("head_commit"),
            started_at=utc_now(),
            status="staging",
        )
        self.session.add(run)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.session.scalar(
                select(AgentRun).where(
                    AgentRun.workspace_id == workspace_id,
                    AgentRun.run_key == run_key,
                )
            )
            if existing is not None:
                raise _duplicate_run_error(existing)
            raise

        timeout_seconds = (
            request_timeout_seconds
            if request_timeout_seconds is not None
            else min(settings.continuation_command_timeout_seconds, 30.0)
        )
        try:
            staged = await stage_codex_thread(
                codex_bin=invocation.executable,
                cwd=effective_repo_path,
                context_message=context_message,
                filesystem_mode=contract.authority.filesystem_mode.value,
                model=invocation.model,
                effort=invocation.effort,
                request_timeout_seconds=timeout_seconds,
                environment=provider_environment("codex"),
            )
            repository_after = await capture_repository_snapshot(
                effective_repo_path
            )
            if repository_after.status_fingerprint != expected_fingerprint:
                raise RepositoryStateChangedError(
                    expected_fingerprint,
                    repository_after.status_fingerprint,
                )
        except RepositoryStateChangedError as exc:
            run.status = "failed"
            run.ended_at = utc_now()
            await asyncio.shield(self.session.commit())
            raise ContinuationRunError(
                "continuation_repository_changed",
                (
                    "Repository state changed while context was being loaded. "
                    "No Codex turn was started."
                ),
                status_code=409,
            ) from exc
        except CodexThreadStagingError as exc:
            run.status = "failed"
            run.ended_at = utc_now()
            await asyncio.shield(self.session.commit())
            raise ContinuationRunError(
                "continuation_staging_failed",
                f"Codex could not load the waiting continuation: {exc}",
                status_code=409,
            ) from exc
        except BaseException:
            run.status = "failed"
            run.ended_at = utc_now()
            await asyncio.shield(self.session.commit())
            raise

        source = _normalized_source_provider(preparation.source_session)
        manifest_continuation = (
            preparation.manifest.get("continuation")
            if isinstance(preparation.manifest, dict)
            and isinstance(preparation.manifest.get("continuation"), dict)
            else {}
        )
        source_session = (
            preparation.source_session
            if isinstance(preparation.source_session, dict)
            else {}
        )
        continuation_identity = {
            "task_id": manifest_continuation.get("task_id"),
            "selected_objective": (
                manifest_continuation.get("selected_objective")
                or preparation.objective
            ),
            "checkpoint_id": (
                manifest_continuation.get("checkpoint_id")
                or contract.checkpoint_id
            ),
            "source_provider": (
                manifest_continuation.get("provider")
                or source
            ),
            "source_session_id": (
                manifest_continuation.get("session_id")
                or source_session.get("session_id")
            ),
        }
        session_state: dict[str, Any] = {
            "provider": "codex",
            "session_id": staged.thread_id,
            "cwd": effective_repo_path,
            "launched": False,
            "navigation_requested": False,
            "navigation_verified": False,
            "mode": "desktop_app",
            "navigation": "session",
            "exact_session_supported": True,
            "renderable_activity_observed": False,
            "awaiting_user": True,
            "execution_started": False,
            "activation_boundary_verified": (
                staged.activation_boundary_verified
            ),
            "observed_turn_count": staged.observed_turn_count,
            "context_delivery": staged.context_delivery,
            "context_sha256": staged.context_sha256,
            "developer_instructions_sha256": (
                staged.developer_instructions_sha256
            ),
            "context_schema_version": STAGING_CONTEXT_SCHEMA_VERSION,
            "continuation_identity": continuation_identity,
        }
        try:
            launch = await asyncio.to_thread(
                launch_harness_session,
                "codex",
                staged.thread_id,
                cwd=effective_repo_path,
            )
            session_state.update({
                "launched": launch.get("launched") is True,
                "navigation_requested": (
                    launch.get("navigation_requested") is True
                    or launch.get("launched") is True
                ),
                "navigation_verified": (
                    launch.get("navigation_verified") is True
                ),
                "mode": launch.get("mode") or "desktop_app",
                "navigation": launch.get("navigation") or "session",
                "exact_session_supported": (
                    launch.get("exact_session_supported") is True
                ),
            })
        except HarnessLaunchError as exc:
            session_state.update({
                "code": exc.code,
                "message": str(exc),
            })

        public_session = await record_staged_harness_session(
            self.session,
            run=run,
            state=session_state,
        )
        run.status = "awaiting_user"
        await self.session.commit()

        delivery = {
            "status": "awaiting_user",
            "provider": "codex",
            "source_provider": source,
            "provider_switched": bool(source and source != "codex"),
            "mode": "waiting_thread",
            "context_delivery": staged.context_delivery,
            "context_schema_version": STAGING_CONTEXT_SCHEMA_VERSION,
            "context_sha256": staged.context_sha256,
            "execution_started": False,
            "activation_boundary_verified": (
                staged.activation_boundary_verified
            ),
            "observed_turn_count": staged.observed_turn_count,
            "activation": "next_user_turn",
            "run_id": str(run.id),
            "provider_model": invocation.model,
            "provider_effort": invocation.effort,
            "task_mode": contract.task_mode.value,
            "filesystem_mode": invocation.filesystem_mode,
            "harness_session": public_session,
            "visibility": {
                "status": (
                    "navigation_requested_unverified"
                    if public_session.get("navigation_requested") is True
                    else "thread_staged"
                ),
                "context_loaded": True,
                "execution_started": False,
                "navigation_requested": (
                    public_session.get("navigation_requested") is True
                ),
                "navigation_verified": (
                    public_session.get("navigation_verified") is True
                ),
                "message": (
                    "Context is loaded; Codex is waiting for the user's lead."
                ),
            },
        }
        return ContinuationStageResult(
            preparation=preparation,
            delivery=delivery,
            run={
                "run_id": str(run.id),
                "status": run.status,
                "provider": "codex",
                "provider_session_id": staged.thread_id,
                "objective": run.objective,
                "started_at": (
                    run.started_at.isoformat() if run.started_at else None
                ),
                "execution_started": False,
            },
        )


class ContinuationRunService:
    """Prepare, deliver, execute, and verify one local continuation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @traced(
        "daemonstate.continuation.run",
        attributes=lambda _args, kwargs: (
            _continuation_boundary_trace_attributes(
                kwargs,
                phase="continuation_run",
            )
        ),
        result_attributes=lambda result: _continuation_run_trace_result(
            result
        ),
    )
    async def run(
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
        target_provider: str = "auto",
        provider_model: str | None = None,
        provider_effort: str | None = None,
        task_mode: TaskMode | str | None = None,
        artifacts: tuple[ContinuationArtifactInput, ...] = (),
        token_budget: int | None = None,
        idempotency_key: str | None = None,
        sync_sessions: bool = True,
        output_limit_bytes: int | None = None,
        command_timeout_seconds: float | None = None,
        verification_timeout_seconds: float | None = None,
    ) -> ContinuationRunResult:
        if access_scope.principal_id != "local":
            raise ContinuationRunError(
                "local_action_required",
                "Agent continuation can run only from the local app.",
                status_code=403,
            )

        run_key = _continuation_run_key(workspace_id, idempotency_key)
        if idempotency_key:
            existing = await self.session.scalar(
                select(AgentRun).where(
                    AgentRun.workspace_id == workspace_id,
                    AgentRun.run_key == run_key,
                )
            )
            if existing is not None:
                raise _duplicate_run_error(existing)
        active_run = await active_continuation_run(
            self.session,
            workspace_id=workspace_id,
        )
        if active_run is not None:
            raise _active_run_error(active_run)

        preparation = await ContinuationService(self.session).prepare(
            workspace_id=workspace_id,
            access_scope=access_scope,
            repo_path=repo_path,
            objective=objective,
            objective_is_user_edited=objective_is_user_edited,
            checkpoint_id=checkpoint_id,
            checkpoint_source_id=checkpoint_source_id,
            source_provider=source_provider,
            source_session_id=source_session_id,
            target_model=target_model,
            token_budget=token_budget,
            sync_sessions=sync_sessions,
            task_mode=task_mode,
            artifacts=artifacts,
        )
        if _repository_baseline_needs_refresh(preparation):
            refresh_repo_path, _refresh_repository = _repository_coordinates(
                preparation
            )
            try:
                refreshed_snapshot = await capture_repository_snapshot(
                    refresh_repo_path
                )
            except (OSError, ValueError):
                refreshed_snapshot = None
            if (
                refreshed_snapshot is not None
                and not refreshed_snapshot.status_truncated
            ):
                # The preservation capture can race with an atomic editor save.
                # Recompile once from the now-complete state before failing the
                # closed quality gate.
                preparation = await ContinuationService(self.session).prepare(
                    workspace_id=workspace_id,
                    access_scope=access_scope,
                    repo_path=repo_path,
                    objective=objective,
                    objective_is_user_edited=objective_is_user_edited,
                    checkpoint_id=checkpoint_id,
                    checkpoint_source_id=checkpoint_source_id,
                    source_provider=source_provider,
                    source_session_id=source_session_id,
                    target_model=target_model,
                    token_budget=token_budget,
                    sync_sessions=False,
                    task_mode=task_mode,
                    artifacts=artifacts,
                )
        effective_repo_path, current_repository = _runnable_repository(preparation)
        expected_fingerprint = _repository_fingerprint(current_repository)

        try:
            launch_snapshot = await capture_repository_snapshot(effective_repo_path)
        except (OSError, ValueError) as exc:
            raise ContinuationRunError(
                "continuation_repository_unavailable",
                "A readable local Git repository is required to continue this task.",
            ) from exc
        if launch_snapshot.status_fingerprint != expected_fingerprint:
            # Repository activity during preparation is normal. Recompile once so
            # the receiving agent gets the latest state without user intervention.
            preparation = await ContinuationService(self.session).prepare(
                workspace_id=workspace_id,
                access_scope=access_scope,
                repo_path=repo_path,
                objective=objective,
                objective_is_user_edited=objective_is_user_edited,
                checkpoint_id=checkpoint_id,
                checkpoint_source_id=checkpoint_source_id,
                source_provider=source_provider,
                source_session_id=source_session_id,
                target_model=target_model,
                token_budget=token_budget,
                sync_sessions=False,
                task_mode=task_mode,
                artifacts=artifacts,
            )
            effective_repo_path, current_repository = _runnable_repository(preparation)
            expected_fingerprint = _repository_fingerprint(current_repository)

        execution, contract = await _prepared_execution(
            self.session,
            preparation,
        )
        quality = evaluate_continuation_quality(
            contract,
            prompt_markdown=execution.prompt_markdown,
            expected_contract_sha256=execution.contract_sha256,
            expected_prompt_sha256=execution.prompt_sha256,
        )
        if not quality.launchable:
            raise _quality_gate_error(
                quality.to_dict(),
                current_task=preparation.objective,
            )

        source_provider = _normalized_source_provider(preparation.source_session)
        effective_command_timeout = (
            command_timeout_seconds
            if command_timeout_seconds is not None
            else settings.continuation_command_timeout_seconds
        )
        runner_options = {
            **(
                {"output_limit_bytes": output_limit_bytes}
                if output_limit_bytes is not None
                else {}
            ),
            **(
                {
                    "verification_timeout_seconds":
                    verification_timeout_seconds
                }
                if verification_timeout_seconds is not None
                else {}
            ),
        }
        invocation = await _select_ready_invocation(
            repo_path=effective_repo_path,
            target_provider=target_provider,
            provider_model=provider_model,
            provider_effort=provider_effort,
            current_task=preparation.objective,
            affected_tasks=_preparation_affected_task_titles(preparation),
            contract=contract,
        )
        pack_id = UUID(preparation.context_pack_id)
        run = AgentRun(
            workspace_id=workspace_id,
            context_pack_id=pack_id,
            continuation_execution_id=execution.id,
            attempt_index=1,
            run_key=run_key,
            tool=f"daemonstate:{invocation.provider}",
            model=invocation.model or invocation.provider,
            objective=preparation.objective,
            branch=current_repository.get("branch"),
            base_commit=current_repository.get("head_commit"),
            started_at=utc_now(),
            status="running",
        )
        self.session.add(run)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.session.scalar(
                select(AgentRun).where(
                    AgentRun.workspace_id == workspace_id,
                    AgentRun.run_key == run_key,
                )
            )
            if existing is not None:
                raise _duplicate_run_error(existing)
            raise

        launch_readiness = await _readiness_for(
            invocation.provider,
            provider_model=invocation.model,
        )
        if not launch_readiness.ready:
            run.status = "failed"
            run.ended_at = utc_now()
            await asyncio.shield(self.session.commit())
            raise _provider_readiness_error(
                launch_readiness,
                current_task=preparation.objective,
                explicit=_target_provider(target_provider) != "auto",
                affected_tasks=_preparation_affected_task_titles(preparation),
            )

        try:
            session_bridge = HarnessSessionBridge(
                self.session,
                run=run,
                provider=invocation.provider,
                repo_path=invocation.repo_path,
            )
            try:
                result = await LocalHarnessRunner(
                    self.session,
                    **runner_options,
                ).run(
                    context_pack_id=pack_id,
                    run_id=run.id,
                    repo_path=invocation.repo_path,
                    command=invocation.argv,
                    verify=True,
                    context_stdin=invocation.context_delivery == "stdin",
                    extra_env=provider_environment(invocation.provider),
                    expected_status_fingerprint=expected_fingerprint,
                    command_timeout_seconds=effective_command_timeout,
                    stdout_chunk_observer=session_bridge.observe_stdout_chunk,
                    continuation_execution_id=execution.id,
                )
            finally:
                await session_bridge.finish()
        except RepositoryStateChangedError as exc:
            run.status = "failed"
            run.ended_at = utc_now()
            await asyncio.shield(self.session.commit())
            raise ContinuationRunError(
                "continuation_repository_changed",
                (
                    "Repository state changed again immediately before launch. "
                    "No target agent was started."
                ),
                status_code=409,
            ) from exc
        except BaseException:
            run.status = "failed"
            run.ended_at = utc_now()
            await asyncio.shield(self.session.commit())
            raise

        delivery = {
            "status": "delivered",
            "provider": invocation.provider,
            "source_provider": source_provider,
            "provider_switched": bool(
                source_provider and invocation.provider != source_provider
            ),
            "mode": invocation.mode,
            "context_delivery": invocation.context_delivery,
            "run_id": str(run.id),
            "provider_model": invocation.model,
            "provider_effort": invocation.effort,
            "task_mode": contract.task_mode.value,
            "filesystem_mode": invocation.filesystem_mode,
            "command_timeout_seconds": effective_command_timeout,
        }
        if session_bridge.state is not None:
            delivery["harness_session"] = session_bridge.state
            delivery["visibility"] = _harness_visibility_evidence(
                session_bridge.state
            )
        matrix = build_requirement_matrix(
            contract,
            result.verification_results,
            worker_succeeded=result.status == "completed",
            bundle_integrity_passed=result.runtime_bundle_integrity_passed,
            preservation_passed=result.preservation_passed,
        )
        await persist_requirement_matrix(
            self.session,
            execution=execution,
            run=run,
            matrix=matrix,
        )
        await self.session.commit()
        attempts = [{
            "attempt_index": 1,
            "run_id": str(run.id),
            "status": matrix.status,
        }]
        root_run = run
        preservation_baseline = result.repository_before
        session_id = (
            str(session_bridge.state.get("session_id") or "").strip()
            if session_bridge.state is not None
            else ""
        )
        prior_signature = _repair_progress_signature(matrix, result)
        repair_blocker: dict[str, Any] | None = None
        for attempt_index in range(
            2,
            contract.execution_policy.max_repair_attempts + 2,
        ):
            if not _repairable(
                contract,
                matrix=matrix,
                result=result,
                session_id=session_id,
            ):
                break
            repair_readiness = await _readiness_for(
                invocation.provider,
                provider_model=invocation.model,
            )
            if not repair_readiness.ready:
                repair_blocker = {
                    "code": repair_readiness.code,
                    "provider": repair_readiness.provider,
                    "message": repair_readiness.message,
                    "action": repair_readiness.action,
                    "affected_tasks": _preparation_affected_task_titles(
                        preparation
                    ),
                }
                break
            repair_prompt = render_targeted_repair_prompt(
                contract,
                canonical_prompt=execution.prompt_markdown,
                verification_matrix=matrix,
                attempt_index=attempt_index,
                current_status_fingerprint=(
                    result.repository_after.status_fingerprint
                ),
            )
            repair_invocation = build_harness_invocation(
                invocation.provider,
                repo_path=invocation.repo_path,
                session_id=session_id,
                model=invocation.model,
                effort=invocation.effort,
                visible=False,
                filesystem_mode=contract.authority.filesystem_mode.value,
            )
            repair_run = AgentRun(
                workspace_id=workspace_id,
                context_pack_id=pack_id,
                continuation_execution_id=execution.id,
                parent_agent_run_id=root_run.id,
                attempt_index=attempt_index,
                provider_session_id=session_id,
                run_key=f"{run_key}:repair:{attempt_index}",
                tool=f"daemonstate:{repair_invocation.provider}",
                model=repair_invocation.model or repair_invocation.provider,
                objective=preparation.objective,
                branch=result.repository_after.branch,
                base_commit=result.repository_after.head_commit,
                started_at=utc_now(),
                status="running",
            )
            self.session.add(repair_run)
            await self.session.commit()
            repair_bridge = HarnessSessionBridge(
                self.session,
                run=repair_run,
                provider=repair_invocation.provider,
                repo_path=repair_invocation.repo_path,
                open_desktop=False,
            )
            try:
                try:
                    repair_result = await LocalHarnessRunner(
                        self.session,
                        **runner_options,
                    ).run(
                        context_pack_id=pack_id,
                        run_id=repair_run.id,
                        repo_path=repair_invocation.repo_path,
                        command=repair_invocation.argv,
                        verify=True,
                        context_stdin=(
                            repair_invocation.context_delivery == "stdin"
                        ),
                        extra_env=provider_environment(
                            repair_invocation.provider
                        ),
                        expected_status_fingerprint=(
                            result.repository_after.status_fingerprint
                        ),
                        command_timeout_seconds=effective_command_timeout,
                        stdout_chunk_observer=(
                            repair_bridge.observe_stdout_chunk
                        ),
                        continuation_execution_id=execution.id,
                        execution_prompt_override=repair_prompt,
                        preservation_baseline=preservation_baseline,
                    )
                finally:
                    await repair_bridge.finish()
            except RepositoryStateChangedError:
                repair_run.status = "failed"
                repair_run.ended_at = utc_now()
                await asyncio.shield(self.session.commit())
                attempts.append({
                    "attempt_index": attempt_index,
                    "run_id": str(repair_run.id),
                    "status": "execution_failed",
                })
                repair_blocker = {
                    "code": "continuation_repository_changed",
                    "message": (
                        "Repository state changed immediately before a repair "
                        "attempt, so the controller stopped safely."
                    ),
                }
                break
            except BaseException:
                repair_run.status = "failed"
                repair_run.ended_at = utc_now()
                await asyncio.shield(self.session.commit())
                raise
            repair_matrix = build_requirement_matrix(
                contract,
                repair_result.verification_results,
                worker_succeeded=repair_result.status == "completed",
                bundle_integrity_passed=(
                    repair_result.runtime_bundle_integrity_passed
                ),
                preservation_passed=repair_result.preservation_passed,
            )
            await persist_requirement_matrix(
                self.session,
                execution=execution,
                run=repair_run,
                matrix=repair_matrix,
            )
            await self.session.commit()
            run = repair_run
            result = repair_result
            matrix = repair_matrix
            attempts.append({
                "attempt_index": attempt_index,
                "run_id": str(run.id),
                "status": matrix.status,
            })
            if matrix.verified:
                break
            progress_signature = _repair_progress_signature(matrix, result)
            if (
                contract.execution_policy.stop_on_no_progress
                and progress_signature == prior_signature
            ):
                repair_blocker = {
                    "code": "repair_no_progress",
                    "message": (
                        "A targeted repair attempt left the same unmet "
                        "requirements and repository fingerprint."
                    ),
                }
                break
            prior_signature = progress_signature

        delivery["root_run_id"] = str(root_run.id)
        delivery["run_id"] = str(run.id)
        delivery["attempts"] = attempts
        outcome = _contract_outcome(
            matrix,
            result=result,
            provider=invocation.provider,
            current_task=preparation.objective,
            affected_tasks=_preparation_affected_task_titles(preparation),
            blocker_override=repair_blocker,
        )
        await persist_final_outcome(
            self.session,
            execution=execution,
            matrix=matrix,
            payload=outcome,
        )
        await self.session.commit()
        if outcome["verified"]:
            preparation_workflow = (
                preparation.task.get("workflow")
                if isinstance(preparation.task, dict)
                else None
            )
            transition = await complete_verified_execution_task(
                self.session,
                workspace_id=workspace_id,
                access_scope=access_scope,
                workflow=preparation_workflow,
            )
            await self.session.commit()
            refreshed_workflow = await _refreshed_workflow_after_transition(
                self.session,
                workspace_id=workspace_id,
                access_scope=access_scope,
                workflow=preparation_workflow,
                transition=transition,
            )
            if refreshed_workflow is not None:
                transition["workflow_after"] = refreshed_workflow
            outcome["task_transition"] = transition
        return ContinuationRunResult(
            preparation=preparation,
            delivery=delivery,
            run=result,
            outcome=outcome,
        )


def _runnable_repository(
    preparation: ContinuationResult,
) -> tuple[str, dict[str, Any]]:
    quality_report = getattr(preparation, "quality_report", None)
    if (
        isinstance(quality_report, dict)
        and quality_report.get("launchable") is False
    ):
        raise _quality_gate_error(
            quality_report,
            current_task=preparation.objective,
        )
    readiness = str(preparation.readiness.get("status") or "").strip().lower()
    checkpoint_status = str(
        (preparation.checkpoint or {}).get("continuation_status") or ""
    ).strip().lower()
    if readiness not in {"ready", "review_required"} or checkpoint_status == "blocked":
        blocker = _preparation_blocker(preparation)
        raise ContinuationRunError(
            "continuation_preparation_blocked",
            blocker["message"],
            status_code=409,
            blocker=blocker,
        )

    return _repository_coordinates(preparation)


def _repository_coordinates(
    preparation: ContinuationResult,
) -> tuple[str, dict[str, Any]]:
    repo_path = str(preparation.repository.get("path") or "").strip()
    current = preparation.repository.get("current")
    if not repo_path or not isinstance(current, dict):
        raise ContinuationRunError(
            "continuation_repository_unavailable",
            "A readable local Git repository is required to continue this task.",
        )
    return repo_path, current


def _repository_baseline_needs_refresh(
    preparation: ContinuationResult,
) -> bool:
    report = getattr(preparation, "quality_report", None)
    if not isinstance(report, dict) or report.get("launchable") is not False:
        return False
    raw_blocking = report.get("blocking_issues")
    if not isinstance(raw_blocking, list):
        raw_issues = report.get("issues")
        if not isinstance(raw_issues, list):
            raw_issues = []
        raw_blocking = [
            issue
            for issue in raw_issues
            if isinstance(issue, dict)
            and (
                issue.get("severity") == "blocking"
                or issue.get("blocks_current_execution") is True
            )
        ]
    blocking = [
        issue for issue in raw_blocking if isinstance(issue, dict)
    ]
    return bool(blocking) and all(
        issue.get("code") == "repository_baseline_truncated"
        for issue in blocking
    )


async def _prepared_execution(
    session: AsyncSession,
    preparation: ContinuationResult,
) -> tuple[ContinuationExecution, ContinuationExecutionContract]:
    try:
        execution_id = UUID(preparation.continuation_execution_id)
        contract = ContinuationExecutionContract.model_validate(
            preparation.execution_contract
        )
    except (TypeError, ValueError) as exc:
        raise ContinuationRunError(
            "continuation_execution_invalid",
            "The prepared continuation execution contract is invalid.",
            status_code=409,
        ) from exc
    execution = await session.get(ContinuationExecution, execution_id)
    if execution is None:
        raise ContinuationRunError(
            "continuation_execution_missing",
            "The prepared continuation execution contract was not persisted.",
            status_code=409,
        )
    if (
        str(contract.id) != str(execution.id)
        or str(contract.context_pack_id) != preparation.context_pack_id
        or execution.context_pack_id != UUID(preparation.context_pack_id)
    ):
        raise ContinuationRunError(
            "continuation_execution_mismatch",
            "The prepared execution contract does not match its context pack.",
            status_code=409,
        )
    return execution, contract


def _staging_context_for_preparation(
    preparation: ContinuationResult,
    *,
    contract: ContinuationExecutionContract,
    expected_lead: str,
) -> str:
    """Return only a hash-bound, copy-safe context for the supplied lead.

    Staging creates no provider turn, so subjective or externally observed
    verification may prevent automatic execution without making the handoff
    unsafe to load. The Project Context copy gate is the correct boundary here;
    automatic runs continue to use the stricter execution quality gate.
    """

    project_context = (
        preparation.project_context
        if isinstance(preparation.project_context, dict)
        else {}
    )
    quality_issues = [
        issue
        for issue in project_context.get("quality_issues", [])
        if isinstance(issue, dict) and issue.get("blocks_copy") is not False
    ]
    rendered = render_continuation_staging_context(contract)
    expected_content = str(project_context.get("content") or "")
    expected_sha256 = str(project_context.get("sha256") or "").strip()
    content_sha256 = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    structurally_safe = (
        project_context.get("schema_version")
        == STAGING_CONTEXT_SCHEMA_VERSION
        and project_context.get("scope") == "project"
        and project_context.get("copy_ready") is True
        and bool(expected_content.strip())
        and expected_content == rendered
        and expected_sha256 == content_sha256
    )
    lead_matches = contract.task.request_verbatim == expected_lead
    if structurally_safe and lead_matches:
        return rendered

    issue_message = next(
        (
            str(issue.get("message") or "").strip()
            for issue in quality_issues
            if str(issue.get("message") or "").strip()
        ),
        "",
    )
    message = (
        issue_message
        or (
            "The compiled Project Context does not match the supplied "
            "immediate lead."
            if not lead_matches
            else (
                "The compiled Project Context failed its copy-safety or "
                "integrity checks."
            )
        )
    )
    raise ContinuationRunError(
        (
            "continuation_lead_mismatch"
            if not lead_matches
            else "project_context_staging_blocked"
        ),
        message,
        status_code=409,
        blocker={
            "code": (
                "continuation_lead_mismatch"
                if not lead_matches
                else "project_context_staging_blocked"
            ),
            "title": (
                "Immediate lead changed"
                if not lead_matches
                else "Project Context is not safe to stage"
            ),
            "message": message,
            "action": (
                "Compile fresh Project Context for the exact immediate lead "
                "before loading it into a harness."
            ),
            "affected_tasks": [_bounded_task(expected_lead)],
            "quality_issues": quality_issues,
        },
    )


def _quality_gate_error(
    report: dict[str, Any],
    *,
    current_task: str,
) -> ContinuationRunError:
    issues = [
        issue
        for issue in report.get("issues", [])
        if isinstance(issue, dict)
    ]
    message = (
        str(issues[0].get("message") or "").strip()
        if issues
        else "The continuation execution contract is not launchable."
    )
    return ContinuationRunError(
        "continuation_quality_gate_failed",
        message,
        status_code=409,
        blocker={
            "code": "continuation_quality_gate_failed",
            "title": "Continuation contract needs evidence",
            "message": message,
            "action": (
                "Resolve the listed contract, artifact, verifier, or provider "
                "capability gaps before launching."
            ),
            "affected_tasks": [_bounded_task(current_task)],
            "quality_report": report,
        },
    )


def _preparation_blocker(preparation: ContinuationResult) -> dict[str, Any]:
    readiness = (
        preparation.readiness
        if isinstance(preparation.readiness, dict)
        else {}
    )
    readiness_issues = readiness.get("blocking_issues")
    if isinstance(readiness_issues, list):
        exact_issue = next(
            (
                issue
                for issue in readiness_issues
                if isinstance(issue, dict)
                and issue.get("blocks_current_execution", True)
            ),
            None,
        )
        if exact_issue is not None:
            code = str(
                exact_issue.get("code") or "continuation_preparation_blocked"
            ).strip()
            message = str(
                exact_issue.get("message")
                or exact_issue.get("statement")
                or "Continuation is blocked."
            ).strip()
            affected_tasks = exact_issue.get("affected_tasks")
            if not isinstance(affected_tasks, list) or not affected_tasks:
                affected_tasks = readiness.get("affected_tasks")
            if not isinstance(affected_tasks, list) or not affected_tasks:
                affected_tasks = _preparation_affected_task_titles(preparation)
            return {
                "code": code,
                "title": _preparation_blocker_title(code, exact_issue),
                "provider": _issue_provider(exact_issue),
                "message": message[:1_000],
                "action": _preparation_blocker_action(code, exact_issue),
                "blocking_tasks": exact_issue.get("blocking_tasks") or [],
                "affected_tasks": affected_tasks,
                "applicability": exact_issue.get("applicability"),
            }

    attention = getattr(preparation, "attention", None)
    blocking_attention = None
    if isinstance(attention, list):
        blocking_attention = next(
            (
                item
                for item in attention
                if isinstance(item, dict)
                and str(item.get("severity") or "").lower() == "error"
            ),
            None,
        )
    message = (
        str(blocking_attention.get("message") or "").strip()
        if blocking_attention
        else ""
    )
    code = (
        str(blocking_attention.get("code") or "").strip()
        if blocking_attention
        else ""
    )
    if not message:
        message = "Checkpoint verification failed; continuation was not started."
    if not code:
        code = "continuation_preparation_blocked"
    return {
        "code": code,
        "title": _preparation_blocker_title(code, {}),
        "provider": None,
        "message": message[:1_000],
        "action": "Resolve the failed preparation check, then retry.",
        "affected_tasks": _preparation_affected_task_titles(preparation),
    }


def _preparation_blocker_title(
    code: str,
    issue: dict[str, Any],
) -> str:
    blocker = issue.get("blocker")
    blocker_title = (
        str(blocker.get("title") or "").strip()
        if isinstance(blocker, dict)
        else ""
    )
    normalized = code.casefold()
    if blocker_title and "dependency" in normalized:
        return f"{blocker_title} blocks this continuation"
    if "cycle" in normalized:
        return "Dependency cycle blocks continuation"
    if "ambiguous" in normalized:
        return "Execution order needs a decision"
    if "checkpoint" in normalized:
        return "Saved checkpoint blocker"
    if "goal" in normalized:
        return "Task goal is missing"
    if "verification" in normalized:
        return "Checkpoint verification failed"
    return "Continuation preparation blocked"


def _preparation_blocker_action(
    code: str,
    issue: dict[str, Any],
) -> str:
    explicit = str(
        issue.get("action")
        or issue.get("recovery_action")
        or ""
    ).strip()
    if explicit:
        return explicit[:500]
    normalized = code.casefold()
    if "cycle" in normalized or "ambiguous" in normalized:
        return "Correct the task dependency order, then retry."
    if "dependency" in normalized:
        return "Make the blocking prerequisite actionable, then retry."
    if "checkpoint" in normalized:
        return "Resolve or supersede the saved blocker, then retry."
    return "Resolve the failed preparation check, then retry."


def _issue_provider(issue: dict[str, Any]) -> str | None:
    applicability = issue.get("applicability")
    providers = (
        applicability.get("providers")
        if isinstance(applicability, dict)
        else None
    )
    if isinstance(providers, list) and len(providers) == 1:
        provider = str(providers[0] or "").strip()
        return provider or None
    return None


def _preparation_affected_task_titles(
    preparation: ContinuationResult,
) -> list[str]:
    task_value = getattr(preparation, "task", None)
    task = task_value if isinstance(task_value, dict) else {}
    workflow = task.get("workflow")
    candidates: list[Any] = []
    source_session = getattr(preparation, "source_session", None)
    source_title = (
        source_session.get("title")
        if isinstance(source_session, dict)
        else None
    )
    if isinstance(workflow, dict):
        candidates.extend([
            workflow.get("execution_task"),
            workflow.get("selected_intent"),
            *(workflow.get("affected_tasks") or []),
        ])
    if not any(candidates) and is_substantive_user_request(source_title):
        candidates.append(source_title)
    if not candidates:
        candidates.append(getattr(preparation, "objective", None))
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = (
            candidate.get("title") or candidate.get("objective")
            if isinstance(candidate, dict)
            else candidate
        )
        raw_title = " ".join(
            str(normalize_substantive_user_request(value) or "").split()
        )
        if not raw_title or not is_substantive_user_request(raw_title):
            continue
        title = _bounded_task(raw_title)
        key = title.casefold()
        if not title or key in seen:
            continue
        seen.add(key)
        result.append(title)
        if len(result) >= 12:
            break
    return result or ["Current continuation task"]


async def _refreshed_workflow_after_transition(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    access_scope: AccessScope,
    workflow: dict[str, Any] | None,
    transition: dict[str, Any],
) -> dict[str, Any] | None:
    if transition.get("status") not in {"completed", "already_completed"}:
        return None
    selected = (
        workflow.get("selected_intent")
        if isinstance(workflow, dict)
        else None
    )
    if not isinstance(selected, dict):
        return None
    selected_objective = str(
        selected.get("objective") or selected.get("title") or ""
    ).strip()
    if not selected_objective:
        return None
    try:
        resolution = await TaskWorkflowService(session).resolve(
            workspace_id=workspace_id,
            access_scope=access_scope,
            selected_objective=selected_objective,
            selected_component_id=selected.get("component_id"),
        )
    except Exception:
        transition["workflow_refresh"] = "unavailable"
        return None
    return resolution.workflow


def _repository_fingerprint(repository: dict[str, Any]) -> str:
    fingerprint = str(repository.get("status_fingerprint") or "").strip()
    if not fingerprint:
        raise ContinuationRunError(
            "continuation_repository_unavailable",
            "The repository snapshot could not be fingerprinted safely.",
        )
    return fingerprint


def _continuation_run_key(
    workspace_id: UUID,
    idempotency_key: str | None,
) -> str:
    if not idempotency_key:
        return f"continuation:{uuid4()}"
    digest = hashlib.sha256(
        f"{workspace_id}:{idempotency_key}".encode("utf-8")
    ).hexdigest()
    return f"continuation:{digest}"


def _duplicate_run_error(run: AgentRun) -> ContinuationRunError:
    return ContinuationRunError(
        "continuation_duplicate",
        (
            f"This Continue action is already {run.status}; "
            f"no second agent was started. Run ID: {run.id}."
        ),
        status_code=409,
    )


async def active_continuation_run(
    session: AsyncSession,
    *,
    workspace_id: UUID,
) -> AgentRun | None:
    return await session.scalar(
        select(AgentRun)
        .options(selectinload(AgentRun.observations))
        .where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.status.in_(("running", "staging")),
            AgentRun.run_key.like("continuation:%"),
        )
        .execution_options(populate_existing=True)
        .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
        .limit(1)
    )


def active_continuation_run_payload(run: AgentRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    tool = str(run.tool or "").strip().lower()
    provider = tool.rsplit(":", 1)[-1] if ":" in tool else tool
    session = harness_session_payload(run.observations)
    payload = {
        "run_id": str(run.id),
        "provider": provider or None,
        "model": run.model,
        "objective": run.objective,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "phase": (
            "awaiting_user"
            if run.status == "awaiting_user"
            else "loading_context"
            if run.status == "staging"
            else "agent_running"
            if session is not None
            else "starting_harness"
        ),
    }
    if run.status in {"staging", "awaiting_user"}:
        payload["execution_started"] = False
    if session is not None:
        payload["harness_session"] = session
    return payload


async def awaiting_continuation_handoff(
    session: AsyncSession,
    *,
    workspace_id: UUID,
) -> AgentRun | None:
    return await session.scalar(
        select(AgentRun)
        .options(selectinload(AgentRun.observations))
        .where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.status == "awaiting_user",
            AgentRun.run_key.like("continuation:%"),
        )
        .execution_options(populate_existing=True)
        .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
        .limit(1)
    )


async def reconcile_awaiting_continuation_handoffs(
    session: AsyncSession,
    *,
    workspace_id: UUID,
) -> int:
    """Close waiting state after an imported user message activates the thread."""

    runs = list(await session.scalars(
        select(AgentRun)
        .where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.status == "awaiting_user",
            AgentRun.provider_session_id.is_not(None),
            AgentRun.run_key.like("continuation:%"),
        )
        .order_by(AgentRun.started_at, AgentRun.id)
    ))
    reconciled = 0
    for run in runs:
        tool = str(run.tool or "").strip().lower()
        provider = tool.rsplit(":", 1)[-1] if ":" in tool else tool
        session_id = str(run.provider_session_id or "").strip()
        if provider not in PROVIDER_PREFERENCE or not session_id:
            continue
        conditions = [
            SessionEvent.workspace_id == workspace_id,
            SessionEvent.provider == provider,
            SessionEvent.session_id == session_id,
            SessionEvent.role == "user",
        ]
        activation = await session.scalar(
            select(SessionEvent)
            .where(*conditions)
            .order_by(
                SessionEvent.occurred_at,
                SessionEvent.created_at,
                SessionEvent.sequence_number,
            )
            .limit(1)
        )
        if activation is None:
            continue
        run.status = "handed_off"
        run.ended_at = activation.occurred_at or activation.created_at or utc_now()
        reconciled += 1
    if reconciled:
        await session.commit()
    return reconciled


def staged_continuation_payload(run: AgentRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    active = active_continuation_run_payload(run)
    if active is None:
        return None
    session = active.get("harness_session")
    if not isinstance(session, dict):
        return None
    provider = str(active.get("provider") or session.get("provider") or "").strip()
    run_id = str(active["run_id"])
    payload = {
        "schema_version": CONTINUATION_STAGE_SCHEMA_VERSION,
        "status": "awaiting_user",
        "execution_started": False,
        "delivery": {
            "status": "awaiting_user",
            "provider": provider or None,
            "run_id": run_id,
            "context_delivery": session.get("context_delivery"),
            "context_schema_version": session.get("context_schema_version"),
            "execution_started": False,
            "activation_boundary_verified": (
                session.get("activation_boundary_verified") is True
            ),
            "observed_turn_count": session.get("observed_turn_count", 0),
            "activation": "next_user_turn",
            "harness_session": session,
        },
        "run": {
            "run_id": run_id,
            "provider": provider or None,
            "model": run.model,
            "objective": run.objective,
            "status": run.status,
            "started_at": (
                run.started_at.isoformat() if run.started_at else None
            ),
            "provider_session_id": run.provider_session_id,
            "execution_started": False,
        },
    }
    identity = session.get("continuation_identity")
    if isinstance(identity, dict):
        payload["context_package"] = {
            "schema_version": "context_package_summary.v1",
            "continuation_identity": identity,
        }
    return payload


def _active_run_error(run: AgentRun) -> ContinuationRunError:
    active = active_continuation_run_payload(run) or {}
    provider = PROVIDER_DISPLAY_NAMES.get(
        str(active.get("provider") or ""),
        "Target agent",
    )
    objective = _bounded_task(run.objective or "Current continuation task")
    return ContinuationRunError(
        "continuation_already_running",
        (
            f"{provider} is already continuing this workspace. "
            f"No second agent was started. Run ID: {run.id}."
        ),
        status_code=409,
        blocker={
            "code": "continuation_already_running",
            "title": "Continuation already running",
            "provider": active.get("provider"),
            "message": (
                f"{provider} is still working on this continuation. "
                "No duplicate agent was started."
            ),
            "action": "Wait for the active run to finish, then retry if needed.",
            "affected_tasks": [objective],
            "active_run": active,
        },
    )


async def provider_readiness(
    *,
    force_refresh: bool = False,
) -> list[ProviderReadiness]:
    """Return bounded local readiness for every supported continuation provider."""

    global _provider_readiness_cache
    cache_key = (
        probe_provider_readiness,
        probe_harness_visibility,
    )
    now = monotonic()
    if (
        not force_refresh
        and _provider_readiness_cache is not None
        and _provider_readiness_cache[0] > now
        and _provider_readiness_cache[1] == cache_key
    ):
        return list(_provider_readiness_cache[2])

    cli_results, visibility_results = await asyncio.gather(
        asyncio.gather(*(
            asyncio.to_thread(probe_provider_readiness, provider)
            for provider in PROVIDER_PREFERENCE
        )),
        asyncio.gather(*(
            asyncio.to_thread(probe_harness_visibility, provider)
            for provider in PROVIDER_PREFERENCE
        )),
    )
    providers = [
        replace(
            _visible_provider_readiness(cli, visibility),
            capabilities=provider_capabilities(cli.provider).to_dict(),
        )
        for cli, visibility in zip(
            cli_results,
            visibility_results,
            strict=True,
        )
    ]
    _provider_readiness_cache = (
        monotonic() + PROVIDER_READINESS_CACHE_SECONDS,
        cache_key,
        tuple(providers),
    )
    return providers


async def _readiness_for(
    provider: ProviderName,
    *,
    provider_model: str | None = None,
) -> ProviderReadiness:
    cli, visibility = await asyncio.gather(
        asyncio.to_thread(
            probe_provider_readiness,
            provider,
            provider_model=provider_model,
        ),
        asyncio.to_thread(probe_harness_visibility, provider),
    )
    return _visible_provider_readiness(cli, visibility)


def _visible_provider_readiness(
    cli: ProviderReadiness,
    visibility: HarnessVisibility,
) -> ProviderReadiness:
    """Require both provider access and an exact visible execution surface."""

    values = {
        "provider": cli.provider,
        "ready": cli.ready,
        "status": cli.status,
        "code": cli.code,
        "message": cli.message,
        "action": cli.action,
        "models": cli.models,
        "desktop_available": visibility.desktop_available,
        "exact_session_supported": visibility.exact_session_supported,
        "context_staging_supported": (
            cli.provider == "codex"
            and cli.ready
            and visibility.ready
            and visibility.exact_session_supported
        ),
        "capabilities": cli.capabilities,
    }
    if cli.ready and not visibility.ready:
        values.update({
            "ready": False,
            "status": "unavailable",
            "code": visibility.code,
            "message": visibility.message,
            "action": visibility.action,
        })
    return ProviderReadiness(**values)


async def _select_ready_invocation(
    *,
    repo_path: str,
    target_provider: str,
    provider_model: str | None,
    provider_effort: str | None,
    current_task: str,
    contract: ContinuationExecutionContract,
    affected_tasks: list[str] | None = None,
) -> HarnessInvocation:
    normalized_target = _target_provider(target_provider)
    candidates = (
        PROVIDER_PREFERENCE
        if normalized_target == "auto"
        else (normalized_target,)
    )
    selected_models = tuple(
        continuation_provider_model(provider, provider_model)
        for provider in candidates
    )
    readiness_results = list(await asyncio.gather(*(
        _readiness_for(provider, provider_model=selected_model)
        for provider, selected_model in zip(
            candidates,
            selected_models,
            strict=True,
        )
    )))
    for index, (provider, selected_model, readiness) in enumerate(zip(
        candidates,
        selected_models,
        readiness_results,
        strict=True,
    )):
        if not readiness.ready:
            continue
        unsupported = [
            check
            for check in check_provider_capabilities(provider, contract)
            if not check.supported
        ]
        if unsupported:
            readiness_results[index] = replace(
                readiness,
                ready=False,
                status="unsupported_for_task",
                code="provider_capability_missing",
                message=" ".join(check.message for check in unsupported),
                action=(
                    "Choose a provider that can enforce every capability "
                    "required by this continuation."
                ),
                capabilities=provider_capabilities(provider).to_dict(),
            )
            continue
        try:
            return build_harness_invocation(
                provider,
                repo_path=repo_path,
                session_id=None,
                model=selected_model,
                effort=provider_effort,
                visible=provider == "codex",
                filesystem_mode=contract.authority.filesystem_mode.value,
            )
        except HarnessExecutableNotFound:
            readiness = ProviderReadiness(
                provider=provider,
                ready=False,
                status="unavailable",
                code="provider_cli_not_found",
                message=(
                    f"{PROVIDER_DISPLAY_NAMES[provider]} CLI disappeared "
                    "after its readiness check."
                ),
                action=(
                    f"Install the {PROVIDER_DISPLAY_NAMES[provider]} CLI "
                    "and try again."
                ),
            )
            if normalized_target != "auto":
                raise _provider_readiness_error(
                    readiness,
                    current_task=current_task,
                    explicit=True,
                    affected_tasks=affected_tasks,
                )
        except HarnessAdapterError as exc:
            raise ContinuationRunError(
                "continuation_delivery_invalid",
                str(exc),
            ) from exc

    if normalized_target != "auto":
        raise _provider_readiness_error(
            readiness_results[0],
            current_task=current_task,
            explicit=True,
            affected_tasks=affected_tasks,
        )
    provider_summaries = "; ".join(
        f"{item.provider}: {item.message}" for item in readiness_results
    )
    raise ContinuationRunError(
        "continuation_provider_unavailable",
        (
            "No supported local agent is both installed and authenticated. "
            f"{provider_summaries}"
        ),
        status_code=409,
        blocker={
            "code": "continuation_provider_unavailable",
            "provider": "auto",
            "message": "No supported local agent is ready.",
            "action": "Repair or authenticate one provider, then try again.",
            "affected_tasks": affected_tasks or [_bounded_task(current_task)],
        },
    )


def _target_provider(value: str | None) -> str:
    normalized = str(value or "auto").strip().lower()
    if normalized in {"claude_code", "claude-code"}:
        normalized = "claude"
    if normalized not in TARGET_PROVIDERS:
        raise ContinuationRunError(
            "continuation_provider_invalid",
            f"Unsupported target provider: {normalized or 'empty'}.",
        )
    return normalized


def _provider_readiness_error(
    readiness: ProviderReadiness,
    *,
    current_task: str,
    explicit: bool,
    affected_tasks: list[str] | None = None,
) -> ContinuationRunError:
    selection = "selected" if explicit else "available"
    return ContinuationRunError(
        "continuation_provider_not_ready",
        (
            f"The {selection} provider is not ready: "
            f"{readiness.message}"
        ),
        status_code=409,
        readiness=readiness.to_dict(),
        blocker={
            "code": readiness.code,
            "provider": readiness.provider,
            "message": readiness.message,
            "action": readiness.action,
            "affected_tasks": affected_tasks or [_bounded_task(current_task)],
        },
    )


def _normalized_source_provider(
    source_session: dict[str, Any] | None,
) -> str | None:
    provider = str((source_session or {}).get("provider") or "").strip().lower()
    if provider in {"claude_code", "claude-code"}:
        return "claude"
    return provider if provider in PROVIDER_PREFERENCE else None


def _harness_visibility_evidence(state: dict[str, Any]) -> dict[str, Any]:
    navigation_verified = state.get("navigation_verified") is True
    navigation_requested = state.get("navigation_requested") is True
    activity_observed = state.get("renderable_activity_observed") is True
    if navigation_verified and activity_observed:
        status = "observed_visible"
        message = "Renderable provider activity and exact navigation were observed."
    elif navigation_requested and activity_observed:
        status = "navigation_requested_unverified"
        message = (
            "Renderable provider activity was observed and navigation was "
            "requested, but the visible destination was not independently verified."
        )
    elif activity_observed:
        status = "activity_observed"
        message = (
            "Renderable provider activity was observed; visible navigation was "
            "not verified."
        )
    else:
        status = "session_captured"
        message = (
            "The provider session was captured; visible execution was not "
            "independently observed."
        )
    return {
        "status": status,
        "visible_execution_observed": (
            navigation_verified and activity_observed
        ),
        "renderable_activity_observed": activity_observed,
        "navigation_requested": navigation_requested,
        "navigation_verified": navigation_verified,
        "message": message,
    }


def _repairable(
    contract: ContinuationExecutionContract,
    *,
    matrix: RequirementVerificationMatrix,
    result: LocalHarnessResult,
    session_id: str,
) -> bool:
    if contract.task_mode is not TaskMode.CHANGE:
        return False
    if (
        matrix.verified
        or matrix.status == "execution_failed"
        or not matrix.bundle_integrity_passed
        or not matrix.preservation_passed
        or result.status != "completed"
        or not session_id
    ):
        return False
    return any(
        item.required and item.status == "failed"
        for item in matrix.evidence
    )


def _repair_progress_signature(
    matrix: RequirementVerificationMatrix,
    result: LocalHarnessResult,
) -> tuple[tuple[tuple[str, str], ...], str]:
    unmet = tuple(sorted(
        (item.requirement_id, item.status)
        for item in matrix.requirements
        if (
            item.priority == "must"
            and item.status != "passed"
        )
    ))
    return unmet, result.repository_after.status_fingerprint


def _contract_outcome(
    matrix: RequirementVerificationMatrix,
    *,
    result: LocalHarnessResult,
    provider: ProviderName,
    current_task: str,
    affected_tasks: list[str] | None = None,
    blocker_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = matrix.to_dict()
    blocker = blocker_override or matrix.blocker
    if matrix.status == "execution_failed":
        failed_count = sum(
            item.status == "failed"
            for item in matrix.evidence
        )
        blocker = _failed_run_blocker(
            result,
            provider=provider,
            current_task=current_task,
            failed_check_count=failed_count,
            affected_tasks=affected_tasks,
        )
    status = _terminal_contract_status(matrix.status, blocker)
    checks = [
        {
            "verifier_id": item.verifier_id,
            "requirement_ids": list(item.requirement_ids),
            "verifier_type": item.verifier_type,
            "required": item.required,
            "status": item.status,
            **item.details,
        }
        for item in matrix.evidence
    ]
    return {
        **payload,
        "status": status,
        "verified": status == "verified_complete",
        "run_status": result.status,
        "completion_evidence": (
            "all_mandatory_requirements_observed"
            if status == "verified_complete"
            else "external_blocker_observed"
            if status == "blocked_external"
            else "task_ambiguity_observed"
            if status == "blocked_ambiguity"
            else "worker_execution_failed"
            if matrix.status == "execution_failed"
            else "mandatory_requirements_not_proven"
        ),
        "agent_changed_files": list(result.agent_changed_files),
        "changed_files": list(result.changed_files),
        "checks": {
            "status": (
                "passed"
                if checks and all(item["status"] == "passed" for item in checks)
                else "failed"
                if any(item["status"] == "failed" for item in checks)
                else "unproven"
            ),
            "total": len(checks),
            "passed": sum(item["status"] == "passed" for item in checks),
            "failed": sum(item["status"] == "failed" for item in checks),
            "unproven": sum(
                item["status"] not in {"passed", "failed"}
                for item in checks
            ),
            "items": checks,
        },
        **({"blocker": blocker} if blocker is not None else {}),
    }


def _terminal_contract_status(
    matrix_status: str,
    blocker: Mapping[str, Any] | None,
) -> str:
    code = (
        str(blocker.get("code") or "").strip()
        if isinstance(blocker, Mapping)
        else ""
    )
    if code in EXTERNAL_BLOCKER_CODES:
        return "blocked_external"
    if code in AMBIGUITY_BLOCKER_CODES:
        return "blocked_ambiguity"
    return matrix_status


def _outcome(
    result: LocalHarnessResult,
    *,
    provider: ProviderName,
    current_task: str,
    affected_tasks: list[str] | None = None,
) -> dict[str, Any]:
    agent_changed_files = tuple(
        getattr(result, "agent_changed_files", result.changed_files)
    )
    check_items = []
    for verification in result.verification_results:
        command_result = verification.result
        passed = command_result.exit_code == 0 and not command_result.timed_out
        check_items.append({
            "requirement_id": verification.requirement_id,
            "command": verification.command,
            "cwd": verification.cwd,
            "status": "passed" if passed else "failed",
            "exit_code": command_result.exit_code,
            "timed_out": command_result.timed_out,
        })
    passed_count = sum(item["status"] == "passed" for item in check_items)
    failed_count = sum(item["status"] == "failed" for item in check_items)
    if failed_count:
        checks_status = "failed"
    elif check_items:
        checks_status = "passed"
    else:
        checks_status = "not_available"

    blocker = None
    if result.status == "failed":
        blocker = _failed_run_blocker(
            result,
            provider=provider,
            current_task=current_task,
            failed_check_count=failed_count,
            affected_tasks=affected_tasks,
        )
        status = (
            "blocked_external"
            if blocker["code"] in {
                "provider_authentication_failed",
                "provider_authentication_revoked",
                "provider_billing_required",
                "provider_cli_update_required",
                "provider_service_unavailable",
            }
            else "execution_failed"
        )
    else:
        # This compatibility evaluator has no typed requirement-to-proof
        # lineage. Even passing checks plus a diff cannot establish semantic
        # completion.
        status = "requirements_unproven"
    if result.status == "failed":
        completion_evidence = "agent_run_failed"
    elif checks_status == "passed" and not agent_changed_files:
        completion_evidence = "checks_passed_without_repository_changes"
    elif checks_status == "passed":
        completion_evidence = "legacy_checks_and_changes_without_requirement_lineage"
    elif checks_status == "not_available":
        completion_evidence = "required_checks_not_available"
    else:
        completion_evidence = "required_checks_failed"
    return {
        "status": status,
        "run_status": result.status,
        "verified": False,
        "completion_evidence": completion_evidence,
        "agent_changed_files": list(agent_changed_files),
        "changed_files": list(result.changed_files),
        "checks": {
            "status": checks_status,
            "total": len(check_items),
            "passed": passed_count,
            "failed": failed_count,
            "items": check_items,
        },
        **({"blocker": blocker} if blocker is not None else {}),
    }


def _failed_run_blocker(
    result: LocalHarnessResult,
    *,
    provider: ProviderName,
    current_task: str,
    failed_check_count: int,
    affected_tasks: list[str] | None = None,
) -> dict[str, Any]:
    display_name = PROVIDER_DISPLAY_NAMES[provider]
    command_result = getattr(result, "command", None)
    billing_failure = _provider_billing_failure(command_result, provider)
    service_failure = _provider_service_failure(command_result, provider)
    auth_failure = _provider_auth_failure(command_result, provider)
    cli_failure = _provider_cli_compatibility_failure(command_result, provider)
    invocation_failure = _provider_invocation_failure(command_result, provider)
    if invocation_failure is not None:
        code = "provider_invocation_invalid"
        message = invocation_failure
        action = (
            "Update DaemonState to the corrected OpenCode invocation and "
            "retry the continuation."
        )
    elif cli_failure is not None:
        code = "provider_cli_update_required"
        message = cli_failure
        action = (
            "Upgrade Codex CLI or configure DaemonState to use a current "
            "Codex executable, then retry."
        )
    elif billing_failure:
        code = "provider_billing_required"
        message = (
            "OpenCode cannot use the selected model because its provider "
            "account has insufficient balance or billing is not enabled."
        )
        action = (
            "Add credits or enable billing for that OpenCode provider, or "
            "choose another configured model."
        )
    elif service_failure is not None:
        code = "provider_service_unavailable"
        http_detail = (
            f" (HTTP {service_failure})"
            if service_failure
            else ""
        )
        message = (
            "OpenCode's selected model provider is temporarily unavailable"
            f"{http_detail}."
        )
        action = "Retry later or choose another configured model."
    elif auth_failure == "revoked":
        code = "provider_authentication_revoked"
        message = (
            f"{display_name} authentication failed because its OAuth token "
            "has been revoked (401)."
        )
        action = PROVIDER_AUTH_ACTIONS[provider]
    elif auth_failure == "authentication":
        code = "provider_authentication_failed"
        message = f"{display_name} authentication failed."
        action = PROVIDER_AUTH_ACTIONS[provider]
    elif bool(getattr(command_result, "timed_out", False)):
        code = "provider_run_timed_out"
        message = f"{display_name} did not finish before the execution timeout."
        action = f"Inspect the {display_name} run and retry the continuation."
    elif failed_check_count:
        code = "continuation_checks_failed"
        message = (
            f"{failed_check_count} required verification "
            f"{'check' if failed_check_count == 1 else 'checks'} failed."
        )
        action = "Inspect the failed checks, fix the repository, and retry."
    else:
        exit_code = getattr(command_result, "exit_code", None)
        suffix = f" with exit code {exit_code}" if isinstance(exit_code, int) else ""
        code = "provider_run_failed"
        message = f"{display_name} failed to complete the continuation{suffix}."
        action = f"Inspect the {display_name} run details and retry."
    return {
        "code": code,
        "provider": provider,
        "message": message,
        "action": action,
        "affected_tasks": affected_tasks or [_bounded_task(current_task)],
    }


def _provider_billing_failure(
    command_result: Any,
    provider: ProviderName,
) -> bool:
    if provider != "opencode":
        return False

    stdout = str(getattr(command_result, "stdout", "") or "")
    if any(
        _billing_failure_text(error_text)
        for error_text in _structured_error_details(stdout)
    ):
        return True

    stderr = str(getattr(command_result, "stderr", "") or "")
    normalized_stderr = stderr.casefold()
    return (
        "creditserror" in normalized_stderr
        and _billing_failure_text(stderr)
    )


def _billing_failure_text(value: str) -> bool:
    normalized = str(value or "").casefold()
    if _provider_http_status(normalized) == 402:
        return True
    return any(
        marker in normalized
        for marker in (
            "creditserror",
            "insufficient balance",
            "insufficient credit",
            "credits exhausted",
            "credit balance exhausted",
            "no available credit",
            "no credits",
            "not enough credits",
            "out of credit",
            "billing is not enabled",
            "billing not enabled",
            "billing required",
            "enable billing",
            "billing details required",
            "payment required",
            "payment is required",
            "payment method required",
            "no payment method",
            "add a payment method",
        )
    )


def _provider_service_failure(
    command_result: Any,
    provider: ProviderName,
) -> int | None:
    if provider != "opencode":
        return None

    stdout = str(getattr(command_result, "stdout", "") or "")
    for error_text in _structured_error_details(stdout):
        status = _provider_http_status(error_text)
        if status is not None and 500 <= status <= 599:
            return status
        if "internal server error" in error_text.casefold():
            return 500
    return None


def _provider_http_status(value: str) -> int | None:
    normalized = str(value or "").casefold()
    for pattern in (
        r'\\?"statuscode\\?"\s*:\s*(\d{3})',
        r'\\?"status\\?"\s*:\s*(\d{3})',
        r"\bhttp(?:\s+status)?\s*(\d{3})\b",
    ):
        match = re.search(pattern, normalized)
        if match:
            return int(match.group(1))
    return None


def _provider_invocation_failure(
    command_result: Any,
    provider: ProviderName,
) -> str | None:
    """Recognize DaemonState/provider CLI contract failures without leaking logs."""

    if provider != "opencode":
        return None
    exit_code = getattr(command_result, "exit_code", None)
    if not isinstance(exit_code, int) or exit_code == 0:
        return None
    output = "\n".join((
        str(getattr(command_result, "stdout", "") or ""),
        str(getattr(command_result, "stderr", "") or ""),
    )).casefold()
    if (
        "file not found:" in output
        and "continue the task using the attached " in output
        and " context pack. verify the current repository state before editing"
        in output
    ):
        return (
            "DaemonState constructed an invalid OpenCode command: OpenCode "
            "treated the continuation message as another attachment."
        )
    return None


def _provider_cli_compatibility_failure(
    command_result: Any,
    provider: ProviderName,
) -> str | None:
    if provider != "codex":
        return None
    exit_code = getattr(command_result, "exit_code", None)
    if not isinstance(exit_code, int) or exit_code == 0:
        return None

    stdout = str(getattr(command_result, "stdout", "") or "")
    for error_text in _structured_error_payloads(stdout):
        normalized = error_text.casefold()
        if (
            "requires a newer version of codex" in normalized
            or "please upgrade to the latest app or cli" in normalized
        ):
            model_match = re.search(
                r"([a-z0-9][a-z0-9._:-]{1,100})['`\\\"]?\s+model "
                r"requires a newer version of codex",
                normalized,
            )
            if model_match:
                return (
                    "Codex could not start because the installed CLI is too old "
                    f"for the configured `{model_match.group(1)}` model."
                )
            return (
                "Codex could not start because the configured model requires "
                "a newer Codex CLI."
            )

    stderr = str(getattr(command_result, "stderr", "") or "").casefold()
    if (
        "codex_models_manager::cache" in stderr
        and "supports_reasoning_summaries" in stderr
    ):
        return (
            "Codex could not start because its model cache is newer than the "
            "installed CLI understands."
        )
    return None


def _provider_auth_failure(
    command_result: Any,
    provider: ProviderName,
) -> str | None:
    exit_code = getattr(command_result, "exit_code", None)
    if not isinstance(exit_code, int):
        return None

    stderr = str(getattr(command_result, "stderr", "") or "")
    stdout = str(getattr(command_result, "stdout", "") or "")
    structured_errors = _structured_error_payloads(stdout)
    if exit_code == 0 and not structured_errors:
        return None
    failure = _auth_failure_kind(stderr, provider)
    if failure is not None:
        return failure
    for error_text in structured_errors:
        failure = _auth_failure_kind(error_text, provider, structured=True)
        if failure is not None:
            return failure
    return None


def _auth_failure_kind(
    output: str,
    provider: ProviderName,
    *,
    structured: bool = False,
) -> str | None:
    normalized = output.casefold()
    if not normalized:
        return None
    provider_markers = {
        "codex": ("codex", "openai", "chatgpt"),
        "claude": ("claude", "anthropic"),
        "opencode": ("opencode",),
    }[provider]
    error_shape = structured or any(
        marker in normalized
        for marker in (
            "api error",
            "authentication_error",
            "authentication failed",
            "authentication required",
            "error authenticating",
            "oauth error",
            "login required",
            '"error"',
        )
    ) or bool(re.search(r"(^|\n)\s*(error|fatal)\s*:", normalized))
    error_shape = error_shape or any(
        marker in normalized for marker in provider_markers
    )
    if not error_shape:
        return None

    auth_context = any(
        marker in normalized
        for marker in (
            "auth",
            "oauth",
            "token",
            "api key",
            "apikey",
            "login",
            "logged in",
            "invalid_grant",
        )
    )
    if (
        "revoked" in normalized
        and ("oauth" in normalized or "token" in normalized)
        and auth_context
    ):
        return "revoked"
    auth_markers = (
        "authentication_error",
        "authentication failed",
        "authentication required",
        "error authenticating",
        "not logged in",
        "please log in",
        "please login",
        "invalid oauth",
        "invalid_grant",
        "token expired",
        "invalid api key",
        "incorrect api key",
    )
    if any(marker in normalized for marker in auth_markers):
        return "authentication"
    if (
        ("401" in normalized or "unauthorized" in normalized)
        and auth_context
    ):
        return "authentication"
    return None


def _structured_error_payloads(output: str) -> list[str]:
    return [
        json.dumps(payload, sort_keys=True, default=str)[:8_192]
        for payload in _structured_error_objects(output)
    ]


def _structured_error_details(output: str) -> list[str]:
    return [
        "\n".join(_error_signal_values(payload))[:8_192]
        for payload in _structured_error_objects(output)
    ]


def _structured_error_objects(output: str) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for line in output.splitlines()[:200]:
        normalized = line.strip()
        if not normalized:
            continue
        try:
            payload = json.loads(normalized)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        payload_type = str(payload.get("type") or "").casefold()
        subtype = str(payload.get("subtype") or "").casefold()
        is_error = (
            payload.get("is_error") is True
            or payload_type in {"error", "error_message"}
            or subtype.startswith("error")
            or bool(payload.get("error"))
        )
        if is_error:
            errors.append(payload)
    return errors


def _error_signal_values(value: Any) -> list[str]:
    signals: list[str] = []
    signal_fields = {
        "code",
        "message",
        "name",
        "responsebody",
        "status",
        "statuscode",
        "type",
    }
    container_fields = {"cause", "data", "error", "response"}
    ignored_fields = {
        "input",
        "messages",
        "prompt",
        "request",
        "requestbody",
        "requestbodyvalues",
    }

    def visit(item: Any, *, field: str = "") -> None:
        if isinstance(item, Mapping):
            for raw_key, nested in item.items():
                key = str(raw_key).casefold()
                if key in ignored_fields:
                    continue
                if key in signal_fields:
                    if isinstance(nested, (Mapping, list, tuple)):
                        visit(nested, field=key)
                    else:
                        signals.append(str(nested))
                elif key in container_fields:
                    visit(nested, field=key)
            return
        if isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested, field=field)
            return
        if field in signal_fields:
            signals.append(str(item))

    visit(value)
    return signals


def _bounded_task(value: str | None) -> str:
    normalized = " ".join(
        str(normalize_substantive_user_request(value) or "").split()
    )
    if not normalized:
        return "Current continuation task"
    if len(normalized) <= MAX_BLOCKER_TASK_LENGTH:
        return normalized
    return f"{normalized[:MAX_BLOCKER_TASK_LENGTH - 1].rstrip()}…"
