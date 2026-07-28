from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AgentRun,
    ContextPack,
    ContinuationExecution,
    RunObservation,
)
from app.services.harness_sessions import harness_session_payload


SUCCESS_STATUSES = frozenset({"complete", "completed", "passed", "success", "succeeded"})


@dataclass(frozen=True)
class HarnessOutcomeGroup:
    model: str
    model_profile: str
    observed_runs: int
    completed_runs: int
    verified_successful_runs: int
    failed_verification_runs: int
    unresolved_blocker_runs: int
    duration_observed_runs: int
    total_duration_seconds: float | None
    average_duration_seconds: float | None
    evidence: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "model_profile": self.model_profile,
            "observed_runs": self.observed_runs,
            "completed_runs": self.completed_runs,
            "completion_rate": _rate(self.completed_runs, self.observed_runs),
            "verified_successful_runs": self.verified_successful_runs,
            "verified_success_rate": _rate(
                self.verified_successful_runs, self.observed_runs
            ),
            "failed_verification_runs": self.failed_verification_runs,
            "unresolved_blocker_runs": self.unresolved_blocker_runs,
            "duration": {
                "observed_runs": self.duration_observed_runs,
                "total_seconds": self.total_duration_seconds,
                "average_seconds": self.average_duration_seconds,
            },
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class HarnessOutcomeReport:
    workspace_id: UUID
    groups: tuple[HarnessOutcomeGroup, ...]
    runs: tuple["_RunOutcome", ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "harness_outcomes.v1",
            "workspace_id": str(self.workspace_id),
            "observed_runs": sum(group.observed_runs for group in self.groups),
            "groups": [group.to_dict() for group in self.groups],
            "runs": [run.to_dict() for run in self.runs],
            "measurement_note": (
                "Only local-harness-observed completion and verification evidence can "
                "produce verified success, and any recorded unresolved blocker prevents "
                "it. Model names are recorded labels, not independently verified "
                "provider identities."
            ),
        }


@dataclass(frozen=True)
class _VerificationEvidence:
    requirement_id: str | None
    command: str | None
    fallback_key: str
    passed: bool
    event_time: datetime
    observation_id: str


@dataclass(frozen=True)
class _RunOutcome:
    run_id: str
    model: str
    model_profile: str
    objective: str | None
    tool: str | None
    status: str
    completed: bool
    verified_success: bool
    failed_verification: bool
    unresolved_blocker: bool
    duration_seconds: float | None
    started_at: datetime | None
    ended_at: datetime | None
    outcome_summary: str | None
    changed_files: tuple[str, ...]
    verification_observed: int
    verification_passed: int
    verification_failed: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "model": self.model,
            "model_profile": self.model_profile,
            "objective": self.objective,
            "tool": self.tool,
            "status": self.status,
            "completed": self.completed,
            "verified_success": self.verified_success,
            "failed_verification": self.failed_verification,
            "unresolved_blocker": self.unresolved_blocker,
            "duration_seconds": self.duration_seconds,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "outcome_summary": self.outcome_summary,
            "changed_files": list(self.changed_files),
            "verification": {
                "observed": self.verification_observed,
                "passed": self.verification_passed,
                "failed": self.verification_failed,
            },
        }


class HarnessOutcomeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def latest_continuation(
        self,
        *,
        workspace_id: UUID,
    ) -> dict[str, Any] | None:
        """Return the latest terminal continuation, including observed evidence."""

        run = await self.session.scalar(
            select(AgentRun)
            .options(
                selectinload(AgentRun.context_pack),
                selectinload(AgentRun.continuation_execution).selectinload(
                    ContinuationExecution.outcome
                ),
                selectinload(AgentRun.observations).selectinload(
                    RunObservation.source_document
                ),
            )
            .where(
                AgentRun.workspace_id == workspace_id,
                AgentRun.run_key.like("continuation:%"),
                AgentRun.status.notin_(
                    ("running", "staging", "awaiting_user", "handed_off")
                ),
            )
            .order_by(
                AgentRun.ended_at.desc(),
                AgentRun.started_at.desc(),
                AgentRun.id.desc(),
            )
            .limit(1)
        )
        if run is None:
            return None

        command_observation = next(
            (
                item
                for item in reversed(sorted(
                    run.observations,
                    key=_observation_sort_key,
                ))
                if item.event_key == "harness:command"
                and _is_local_harness_observation(item)
            ),
            None,
        )
        outcome = _evaluate_run(run)
        if outcome is not None:
            payload = outcome.to_dict()
            agent_changed_files = list(_observation_files(command_observation))
            payload["agent_changed_files"] = agent_changed_files
            # Continuation success requires both passing required checks and
            # repository changes made by the target agent. A pre-existing dirty
            # tree or checks alone must not become a recovered success claim.
            if not agent_changed_files:
                payload["verified_success"] = False
        else:
            status = _normalized_text(run.status) or "unknown"
            payload = {
                "run_id": str(run.id),
                "model": _normalized_text(run.model) or "unreported",
                "model_profile": "unreported",
                "objective": _normalized_text(run.objective),
                "tool": _normalized_text(run.tool),
                "status": status,
                "completed": status.lower() in SUCCESS_STATUSES,
                "verified_success": False,
                "failed_verification": False,
                "unresolved_blocker": status.lower() not in SUCCESS_STATUSES,
                "duration_seconds": _duration_seconds(run),
                "started_at": (
                    run.started_at.isoformat() if run.started_at else None
                ),
                "ended_at": run.ended_at.isoformat() if run.ended_at else None,
                "outcome_summary": (
                    "The run ended before a local harness outcome was recorded."
                ),
                "agent_changed_files": [],
                "changed_files": [],
                "verification": {
                    "observed": 0,
                    "passed": 0,
                    "failed": 0,
                },
            }
        canonical_outcome = (
            run.continuation_execution.outcome
            if run.continuation_execution is not None
            else None
        )
        if canonical_outcome is not None:
            canonical_summary = _json_object(canonical_outcome.summary_json)
            canonical_blocker = _json_object(canonical_outcome.blocker_json)
            canonical_status = (
                _normalized_text(canonical_outcome.status)
                or "requirements_unproven"
            )
            canonical_checks = canonical_summary.get("checks")
            if not isinstance(canonical_checks, dict):
                canonical_checks = {}
            payload.update({
                "status": canonical_status,
                "completed": (
                    str(run.status or "").strip().lower()
                    in SUCCESS_STATUSES
                ),
                "verified_success": (
                    canonical_status == "verified_complete"
                    and canonical_outcome.verified_at is not None
                ),
                "failed_verification": (
                    canonical_outcome.mandatory_failed > 0
                ),
                "unresolved_blocker": (
                    bool(canonical_blocker)
                    or canonical_status
                    in {"blocked_external", "blocked_ambiguity"}
                ),
                "outcome_summary": (
                    _normalized_text(canonical_summary.get("summary"))
                    or _normalized_text(
                        canonical_summary.get("completion_evidence")
                    )
                    or canonical_status.replace("_", " ")
                ),
                "verification": {
                    "observed": int(
                        canonical_checks.get(
                            "total",
                            canonical_outcome.mandatory_total,
                        )
                        or 0
                    ),
                    "passed": int(
                        canonical_checks.get(
                            "passed",
                            canonical_outcome.mandatory_passed,
                        )
                        or 0
                    ),
                    "failed": int(
                        canonical_checks.get(
                            "failed",
                            canonical_outcome.mandatory_failed,
                        )
                        or 0
                    ),
                },
                "canonical_outcome": {
                    "status": canonical_status,
                    "mandatory_total": canonical_outcome.mandatory_total,
                    "mandatory_passed": canonical_outcome.mandatory_passed,
                    "mandatory_failed": canonical_outcome.mandatory_failed,
                    "mandatory_unproven": (
                        canonical_outcome.mandatory_unproven
                    ),
                    "blocker": canonical_blocker or None,
                    "verified_at": (
                        canonical_outcome.verified_at.isoformat()
                        if canonical_outcome.verified_at
                        else None
                    ),
                },
            })
            for key in ("agent_changed_files", "changed_files"):
                values = canonical_summary.get(key)
                if isinstance(values, list):
                    payload[key] = [
                        str(value)
                        for value in values
                        if str(value).strip()
                    ]
        tool = str(payload.get("tool") or "").strip().lower()
        payload["provider"] = (
            tool.rsplit(":", 1)[-1]
            if ":" in tool
            else tool or None
        )
        harness_session = harness_session_payload(run.observations)
        if harness_session is not None:
            payload["harness_session"] = harness_session
        command_payload = (
            _payload(command_observation)
            if command_observation is not None
            else {}
        )
        if (
            str(payload.get("status") or "").strip().lower() == "failed"
            and command_payload.get("timed_out") is True
        ):
            provider_label = {
                "codex": "Codex",
                "claude": "Claude Code",
                "opencode": "OpenCode",
            }.get(str(payload["provider"] or ""), "The target agent")
            payload["failure_code"] = "provider_run_timed_out"
            payload["outcome_summary"] = (
                f"{provider_label} did not finish before the continuation timeout."
            )
        context_package = _context_package_summary(
            run.context_pack,
            delivered=command_observation is not None,
        )
        if context_package is not None:
            payload["context_package"] = context_package
        return payload

    async def summarize(
        self,
        *,
        workspace_id: UUID,
        accessible_source_ids: set[UUID] | None = None,
    ) -> HarnessOutcomeReport:
        runs = list(await self.session.scalars(
            select(AgentRun)
            .options(
                selectinload(AgentRun.context_pack),
                selectinload(AgentRun.observations).selectinload(
                    RunObservation.source_document
                ),
            )
            .where(AgentRun.workspace_id == workspace_id)
            .order_by(AgentRun.started_at, AgentRun.id)
        ))
        grouped: dict[tuple[str, str], list[_RunOutcome]] = {}
        observed_outcomes: list[_RunOutcome] = []
        for run in runs:
            observations = (
                [
                    item for item in run.observations
                    if item.source_document_id in accessible_source_ids
                ]
                if accessible_source_ids is not None
                else run.observations
            )
            outcome = _evaluate_run(run, observations=observations)
            if outcome is None:
                continue
            observed_outcomes.append(outcome)
            grouped.setdefault((outcome.model, outcome.model_profile), []).append(outcome)

        groups = tuple(
            _aggregate_group(model=model, model_profile=profile, outcomes=outcomes)
            for (model, profile), outcomes in sorted(grouped.items())
        )
        recent = tuple(sorted(
            observed_outcomes,
            key=lambda item: (
                item.started_at or datetime.min,
                item.run_id,
            ),
            reverse=True,
        ))
        return HarnessOutcomeReport(
            workspace_id=workspace_id,
            groups=groups,
            runs=recent,
        )


