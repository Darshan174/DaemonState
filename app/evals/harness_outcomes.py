from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


EXPERIMENT_LABELS = ("old_alone", "old_with_context_engine", "new_alone")
PAIRWISE_COMPARISONS = (
    ("old_with_context_engine", "old_alone"),
    ("old_with_context_engine", "new_alone"),
    ("old_alone", "new_alone"),
)


class ExperimentValidationError(ValueError):
    pass


@dataclass(frozen=True)
class _ExperimentRow:
    task_id: str
    label: str
    solved: bool
    cost_usd: float | None
    duration_seconds: float | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MetricSummary:
    observed_count: int
    total: float
    mean: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_count": self.observed_count,
            "total": self.total,
            "mean": self.mean,
        }


@dataclass(frozen=True)
class ConditionSummary:
    label: str
    task_count: int
    solved_count: int
    solve_rate: float
    cost_usd: MetricSummary | None
    duration_seconds: MetricSummary | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "task_count": self.task_count,
            "solved_count": self.solved_count,
            "solve_rate": self.solve_rate,
            "cost_usd": self.cost_usd.to_dict() if self.cost_usd else None,
            "duration_seconds": (
                self.duration_seconds.to_dict() if self.duration_seconds else None
            ),
        }


@dataclass(frozen=True)
class PairwiseDelta:
    left_label: str
    right_label: str
    paired_task_count: int
    left_solved_count: int
    right_solved_count: int
    solve_rate_delta: float
    wins: int
    losses: int
    ties: int
    mean_cost_usd_delta: float | None
    cost_paired_count: int
    mean_duration_seconds_delta: float | None
    duration_paired_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_label": self.left_label,
            "right_label": self.right_label,
            "paired_task_count": self.paired_task_count,
            "left_solved_count": self.left_solved_count,
            "right_solved_count": self.right_solved_count,
            "solve_rate_delta": self.solve_rate_delta,
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "cost_usd": {
                "paired_count": self.cost_paired_count,
                "mean_delta": self.mean_cost_usd_delta,
            },
            "duration_seconds": {
                "paired_count": self.duration_paired_count,
                "mean_delta": self.mean_duration_seconds_delta,
            },
        }


@dataclass(frozen=True)
class PairedExperimentReport:
    task_count: int
    claim_status: str
    minimum_directional_tasks: int
    conditions: tuple[ConditionSummary, ...]
    pairwise_deltas: tuple[PairwiseDelta, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "harness_paired_eval.v1",
            "task_count": self.task_count,
            "claim_status": self.claim_status,
            "minimum_directional_tasks": self.minimum_directional_tasks,
            "conditions": [item.to_dict() for item in self.conditions],
            "pairwise_deltas": [item.to_dict() for item in self.pairwise_deltas],
            "claim_note": (
                "These are observed paired differences only. This report does not "
                "establish causality or model parity. Evidence identifiers are "
                "caller-supplied and checked for shape and uniqueness, but are not "
                "resolved against Context Engine storage by this offline evaluator."
            ),
        }


def evaluate_paired_experiment(
    rows: Iterable[Mapping[str, Any]],
    *,
    minimum_directional_tasks: int = 10,
) -> PairedExperimentReport:
    if (
        not isinstance(minimum_directional_tasks, int)
        or isinstance(minimum_directional_tasks, bool)
        or minimum_directional_tasks < 1
    ):
        raise ExperimentValidationError("minimum_directional_tasks must be a positive integer")
    normalized = [_validate_row(row, index=index) for index, row in enumerate(rows)]
    if not normalized:
        raise ExperimentValidationError("at least one experiment row is required")
    evidence_owners: dict[str, tuple[str, str]] = {}
    for row in normalized:
        for evidence_id in row.evidence_ids:
            owner = evidence_owners.setdefault(evidence_id, (row.task_id, row.label))
            if owner != (row.task_id, row.label):
                raise ExperimentValidationError(
                    f"evidence id {evidence_id!r} is reused across experiment rows"
                )

    tasks: dict[str, dict[str, _ExperimentRow]] = {}
    for row in normalized:
        task = tasks.setdefault(row.task_id, {})
        if row.label in task:
            raise ExperimentValidationError(
                f"task {row.task_id!r} has duplicate label {row.label!r}"
            )
        task[row.label] = row
    for task_id, task in sorted(tasks.items()):
        missing = [label for label in EXPERIMENT_LABELS if label not in task]
        if missing:
            raise ExperimentValidationError(
                f"task {task_id!r} is missing paired rows: {', '.join(missing)}"
            )

    ordered_tasks = [tasks[task_id] for task_id in sorted(tasks)]
    conditions = tuple(
        _condition_summary(label, [task[label] for task in ordered_tasks])
        for label in EXPERIMENT_LABELS
    )
    pairwise = tuple(
        _pairwise_delta(
            left_label=left,
            right_label=right,
            tasks=ordered_tasks,
        )
        for left, right in PAIRWISE_COMPARISONS
    )
    claim_status = (
        "directional"
        if len(ordered_tasks) >= minimum_directional_tasks
        else "insufficient_evidence"
    )
    return PairedExperimentReport(
        task_count=len(ordered_tasks),
        claim_status=claim_status,
        minimum_directional_tasks=minimum_directional_tasks,
        conditions=conditions,
        pairwise_deltas=pairwise,
    )


