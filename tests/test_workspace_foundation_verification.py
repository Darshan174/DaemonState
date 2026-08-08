from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.models import AgentRun, RunObservation, Workspace
from app.services.repo_indexer import RepoFrame
from app.services.workspace_foundation_verification import (
    MAX_WORKSPACE_VERIFICATION_OBSERVATIONS,
    MAX_WORKSPACE_VERIFICATION_OUTCOMES,
    MAX_WORKSPACE_VERIFICATION_SCAN,
    WORKSPACE_VERIFICATION_EVIDENCE_RULE,
    load_workspace_verification_observations,
)


pytestmark = pytest.mark.anyio

_HEAD = "a" * 40
_CONTENT_SHA = "b" * 64
_NOW = datetime(2026, 8, 6, 8, 30, tzinfo=timezone.utc)


def _frame(root: Path) -> RepoFrame:
    return RepoFrame(
        repo_path=str(root.resolve()),
        branch="main",
        base_commit="9" * 40,
        head_commit=_HEAD,
        dirty=True,
        changed_files=[
            {
                "path": "app/service.py",
                "status": " M",
                "sha256": _CONTENT_SHA,
            }
        ],
        untracked_files=[],
        indexed_files=[],
        package_manifests={},
        recent_commits=[],
        test_files=[],
        manifest_files=[],
        env_files=[],
        last_indexed_at="2026-08-06T08:30:00Z",
        snapshot_fingerprint="c" * 64,
    )


def _repository_after(
    frame: RepoFrame,
    *,
    status_truncated: bool = False,
) -> dict:
    return {
        "root": str(Path(frame.repo_path) / "."),
        "branch": frame.branch,
        "head_commit": frame.head_commit,
        "dirty": frame.dirty,
        "changed_files": sorted(item["path"] for item in frame.changed_files),
        "changed_file_entries": [
            {
                "status": item["status"],
                "xy": item["status"],
                "path": item["path"],
                "sha256": item["sha256"],
            }
            for item in reversed(frame.changed_files)
        ],
        "status_fingerprint": "d" * 64,
        "diff_summary": "1 file changed",
        "status_truncated": status_truncated,
    }


def _payload(event_type: str, **values) -> str:
    payload = {
        "schema_version": "run_observation.v1",
        "event_type": event_type,
        "content": f"{event_type} observation",
        "files": [],
        "command": None,
        "exit_code": None,
    }
    payload.update(values)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _verification_payload(
    *,
    command: str,
    cwd: str,
    exit_code: int,
    timed_out: bool = False,
    stdout: str = "ok\n",
    stderr: str = "",
) -> str:
    return _payload(
        "verification",
        command=command,
        cwd=cwd,
        exit_code=exit_code,
        timed_out=timed_out,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=False,
        stderr_truncated=False,
        argv=["pytest", "-q"],
        duration_ms=25,
    )


