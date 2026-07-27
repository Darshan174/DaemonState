"""Opt-in end-to-end smoke test for a visible real Codex continuation.

Run with:
DAEMONSTATE_REAL_CODEX_SMOKE=1 \
  pytest -q tests/test_real_codex_continuation.py
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
from app.services.harness_launcher import SESSION_ID_PATTERN
from app.services.session_events import (
    NormalizedSessionEvent,
    persist_session_events,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("DAEMONSTATE_REAL_CODEX_SMOKE") != "1",
    reason=(
        "requires an installed, signed-in Codex CLI, network access, and the "
        "Codex desktop app"
    ),
)


async def test_real_codex_executes_tools_opens_its_task_and_verifies(
    client,
    db_session,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "codex-continuation"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# Real Codex continuation smoke\n",
        encoding="utf-8",
    )
    (repo / "pyproject.toml").write_text(
        "[project]\n"
        "name = 'real-codex-continuation-smoke'\n"
        "version = '0.0.0'\n",
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.pytest_cache/\n",
        encoding="utf-8",
    )
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_continuation.py").write_text(
        "from pathlib import Path\n\n"
        "def test_codex_continuation_marker():\n"
        "    marker = Path('CODEX_CONTINUATION_OK.txt')\n"
        "    assert marker.read_text(encoding='utf-8') == "
        "'daemonstate-codex-continuation-ok\\n'\n",
        encoding="utf-8",
    )
    _initialize_repository(repo)

    workspace = Workspace(
        id=uuid4(),
        name="Real Codex continuation smoke",
        slug=f"real-codex-smoke-{uuid4().hex[:8]}",
    )
    db_session.add(workspace)
    await db_session.flush()
    goal = (
        "Create CODEX_CONTINUATION_OK.txt in the repository root with exactly "
        "the line daemonstate-codex-continuation-ok so the test passes."
    )
    source_session_id = f"real-codex-source-{uuid4().hex}"
    content = (
        f"[USER]\n{goal}\n\n"
        "[ASSISTANT]\nThe marker file has not been created yet."
    )
    source = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id=f"codex:session:{source_session_id}",
        content=content,
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        source_identity_sha256=hashlib.sha256(
            f"{workspace.id}:codex:{source_session_id}".encode()
        ).hexdigest(),
        revision_number=1,
        trust_zone="semi_trusted_tool",
        metadata_json=json.dumps({
            "workspace_id": str(workspace.id),
            "connector_type": "codex",
            "tool": "codex",
            "session_id": source_session_id,
            "cwd": str(repo),
            "title": "Real visible Codex continuation",
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
        session_id=source_session_id,
        events=[
            NormalizedSessionEvent(
                provider_event_id=f"{source_session_id}:user",
                sequence_number=1,
                event_type="user_request",
                role="user",
                content=goal,
                payload={"cwd": str(repo)},
            ),
            NormalizedSessionEvent(
                provider_event_id=f"{source_session_id}:assistant",
                sequence_number=2,
                event_type="assistant_update",
                role="assistant",
                content="The marker file has not been created yet.",
                payload={"cwd": str(repo)},
            ),
        ],
    )
    decoy_goal = "Write DECOY_TASK.txt instead of the requested marker."
    decoy_session_id = f"real-codex-decoy-{uuid4().hex}"
    decoy_content = f"[USER]\n{decoy_goal}\n"
    decoy = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id=f"codex:session:{decoy_session_id}",
        content=decoy_content,
        content_sha256=hashlib.sha256(decoy_content.encode()).hexdigest(),
        source_identity_sha256=hashlib.sha256(
            f"{workspace.id}:codex:{decoy_session_id}".encode()
        ).hexdigest(),
        revision_number=1,
        trust_zone="semi_trusted_tool",
        metadata_json=json.dumps({
            "workspace_id": str(workspace.id),
            "connector_type": "codex",
            "tool": "codex",
            "session_id": decoy_session_id,
            "cwd": str(repo),
            "title": "Newer unrelated Codex session",
            "thread_source": "user",
        }),
    )
    db_session.add(decoy)
    await db_session.flush()
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=decoy,
        provider="codex",
        session_id=decoy_session_id,
        events=[
            NormalizedSessionEvent(
                provider_event_id=f"{decoy_session_id}:user",
                sequence_number=1,
                event_type="user_request",
                role="user",
                content=decoy_goal,
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
            "source_provider": "codex",
            "source_session_id": source_session_id,
            "target_provider": "codex",
            "provider_model": "gpt-5.6-sol",
            "provider_effort": "medium",
            "idempotency_key": f"real-codex-{uuid4().hex}",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    command = body["run"]["command"]
    argv = command["argv"]
    harness_session = body["delivery"]["harness_session"]
    assert body["status"] == "verified_complete", body
    assert body["preparation"]["objective"] == goal
    assert (
        body["preparation"]["execution_contract"]["task"][
            "request_verbatim"
        ]
        == goal
    )
    assert goal in body["preparation"]["execution_prompt"]
    assert body["preparation"]["execution_prompt"].startswith(
        "Complete the immediate task in the current checkout."
    )
    assert body["preparation"]["continuation_execution_id"] == (
        body["run"]["continuation_execution_id"]
    )
    assert body["preparation"]["source_session"]["provider"] == "codex"
    assert body["preparation"]["source_session"]["session_id"] == (
        source_session_id
    )
    assert body["delivery"]["provider"] == "codex"
    assert body["run"]["status"] == "completed"
    assert body["run"]["runtime_bundle_integrity_passed"] is True
    assert body["run"]["preservation_passed"] is True
    assert body["run"]["agent_changed_files"] == [
        "CODEX_CONTINUATION_OK.txt"
    ]
    assert command["exit_code"] == 0
    assert "exec" in argv
    assert "--json" in argv
    assert "app-server" not in argv
    assert harness_session["provider"] == "codex"
    assert SESSION_ID_PATTERN.fullmatch(harness_session["session_id"])
    assert harness_session["launched"] is True
    assert harness_session["navigation_requested"] is True
    assert harness_session["navigation_verified"] is False
    assert (repo / "CODEX_CONTINUATION_OK.txt").read_text(
        encoding="utf-8"
    ) == "daemonstate-codex-continuation-ok\n"
    assert not (repo / "DECOY_TASK.txt").exists()
    assert body["outcome"]["checks"]["status"] == "passed"
    assert body["outcome"]["checks"]["passed"] >= 1
    assert body["outcome"]["verified"] is True
    assert body["outcome"]["mandatory"]["unproven"] == 0


def _initialize_repository(repo: Path) -> None:
    commands = (
        ("init", "-q"),
        ("config", "user.email", "smoke@daemonstate.local"),
        ("config", "user.name", "DaemonState Smoke"),
        ("add", "."),
        ("commit", "-q", "-m", "Initialize real Codex continuation smoke"),
    )
    for command in commands:
        subprocess.run(
            ["git", "-C", str(repo), *command],
            check=True,
            capture_output=True,
            text=True,
        )
