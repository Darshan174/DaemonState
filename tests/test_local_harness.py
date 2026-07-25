from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import AgentRun, ContextPack, RunObservation, SourceDocument, Workspace
from app.services.harness_adapters import provider_environment
from app.services.local_harness import (
    MAX_CONTEXT_STDIN_BYTES,
    LocalHarnessRunner,
    RepositoryStateChangedError,
    TRUNCATED_OUTPUT,
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "harness@example.test")
    _git(root, "config", "user.name", "Harness Test")
    (root / "README.md").write_text("initial\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "initial")
    return root


async def _pack_and_run(
    db_session,
    *,
    verification_commands=None,
    markdown="# Context pack\nUse only the supplied project evidence.\n",
):
    workspace = Workspace(
        id=uuid4(),
        name=f"Harness {uuid4()}",
        slug=f"harness-{uuid4()}",
    )
    db_session.add(workspace)
    await db_session.flush()
    pack = ContextPack(
        id=uuid4(),
        workspace_id=workspace.id,
        objective="Implement the local harness contract",
        markdown=markdown,
        manifest=json.dumps(
            {
                "schema_version": "context_pack.v2",
                "verification": {"commands": verification_commands or []},
            }
        ),
        repo_state_json="{}",
        model_profile="small_local",
    )
    run = AgentRun(
        id=uuid4(),
        workspace_id=workspace.id,
        context_pack_id=pack.id,
        run_key=f"harness-{uuid4()}",
        tool="local-harness-test",
        model="old-model",
        objective=pack.objective,
        status="running",
    )
    db_session.add_all([pack, run])
    await db_session.flush()
    return pack, run


@pytest.mark.asyncio
async def test_runner_refuses_a_stale_pack_before_starting_the_agent(
    db_session,
    tmp_path,
):
    root = _repository(tmp_path)
    pack, run = await _pack_and_run(db_session)
    marker = root / "agent-started.txt"

    with pytest.raises(RepositoryStateChangedError):
        await LocalHarnessRunner(db_session).run(
            context_pack_id=pack.id,
            run_id=run.id,
            repo_path=root,
            command=[
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).write_text('started')",
            ],
            expected_status_fingerprint="stale-pack-fingerprint",
        )

    await db_session.refresh(run)
    assert run.status == "failed"
    assert run.ended_at is not None
    assert not marker.exists()


@pytest.mark.asyncio
async def test_runner_exposes_context_and_persists_observed_evidence(db_session, tmp_path):
    root = _repository(tmp_path)
    (root / "checks").mkdir()
    (root / "checks" / ".keep").write_text("verification cwd\n", encoding="utf-8")
    _git(root, "add", "checks/.keep")
    _git(root, "commit", "-q", "-m", "add verification cwd")
    verification_code = (
        "from pathlib import Path; "
        "Path('verification-ran.txt').write_text('yes'); "
        "print('api_key=verification-secret')"
    )
    verification_command = shlex.join([sys.executable, "-c", verification_code])
    pack, run = await _pack_and_run(
        db_session,
        verification_commands=[
            {
                "id": "V1",
                "command": verification_command,
                "cwd": "checks",
                "required": True,
            }
        ],
    )
    child_code = (
        "import os, sys; from pathlib import Path; "
        "context = Path(sys.argv[1]); "
        "assert context == Path(os.environ['CONTEXT_ENGINE_PACK_PATH']); "
        "assert context.read_text().startswith('# Context pack'); "
        "assert os.environ['CONTEXT_ENGINE_PACK_ID']; "
        "assert os.environ['CONTEXT_ENGINE_RUN_ID']; "
        "Path('worker-change.txt').write_text('implemented'); "
        "print('password=hunter2')"
    )

    result = await LocalHarnessRunner(db_session, output_limit_bytes=1_024).run(
        context_pack_id=pack.id,
        run_id=run.id,
        repo_path=root,
        command=[sys.executable, "-c", child_code, "{context_file}"],
        verify=True,
    )

    assert result.status == "completed"
    assert result.command.exit_code == 0
    assert "password=[redacted]" in result.command.stdout
    assert "hunter2" not in result.command.stdout
    assert result.verification_results[0].result.exit_code == 0
    assert "api_key=[redacted]" in result.verification_results[0].result.stdout
    assert set(result.changed_files) == {"checks/verification-ran.txt", "worker-change.txt"}
    assert result.verification_results[0].cwd == str(root / "checks")
    assert result.repository_before.dirty is False
    assert result.repository_after.dirty is True
    context_path = Path(result.command.argv[-1])
    assert not context_path.exists()

    observations = list(
        await db_session.scalars(
            select(RunObservation)
            .where(RunObservation.agent_run_id == run.id)
            .order_by(RunObservation.created_at, RunObservation.id)
        )
    )
    assert {item.event_type for item in observations} == {
        "command",
        "patch_summary",
        "verification",
        "outcome",
    }
    command_observation = next(item for item in observations if item.event_type == "command")
    command_payload = json.loads(command_observation.payload_json)
    assert command_payload["stdout"].strip() == "password=[redacted]"
    verification_observation = next(
        item for item in observations if item.event_type == "verification"
    )
    assert verification_observation.command == result.verification_results[0].command
    assert "verification-secret" not in verification_observation.command
    assert verification_observation.exit_code == 0
    outcome = next(item for item in observations if item.event_type == "outcome")
    assert json.loads(outcome.payload_json)["status"] == "completed"
    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.base_commit == result.repository_before.head_commit
    assert run.head_commit == result.repository_after.head_commit
    assert run.ended_at is not None

    source_contents = "\n".join(
        await db_session.scalars(
            select(SourceDocument.content).where(
                SourceDocument.source_type == "agent_run_observation",
                SourceDocument.workspace_id == pack.workspace_id,
            )
        )
    )
    assert "hunter2" not in source_contents
    assert "verification-secret" not in source_contents


