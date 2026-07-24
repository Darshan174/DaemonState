from __future__ import annotations

import json
from uuid import uuid4

from app.models import CodeFile, SessionEvent, SourceDocument, Workspace
from app.services.session_ledger import build_session_ledger
from app.services.session_events import NormalizedSessionEvent, persist_session_events


async def test_session_continuity_builds_one_truthful_ledger_per_session(
    client,
    db_session,
) -> None:
    workspace = Workspace(
        id=uuid4(),
        name="Session continuity",
        slug=f"session-continuity-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    db_session.add(CodeFile(
        workspace_id=workspace.id,
        repo_root="/workspace/context-engine",
        path="app.py",
        identity_key=uuid4().hex * 2,
        language="python",
        sha256="5" * 64,
        size=10,
    ))

    first = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:continuity-one",
        content="[USER]\nBuild the resume experience.",
        metadata_json=json.dumps({
            "tool": "codex",
            "session_id": "continuity-one",
            "cwd": "/workspace/context-engine",
            "source_path": "/tmp/continuity-one.jsonl",
            "title": "Resume experience",
        }),
    )
    second = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:continuity-two",
        content="[USER]\nBuild the resume experience.",
        metadata_json=json.dumps({
            "tool": "codex",
            "session_id": "continuity-two",
            "cwd": "/workspace/context-engine",
            "source_path": "/tmp/continuity-two.jsonl",
            "title": "Another resume session",
        }),
    )
    db_session.add_all([first, second])
    await db_session.flush()

    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=first,
        provider="codex",
        session_id="continuity-one",
        events=[
            NormalizedSessionEvent(
                provider_event_id="noise",
                sequence_number=1,
                event_type="runtime_instruction",
                role="user",
                content="<environment_context>workspace data</environment_context>",
            ),
            NormalizedSessionEvent(
                provider_event_id="base",
                sequence_number=2,
                event_type="user_request",
                role="user",
                content="Build the resume experience with one card per session.",
            ),
            NormalizedSessionEvent(
                provider_event_id="progress",
                sequence_number=3,
                event_type="assistant_update",
                role="assistant",
                content=(
                    "Implemented the ledger in frontend/src/pages/RunsPage.jsx. "
                    "We will keep repository comparison read-only. "
                    "The digest uses hashlib.sha256. "
                    "The example name hashlib.sh is not a project path."
                ),
            ),
            NormalizedSessionEvent(
                provider_event_id="compact",
                sequence_number=4,
                event_type="compaction_boundary",
                payload={"window_id": "window-1"},
            ),
            NormalizedSessionEvent(
                provider_event_id="added",
                sequence_number=5,
                event_type="user_request",
                role="user",
                content="Add smooth keyboard-accessible card expansion.",
            ),
            NormalizedSessionEvent(
                provider_event_id="changed",
                sequence_number=6,
                event_type="user_request",
                role="user",
                content="Instead of task cards, use one card per session.",
            ),
            NormalizedSessionEvent(
                provider_event_id="ordinary-remove",
                sequence_number=7,
                event_type="user_request",
                role="user",
                content="Remove the checkpoint label from the card.",
            ),
            NormalizedSessionEvent(
                provider_event_id="removed",
                sequence_number=8,
                event_type="user_request",
                role="user",
                content="Disregard the previous requirement about showing technical IDs.",
            ),
            NormalizedSessionEvent(
                provider_event_id="check",
                sequence_number=9,
                event_type="command_result",
                role="tool",
                content="3 passed",
                payload={"command": "pytest -q tests/test_session_continuity.py", "exit_code": 0},
            ),
            NormalizedSessionEvent(
                provider_event_id="edit",
                sequence_number=10,
                event_type="tool_call",
                role="assistant",
                payload={
                    "tool_name": "apply_patch",
                    "input": (
                        "*** Begin Patch\n"
                        "*** Update File: app/services/observed_edit.py\n"
                        "@@\n"
                        "+hashlib.sh should remain ordinary patch content\n"
                        "*** End Patch"
                    ),
                },
            ),
        ],
    )
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=second,
        provider="codex",
        session_id="continuity-two",
        events=[
            NormalizedSessionEvent(
                provider_event_id="base-2",
                sequence_number=1,
                event_type="user_request",
                role="user",
                content="Build the resume experience with one card per session.",
            ),
        ],
    )
    await db_session.commit()

    response = await client.get(
        "/api/session-continuity",
        params={"workspace_id": str(workspace.id)},
    )
    assert response.status_code == 200
    sessions = response.json()["sessions"]
    assert {(item["provider"], item["session_id"]) for item in sessions} == {
        ("codex", "continuity-one"),
        ("codex", "continuity-two"),
    }

    ledger = next(item for item in sessions if item["session_id"] == "continuity-one")
    assert ledger["schema_version"] == "session_context.v1"
    assert ledger["base"][0]["text"] == (
        "Build the resume experience with one card per session."
    )
    assert any(item["kind"] == "progress" for item in ledger["added"])
    assert any(item["kind"] == "decision" for item in ledger["added"])
    assert any(item["kind"] == "file" for item in ledger["added"])
    assert not any(item["kind"] == "check" for item in ledger["added"])
    assert "frontend/src/pages/RunsPage.jsx" in {
        item["text"] for item in ledger["added"] if item["kind"] == "file"
    }
    assert any(
        item["text"] == "app/services/observed_edit.py"
        and item["truth_state"] == "observed"
        for item in ledger["added"]
    )
    assert any(
        item["text"] == "Remove the checkpoint label from the card."
        for item in ledger["added"]
    )
    assert [item["text"] for item in ledger["changed"]] == [
        "Instead of task cards, use one card per session."
    ]
    assert [item["text"] for item in ledger["removed"]] == [
        "Disregard the previous requirement about showing technical IDs."
    ]
    assert ledger["missing"]["status"] == "unmeasured"
    assert ledger["missing"]["items"] == []
    assert ledger["counts"]["missing"] is None
    assert len(ledger["compactions"]) == 1
    assert "hashlib.sh" not in {
        item["text"] for item in ledger["added"] if item["kind"] == "file"
    }

    uncompacted = next(
        item for item in sessions if item["session_id"] == "continuity-two"
    )
    assert uncompacted["missing"]["status"] == "not_applicable"
    assert uncompacted["missing"]["reason_code"] == "no_compaction_boundary"


