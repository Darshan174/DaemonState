from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import AgentRun, ContinuationExecution, SessionEvent
from app.models_continuation_stage import ContinuationStageRequest
from app.schemas.continuation_execution import (
    ContinuationArtifactInput,
    ContinuationExecutionContract,
    TaskMode,
)
from app.services.access import AccessScope
from app.services.checkpoint_verifier import compare_checkpoint_repository
from app.services.checkpoints import (
    SESSION_HANDOFF_SCHEMA_VERSION,
    build_session_handoff_artifact,
    checkpoint_to_dict,
    checkpoints_to_dicts,
    get_checkpoint,
    resolve_session_handoff_attachment_descriptors,
    resolve_session_handoff_request_verbatim,
    resolve_session_handoff_supporting_context,
)
from app.services.continuation import ContinuationResult, ContinuationService
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
)
from app.services.harness_launcher import (
    HarnessComposerReadiness,
    HarnessLaunchError,
    HarnessVisibility,
    launch_harness_composer,
    probe_harness_composer_readiness,
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
COMPOSER_READINESS_TIMEOUT_SECONDS = 3.0
CONTINUATION_STAGE_PENDING_LEASE_SECONDS = 60.0
DESKTOP_ACCESS_CONFIRMATION = "user_confirmed_usable_in_desktop"
_DESKTOP_STAGE_ADVISORY_QUALITY_CODES = frozenset({
    "project_context_core_sections_empty",
})
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
    preparation: ContinuationResult | dict[str, Any]
    delivery: dict[str, Any]
    run: dict[str, Any]
    schema_version: str = CONTINUATION_STAGE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        preparation = (
            self.preparation.to_dict()
            if isinstance(self.preparation, ContinuationResult)
            else dict(self.preparation)
        )
        return {
            "schema_version": self.schema_version,
            "status": "awaiting_user",
            "execution_started": False,
            "preparation": preparation,
            "delivery": self.delivery,
            "run": self.run,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContinuationStageResult:
        preparation = value.get("preparation")
        delivery = value.get("delivery")
        run = value.get("run")
        if not all(
            isinstance(item, dict)
            for item in (preparation, delivery, run)
        ):
            raise ValueError("Stored continuation stage result is incomplete.")
        return cls(
            preparation=dict(preparation),
            delivery=dict(delivery),
            run=dict(run),
            schema_version=str(
                value.get("schema_version")
                or CONTINUATION_STAGE_SCHEMA_VERSION
            ),
        )


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
    payload = result.to_dict()
    delivery = payload.get("delivery", {})
    run = payload.get("run", {})
    preparation = payload.get("preparation", {})
    return {
        "daemonstate.context_pack.id": preparation.get("context_pack_id"),
        "daemonstate.continuation.execution.id": (
            preparation.get("continuation_execution_id")
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
    """Load the latest lead-bound Session Context and wait for user authorization."""

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
        desktop_access_confirmation: Mapping[str, str] | None = None,
        task_mode: TaskMode | str | None = None,
        artifacts: tuple[ContinuationArtifactInput, ...] = (),
        token_budget: int | None = None,
        idempotency_key: str | None = None,
        sync_sessions: bool = False,
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
                    "or checkpoint before loading Session Context. Task-relevant "
                    "retrieval cannot be compiled for an unknown future "
                    "instruction."
                ),
                status_code=422,
                blocker={
                    "code": "continuation_lead_required",
                    "title": "Immediate lead required",
                    "message": (
                        "Session Context has not been staged because no "
                        "substantive immediate lead was supplied."
                    ),
                    "action": (
                        "Enter or confirm the task, or select its exact source "
                        "session or checkpoint, then load Session Context."
                    ),
                    "affected_tasks": [],
                },
            )
        if not str(idempotency_key or "").strip():
            raise ContinuationRunError(
                "continuation_idempotency_key_required",
                (
                    "Desktop Continue requires an idempotency key so retries "
                    "cannot send duplicate open requests."
                ),
                status_code=422,
                blocker={
                    "code": "continuation_idempotency_key_required",
                    "title": "Safe retry key required",
                    "message": (
                        "No desktop handoff was requested because this action "
                        "did not include its duplicate-protection key."
                    ),
                    "action": "Refresh the Continue page, then try again.",
                    "affected_tasks": [
                        _bounded_task(objective or "Current continuation task")
                    ],
                },
            )

        normalized_target = _target_provider(target_provider)
        confirmed_access_provider = _desktop_access_confirmation_provider(
            desktop_access_confirmation
        )
        if confirmed_access_provider is not None:
            if normalized_target == "auto":
                raise ContinuationRunError(
                    "desktop_access_confirmation_requires_exact_provider",
                    (
                        "Desktop access confirmation must name the exact "
                        "selected provider. No desktop app was opened."
                    ),
                    status_code=422,
                    blocker={
                        "code": (
                            "desktop_access_confirmation_requires_exact_provider"
                        ),
                        "title": "Choose the confirmed desktop app",
                        "provider": confirmed_access_provider,
                        "message": (
                            "A request-scoped access confirmation cannot be "
                            "used with automatic provider selection."
                        ),
                        "action": (
                            f"Choose {PROVIDER_DISPLAY_NAMES[
                                confirmed_access_provider
                            ]} explicitly, then confirm access again."
                        ),
                        "affected_tasks": [_bounded_task(
                            objective or "Current continuation task"
                        )],
                    },
                )
            if confirmed_access_provider != normalized_target:
                raise ContinuationRunError(
                    "desktop_access_confirmation_provider_mismatch",
                    (
                        "Desktop access was confirmed for a different "
                        "provider. No desktop app was opened."
                    ),
                    status_code=422,
                    blocker={
                        "code": (
                            "desktop_access_confirmation_provider_mismatch"
                        ),
                        "title": "Desktop confirmation does not match",
                        "provider": normalized_target,
                        "message": (
                            f"The confirmation names "
                            f"{PROVIDER_DISPLAY_NAMES[
                                confirmed_access_provider
                            ]}, but the request targets "
                            f"{PROVIDER_DISPLAY_NAMES[normalized_target]}."
                        ),
                        "action": (
                            "Confirm access in the same desktop app selected "
                            "for this handoff."
                        ),
                        "affected_tasks": [_bounded_task(
                            objective or "Current continuation task"
                        )],
                    },
                )
        stage_request_sha256 = _continuation_stage_request_sha256(
            repo_path=repo_path,
            objective=objective,
            objective_is_user_edited=objective_is_user_edited,
            checkpoint_id=checkpoint_id,
            checkpoint_source_id=checkpoint_source_id,
            source_provider=source_provider,
            source_session_id=source_session_id,
            target_model=target_model,
            target_provider=normalized_target,
            provider_model=provider_model,
            provider_effort=provider_effort,
            desktop_access_confirmation=desktop_access_confirmation,
            task_mode=task_mode,
            artifacts=artifacts,
            token_budget=token_budget,
        )
        if idempotency_key:
            existing_stage_request = await _continuation_stage_request(
                self.session,
                workspace_id=workspace_id,
                idempotency_key=idempotency_key,
            )
            if existing_stage_request is not None:
                if (
                    existing_stage_request.status == "pending"
                    and _continuation_stage_pending_expired(
                        existing_stage_request
                    )
                ):
                    await _abandon_continuation_stage_pending(
                        self.session,
                        existing_stage_request,
                    )
                    raise _uncertain_continuation_stage_error(
                        existing_stage_request
                    )
                return _replay_continuation_stage_request(
                    existing_stage_request,
                    request_sha256=stage_request_sha256,
                )
        await _guard_continuation_stage_pending(
            self.session,
            workspace_id=workspace_id,
        )

        candidates = (
            PROVIDER_PREFERENCE
            if normalized_target == "auto"
            else (normalized_target,)
        )
        composer_readiness = list(await asyncio.gather(*(
            _bounded_composer_readiness(provider)
            for provider in candidates
        )))
        selected = next(
            (
                (provider, readiness)
                for provider, readiness in zip(
                    candidates,
                    composer_readiness,
                    strict=True,
                )
                if (
                    readiness.ready
                    or _desktop_access_confirmation_allows(
                        provider,
                        readiness,
                        confirmed_access_provider=confirmed_access_provider,
                    )
                )
            ),
            None,
        )
        if selected is None:
            readiness = composer_readiness[0]
            provider = candidates[0]
            raise ContinuationRunError(
                readiness.code,
                (
                    f"{PROVIDER_DISPLAY_NAMES[provider]} Desktop is required "
                    "for this continuation. No provider CLI or task was started."
                ),
                status_code=409,
                blocker={
                    "code": readiness.code,
                    "title": "Desktop composer unavailable",
                    "provider": provider,
                    "message": readiness.message,
                    "action": readiness.action,
                    "affected_tasks": [_bounded_task(
                        objective or "Current continuation task"
                    )],
                },
            )
        selected_provider, selected_composer_readiness = selected
        access_user_confirmed = (
            not selected_composer_readiness.ready
            and _desktop_access_confirmation_allows(
                selected_provider,
                selected_composer_readiness,
                confirmed_access_provider=confirmed_access_provider,
            )
        )
        if (
            str(provider_effort or "").strip()
            and selected_provider != "codex"
        ):
            raise ContinuationRunError(
                "provider_effort_unsupported",
                (
                    "Reasoning effort can be requested only for Codex "
                    "Desktop. No desktop app was opened."
                ),
                status_code=422,
                blocker={
                    "code": "provider_effort_unsupported",
                    "title": "Reasoning effort is Codex-only",
                    "provider": selected_provider,
                    "message": (
                        f"{PROVIDER_DISPLAY_NAMES[selected_provider]} does not "
                        "accept the Codex reasoning-effort setting."
                    ),
                    "action": (
                        "Remove the reasoning-effort selection or choose Codex."
                    ),
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
            # Browser-triggered desktop handoff must not scan provider-owned
            # session stores or start any provider process.
            sync_sessions=False,
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
        session_context = await _canonical_session_context_for_preparation(
            self.session,
            preparation,
            contract=contract,
            workspace_id=workspace_id,
            access_scope=access_scope,
        )
        context_message = _staging_context_for_preparation(
            preparation,
            contract=contract,
            expected_lead=objective or contract.task.request_verbatim,
            session_context=session_context,
        )

        try:
            repository_after = await capture_repository_snapshot(
                effective_repo_path
            )
            if repository_after.status_fingerprint != expected_fingerprint:
                raise RepositoryStateChangedError(
                    expected_fingerprint,
                    repository_after.status_fingerprint,
                )
        except RepositoryStateChangedError as exc:
            raise ContinuationRunError(
                "continuation_repository_changed",
                (
                    "Repository state changed while the desktop handoff was "
                    "being prepared. No provider task was started."
                ),
                status_code=409,
            ) from exc

        # Persist only the prepared context and a launch reservation.
        # A provider run/session does not exist until the user submits the
        # visible desktop draft. The reservation is committed before opening
        # Desktop so a retried request cannot open a second composer.
        stage_request: ContinuationStageRequest | None = None
        if idempotency_key:
            stage_request, claimed = await _claim_continuation_stage_request(
                self.session,
                workspace_id=workspace_id,
                context_pack_id=UUID(preparation.context_pack_id),
                continuation_execution_id=UUID(
                    preparation.continuation_execution_id
                ),
                idempotency_key=idempotency_key,
                request_sha256=stage_request_sha256,
                target_provider=selected_provider,
            )
            if not claimed:
                return _replay_continuation_stage_request(
                    stage_request,
                    request_sha256=stage_request_sha256,
                )
        else:
            await self.session.commit()
        timeout_seconds = max(
            1.0,
            min(
                request_timeout_seconds
                if request_timeout_seconds is not None
                else 20.0,
                30.0,
            ),
        )
        try:
            launch = await asyncio.wait_for(
                asyncio.to_thread(
                    launch_harness_composer,
                    selected_provider,
                    cwd=effective_repo_path,
                    prompt=context_message,
                ),
                timeout=timeout_seconds,
            )
            if (
                launch.get("open_requested") is not True
                or launch.get("context_copied") is not True
            ):
                raise HarnessLaunchError(
                    (
                        "The desktop open request and complete clipboard copy "
                        "were not both confirmed."
                    ),
                    code="desktop_handoff_unconfirmed",
                )
        except asyncio.CancelledError:
            # asyncio cancellation does not stop a worker already running in
            # to_thread(). Keep the unique pending reservation in place until
            # its lease expires, well after the launcher's own hard deadline,
            # so a fast retry cannot race a late desktop-open request.
            raise
        except TimeoutError as exc:
            error = ContinuationRunError(
                "desktop_handoff_timeout",
                (
                    f"{PROVIDER_DISPLAY_NAMES[selected_provider]} Desktop open "
                    "request timed out. No provider task was started."
                ),
                status_code=504,
                blocker={
                    "code": "desktop_handoff_timeout",
                    "title": "Desktop open request timed out",
                    "provider": selected_provider,
                    "message": (
                        "The visible desktop handoff request timed out. No "
                        "provider CLI or task was started."
                    ),
                    "action": "Open the desktop app, then retry Continue.",
                    "affected_tasks": _preparation_affected_task_titles(
                        preparation
                    ),
                },
            )
            # A timed-out to_thread worker can still be winding down. Keep the
            # row pending so another key cannot dispatch until the bounded
            # stale-reservation recovery path has warned the user.
            raise error from exc
        except HarnessLaunchError as exc:
            error = ContinuationRunError(
                exc.code,
                f"{exc} No provider task was started.",
                status_code=409,
                blocker={
                    "code": exc.code,
                    "title": "Desktop handoff failed",
                    "provider": selected_provider,
                    "message": str(exc),
                    "action": (
                        f"Open {PROVIDER_DISPLAY_NAMES[selected_provider]} "
                        "Desktop, then retry Continue."
                    ),
                    "affected_tasks": _preparation_affected_task_titles(
                        preparation
                    ),
                },
            )
            if stage_request is not None:
                await _record_continuation_stage_error(
                    self.session,
                    stage_request,
                    error,
                )
            raise error from exc

        context_sha256 = hashlib.sha256(
            context_message.encode("utf-8")
        ).hexdigest()
        handoff_id = str(uuid4())
        source = _normalized_source_provider(preparation.source_session)
        account_access_state = (
            "user_confirmed"
            if access_user_confirmed
            else selected_composer_readiness.account_access_state
        )
        account_access_verified = (
            selected_composer_readiness.account_access_verified is True
        )
        account_access_basis = (
            "request_attestation"
            if access_user_confirmed
            else (
                "provider_desktop_bridge"
                if account_access_verified
                else None
            )
        )
        public_handoff: dict[str, Any] = {
            "handoff_id": handoff_id,
            "provider": selected_provider,
            "cwd": effective_repo_path,
            "launched": False,
            "open_requested": launch.get("open_requested") is True,
            "open_verified": False,
            "navigation_requested": (
                launch.get("navigation_requested") is True
            ),
            "navigation_verified": False,
            "mode": "desktop_composer",
            "navigation": "new_session",
            "exact_session_supported": False,
            "awaiting_user": True,
            "execution_started": False,
            "context_loaded": False,
            "prefill_requested": launch.get("prefill_requested") is True,
            "context_copied": launch.get("context_copied") is True,
            "context_delivery": launch.get("context_delivery"),
            "context_sha256": context_sha256,
            "context_schema_version": SESSION_HANDOFF_SCHEMA_VERSION,
            "context_scope": "session",
            "source_session_id": (
                preparation.source_session.get("session_id")
                if isinstance(preparation.source_session, dict)
                else None
            ),
            "requested_provider_model": provider_model,
            "requested_provider_effort": provider_effort,
            "settings_applied": False,
            "settings_confirmation_required": bool(
                provider_model or provider_effort
            ),
            "account_access_state": account_access_state,
            "account_access_verified": account_access_verified,
            "account_access_basis": account_access_basis,
        }
        delivery = {
            "status": "awaiting_user",
            "provider": selected_provider,
            "source_provider": source,
            "source_session_id": (
                preparation.source_session.get("session_id")
                if isinstance(preparation.source_session, dict)
                else None
            ),
            "provider_switched": bool(
                source and source != selected_provider
            ),
            "mode": "desktop_composer_prefill",
            "context_delivery": launch.get("context_delivery"),
            "context_schema_version": SESSION_HANDOFF_SCHEMA_VERSION,
            "context_scope": "session",
            "context_sha256": context_sha256,
            "execution_started": False,
            "activation_boundary_verified": False,
            "activation": "user_review_and_submit",
            "handoff_id": handoff_id,
            "provider_model": None,
            "provider_effort": None,
            "requested_provider_model": provider_model,
            "requested_provider_effort": provider_effort,
            "settings_applied": False,
            "settings_confirmation_required": bool(
                provider_model or provider_effort
            ),
            "account_access_state": account_access_state,
            "account_access_verified": account_access_verified,
            "account_access_basis": account_access_basis,
            "task_mode": contract.task_mode.value,
            "filesystem_mode": contract.authority.filesystem_mode.value,
            "harness_session": public_handoff,
            "visibility": {
                "status": "desktop_composer_open_requested",
                "context_loaded": False,
                "context_copied": launch.get("context_copied") is True,
                "prefill_requested": (
                    launch.get("prefill_requested") is True
                ),
                "execution_started": False,
                "open_requested": launch.get("open_requested") is True,
                "open_verified": False,
                "navigation_requested": (
                    launch.get("navigation_requested") is True
                ),
                "navigation_verified": False,
                "message": (
                    (
                        f"{PROVIDER_DISPLAY_NAMES[selected_provider]} Desktop "
                        "open was requested with a reviewable draft. The "
                        "complete context is also on the clipboard. Opening is "
                        "not verified and nothing was submitted."
                    )
                    + (
                        " Requested model settings must be confirmed in the "
                        "desktop app."
                        if provider_model or provider_effort
                        else ""
                    )
                    if launch.get("prefill_requested") is True
                    else (
                        (
                            f"{PROVIDER_DISPLAY_NAMES[selected_provider]} "
                            "Desktop open was requested and the complete "
                            "context was copied. Opening is not verified; paste "
                            "it into the composer if needed. Nothing was "
                            "submitted."
                        )
                        + (
                            " Requested model settings must be confirmed in "
                            "the desktop app."
                            if provider_model or provider_effort
                            else ""
                        )
                    )
                ),
            },
        }
        result = ContinuationStageResult(
            preparation=preparation,
            delivery=delivery,
            run={
                "handoff_id": handoff_id,
                "status": "awaiting_user",
                "provider": selected_provider,
                "provider_session_id": None,
                "objective": preparation.objective,
                "started_at": utc_now().isoformat(),
                "execution_started": False,
                "provider_model": None,
                "provider_effort": None,
                "requested_provider_model": provider_model,
                "requested_provider_effort": provider_effort,
                "settings_applied": False,
                "account_access_state": account_access_state,
                "account_access_verified": account_access_verified,
                "account_access_basis": account_access_basis,
            },
        )
        if stage_request is not None:
            stage_request.status = "succeeded"
            stage_request.response_json = json.dumps(
                result.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                default=_continuation_stage_json_default,
            )
            await asyncio.shield(self.session.commit())
        return result


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


async def _canonical_session_context_for_preparation(
    session: AsyncSession,
    preparation: ContinuationResult,
    *,
    contract: ContinuationExecutionContract,
    workspace_id: UUID,
    access_scope: AccessScope,
) -> dict[str, Any]:
    """Compile the canonical latest-checkpoint Session Context for Continue."""

    checkpoint_summary = (
        preparation.checkpoint
        if isinstance(preparation.checkpoint, dict)
        else {}
    )
    checkpoint_id = str(checkpoint_summary.get("id") or "").strip()
    try:
        parsed_checkpoint_id = UUID(checkpoint_id)
    except (TypeError, ValueError) as exc:
        raise ContinuationRunError(
            "session_context_unavailable",
            (
                "The latest session has no canonical checkpoint-backed "
                "Session Context. No desktop app was opened."
            ),
            status_code=409,
        ) from exc
    checkpoint = await get_checkpoint(session, parsed_checkpoint_id)
    if checkpoint is None or checkpoint.workspace_id != workspace_id:
        raise ContinuationRunError(
            "session_context_unavailable",
            (
                "The latest session checkpoint is unavailable in this "
                "workspace. No desktop app was opened."
            ),
            status_code=409,
        )

    request_verbatim = await resolve_session_handoff_request_verbatim(
        session,
        checkpoint,
        access_scope=access_scope,
    )
    if (
        not request_verbatim
        or hashlib.sha256(request_verbatim.encode("utf-8")).hexdigest()
        != contract.task.request_sha256
    ):
        raise ContinuationRunError(
            "continuation_lead_mismatch",
            (
                "The latest Session Context does not match the prepared "
                "continuation lead. No desktop app was opened."
            ),
            status_code=409,
        )

    supporting_context = await resolve_session_handoff_supporting_context(
        session,
        checkpoint,
        request_verbatim=request_verbatim,
        access_scope=access_scope,
    )
    attachment_descriptors = (
        await resolve_session_handoff_attachment_descriptors(
            session,
            checkpoint,
            request_verbatim=request_verbatim,
            access_scope=access_scope,
        )
    )
    current_projection = (
        await checkpoints_to_dicts(
            session,
            [checkpoint],
            access_scope=access_scope,
        )
    )[0]
    current_boundary = current_projection.get("boundary") or {}
    checkpoint_data = checkpoint_to_dict(
        checkpoint,
        recovered_goal=request_verbatim,
        session_tip={
            "sequence_number": current_boundary.get("session_tip_sequence"),
            "occurred_at": current_boundary.get("session_tip_at"),
        },
    )
    repository_comparison = await compare_checkpoint_repository(checkpoint)
    try:
        return build_session_handoff_artifact(
            checkpoint,
            request_verbatim=request_verbatim,
            supporting_context=supporting_context,
            trusted_attachment_descriptors=attachment_descriptors,
            allow_local_artifacts=access_scope.principal_id == "local",
            checkpoint_data=checkpoint_data,
            repository_comparison=repository_comparison,
        )
    except ValueError as exc:
        raise ContinuationRunError(
            "session_context_unavailable",
            f"{exc} No desktop app was opened.",
            status_code=409,
        ) from exc


def _staging_context_for_preparation(
    preparation: ContinuationResult,
    *,
    contract: ContinuationExecutionContract,
    expected_lead: str,
    session_context: Mapping[str, Any],
) -> str:
    """Return a hash-bound Session Context for the supplied lead.

    Staging creates no provider turn, so subjective or externally observed
    verification may prevent automatic execution without making the handoff
    unsafe to load. The inherited Workspace Context must still pass its copy
    gate; automatic runs continue to use the stricter execution quality gate.
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
    # Missing foundation coverage is an absence warning, not an integrity
    # failure. A visible desktop draft may carry that warning because it never
    # submits or starts execution. Direct copy and automatic execution retain
    # their stricter gates.
    blocking_stage_issues = [
        issue
        for issue in quality_issues
        if str(issue.get("code") or "")
        not in _DESKTOP_STAGE_ADVISORY_QUALITY_CODES
    ]
    advisory_only = bool(quality_issues) and not blocking_stage_issues
    rendered_project_context = render_continuation_staging_context(contract)
    expected_content = str(project_context.get("content") or "")
    expected_sha256 = str(project_context.get("sha256") or "").strip()
    content_sha256 = hashlib.sha256(
        rendered_project_context.encode("utf-8")
    ).hexdigest()
    structurally_safe = (
        project_context.get("schema_version")
        == STAGING_CONTEXT_SCHEMA_VERSION
        and project_context.get("scope") == "project"
        and not blocking_stage_issues
        and (
            project_context.get("copy_ready") is True
            or advisory_only
        )
        and bool(expected_content.strip())
        and expected_content == rendered_project_context
        and expected_sha256 == content_sha256
    )
    lead_matches = contract.task.request_verbatim == expected_lead
    session_content = str(session_context.get("content") or "")
    session_sha256 = str(session_context.get("sha256") or "").strip()
    session_quality = (
        session_context.get("quality_report")
        if isinstance(session_context.get("quality_report"), Mapping)
        else {}
    )
    session_issues = [
        issue
        for issue in session_quality.get("blocking_issues", [])
        if isinstance(issue, Mapping)
    ]
    source_session = (
        preparation.source_session
        if isinstance(preparation.source_session, dict)
        else {}
    )
    session_identity_matches = (
        str(session_context.get("provider") or "").strip().lower()
        == str(source_session.get("provider") or "").strip().lower()
        and str(session_context.get("session_id") or "").strip()
        == str(source_session.get("session_id") or "").strip()
    )
    session_is_safe = (
        session_context.get("schema_version")
        == SESSION_HANDOFF_SCHEMA_VERSION
        and session_context.get("scope") == "session"
        and session_quality.get("copy_ready") is True
        and not session_issues
        and bool(session_content.strip())
        and session_sha256
        == hashlib.sha256(session_content.encode("utf-8")).hexdigest()
        and session_identity_matches
        and (
            session_context.get("current_goal") or {}
        ).get("request_sha256") == contract.task.request_sha256
    )
    if structurally_safe and lead_matches and session_is_safe:
        return session_content

    issue_message = next(
        (
            str(issue.get("message") or "").strip()
            for issue in (*blocking_stage_issues, *session_issues)
            if str(issue.get("message") or "").strip()
        ),
        "",
    )
    message = (
        issue_message
        or (
            "The compiled Session Context does not match the supplied "
            "immediate lead."
            if not lead_matches
            else (
                "The canonical latest-session Session Context failed its "
                "copy-safety, identity, or integrity checks."
                if not session_is_safe
                else (
                    "Session Context could not safely inherit the compiled "
                    "Workspace Context because its copy-safety or integrity "
                    "checks failed."
                )
            )
        )
    )
    raise ContinuationRunError(
        (
            "continuation_lead_mismatch"
            if not lead_matches
            else (
                "session_context_staging_blocked"
                if not session_is_safe
                else "project_context_staging_blocked"
            )
        ),
        message,
        status_code=409,
        blocker={
            "code": (
                "continuation_lead_mismatch"
                if not lead_matches
                else (
                    "session_context_staging_blocked"
                    if not session_is_safe
                    else "project_context_staging_blocked"
                )
            ),
            "title": (
                "Immediate lead changed"
                if not lead_matches
                else "Session Context is not safe to stage"
            ),
            "message": message,
            "action": (
                "Capture fresh Session Context for the exact immediate lead "
                "before loading it into a harness."
            ),
            "affected_tasks": [_bounded_task(expected_lead)],
            "quality_issues": [*quality_issues, *session_issues],
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


def _continuation_stage_request_sha256(
    *,
    repo_path: str | None,
    objective: str | None,
    objective_is_user_edited: bool,
    checkpoint_id: UUID | str | None,
    checkpoint_source_id: UUID | None,
    source_provider: str | None,
    source_session_id: str | None,
    target_model: str | None,
    target_provider: str,
    provider_model: str | None,
    provider_effort: str | None,
    desktop_access_confirmation: Mapping[str, str] | None,
    task_mode: TaskMode | str | None,
    artifacts: tuple[ContinuationArtifactInput, ...],
    token_budget: int | None,
) -> str:
    artifact_payloads: list[dict[str, Any]] = []
    for artifact in artifacts:
        if hasattr(artifact, "model_dump"):
            artifact_payloads.append(artifact.model_dump(mode="json"))
        elif isinstance(artifact, Mapping):
            artifact_payloads.append(dict(artifact))
        else:
            artifact_payloads.append({"value": str(artifact)})
    normalized_task_mode = (
        task_mode.value if isinstance(task_mode, TaskMode) else task_mode
    )
    canonical = json.dumps(
        {
            "repo_path": repo_path,
            "objective": objective,
            "objective_is_user_edited": objective_is_user_edited,
            "checkpoint_id": (
                str(checkpoint_id) if checkpoint_id is not None else None
            ),
            "checkpoint_source_id": (
                str(checkpoint_source_id)
                if checkpoint_source_id is not None
                else None
            ),
            "source_provider": source_provider,
            "source_session_id": source_session_id,
            "target_model": target_model,
            "target_provider": target_provider,
            "provider_model": provider_model,
            "provider_effort": provider_effort,
            "desktop_access_confirmation": (
                dict(desktop_access_confirmation)
                if desktop_access_confirmation is not None
                else None
            ),
            "task_mode": normalized_task_mode,
            "artifacts": artifact_payloads,
            "token_budget": token_budget,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _continuation_stage_json_default(value: object) -> str:
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return str(enum_value)
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON serializable"
    )


async def _continuation_stage_request(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    idempotency_key: str,
) -> ContinuationStageRequest | None:
    return await session.scalar(
        select(ContinuationStageRequest)
        .where(
            ContinuationStageRequest.workspace_id == workspace_id,
            ContinuationStageRequest.idempotency_key == idempotency_key,
        )
        .limit(1)
    )


async def _claim_continuation_stage_request(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    context_pack_id: UUID,
    continuation_execution_id: UUID,
    idempotency_key: str,
    request_sha256: str,
    target_provider: ProviderName,
) -> tuple[ContinuationStageRequest, bool]:
    now = utc_now()
    await _guard_continuation_stage_pending(
        session,
        workspace_id=workspace_id,
        now=now,
    )
    await session.execute(
        update(ContinuationStageRequest)
        .where(
            ContinuationStageRequest.workspace_id == workspace_id,
            ContinuationStageRequest.status == "succeeded",
        )
        .values(status="superseded_succeeded", updated_at=now)
    )
    await session.execute(
        update(ContinuationStageRequest)
        .where(
            ContinuationStageRequest.workspace_id == workspace_id,
            ContinuationStageRequest.status == "failed",
        )
        .values(status="superseded_failed", updated_at=now)
    )
    request = ContinuationStageRequest(
        workspace_id=workspace_id,
        context_pack_id=context_pack_id,
        continuation_execution_id=continuation_execution_id,
        idempotency_key=idempotency_key,
        request_sha256=request_sha256,
        target_provider=target_provider,
        status="pending",
    )
    session.add(request)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await _continuation_stage_request(
            session,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return existing, False
        current = await session.scalar(
            select(ContinuationStageRequest)
            .where(
                ContinuationStageRequest.workspace_id == workspace_id,
                ContinuationStageRequest.status.in_(
                    ("pending", "succeeded", "failed")
                ),
            )
            .limit(1)
        )
        if current is not None:
            raise ContinuationRunError(
                "desktop_handoff_changed",
                (
                    "Another desktop handoff request won the race. "
                    "No second open request was sent."
                ),
                status_code=409,
            )
        raise
    return request, True


async def _guard_continuation_stage_pending(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    now: datetime | None = None,
) -> None:
    checked_at = now or utc_now()
    pending = await session.scalar(
        select(ContinuationStageRequest)
        .where(
            ContinuationStageRequest.workspace_id == workspace_id,
            ContinuationStageRequest.status == "pending",
        )
        .limit(1)
    )
    if pending is not None:
        if not _continuation_stage_pending_expired(
            pending,
            now=checked_at,
        ):
            raise ContinuationRunError(
                "desktop_handoff_in_progress",
                (
                    "Another desktop handoff request is still in progress. "
                    "No second open request was sent."
                ),
                status_code=409,
            )
        await _abandon_continuation_stage_pending(
            session,
            pending,
            now=checked_at,
        )
        raise _uncertain_continuation_stage_error(pending)


async def _abandon_continuation_stage_pending(
    session: AsyncSession,
    request: ContinuationStageRequest,
    *,
    now: datetime | None = None,
) -> None:
    request.status = "abandoned_uncertain"
    request.error_json = json.dumps(
        {
            "code": "desktop_handoff_outcome_unknown",
            "message": (
                "The previous desktop handoff reservation expired before "
                "its result was recorded. It may have requested an app "
                "open, so its outcome is unknown."
            ),
            "status_code": 409,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    request.updated_at = now or utc_now()
    await asyncio.shield(session.commit())


def _continuation_stage_pending_expired(
    request: ContinuationStageRequest,
    *,
    now: datetime | None = None,
) -> bool:
    updated_at = request.updated_at or request.created_at
    if updated_at is None:
        return True
    cutoff = (now or utc_now()) - timedelta(
        seconds=CONTINUATION_STAGE_PENDING_LEASE_SECONDS
    )
    return updated_at <= cutoff


def _uncertain_continuation_stage_error(
    request: ContinuationStageRequest,
) -> ContinuationRunError:
    return ContinuationRunError(
        "desktop_handoff_outcome_unknown",
        (
            "The earlier desktop handoff reservation expired before its "
            "result was recorded. It may have requested an app open, so no "
            "new open request was sent."
        ),
        status_code=409,
        blocker={
            "code": "desktop_handoff_outcome_unknown",
            "title": "Earlier desktop request is uncertain",
            "provider": request.target_provider,
            "message": (
                "The app may have received the earlier open request, but "
                "DaemonState did not record a confirmed result."
            ),
            "action": (
                "Check the selected desktop app. If no reviewable draft "
                "appeared, use Request again to make one explicit new "
                "request."
            ),
            "affected_tasks": [],
        },
    )


def _replay_continuation_stage_request(
    request: ContinuationStageRequest,
    *,
    request_sha256: str,
) -> ContinuationStageResult:
    if request.request_sha256 != request_sha256:
        raise ContinuationRunError(
            "continuation_idempotency_conflict",
            (
                "This idempotency key was already used for a different "
                "desktop handoff request. No second open request was sent."
            ),
            status_code=409,
        )
    if request.status in {"succeeded", "superseded_succeeded"}:
        try:
            payload = json.loads(request.response_json)
            if not isinstance(payload, dict):
                raise ValueError("stored response is not an object")
            return ContinuationStageResult.from_dict(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ContinuationRunError(
                "continuation_stage_replay_invalid",
                (
                    "The saved desktop handoff result could not be replayed "
                    "safely. No second open request was sent."
                ),
                status_code=500,
            ) from exc
    if request.status in {"failed", "superseded_failed"}:
        try:
            payload = json.loads(request.error_json)
        except (TypeError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        raise ContinuationRunError(
            str(payload.get("code") or "desktop_handoff_failed"),
            str(
                payload.get("message")
                or (
                    "The previous desktop handoff failed. The same "
                    "idempotency key will not open another draft."
                )
            ),
            status_code=int(payload.get("status_code") or 409),
            blocker=(
                payload.get("blocker")
                if isinstance(payload.get("blocker"), dict)
                else None
            ),
            readiness=(
                payload.get("readiness")
                if isinstance(payload.get("readiness"), dict)
                else None
            ),
        )
    if (
        request.status == "abandoned_uncertain"
        or (
            request.status == "pending"
            and _continuation_stage_pending_expired(request)
        )
    ):
        raise _uncertain_continuation_stage_error(request)
    raise ContinuationRunError(
        "desktop_handoff_in_progress",
        (
            "This Continue action is already opening a desktop draft. "
            "No second open request was sent."
        ),
        status_code=409,
        blocker={
            "code": "desktop_handoff_in_progress",
            "title": "Desktop handoff already in progress",
            "provider": request.target_provider,
            "message": (
                "The original request still owns this idempotency key. "
                "Reloading or retrying it will not open another draft."
            ),
            "action": (
                "Wait for the original request to finish. Use a new Continue "
                "action only after checking the first requested draft."
            ),
            "affected_tasks": [],
        },
    )


async def _record_continuation_stage_error(
    session: AsyncSession,
    request: ContinuationStageRequest,
    error: ContinuationRunError,
) -> None:
    request.status = "failed"
    request.error_json = json.dumps(
        {
            "code": error.code,
            "message": str(error),
            "status_code": error.status_code,
            "blocker": error.blocker,
            "readiness": error.readiness,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    await asyncio.shield(session.commit())


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
) -> AgentRun | ContinuationStageRequest | None:
    latest_desktop_request = await session.scalar(
        select(ContinuationStageRequest)
        .where(
            ContinuationStageRequest.workspace_id == workspace_id,
            ContinuationStageRequest.status.in_(
                ("pending", "succeeded", "failed")
            ),
        )
        .execution_options(populate_existing=True)
        .order_by(
            ContinuationStageRequest.created_at.desc(),
            ContinuationStageRequest.id.desc(),
        )
        .limit(1)
    )
    if latest_desktop_request is not None:
        # A later failed or pending request must not resurrect an older
        # successful dispatch as the workspace's current handoff.
        return (
            latest_desktop_request
            if latest_desktop_request.status == "succeeded"
            else None
        )
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


def staged_continuation_payload(
    run: AgentRun | ContinuationStageRequest | None,
) -> dict[str, Any] | None:
    if run is None:
        return None
    if isinstance(run, ContinuationStageRequest):
        try:
            payload = json.loads(run.response_json)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        delivery = payload.get("delivery")
        harness_session = (
            delivery.get("harness_session")
            if isinstance(delivery, dict)
            else None
        )
        if (
            payload.get("status") != "awaiting_user"
            or not isinstance(harness_session, dict)
            or harness_session.get("execution_started") is not False
            or harness_session.get("context_loaded") is not False
        ):
            return None
        # The durable stage response also contains the full preparation and
        # ContextPack. Returning that multi-megabyte payload from the 30-second
        # provider-readiness poll made Continue appear to hang. Recovery needs
        # only the verified handoff envelope; the canonical context remains in
        # the stage ledger and checkpoint APIs.
        run_payload = payload.get("run")
        if not isinstance(run_payload, dict):
            return None
        return {
            "schema_version": str(
                payload.get("schema_version")
                or CONTINUATION_STAGE_SCHEMA_VERSION
            ),
            "status": "awaiting_user",
            "execution_started": False,
            "delivery": delivery,
            "run": run_payload,
        }
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
    """Return desktop-app readiness without invoking any provider CLI."""

    global _provider_readiness_cache
    cache_key = (
        probe_harness_composer_readiness,
        _composer_provider_readiness,
    )
    now = monotonic()
    if (
        not force_refresh
        and _provider_readiness_cache is not None
        and _provider_readiness_cache[0] > now
        and _provider_readiness_cache[1] == cache_key
    ):
        return list(_provider_readiness_cache[2])

    composer_results = await asyncio.gather(*(
        _bounded_composer_readiness(provider)
        for provider in PROVIDER_PREFERENCE
    ))
    providers = [
        _composer_provider_readiness(readiness)
        for readiness in composer_results
    ]
    _provider_readiness_cache = (
        monotonic() + PROVIDER_READINESS_CACHE_SECONDS,
        cache_key,
        tuple(providers),
    )
    return providers


async def _bounded_composer_readiness(
    provider: ProviderName,
) -> HarnessComposerReadiness:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(probe_harness_composer_readiness, provider),
            timeout=COMPOSER_READINESS_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        label = PROVIDER_DISPLAY_NAMES[provider]
        return HarnessComposerReadiness(
            provider=provider,
            ready=False,
            desktop_available=False,
            url_scheme_registered=False,
            required_url_scheme=provider,
            code="desktop_readiness_timeout",
            message=(
                f"{label} Desktop readiness could not be checked within "
                f"{COMPOSER_READINESS_TIMEOUT_SECONDS:g} seconds."
            ),
            action="Check that the desktop app is installed, then try again.",
        )


def _composer_provider_readiness(
    readiness: HarnessComposerReadiness,
) -> ProviderReadiness:
    provider = readiness.provider
    if readiness.ready:
        return ProviderReadiness(
            provider=provider,
            ready=True,
            status="ready",
            code=readiness.code,
            message=readiness.message,
            action=readiness.action,
            models=readiness.models,
            desktop_available=True,
            exact_session_supported=False,
            context_staging_supported=False,
            desktop_handoff_supported=True,
            readiness_scope="desktop_application_and_account_access",
            account_access_state=readiness.account_access_state,
            account_access_verified=readiness.account_access_verified,
            model_catalog_source=readiness.model_catalog_source,
        )
    access_unverified = (
        readiness.code == "desktop_account_access_unverified"
    )
    return ProviderReadiness(
        provider=provider,
        ready=False,
        status="access_unverified" if access_unverified else "unavailable",
        code=readiness.code,
        message=readiness.message,
        action=readiness.action,
        models=readiness.models,
        desktop_available=readiness.desktop_available,
        exact_session_supported=False,
        context_staging_supported=False,
        desktop_handoff_supported=False,
        readiness_scope="desktop_application_and_account_access",
        account_access_state=readiness.account_access_state,
        account_access_verified=readiness.account_access_verified,
        model_catalog_source=readiness.model_catalog_source,
        capabilities={
            "desktop_dispatch_available": (
                readiness.desktop_available
                and readiness.url_scheme_registered
            ),
            "account_access_confirmation_supported": access_unverified and (
                readiness.desktop_available
                and readiness.url_scheme_registered
            ),
        },
    )


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


def _desktop_access_confirmation_provider(
    confirmation: Mapping[str, str] | None,
) -> ProviderName | None:
    if confirmation is None:
        return None
    provider = str(confirmation.get("provider") or "").strip().lower()
    confirmation_value = str(
        confirmation.get("confirmation") or ""
    ).strip().lower()
    if (
        provider not in PROVIDER_PREFERENCE
        or confirmation_value != DESKTOP_ACCESS_CONFIRMATION
    ):
        raise ContinuationRunError(
            "desktop_access_confirmation_invalid",
            (
                "Desktop access confirmation is invalid. No desktop app was "
                "opened."
            ),
            status_code=422,
        )
    return provider  # type: ignore[return-value]


def _desktop_access_confirmation_allows(
    provider: ProviderName,
    readiness: HarnessComposerReadiness,
    *,
    confirmed_access_provider: ProviderName | None,
) -> bool:
    return (
        confirmed_access_provider == provider
        and readiness.code == "desktop_account_access_unverified"
        and readiness.desktop_available is True
        and readiness.url_scheme_registered is True
    )


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