@pytest.mark.asyncio
async def test_runner_delivers_context_on_stdin_and_closes_the_pipe(
    db_session,
    tmp_path,
):
    root = _repository(tmp_path)
    markdown = "# Context pack\nContinue from the verified checkpoint.\n"
    pack, run = await _pack_and_run(db_session, markdown=markdown)
    child_code = (
        "import sys; from pathlib import Path; "
        "payload = sys.stdin.read(); "
        "assert payload == sys.argv[1]; "
        "assert sys.stdin.read() == ''; "
        "Path('stdin-received.txt').write_text(payload)"
    )

    result = await LocalHarnessRunner(db_session).run(
        context_pack_id=pack.id,
        run_id=run.id,
        repo_path=root,
        command=[sys.executable, "-c", child_code, markdown],
        context_stdin=True,
    )

    assert result.status == "completed"
    assert (root / "stdin-received.txt").read_text(encoding="utf-8") == markdown


@pytest.mark.asyncio
async def test_runner_strips_server_secrets_and_preserves_provider_auth(
    db_session,
    monkeypatch,
    tmp_path,
):
    root = _repository(tmp_path)
    pack, run = await _pack_and_run(db_session)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "provider-auth")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-provider-auth")
    monkeypatch.setenv("DATABASE_URL", "postgresql://server-secret")
    monkeypatch.setenv("SERVER_API_KEY", "server-api-secret")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "connector-secret")
    child_code = (
        "import json, os; from pathlib import Path; "
        "names = ['ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', "
        "'DATABASE_URL', 'SERVER_API_KEY', 'GOOGLE_CLIENT_SECRET']; "
        "Path('child-env.json').write_text(json.dumps("
        "{name: os.environ.get(name) for name in names}))"
    )
    environment = {
        **provider_environment("claude"),
        # The runner keeps the denylist as a second line of defense even if a
        # caller accidentally includes a Context Engine secret.
        "DATABASE_URL": "explicit-server-secret",
    }

    result = await LocalHarnessRunner(db_session).run(
        context_pack_id=pack.id,
        run_id=run.id,
        repo_path=root,
        command=[sys.executable, "-c", child_code],
        extra_env=environment,
    )

    assert result.status == "completed"
    observed = json.loads(
        (root / "child-env.json").read_text(encoding="utf-8")
    )
    assert observed == {
        "ANTHROPIC_API_KEY": "provider-auth",
        "CLAUDE_CODE_OAUTH_TOKEN": "oauth-provider-auth",
        "DATABASE_URL": None,
        "SERVER_API_KEY": None,
        "GOOGLE_CLIENT_SECRET": None,
    }


@pytest.mark.asyncio
async def test_runner_keeps_worker_stdin_closed_by_default(db_session, tmp_path):
    root = _repository(tmp_path)
    pack, run = await _pack_and_run(db_session)
    child_code = (
        "import sys; from pathlib import Path; "
        "Path('stdin-default.txt').write_text(sys.stdin.read())"
    )

    result = await LocalHarnessRunner(db_session).run(
        context_pack_id=pack.id,
        run_id=run.id,
        repo_path=root,
        command=[sys.executable, "-c", child_code],
    )

    assert result.status == "completed"
    assert (root / "stdin-default.txt").read_text(encoding="utf-8") == ""


