from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import codex_app_server_client


@pytest.mark.asyncio
async def test_app_server_client_sequences_requests_and_normalizes_events(
    tmp_path: Path,
    monkeypatch,
) -> None:
    trace_path = tmp_path / "requests.jsonl"
    fake_codex = tmp_path / "fake-codex"
    fake_codex.write_text(
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
        "    'thread': {'id': 'thread-persisted-123'},\n"
        "}})\n"
        "turn_start = receive()\n"
        "send({'id': turn_start['id'], 'result': {'turn': {'id': 'turn-9'}}})\n"
        "send({'id': 91, 'method': 'item/tool/requestUserInput', 'params': {}})\n"
        "receive()\n"
        "send({'method': 'turn/started', 'params': {\n"
        "    'turn': {'id': 'turn-9'},\n"
        "}})\n"
        "send({'method': 'item/started', 'params': {\n"
        "    'item': {'id': 'item-1', 'type': 'commandExecution'},\n"
        "}})\n"
        "send({'method': 'item/completed', 'params': {\n"
        "    'item': {'id': 'item-2', 'type': 'agentMessage'},\n"
        "}})\n"
        "send({'method': 'turn/completed', 'params': {\n"
        "    'turn': {'id': 'turn-9', 'status': 'completed'},\n"
        "}})\n",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(
        codex_app_server_client,
        "_emit",
        lambda payload: emitted.append(dict(payload)),
    )

    exit_code = await codex_app_server_client._run(
        codex_bin=str(fake_codex),
        cwd=str(tmp_path),
        model="gpt-5.6-sol",
        effort="xhigh",
        prompt="Continue the exact visible task.",
    )

    assert exit_code == 0
    requests = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [request.get("method") for request in requests[:4]] == [
        "initialize",
        "initialized",
        "thread/start",
        "turn/start",
    ]
    assert requests[0]["id"] == codex_app_server_client.INITIALIZE_REQUEST_ID
    assert requests[2] == {
        "method": "thread/start",
        "id": codex_app_server_client.THREAD_START_REQUEST_ID,
        "params": {
            "cwd": str(tmp_path),
            "sandbox": "workspace-write",
            "approvalPolicy": "on-request",
            "approvalsReviewer": "auto_review",
            "ephemeral": False,
            "model": "gpt-5.6-sol",
        },
    }
    assert requests[3] == {
        "method": "turn/start",
        "id": codex_app_server_client.TURN_START_REQUEST_ID,
        "params": {
            "threadId": "thread-persisted-123",
            "cwd": str(tmp_path),
            "approvalPolicy": "on-request",
            "approvalsReviewer": "auto_review",
            "input": [{
                "type": "text",
                "text": "Continue the exact visible task.",
            }],
            "model": "gpt-5.6-sol",
            "effort": "xhigh",
        },
    }
    assert requests[4] == {
        "id": 91,
        "error": {
            "code": -32000,
            "message": (
                "Interactive requests are unavailable during an "
                "automatic continuation."
            ),
        },
    }
    assert emitted == [
        {
            "type": "thread.started",
            "thread_id": "thread-persisted-123",
            "visibility_ready": True,
        },
        {"type": "turn.started", "turn_id": "turn-9"},
        {
            "type": "item.started",
            "item": {"id": "item-1", "type": "command_execution"},
        },
        {
            "type": "item.completed",
            "item": {"id": "item-2", "type": "agent_message"},
        },
        {"type": "turn.completed", "status": "completed"},
    ]
