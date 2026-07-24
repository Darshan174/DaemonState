from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.config import settings
from app.models import CodeFile, SourceDocument, Workspace
from app.services.session_events import NormalizedSessionEvent, persist_session_events
from app.services.source_revisions import ingest_source_document_revision
from app.sync.session_resolvers import (
    ResolvedSession,
    SessionDiscoveryResult,
    discover_local_ai_sessions,
)


async def test_library_and_resume_share_the_indexed_project_boundary(
    client,
    db_session,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "context-engine"
    repo.mkdir()
    (repo / ".git").mkdir()
    worktree = tmp_path / "codex-worktrees" / "task" / "context-engine"
    worktree.mkdir(parents=True)
    worktree_git_dir = repo / ".git" / "worktrees" / "task"
    worktree_git_dir.mkdir(parents=True)
    (worktree_git_dir / "commondir").write_text("../..", encoding="utf-8")
    (worktree / ".git").write_text(
        f"gitdir: {worktree_git_dir}\n",
        encoding="utf-8",
    )
    outside = tmp_path / "another-project"
    outside.mkdir()

    workspace = Workspace(
        id=uuid4(),
        name="Scoped session project",
        slug=f"scoped-session-project-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    db_session.add(CodeFile(
        workspace_id=workspace.id,
        repo_root=str(repo),
        path="app.py",
        identity_key=uuid4().hex * 2,
        language="python",
        sha256="1" * 64,
        size=10,
    ))

    def document(provider: str, session_id: str, cwd: Path) -> SourceDocument:
        return SourceDocument(
            workspace_id=workspace.id,
            source_type="agent_session",
            external_id=f"{provider}:session:{session_id}",
            content=f"[USER]\nWork on {session_id}.",
            metadata_json=json.dumps({
                "connector_type": provider,
                "session_id": session_id,
                "cwd": str(cwd),
                "source_path": str(tmp_path / f"{session_id}.jsonl"),
                "title": session_id.replace("-", " ").title(),
            }),
        )

    direct = document("codex", "direct-project", repo)
    observed = document("opencode", "observed-project", outside)
    linked_worktree = document("codex", "linked-worktree", outside)
    unrelated = document("claude", "outside-project", outside)
    db_session.add_all([direct, observed, linked_worktree, unrelated])
    await db_session.flush()

    for item, provider, session_id, event_cwd in (
        (direct, "codex", "direct-project", repo),
        (observed, "opencode", "observed-project", repo),
        (linked_worktree, "codex", "linked-worktree", worktree),
        (unrelated, "claude", "outside-project", outside),
    ):
        await persist_session_events(
            db_session,
            workspace_id=workspace.id,
            source_document=item,
            provider=provider,
            session_id=session_id,
            events=[
                NormalizedSessionEvent(
                    provider_event_id=f"{session_id}:base",
                    sequence_number=1,
                    event_type="user_request",
                    role="user",
                    content=f"Work on {session_id}.",
                ),
                NormalizedSessionEvent(
                    provider_event_id=f"{session_id}:tool",
                    sequence_number=2,
                    event_type="tool_call",
                    role="assistant",
                    payload={
                        "tool_name": "apply_patch",
                        "cwd": str(event_cwd),
                        "input": "*** Begin Patch",
                    },
                ),
            ],
        )
    await db_session.commit()

    library_response = await client.get(
        "/api/session-library",
        params={"workspace_id": str(workspace.id)},
    )
    assert library_response.status_code == 200
    library = library_response.json()
    assert {
        item["session_id"] for item in library["sessions"]
    } == {"direct-project", "observed-project", "linked-worktree"}
    assert library["stats"]["sessions"] == 3
    assert {
        item["connector_type"]: item["session_count"]
        for item in library["harnesses"]
    } == {"codex": 2, "claude": 0, "opencode": 1}

    continuity_response = await client.get(
        "/api/session-continuity",
        params={"workspace_id": str(workspace.id)},
    )
    assert continuity_response.status_code == 200
    assert {
        item["session_id"] for item in continuity_response.json()["sessions"]
    } == {"direct-project", "observed-project", "linked-worktree"}

    for endpoint, method, body in (
        (
            "/api/session-library/selection",
            client.put,
            {
                "workspace_id": str(workspace.id),
                "source_document_id": str(unrelated.id),
            },
        ),
        (
            "/api/session-continuity/continue",
            client.post,
            {
                "workspace_id": str(workspace.id),
                "source_document_id": str(unrelated.id),
                "launch_session": False,
            },
        ),
    ):
        response = await method(endpoint, json=body)
        assert response.status_code == 404


