from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.codex_thread_stager import (
    STAGING_DEVELOPER_INSTRUCTIONS,
    CodexThreadStagingError,
    stage_codex_thread,
)


def _fake_codex(
    tmp_path: Path,
    *,
    inject_error: str | None = None,
) -> tuple[Path, Path]:
    trace_path = tmp_path / "requests.jsonl"
    executable = tmp_path / "fake-codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"trace = Path({str(trace_path)!r})\n"
        "\n"
        "def receive():\n"
        "    message = json.loads(sys.stdin.readline())\n"
        "    with trace.open('a', encoding='utf-8') as output:\n"
        "        output.write(json.dumps(message, separators=(',', ':')) + '\\n')\n"
        "    return message\n"
        "\n"
        "def send(message):\n"
        "    print(json.dumps(message, separators=(',', ':')), flush=True)\n"
        "\n"
        "initialize = receive()\n"
        "send({'id': initialize['id'], 'result': {'userAgent': 'fake'}})\n"
        "receive()\n"
        "thread_start = receive()\n"
        "send({'id': thread_start['id'], 'result': {\n"
        "    'thread': {'id': 'thread-waiting-123'},\n"
        "}})\n"
        "inject = receive()\n"
        + (
            f"send({{'id': inject['id'], 'error': "
            f"{{'code': -32000, 'message': {inject_error!r}}}}})\n"
            if inject_error
            else (
                "send({'id': inject['id'], 'result': {}})\n"
                "thread_read = receive()\n"
                "send({'id': thread_read['id'], 'result': {'thread': {\n"
                "    'id': 'thread-waiting-123',\n"
                "    'status': {'type': 'idle'},\n"
                "    'preview': '',\n"
                "    'turns': [],\n"
                "}}})\n"
            )
        ),
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable, trace_path


@pytest.mark.asyncio
async def test_stager_loads_context_and_starts_no_turn(tmp_path: Path) -> None:
    executable, trace_path = _fake_codex(tmp_path)
    context = (
        "## Context\nCurrent state.\n\n"
        "## Direction\nWait for the lead.\n\n"
        "## Execution loop\nInspect → implement → test → fix → verify.\n"
    )

    result = await stage_codex_thread(
        codex_bin=str(executable),
        cwd=str(tmp_path),
        context_message=context,
        model="gpt-5.6-sol",
        effort="xhigh",
    )

    requests = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [request.get("method") for request in requests] == [
        "initialize",
        "initialized",
        "thread/start",
        "thread/inject_items",
        "thread/read",
    ]
    assert all(request.get("method") != "turn/start" for request in requests)
    assert requests[2]["params"] == {
        "cwd": str(tmp_path),
        "sandbox": "workspace-write",
        "approvalPolicy": "on-request",
        "approvalsReviewer": "auto_review",
        "ephemeral": False,
        "developerInstructions": STAGING_DEVELOPER_INSTRUCTIONS,
        "model": "gpt-5.6-sol",
        "config": {"model_reasoning_effort": "xhigh"},
    }
    assert requests[3]["params"] == {
        "threadId": "thread-waiting-123",
        "items": [{
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": context}],
        }],
    }
    assert requests[4]["params"] == {
        "threadId": "thread-waiting-123",
        "includeTurns": True,
    }
    assert result.thread_id == "thread-waiting-123"
    assert result.context_delivery == (
        "thread_history_and_developer_instructions"
    )
    assert result.execution_started is False
    assert result.activation_boundary_verified is True
    assert result.observed_turn_count == 0
    assert len(result.context_sha256) == 64


@pytest.mark.asyncio
async def test_stager_enforces_read_only_task_authority(tmp_path: Path) -> None:
    executable, trace_path = _fake_codex(tmp_path)

    await stage_codex_thread(
        codex_bin=str(executable),
        cwd=str(tmp_path),
        context_message="## Context\nRead-only review.\n",
        filesystem_mode="read_only",
    )

    requests = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert requests[2]["method"] == "thread/start"
    assert requests[2]["params"]["sandbox"] == "read-only"


@pytest.mark.asyncio
async def test_stager_fails_closed_when_context_injection_is_rejected(
    tmp_path: Path,
) -> None:
    executable, trace_path = _fake_codex(
        tmp_path,
        inject_error="thread/inject_items is unavailable",
    )

    with pytest.raises(
        CodexThreadStagingError,
        match="thread/inject_items is unavailable",
    ):
        await stage_codex_thread(
            codex_bin=str(executable),
            cwd=str(tmp_path),
            context_message="## Context\nLoaded.\n",
        )

    requests = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert all(request.get("method") != "turn/start" for request in requests)
