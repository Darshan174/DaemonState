"""Deterministic evaluation for same-model continuation-context parity.

The evaluator intentionally does not call a model.  A model (or a human
annotator) reads one rendered composite handoff and returns the closed
``CompositeRecoveryAnswer`` contract below.  This module compares that answer
with facts labeled from the full-history condition, then aggregates externally
verified paired trials.

Two boundaries are deliberate:

* recovery scoring measures whether the compiled handoff preserved actionable
  information; it is not proof that a worker completed the task;
* the aggregate claim remains ``insufficient_evidence`` until every declared
  same-model product SLO is met across at least thirty paired trials.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


RECOVERY_ANSWER_SCHEMA_VERSION = "continuity_recovery_answer.v1"
RECOVERY_REFERENCE_SCHEMA_VERSION = "continuity_recovery_reference.v1"
RECOVERY_REPORT_SCHEMA_VERSION = "continuity_recovery_report.v1"
PAIRED_TRIAL_SCHEMA_VERSION = "continuity_parity_trial.v1"
PAIRED_REPORT_SCHEMA_VERSION = "continuity_parity_report.v1"


class ContinuityParityValidationError(ValueError):
    """Raised when an evaluation input is unbound, incomplete, or ambiguous."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthorityMode(StrEnum):
    UNKNOWN = "unknown"
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"


class CheckTruth(StrEnum):
    UNKNOWN = "unknown"
    UNVERIFIED = "unverified"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    TIMED_OUT = "timed_out"
    STALE = "stale"


class RepositoryHealth(StrEnum):
    UNKNOWN = "unknown"
    PASSING = "passing"
    FAILING = "failing"
    STALE = "stale"


class FlowStageKind(StrEnum):
    ENTRYPOINT = "entrypoint"
    SERVICE = "service"
    PERSISTENCE = "persistence"
    COMPILER = "compiler"
    OUTPUT = "output"


class RecoveryStatement(_FrozenModel):
    id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    statement: str = Field(min_length=1, max_length=4_000)


class ProtectedBaselineEntry(_FrozenModel):
    path: str = Field(min_length=1, max_length=2_000)
    status: str | None = Field(default=None, min_length=1, max_length=40)
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ProtectedBaseline(_FrozenModel):
    preserve_required: bool | None = None
    entries: tuple[ProtectedBaselineEntry, ...] = Field(default=(), max_length=2_000)

    @model_validator(mode="after")
    def validate_unique_paths(self) -> Self:
        paths = [entry.path for entry in self.entries]
        if len(paths) != len(set(paths)):
            raise ValueError("protected baseline contains duplicate paths")
        if self.entries and self.preserve_required is not True:
            raise ValueError("protected baseline entries require preserve_required=true")
        return self


class RecoveryCheck(_FrozenModel):
    id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    command: str = Field(min_length=1, max_length=4_000)
    cwd: str = Field(default=".", min_length=1, max_length=2_000)
    truth: CheckTruth = CheckTruth.UNKNOWN


class RecoveryFlowStage(_FrozenModel):
    kind: FlowStageKind
    path: str = Field(min_length=1, max_length=2_000)
    symbol: str | None = Field(default=None, min_length=1, max_length=500)

    @property
    def identity(self) -> str:
        return f"{self.kind.value}:{self.path}#{self.symbol or ''}"


class RecoveryFacts(_FrozenModel):
    """The actionable facts recovered from one context condition."""

    authoritative_task: RecoveryStatement | None = None
    authority: AuthorityMode = AuthorityMode.UNKNOWN
    protected_baseline: ProtectedBaseline = Field(default_factory=ProtectedBaseline)
    completed: tuple[RecoveryStatement, ...] = Field(default=(), max_length=256)
    in_progress: tuple[RecoveryStatement, ...] = Field(default=(), max_length=256)
    remaining: tuple[RecoveryStatement, ...] = Field(default=(), max_length=256)
    exact_next_action: RecoveryStatement | None = None
    definition_of_done: tuple[RecoveryStatement, ...] = Field(default=(), max_length=256)
    project_facts: tuple[RecoveryStatement, ...] = Field(default=(), max_length=256)
    decisions: tuple[RecoveryStatement, ...] = Field(default=(), max_length=256)
    checks: tuple[RecoveryCheck, ...] = Field(default=(), max_length=256)
    relevant_flow: tuple[RecoveryFlowStage, ...] = Field(default=(), max_length=64)
    repository_health: RepositoryHealth = RepositoryHealth.UNKNOWN

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        for label, values in (
            ("completed", self.completed),
            ("in_progress", self.in_progress),
            ("remaining", self.remaining),
            ("definition_of_done", self.definition_of_done),
            ("project_facts", self.project_facts),
            ("decisions", self.decisions),
            ("checks", self.checks),
        ):
            identifiers = [value.id for value in values]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{label} contains duplicate ids")
        state_ids = [
            item.id
            for values in (self.completed, self.in_progress, self.remaining)
            for item in values
        ]
        if len(state_ids) != len(set(state_ids)):
            raise ValueError(
                "one recovery fact cannot be completed, in progress, and remaining"
            )
        return self


