from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.evals.harness_outcomes import (
    ExperimentValidationError,
    evaluate_paired_experiment,
)
from app.models import AgentRun, ContextPack, RunObservation, SourceDocument, Workspace
from app.services.harness_outcomes import HarnessOutcomeService


BASE_TIME = datetime(2026, 7, 16, 9, 0, 0)
COMMAND = "pytest -q tests/test_harness_outcomes.py"


async def _pack(
    session,
    workspace,
    *,
    target_model: str,
    model_profile: str,
):
    pack = ContextPack(
        id=uuid4(),
        workspace_id=workspace.id,
        objective="Measure harness outcomes without inferred success",
        target_model=target_model,
        model_profile=model_profile,
        markdown="# Outcome measurement",
        manifest=json.dumps({
            "schema_version": "context_pack.v2",
            "verification": {"commands": [{
                "id": "V1",
                "command": COMMAND,
                "required": True,
            }]},
        }),
        repo_state_json="{}",
        created_at=BASE_TIME,
    )
    session.add(pack)
    await session.flush()
    return pack


async def _run(
    session,
    workspace,
    pack,
    *,
    model: str,
    run_key: str,
    status: str = "completed",
    start_minute: int = 0,
    duration_minutes: int | None = 5,
):
    started_at = BASE_TIME + timedelta(minutes=start_minute)
    run = AgentRun(
        id=uuid4(),
        workspace_id=workspace.id,
        context_pack_id=pack.id,
        run_key=run_key,
        model=model,
        status=status,
        started_at=started_at,
        ended_at=(
            started_at + timedelta(minutes=duration_minutes)
            if duration_minutes is not None
            else None
        ),
    )
    session.add(run)
    await session.flush()
    return run


async def _observation(
    session,
    run,
    *,
    event_type: str,
    event_key: str | None,
    payload: dict,
    minute: int,
    harness_observed: bool = True,
):
    source = SourceDocument(
        id=uuid4(),
        workspace_id=run.workspace_id,
        source_type="agent_run_observation",
        external_id=f"test-observation:{uuid4()}",
        content=json.dumps(payload, sort_keys=True),
        metadata_json=json.dumps(
            {"observed_by": "local_harness"} if harness_observed else {}
        ),
    )
    item = RunObservation(
        id=uuid4(),
        agent_run_id=run.id,
        source_document_id=source.id,
        event_type=event_type,
        event_key=event_key,
        payload_json=json.dumps(payload, sort_keys=True),
        observed_at=BASE_TIME + timedelta(minutes=minute),
        content=payload.get("content"),
        files_json=json.dumps(payload.get("files", [])),
        command=payload.get("command"),
        exit_code=payload.get("exit_code"),
    )
    session.add_all([source, item])
    await session.flush()
    return item