def _evaluate_run(
    run: AgentRun,
    *,
    observations: Iterable[RunObservation] | None = None,
) -> _RunOutcome | None:
    observations = sorted(
        run.observations if observations is None else observations,
        key=_observation_sort_key,
    )
    harness_observations = [
        item for item in observations if _is_local_harness_observation(item)
    ]
    if not harness_observations:
        return None
    latest_outcome = next(
        (
            item
            for item in reversed(harness_observations)
            if item.event_type == "outcome"
        ),
        None,
    )
    outcome_status = _outcome_status(latest_outcome)
    completed = outcome_status in SUCCESS_STATUSES if outcome_status else False

    requirements = _required_verification(run.context_pack)
    evidence = _verification_evidence(
        harness_observations, requirements=requirements
    )
    latest_evidence: dict[str, _VerificationEvidence] = {}
    for item in evidence:
        key = _canonical_verification_key(item, requirements=requirements)
        previous = latest_evidence.get(key)
        if previous is None or _verification_sort_key(item) > _verification_sort_key(previous):
            latest_evidence[key] = item

    if requirements:
        required_evidence = [latest_evidence.get(key) for key in requirements]
        failed_verification = any(
            item is not None and not item.passed for item in required_evidence
        )
        required_passed = all(
            item is not None and item.passed for item in required_evidence
        )
        has_passing_evidence = required_passed
    else:
        failed_verification = any(
            not item.passed for item in latest_evidence.values()
        )
        required_passed = True
        has_passing_evidence = bool(latest_evidence) and all(
            item.passed for item in latest_evidence.values()
        )
    unresolved_blocker = _has_unresolved_blocker(observations)
    verified_success = (
        completed
        and has_passing_evidence
        and required_passed
        and not unresolved_blocker
    )

    pack = run.context_pack
    model = _normalized_text(run.model) or "unreported"
    model_profile = _normalized_text(pack.model_profile if pack else None) or "unreported"
    verification_items = list(latest_evidence.values())
    changed_files = _observation_files(latest_outcome)
    if not changed_files:
        latest_patch = next(
            (
                item for item in reversed(harness_observations)
                if item.event_type == "patch_summary"
            ),
            None,
        )
        changed_files = _observation_files(latest_patch)
    outcome_payload = _payload(latest_outcome) if latest_outcome is not None else {}
    return _RunOutcome(
        run_id=str(run.id),
        model=model,
        model_profile=model_profile,
        objective=_normalized_text(run.objective or (pack.objective if pack else None)),
        tool=_normalized_text(run.tool),
        status=_normalized_text(run.status) or "unknown",
        completed=completed,
        verified_success=verified_success,
        failed_verification=failed_verification,
        unresolved_blocker=unresolved_blocker,
        duration_seconds=_duration_seconds(run),
        started_at=run.started_at,
        ended_at=run.ended_at,
        outcome_summary=_normalized_text(
            outcome_payload.get("summary")
            or outcome_payload.get("content")
            or (latest_outcome.content if latest_outcome is not None else None)
        ),
        changed_files=changed_files,
        verification_observed=len(verification_items),
        verification_passed=sum(item.passed for item in verification_items),
        verification_failed=sum(not item.passed for item in verification_items),
    )