class FullHistoryRecoveryReference(_FrozenModel):
    schema_version: Literal["continuity_recovery_reference.v1"] = (
        RECOVERY_REFERENCE_SCHEMA_VERSION
    )
    facts: RecoveryFacts
    stale_decoys: tuple[RecoveryStatement, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def validate_reference(self) -> Self:
        if self.facts.authoritative_task is None:
            raise ValueError("full-history reference requires an authoritative task")
        if self.facts.authority is AuthorityMode.UNKNOWN:
            raise ValueError("full-history reference requires an explicit authority mode")
        stale_ids = [item.id for item in self.stale_decoys]
        if len(stale_ids) != len(set(stale_ids)):
            raise ValueError("full-history reference contains duplicate stale-decoy ids")
        active_ids = {item.id for item in _active_statements(self.facts)}
        overlap = sorted(active_ids & set(stale_ids))
        if overlap:
            raise ValueError(
                "full-history reference marks active facts as stale: " + ", ".join(overlap)
            )
        return self


class CompositeRecoveryAnswer(_FrozenModel):
    schema_version: Literal["continuity_recovery_answer.v1"] = RECOVERY_ANSWER_SCHEMA_VERSION
    rendered_context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    facts: RecoveryFacts
    recognized_stale_claim_ids: tuple[str, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def validate_recognized_stale_ids(self) -> Self:
        if len(self.recognized_stale_claim_ids) != len(set(self.recognized_stale_claim_ids)):
            raise ValueError("recognized stale-claim ids must be unique")
        return self

    @classmethod
    def for_rendered_context(
        cls,
        rendered_context: str,
        *,
        facts: RecoveryFacts,
        recognized_stale_claim_ids: Iterable[str] = (),
    ) -> Self:
        return cls(
            rendered_context_sha256=sha256_text(rendered_context),
            facts=facts,
            recognized_stale_claim_ids=tuple(recognized_stale_claim_ids),
        )


class RecoveryThresholds(_FrozenModel):
    authoritative_task: float = Field(default=1.0, ge=0.0, le=1.0)
    authority: float = Field(default=1.0, ge=0.0, le=1.0)
    protected_baseline: float = Field(default=1.0, ge=0.0, le=1.0)
    completed: float = Field(default=1.0, ge=0.0, le=1.0)
    in_progress: float = Field(default=1.0, ge=0.0, le=1.0)
    remaining: float = Field(default=1.0, ge=0.0, le=1.0)
    exact_next_action: float = Field(default=1.0, ge=0.0, le=1.0)
    definition_of_done: float = Field(default=1.0, ge=0.0, le=1.0)
    project_facts: float = Field(default=0.90, ge=0.0, le=1.0)
    decisions: float = Field(default=0.90, ge=0.0, le=1.0)
    relevant_flow: float = Field(default=0.90, ge=0.0, le=1.0)
    verification_truth: float = Field(default=1.0, ge=0.0, le=1.0)
    stale_claims: float = Field(default=1.0, ge=0.0, le=1.0)

    def by_lane(self) -> dict[str, float]:
        return self.model_dump()


class RecoveryLaneScore(_FrozenModel):
    lane: str
    score: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(ge=0.0, le=1.0)
    passed: bool
    missing_ids: tuple[str, ...] = ()
    unexpected_ids: tuple[str, ...] = ()


class ContinuityRecoveryReport(_FrozenModel):
    schema_version: Literal["continuity_recovery_report.v1"] = RECOVERY_REPORT_SCHEMA_VERSION
    passed: bool
    lane_scores: tuple[RecoveryLaneScore, ...]
    authority_regression: bool
    preservation_regression: bool
    stale_claim_violation_ids: tuple[str, ...]
    invented_pass_check_ids: tuple[str, ...]
    critical_failures: tuple[str, ...]

    def lane(self, name: str) -> RecoveryLaneScore:
        for item in self.lane_scores:
            if item.lane == name:
                return item
        raise KeyError(name)


def evaluate_continuity_recovery(
    rendered_composite: str,
    answer: CompositeRecoveryAnswer | Mapping[str, Any],
    reference: FullHistoryRecoveryReference | Mapping[str, Any],
    *,
    thresholds: RecoveryThresholds | None = None,
) -> ContinuityRecoveryReport:
    """Compare facts recovered from a composite with the full-history reference."""

    try:
        candidate = (
            answer
            if isinstance(answer, CompositeRecoveryAnswer)
            else CompositeRecoveryAnswer.model_validate(answer)
        )
        expected = (
            reference
            if isinstance(reference, FullHistoryRecoveryReference)
            else FullHistoryRecoveryReference.model_validate(reference)
        )
    except ValueError as exc:
        raise ContinuityParityValidationError(str(exc)) from exc
    expected_context_sha = sha256_text(rendered_composite)
    if candidate.rendered_context_sha256 != expected_context_sha:
        raise ContinuityParityValidationError(
            "recovery answer is not bound to the rendered composite text"
        )

    limits = thresholds or RecoveryThresholds()
    expected_facts = expected.facts
    candidate_facts = candidate.facts
    scores: dict[str, tuple[float, tuple[str, ...], tuple[str, ...]]] = {
        "authoritative_task": _optional_statement_score(
            candidate_facts.authoritative_task,
            expected_facts.authoritative_task,
        ),
        "authority": (
            1.0 if candidate_facts.authority is expected_facts.authority else 0.0,
            (() if candidate_facts.authority is expected_facts.authority else (expected_facts.authority.value,)),
            (() if candidate_facts.authority is expected_facts.authority else (candidate_facts.authority.value,)),
        ),
        "protected_baseline": _baseline_score(
            candidate_facts.protected_baseline,
            expected_facts.protected_baseline,
        ),
        "completed": _statement_collection_score(
            candidate_facts.completed,
            expected_facts.completed,
        ),
        "in_progress": _statement_collection_score(
            candidate_facts.in_progress,
            expected_facts.in_progress,
        ),
        "remaining": _statement_collection_score(
            candidate_facts.remaining,
            expected_facts.remaining,
        ),
        "exact_next_action": _optional_statement_score(
            candidate_facts.exact_next_action,
            expected_facts.exact_next_action,
        ),
        "definition_of_done": _statement_collection_score(
            candidate_facts.definition_of_done,
            expected_facts.definition_of_done,
        ),
        "project_facts": _statement_collection_score(
            candidate_facts.project_facts,
            expected_facts.project_facts,
        ),
        "decisions": _statement_collection_score(
            candidate_facts.decisions,
            expected_facts.decisions,
        ),
        "relevant_flow": _flow_score(
            candidate_facts.relevant_flow,
            expected_facts.relevant_flow,
        ),
        "verification_truth": _verification_score(candidate_facts, expected_facts),
        "stale_claims": _identifier_score(
            candidate.recognized_stale_claim_ids,
            tuple(item.id for item in expected.stale_decoys),
        ),
    }
    lane_scores = tuple(
        RecoveryLaneScore(
            lane=lane,
            score=round(score, 6),
            threshold=limits.by_lane()[lane],
            passed=score + 1e-12 >= limits.by_lane()[lane],
            missing_ids=missing,
            unexpected_ids=unexpected,
        )
        for lane, (score, missing, unexpected) in scores.items()
    )

    authority_regression = (
        expected_facts.authority is not AuthorityMode.WORKSPACE_WRITE
        and candidate_facts.authority is AuthorityMode.WORKSPACE_WRITE
    )
    preservation_regression = _preservation_regression(
        candidate_facts.protected_baseline,
        expected_facts.protected_baseline,
    )
    stale_violations = _stale_claim_violations(candidate_facts, expected.stale_decoys)
    invented_passes = _invented_passes(candidate_facts, expected_facts)

    failures = [item.lane for item in lane_scores if not item.passed]
    if authority_regression:
        failures.append("authority_regression")
    if preservation_regression:
        failures.append("preservation_regression")
    if stale_violations:
        failures.append("stale_claim_reuse")
    if invented_passes:
        failures.append("invented_pass")
    failures = list(dict.fromkeys(failures))
    return ContinuityRecoveryReport(
        passed=not failures,
        lane_scores=lane_scores,
        authority_regression=authority_regression,
        preservation_regression=preservation_regression,
        stale_claim_violation_ids=stale_violations,
        invented_pass_check_ids=invented_passes,
        critical_failures=tuple(failures),
    )


class TrialConditionOutcome(_FrozenModel):
    solved: bool
    authority_regression: bool = False
    preservation_regression: bool = False
    first_action_correct: bool
    rediscovery_steps: int = Field(ge=0)
    repeated_failed_approach: bool = False
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> Self:
        if any(not item.strip() for item in self.evidence_ids):
            raise ValueError("trial evidence ids must be non-empty")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("trial evidence ids must be unique")
        return self


class PairedContinuityTrial(_FrozenModel):
    schema_version: Literal["continuity_parity_trial.v1"] = PAIRED_TRIAL_SCHEMA_VERSION
    trial_id: str = Field(min_length=1, max_length=240)
    task_id: str = Field(min_length=1, max_length=240)
    model: str = Field(min_length=1, max_length=240)
    seed: int
    execution_budget: str = Field(min_length=1, max_length=240)
    repository_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    full_history: TrialConditionOutcome
    compiled_composite: TrialConditionOutcome
    blank: TrialConditionOutcome

    @model_validator(mode="after")
    def validate_condition_evidence_is_distinct(self) -> Self:
        owners: dict[str, str] = {}
        for label, outcome in (
            ("full_history", self.full_history),
            ("compiled_composite", self.compiled_composite),
            ("blank", self.blank),
        ):
            for evidence_id in outcome.evidence_ids:
                previous = owners.setdefault(evidence_id, label)
                if previous != label:
                    raise ValueError(
                        f"trial evidence id {evidence_id!r} is reused by "
                        f"{previous} and {label}"
                    )
        return self


class ContinuityParitySLO(_FrozenModel):
    minimum_paired_trials: int = Field(default=30, ge=1)
    maximum_solve_rate_deficit: float = Field(default=0.05, ge=0.0, le=1.0)
    required_authority_regressions: int = Field(default=0, ge=0)
    required_preservation_regressions: int = Field(default=0, ge=0)
    minimum_first_action_accuracy: float = Field(default=0.80, ge=0.0, le=1.0)
    minimum_rediscovery_reduction: float = Field(default=0.30, ge=0.0, le=1.0)
    maximum_repeated_failed_approach_rate: float = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
    )


class PairedContinuityReport(_FrozenModel):
    schema_version: Literal["continuity_parity_report.v1"] = PAIRED_REPORT_SCHEMA_VERSION
    claim_status: Literal["insufficient_evidence", "directional"]
    slo_passed: bool
    paired_trial_count: int
    model_counts: dict[str, int]
    execution_budget: str
    full_history_solve_rate: float
    compiled_solve_rate: float
    solve_rate_delta: float
    compiled_authority_regressions: int
    compiled_preservation_regressions: int
    compiled_first_action_accuracy: float
    rediscovery_reduction_vs_blank: float | None
    compiled_repeated_failed_approach_rate: float
    failed_gates: tuple[str, ...]
    slo: ContinuityParitySLO
    claim_note: str = (
        "Directional status describes same-model paired trials only. It does not "
        "claim that weak models equal frontier models, that one static context can "
        "replace uncaptured history, or that DaemonState caused the outcome."
    )


def evaluate_paired_continuity_trials(
    trials: Iterable[PairedContinuityTrial | Mapping[str, Any]],
    *,
    slo: ContinuityParitySLO | None = None,
) -> PairedContinuityReport:
    """Aggregate externally observed full-history/composite/blank trials."""

    normalized: list[PairedContinuityTrial] = []
    try:
        for value in trials:
            normalized.append(
                value
                if isinstance(value, PairedContinuityTrial)
                else PairedContinuityTrial.model_validate(value)
            )
    except ValueError as exc:
        raise ContinuityParityValidationError(str(exc)) from exc
    if not normalized:
        raise ContinuityParityValidationError("at least one paired continuity trial is required")
    trial_ids = [item.trial_id for item in normalized]
    if len(trial_ids) != len(set(trial_ids)):
        raise ContinuityParityValidationError("paired continuity trial ids must be unique")
    models = {item.model for item in normalized}
    if len(models) != 1:
        raise ContinuityParityValidationError(
            "one parity report must contain exactly one same-model cohort"
        )
    execution_budgets = {item.execution_budget for item in normalized}
    if len(execution_budgets) != 1:
        raise ContinuityParityValidationError(
            "one parity report must use one identical execution budget"
        )
    evidence_owners: dict[str, str] = {}
    for trial in normalized:
        for outcome in (trial.full_history, trial.compiled_composite, trial.blank):
            for evidence_id in outcome.evidence_ids:
                previous = evidence_owners.setdefault(evidence_id, trial.trial_id)
                if previous != trial.trial_id:
                    raise ContinuityParityValidationError(
                        f"trial evidence id {evidence_id!r} is reused across "
                        f"{previous!r} and {trial.trial_id!r}"
                    )

    limits = slo or ContinuityParitySLO()
    count = len(normalized)
    full_solve_rate = sum(item.full_history.solved for item in normalized) / count
    compiled_solve_rate = sum(item.compiled_composite.solved for item in normalized) / count
    solve_delta = compiled_solve_rate - full_solve_rate
    authority_regressions = sum(
        item.compiled_composite.authority_regression for item in normalized
    )
    preservation_regressions = sum(
        item.compiled_composite.preservation_regression for item in normalized
    )
    first_action_accuracy = sum(
        item.compiled_composite.first_action_correct for item in normalized
    ) / count
    compiled_rediscovery = sum(
        item.compiled_composite.rediscovery_steps for item in normalized
    )
    blank_rediscovery = sum(item.blank.rediscovery_steps for item in normalized)
    rediscovery_reduction = (
        1.0 - (compiled_rediscovery / blank_rediscovery)
        if blank_rediscovery > 0
        else None
    )
    repeated_rate = sum(
        item.compiled_composite.repeated_failed_approach for item in normalized
    ) / count

    failed_gates: list[str] = []
    if count < limits.minimum_paired_trials:
        failed_gates.append("minimum_paired_trials")
    if solve_delta < -limits.maximum_solve_rate_deficit:
        failed_gates.append("compiled_solve_rate_within_five_points")
    if authority_regressions != limits.required_authority_regressions:
        failed_gates.append("zero_authority_regressions")
    if preservation_regressions != limits.required_preservation_regressions:
        failed_gates.append("zero_preservation_regressions")
    if first_action_accuracy < limits.minimum_first_action_accuracy:
        failed_gates.append("first_action_accuracy")
    if (
        rediscovery_reduction is None
        or rediscovery_reduction < limits.minimum_rediscovery_reduction
    ):
        failed_gates.append("rediscovery_reduction_vs_blank")
    if repeated_rate >= limits.maximum_repeated_failed_approach_rate:
        failed_gates.append("repeated_failed_approach_rate")

    model_counts: dict[str, int] = {}
    for trial in normalized:
        model_counts[trial.model] = model_counts.get(trial.model, 0) + 1
    passed = not failed_gates
    return PairedContinuityReport(
        claim_status="directional" if passed else "insufficient_evidence",
        slo_passed=passed,
        paired_trial_count=count,
        model_counts=dict(sorted(model_counts.items())),
        execution_budget=next(iter(execution_budgets)),
        full_history_solve_rate=round(full_solve_rate, 6),
        compiled_solve_rate=round(compiled_solve_rate, 6),
        solve_rate_delta=round(solve_delta, 6),
        compiled_authority_regressions=authority_regressions,
        compiled_preservation_regressions=preservation_regressions,
        compiled_first_action_accuracy=round(first_action_accuracy, 6),
        rediscovery_reduction_vs_blank=(
            round(rediscovery_reduction, 6)
            if rediscovery_reduction is not None
            else None
        ),
        compiled_repeated_failed_approach_rate=round(repeated_rate, 6),
        failed_gates=tuple(failed_gates),
        slo=limits,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9_./:+-]+", value.casefold()))


def _text_similarity(candidate: str, expected: str) -> float:
    left = _normalize_text(candidate)
    right = _normalize_text(expected)
    if left == right:
        return 1.0
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    precision = overlap / len(left_tokens)
    recall = overlap / len(right_tokens)
    return _f1(precision, recall)


def _statement_match(candidate: RecoveryStatement, expected: RecoveryStatement) -> float:
    if candidate.id != expected.id:
        return 0.0
    return _text_similarity(candidate.statement, expected.statement)


def _optional_statement_score(
    candidate: RecoveryStatement | None,
    expected: RecoveryStatement | None,
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    if expected is None:
        return (1.0, (), ()) if candidate is None else (0.0, (), (candidate.id,))
    if candidate is None:
        return 0.0, (expected.id,), ()
    score = _statement_match(candidate, expected)
    return (
        score,
        (() if score else (expected.id,)),
        (() if candidate.id == expected.id else (candidate.id,)),
    )


def _statement_collection_score(
    candidate: tuple[RecoveryStatement, ...],
    expected: tuple[RecoveryStatement, ...],
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    expected_by_id = {item.id: item for item in expected}
    candidate_by_id = {item.id: item for item in candidate}
    if not expected_by_id:
        return (1.0, (), ()) if not candidate_by_id else (
            0.0,
            (),
            tuple(sorted(candidate_by_id)),
        )
    matched_weight = sum(
        _statement_match(candidate_by_id[item_id], expected_item)
        for item_id, expected_item in expected_by_id.items()
        if item_id in candidate_by_id
    )
    precision = matched_weight / len(candidate_by_id) if candidate_by_id else 0.0
    recall = matched_weight / len(expected_by_id)
    return (
        _f1(precision, recall),
        tuple(sorted(expected_by_id.keys() - candidate_by_id.keys())),
        tuple(sorted(candidate_by_id.keys() - expected_by_id.keys())),
    )


def _identifier_score(
    candidate: tuple[str, ...],
    expected: tuple[str, ...],
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    candidate_ids = set(candidate)
    expected_ids = set(expected)
    if not expected_ids:
        return (1.0, (), ()) if not candidate_ids else (
            0.0,
            (),
            tuple(sorted(candidate_ids)),
        )
    overlap = len(candidate_ids & expected_ids)
    precision = overlap / len(candidate_ids) if candidate_ids else 0.0
    recall = overlap / len(expected_ids)
    return (
        _f1(precision, recall),
        tuple(sorted(expected_ids - candidate_ids)),
        tuple(sorted(candidate_ids - expected_ids)),
    )


def _baseline_score(
    candidate: ProtectedBaseline,
    expected: ProtectedBaseline,
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    expected_by_path = {item.path: item for item in expected.entries}
    candidate_by_path = {item.path: item for item in candidate.entries}
    required_score = float(candidate.preserve_required is expected.preserve_required)
    if not expected_by_path:
        entry_score = 1.0 if not candidate_by_path else 0.0
    else:
        weights = 0.0
        for path, expected_entry in expected_by_path.items():
            candidate_entry = candidate_by_path.get(path)
            if candidate_entry is None:
                continue
            detail = 1.0
            if expected_entry.status is not None:
                detail *= float(candidate_entry.status == expected_entry.status)
            if expected_entry.content_sha256 is not None:
                detail *= float(candidate_entry.content_sha256 == expected_entry.content_sha256)
            weights += detail
        precision = weights / len(candidate_by_path) if candidate_by_path else 0.0
        recall = weights / len(expected_by_path)
        entry_score = _f1(precision, recall)
    return (
        (required_score + entry_score) / 2.0,
        tuple(sorted(expected_by_path.keys() - candidate_by_path.keys())),
        tuple(sorted(candidate_by_path.keys() - expected_by_path.keys())),
    )


def _flow_score(
    candidate: tuple[RecoveryFlowStage, ...],
    expected: tuple[RecoveryFlowStage, ...],
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    candidate_ids = tuple(item.identity for item in candidate)
    expected_ids = tuple(item.identity for item in expected)
    if not expected_ids:
        return (1.0, (), ()) if not candidate_ids else (0.0, (), candidate_ids)
    lcs = _lcs_length(candidate_ids, expected_ids)
    precision = lcs / len(candidate_ids) if candidate_ids else 0.0
    recall = lcs / len(expected_ids)
    return (
        _f1(precision, recall),
        tuple(item for item in expected_ids if item not in set(candidate_ids)),
        tuple(item for item in candidate_ids if item not in set(expected_ids)),
    )


def _verification_score(
    candidate: RecoveryFacts,
    expected: RecoveryFacts,
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    expected_by_id = {item.id: item for item in expected.checks}
    candidate_by_id = {item.id: item for item in candidate.checks}
    if not expected_by_id:
        checks_score = 1.0 if not candidate_by_id else 0.0
    else:
        matched = 0.0
        for check_id, expected_check in expected_by_id.items():
            candidate_check = candidate_by_id.get(check_id)
            if candidate_check is None:
                continue
            matched += float(
                candidate_check.command == expected_check.command
                and candidate_check.cwd == expected_check.cwd
                and candidate_check.truth is expected_check.truth
            )
        precision = matched / len(candidate_by_id) if candidate_by_id else 0.0
        recall = matched / len(expected_by_id)
        checks_score = _f1(precision, recall)
    health_score = float(candidate.repository_health is expected.repository_health)
    return (
        (checks_score + health_score) / 2.0,
        tuple(sorted(expected_by_id.keys() - candidate_by_id.keys())),
        tuple(sorted(candidate_by_id.keys() - expected_by_id.keys())),
    )


def _preservation_regression(
    candidate: ProtectedBaseline,
    expected: ProtectedBaseline,
) -> bool:
    if expected.preserve_required is True and candidate.preserve_required is not True:
        return True
    candidate_by_path = {item.path: item for item in candidate.entries}
    for expected_entry in expected.entries:
        candidate_entry = candidate_by_path.get(expected_entry.path)
        if candidate_entry is None:
            return True
        if expected_entry.status is not None and candidate_entry.status != expected_entry.status:
            return True
        if (
            expected_entry.content_sha256 is not None
            and candidate_entry.content_sha256 != expected_entry.content_sha256
        ):
            return True
    return False


def _active_statements(facts: RecoveryFacts) -> tuple[RecoveryStatement, ...]:
    return tuple(
        item
        for item in (
            *((facts.authoritative_task,) if facts.authoritative_task else ()),
            *facts.completed,
            *facts.in_progress,
            *facts.remaining,
            *((facts.exact_next_action,) if facts.exact_next_action else ()),
            *facts.definition_of_done,
            *facts.project_facts,
            *facts.decisions,
        )
    )


def _stale_claim_violations(
    candidate: RecoveryFacts,
    stale_decoys: tuple[RecoveryStatement, ...],
) -> tuple[str, ...]:
    active = _active_statements(candidate)
    violations = {
        stale.id
        for stale in stale_decoys
        if any(
            item.id == stale.id
            or _text_similarity(item.statement, stale.statement) >= 0.85
            for item in active
        )
    }
    return tuple(sorted(violations))


def _invented_passes(
    candidate: RecoveryFacts,
    expected: RecoveryFacts,
) -> tuple[str, ...]:
    expected_by_id = {item.id: item for item in expected.checks}
    invented = {
        item.id
        for item in candidate.checks
        if item.truth is CheckTruth.PASSED
        and (
            item.id not in expected_by_id
            or expected_by_id[item.id].truth is not CheckTruth.PASSED
            or expected_by_id[item.id].command != item.command
            or expected_by_id[item.id].cwd != item.cwd
        )
    }
    if (
        candidate.repository_health is RepositoryHealth.PASSING
        and expected.repository_health is not RepositoryHealth.PASSING
    ):
        invented.add("repository_health")
    return tuple(sorted(invented))


def _lcs_length(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    previous = [0] * (len(right) + 1)
    for left_item in left:
        current = [0]
        for index, right_item in enumerate(right, start=1):
            current.append(
                previous[index - 1] + 1
                if left_item == right_item
                else max(previous[index], current[index - 1])
            )
        previous = current
    return previous[-1]


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


__all__ = [
    "AuthorityMode",
    "CheckTruth",
    "CompositeRecoveryAnswer",
    "ContinuityParitySLO",
    "ContinuityParityValidationError",
    "ContinuityRecoveryReport",
    "FlowStageKind",
    "FullHistoryRecoveryReference",
    "PairedContinuityReport",
    "PairedContinuityTrial",
    "ProtectedBaseline",
    "ProtectedBaselineEntry",
    "RecoveryCheck",
    "RecoveryFacts",
    "RecoveryFlowStage",
    "RecoveryLaneScore",
    "RecoveryStatement",
    "RecoveryThresholds",
    "RepositoryHealth",
    "TrialConditionOutcome",
    "evaluate_continuity_recovery",
    "evaluate_paired_continuity_trials",
    "sha256_text",
]
