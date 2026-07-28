from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentRun,
    ContinuationExecution,
    ContinuationOutcome,
    ContinuationRequirement,
    RequirementEvidence,
)
from app.schemas.continuation_execution import (
    ContinuationExecutionContract,
    RequirementPriority,
    VerificationSpec,
    VerifierType,
)
from app.telemetry import traced
from app.time import utc_now


EVIDENCE_STATUSES = frozenset({
    "passed",
    "failed",
    "missing",
    "malformed",
    "skipped",
})
COMMAND_VERIFIER_TYPES = frozenset({
    VerifierType.UNIT_TEST,
    VerifierType.INTEGRATION_TEST,
    VerifierType.STATIC_ANALYSIS,
    VerifierType.BROWSER_ASSERTION,
    VerifierType.SCREENSHOT_COMPARISON,
    VerifierType.EVENT_ASSERTION,
    VerifierType.DATABASE_STATE_ASSERTION,
    VerifierType.GIT_DIFF_ASSERTION,
})


@dataclass(frozen=True)
class VerifierEvidenceItem:
    verifier_id: str
    verifier_type: str
    requirement_ids: tuple[str, ...]
    status: str
    required: bool
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RequirementAssessment:
    requirement_id: str
    priority: str
    status: str
    verifier_ids: tuple[str, ...]
    evidence: tuple[VerifierEvidenceItem, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "priority": self.priority,
            "status": self.status,
            "verifier_ids": list(self.verifier_ids),
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class RequirementVerificationMatrix:
    status: str
    worker_succeeded: bool
    bundle_integrity_passed: bool
    preservation_passed: bool
    mandatory_total: int
    mandatory_passed: int
    mandatory_failed: int
    mandatory_unproven: int
    requirements: tuple[RequirementAssessment, ...]
    evidence: tuple[VerifierEvidenceItem, ...]
    blocker: dict[str, Any] | None = None

    @property
    def verified(self) -> bool:
        return self.status == "verified_complete"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "verified": self.verified,
            "worker_succeeded": self.worker_succeeded,
            "bundle_integrity_passed": self.bundle_integrity_passed,
            "preservation_passed": self.preservation_passed,
            "mandatory": {
                "total": self.mandatory_total,
                "passed": self.mandatory_passed,
                "failed": self.mandatory_failed,
                "unproven": self.mandatory_unproven,
            },
            "requirements": [item.to_dict() for item in self.requirements],
            "evidence": [item.to_dict() for item in self.evidence],
            **({"blocker": self.blocker} if self.blocker is not None else {}),
        }