async def test_sync_excludes_sessions_outside_the_selected_project(
    client,
    db_session,
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "selected-project"
    repo.mkdir()
    workspace = Workspace(
        id=uuid4(),
        name="Selected project",
        slug=f"selected-project-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    db_session.add(CodeFile(
        workspace_id=workspace.id,
        repo_root=str(repo),
        path="main.py",
        identity_key=uuid4().hex * 2,
        sha256="2" * 64,
        size=10,
    ))
    await db_session.commit()

    matching = ResolvedSession(
        connector_type="codex",
        session_id="matching",
        content="[USER]\nImplement the selected project.",
        metadata={
            "tool": "codex",
            "cwd": str(repo),
            "source_path": str(tmp_path / "matching.jsonl"),
        },
    )
    observed = ResolvedSession(
        connector_type="claude",
        session_id="observed",
        content="[USER]\nReview the selected project.",
        metadata={
            "tool": "claude",
            "cwd": str(tmp_path),
            "source_path": str(tmp_path / "observed.jsonl"),
        },
        events=[NormalizedSessionEvent(
            provider_event_id="observed:tool",
            sequence_number=1,
            event_type="tool_call",
            payload={"tool_name": "Read", "cwd": str(repo)},
        )],
    )
    outside = ResolvedSession(
        connector_type="opencode",
        session_id="outside",
        content="[USER]\nWork on an unrelated repository.",
        metadata={
            "tool": "opencode",
            "cwd": str(tmp_path / "outside"),
            "source_path": str(tmp_path / "outside.jsonl"),
        },
    )

    monkeypatch.setattr(
        "app.services.session_library.discover_local_ai_sessions",
        lambda _types: [
            SessionDiscoveryResult(connector_type="codex", sessions=[matching]),
            SessionDiscoveryResult(connector_type="claude", sessions=[observed]),
            SessionDiscoveryResult(connector_type="opencode", sessions=[outside]),
        ],
    )

    response = await client.post(
        "/api/session-library/sync",
        json={"workspace_id": str(workspace.id)},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["sync"]["scanned"] == 3
    assert payload["sync"]["discovered"] == 2
    assert payload["sync"]["excluded"] == 1
    assert {
        item["session_id"] for item in payload["library"]["sessions"]
    } == {"matching", "observed"}


async def test_unindexed_project_workspace_fails_closed_during_session_sync(
    client,
    db_session,
    monkeypatch,
) -> None:
    workspace = Workspace(
        id=uuid4(),
        name="Unindexed project",
        slug=f"unindexed-project-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.commit()

    monkeypatch.setattr(
        "app.services.session_library.discover_local_ai_sessions",
        lambda _types: [
            SessionDiscoveryResult(
                connector_type="codex",
                sessions=[ResolvedSession(
                    connector_type="codex",
                    session_id="unscoped-session",
                    content="[USER]\nWork on a local project.",
                    metadata={
                        "tool": "codex",
                        "cwd": "/workspace/unknown-project",
                        "source_path": "/tmp/unscoped-session.jsonl",
                    },
                )],
            ),
        ],
    )

    response = await client.post(
        "/api/session-library/sync",
        json={"workspace_id": str(workspace.id)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sync"]["scanned"] == 1
    assert payload["sync"]["discovered"] == 0
    assert payload["sync"]["excluded"] == 1
    assert payload["library"]["sessions"] == []


async def test_library_and_resume_enforce_session_source_read_grants(
    client,
    db_session,
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "permissioned-project"
    repo.mkdir()
    workspace = Workspace(
        id=uuid4(),
        name="Permissioned project",
        slug=f"permissioned-project-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    db_session.add(CodeFile(
        workspace_id=workspace.id,
        repo_root=str(repo),
        path="app.py",
        identity_key=uuid4().hex * 2,
        language="python",
        sha256="3" * 64,
        size=10,
    ))
    documents = {}
    for principal in ("alice", "bob"):
        result = await ingest_source_document_revision(
            db_session,
            workspace_id=workspace.id,
            source_type="agent_session",
            external_id=f"codex:session:{principal}-session",
            content=f"[USER]\nWork on the {principal} session.",
            metadata_json={
                "connector_type": "codex",
                "session_id": f"{principal}-session",
                "cwd": str(repo),
                "source_path": str(tmp_path / f"{principal}.jsonl"),
            },
            visibility_scope="restricted",
            permission_source="explicit",
            allowed_principal_ids=[principal],
        )
        documents[principal] = result.document
        await persist_session_events(
            db_session,
            workspace_id=workspace.id,
            source_document=result.document,
            provider="codex",
            session_id=f"{principal}-session",
            events=[NormalizedSessionEvent(
                provider_event_id=f"{principal}:base",
                sequence_number=1,
                event_type="user_request",
                role="user",
                content=f"Work on the {principal} session.",
            )],
        )
    await db_session.commit()

    monkeypatch.setattr(
        settings,
        "principal_api_keys",
        json.dumps({
            "alice-token": {
                "principal_id": "alice",
                "workspace_ids": [str(workspace.id)],
            },
        }),
        raising=False,
    )
    headers = {"X-Context-Engine-API-Key": "alice-token"}

    library = await client.get(
        "/api/session-library",
        params={"workspace_id": str(workspace.id)},
        headers=headers,
    )
    assert library.status_code == 200
    assert {
        item["session_id"] for item in library.json()["sessions"]
    } == {"alice-session"}

    continuity = await client.get(
        "/api/session-continuity",
        params={"workspace_id": str(workspace.id)},
        headers=headers,
    )
    assert continuity.status_code == 200
    assert {
        item["session_id"] for item in continuity.json()["sessions"]
    } == {"alice-session"}

    denied_selection = await client.put(
        "/api/session-library/selection",
        json={
            "workspace_id": str(workspace.id),
            "source_document_id": str(documents["bob"].id),
        },
        headers=headers,
    )
    assert denied_selection.status_code == 404


async def test_sample_workspace_never_mixes_in_live_local_sessions(
    client, db_session, monkeypatch
) -> None:
    workspace = Workspace(
        id=uuid4(),
        name="Product Tour",
        slug=f"product-tour-{uuid4().hex}",
        kind="demo",
    )
    document = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:should-stay-out-of-demo",
        content="[USER]\nImplement the real project.\n\n[ASSISTANT]\nWorking on it.",
        metadata_json=json.dumps({
            "session_id": "should-stay-out-of-demo",
            "tool": "codex",
            "source_path": "/tmp/real-session.jsonl",
        }),
    )
    db_session.add_all([workspace, document])
    await db_session.commit()

    def _unexpected_discovery(*_args, **_kwargs):
        raise AssertionError("sample workspaces must not scan local harness history")

    monkeypatch.setattr(
        "app.services.session_library.discover_local_ai_sessions",
        _unexpected_discovery,
    )

    sync_response = await client.post(
        "/api/session-library/sync",
        json={"workspace_id": str(workspace.id)},
    )
    assert sync_response.status_code == 200
    assert sync_response.json()["sync"]["skipped_reason"] == "sample_workspace"
    assert sync_response.json()["library"]["stats"]["sessions"] == 0

    digest_response = await client.get(
        "/api/context/digest",
        params={"workspace_id": str(workspace.id)},
    )
    assert digest_response.status_code == 200
    assert digest_response.json()["activity"]["primary"] is None


def test_codex_discovery_reads_every_local_session_without_ids(tmp_path: Path, monkeypatch) -> None:
    codex_home = tmp_path / "codex-home"
    sessions_dir = codex_home / "sessions" / "2026" / "07" / "18"
    sessions_dir.mkdir(parents=True)
    for index in (1, 2):
        session_id = f"session-{index}"
        path = sessions_dir / f"rollout-{index}.jsonl"
        path.write_text(
            "\n".join([
                json.dumps({
                    "type": "session_meta",
                    "timestamp": f"2026-07-18T0{index}:00:00Z",
                    "payload": {
                        "id": session_id,
                        "cwd": f"/workspace/product-{index}",
                        "model": "gpt-test",
                    },
                }),
                json.dumps({
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "text", "text": f"Plan product {index} launch"}],
                    },
                }),
                json.dumps({
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "phase": "commentary",
                        "content": [{"type": "output_text", "text": "I’m checking the launch files."}],
                    },
                }),
                json.dumps({
                    "type": "compacted",
                    "timestamp": f"2026-07-18T0{index}:30:00Z",
                    "payload": {
                        "window_id": index,
                        "replacement_history": [
                            {"type": "compaction", "encrypted_content": "opaque"},
                        ],
                    },
                }),
                json.dumps({
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "phase": "final_answer",
                        "content": [{"type": "output_text", "text": f"Implemented product {index} launch."}],
                    },
                }),
            ]),
            encoding="utf-8",
        )

    monkeypatch.setattr(settings, "codex_home", str(codex_home))
    result = discover_local_ai_sessions(["codex"])[0]

    assert result.error is None
    assert {item.session_id for item in result.sessions} == {"session-1", "session-2"}
    assert all(item.metadata["topics"] for item in result.sessions)
    assert {item.metadata["agent_reported_summary"] for item in result.sessions} == {
        "Implemented product 1 launch.",
        "Implemented product 2 launch.",
    }
    assert all(
        item.metadata["agent_reported_summary_source"] == "provider_final_answer"
        for item in result.sessions
    )
    assert all(len(item.metadata["compaction_checkpoints"]) == 1 for item in result.sessions)
    assert {item.metadata["compaction_checkpoints"][0]["turn_count"] for item in result.sessions} == {2}
    assert {item.metadata["compaction_checkpoints"][0]["provider"] for item in result.sessions} == {"codex"}