async def _workspace(db_session) -> Workspace:
    workspace = Workspace(
        id=uuid4(),
        name="Verification workspace",
        slug=f"verification-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    return workspace


async def _run(
    db_session,
    workspace: Workspace,
    frame: RepoFrame,
    *,
    verifications: list[dict],
    repository_after: dict | None = None,
    outcome_payload: str | None = None,
    outcome_time: datetime = _NOW,
    tool: str = "daemonstate:codex",
) -> tuple[AgentRun, list[RunObservation], RunObservation]:
    run = AgentRun(
        id=uuid4(),
        workspace_id=workspace.id,
        tool=tool,
        branch=frame.branch,
        base_commit=frame.base_commit,
        head_commit=frame.head_commit,
        status="completed",
        started_at=outcome_time - timedelta(minutes=2),
        ended_at=outcome_time,
    )
    db_session.add(run)
    await db_session.flush()

    observations: list[RunObservation] = []
    outcome_results: list[dict] = []
    for index, spec in enumerate(verifications, start=1):
        command = spec.get("command", f"check-{index}")
        cwd = spec.get("cwd", frame.repo_path)
        exit_code = spec.get("exit_code", 0)
        timed_out = spec.get("timed_out", False)
        payload_json = spec.get("payload_json") or _verification_payload(
            command=command,
            cwd=cwd,
            exit_code=exit_code,
            timed_out=timed_out,
            stdout=spec.get("stdout", f"result-{index}\n"),
            stderr=spec.get("stderr", ""),
        )
        observation = RunObservation(
            id=spec.get("id", uuid4()),
            agent_run_id=run.id,
            event_type="verification",
            event_key=f"harness:verification:{index}",
            payload_json=payload_json,
            observed_at=spec.get("observed_at", outcome_time - timedelta(seconds=index + 1)),
            command=spec.get("row_command", command),
            exit_code=spec.get("row_exit_code", exit_code),
        )
        observations.append(observation)
        outcome_results.append(
            {
                "requirement_id": f"R{index}",
                "command": command,
                "cwd": cwd,
                "exit_code": exit_code,
                "timed_out": timed_out,
            }
        )
    db_session.add_all(observations)

    after = repository_after or _repository_after(frame)
    outcome = RunObservation(
        id=uuid4(),
        agent_run_id=run.id,
        event_type="outcome",
        event_key="harness:outcome",
        payload_json=outcome_payload
        or _payload(
            "outcome",
            status="completed",
            head_commit=frame.head_commit,
            verification_results=outcome_results,
            repository_before=after,
            repository_after=after,
            runtime_bundle_integrity_passed=True,
            preservation_passed=True,
            completed_context_item_ids=[],
            addresses_context_item_ids=[],
        ),
        observed_at=outcome_time,
    )
    db_session.add(outcome)
    await db_session.flush()
    return run, observations, outcome


async def test_exact_snapshot_loads_deduplicated_source_bound_verification(
    db_session,
    tmp_path,
):
    frame = _frame(tmp_path)
    workspace = await _workspace(db_session)
    command = "pytest -q tests/test_service.py"
    cwd = str(tmp_path / "tests")
    _run_row, rows, outcome = await _run(
        db_session,
        workspace,
        frame,
        verifications=[
            {
                "command": command,
                "cwd": cwd,
                "stdout": "12 passed\n",
                "observed_at": _NOW - timedelta(seconds=2),
            },
            {
                "command": command,
                "cwd": cwd,
                "stdout": "12 passed\n",
                "observed_at": _NOW - timedelta(seconds=1),
            },
            {
                "command": "npm test",
                "cwd": frame.repo_path,
                "exit_code": 1,
                "stderr": "1 failed\n",
                "observed_at": _NOW - timedelta(seconds=3),
            },
        ],
    )

    loaded = await load_workspace_verification_observations(
        db_session,
        workspace.id,
        frame,
    )

    assert [(item.command, item.cwd, item.exit_code) for item in loaded] == [
        (command, "tests", 0),
        ("npm test", ".", 1),
    ]
    newest_duplicate = rows[1]
    assert loaded[0].run_observation_id == str(newest_duplicate.id)
    assert loaded[0].outcome_observation_id == str(outcome.id)
    assert loaded[0].agent_run_id == str(newest_duplicate.agent_run_id)
    assert loaded[0].evidence_rule == WORKSPACE_VERIFICATION_EVIDENCE_RULE
    assert loaded[0].evidence_id == f"run-observation:{newest_duplicate.id}"
    assert (
        loaded[0].payload_sha256
        == hashlib.sha256(newest_duplicate.payload_json.encode("utf-8")).hexdigest()
    )
    assert len(loaded[0].output_sha256) == 64
    assert loaded[0].observed_at.tzinfo is not None
    with pytest.raises(FrozenInstanceError):
        loaded[0].command = "changed"  # type: ignore[misc]


async def test_stale_head_dirty_status_or_content_bytes_are_not_promoted(
    db_session,
    tmp_path,
):
    frame = _frame(tmp_path)
    workspace = await _workspace(db_session)
    await _run(
        db_session,
        workspace,
        frame,
        verifications=[{"command": "pytest", "cwd": frame.repo_path}],
    )

    stale_frames = (
        replace(frame, head_commit="e" * 40),
        replace(frame, dirty=False, changed_files=[]),
        replace(
            frame,
            changed_files=[
                {
                    "path": "app/service.py",
                    "status": "M ",
                    "sha256": _CONTENT_SHA,
                }
            ],
        ),
        replace(
            frame,
            changed_files=[
                {
                    "path": "app/service.py",
                    "status": " M",
                    "sha256": "f" * 64,
                }
            ],
        ),
    )
    for stale in stale_frames:
        assert (
            await load_workspace_verification_observations(
                db_session,
                workspace.id,
                stale,
            )
            == ()
        )


async def test_current_bytes_bridge_indexer_and_local_harness_hash_contracts(
    db_session,
    tmp_path,
):
    path = tmp_path / "app" / "service.py"
    path.parent.mkdir()
    content = b"def service():\n    return True\n"
    path.write_bytes(content)
    raw_digest = hashlib.sha256(content).hexdigest()
    harness_digest = hashlib.sha256(
        str(len(content)).encode("utf-8") + content + b":complete"
    ).hexdigest()
    frame = replace(
        _frame(tmp_path),
        changed_files=[
            {
                "path": "app/service.py",
                "status": " M",
                "sha256": raw_digest,
            }
        ],
    )
    repository_after = _repository_after(frame)
    repository_after["changed_file_entries"][0]["sha256"] = harness_digest
    workspace = await _workspace(db_session)
    await _run(
        db_session,
        workspace,
        frame,
        verifications=[{"command": "pytest", "cwd": frame.repo_path}],
        repository_after=repository_after,
    )

    loaded = await load_workspace_verification_observations(
        db_session,
        workspace.id,
        frame,
    )
    assert [item.command for item in loaded] == ["pytest"]

    path.write_text("def service():\n    return False\n", encoding="utf-8")
    assert (
        await load_workspace_verification_observations(
            db_session,
            workspace.id,
            frame,
        )
        == ()
    )


async def test_truncated_repository_snapshot_is_not_promoted(db_session, tmp_path):
    frame = _frame(tmp_path)
    workspace = await _workspace(db_session)
    await _run(
        db_session,
        workspace,
        frame,
        verifications=[{"command": "pytest", "cwd": frame.repo_path}],
        repository_after=_repository_after(frame, status_truncated=True),
    )

    assert (
        await load_workspace_verification_observations(
            db_session,
            workspace.id,
            frame,
        )
        == ()
    )


async def test_non_harness_agent_run_cannot_spoof_verification_evidence(
    db_session,
    tmp_path,
):
    frame = _frame(tmp_path)
    workspace = await _workspace(db_session)
    run, _rows, _outcome = await _run(
        db_session,
        workspace,
        frame,
        verifications=[{"command": "pytest", "cwd": frame.repo_path}],
    )
    run.tool = "imported:codex"
    await db_session.flush()

    assert (
        await load_workspace_verification_observations(
            db_session,
            workspace.id,
            frame,
        )
        == ()
    )


async def test_cli_local_harness_shape_is_accepted_but_label_alone_is_not(
    db_session,
    tmp_path,
):
    frame = _frame(tmp_path)
    workspace = await _workspace(db_session)
    await _run(
        db_session,
        workspace,
        frame,
        verifications=[{"command": "pytest -q", "cwd": frame.repo_path}],
        tool="local-harness",
    )

    loaded = await load_workspace_verification_observations(
        db_session,
        workspace.id,
        frame,
    )
    assert [item.command for item in loaded] == ["pytest -q"]

    spoofed_workspace = await _workspace(db_session)
    malformed_outcome = _payload(
        "outcome",
        status="completed",
        verification_results=[
            {
                "command": "pytest -q",
                "cwd": frame.repo_path,
                "exit_code": 0,
                "timed_out": False,
            }
        ],
        repository_after=_repository_after(frame),
    )
    await _run(
        db_session,
        spoofed_workspace,
        frame,
        verifications=[{"command": "pytest -q", "cwd": frame.repo_path}],
        outcome_payload=malformed_outcome,
        tool="local-harness",
    )
    assert (
        await load_workspace_verification_observations(
            db_session,
            spoofed_workspace.id,
            frame,
        )
        == ()
    )


async def test_newer_exact_outcome_without_checks_does_not_eclipse_suite(
    db_session,
    tmp_path,
):
    frame = _frame(tmp_path)
    workspace = await _workspace(db_session)
    await _run(
        db_session,
        workspace,
        frame,
        verifications=[{"command": "pytest -q", "cwd": frame.repo_path}],
        outcome_time=_NOW - timedelta(minutes=2),
    )
    await _run(
        db_session,
        workspace,
        frame,
        verifications=[],
        outcome_time=_NOW,
    )

    loaded = await load_workspace_verification_observations(
        db_session,
        workspace.id,
        frame,
    )
    assert [item.command for item in loaded] == ["pytest -q"]


async def test_malformed_outcome_or_individual_payload_fails_closed(
    db_session,
    tmp_path,
):
    frame = _frame(tmp_path)
    workspace = await _workspace(db_session)
    await _run(
        db_session,
        workspace,
        frame,
        verifications=[],
        outcome_payload="{not-json",
        outcome_time=_NOW - timedelta(minutes=5),
    )
    await _run(
        db_session,
        workspace,
        frame,
        verifications=[
            {
                "command": "pytest",
                "cwd": frame.repo_path,
                "payload_json": _payload(
                    "verification",
                    command="pytest",
                    cwd=frame.repo_path,
                    exit_code=0,
                    timed_out=False,
                    stdout="ok",
                    # Missing stderr and truncation flags is not complete proof.
                ),
            }
        ],
    )

    assert (
        await load_workspace_verification_observations(
            db_session,
            workspace.id,
            frame,
        )
        == ()
    )


@pytest.mark.parametrize("spoof", ["wrong_event_index", "after_outcome"])
async def test_individual_result_must_be_the_outcome_indexed_prior_observation(
    db_session,
    tmp_path,
    spoof,
):
    frame = _frame(tmp_path)
    workspace = await _workspace(db_session)
    _run_row, rows, _outcome = await _run(
        db_session,
        workspace,
        frame,
        verifications=[{"command": "pytest -q", "cwd": frame.repo_path}],
    )
    if spoof == "wrong_event_index":
        rows[0].event_key = "harness:verification:99"
    else:
        rows[0].observed_at = _NOW + timedelta(seconds=1)
    await db_session.flush()

    assert (
        await load_workspace_verification_observations(
            db_session,
            workspace.id,
            frame,
        )
        == ()
    )


async def test_verification_loading_is_deterministic_at_unique_observation_cap(
    db_session,
    tmp_path,
):
    frame = _frame(tmp_path)
    workspace = await _workspace(db_session)
    count = MAX_WORKSPACE_VERIFICATION_OBSERVATIONS
    specs = [
        {
            "command": f"check-{index:02d}",
            "cwd": frame.repo_path,
            "stdout": f"output-{index}",
            "observed_at": _NOW + timedelta(seconds=index),
        }
        for index in reversed(range(count))
    ]
    await _run(
        db_session,
        workspace,
        frame,
        verifications=specs,
        outcome_time=_NOW + timedelta(minutes=2),
    )

    first = await load_workspace_verification_observations(
        db_session,
        workspace.id,
        frame,
    )
    second = await load_workspace_verification_observations(
        db_session,
        workspace.id,
        frame,
    )

    assert first == second
    assert len(first) == MAX_WORKSPACE_VERIFICATION_OBSERVATIONS
    assert [item.command for item in first] == [
        f"check-{index:02d}"
        for index in range(count - 1, count - 1 - MAX_WORKSPACE_VERIFICATION_OBSERVATIONS, -1)
    ]
    assert len({item.evidence_id for item in first}) == len(first)


async def test_unique_observation_overflow_fails_closed(db_session, tmp_path):
    frame = _frame(tmp_path)
    workspace = await _workspace(db_session)
    count = MAX_WORKSPACE_VERIFICATION_OBSERVATIONS + 1
    await _run(
        db_session,
        workspace,
        frame,
        verifications=[
            {
                "command": f"check-{index:02d}",
                "cwd": frame.repo_path,
                "stdout": f"output-{index}",
            }
            for index in range(count)
        ],
        outcome_time=_NOW + timedelta(minutes=2),
    )

    assert (
        await load_workspace_verification_observations(
            db_session,
            workspace.id,
            frame,
        )
        == ()
    )


async def test_outcome_scan_overflow_fails_closed(db_session, tmp_path):
    frame = _frame(tmp_path)
    workspace = await _workspace(db_session)
    for index in range(MAX_WORKSPACE_VERIFICATION_OUTCOMES + 1):
        await _run(
            db_session,
            workspace,
            frame,
            verifications=(
                [{"command": "pytest -q", "cwd": frame.repo_path}]
                if index == MAX_WORKSPACE_VERIFICATION_OUTCOMES
                else []
            ),
            outcome_time=_NOW + timedelta(minutes=index),
        )

    assert (
        await load_workspace_verification_observations(
            db_session,
            workspace.id,
            frame,
        )
        == ()
    )


async def test_verification_row_scan_overflow_fails_closed(db_session, tmp_path):
    frame = _frame(tmp_path)
    workspace = await _workspace(db_session)
    first_count = MAX_WORKSPACE_VERIFICATION_SCAN // 2 + 1
    second_count = MAX_WORKSPACE_VERIFICATION_SCAN + 1 - first_count
    for offset, count in enumerate((first_count, second_count)):
        await _run(
            db_session,
            workspace,
            frame,
            verifications=[
                {
                    "command": "pytest -q",
                    "cwd": frame.repo_path,
                    "stdout": "same output",
                }
                for _index in range(count)
            ],
            outcome_time=_NOW + timedelta(minutes=offset),
        )

    assert (
        await load_workspace_verification_observations(
            db_session,
            workspace.id,
            frame,
        )
        == ()
    )


async def test_missing_session_or_workspace_returns_no_observations(tmp_path):
    frame = _frame(tmp_path)
    assert await load_workspace_verification_observations(None, None, frame) == ()