def _aggregate_group(
    *,
    model: str,
    model_profile: str,
    outcomes: list[_RunOutcome],
) -> HarnessOutcomeGroup:
    completed = [item.run_id for item in outcomes if item.completed]
    verified = [item.run_id for item in outcomes if item.verified_success]
    failed = [item.run_id for item in outcomes if item.failed_verification]
    blocked = [item.run_id for item in outcomes if item.unresolved_blocker]
    durations = [
        item.duration_seconds for item in outcomes if item.duration_seconds is not None
    ]
    total_duration = round(sum(durations), 3) if durations else None
    average_duration = (
        round(sum(durations) / len(durations), 3) if durations else None
    )
    return HarnessOutcomeGroup(
        model=model,
        model_profile=model_profile,
        observed_runs=len(outcomes),
        completed_runs=len(completed),
        verified_successful_runs=len(verified),
        failed_verification_runs=len(failed),
        unresolved_blocker_runs=len(blocked),
        duration_observed_runs=len(durations),
        total_duration_seconds=total_duration,
        average_duration_seconds=average_duration,
        evidence={
            "observed_run_ids": [item.run_id for item in outcomes],
            "completed_run_ids": completed,
            "verified_successful_run_ids": verified,
            "failed_verification_run_ids": failed,
            "unresolved_blocker_run_ids": blocked,
        },
    )


def _required_verification(pack: ContextPack | None) -> dict[str, tuple[str | None, str | None]]:
    if pack is None:
        return {}
    manifest = _json_object(pack.manifest)
    raw_commands = (manifest.get("verification") or {}).get("commands") or []
    result: dict[str, tuple[str | None, str | None]] = {}
    for item in raw_commands:
        if not isinstance(item, dict) or item.get("required") is not True:
            continue
        requirement_id = _normalized_text(item.get("id"))
        command = _normalize_command(item.get("command"))
        if requirement_id is None and command is None:
            continue
        key = f"requirement:{requirement_id}" if requirement_id else f"command:{command}"
        if key in result:
            continue
        result[key] = (requirement_id, command)
    return result


