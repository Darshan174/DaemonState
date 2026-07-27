"""Opt-in smoke test for the real OpenCode continuation boundary.

Run with:
DAEMONSTATE_REAL_OPENCODE_SMOKE=1 \
  pytest -q tests/test_real_opencode_continuation.py
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app.models import SourceDocument, Workspace
from app.services.harness_adapters import (
    OPENCODE_CONTINUATION_MESSAGE,
    OPENCODE_MODEL_ENV,
)
from app.services.session_events import (
    NormalizedSessionEvent,
    persist_session_events,
)


pytestmark = pytest.mark.skipif(
    (
        os.environ.get("DAEMONSTATE_REAL_OPENCODE_SMOKE") != "1"
        or not os.environ.get(OPENCODE_MODEL_ENV)
    ),
    reason=(
        "requires an installed, authenticated OpenCode CLI, network access, "
        f"and an explicit {OPENCODE_MODEL_ENV}"
    ),
)


async def test_real_opencode_continues_from_the_compiled_context(
    client,
    db_session,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "opencode-continuation"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# Real OpenCode continuation smoke\n",
        encoding="utf-8",
    )
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'real-opencode-continuation-smoke'\nversion = '0.0.0'\n",
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.pytest_cache/\n",
        encoding="utf-8",
    )
    agent_runs = repo / ".agent-runs"
    agent_runs.mkdir()
    (agent_runs / "continuation-task.md").write_text(
        "Historical continuation task evidence must not replace current code.\n",
        encoding="utf-8",
    )
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_continuation.py").write_text(
        "from pathlib import Path\n\n"
        "def test_opencode_continuation_marker():\n"
        "    marker = Path('OPENCODE_CONTINUATION_OK.txt')\n"
        "    assert marker.read_text(encoding='utf-8') == "
        "'daemonstate-opencode-continuation-ok\\n'\n",
        encoding="utf-8",
    )
    nested_fixture_tests = (
        repo
        / "app"
        / "evals"
        / "compiler"
        / "fixture_project"
        / "repo"
        / "tests"
    )
    nested_fixture_tests.mkdir(parents=True)
    (nested_fixture_tests / "test_continuation.py").write_text(
        "from missing_fixture_application import continuation\n",
        encoding="utf-8",
    )
    _initialize_repository(repo)

    workspace = Workspace(
        id=uuid4(),
        name="Real OpenCode continuation smoke",
        slug=f"real-opencode-smoke-{uuid4().hex[:8]}",
    )
    db_session.add(workspace)
    await db_session.flush()
    goal = (
        "Create OPENCODE_CONTINUATION_OK.txt in the repository root with exactly "
        "the line daemonstate-opencode-continuation-ok so the tests pass."
    )
    reaction = (
        "# Files mentioned by the user:\n\n"
        "## Screenshot 2026-07-25 at 19.57.03.png: "
        "/Users/example/Screenshot 2026-07-25 at 19.57.03.png\n\n"
        "## My request for Codex:\n"
        "ARE U FUCKING KIDDING ME U FUCKING PICEC OF SHITE\n"
        "<image name=[Image #1] "
        'path="/Users/example/Screenshot 2026-07-25 at 19.57.03.png"></image>'
    )
    content = (
        f"[USER]\n{goal}\n\n"
        "[ASSISTANT]\nThe marker file is not implemented yet.\n\n"
        f"[USER]\n{reaction}"
    )
    session_id = f"real-opencode-{uuid4().hex}"
    source = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id=f"codex:session:{session_id}",
        content=content,
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        source_identity_sha256=hashlib.sha256(
            f"{workspace.id}:codex:{session_id}".encode()
        ).hexdigest(),
        revision_number=1,
        trust_zone="semi_trusted_tool",
        metadata_json=json.dumps({
            "workspace_id": str(workspace.id),
            "connector_type": "codex",
            "tool": "codex",
            "session_id": session_id,
            "cwd": str(repo),
            "title": "Continuing from AI Infra Components",
            "thread_source": "user",
        }),
    )
    db_session.add(source)
    await db_session.flush()
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=source,
        provider="codex",
        session_id=session_id,
        events=[
            NormalizedSessionEvent(
                provider_event_id=f"{session_id}:user",
                sequence_number=1,
                event_type="user_request",
                role="user",
                content=goal,
                payload={"cwd": str(repo)},
            ),
            NormalizedSessionEvent(
                provider_event_id=f"{session_id}:assistant",
                sequence_number=2,
                event_type="assistant_update",
                role="assistant",
                content="The marker file is not implemented yet.",
                payload={"cwd": str(repo)},
            ),
            NormalizedSessionEvent(
                provider_event_id=f"{session_id}:reaction",
                sequence_number=3,
                event_type="user_request",
                role="user",
                occurred_at="2026-07-25T10:00:00Z",
                content=reaction,
                payload={"cwd": str(repo)},
            ),
        ],
    )
    subagent_session_id = f"real-opencode-subagent-{uuid4().hex}"
    subagent_content = (
        f"[USER]\n{goal}\n\n"
        f"[USER]\n{reaction}\n\n"
        "[ASSISTANT]\nAuditing the failure card."
    )
    subagent_source = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id=f"codex:session:{subagent_session_id}",
        content=subagent_content,
        content_sha256=hashlib.sha256(subagent_content.encode()).hexdigest(),
        source_identity_sha256=hashlib.sha256(
            f"{workspace.id}:codex:{subagent_session_id}".encode()
        ).hexdigest(),
        revision_number=1,
        trust_zone="semi_trusted_tool",
        metadata_json=json.dumps({
            "workspace_id": str(workspace.id),
            "connector_type": "codex",
            "tool": "codex",
            "session_id": subagent_session_id,
            "cwd": str(repo),
            "title": "Continuing from AI Infra Components",
            "thread_source": "subagent",
            "parent_thread_id": session_id,
        }),
    )
    db_session.add(subagent_source)
    await db_session.flush()
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=subagent_source,
        provider="codex",
        session_id=subagent_session_id,
        events=[
            NormalizedSessionEvent(
                provider_event_id=f"{subagent_session_id}:goal",
                sequence_number=1,
                event_type="user_request",
                role="user",
                occurred_at="2026-07-25T11:00:00Z",
                content=goal,
                payload={"cwd": str(repo)},
            ),
            NormalizedSessionEvent(
                provider_event_id=f"{subagent_session_id}:reaction",
                sequence_number=2,
                event_type="user_request",
                role="user",
                occurred_at="2026-07-25T11:00:01Z",
                content=reaction,
                payload={"cwd": str(repo)},
            ),
        ],
    )
    await db_session.commit()

    response = await client.post(
        "/api/continuations",
        json={
            "workspace_id": str(workspace.id),
            "repo_path": str(repo),
            "target_provider": "opencode",
            "idempotency_key": f"real-opencode-{uuid4().hex}",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    command = body["run"]["command"]
    argv = command["argv"]
    assert body["status"] == "verified_complete", body
    assert body["preparation"]["objective"] == goal
    assert body["preparation"]["source_session"]["session_id"] == session_id
    assert "Screenshot 2026" not in body["preparation"]["markdown"]
    assert "PICEC OF SHITE" not in body["preparation"]["markdown"]
    verification_commands = body["preparation"]["manifest"]["verification"]["commands"]
    assert verification_commands
    assert all(
        "fixture_project" not in item["command"]
        for item in verification_commands
    )
    assert body["delivery"]["provider"] == "opencode"
    assert body["run"]["status"] == "completed"
    assert body["run"]["agent_changed_files"] == [
        "OPENCODE_CONTINUATION_OK.txt"
    ]
    assert command["exit_code"] == 0
    assert argv[argv.index("--model") + 1] == os.environ[OPENCODE_MODEL_ENV]
    assert argv.index(OPENCODE_CONTINUATION_MESSAGE) < argv.index("-f")
    assert argv[-2] == "-f"
    assert Path(argv[-1]).name == "context-pack.md"
    assert (repo / "OPENCODE_CONTINUATION_OK.txt").read_text(
        encoding="utf-8"
    ) == "daemonstate-opencode-continuation-ok\n"
    checks = body["outcome"]["checks"]
    assert checks["status"] == "passed"
    assert checks["passed"] >= 1


def _initialize_repository(repo: Path) -> None:
    commands = (
        ("init", "-q"),
        ("config", "user.email", "smoke@daemonstate.local"),
        ("config", "user.name", "DaemonState Smoke"),
        ("add", "."),
        ("commit", "-q", "-m", "Initialize real continuation smoke"),
    )
    for command in commands:
        subprocess.run(
            ["git", "-C", str(repo), *command],
            check=True,
            capture_output=True,
            text=True,
        )