def test_codex_discovery_marks_continued_tasks_as_forks(tmp_path: Path, monkeypatch) -> None:
    codex_home = tmp_path / "codex-home"
    sessions_dir = codex_home / "sessions" / "2026" / "07" / "18"
    sessions_dir.mkdir(parents=True)

    shared_messages = [
        {
            "type": "response_item",
            "payload": {
                "id": "message-shared-user",
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Plan the session library"}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "id": "message-shared-assistant",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "I mapped the library."}],
            },
        },
    ]
    parent_path = sessions_dir / "rollout-parent.jsonl"
    parent_path.write_text("\n".join(json.dumps(item) for item in [
        {
            "type": "session_meta",
            "payload": {
                "id": "parent-session",
                "timestamp": "2026-07-18T08:00:00Z",
                "cwd": "/workspace/context-engine",
                "thread_source": "user",
            },
        },
        *shared_messages,
    ]), encoding="utf-8")
    child_path = sessions_dir / "rollout-child.jsonl"
    child_path.write_text("\n".join(json.dumps(item) for item in [
        {
            "type": "session_meta",
            "payload": {
                "id": "child-session",
                "timestamp": "2026-07-18T09:00:00Z",
                "cwd": "/workspace/context-engine",
                "thread_source": "user",
            },
        },
        *shared_messages,
        {
            "type": "response_item",
            "payload": {
                "id": "message-child-user",
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Continue in a new task"}],
            },
        },
    ]), encoding="utf-8")
    (codex_home / "session_index.jsonl").write_text("\n".join([
        json.dumps({"id": "parent-session", "thread_name": "Session library work"}),
        json.dumps({"id": "child-session", "thread_name": "Session library work"}),
        json.dumps({"id": "child-session", "thread_name": "Session library work (2)"}),
    ]), encoding="utf-8")

    monkeypatch.setattr(settings, "codex_home", str(codex_home))
    sessions = discover_local_ai_sessions(["codex"])[0].sessions
    child = next(item for item in sessions if item.session_id == "child-session")

    assert child.metadata["title"] == "Session library work (2)"
    assert child.metadata["forked_from_session_id"] == "parent-session"
    assert child.metadata["forked_from_title"] == "Session library work"
    assert "_provider_message_ids" not in child.metadata