def _context_package_summary(
    pack: ContextPack | None,
    *,
    delivered: bool,
) -> dict[str, Any] | None:
    if pack is None:
        return None
    manifest = _json_object(pack.manifest)
    selected = [
        item for item in (manifest.get("selected_context") or [])
        if isinstance(item, dict)
    ]
    excluded = [
        item for item in (manifest.get("excluded_context") or [])
        if isinstance(item, dict)
    ]
    selected_by_lane: dict[str, int] = {}
    for item in selected:
        lane = _normalized_text(item.get("lane")) or "supporting_context"
        selected_by_lane[lane] = selected_by_lane.get(lane, 0) + 1
    excluded_by_reason: dict[str, int] = {}
    for item in excluded:
        reason = _normalized_text(item.get("reason")) or "unspecified"
        excluded_by_reason[reason] = excluded_by_reason.get(reason, 0) + 1
    provenance = {"verified": 0, "unverified": 0, "unknown": 0}
    for item in selected:
        verified = item.get("provenance_verified")
        if verified is True:
            provenance["verified"] += 1
        elif verified is False:
            provenance["unverified"] += 1
        else:
            provenance["unknown"] += 1
    accounting = _json_object(
        manifest.get("token_accounting")
        or manifest.get("rendering")
    )
    compiler = _json_object(manifest.get("compiler"))
    continuation = _json_object(manifest.get("continuation"))
    repo_state = _json_object(manifest.get("repo_state"))
    verification = _json_object(manifest.get("verification"))
    commands = [
        item for item in (verification.get("commands") or [])
        if isinstance(item, dict)
    ]
    relevant_files = [
        item for item in (repo_state.get("relevant_files") or [])
        if isinstance(item, dict)
    ]
    return {
        "schema_version": "context_package_summary.v1",
        "context_pack_id": str(pack.id),
        "state": "delivered" if delivered else "prepared_not_delivered",
        "compiler_version": _normalized_text(compiler.get("version")),
        "created_at": pack.created_at.isoformat() if pack.created_at else None,
        "selected_count": len(selected),
        "excluded_count": len(excluded),
        "selected_by_lane": selected_by_lane,
        "excluded_by_reason": excluded_by_reason,
        "provenance": provenance,
        "token_estimate": {
            "rendered": _integer_or_zero(
                accounting.get("rendered_tokens")
                or accounting.get("estimated_tokens")
            ),
            "budget": _integer_or_zero(
                accounting.get("budget")
                or accounting.get("budget_tokens")
                or pack.token_budget
            ),
            "remaining": _integer_or_zero(accounting.get("remaining_tokens")),
            "within_budget": accounting.get("within_budget") is True,
            "method": _normalized_text(accounting.get("estimation_method")),
        },
        "relevant_files_count": len(relevant_files),
        "verification_commands_count": len(commands),
        "input_fingerprint": _normalized_text(manifest.get("input_fingerprint")),
        "continuation_identity": {
            "task_id": _normalized_text(continuation.get("task_id")),
            "selected_objective": _normalized_text(
                continuation.get("selected_objective")
                or manifest.get("objective")
            ),
            "checkpoint_id": _normalized_text(continuation.get("checkpoint_id")),
            "source_provider": _normalized_text(continuation.get("provider")),
            "source_session_id": _normalized_text(continuation.get("session_id")),
        },
    }


def _verification_evidence(
    observations: Iterable[RunObservation],
    *,
    requirements: dict[str, tuple[str | None, str | None]],
) -> list[_VerificationEvidence]:
    del requirements  # Requirements are applied when evidence receives a canonical key.
    result: list[_VerificationEvidence] = []
    for observation in observations:
        payload = _payload(observation)
        if observation.event_type == "verification":
            passed = _verification_passed(payload)
            if passed is not None:
                result.append(_verification_item(
                    observation=observation,
                    payload=payload,
                    passed=passed,
                    fallback_key=f"observation:{observation.event_key or observation.id}",
                ))
        if observation.event_type != "outcome":
            continue
        raw_results = payload.get("verification_results") or []
        if not isinstance(raw_results, list):
            continue
        for index, raw in enumerate(raw_results):
            if not isinstance(raw, dict):
                continue
            passed = _verification_passed(raw)
            if passed is None:
                continue
            result.append(_verification_item(
                observation=observation,
                payload=raw,
                passed=passed,
                fallback_key=f"outcome:{observation.id}:{index}",
            ))
    return result


