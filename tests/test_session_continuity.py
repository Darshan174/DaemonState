from __future__ import annotations

import json
from uuid import uuid4

from app.models import CodeFile, SessionEvent, SourceDocument, Workspace
from app.services.session_ledger import build_session_ledger, render_session_ledger_markdown
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
        repo_root="/workspace/daemonstate",
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
            "cwd": "/workspace/daemonstate",
            "source_path": "/tmp/continuity-one.jsonl",
            "title": "Resume experience",
            "updated_at": "2026-07-20T09:00:00Z",
            "source_modified_at": "2026-07-23T09:00:00Z",
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
            "cwd": "/workspace/daemonstate",
            "source_path": "/tmp/continuity-two.jsonl",
            "title": "Another resume session",
            "updated_at": "2026-07-22T09:00:00Z",
            "source_modified_at": "2026-07-21T09:00:00Z",
        }),
    )
    internal = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:internal-assessment",
        content=(
            "[USER]\n"
            + ("Long assessment envelope. " * 1_000)
            + "\nThe following is the Codex agent history whose request action "
            "you are assessing.\n>>> TRANSCRIPT START"
        ),
        metadata_json=json.dumps({
            "tool": "codex",
            "session_id": "internal-assessment",
            "cwd": "/workspace/daemonstate",
            "source_path": "/tmp/internal-assessment.jsonl",
            "title": "Internal assessment",
        }),
    )
    db_session.add_all([first, second, internal])
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
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=internal,
        provider="codex",
        session_id="internal-assessment",
        events=[
            NormalizedSessionEvent(
                provider_event_id="internal-base",
                sequence_number=1,
                event_type="user_request",
                role="user",
                content="Assess the supplied transcript.",
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
    assert not any(item["kind"] == "file" for item in ledger["added"])
    assert not any(item["kind"] == "check" for item in ledger["added"])
    assert "frontend/src/pages/RunsPage.jsx" in {
        item["text"] for item in ledger["files"]
    }
    assert any(
        item["text"] == "app/services/observed_edit.py"
        and item["truth_state"] == "observed"
        for item in ledger["files"]
    )
    assert ledger["counts"]["files"] == 2
    assert ledger["truncated"]["files"] == 0
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
        item["text"] for item in ledger["files"]
    }

    uncompacted = next(
        item for item in sessions if item["session_id"] == "continuity-two"
    )
    assert uncompacted["missing"]["status"] == "not_applicable"
    assert uncompacted["missing"]["reason_code"] == "no_compaction_boundary"

    limited_response = await client.get(
        "/api/session-continuity",
        params={"workspace_id": str(workspace.id), "limit": 1},
    )
    assert limited_response.status_code == 200
    limited_sessions = limited_response.json()["sessions"]
    assert len(limited_sessions) == 1
    assert limited_sessions[0]["session_id"] == "continuity-one"


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
            "cwd": "/workspace/daemonstate",
            "source_path": "/tmp/bundle-session.jsonl",
            "title": "Preserve context",
        }),
    )
    db_session.add_all([
        workspace,
        source,
        CodeFile(
            workspace_id=workspace.id,
            repo_root="/workspace/daemonstate",
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
    assert "## Original request" in payload["content"]
    assert "## Since your request" in payload["content"]
    assert "## Updated requests" in payload["content"]
    assert "## No longer applies" in payload["content"]
    assert "## Context gaps" in payload["content"]
    assert "event 1" not in payload["content"].lower()


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


def test_session_ledger_separates_and_windows_file_evidence() -> None:
    workspace_id = uuid4()
    source_document_id = uuid4()
    events = [
        SessionEvent(
            id=uuid4(),
            workspace_id=workspace_id,
            source_document_id=source_document_id,
            provider="codex",
            session_id="file-heavy-session",
            provider_event_id="base",
            sequence_number=1,
            event_type="user_request",
            role="user",
            content="Build the resume experience.",
            payload_json="{}",
            content_sha256="1" * 64,
        ),
        *[
            SessionEvent(
                id=uuid4(),
                workspace_id=workspace_id,
                source_document_id=source_document_id,
                provider="codex",
                session_id="file-heavy-session",
                provider_event_id=f"file-{sequence}",
                sequence_number=sequence,
                event_type="tool_call",
                role="assistant",
                payload_json=json.dumps({
                    "tool_name": "apply_patch",
                    "input": (
                        "*** Begin Patch\n"
                        f"*** Update File: /workspace/daemonstate/tests/test_{sequence}.py\n"
                        "@@\n"
                        "+updated = True\n"
                        "*** End Patch"
                    ),
                }),
                content_sha256=f"{sequence:064x}",
            )
            for sequence in range(2, 27)
        ],
        SessionEvent(
            id=uuid4(),
            workspace_id=workspace_id,
            source_document_id=source_document_id,
            provider="codex",
            session_id="file-heavy-session",
            provider_event_id="meaningful-progress",
            sequence_number=27,
            event_type="assistant_update",
            role="assistant",
            content="Implemented keyboard navigation for every resume card.",
            payload_json="{}",
            content_sha256="f" * 64,
        ),
    ]

    ledger = build_session_ledger(events)

    assert [item["text"] for item in ledger["added"]] == [
        "Implemented keyboard navigation for every resume card."
    ]
    assert ledger["counts"]["files"] == 25
    assert len(ledger["files"]) == 18
    assert ledger["truncated"]["files"] == 7
    assert ledger["files"][-1]["text"] == (
        "/workspace/daemonstate/tests/test_26.py"
    )
    assert all(item["kind"] == "file" for item in ledger["files"])


def test_session_ledger_filters_low_signal_updates_and_cli_auth_transcripts() -> None:
    workspace_id = uuid4()
    source_document_id = uuid4()

    def event(
        sequence_number: int,
        event_type: str,
        content: str,
        *,
        role: str,
    ) -> SessionEvent:
        return SessionEvent(
            id=uuid4(),
            workspace_id=workspace_id,
            source_document_id=source_document_id,
            provider="codex",
            session_id="signal-session",
            provider_event_id=f"event-{sequence_number}",
            sequence_number=sequence_number,
            event_type=event_type,
            role=role,
            content=content,
            payload_json="{}",
            content_sha256=f"{sequence_number:064x}",
        )

    ledger = build_session_ledger([
        event(1, "user_request", "Improve the resume cards.", role="user"),
        event(
            2,
            "assistant_update",
            (
                "Implemented.\n"
                "Authentication is fixed.\n"
                "Authentication is working.\n"
                "Implemented normalized session events.\n"
                "- Added scoped ledger grouping\n"
                "- Tests passed across backend"
            ),
            role="assistant",
        ),
        event(
            3,
            "user_request",
            (
                "✓ Authentication complete. — gh config set -h github.com "
                "git_protocol https ✓ Configured git protocol ✓ Logged in as "
                "Darshan174! You were already logged in to this account."
            ),
            role="user",
        ),
        event(
            4,
            "user_request",
            "Add keyboard navigation to the expanded ledger.",
            role="user",
        ),
    ])

    assert [item["text"] for item in ledger["added"]] == [
        "Implemented normalized session events.",
        "Added scoped ledger grouping",
        "Tests passed across backend",
        "Add keyboard navigation to the expanded ledger.",
    ]


def test_session_ledger_markdown_uses_user_facing_sections_without_event_numbers() -> None:
    workspace_id = uuid4()
    source_document_id = uuid4()
    events = [
        SessionEvent(
            id=uuid4(),
            workspace_id=workspace_id,
            source_document_id=source_document_id,
            provider="codex",
            session_id="markdown-session",
            provider_event_id="base",
            sequence_number=9,
            event_type="user_request",
            role="user",
            content="Build useful resume cards.",
            payload_json="{}",
            content_sha256="1" * 64,
        ),
        SessionEvent(
            id=uuid4(),
            workspace_id=workspace_id,
            source_document_id=source_document_id,
            provider="codex",
            session_id="markdown-session",
            provider_event_id="progress",
            sequence_number=1771,
            event_type="assistant_update",
            role="assistant",
            content="Implemented meaningful progress summaries.",
            payload_json="{}",
            content_sha256="2" * 64,
        ),
    ]

    content = render_session_ledger_markdown(
        build_session_ledger(events),
        session_title="Resume cards",
    )

    assert "## Original request" in content
    assert "## Since your request" in content
    assert "## Updated requests" in content
    assert "## No longer applies" in content
    assert "## Context gaps" in content
    assert "[You asked] Build useful resume cards." in content
    assert "[Agent reported] Implemented meaningful progress summaries." in content
    assert "event 9" not in content.lower()
    assert "event 1771" not in content.lower()