async def test_service_groups_only_structured_observed_outcomes(db_session):
    workspace = Workspace(id=uuid4(), name="Harness outcomes", slug=f"harness-{uuid4()}")
    db_session.add(workspace)
    await db_session.flush()
    old_pack = await _pack(
        db_session,
        workspace,
        target_model="old-target-name-is-not-observed-model",
        model_profile="small_coder_model",
    )
    new_pack = await _pack(
        db_session,
        workspace,
        target_model="new-target",
        model_profile="frontier_coder_model",
    )

    recovered = await _run(
        db_session,
        workspace,
        old_pack,
        model="old-model",
        run_key="recovered",
        start_minute=1,
        duration_minutes=5,
    )
    await _observation(
        db_session,
        recovered,
        event_type="note",
        event_key="ambiguous-note",
        payload={"content": "The test might still be failing."},
        minute=2,
    )
    await _observation(
        db_session,
        recovered,
        event_type="verification",
        event_key="verify-failed",
        payload={"requirement_id": "V1", "command": COMMAND, "exit_code": 1},
        minute=3,
    )
    await _observation(
        db_session,
        recovered,
        event_type="blocker",
        event_key="blocked-test",
        payload={"content": "Focused test is failing."},
        minute=4,
    )
    await _observation(
        db_session,
        recovered,
        event_type="verification",
        event_key="verify-passed",
        payload={"command": COMMAND, "exit_code": 0},
        minute=5,
    )
    await _observation(
        db_session,
        recovered,
        event_type="verification",
        event_key="unrequired-exploratory-failure",
        payload={"command": "ruff check optional.py", "exit_code": 1},
        minute=5,
    )
    await _observation(
        db_session,
        recovered,
        event_type="blocker_resolution",
        event_key="resolve-test",
        payload={"resolves_event_key": "blocked-test"},
        minute=6,
    )
    await _observation(
        db_session,
        recovered,
        event_type="outcome",
        event_key="outcome-recovered",
        payload={
            "status": "completed",
            "summary": "Authentication redirect fixed and verified.",
            "files": ["app/auth.py", "tests/test_auth.py"],
        },
        minute=7,
    )

    failed = await _run(
        db_session,
        workspace,
        old_pack,
        model="old-model",
        run_key="failed",
        start_minute=10,
        duration_minutes=None,
    )
    await _observation(
        db_session,
        failed,
        event_type="verification",
        event_key="verify-failed-final",
        payload={"requirement_id": "V1", "exit_code": 1},
        minute=11,
    )
    await _observation(
        db_session,
        failed,
        event_type="blocker",
        event_key="unresolved",
        payload={"content": "The test remains red."},
        minute=12,
    )
    await _observation(
        db_session,
        failed,
        event_type="outcome",
        event_key="outcome-failed",
        payload={"status": "completed"},
        minute=13,
    )

    incomplete = await _run(
        db_session,
        workspace,
        new_pack,
        model="new-model",
        run_key="incomplete",
        status="failed",
        start_minute=20,
        duration_minutes=2,
    )
    await _observation(
        db_session,
        incomplete,
        event_type="verification",
        event_key="verify-new",
        payload={"requirement_id": "V1", "status": "passed"},
        minute=21,
    )
    await _observation(
        db_session,
        incomplete,
        event_type="outcome",
        event_key="outcome-incomplete",
        payload={"status": "failed"},
        minute=22,
    )

    self_reported = await _run(
        db_session,
        workspace,
        new_pack,
        model="self-reported-model",
        run_key="not-local-harness",
        start_minute=30,
        duration_minutes=1,
    )
    await _observation(
        db_session,
        self_reported,
        event_type="verification",
        event_key="self-reported-pass",
        payload={"requirement_id": "V1", "command": COMMAND, "exit_code": 0},
        minute=31,
        harness_observed=False,
    )
    await _observation(
        db_session,
        self_reported,
        event_type="outcome",
        event_key="self-reported-outcome",
        payload={"status": "completed"},
        minute=32,
        harness_observed=False,
    )

    result = (await HarnessOutcomeService(db_session).summarize(
        workspace_id=workspace.id
    )).to_dict()

    assert result["observed_runs"] == 3
    assert [group["model"] for group in result["groups"]] == ["new-model", "old-model"]
    new_group, old_group = result["groups"]
    assert new_group["model_profile"] == "frontier_coder_model"
    assert new_group["completed_runs"] == 0
    assert new_group["verified_successful_runs"] == 0
    assert new_group["duration"] == {
        "observed_runs": 1,
        "total_seconds": 120.0,
        "average_seconds": 120.0,
    }
    assert old_group["model_profile"] == "small_coder_model"
    assert old_group["observed_runs"] == 2
    assert old_group["completed_runs"] == 2
    assert old_group["verified_successful_runs"] == 1
    assert old_group["failed_verification_runs"] == 1
    assert old_group["unresolved_blocker_runs"] == 1
    assert old_group["duration"] == {
        "observed_runs": 1,
        "total_seconds": 300.0,
        "average_seconds": 300.0,
    }
    assert old_group["evidence"]["verified_successful_run_ids"] == [str(recovered.id)]
    assert old_group["evidence"]["failed_verification_run_ids"] == [str(failed.id)]
    assert result["runs"][0]["run_id"] == str(incomplete.id)
    recovered_result = next(
        item for item in result["runs"] if item["run_id"] == str(recovered.id)
    )
    assert recovered_result["verified_success"] is True
    assert recovered_result["outcome_summary"] == "Authentication redirect fixed and verified."
    assert recovered_result["changed_files"] == ["app/auth.py", "tests/test_auth.py"]
    assert recovered_result["verification"] == {
        "observed": 2,
        "passed": 1,
        "failed": 1,
    }
    assert "parity" not in result
    json.dumps(result)

    restricted = (await HarnessOutcomeService(db_session).summarize(
        workspace_id=workspace.id,
        accessible_source_ids=set(),
    )).to_dict()
    assert restricted["observed_runs"] == 0
    assert restricted["runs"] == []