def _verification_item(
    *,
    observation: RunObservation,
    payload: dict[str, Any],
    passed: bool,
    fallback_key: str,
) -> _VerificationEvidence:
    return _VerificationEvidence(
        requirement_id=_normalized_text(payload.get("requirement_id")),
        command=_normalize_command(payload.get("command")),
        fallback_key=fallback_key,
        passed=passed,
        event_time=_event_time(observation),
        observation_id=str(observation.id),
    )


def _canonical_verification_key(
    evidence: _VerificationEvidence,
    *,
    requirements: dict[str, tuple[str | None, str | None]],
) -> str:
    for key, (requirement_id, command) in requirements.items():
        if requirement_id and evidence.requirement_id == requirement_id:
            return key
        if command and evidence.command == command:
            return key
    if evidence.requirement_id:
        return f"requirement:{evidence.requirement_id}"
    if evidence.command:
        return f"command:{evidence.command}"
    return evidence.fallback_key


def _has_unresolved_blocker(observations: Iterable[RunObservation]) -> bool:
    active_keys: set[str] = set()
    unkeyed_blockers = 0
    for observation in sorted(observations, key=_observation_sort_key):
        if observation.event_type == "blocker":
            if observation.event_key:
                active_keys.add(observation.event_key)
            else:
                unkeyed_blockers += 1
        elif observation.event_type == "blocker_resolution":
            resolved_key = _normalized_text(_payload(observation).get("resolves_event_key"))
            if resolved_key:
                active_keys.discard(resolved_key)
    return bool(active_keys or unkeyed_blockers)


def _outcome_status(observation: RunObservation | None) -> str | None:
    if observation is None:
        return None
    payload = _payload(observation)
    for key in ("status", "terminal_status", "outcome"):
        value = _normalized_text(payload.get(key))
        if value:
            return value.lower()
    return None


def _verification_passed(payload: dict[str, Any]) -> bool | None:
    exit_code = payload.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        return exit_code == 0
    status = _normalized_text(payload.get("status"))
    if status is None:
        return None
    normalized = status.lower()
    if normalized in {"pass", "passed", "success", "succeeded"}:
        return True
    if normalized in {"error", "fail", "failed"}:
        return False
    return None


def _duration_seconds(run: AgentRun) -> float | None:
    if run.started_at is None or run.ended_at is None or run.ended_at < run.started_at:
        return None
    return round((run.ended_at - run.started_at).total_seconds(), 3)


def _payload(observation: RunObservation) -> dict[str, Any]:
    payload = _json_object(observation.payload_json)
    payload.setdefault("command", observation.command)
    payload.setdefault("exit_code", observation.exit_code)
    return payload


def _observation_files(observation: RunObservation | None) -> tuple[str, ...]:
    if observation is None:
        return ()
    try:
        decoded = json.loads(observation.files_json or "[]")
    except (TypeError, json.JSONDecodeError):
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(sorted({
        normalized
        for value in decoded
        if (normalized := _normalized_text(value)) is not None
    }))


def _is_local_harness_observation(observation: RunObservation) -> bool:
    source = observation.source_document
    if source is None:
        return False
    metadata = _json_object(source.metadata_json)
    return metadata.get("observed_by") == "local_harness"


def _json_object(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _event_time(observation: RunObservation) -> datetime:
    return observation.observed_at or observation.created_at


def _observation_sort_key(observation: RunObservation) -> tuple[datetime, str]:
    return (_event_time(observation), str(observation.id))


def _verification_sort_key(item: _VerificationEvidence) -> tuple[datetime, str]:
    return (item.event_time, item.observation_id)


def _normalize_command(value: Any) -> str | None:
    normalized = " ".join(str(value or "").split())
    return normalized or None


def _normalized_text(value: Any) -> str | None:
    normalized = " ".join(str(value or "").split())
    return normalized or None


def _integer_or_zero(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None