def test_codex_parser_preserves_commands_results_and_compaction_boundaries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    codex_home = tmp_path / "codex-home"
    sessions_dir = codex_home / "sessions" / "2026" / "07" / "21"
    sessions_dir.mkdir(parents=True)
    session_id = "checkpoint-session"
    (sessions_dir / "rollout.jsonl").write_text("\n".join([
        json.dumps({
            "type": "session_meta",
            "timestamp": "2026-07-21T08:00:00Z",
            "payload": {"id": session_id, "cwd": "/workspace/product"},
        }),
        json.dumps({
            "type": "response_item",
            "timestamp": "2026-07-21T08:01:00Z",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "text", "text": "Fix checkpoint capture"}],
            },
        }),
        json.dumps({
            "type": "response_item",
            "timestamp": "2026-07-21T08:02:00Z",
            "payload": {
                "type": "custom_tool_call",
                "call_id": "call-1",
                "name": "exec",
                "input": 'await tools.exec_command({cmd: "pytest -q", workdir: "/workspace/product"})',
            },
        }),
        json.dumps({
            "type": "response_item",
            "timestamp": "2026-07-21T08:03:00Z",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "call-1",
                "output": "Script completed\nOutput:\n3 passed",
            },
        }),
        json.dumps({
            "type": "compacted",
            "timestamp": "2026-07-21T08:04:00Z",
            "payload": {"window_id": "window-2", "window_number": 2},
        }),
    ]), encoding="utf-8")
    monkeypatch.setattr(settings, "codex_home", str(codex_home))

    resolved = discover_local_ai_sessions(["codex"])[0].sessions[0]
    by_type = {event.event_type: event for event in resolved.events}

    assert resolved.metadata["compaction_count"] == 1
    assert by_type["command_call"].payload["command"] == "pytest -q"
    assert by_type["command_result"].payload["exit_code"] == 0
    assert by_type["command_result"].payload["passed"] is True
    assert by_type["compaction_boundary"].payload["window_id"] == "window-2"