def _requirement_judge_trace_attributes(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    contract = args[0] if args else kwargs.get("contract")
    results = (
        args[1]
        if len(args) > 1
        else kwargs.get("verification_results", ())
    )
    return {
        "daemonstate.phase": "requirements_judge",
        "daemonstate.continuation.execution.id": getattr(contract, "id", None),
        "daemonstate.context_pack.id": getattr(contract, "context_pack_id", None),
        "daemonstate.checkpoint.id": getattr(contract, "checkpoint_id", None),
        "daemonstate.task.mode": getattr(contract, "task_mode", None),
        "daemonstate.verification.total": len(results),
        "daemonstate.runtime.worker_succeeded": kwargs.get("worker_succeeded"),
        "daemonstate.runtime.bundle_integrity_passed": kwargs.get(
            "bundle_integrity_passed"
        ),
        "daemonstate.runtime.preservation_passed": kwargs.get(
            "preservation_passed"
        ),
    }


@traced(
    "daemonstate.requirements.judge",
    attributes=_requirement_judge_trace_attributes,
    result_attributes=lambda result: {
        "daemonstate.status": result.status,
        "daemonstate.verification.total": result.mandatory_total,
        "daemonstate.verification.passed": result.mandatory_passed,
        "daemonstate.verification.failed": result.mandatory_failed,
        "daemonstate.verification.unproven": result.mandatory_unproven,
    },
)
def build_requirement_matrix(
    contract: ContinuationExecutionContract,
    verification_results: Sequence[Any],
    *,
    worker_succeeded: bool,
    bundle_integrity_passed: bool,
    preservation_passed: bool,
    blocker: dict[str, Any] | None = None,
) -> RequirementVerificationMatrix:
    """Evaluate every mandatory requirement, including absent verifier evidence."""

    observed = {
        _result_verifier_id(item): item
        for item in verification_results
        if _result_verifier_id(item)
    }
    evidence_by_verifier: dict[str, VerifierEvidenceItem] = {}
    for spec in contract.verification:
        result = observed.get(spec.id)
        status, details = _evaluate_verifier(spec, result)
        evidence_by_verifier[spec.id] = VerifierEvidenceItem(
            verifier_id=spec.id,
            verifier_type=spec.verifier_type.value,
            requirement_ids=tuple(spec.requirement_ids),
            status=status,
            required=spec.required,
            details=details,
        )

    assessments: list[RequirementAssessment] = []
    for requirement in contract.requirements:
        required_evidence = tuple(
            evidence_by_verifier[verifier_id]
            for verifier_id in requirement.verification_ids
            if verifier_id in evidence_by_verifier
            and evidence_by_verifier[verifier_id].required
        )
        missing_declared = tuple(
            verifier_id
            for verifier_id in requirement.verification_ids
            if verifier_id not in evidence_by_verifier
        )
        if missing_declared or not required_evidence:
            requirement_status = "unproven"
        elif any(item.status == "failed" for item in required_evidence):
            requirement_status = "failed"
        elif any(item.status != "passed" for item in required_evidence):
            requirement_status = "unproven"
        else:
            requirement_status = "passed"
        assessments.append(RequirementAssessment(
            requirement_id=requirement.id,
            priority=requirement.priority.value,
            status=requirement_status,
            verifier_ids=tuple(requirement.verification_ids),
            evidence=required_evidence,
        ))

    mandatory = [
        item for item in assessments
        if item.priority == RequirementPriority.MUST.value
    ]
    mandatory_passed = sum(item.status == "passed" for item in mandatory)
    mandatory_failed = sum(item.status == "failed" for item in mandatory)
    mandatory_unproven = len(mandatory) - mandatory_passed - mandatory_failed
    required_verifiers_passed = all(
        not item.required or item.status == "passed"
        for item in evidence_by_verifier.values()
    )
    if not worker_succeeded:
        status = "execution_failed"
    elif (
        bundle_integrity_passed
        and preservation_passed
        and required_verifiers_passed
        and mandatory
        and mandatory_passed == len(mandatory)
    ):
        status = "verified_complete"
    else:
        status = "requirements_unproven"
    if not bundle_integrity_passed and blocker is None:
        blocker = {
            "code": "runtime_bundle_integrity_failed",
            "message": "The read-only runtime bundle changed during execution.",
        }
    if not preservation_passed and blocker is None:
        blocker = {
            "code": "preexisting_changes_not_preserved",
            "message": "One or more pre-existing repository changes were altered.",
        }

    return RequirementVerificationMatrix(
        status=status,
        worker_succeeded=worker_succeeded,
        bundle_integrity_passed=bundle_integrity_passed,
        preservation_passed=preservation_passed,
        mandatory_total=len(mandatory),
        mandatory_passed=mandatory_passed,
        mandatory_failed=mandatory_failed,
        mandatory_unproven=mandatory_unproven,
        requirements=tuple(assessments),
        evidence=tuple(evidence_by_verifier.values()),
        blocker=blocker,
    )


async def persist_requirement_matrix(
    session: AsyncSession,
    *,
    execution: ContinuationExecution,
    run: AgentRun,
    matrix: RequirementVerificationMatrix,
) -> ContinuationOutcome:
    requirements = list(await session.scalars(
        select(ContinuationRequirement).where(
            ContinuationRequirement.continuation_execution_id == execution.id
        )
    ))
    requirement_by_key = {
        requirement.requirement_key: requirement
        for requirement in requirements
    }
    for assessment in matrix.requirements:
        requirement = requirement_by_key.get(assessment.requirement_id)
        if requirement is None:
            continue
        for evidence in assessment.evidence:
            payload = {
                **evidence.details,
                "requirement_id": assessment.requirement_id,
                "verifier_id": evidence.verifier_id,
                "verifier_type": evidence.verifier_type,
                "status": evidence.status,
                "required": evidence.required,
            }
            payload_json = _canonical_json(payload)
            existing = await session.scalar(
                select(RequirementEvidence).where(
                    RequirementEvidence.continuation_requirement_id
                    == requirement.id,
                    RequirementEvidence.agent_run_id == run.id,
                    RequirementEvidence.verifier_id == evidence.verifier_id,
                )
            )
            values = {
                "continuation_execution_id": execution.id,
                "continuation_requirement_id": requirement.id,
                "agent_run_id": run.id,
                "verifier_id": evidence.verifier_id,
                "verifier_type": evidence.verifier_type,
                "status": evidence.status,
                "required": evidence.required,
                "evidence_json": payload_json,
                "evidence_sha256": _sha256_text(payload_json),
                "observed_at": utc_now(),
            }
            if existing is None:
                session.add(RequirementEvidence(**values))
            else:
                for key, value in values.items():
                    setattr(existing, key, value)

    outcome = await session.scalar(
        select(ContinuationOutcome).where(
            ContinuationOutcome.continuation_execution_id == execution.id
        )
    )
    summary_json = _canonical_json(matrix.to_dict())
    if outcome is None:
        outcome = ContinuationOutcome(
            continuation_execution_id=execution.id,
            status=matrix.status,
            mandatory_total=matrix.mandatory_total,
            mandatory_passed=matrix.mandatory_passed,
            mandatory_failed=matrix.mandatory_failed,
            mandatory_unproven=matrix.mandatory_unproven,
            blocker_json=_canonical_json(matrix.blocker or {}),
            summary_json=summary_json,
            verified_at=utc_now() if matrix.verified else None,
        )
        session.add(outcome)
    else:
        outcome.status = matrix.status
        outcome.mandatory_total = matrix.mandatory_total
        outcome.mandatory_passed = matrix.mandatory_passed
        outcome.mandatory_failed = matrix.mandatory_failed
        outcome.mandatory_unproven = matrix.mandatory_unproven
        outcome.blocker_json = _canonical_json(matrix.blocker or {})
        outcome.summary_json = summary_json
        outcome.verified_at = utc_now() if matrix.verified else None
    execution.status = matrix.status
    await session.flush()
    return outcome


async def persist_final_outcome(
    session: AsyncSession,
    *,
    execution: ContinuationExecution,
    matrix: RequirementVerificationMatrix,
    payload: dict[str, Any],
) -> ContinuationOutcome:
    """Persist the provider-aware terminal result after matrix evaluation.

    The requirement matrix deliberately knows nothing about provider failures.
    The runtime classifies authentication, billing, availability, and CLI
    incompatibility as external blockers after inspecting the provider result.
    Persisting that final classification keeps the durable outcome aligned
    with the API response instead of leaving it at the intermediate
    ``execution_failed`` state.
    """

    outcome = await session.scalar(
        select(ContinuationOutcome).where(
            ContinuationOutcome.continuation_execution_id == execution.id
        )
    )
    if outcome is None:
        outcome = ContinuationOutcome(
            continuation_execution_id=execution.id,
            status=matrix.status,
            mandatory_total=matrix.mandatory_total,
            mandatory_passed=matrix.mandatory_passed,
            mandatory_failed=matrix.mandatory_failed,
            mandatory_unproven=matrix.mandatory_unproven,
            blocker_json=_canonical_json(matrix.blocker or {}),
            summary_json=_canonical_json(matrix.to_dict()),
            verified_at=utc_now() if matrix.verified else None,
        )
        session.add(outcome)
    status = str(payload.get("status") or matrix.status).strip()
    blocker = payload.get("blocker")
    outcome.status = status
    outcome.mandatory_total = matrix.mandatory_total
    outcome.mandatory_passed = matrix.mandatory_passed
    outcome.mandatory_failed = matrix.mandatory_failed
    outcome.mandatory_unproven = matrix.mandatory_unproven
    outcome.blocker_json = _canonical_json(
        blocker if isinstance(blocker, dict) else {}
    )
    outcome.summary_json = _canonical_json(payload)
    outcome.verified_at = utc_now() if status == "verified_complete" else None
    execution.status = status
    await session.flush()
    return outcome


def _evaluate_verifier(
    spec: VerificationSpec,
    result: Any | None,
) -> tuple[str, dict[str, Any]]:
    if spec.verifier_type not in COMMAND_VERIFIER_TYPES:
        return "skipped", {
            "reason": "verifier_executor_unavailable",
        }
    if not spec.command_argv:
        return "malformed", {
            "reason": "command_argv_missing",
        }
    if result is None:
        return "missing", {
            "reason": "no_observed_verification_result",
            "command_argv": list(spec.command_argv),
            "cwd": spec.cwd,
        }
    command_result = getattr(result, "result", result)
    exit_code = getattr(command_result, "exit_code", None)
    timed_out = bool(getattr(command_result, "timed_out", False))
    expected_exit_code = (
        spec.expected_exit_code
        if spec.expected_exit_code is not None
        else 0
    )
    status = (
        "passed"
        if isinstance(exit_code, int)
        and exit_code == expected_exit_code
        and not timed_out
        else "failed"
    )
    return status, {
        "command_argv": list(spec.command_argv),
        "cwd": spec.cwd,
        "exit_code": exit_code,
        "expected_exit_code": expected_exit_code,
        "timed_out": timed_out,
        "stdout_truncated": bool(
            getattr(command_result, "stdout_truncated", False)
        ),
        "stderr_truncated": bool(
            getattr(command_result, "stderr_truncated", False)
        ),
    }


def _result_verifier_id(value: Any) -> str:
    for name in ("verifier_id", "requirement_id"):
        candidate = str(getattr(value, name, "") or "").strip()
        if candidate:
            return candidate
    return ""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