async def test_session_continuation_returns_a_reviewable_source_backed_bundle(
    client,
    db_session,
    monkeypatch,
) -> None:
    workspace = Workspace(
        id=uuid4(),
        name="Continuation bundle",
        slug=f"continuation-bundle-{uuid4().hex}",
    )
    source = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:bundle-session",
        content="[USER]\nPreserve the original request.",
        metadata_json=json.dumps({
            "tool": "codex",
            "session_id": "bundle-session",
            "cwd": "/workspace/context-engine",
            "source_path": "/tmp/bundle-session.jsonl",
            "title": "Preserve context",
        }),
    )
    db_session.add_all([
        workspace,
        source,
        CodeFile(
            workspace_id=workspace.id,
            repo_root="/workspace/context-engine",
            path="app.py",
            identity_key=uuid4().hex * 2,
            language="python",
            sha256="6" * 64,
            size=10,
        ),
    ])
    await db_session.flush()
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=source,
        provider="codex",
        session_id="bundle-session",
        events=[
            NormalizedSessionEvent(
                provider_event_id="base",
                sequence_number=1,
                event_type="user_request",
                role="user",
                content="Preserve the original request.",
            ),
            NormalizedSessionEvent(
                provider_event_id="compact",
                sequence_number=2,
                event_type="compaction_boundary",
            ),
        ],
    )
    await db_session.commit()

    monkeypatch.setattr(
        "app.api.session_continuity.launch_harness_session",
        lambda *_args, **_kwargs: {"launched": True, "harness": "Codex"},
    )
    response = await client.post(
        "/api/session-continuity/continue",
        json={
            "workspace_id": str(workspace.id),
            "source_document_id": str(source.id),
            "launch_session": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "session_continuation.v1"
    assert payload["launch"]["launched"] is True
    assert "# Continue with recovered session context" in payload["content"]
    assert "Preserve the original request." in payload["content"]
    assert "Status: unmeasured" in payload["content"]


def test_session_ledger_reports_when_a_section_is_windowed() -> None:
    workspace_id = uuid4()
    source_document_id = uuid4()
    events = [
        SessionEvent(
            id=uuid4(),
            workspace_id=workspace_id,
            source_document_id=source_document_id,
            provider="codex",
            session_id="long-session",
            provider_event_id=f"request-{sequence}",
            sequence_number=sequence,
            event_type="user_request",
            role="user",
            content=(
                "Build the original feature."
                if sequence == 1
                else f"Add independently captured requirement {sequence}."
            ),
            payload_json="{}",
            content_sha256=f"{sequence:064x}",
        )
        for sequence in range(1, 26)
    ]

    ledger = build_session_ledger(events)

    assert ledger["counts"]["added"] == 24
    assert len(ledger["added"]) == 18
    assert ledger["truncated"]["added"] == 6
    assert ledger["added"][0]["text"] == "Add independently captured requirement 8."