async def test_library_sync_discovers_ingests_and_groups_sessions(
    client,
    db_session,
    monkeypatch,
) -> None:
    workspace = Workspace(
        id=uuid4(),
        name="Automatic session library",
        slug=f"automatic-session-library-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    db_session.add(CodeFile(
        workspace_id=workspace.id,
        repo_root="/workspace/context-engine",
        path="app.py",
        identity_key=uuid4().hex * 2,
        language="python",
        sha256="4" * 64,
        size=10,
    ))
    await db_session.commit()

    resolved = [
        ResolvedSession(
            connector_type="codex",
            session_id="codex-alpha-beta",
            content=(
                "[USER]\nPlan billing for Alpha.\n\n"
                "[ASSISTANT]\nI mapped the flow.\n\n"
                "[USER]\nReview onboarding for Beta."
            ),
            metadata={
                "tool": "codex",
                "source_path": "/tmp/codex-alpha-beta.jsonl",
                "source_modified_at": "2026-07-18T08:00:00+00:00",
                "cwd": "/workspace/context-engine",
                "title": "Alpha and Beta planning",
                "topics": ["Alpha billing", "Beta onboarding"],
                "compaction_checkpoints": [{
                    "id": "checkpoint-alpha",
                    "kind": "provider_compaction",
                    "provider": "codex",
                    "occurred_at": "2026-07-18T08:30:00Z",
                    "turn_count": 3,
                    "user_turn_count": 2,
                    "assistant_turn_count": 1,
                    "window_id": 1,
                }],
            },
        ),
        ResolvedSession(
            connector_type="codex",
            session_id="codex-release",
            content=(
                "[USER]\nPlan billing for Alpha.\n\n"
                "[ASSISTANT]\nBilling is ready for release."
            ),
            metadata={
                "tool": "codex",
                "source_path": "/tmp/codex-release.jsonl",
                "source_modified_at": "2026-07-18T09:00:00+00:00",
                "cwd": "/workspace/context-engine",
                "title": "Alpha release",
                "topics": ["Alpha billing", "Release readiness"],
                "forked_from_session_id": "codex-alpha-beta",
                "forked_from_title": "Alpha and Beta planning",
            },
        ),
        ResolvedSession(
            connector_type="codex",
            session_id="codex-internal-assessment",
            content=(
                "[USER]\nThe following is the Codex agent history whose request action "
                "you are assessing.\n>>> TRANSCRIPT START\n[1] user: Plan billing for Alpha"
            ),
            metadata={
                "tool": "codex",
                "source_path": "/tmp/codex-internal-assessment.jsonl",
                "source_modified_at": "2026-07-18T10:00:00+00:00",
            },
        ),
    ]

    def _discover(connector_types):
        assert tuple(connector_types) == ("codex", "claude", "opencode")
        return [
            SessionDiscoveryResult(connector_type="codex", sessions=resolved),
            SessionDiscoveryResult(
                connector_type="claude",
                error="Claude project history directory not found",
            ),
            SessionDiscoveryResult(
                connector_type="opencode",
                error="OpenCode database not found",
            ),
        ]

    monkeypatch.setattr(
        "app.services.session_library.discover_local_ai_sessions",
        _discover,
    )

    first = await client.post(
        "/api/session-library/sync",
        json={"workspace_id": str(workspace.id)},
    )
    assert first.status_code == 200
    payload = first.json()
    assert payload["sync"]["automatic"] is True
    assert payload["sync"]["discovered"] == 2
    assert payload["library"]["stats"]["sessions"] == 2
    assert payload["library"]["stats"]["harnesses"] == 1
    assert payload["library"]["stats"]["live_sessions"] == 2
    assert payload["library"]["stats"]["checkpoints"] == 1
    alpha = next(
        topic
        for topic in payload["library"]["topics"]
        if topic["name"] == "Plan billing for Alpha"
    )
    assert alpha["session_count"] == 2
    release_session = next(
        item
        for item in payload["library"]["sessions"]
        if item["session_id"] == "codex-release"
    )
    assert release_session["forked_from"] == {
        "session_id": "codex-alpha-beta",
        "title": "Alpha and Beta planning",
        "source_document_id": next(
            item["source_document_id"]
            for item in payload["library"]["sessions"]
            if item["session_id"] == "codex-alpha-beta"
        ),
    }
    checkpoint_session = next(
        item
        for item in payload["library"]["sessions"]
        if item["session_id"] == "codex-alpha-beta"
    )
    assert checkpoint_session["compaction_checkpoints"] == [{
        "id": "checkpoint-alpha",
        "kind": "provider_compaction",
        "provider": "codex",
        "occurred_at": "2026-07-18T08:30:00Z",
        "turn_count": 3,
        "user_turn_count": 2,
        "assistant_turn_count": 1,
        "window_id": 1,
        "label": "Before context compact",
        "objective": "Review onboarding for Beta.",
        "objective_preview": "Review onboarding for Beta.",
        "agent_state_preview": "I mapped the flow.",
        "restorable": True,
    }]

    restored = await client.post(
        "/api/session-library/checkpoints/restore",
        json={
            "workspace_id": str(workspace.id),
            "source_document_id": checkpoint_session["source_document_id"],
            "checkpoint_id": "checkpoint-alpha",
        },
    )
    assert restored.status_code == 200
    restored_payload = restored.json()
    assert restored_payload["restore_context"]["objective"] == "Review onboarding for Beta."
    assert restored_payload["restore_context"]["earlier_requirements"] == [
        "Plan billing for Alpha."
    ]
    assert restored_payload["restore_context"]["agent_reported_state"] == "I mapped the flow."
    assert "reported state, not verified project truth" in restored_payload["restore_context"]["markdown"]

    second = await client.post(
        "/api/session-library/sync",
        json={"workspace_id": str(workspace.id)},
    )
    assert second.status_code == 200
    assert second.json()["sync"]["unchanged"] == 2

    documents = list(await db_session.scalars(
        select(SourceDocument).where(
            SourceDocument.workspace_id == workspace.id,
            SourceDocument.source_type == "agent_session",
        )
    ))
    assert len(documents) == 2
    chosen_library_session = next(
        item for item in second.json()["library"]["sessions"]
        if item["source_document_id"] == str(documents[0].id)
    )
    chosen_topic = chosen_library_session["latest_topic"]
    assert chosen_topic == chosen_library_session["topics"][-1]

    selected = await client.put(
        "/api/session-library/selection",
        json={
            "workspace_id": str(workspace.id),
            "source_document_id": str(documents[0].id),
        },
    )
    assert selected.status_code == 200
    selected_payload = selected.json()
    assert selected_payload["selection"]["source_document_id"] == str(documents[0].id)
    assert selected_payload["library"]["selection"]["source_document_id"] == str(documents[0].id)
    assert selected_payload["library"]["selection"]["topic"] == chosen_topic
    selected_sessions = [
        item for item in selected_payload["library"]["sessions"]
        if item["selected_for_now"]
    ]
    assert len(selected_sessions) == 1
    assert selected_sessions[0]["source_document_id"] == str(documents[0].id)
    assert selected_sessions[0]["selected_topic"] == chosen_topic

    cleared = await client.delete(
        "/api/session-library/selection",
        params={"workspace_id": str(workspace.id)},
    )
    assert cleared.status_code == 200
    assert cleared.json()["cleared"] is True
    assert cleared.json()["selection"] is None
    assert cleared.json()["library"]["selection"] is None
    assert not any(
        item["selected_for_now"]
        for item in cleared.json()["library"]["sessions"]
    )

    launched = {}

    def _launch(connector_type, session_id, *, cwd=None):
        launched.update({
            "connector_type": connector_type,
            "session_id": session_id,
            "cwd": cwd,
        })
        return {
            "launched": True,
            "connector_type": connector_type,
            "harness": "Codex",
            "session_id": session_id,
            "mode": "desktop_app",
            "navigation": "session",
            "exact_session_supported": True,
            "topic_anchor_supported": False,
        }

    monkeypatch.setattr("app.api.session_library.launch_harness_session", _launch)
    opened = await client.post(
        "/api/session-library/open",
        json={
            "workspace_id": str(workspace.id),
            "source_document_id": str(documents[0].id),
            "topic": "Alpha billing",
        },
    )
    assert opened.status_code == 200
    assert opened.json()["launched"] is True
    assert opened.json()["mode"] == "desktop_app"
    assert opened.json()["exact_session_supported"] is True
    assert opened.json()["topic_anchor_supported"] is False
    assert opened.json()["topic"] == "Alpha billing"
    assert launched["connector_type"] == "codex"
    assert launched["session_id"] in {"codex-alpha-beta", "codex-release"}