def _validate_row(row: Mapping[str, Any], *, index: int) -> _ExperimentRow:
    if not isinstance(row, Mapping):
        raise ExperimentValidationError(f"row {index} must be an object")
    task_id = _required_text(row.get("task_id"), field=f"row {index} task_id")
    label = _required_text(row.get("label"), field=f"row {index} label")
    if label not in EXPERIMENT_LABELS:
        raise ExperimentValidationError(
            f"row {index} label must be one of: {', '.join(EXPERIMENT_LABELS)}"
        )
    evidence = row.get("outcome_evidence")
    if not isinstance(evidence, Mapping):
        raise ExperimentValidationError(f"row {index} outcome_evidence must be an object")
    completed = _required_bool(evidence, "completed", row_index=index)
    verification_passed = _required_bool(
        evidence, "verification_passed", row_index=index
    )
    blocker_count = evidence.get("unresolved_blockers")
    if (
        not isinstance(blocker_count, int)
        or isinstance(blocker_count, bool)
        or blocker_count < 0
    ):
        raise ExperimentValidationError(
            f"row {index} outcome_evidence.unresolved_blockers must be a non-negative integer"
        )
    raw_evidence_ids = evidence.get("evidence_ids")
    if not isinstance(raw_evidence_ids, list) or not raw_evidence_ids:
        raise ExperimentValidationError(
            f"row {index} outcome_evidence.evidence_ids must be a non-empty list"
        )
    if any(not isinstance(value, str) for value in raw_evidence_ids):
        raise ExperimentValidationError(
            f"row {index} outcome_evidence.evidence_ids must contain strings"
        )
    evidence_ids = tuple(
        _required_text(value, field=f"row {index} evidence_ids")
        for value in raw_evidence_ids
    )
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ExperimentValidationError(
            f"row {index} outcome_evidence.evidence_ids must be unique"
        )
    cost = _optional_number(row.get("cost_usd"), field=f"row {index} cost_usd")
    duration = _optional_number(
        row.get("duration_seconds"), field=f"row {index} duration_seconds"
    )
    return _ExperimentRow(
        task_id=task_id,
        label=label,
        solved=completed and verification_passed and blocker_count == 0,
        cost_usd=cost,
        duration_seconds=duration,
        evidence_ids=evidence_ids,
    )


def _condition_summary(label: str, rows: list[_ExperimentRow]) -> ConditionSummary:
    solved_count = sum(item.solved for item in rows)
    return ConditionSummary(
        label=label,
        task_count=len(rows),
        solved_count=solved_count,
        solve_rate=_rounded(solved_count / len(rows)),
        cost_usd=_metric_summary([item.cost_usd for item in rows]),
        duration_seconds=_metric_summary([item.duration_seconds for item in rows]),
    )


def _pairwise_delta(
    *,
    left_label: str,
    right_label: str,
    tasks: list[dict[str, _ExperimentRow]],
) -> PairwiseDelta:
    left = [task[left_label] for task in tasks]
    right = [task[right_label] for task in tasks]
    left_solved = sum(item.solved for item in left)
    right_solved = sum(item.solved for item in right)
    cost_deltas = [
        left_item.cost_usd - right_item.cost_usd
        for left_item, right_item in zip(left, right, strict=True)
        if left_item.cost_usd is not None and right_item.cost_usd is not None
    ]
    duration_deltas = [
        left_item.duration_seconds - right_item.duration_seconds
        for left_item, right_item in zip(left, right, strict=True)
        if left_item.duration_seconds is not None
        and right_item.duration_seconds is not None
    ]
    return PairwiseDelta(
        left_label=left_label,
        right_label=right_label,
        paired_task_count=len(tasks),
        left_solved_count=left_solved,
        right_solved_count=right_solved,
        solve_rate_delta=_rounded((left_solved - right_solved) / len(tasks)),
        wins=sum(left_item.solved and not right_item.solved for left_item, right_item in zip(left, right, strict=True)),
        losses=sum(not left_item.solved and right_item.solved for left_item, right_item in zip(left, right, strict=True)),
        ties=sum(left_item.solved == right_item.solved for left_item, right_item in zip(left, right, strict=True)),
        mean_cost_usd_delta=_mean(cost_deltas),
        cost_paired_count=len(cost_deltas),
        mean_duration_seconds_delta=_mean(duration_deltas),
        duration_paired_count=len(duration_deltas),
    )


def _metric_summary(values: list[float | None]) -> MetricSummary | None:
    observed = [value for value in values if value is not None]
    if not observed:
        return None
    return MetricSummary(
        observed_count=len(observed),
        total=_rounded(sum(observed)),
        mean=_rounded(sum(observed) / len(observed)),
    )


def _mean(values: list[float]) -> float | None:
    return _rounded(sum(values) / len(values)) if values else None


def _required_text(value: Any, *, field: str) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized:
        raise ExperimentValidationError(f"{field} is required")
    return normalized


def _required_bool(
    evidence: Mapping[str, Any], field: str, *, row_index: int
) -> bool:
    value = evidence.get(field)
    if not isinstance(value, bool):
        raise ExperimentValidationError(
            f"row {row_index} outcome_evidence.{field} must be a boolean"
        )
    return value


def _optional_number(value: Any, *, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExperimentValidationError(f"{field} must be a non-negative number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ExperimentValidationError(f"{field} must be a non-negative finite number")
    return normalized


def _rounded(value: float) -> float:
    return round(value, 6)
