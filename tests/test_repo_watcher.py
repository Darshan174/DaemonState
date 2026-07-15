from __future__ import annotations

import asyncio
import hashlib
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import CodeFile, SourceDocument, Workspace
from app.services.repo_watcher import RepositoryWatchError, watch_repository


async def _workspace(session) -> Workspace:
    workspace = Workspace(
        id=uuid4(),
        name=f"Watched project {uuid4().hex}",
        slug=f"watched-{uuid4().hex}",
    )
    session.add(workspace)
    await session.flush()
    return workspace


def _project(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    source = tmp_path / "src" / "worker.py"
    source.write_text("def work():\n    return 1\n", encoding="utf-8")
    return source


async def _watch_documents(session, workspace_id):
    return list(
        await session.scalars(
            select(SourceDocument)
            .where(
                SourceDocument.workspace_id == workspace_id,
                SourceDocument.external_id.like("repo-watch:%"),
            )
            .order_by(SourceDocument.revision_number, SourceDocument.id)
        )
    )


async def test_watch_initial_snapshot_is_source_first_and_restart_is_idempotent(
    db_session, tmp_path
):
    workspace = await _workspace(db_session)
    _project(tmp_path)

    first = await watch_repository(
        db_session,
        repo_path=tmp_path,
        workspace_id=workspace.id,
        debounce_seconds=0,
        once=True,
    )
    second = await watch_repository(
        db_session,
        repo_path=tmp_path,
        workspace_id=workspace.id,
        debounce_seconds=0,
        once=True,
    )

    assert first.cycles == second.cycles == 1
    assert first.changes_detected == first.events_created == 1
    assert second.changes_detected == second.events_created == 0
    assert second.last_snapshot_fingerprint == first.last_snapshot_fingerprint
    documents = await _watch_documents(db_session, workspace.id)
    assert len(documents) == 1
    document = documents[0]
    assert document.source_type == "local_repository"
    assert document.trust_zone == "trusted_repo"
    assert document.source_url is None
    assert document.external_id.endswith(first.last_snapshot_fingerprint)
    payload = json.loads(document.content)
    assert payload["schema_version"] == "repository_event.v1"
    assert payload["event_type"] == "repository_snapshot"
    assert payload["changes"]["added"] == {
        "count": 1,
        "paths": ["src/worker.py"],
    }
    assert str(tmp_path.resolve()) not in document.content
    assert list(
        await db_session.scalars(
            select(CodeFile).where(CodeFile.workspace_id == workspace.id)
        )
    )


async def test_watch_detects_one_changed_snapshot_after_poll(db_session, tmp_path):
    workspace = await _workspace(db_session)
    source = _project(tmp_path)
    slept: list[float] = []

    async def change_after_first_cycle(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 1:
            source.write_text("def work():\n    return 2\n", encoding="utf-8")

    events = []
    result = await watch_repository(
        db_session,
        repo_path=tmp_path,
        workspace_id=workspace.id,
        poll_interval_seconds=0.25,
        debounce_seconds=0,
        max_cycles=2,
        sleep=change_after_first_cycle,
        on_event=events.append,
    )

    assert result.cycles == 2
    assert result.changes_detected == result.events_created == 2
    assert result.stopped_reason == "max_cycles"
    assert slept == [0.25]
    assert [event.event_type for event in events] == [
        "repository_snapshot",
        "repository_change",
    ]
    assert events[-1].files_changed == 1
    documents = await _watch_documents(db_session, workspace.id)
    assert len(documents) == 2
    change = next(
        json.loads(document.content)
        for document in documents
        if json.loads(document.content)["event_type"] == "repository_change"
    )
    assert change["changes"]["changed"] == {
        "count": 1,
        "paths": ["src/worker.py"],
    }
    restarted = await watch_repository(
        db_session,
        repo_path=tmp_path,
        workspace_id=workspace.id,
        debounce_seconds=0,
        once=True,
    )
    assert restarted.changes_detected == restarted.events_created == 0
    assert len(await _watch_documents(db_session, workspace.id)) == 2


async def test_watch_debounces_a_burst_to_the_latest_file_hash(db_session, tmp_path):
    workspace = await _workspace(db_session)
    source = _project(tmp_path)
    await watch_repository(
        db_session,
        repo_path=tmp_path,
        workspace_id=workspace.id,
        debounce_seconds=0,
        once=True,
    )
    source.write_text("def work():\n    return 2\n", encoding="utf-8")

    async def finish_burst(_seconds: float) -> None:
        source.write_text("def work():\n    return 3\n", encoding="utf-8")

    result = await watch_repository(
        db_session,
        repo_path=tmp_path,
        workspace_id=workspace.id,
        debounce_seconds=0.2,
        once=True,
        sleep=finish_burst,
    )

    assert result.changes_detected == result.events_created == 1
    files = list(
        await db_session.scalars(
            select(CodeFile).where(CodeFile.workspace_id == workspace.id)
        )
    )
    assert len(files) == 1
    assert files[0].sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    documents = await _watch_documents(db_session, workspace.id)
    assert len(documents) == 2


async def test_watch_records_deleted_supported_paths(db_session, tmp_path):
    workspace = await _workspace(db_session)
    source = _project(tmp_path)
    await watch_repository(
        db_session,
        repo_path=tmp_path,
        workspace_id=workspace.id,
        debounce_seconds=0,
        once=True,
    )
    source.unlink()
    (tmp_path / "README.md").write_text("Project remains indexable.\n", encoding="utf-8")

    result = await watch_repository(
        db_session,
        repo_path=tmp_path,
        workspace_id=workspace.id,
        debounce_seconds=0,
        once=True,
    )

    assert result.changes_detected == result.events_created == 1
    documents = await _watch_documents(db_session, workspace.id)
    change = next(
        json.loads(document.content)
        for document in documents
        if json.loads(document.content)["event_type"] == "repository_change"
    )
    assert change["changes"]["deleted"] == {
        "count": 1,
        "paths": ["src/worker.py"],
    }
    assert change["changes"]["added"] == {
        "count": 1,
        "paths": ["README.md"],
    }


async def test_watch_omits_secret_paths_and_never_stores_file_content(
    db_session, tmp_path
):
    workspace = await _workspace(db_session)
    source = _project(tmp_path)
    source.write_text(
        "def work():\n    return 'terminal output must not be copied'\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("API_KEY=super-secret-value\n", encoding="utf-8")
    (tmp_path / "credentials.json").write_text(
        '{"password":"another-secret"}', encoding="utf-8"
    )

    await watch_repository(
        db_session,
        repo_path=tmp_path,
        workspace_id=workspace.id,
        debounce_seconds=0,
        once=True,
    )

    document = (await _watch_documents(db_session, workspace.id))[0]
    payload = json.loads(document.content)
    assert payload["changes"]["added"]["count"] == 3
    assert payload["changes"]["added"]["paths"] == ["src/worker.py"]
    assert payload["paths_redacted"] == 2
    for forbidden in (
        ".env",
        "credentials.json",
        "super-secret-value",
        "another-secret",
        "terminal output must not be copied",
        "API_KEY",
        "command",
    ):
        assert forbidden not in document.content


async def test_watch_cancellation_rolls_back_and_propagates(db_session, tmp_path):
    workspace = await _workspace(db_session)
    _project(tmp_path)

    async def cancel(_seconds: float) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await watch_repository(
            db_session,
            repo_path=tmp_path,
            workspace_id=workspace.id,
            debounce_seconds=0,
            max_cycles=2,
            sleep=cancel,
        )

    assert await db_session.get(Workspace, workspace.id) is not None
    assert len(await _watch_documents(db_session, workspace.id)) == 1


async def test_watch_requires_workspace_and_project_root(db_session, tmp_path):
    with pytest.raises(RepositoryWatchError, match="workspace_id is required") as missing:
        await watch_repository(
            db_session,
            repo_path=tmp_path,
            workspace_id="",
            once=True,
        )
    assert missing.value.code == "workspace_required"

    workspace = await _workspace(db_session)
    (tmp_path / "loose.py").write_text("value = 1\n", encoding="utf-8")
    with pytest.raises(RepositoryWatchError) as invalid_root:
        await watch_repository(
            db_session,
            repo_path=tmp_path,
            workspace_id=workspace.id,
            once=True,
        )
    assert invalid_root.value.code == "repo_not_project_root"