async def test_run_outcomes_api_returns_workspace_scoped_observed_runs(
    client,
    db_session,
):
    workspace = Workspace(id=uuid4(), name="Run API", slug=f"run-api-{uuid4()}")
    db_session.add(workspace)
    await db_session.flush()
    pack = await _pack(
        db_session,
        workspace,
        target_model="older-model",
        model_profile="small_coder_model",
    )
    run = await _run(
        db_session,
        workspace,
        pack,
        model="older-model",
        run_key="api-run",
    )
    await _observation(
        db_session,
        run,
        event_type="verification",
        event_key="api-verification",
        payload={"requirement_id": "V1", "command": COMMAND, "exit_code": 0},
        minute=2,
    )
    await _observation(
        db_session,
        run,
        event_type="outcome",
        event_key="api-outcome",
        payload={"status": "completed", "summary": "Observed API run completed."},
        minute=3,
    )
    await db_session.commit()

    response = await client.get(
        "/api/context/run-outcomes",
        params={"workspace_id": str(workspace.id)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "harness_outcomes.v1"
    assert payload["observed_runs"] == 1
    assert payload["runs"][0]["run_id"] == str(run.id)
    assert payload["runs"][0]["verified_success"] is True


def _evidence(*, completed: bool, passed: bool, blockers: int, evidence_id: str):
    return {
        "completed": completed,
        "verification_passed": passed,
        "unresolved_blockers": blockers,
        "evidence_ids": [evidence_id],
    }


def test_paired_evaluator_reports_observed_deltas_without_parity_claim():
    rows = [
        {
            "task_id": "task-1",
            "label": "old_alone",
            "outcome_evidence": _evidence(
                completed=True, passed=False, blockers=0, evidence_id="old-1"
            ),
            "cost_usd": 10,
            "duration_seconds": 100,
        },
        {
            "task_id": "task-1",
            "label": "old_with_context_engine",
            "outcome_evidence": _evidence(
                completed=True, passed=True, blockers=0, evidence_id="ce-1"
            ),
            "cost_usd": 6,
            "duration_seconds": 80,
        },
        {
            "task_id": "task-1",
            "label": "new_alone",
            "outcome_evidence": _evidence(
                completed=True, passed=True, blockers=0, evidence_id="new-1"
            ),
            "cost_usd": 20,
            "duration_seconds": 60,
        },
        {
            "task_id": "task-2",
            "label": "old_alone",
            "outcome_evidence": _evidence(
                completed=False, passed=True, blockers=0, evidence_id="old-2"
            ),
        },
        {
            "task_id": "task-2",
            "label": "old_with_context_engine",
            "outcome_evidence": _evidence(
                completed=True, passed=True, blockers=1, evidence_id="ce-2"
            ),
            "cost_usd": 4,
            "duration_seconds": 90,
        },
        {
            "task_id": "task-2",
            "label": "new_alone",
            "outcome_evidence": _evidence(
                completed=True, passed=True, blockers=0, evidence_id="new-2"
            ),
            "cost_usd": 18,
            "duration_seconds": 70,
        },
    ]

    result = evaluate_paired_experiment(rows).to_dict()

    assert result["task_count"] == 2
    assert result["claim_status"] == "insufficient_evidence"
    assert [item["solve_rate"] for item in result["conditions"]] == [0.0, 0.5, 1.0]
    context_vs_old = result["pairwise_deltas"][0]
    assert context_vs_old["solve_rate_delta"] == 0.5
    assert (context_vs_old["wins"], context_vs_old["losses"], context_vs_old["ties"]) == (
        1,
        0,
        1,
    )
    assert context_vs_old["cost_usd"] == {"paired_count": 1, "mean_delta": -4.0}
    context_vs_new = result["pairwise_deltas"][1]
    assert context_vs_new["solve_rate_delta"] == -0.5
    assert context_vs_new["cost_usd"] == {"paired_count": 2, "mean_delta": -14.0}
    assert context_vs_new["duration_seconds"] == {
        "paired_count": 2,
        "mean_delta": 20.0,
    }
    assert "does not establish causality or model parity" in result["claim_note"]
    json.dumps(result)

    directional = evaluate_paired_experiment(
        rows, minimum_directional_tasks=2
    ).to_dict()
    assert directional["claim_status"] == "directional"


@pytest.mark.parametrize(
    "rows,error",
    [
        (
            [{"task_id": "task-1", "label": "old_alone"}],
            "outcome_evidence must be an object",
        ),
        (
            [{
                "task_id": "task-1",
                "label": "old_alone",
                "outcome_evidence": _evidence(
                    completed=True, passed=True, blockers=0, evidence_id="old-1"
                ),
            }],
            "missing paired rows",
        ),
        (
            [{
                "task_id": "task-1",
                "label": "invalid",
                "outcome_evidence": _evidence(
                    completed=True, passed=True, blockers=0, evidence_id="bad"
                ),
            }],
            "label must be one of",
        ),
        (
            [{
                "task_id": "task-1",
                "label": "old_alone",
                "outcome_evidence": {
                    **_evidence(
                        completed=True,
                        passed=True,
                        blockers=0,
                        evidence_id="duplicate",
                    ),
                    "evidence_ids": ["duplicate", "duplicate"],
                },
            }],
            "evidence_ids must be unique",
        ),
        (
            [{
                "task_id": "task-1",
                "label": "old_alone",
                "outcome_evidence": {
                    **_evidence(
                        completed=True,
                        passed=True,
                        blockers=0,
                        evidence_id="valid",
                    ),
                    "evidence_ids": [123],
                },
            }],
            "evidence_ids must contain strings",
        ),
    ],
)
def test_paired_evaluator_rejects_missing_or_invalid_outcome_evidence(rows, error):
    with pytest.raises(ExperimentValidationError, match=error):
        evaluate_paired_experiment(rows)
