from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import AgentRun
from app.services.access import AccessScope
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
    HarnessVisibility,
    probe_harness_visibility,
)
from app.services.local_harness import (
    LocalHarnessResult,
    LocalHarnessRunner,
    RepositoryStateChangedError,
    capture_repository_snapshot,
)
from app.services.session_summary import (
    is_substantive_user_request,
    normalize_substantive_user_request,
)
from app.services.task_workflow import (
    TaskWorkflowService,
    complete_verified_execution_task,
)
from app.time import utc_now


CONTINUATION_RUN_SCHEMA_VERSION = "continuation.run.v1"
PROVIDER_PREFERENCE: tuple[ProviderName, ...] = ("codex", "claude", "opencode")
TARGET_PROVIDERS = frozenset((*PROVIDER_PREFERENCE, "auto"))
MAX_BLOCKER_TASK_LENGTH = 140


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


class ContinuationRunService:
    """Prepare, deliver, execute, and verify one local continuation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(
        self,
        *,
        workspace_id: UUID,
        access_scope: AccessScope,
        repo_path: str | None = None,
        objective: str | None = None,
        checkpoint_id: UUID | str | None = None,
        checkpoint_source_id: UUID | None = None,
        source_provider: str | None = None,
        source_session_id: str | None = None,
        target_model: str | None = None,
        target_provider: str = "auto",
        provider_model: str | None = None,
        provider_effort: str | None = None,
        token_budget: int | None = None,
        idempotency_key: str | None = None,
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
            checkpoint_id=checkpoint_id,
            checkpoint_source_id=checkpoint_source_id,
            source_provider=source_provider,
            source_session_id=source_session_id,
            target_model=target_model,
            token_budget=token_budget,
            sync_sessions=True,
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
                checkpoint_id=checkpoint_id,
                checkpoint_source_id=checkpoint_source_id,
                source_provider=source_provider,
                source_session_id=source_session_id,
                target_model=target_model,
                token_budget=token_budget,
                sync_sessions=False,
            )
            effective_repo_path, current_repository = _runnable_repository(preparation)
            expected_fingerprint = _repository_fingerprint(current_repository)

        source_provider = _normalized_source_provider(preparation.source_session)
        invocation = await _select_ready_invocation(
            repo_path=effective_repo_path,
            target_provider=target_provider,
            provider_model=provider_model,
            provider_effort=provider_effort,
            current_task=preparation.objective,
            affected_tasks=_preparation_affected_task_titles(preparation),
        )
        pack_id = UUID(preparation.context_pack_id)
        run = AgentRun(
            workspace_id=workspace_id,
            context_pack_id=pack_id,
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
                result = await LocalHarnessRunner(self.session).run(
                    context_pack_id=pack_id,
                    run_id=run.id,
                    repo_path=invocation.repo_path,
                    command=invocation.argv,
                    verify=True,
                    context_stdin=invocation.context_delivery == "stdin",
                    extra_env=provider_environment(invocation.provider),
                    expected_status_fingerprint=expected_fingerprint,
                    command_timeout_seconds=(
                        settings.continuation_command_timeout_seconds
                    ),
                    stdout_chunk_observer=session_bridge.observe_stdout_chunk,
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
            "command_timeout_seconds": (
                settings.continuation_command_timeout_seconds
            ),
        }
        if session_bridge.state is not None:
            delivery["harness_session"] = session_bridge.state
        outcome = _outcome(
            result,
            provider=invocation.provider,
            current_task=preparation.objective,
            affected_tasks=_preparation_affected_task_titles(preparation),
        )
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

    repo_path = str(preparation.repository.get("path") or "").strip()
    current = preparation.repository.get("current")
    if not repo_path or not isinstance(current, dict):
        raise ContinuationRunError(
            "continuation_repository_unavailable",
            "A readable local Git repository is required to continue this task.",
        )
    return repo_path, current


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
            AgentRun.status == "running",
            AgentRun.run_key.like("continuation:%"),
        )
        .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
        .limit(1)
    )


def active_continuation_run_payload(run: AgentRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    tool = str(run.tool or "").strip().lower()
    provider = tool.split(":", 1)[1] if tool.startswith("context-engine:") else tool
    session = harness_session_payload(run.observations)
    payload = {
        "run_id": str(run.id),
        "provider": provider or None,
        "model": run.model,
        "objective": run.objective,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "phase": "agent_running" if session is not None else "starting_harness",
    }
    if session is not None:
        payload["harness_session"] = session
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


async def provider_readiness() -> list[ProviderReadiness]:
    """Return bounded local readiness for every supported continuation provider."""

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
    return [
        _visible_provider_readiness(cli, visibility)
        for cli, visibility in zip(
            cli_results,
            visibility_results,
            strict=True,
        )
    ]


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
    readiness_results = await asyncio.gather(*(
        _readiness_for(provider, provider_model=selected_model)
        for provider, selected_model in zip(
            candidates,
            selected_models,
            strict=True,
        )
    ))
    for provider, selected_model, readiness in zip(
        candidates,
        selected_models,
        readiness_results,
        strict=True,
    ):
        if not readiness.ready:
            continue
        try:
            return build_harness_invocation(
                provider,
                repo_path=repo_path,
                session_id=None,
                model=selected_model,
                effort=provider_effort,
                visible=provider == "codex",
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
            "blocked"
            if blocker["code"] in {
                "provider_authentication_failed",
                "provider_authentication_revoked",
                "provider_billing_required",
                "provider_cli_update_required",
                "provider_service_unavailable",
            }
            else "failed"
        )
    elif checks_status == "passed" and agent_changed_files:
        status = "verified"
    else:
        status = "completed_unverified"
    if result.status == "failed":
        completion_evidence = "agent_run_failed"
    elif status == "verified":
        completion_evidence = "repository_changes_and_required_checks"
    elif checks_status == "passed" and not agent_changed_files:
        completion_evidence = "checks_passed_without_repository_changes"
    elif checks_status == "not_available":
        completion_evidence = "required_checks_not_available"
    else:
        completion_evidence = "required_checks_failed"
    return {
        "status": status,
        "run_status": result.status,
        "verified": status == "verified",
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
            "Update Context Engine to the corrected OpenCode invocation and "
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
    """Recognize Context Engine/provider CLI contract failures without leaking logs."""

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
        and "continue the task using the attached context engine context pack"
        in output
    ):
        return (
            "Context Engine constructed an invalid OpenCode command: OpenCode "
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