@pytest.mark.asyncio
async def test_runner_rejects_oversized_context_before_starting_worker(
    db_session,
    tmp_path,
):
    root = _repository(tmp_path)
    pack, run = await _pack_and_run(
        db_session,
        markdown="x" * (MAX_CONTEXT_STDIN_BYTES + 1),
    )

    with pytest.raises(ValueError, match="too large for stdin"):
        await LocalHarnessRunner(db_session).run(
            context_pack_id=pack.id,
            run_id=run.id,
            repo_path=root,
            command=[
                sys.executable,
                "-c",
                "from pathlib import Path; Path('must-not-run').touch()",
            ],
            context_stdin=True,
        )

    assert not (root / "must-not-run").exists()


@pytest.mark.asyncio
async def test_runner_bounds_output_and_verification_is_opt_in(db_session, tmp_path):
    root = _repository(tmp_path)
    verification_code = "from pathlib import Path; Path('should-not-run').touch()"
    pack, run = await _pack_and_run(
        db_session,
        verification_commands=[
            {
                "id": "V1",
                "command": shlex.join([sys.executable, "-c", verification_code]),
                "required": True,
            }
        ],
    )
    child_code = "import sys; print('password=secret ' + ('x' * 10000)); assert sys.argv[2]"

    result = await LocalHarnessRunner(db_session, output_limit_bytes=128).run(
        context_pack_id=pack.id,
        run_id=run.id,
        repo_path=root,
        command=[sys.executable, "-c", child_code, "--api-key", "argv-secret"],
        verify=False,
    )

    assert result.status == "completed"
    assert result.command.stdout_truncated is True
    assert result.command.stdout == TRUNCATED_OUTPUT
    assert "secret" not in result.command.stdout
    assert "argv-secret" not in " ".join(result.command.argv)
    assert result.command.argv[-1] == "[redacted]"
    assert result.verification_results == ()
    assert not (root / "should-not-run").exists()
    event_types = list(
        await db_session.scalars(
            select(RunObservation.event_type).where(RunObservation.agent_run_id == run.id)
        )
    )
    assert "verification" not in event_types
    stored = "\n".join(
        await db_session.scalars(
            select(SourceDocument.content).where(
                SourceDocument.source_type == "agent_run_observation",
                SourceDocument.workspace_id == pack.workspace_id,
            )
        )
    )
    assert "argv-secret" not in stored


@pytest.mark.asyncio
async def test_runner_never_interprets_a_shell_command_string(db_session, tmp_path):
    root = _repository(tmp_path)
    pack, run = await _pack_and_run(db_session)
    sentinel = root / "shell-interpolation-must-not-run"

    result = await LocalHarnessRunner(db_session).run(
        context_pack_id=pack.id,
        run_id=run.id,
        repo_path=root,
        command=[f"touch {sentinel}"],
    )

    assert result.status == "failed"
    assert result.command.exit_code == 127
    assert not sentinel.exists()
    await db_session.refresh(run)
    assert run.status == "failed"


@pytest.mark.asyncio
async def test_runner_rejects_a_run_linked_to_another_pack(db_session, tmp_path):
    root = _repository(tmp_path)
    pack, _ = await _pack_and_run(db_session)
    _, other_run = await _pack_and_run(db_session)

    with pytest.raises(ValueError, match="not linked"):
        await LocalHarnessRunner(db_session).run(
            context_pack_id=pack.id,
            run_id=other_run.id,
            repo_path=root,
            command=[sys.executable, "-c", "raise SystemExit('must not run')"],
        )


@pytest.mark.asyncio
async def test_runner_rejects_verification_cwd_outside_repository(db_session, tmp_path):
    root = _repository(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    pack, run = await _pack_and_run(
        db_session,
        verification_commands=[
            {
                "id": "V1",
                "command": shlex.join([sys.executable, "-c", "print('must not run')"]),
                "cwd": str(outside),
                "required": True,
            }
        ],
    )

    with pytest.raises(ValueError, match="cwd is outside"):
        await LocalHarnessRunner(db_session).run(
            context_pack_id=pack.id,
            run_id=run.id,
            repo_path=root,
            command=[sys.executable, "-c", "from pathlib import Path; Path('child-ran').touch()"],
            verify=True,
        )
    assert not (root / "child-ran").exists()
