from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AgentRun, ContextPack, RunObservation


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


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None
